"""Motor de priorización: variables → puntaje interpretable → nivel propuesto, con trazabilidad.

Es determinista: la misma historia, fecha de corte y versión de reglas producen siempre el mismo
resultado. El LLM nunca participa aquí (ver explicacion.py).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

from . import reglas as R
from .datos import Historia, Solicitud


@dataclass(slots=True)
class Factor:
    codigo: str          # base_prioridad, riesgo_basal, edad, espera, evento, medicion, tendencia, ...
    descripcion: str
    aporte: float
    categoria: str       # base | evento | medicion | patron | ajuste (deciden el nivel)
                         # contexto (ordena dentro del nivel) | regla_dura | alerta (sin puntos)
    tipo_fuente: str     # lista | paciente | evento | medicion | externa | mensaje
    ref_fuente: str      # id trazable de la fila de origen
    fecha_dato: date | None = None


@dataclass(slots=True)
class Decision:
    fecha_corte: date
    prioridad_final: str
    # Ajuste de la Administradora al puntaje de orden (F0007). None = mantiene el anterior; 0 = vuelve al del motor
    ajuste_puntaje: float | None = None


@dataclass(slots=True)
class Resultado:
    id_solicitud: str
    id_paciente: str
    especialidad: str
    fecha_corte: date
    excluido: bool
    motivo_exclusion: str | None
    puntaje: float                   # puntaje de orden (nivel + contexto)
    nivel_calculado: str
    nivel_propuesto: str
    prioridad_inicial: str
    prioridad_vigente: str
    cambio: str                      # sube | baja | igual (propuesta vs. vigente)
    alerta: bool
    motivos_alerta: list[str] = field(default_factory=list)
    resguardo_aplicado: bool = False  # se evitó bajar de nivel sin evidencia de mejora
    evidencia_mejora: bool = False
    factores: list[Factor] = field(default_factory=list)
    puntaje_nivel: float = 0.0       # base + señales clínicas: decide el nivel
    ajuste_puntaje: float = 0.0      # ajuste vigente de la Administradora al puntaje de orden (no cambia el nivel)
    version_reglas: str = field(default_factory=lambda: R.VERSION_REGLAS)   # la vigente al calcular (F0014)

    @property
    def puntaje_vigente(self) -> float:
        """Lo que ordena la cola: el puntaje del motor más el ajuste de la Administradora."""
        return round(self.puntaje + self.ajuste_puntaje, 2)

    @property
    def motivo_principal(self) -> str:
        if self.excluido:
            return f"Fuera de la lista: {self.motivo_exclusion}"
        if self.alerta:
            return self.motivos_alerta[0]
        clinicos = [f for f in self.factores if f.categoria in CATEGORIAS_CLINICAS]
        if not clinicos:
            return "Sin señales clínicas durante la espera"
        if self.cambio == "baja":
            return min(clinicos, key=lambda f: f.aporte).descripcion
        return max(clinicos, key=lambda f: f.aporte).descripcion

    def aporte_por_categoria(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for f in self.factores:
            out[f.categoria] = out.get(f.categoria, 0.0) + f.aporte
        return out


CATEGORIAS_CLINICAS = ("evento", "medicion", "patron")
CATEGORIAS_NIVEL = ("base", "ajuste") + CATEGORIAS_CLINICAS


def decaimiento(dias: int) -> float:
    return 0.5 ** (dias / R.VIDA_MEDIA_DIAS)


def nivel_por_puntaje(puntaje: float) -> str:
    if puntaje >= R.UMBRAL_ALTA:
        return "alta"
    if puntaje >= R.UMBRAL_MEDIA:
        return "media"
    return "baja"


def prioridad_vigente(sol: Solicitud, decisiones: list[Decision], corte: date) -> str:
    """Última prioridad decidida por el equipo clínico hasta la fecha de corte; si no hay, la inicial."""
    vigente = sol.prioridad_inicial
    for d in sorted(decisiones, key=lambda d: d.fecha_corte):
        if d.fecha_corte <= corte:
            vigente = d.prioridad_final
    return vigente


def ajuste_vigente(decisiones: list[Decision], corte: date) -> float:
    """Último ajuste de puntaje decidido hasta la fecha de corte (una decisión sin ajuste mantiene el anterior)."""
    ajuste = 0.0
    for d in sorted(decisiones, key=lambda d: d.fecha_corte):
        if d.fecha_corte <= corte and d.ajuste_puntaje is not None:
            ajuste = d.ajuste_puntaje
    return ajuste


def _num(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _pendiente_por_dia(puntos: list[tuple[int, float]]) -> float | None:
    n = len(puntos)
    mx = sum(x for x, _ in puntos) / n
    my = sum(y for _, y in puntos) / n
    sxx = sum((x - mx) ** 2 for x, _ in puntos)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in puntos) / sxx


def evaluar(sol: Solicitud, hist: Historia, corte: date, decisiones: list[Decision] | None = None) -> Resultado:
    decisiones = decisiones or []
    vigente = prioridad_vigente(sol, decisiones, corte)
    base = dict(id_solicitud=sol.id_solicitud, id_paciente=sol.id_paciente, especialidad=sol.especialidad,
                fecha_corte=corte, prioridad_inicial=sol.prioridad_inicial, prioridad_vigente=vigente)

    # 1. Exclusión
    if corte < sol.fecha_ingreso:
        return Resultado(**base, excluido=True, motivo_exclusion="aún no ingresa a la lista", puntaje=0.0,
                         nivel_calculado=vigente, nivel_propuesto=vigente, cambio="igual", alerta=False)
    if sol.fecha_egreso and corte >= sol.fecha_egreso:
        motivo = f"{sol.motivo_egreso} desde {sol.fecha_egreso.isoformat()}"
        return Resultado(**base, excluido=True, motivo_exclusion=motivo, puntaje=0.0,
                         nivel_calculado=vigente, nivel_propuesto=vigente, cambio="igual", alerta=False)

    factores: list[Factor] = []
    alerta_motivos: list[str] = []
    evidencia_mejora = False

    # 2. Base y contexto. El contexto (riesgo basal, edad, espera) solo ordena dentro del nivel.
    factores.append(Factor("base_prioridad", f"Prioridad inicial {sol.prioridad_inicial}",
                           R.BASE_PRIORIDAD[sol.prioridad_inicial], "base", "lista",
                           sol.id_solicitud, sol.fecha_ingreso))
    clase, razon = R.RIESGO_BASAL_DX.get(sol.cie10, ("medio", "diagnóstico sin clasificar"))
    if R.PUNTOS_RIESGO_BASAL[clase]:
        factores.append(Factor("riesgo_basal", f"Riesgo basal {clase} por diagnóstico {sol.cie10} ({razon})",
                               R.PUNTOS_RIESGO_BASAL[clase], "contexto", "lista", sol.id_solicitud, sol.fecha_ingreso))
    if (p := R.puntos_edad(sol.edad)):
        factores.append(Factor("edad", f"Edad {sol.edad} años", p, "contexto", "paciente", sol.id_paciente))
    dias_espera = (corte - sol.fecha_ingreso).days
    plazo = R.PLAZO_REFERENCIA_DIAS[clase]
    razon_plazo = dias_espera / plazo
    if (ap := min(R.MAX_APORTE_ESPERA, max(0.0, razon_plazo - 0.5) * 1.5)) > 0:
        factores.append(Factor("espera", f"Lleva {dias_espera} días en espera; plazo de referencia {plazo} días "
                               f"({_num(razon_plazo)}×)", ap, "contexto", "lista", sol.id_solicitud, sol.fecha_ingreso))

    # 3. Eventos clínicos con decaimiento en el tiempo
    eventos = hist.eventos_hasta(corte)
    for e in eventos:
        dias = (corte - e.fecha).days
        if dias > R.VENTANA_EVENTOS_DIAS:
            continue
        w = R.PESO_EVENTO.get((e.tipo, e.subtipo), 0.0)
        if e.subtipo in R.SUBTIPOS_MEJORA and dias <= R.VENTANA_MEJORA_DIAS:
            evidencia_mejora = True
        if w:
            factores.append(Factor("evento", f"{R.NOMBRE_TIPO_EVENTO[e.tipo]}: {e.subtipo} ({e.severidad})",
                                   w * decaimiento(dias), "evento", "evento", e.id_evento, e.fecha))
        if e.severidad == "grave" and dias <= R.VENTANA_REGLA_DURA_DIAS:
            motivo = (f"Evento grave reciente: {R.NOMBRE_TIPO_EVENTO[e.tipo].lower()} "
                      f"({e.subtipo}) el {e.fecha.isoformat()}")
            alerta_motivos.append(motivo)
            factores.append(Factor("regla_dura", f"Regla dura: {motivo}", 0.0, "regla_dura", "evento",
                                   e.id_evento, e.fecha))

    # 4. Mediciones: desviación del último valor, tendencia (tasa de deterioro) y persistencia
    mediciones = hist.mediciones_hasta(corte)
    hay_fuera_reciente, hay_normales_sostenidas = False, False
    for tipo, lst in mediciones.items():
        if not lst:
            continue
        lo, hi = R.RANGOS_NORMALES[tipo]
        ancho = hi - lo
        nombre, unidad = R.NOMBRE_MEDICION[tipo], R.UNIDADES[tipo]
        ultimo = lst[-1]
        edad_dato = (corte - ultimo.fecha).days
        fuente = "externa" if ultimo.origen == "externa" else "medicion"

        desv = max(0.0, ultimo.valor - hi, lo - ultimo.valor) / ancho
        if desv > 0:
            factores.append(Factor(
                "medicion", f"{nombre}: último valor {_num(ultimo.valor)} {unidad} fuera de rango "
                f"({_num(lo)}–{_num(hi)})" + (" · examen externo validado" if fuente == "externa" else ""),
                R.PESO_DESVIACION * min(desv, R.MAX_DESVIACION) * decaimiento(edad_dato),
                "medicion", fuente, ultimo.ref, ultimo.fecha))

        recientes = [m for m in lst if (corte - m.fecha).days <= R.VENTANA_TENDENCIA_DIAS]
        if len(recientes) >= R.MIN_MEDICIONES_TENDENCIA:
            pend = _pendiente_por_dia([((m.fecha - recientes[0].fecha).days, m.valor) for m in recientes])
            if pend is not None:
                pend_mes = pend * 30
                norm = pend_mes / ancho * (-1 if tipo in R.MEJOR_ALTO else 1)
                ref = f"{recientes[0].ref} … {ultimo.ref}"
                if norm > R.UMBRAL_TENDENCIA:
                    factores.append(Factor(
                        "tendencia", f"{nombre}: tendencia de empeoramiento ({'+' if pend_mes > 0 else ''}"
                        f"{_num(pend_mes)} {unidad}/mes en {len(recientes)} mediciones)",
                        min(R.MAX_APORTE_TENDENCIA, R.PESO_TENDENCIA * norm) * decaimiento(edad_dato),
                        "medicion", fuente, ref, ultimo.fecha))
                elif norm < -R.UMBRAL_TENDENCIA and desv == 0:
                    factores.append(Factor(
                        "tendencia_mejora", f"{nombre}: tendencia de mejora con último valor normal",
                        R.APORTE_TENDENCIA_MEJORA * decaimiento(edad_dato), "medicion", fuente, ref, ultimo.fecha))

        ventana = [m for m in lst if (corte - m.fecha).days <= R.VENTANA_PERSISTENCIA_DIAS]
        if ventana:
            fuera = sum(m.fuera_de_rango for m in ventana)
            hay_fuera_reciente |= fuera > 0
            if len(ventana) >= 2:
                hay_normales_sostenidas |= fuera == 0
                if fuera:
                    prop = fuera / len(ventana)
                    factores.append(Factor(
                        "persistencia", f"{nombre}: {fuera} de {len(ventana)} mediciones fuera de rango "
                        f"en {R.VENTANA_PERSISTENCIA_DIAS} días", R.PESO_PERSISTENCIA * prop, "medicion",
                        fuente, f"{ventana[0].ref} … {ventana[-1].ref}", ventana[-1].fecha))
    if hay_normales_sostenidas and not hay_fuera_reciente:
        evidencia_mejora = True

    # 5. Patrones: combinación histórica de señales
    aumentos = [e for e in eventos if e.subtipo == "aumento dosis"
                and (corte - e.fecha).days <= R.PATRON_ESCALADA_VENTANA_DIAS]
    alterados = [e for e in eventos if e.tipo == "examen_alterado"
                 and (corte - e.fecha).days <= R.PATRON_ESCALADA_VENTANA_DIAS]
    if aumentos and alterados:
        a, x = aumentos[-1], alterados[-1]
        factores.append(Factor(
            "patron", f"Patrón: aumento de dosis y examen alterado en {R.PATRON_ESCALADA_VENTANA_DIAS} días "
            "(posible mal control)", R.PATRON_ESCALADA_APORTE, "patron", "evento",
            f"{a.id_evento}+{x.id_evento}", max(a.fecha, x.fecha)))
    todas = [m for lst in mediciones.values() for m in lst if m.fuera_de_rango]
    for e in reversed(eventos):
        if e.severidad == "leve" or (corte - e.fecha).days > R.PATRON_MEDICION_VENTANA_DIAS:
            continue
        previas = [m for m in todas if 0 <= (e.fecha - m.fecha).days <= R.PATRON_MEDICION_PREVIA_DIAS]
        if previas:
            m = previas[-1]
            factores.append(Factor(
                "patron", f"Patrón: {R.NOMBRE_MEDICION[m.tipo]} fuera de rango {(e.fecha - m.fecha).days} días "
                f"antes de {R.NOMBRE_TIPO_EVENTO[e.tipo].lower()} ({e.subtipo})", R.PATRON_MEDICION_APORTE,
                "patron", "evento", f"{m.ref}+{e.id_evento}", e.fecha))
            break

    # 6. Relevancia según riesgo basal: la misma señal pesa más en una condición de alto riesgo
    positivas = sum(f.aporte for f in factores if f.categoria in CATEGORIAS_CLINICAS and f.aporte > 0)
    ajuste = R.AJUSTE_SENALES_RIESGO_BASAL[clase] * positivas
    if abs(ajuste) >= 0.01:
        factores.append(Factor(
            "ajuste_riesgo_basal", f"Ajuste por riesgo basal {clase} ({sol.cie10}): señales clínicas "
            f"×{1 + R.AJUSTE_SENALES_RIESGO_BASAL[clase]:.2f}".replace(".", ","), ajuste, "ajuste", "lista",
            sol.id_solicitud))

    # 7. Alarmas informadas por el paciente y validadas: alertan, no cambian el nivel solas
    for al in hist.alarmas_hasta(corte):
        if (corte - al.fecha).days <= R.VENTANA_REGLA_DURA_DIAS:
            motivo = f"Síntoma de alarma informado por el paciente (validado): {al.detalle}"
            alerta_motivos.append(motivo)
            factores.append(Factor("alarma_paciente", motivo, 0.0, "alerta", "mensaje", al.ref, al.fecha))

    # 8. Nivel (solo base + señales clínicas) y puntaje de orden (+ contexto)
    puntaje_nivel = max(0.0, sum(f.aporte for f in factores if f.categoria in CATEGORIAS_NIVEL))
    puntaje = puntaje_nivel + sum(f.aporte for f in factores if f.categoria == "contexto")
    nivel_calc = nivel_por_puntaje(puntaje_nivel)
    hay_regla_dura = any(f.categoria == "regla_dura" for f in factores)
    propuesto = "alta" if hay_regla_dura else nivel_calc
    resguardo = False
    if R.ORDEN_NIVEL[propuesto] < R.ORDEN_NIVEL[vigente] and not evidencia_mejora:
        propuesto, resguardo = vigente, True
    cambio = ("sube" if R.ORDEN_NIVEL[propuesto] > R.ORDEN_NIVEL[vigente]
              else "baja" if R.ORDEN_NIVEL[propuesto] < R.ORDEN_NIVEL[vigente] else "igual")

    factores.sort(key=lambda f: (f.categoria in ("base", "contexto"), f.categoria == "ajuste", -abs(f.aporte)))
    return Resultado(**base, excluido=False, motivo_exclusion=None, puntaje=round(puntaje, 2),
                     puntaje_nivel=round(puntaje_nivel, 2), ajuste_puntaje=ajuste_vigente(decisiones, corte),
                     nivel_calculado=nivel_calc, nivel_propuesto=propuesto, cambio=cambio,
                     alerta=bool(alerta_motivos), motivos_alerta=alerta_motivos, resguardo_aplicado=resguardo,
                     evidencia_mejora=evidencia_mejora, factores=factores)


def huella_datos(sol: Solicitud, hist: Historia, corte: date, decisiones: list[Decision] | None = None) -> str:
    """Hash de las filas usadas en el cálculo: permite verificar que una propuesta es reproducible."""
    partes = [R.VERSION_REGLAS, sol.id_solicitud, sol.prioridad_inicial, corte.isoformat()]
    partes += [e.id_evento for e in hist.eventos_hasta(corte)]
    for tipo in sorted(hist.mediciones):
        partes += [f"{m.ref}={m.valor}" for m in hist.mediciones_hasta(corte)[tipo]]
    partes += [a.ref for a in hist.alarmas_hasta(corte)]
    partes += [f"{d.fecha_corte}:{d.prioridad_final}" + ("" if d.ajuste_puntaje is None else f":{d.ajuste_puntaje:g}")
               for d in (decisiones or []) if d.fecha_corte <= corte]
    return hashlib.sha256("|".join(partes).encode()).hexdigest()[:16]
