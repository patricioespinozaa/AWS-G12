"""Orquestación del barrido (``business-logic-model.md``, pasos 3–10).

Planificar (puro) -> tope de solicitudes pendientes -> paquetes con verificación de huella -> llamadas en
paralelo con reintentos, corte de circuito y presupuesto compartido de invocaciones (``--max-llamadas``) ->
validación con un reintento -> persistencia y auditoría incrementales, solicitud a solicitud (C5).

Los hilos solo llaman al modelo y validan. Apenas termina una solicitud, el hilo principal escribe, bajo un
solo candado, su E/S del modelo, sus eventos ``llamada_modelo``, su análisis o fallido, su omisión
(``limite_llamadas`` / ``interrumpido``) y su evento final: una interrupción o una caída a mitad del barrido
no pierde lo ya terminado. El orden de las líneas en los archivos depende de cuándo termina cada solicitud;
lo determinista es el conjunto de registros guardados (los lectores ordenan).

Ctrl+C (C4.8): se detiene el barrido, se cancelan las solicitudes que no empezaron, las llamadas en curso
terminan y se guardan (espera acotada a ``ESPERA_INTERRUPCION`` s; un segundo Ctrl+C no espera más) y cada
solicitud que no terminó queda como ``analisis_omitido`` con motivo ``interrumpido``, que la próxima ejecución
retoma.
"""

from __future__ import annotations

import random
import signal
import threading
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import FrameType
from typing import Any, Final

from hlf_priorizacion.auditoria.registro import RegistroAuditoria, nuevo_ulid
from hlf_priorizacion.contrato.validacion import validar_perfil
from hlf_priorizacion.copiloto.cliente import (
    MAX_REINTENTOS,
    ClienteModelo,
    ErrorModelo,
    ErrorPermisos,
    PeticionModelo,
    RespuestaModelo,
    con_reintentos,
    especificacion_herramienta,
)
from hlf_priorizacion.copiloto.config import ConfigModelo
from hlf_priorizacion.copiloto.modelos import (
    AnalisisFallido,
    Correccion,
    MotivoOmision,
    PaqueteBarrido,
    RegistroAnalisis,
    UsoModelo,
)
from hlf_priorizacion.copiloto.paquete import ErrorHuella, armar_paquete, huella_texto, render_datos
from hlf_priorizacion.copiloto.persistencia import (
    guardar_analisis,
    guardar_fallidos,
    guardar_io,
    leer_cohortes,
    leer_hallazgos_dq,
    ya_analizadas,
)
from hlf_priorizacion.copiloto.prompt import Prompt
from hlf_priorizacion.copiloto.seleccion import (
    Decision,
    PlanBarrido,
    comandos_lote,
    cortes_sin_lote,
    marcar_por_tope,
    planificar,
    verificar_tope,
)
from hlf_priorizacion.copiloto.validacion import mensaje_reintento, validar_salida
from hlf_priorizacion.ingesta.carga import cargar_perfiles
from hlf_priorizacion.ingesta.normalizacion import PerfilNormalizado, normalizar_perfil
from hlf_priorizacion.logs import obtener_logger
from hlf_priorizacion.modelos import Evaluacion, MetadatosAnalisis
from hlf_priorizacion.persistencia.salidas import leer_propuestas
from hlf_priorizacion.repositorio.contexto import Repositorio, SolicitudNoEncontrada

VENTANA_CIRCUITO: Final = 10
UMBRAL_CIRCUITO: Final = 0.2  # se abre con más del 20 % de fallas en las últimas 10 llamadas
MAX_INTENTOS_VALIDACION: Final = 2  # C6.7: el original y un reintento con el error
# Peor caso por solicitud (C2.5): 2 intentos de validación x (1 llamada + 3 reintentos de servicio).
MAX_INVOCACIONES_POR_SOLICITUD: Final = MAX_INTENTOS_VALIDACION * (MAX_REINTENTOS + 1)
# Tras Ctrl+C, cuánto se espera a las llamadas en curso: algo más que el timeout de lectura de 60 s (C4.8).
ESPERA_INTERRUPCION: Final = 70.0
_PASO_ESPERA: Final = 0.5  # el hilo principal espera en tramos cortos: Ctrl+C se atiende enseguida
# Campos de una llamada que pueden ir al log (C7.2): IDs, tokens, latencia; nunca texto del modelo.
_CAMPOS_LOG_LLAMADA: Final = (
    "id_solicitud",
    "fecha_corte",
    "model_id",
    "request_id",
    "tokens_entrada",
    "tokens_salida",
    "latencia_ms",
    "intento",
)


class ErrorLoteFaltante(ValueError):
    """Faltan salidas de ``hlf-lote`` para alguna fecha (C2.3). Lleva los comandos exactos."""

    def __init__(self, faltantes: list[date], comandos: list[str]) -> None:
        super().__init__("faltan salidas del lote para: " + ", ".join(f.isoformat() for f in faltantes))
        self.faltantes = faltantes
        self.comandos = comandos


# --------------------------------------------------------------------------- corte de circuito


class CorteCircuito:
    """C4.5. ``permitir()`` y la apertura comparten candado: ninguna llamada empieza después de abrirse."""

    def __init__(self, ventana: int = VENTANA_CIRCUITO, umbral: float = UMBRAL_CIRCUITO) -> None:
        self._ultimas: deque[bool] = deque(maxlen=ventana)
        self._max_fallas = int(umbral * ventana)
        self._candado = threading.Lock()
        self.abierto = False
        self.bitacora: list[str] = []  # "inicio" / "falla" / "ok" / "apertura", en orden real

    def permitir(self) -> bool:
        with self._candado:
            if self.abierto:
                return False
            self.bitacora.append("inicio")
            return True

    def registrar(self, ok: bool) -> None:
        with self._candado:
            self._ultimas.append(ok)
            self.bitacora.append("ok" if ok else "falla")
            if not self.abierto and sum(1 for x in self._ultimas if not x) > self._max_fallas:
                self.abierto = True
                self.bitacora.append("apertura")


class LimiteLlamadas(Exception):
    """El presupuesto de invocaciones (``--max-llamadas``) se agotó: la invocación no empezó (C2.5)."""


class ClienteConPresupuesto:
    """Presupuesto compartido de invocaciones reales al modelo (C2.5), seguro entre hilos.

    Cada invocación (incluidos los reintentos de validación y de servicio) consume 1 unidad antes de
    empezar. Si no queda presupuesto, no se invoca y se lanza ``LimiteLlamadas``; las ya en curso terminan.
    """

    def __init__(self, cliente: ClienteModelo, maximo: int) -> None:
        self._cliente = cliente
        self._candado = threading.Lock()
        self.maximo = maximo
        self.invocaciones = 0

    def converse(self, peticion: PeticionModelo, config: ConfigModelo) -> RespuestaModelo:
        with self._candado:
            if self.invocaciones >= self.maximo:
                raise LimiteLlamadas
            self.invocaciones += 1
        return self._cliente.converse(peticion, config)


# --------------------------------------------------------------------------- tareas


@dataclass(frozen=True)
class Tarea:
    paquete: PaqueteBarrido
    usuario: str
    huella_paquete: str


@dataclass
class ResultadoTarea:
    id_solicitud: str
    fecha_corte: date
    registro: RegistroAnalisis | None = None
    fallido: AnalisisFallido | None = None
    llamadas: list[dict[str, Any]] = field(default_factory=list)
    io: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    error_fatal: ErrorPermisos | None = None
    limite: bool = False  # sin presupuesto: se registra analisis_omitido(limite_llamadas), no fallido
    interrumpida: bool = False  # Ctrl+C antes de terminar: analisis_omitido(interrumpido), no fallido
    abandonada: bool = False  # su llamada seguía en curso al agotarse la espera tras Ctrl+C

    @property
    def estado(self) -> str:
        """Exactamente uno: ``analizada``, ``omitida`` (limite_llamadas), ``interrumpida`` o ``fallida``."""
        marcas = {
            "analizada": self.registro is not None,
            "omitida": self.limite,
            "interrumpida": self.interrumpida,
            "fallida": self.fallido is not None,
        }
        activas = [k for k, v in marcas.items() if v]
        if len(activas) != 1:
            raise AssertionError(f"resultado inconsistente para {self.id_solicitud}")
        return activas[0]


@dataclass(frozen=True)
class Contexto:
    """Dependencias de las tareas (inyectadas)."""

    cliente: ClienteModelo
    config: ConfigModelo
    prompt: Prompt
    id_ejecucion: str
    circuito: CorteCircuito
    detener: threading.Event
    dormir: Callable[[float], None] = time.sleep
    aleatorio: Callable[[], float] = random.random
    interrupcion: threading.Event = field(default_factory=threading.Event)  # Ctrl+C (además de ``detener``)


def construir_tarea(paquete: PaqueteBarrido, prompt: Prompt) -> Tarea:
    usuario = prompt.usuario(
        id_solicitud=paquete.id_solicitud,
        fecha_corte=paquete.fecha_corte.isoformat(),
        version_reglas=paquete.version_reglas,
        datos_clinicos=render_datos(paquete),
    )
    return Tarea(paquete, usuario, huella_texto(usuario))


def _fallido(t: Tarea, cx: Contexto, motivo: str, intentos: int) -> AnalisisFallido:
    return AnalisisFallido(
        id_solicitud=t.paquete.id_solicitud,
        fecha_corte=t.paquete.fecha_corte,
        version_reglas=t.paquete.version_reglas,
        version_prompt=cx.prompt.version_prompt,
        model_id=cx.config.model_id,
        id_ejecucion=cx.id_ejecucion,
        motivo=motivo,
        intentos=intentos,
    )


def analizar(t: Tarea, cx: Contexto) -> ResultadoTarea:
    """Una solicitud: hasta dos llamadas (C6.7), cada una con reintentos de servicio (C4.4)."""
    p = t.paquete
    res = ResultadoTarea(p.id_solicitud, p.fecha_corte)
    herramienta = especificacion_herramienta()
    usuario = t.usuario
    motivo = "sin_intentos"
    tokens_e = tokens_s = latencia = 0
    for intento in range(1, MAX_INTENTOS_VALIDACION + 1):
        if cx.detener.is_set():
            if cx.interrupcion.is_set():  # Ctrl+C: no es una falla; la próxima ejecución la retoma
                res.interrumpida = True
                return res
            res.fallido = _fallido(t, cx, "detenido_por_permisos", intento - 1)
            return res
        if not cx.circuito.permitir():
            res.fallido = _fallido(t, cx, "circuito_abierto", intento - 1)
            return res
        peticion = PeticionModelo(p.id_solicitud, cx.prompt.sistema, usuario, herramienta, intento)
        try:
            r = con_reintentos(cx.cliente, peticion, cx.config, dormir=cx.dormir, aleatorio=cx.aleatorio)
        except LimiteLlamadas:  # no es una falla: la próxima ejecución la retoma
            res.limite = True
            return res
        except ErrorPermisos as e:
            cx.detener.set()
            res.error_fatal = e
            res.fallido = _fallido(t, cx, f"permisos:{e.codigo}", intento)
            return res
        except ErrorModelo as e:
            cx.circuito.registrar(False)
            res.fallido = _fallido(t, cx, f"modelo:{e.codigo}", intento)
            return res
        except Exception as e:  # una solicitud nunca detiene a las demás
            cx.circuito.registrar(False)
            res.fallido = _fallido(t, cx, f"inesperado:{type(e).__name__}", intento)
            return res
        cx.circuito.registrar(True)
        huella_entrada = huella_texto(cx.prompt.huella + "\n" + usuario)
        huella_salida = huella_texto(r.crudo)
        res.io.append((huella_entrada, {"version_prompt": cx.prompt.version_prompt, "usuario": usuario}))
        res.io.append((huella_salida, {"request_id": r.request_id, "salida": r.crudo}))
        res.llamadas.append(
            {
                "id_solicitud": p.id_solicitud,
                "fecha_corte": p.fecha_corte.isoformat(),
                "model_id": cx.config.model_id,
                "request_id": r.request_id,
                "stop_reason": r.stop_reason,
                "tokens_entrada": r.tokens_entrada,
                "tokens_salida": r.tokens_salida,
                "latencia_ms": r.latencia_ms,
                "intento": intento,
                "huella_entrada": huella_entrada,
                "huella_salida": huella_salida,
            }
        )
        tokens_e += r.tokens_entrada
        tokens_s += r.tokens_salida
        latencia += r.latencia_ms
        metadatos = MetadatosAnalisis(
            model_id=cx.config.model_id,
            version_prompt=cx.prompt.version_prompt,
            request_id=r.request_id,
            fecha_corte=p.fecha_corte,
            id_ejecucion=cx.id_ejecucion,
        )
        v = validar_salida(r.entrada_herramienta, p, metadatos)
        if v.valido and v.analisis is not None:
            res.registro = RegistroAnalisis(
                id_analisis=nuevo_ulid(),
                id_solicitud=p.id_solicitud,
                fecha_corte=p.fecha_corte,
                version_reglas=p.version_reglas,
                version_prompt=cx.prompt.version_prompt,
                huella_prompt=cx.prompt.huella,
                model_id=cx.config.model_id,
                temperatura_enviada=cx.config.temperatura if cx.config.envia_temperatura else None,
                intentos=intento,
                correcciones=v.correcciones,
                huella_paquete=t.huella_paquete,
                huella_salida=huella_salida,
                uso=UsoModelo(tokens_entrada=tokens_e, tokens_salida=tokens_s, latencia_ms=latencia),
                analisis=v.analisis,
                revision_equidad=v.revision_equidad,
            )
            return res
        motivo = v.motivo_rechazo or "validacion"
        usuario = mensaje_reintento(t.usuario, motivo)
    res.fallido = _fallido(t, cx, f"validacion: {motivo}", MAX_INTENTOS_VALIDACION)
    return res


@contextmanager
def _sigint_diferido() -> Iterator[None]:
    """Un Ctrl+C mientras se escribe una solicitud se aplaza hasta terminar de escribirla (sin escrituras a
    medias). Solo en el hilo principal, que es donde Python entrega las señales."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    recibido: list[int] = []

    def _anotar(signum: int, _frame: FrameType | None) -> None:
        recibido.append(signum)

    previo = signal.signal(signal.SIGINT, _anotar)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previo if previo is not None else signal.default_int_handler)
    if recibido:
        raise KeyboardInterrupt


def _orden(r: ResultadoTarea) -> tuple[date, str]:
    return (r.fecha_corte, r.id_solicitud)


def _ordenados(futuros: Iterable[Future[ResultadoTarea]], tareas: dict[Future[ResultadoTarea], Tarea]) -> list[
    Future[ResultadoTarea]
]:
    return sorted(futuros, key=lambda f: (tareas[f].paquete.fecha_corte, tareas[f].paquete.id_solicitud))


def _interrumpida(t: Tarea, *, abandonada: bool = False) -> ResultadoTarea:
    return ResultadoTarea(t.paquete.id_solicitud, t.paquete.fecha_corte, interrumpida=True, abandonada=abandonada)


def _resultado_o_interrumpida(f: Future[ResultadoTarea], t: Tarea) -> ResultadoTarea:
    """Un futuro ya terminado: su resultado, o ``interrumpida`` si se canceló o no terminó bien."""
    if not f.cancelled() and f.exception() is None:
        return f.result()
    return _interrumpida(t)


def ejecutar_tareas(
    tareas: Sequence[Tarea],
    cx: Contexto,
    concurrencia: int,
    *,
    al_terminar: Callable[[ResultadoTarea], None] | None = None,
    vigia: Callable[[int], None] | None = None,
    espera_interrupcion: float = ESPERA_INTERRUPCION,
) -> list[ResultadoTarea]:
    """Ejecuta en paralelo (``concurrencia`` hilos) y devuelve en orden ``(fecha_corte, id_solicitud)``.

    ``al_terminar`` se llama en el hilo principal apenas termina cada solicitud (persistencia incremental, C5),
    con Ctrl+C aplazado mientras escribe. ``vigia(n)`` se llama tras cada solicitud terminada, con cuántas van:
    las pruebas lo usan para simular Ctrl+C en un punto exacto sin señales reales.

    Ante ``KeyboardInterrupt`` (C4.8) marca ``cx.interrupcion`` y ``cx.detener``, cancela lo que no empezó,
    espera hasta ``espera_interrupcion`` s a las llamadas en curso (un segundo Ctrl+C corta la espera) y
    devuelve normalmente: cada tarea sin terminar vuelve como ``interrumpida``. Cualquier otra excepción
    detiene el barrido y se propaga; lo ya entregado a ``al_terminar`` queda escrito.
    """
    if not tareas:
        return []
    resultados: list[ResultadoTarea] = []

    recogidos: set[Future[ResultadoTarea]] = set()

    def recoger(f: Future[ResultadoTarea], r: ResultadoTarea) -> None:
        # Idempotente por futuro y con la escritura antes de sacarlo de ``sin_recoger`` (los llamadores
        # descartan después): un Ctrl+C entre ambos pasos no pierde la solicitud ni la cuenta dos veces.
        if f in recogidos:
            return
        with _sigint_diferido():
            if al_terminar is not None:
                al_terminar(r)
            resultados.append(r)
            recogidos.add(f)

    pool = ThreadPoolExecutor(max_workers=concurrencia, thread_name_prefix="copiloto")
    futuros = {pool.submit(analizar, t, cx): t for t in tareas}
    sin_recoger = set(futuros)
    try:
        while sin_recoger:
            hechos, _ = wait(sin_recoger, timeout=_PASO_ESPERA, return_when=FIRST_COMPLETED)
            for f in _ordenados(hechos, futuros):
                r = f.result()  # si el hilo terminó con KeyboardInterrupt, se atiende como Ctrl+C
                recoger(f, r)
                sin_recoger.discard(f)
                if vigia is not None:
                    vigia(len(resultados))
    except KeyboardInterrupt:
        _interrumpir(pool, cx, futuros, sin_recoger, recoger, espera_interrupcion)
    except BaseException:
        cx.detener.set()
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
    return sorted(resultados, key=_orden)


def _interrumpir(
    pool: ThreadPoolExecutor,
    cx: Contexto,
    futuros: dict[Future[ResultadoTarea], Tarea],
    sin_recoger: set[Future[ResultadoTarea]],
    recoger: Callable[[Future[ResultadoTarea], ResultadoTarea], None],
    espera: float,
) -> None:
    cx.interrupcion.set()
    cx.detener.set()  # ninguna solicitud empieza otro intento
    pool.shutdown(wait=False, cancel_futures=True)  # las que no empezaron no empiezan
    fin = time.monotonic() + espera
    try:
        while True:
            for f in _ordenados([f for f in sin_recoger if f.done()], futuros):
                recoger(f, _resultado_o_interrumpida(f, futuros[f]))
                sin_recoger.discard(f)
            vivos = [f for f in sin_recoger if not f.done()]
            restante = fin - time.monotonic()
            if not vivos or restante <= 0:
                break
            wait(vivos, timeout=min(_PASO_ESPERA, restante), return_when=FIRST_COMPLETED)
    except KeyboardInterrupt:  # segundo Ctrl+C: no se espera más; lo ya escrito queda
        pass
    for f in _ordenados(list(sin_recoger), futuros):
        t = futuros[f]
        recoger(f, _resultado_o_interrumpida(f, t) if f.done() else _interrumpida(t, abandonada=True))
        sin_recoger.discard(f)


# --------------------------------------------------------------------------- barrido completo


@dataclass(frozen=True)
class ConfigBarrido:
    cortes: list[date]
    modo_rango: bool
    fecha_extraccion: date
    datos: Path
    salidas: Path
    version_reglas: str
    max_llamadas: int
    forzar: bool = False
    filtro_ids: frozenset[str] | None = None  # solo para pruebas e integración: limita las solicitudes
    datos_arg: str | None = None  # para el mensaje con los comandos hlf-lote exactos
    salidas_arg: str | None = None
    reglas_arg: str | None = None


@dataclass
class ResumenBarrido:
    cortes: list[str]
    analizadas: int = 0
    omitidas: dict[str, int] = field(default_factory=dict)
    fallidas: dict[str, int] = field(default_factory=dict)
    solicitudes_pendientes: int = 0
    invocaciones_peor_caso: int = 0  # pendientes x MAX_INVOCACIONES_POR_SOLICITUD (informativo)
    max_llamadas: int = 0  # presupuesto de invocaciones reales (--max-llamadas)
    por_limite_llamadas: int = 0  # pendientes que quedaron sin procesar por agotar el presupuesto
    interrumpido: bool = False  # hubo Ctrl+C (C4.8): el CLI sale con 130
    interrumpidas: int = 0  # pendientes que no terminaron por Ctrl+C (analisis_omitido: interrumpido)
    abandonadas: int = 0  # de ellas, cuántas seguían con una llamada en curso al agotarse la espera
    llamadas_modelo: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    segundos: float = 0.0
    por_corte: dict[str, dict[str, int]] = field(default_factory=dict)
    error_fatal: ErrorPermisos | None = None
    registros: list[RegistroAnalisis] = field(default_factory=list)

    @property
    def total_fallidas(self) -> int:
        return sum(self.fallidas.values())


def cargar_repositorio(datos: Path, fecha_extraccion: date) -> Repositorio:
    """Reconstruye los perfiles normalizados igual que el lote (contrato -> normalización)."""
    normalizados: list[PerfilNormalizado] = []
    for raw in cargar_perfiles(datos):
        try:
            v = validar_perfil(raw)
            if v.ok and v.perfil is not None:
                normalizados.append(normalizar_perfil(v.perfil).perfil)
        # Un perfil inválido no detiene el barrido; sus solicitudes quedan como contexto_no_disponible.
        except Exception as e:
            obtener_logger().warning("perfil no reconstruible", extra={"campos": {"tipo_error": type(e).__name__}})
    return Repositorio(normalizados, fecha_extraccion)


def _registrar_omitidas(auditoria: RegistroAuditoria, cfg: ConfigBarrido, decisiones: Iterable[Decision]) -> None:
    for d in decisiones:
        campos: dict[str, Any] = {
            "id_solicitud": d.id_solicitud,
            "fecha_corte": d.fecha_corte.isoformat(),
            "version_reglas": cfg.version_reglas,
            "motivo": d.motivo,
            "tipo_resultado": d.evaluacion.tipo_resultado,
        }
        if d.referencia:
            campos["referencia_fecha_corte"] = d.referencia
        auditoria.registrar("analisis_omitido", **campos)


def _plan(cfg: ConfigBarrido, prompt: Prompt, model_id: str) -> PlanBarrido:
    propuestas: dict[date, list[Evaluacion]] = {}
    analizadas: dict[date, set[str]] = {}
    for corte in cfg.cortes:
        evs = leer_propuestas(cfg.salidas, corte, cfg.version_reglas)
        if cfg.filtro_ids is not None:
            evs = [e for e in evs if e.id_solicitud in cfg.filtro_ids]
        propuestas[corte] = evs
        # Sin --forzar vale un análisis de cualquier versión de prompt; con --forzar, solo de la actual.
        version = prompt.version_prompt if cfg.forzar else None
        analizadas[corte] = ya_analizadas(cfg.salidas, corte, cfg.version_reglas, version, model_id)
    return planificar(propuestas, analizadas, modo_rango=cfg.modo_rango, forzar=cfg.forzar)


def ejecutar_barrido(
    cfg: ConfigBarrido,
    config: ConfigModelo,
    prompt: Prompt,
    cliente: ClienteModelo,
    id_ejecucion: str,
    *,
    dormir: Callable[[float], None] = time.sleep,
    aleatorio: Callable[[], float] = random.random,
    repositorio: Repositorio | None = None,
    vigia: Callable[[int], None] | None = None,
    espera_interrupcion: float = ESPERA_INTERRUPCION,
) -> ResumenBarrido:
    """Barrido completo. Ante Ctrl+C durante las llamadas devuelve un resumen parcial con ``interrumpido``;
    ante Ctrl+C fuera de ellas registra las pendientes como ``interrumpido`` y propaga ``KeyboardInterrupt``."""
    inicio = time.monotonic()
    auditoria = RegistroAuditoria(cfg.salidas / "auditoria" / "eventos.jsonl", id_ejecucion, actor="sistema:copiloto")

    # 3. Salidas del lote para cada corte (C2.3): si falta alguna, no se hace nada.
    faltantes = cortes_sin_lote(cfg.salidas, cfg.cortes, cfg.version_reglas)
    if faltantes:
        raise ErrorLoteFaltante(
            faltantes,
            comandos_lote(faltantes, datos=cfg.datos_arg, salidas=cfg.salidas_arg, reglas=cfg.reglas_arg),
        )

    # 4-5. Plan y presupuesto de invocaciones (C2.5): se aborta solo si las pendientes ya no caben.
    plan = _plan(cfg, prompt, config.model_id)
    resumen = ResumenBarrido(
        cortes=[c.isoformat() for c in cfg.cortes],
        solicitudes_pendientes=plan.solicitudes_pendientes,
        invocaciones_peor_caso=plan.solicitudes_pendientes * MAX_INVOCACIONES_POR_SOLICITUD,
        max_llamadas=cfg.max_llamadas,
    )
    try:
        verificar_tope(plan, cfg.max_llamadas)
    except Exception:
        tope = marcar_por_tope(plan)
        for c in tope.cortes:
            _registrar_omitidas(auditoria, cfg, c.omitidas)
        raise
    for c in plan.cortes:
        _registrar_omitidas(auditoria, cfg, c.omitidas)
    resumen.omitidas = plan.omitidas_por_motivo()

    # 6-9. Paquetes, llamadas y persistencia incremental: cada solicitud se escribe apenas termina.
    pendientes = [d for c in plan.cortes for d in c.pendientes]
    persistidor = _Persistidor(cfg, auditoria, {(d.fecha_corte, d.id_solicitud): d for d in pendientes})
    contador = ClienteConPresupuesto(cliente, cfg.max_llamadas)
    cx = Contexto(contador, config, prompt, id_ejecucion, CorteCircuito(), threading.Event(), dormir, aleatorio)
    try:
        tareas = _armar_tareas(cfg, config, prompt, id_ejecucion, pendientes, repositorio, persistidor)
        # 7-8. Llamadas en paralelo con reintentos, corte de circuito, validación y presupuesto compartido.
        ejecutar_tareas(
            tareas,
            cx,
            config.concurrencia,
            al_terminar=persistidor.guardar,
            vigia=vigia,
            espera_interrupcion=espera_interrupcion,
        )
    except KeyboardInterrupt:  # fuera de la espera de las llamadas: las pendientes quedan como interrumpido
        with _sigint_diferido():
            persistidor.interrumpir_restantes(pendientes)
        raise

    # 10. Resumen (determinista: no depende del orden en que terminaron las solicitudes).
    for corte in cfg.cortes:
        omitidas_corte = Counter[str](
            d.motivo for c in plan.cortes if c.fecha_corte == corte for d in c.omitidas if d.motivo
        )
        omitidas_corte.update(persistidor.omitidas_por_corte[corte])
        resumen.por_corte[corte.isoformat()] = {
            "analizadas": persistidor.analizadas_por_corte[corte],
            "fallidas": persistidor.fallidas_por_corte[corte],
            **{f"omitidas_{k}": v for k, v in sorted(omitidas_corte.items())},
        }
    resumen.registros = sorted(persistidor.registros, key=lambda r: (r.fecha_corte, r.id_solicitud))
    resumen.analizadas = len(resumen.registros)
    nuevas_omitidas = Counter[str]()
    for por_motivo in persistidor.omitidas_por_corte.values():
        nuevas_omitidas.update(por_motivo)
    resumen.por_limite_llamadas = nuevas_omitidas["limite_llamadas"]
    resumen.interrumpidas = nuevas_omitidas["interrumpido"]
    if +nuevas_omitidas:
        omitidas = Counter(resumen.omitidas)
        omitidas.update(+nuevas_omitidas)
        resumen.omitidas = dict(sorted(omitidas.items()))
    resumen.fallidas = dict(sorted(persistidor.fallidas.items()))
    resumen.tokens_entrada = persistidor.tokens_entrada
    resumen.tokens_salida = persistidor.tokens_salida
    resumen.llamadas_modelo = contador.invocaciones
    resumen.interrumpido = cx.interrupcion.is_set()
    resumen.abandonadas = persistidor.abandonadas
    resumen.segundos = round(time.monotonic() - inicio, 2)
    resumen.error_fatal = persistidor.error_fatal
    return resumen


def _armar_tareas(
    cfg: ConfigBarrido,
    config: ConfigModelo,
    prompt: Prompt,
    id_ejecucion: str,
    pendientes: list[Decision],
    repositorio: Repositorio | None,
    persistidor: _Persistidor,
) -> list[Tarea]:
    """6. Paquetes (C3), con verificación de huella. Las que no se pueden armar se guardan como fallidas ya."""
    tareas: list[Tarea] = []
    if not pendientes:
        return tareas
    repo = repositorio or cargar_repositorio(cfg.datos, cfg.fecha_extraccion)
    dq_por_corte = {c: leer_hallazgos_dq(cfg.salidas, c) for c in cfg.cortes}
    cohortes_por_corte = {c: leer_cohortes(cfg.salidas, c, cfg.version_reglas) for c in cfg.cortes}
    for d in pendientes:
        try:
            ctx = repo.contexto_a_fecha(d.id_solicitud, d.fecha_corte)
            paquete = armar_paquete(
                ctx,
                d.evaluacion,
                evaluacion_anterior=d.evaluacion_anterior,
                hallazgos_dq=dq_por_corte[d.fecha_corte].get(d.id_solicitud, []),
                cohorte=cohortes_por_corte[d.fecha_corte].get(d.id_solicitud),
            )
        except ErrorHuella:  # el contexto existe pero no es el que evaluó el lote
            motivo = "huella_distinta"
        except (SolicitudNoEncontrada, ValueError):  # no se pudo reconstruir el contexto
            motivo = "contexto_no_disponible"
        else:
            tareas.append(construir_tarea(paquete, prompt))
            continue
        fallido = AnalisisFallido(
            id_solicitud=d.id_solicitud,
            fecha_corte=d.fecha_corte,
            version_reglas=cfg.version_reglas,
            version_prompt=prompt.version_prompt,
            model_id=config.model_id,
            id_ejecucion=id_ejecucion,
            motivo=motivo,
            intentos=0,
        )
        with _sigint_diferido():
            persistidor.guardar(ResultadoTarea(d.id_solicitud, d.fecha_corte, fallido=fallido))
    return tareas


class _Persistidor:
    """9. Persistencia y auditoría de una solicitud apenas termina (C5), bajo un solo candado.

    Por solicitud y en este orden: E/S del modelo, eventos ``llamada_modelo``, análisis o fallido (solo
    agregado, con la clave de idempotencia), omisión ``limite_llamadas`` / ``interrumpido`` y evento
    ``analisis_ia`` / ``error_proceso``. Las claves ya vistas de cada JSONL se guardan en memoria durante la
    ejecución: no se relee un archivo que crece en cada escritura. Lleva también los conteos del resumen.
    """

    def __init__(
        self, cfg: ConfigBarrido, auditoria: RegistroAuditoria, pendientes: dict[tuple[date, str], Decision]
    ) -> None:
        self._cfg = cfg
        self._auditoria = auditoria
        self._pendientes = pendientes
        self._candado = threading.Lock()
        self._vistos: dict[Path, set[str]] = {}
        self._terminadas: set[tuple[date, str]] = set()
        self.registros: list[RegistroAnalisis] = []
        self.fallidas: Counter[str] = Counter()
        self.analizadas_por_corte: Counter[date] = Counter()
        self.fallidas_por_corte: Counter[date] = Counter()
        self.omitidas_por_corte: defaultdict[date, Counter[str]] = defaultdict(Counter)
        self.tokens_entrada = 0
        self.tokens_salida = 0
        self.abandonadas = 0
        self.error_fatal: ErrorPermisos | None = None

    def guardar(self, r: ResultadoTarea) -> None:
        with self._candado:
            clave = (r.fecha_corte, r.id_solicitud)
            if clave in self._terminadas:  # cada solicitud termina en un solo estado por ejecución
                return
            self._terminadas.add(clave)
            self._guardar(r)

    def interrumpir_restantes(self, pendientes: Iterable[Decision]) -> None:
        """Las pendientes que aún no terminaron quedan como ``interrumpido`` (Ctrl+C fuera de las llamadas)."""
        for d in pendientes:
            self.guardar(ResultadoTarea(d.id_solicitud, d.fecha_corte, interrumpida=True))

    def _guardar(self, r: ResultadoTarea) -> None:
        cfg, auditoria, log = self._cfg, self._auditoria, obtener_logger()
        corte = r.fecha_corte
        for huella, contenido in r.io:
            guardar_io(cfg.salidas, corte, huella, contenido)
        for ll in r.llamadas:
            auditoria.registrar("llamada_modelo", version_reglas=cfg.version_reglas, **ll)
            self.tokens_entrada += int(ll["tokens_entrada"])
            self.tokens_salida += int(ll["tokens_salida"])
            log.info("llamada al modelo", extra={"campos": {k: ll[k] for k in _CAMPOS_LOG_LLAMADA}})
        if r.registro is not None:
            guardar_analisis(cfg.salidas, corte, cfg.version_reglas, [r.registro], vistos_por_ruta=self._vistos)
        if r.fallido is not None:
            guardar_fallidos(cfg.salidas, corte, cfg.version_reglas, [r.fallido], vistos_por_ruta=self._vistos)
        motivo: MotivoOmision | None = "limite_llamadas" if r.limite else "interrumpido" if r.interrumpida else None
        if motivo is not None:
            evaluacion = self._pendientes[(corte, r.id_solicitud)].evaluacion
            _registrar_omitidas(auditoria, cfg, [Decision(r.id_solicitud, corte, "omitida", evaluacion, motivo=motivo)])
            self.omitidas_por_corte[corte][motivo] += 1
        if r.registro is not None:
            reg = r.registro
            auditoria.registrar(
                "analisis_ia",
                id_solicitud=reg.id_solicitud,
                fecha_corte=corte.isoformat(),
                version_reglas=cfg.version_reglas,
                id_analisis=reg.id_analisis,
                model_id=reg.model_id,
                version_prompt=reg.version_prompt,
                huella_prompt=reg.huella_prompt,
                huella_entrada=reg.huella_paquete,
                huella_salida=reg.huella_salida,
                intentos=reg.intentos,
                temperatura_enviada=reg.temperatura_enviada,
                correcciones=[_corr(c) for c in reg.correcciones],
                # C6.5 regla 2: solo la cantidad de oraciones marcadas; nunca su texto (C7.2).
                revision_equidad=len(reg.revision_equidad),
                estado=reg.analisis.metadatos.estado,
            )
            self.registros.append(reg)
            self.analizadas_por_corte[corte] += 1
        if r.fallido is not None:
            f = r.fallido
            codigo = f.motivo.split(":", 1)[0]
            self.fallidas[codigo] += 1
            self.fallidas_por_corte[corte] += 1
            auditoria.registrar(
                "error_proceso",
                id_solicitud=f.id_solicitud,
                fecha_corte=corte.isoformat(),
                version_reglas=cfg.version_reglas,
                etapa="copiloto",
                motivo=codigo,
                intentos=f.intentos,
                model_id=f.model_id,
            )
            log.warning(
                "análisis fallido",
                extra={"campos": {"id_solicitud": f.id_solicitud, "fecha_corte": corte.isoformat(), "motivo": codigo}},
            )
        if r.error_fatal is not None and self.error_fatal is None:
            self.error_fatal = r.error_fatal
        if r.abandonada:
            self.abandonadas += 1


def _corr(c: Correccion) -> dict[str, str]:
    return {"tipo": c.tipo, "campo": c.campo}
