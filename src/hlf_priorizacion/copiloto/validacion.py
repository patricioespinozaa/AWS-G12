"""Validación de la salida del modelo antes de guardarla (C6, sección 8.5). Funciones puras.

Orden: los ``metadatos`` los escribe el sistema (C6.6); ``riesgo_poblacional`` se reemplaza por la cohorte
del paquete (C6.3); esquema ``analisis-v1`` estricto e ``id_solicitud`` (C6.1); citas (C6.2); bandera roja
(C6.4); equidad (C6.5: rechazo por atributo no disponible y marca de revisión por inasistencias). Validar un
análisis ya validado no cambia nada (idempotencia).
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Final

from pydantic import ValidationError

from hlf_priorizacion.copiloto.modelos import Correccion, FraseRevisionEquidad, PaqueteBarrido
from hlf_priorizacion.modelos import (
    AnalisisIA,
    EntradaLineaTiempo,
    HallazgoIA,
    InconsistenciaDatos,
    MetadatosAnalisis,
    RiesgoPoblacional,
)

# C6.5 (decisión E-1 = C): listas de palabras auditables, en un solo lugar. Sin interpretar negaciones: "no",
# "sin", "sino", "salvo" no cambian nada. Se compara sobre ``normalizar()``: NFKD, minúsculas, sin tildes y cada
# tramo de separadores ("-", "—", "/", ".", "_", espacios) reducido a un solo espacio; por eso los patrones solo
# usan " " como separador.
# - "atributo_no_disponible" (regla 1): el copiloto nunca recibe comuna, previsión ni nivel socioeconómico;
#   mencionarlos en cualquier campo rechaza el análisis (fail-closed). La clave es el nombre que va al motivo.
# - "inasistencia" + "verbo_bajada" en una misma oración (regla 2): el análisis se guarda con la marca
#   ``revision_equidad`` y decide el médico. Los verbos van como raíz: cubren conjugaciones, clíticos
#   (bajarla, postergarlo) y sustantivos (baja, rebaja, postergación, reducción, disminución).
EQUIDAD_TERMINOS: Final[dict[str, dict[str, str]]] = {
    "atributo_no_disponible": {
        # Raíces con prefijos y sufijos (fail-closed): "intercomunal", "comuna_residencia", "previsionalmente",
        # "imprevisión". No tocan "comunicó", "comunitario" ni "previsible".
        "comuna": r"\w*comuna\w*",
        "prevision": r"\w*prevision\w*|fonasa|isapres?|fondo nacional de salud",
        # "socio-económico", "socio—económico", "socio/económica", "N.S.E.", "N S E"; GSE = grupo socioeconómico.
        "nivel_socioeconomico": r"socio ?economic\w*|n ?s ?e|gse",
    },
    "inasistencia": {
        "inasistencia": r"inasistencias?",
        "no_asistio": r"no asistio",  # también "no_asistio": el "_" queda como espacio
        "no_show": r"no ?shows?",
        "ausencia_a_citas": r"ausencias? a (?:(?:la|las|su|sus) )?citas?",
        "citas_fallidas": r"citas? fallidas?",
    },
    "verbo_bajada": {
        "bajar": r"baj\w*",
        "rebajar": r"rebaj\w*",
        "postergar": r"posterg\w*",
        "reducir": r"redu[cjz]\w*",
        "disminuir": r"disminu\w*",
        "degradar": r"degrad\w*",
        "relegar": r"releg\w*",
    },
}
MOTIVO_EQUIDAD: Final = "equidad_atributo_no_disponible"
DETALLE_REVISION_EQUIDAD: Final = "inasistencias junto a un verbo de bajada en la misma oración"


def _patron(grupo: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(f"(?P<{k}>{v})" for k, v in EQUIDAD_TERMINOS[grupo].items()) + r")\b")


_RE_ATRIBUTO_NO_DISPONIBLE = _patron("atributo_no_disponible")
_RE_INASISTENCIA = _patron("inasistencia")
_RE_VERBO_BAJADA = _patron("verbo_bajada")
# Oraciones: se corta en ". ", "; ", "? ", "! " y saltos de línea.
_RE_ORACION = re.compile(r"[.;?!][ \t]+|[\r\n]+")
_RE_SEPARADORES = re.compile(r"[\W_]+")
MOTIVO_SIN_HERRAMIENTA: Final = "sin_herramienta"


@dataclass(frozen=True)
class ResultadoValidacion:
    valido: bool
    analisis: AnalisisIA | None = None
    correcciones: list[Correccion] = field(default_factory=list)
    motivo_rechazo: str | None = None
    revision_equidad: list[FraseRevisionEquidad] = field(default_factory=list)


def riesgo_de_paquete(paquete: PaqueteBarrido) -> RiesgoPoblacional | None:
    c = paquete.cohorte
    if c is None:
        return None
    return RiesgoPoblacional(
        n=c.n,
        k=c.k,
        p=c.p,
        ic95_inf=c.ic95_inf,
        ic95_sup=c.ic95_sup,
        advertencia_muestra_pequena=c.advertencia_muestra_pequena,
        advertencia_sesgo_acceso=c.advertencia_sesgo_acceso,
    )


def _textos(a: AnalisisIA) -> list[tuple[str, str]]:
    """``(campo, texto)`` de cada cadena del análisis, salvo ``metadatos`` (los escribe el sistema)."""
    salida: list[tuple[str, str]] = []

    def recorrer(nodo: object, ruta: str) -> None:
        if isinstance(nodo, str):
            salida.append((ruta, nodo))
        elif isinstance(nodo, dict):
            for k, v in nodo.items():
                recorrer(v, f"{ruta}.{k}" if ruta else str(k))
        elif isinstance(nodo, list):
            for n, v in enumerate(nodo):
                recorrer(v, f"{ruta}[{n}]")

    recorrer(a.model_dump(mode="python", exclude={"metadatos"}), "")
    return salida


def normalizar(texto: str) -> str:
    """NFKD (pliega anchos completos y ligaduras), minúsculas, sin tildes ni diéresis, y cada tramo de caracteres
    no alfanuméricos (``_`` incluido) como un solo espacio: "Socio—Económico", "socio/economico" y
    "SOCIO ECONOMICO" quedan iguales."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_marcas = "".join(c for c in descompuesto if not unicodedata.combining(c)).casefold()
    return _RE_SEPARADORES.sub(" ", sin_marcas)


def oraciones(texto: str) -> list[str]:
    return [o.strip() for o in _RE_ORACION.split(texto) if o.strip()]


# C6.5 regla 1, segundo filtro (fail-closed). Las listas de palabras por token no convergen ("FONASAs",
# "F.O.N.A.S.A.", "socioeconomía", "I.S.A.P.R.E."), así que las raíces largas se buscan como subcadena en el
# texto reducido a solo letras: atrapa plurales, sufijos, siglas con puntos y separadores. Las siglas cortas
# (NSE, GSE) se buscan como token tras unir letras sueltas ("n s e" -> "nse"), para no confundirlas con
# fragmentos de palabras comunes ("pense", "ingreso").
RAICES_ATRIBUTO_SUBCADENA: Final[dict[str, tuple[str, ...]]] = {
    "comuna": ("comuna",),
    "prevision": ("prevision", "fonasa", "isapre", "fondonacionaldesalud"),
    "nivel_socioeconomico": ("socioeconom",),
}
_RE_SIGLAS_CORTAS: Final = re.compile(r"\b(?:nse|gse)s?\b")
_RE_LETRAS_SUELTAS: Final = re.compile(r"\b(?:[a-z0-9] )+[a-z0-9]\b")
_RE_NO_LETRAS: Final = re.compile(r"[^a-z0-9]+")


def _atributo_por_raiz(normalizado: str) -> str | None:
    compacto = _RE_NO_LETRAS.sub("", normalizado)
    for atributo, raices in RAICES_ATRIBUTO_SUBCADENA.items():
        if any(r in compacto for r in raices):
            return atributo
    unido = _RE_LETRAS_SUELTAS.sub(lambda m: m.group().replace(" ", ""), normalizado)
    if _RE_SIGLAS_CORTAS.search(unido):
        return "nivel_socioeconomico"
    return None


def atributo_no_disponible(a: AnalisisIA) -> tuple[str, str] | None:
    """C6.5 regla 1: primer ``(campo, atributo)`` que menciona comuna, previsión o NSE; ``None`` si no hay."""
    for campo, texto in _textos(a):
        por_raiz = _atributo_por_raiz(normalizar(texto))
        if por_raiz is not None:
            return campo, por_raiz
        m = _RE_ATRIBUTO_NO_DISPONIBLE.search(normalizar(texto))
        if m is not None and m.lastgroup is not None:
            return campo, m.lastgroup
    return None


def frases_revision_equidad(a: AnalisisIA) -> list[FraseRevisionEquidad]:
    """C6.5 regla 2: cada oración que menciona inasistencias y un verbo de bajada, con su campo."""
    marcas: list[FraseRevisionEquidad] = []
    for campo, texto in _textos(a):
        for oracion in oraciones(texto):
            normal = normalizar(oracion)
            if _RE_INASISTENCIA.search(normal) and _RE_VERBO_BAJADA.search(normal):
                marcas.append(FraseRevisionEquidad(campo=campo, texto=oracion))
    return marcas


def _resumen_errores(e: ValidationError) -> str:
    partes = [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors(include_input=False)[:10]]
    return "; ".join(partes)


def _corregir_citas(a: AnalisisIA, ids: set[str]) -> tuple[AnalisisIA, list[Correccion]]:
    correcciones: list[Correccion] = []
    hallazgos: list[HallazgoIA] = []
    for n, h in enumerate(a.hallazgos):
        invalidos = [i for i in h.ids_registro if i not in ids]
        if not invalidos:
            hallazgos.append(h)
            continue
        validos = [i for i in h.ids_registro if i in ids]
        correcciones += [Correccion(tipo="id_eliminado", campo=f"hallazgos[{n}]", detalle=i) for i in invalidos]
        if h.tipo == "documentado":
            correcciones.append(
                Correccion(tipo="hallazgo_a_inferido", campo=f"hallazgos[{n}]", detalle=",".join(invalidos))
            )
        hallazgos.append(HallazgoIA(texto=h.texto, tipo="inferido", ids_registro=validos))
    linea: list[EntradaLineaTiempo] = []
    for n, e in enumerate(a.linea_tiempo_relevante):
        invalidos = [i for i in e.ids_registro if i not in ids]
        correcciones += [
            Correccion(tipo="id_eliminado", campo=f"linea_tiempo_relevante[{n}]", detalle=i) for i in invalidos
        ]
        linea.append(
            e if not invalidos else e.model_copy(update={"ids_registro": [i for i in e.ids_registro if i in ids]})
        )
    inconsistencias: list[InconsistenciaDatos] = []
    for n, inc in enumerate(a.inconsistencias_datos):
        validos = [i for i in inc.ids_registro if i in ids]
        invalidos = [i for i in inc.ids_registro if i not in ids]
        correcciones += [
            Correccion(tipo="id_eliminado", campo=f"inconsistencias_datos[{n}]", detalle=i) for i in invalidos
        ]
        if not validos:
            correcciones.append(
                Correccion(tipo="inconsistencia_eliminada", campo=f"inconsistencias_datos[{n}]", detalle="sin IDs")
            )
            continue
        inconsistencias.append(inc if not invalidos else InconsistenciaDatos(texto=inc.texto, ids_registro=validos))
    corregido = a.model_copy(
        update={"hallazgos": hallazgos, "linea_tiempo_relevante": linea, "inconsistencias_datos": inconsistencias}
    )
    return corregido, correcciones


def validar_salida(
    entrada: dict[str, Any] | None,
    paquete: PaqueteBarrido,
    metadatos: MetadatosAnalisis,
) -> ResultadoValidacion:
    if not isinstance(entrada, dict):
        return ResultadoValidacion(False, motivo_rechazo=MOTIVO_SIN_HERRAMIENTA)
    datos = copy.deepcopy(entrada)
    correcciones: list[Correccion] = []

    # C6.6: los metadatos son del sistema.
    datos["metadatos"] = metadatos.model_dump(mode="json")

    # C6.3: cifras de la cohorte, siempre las del paquete.
    esperado = riesgo_de_paquete(paquete)
    esperado_json = esperado.model_dump(mode="json") if esperado is not None else None
    if datos.get("riesgo_poblacional") != esperado_json:
        correcciones.append(
            Correccion(
                tipo="riesgo_poblacional_reemplazado",
                campo="riesgo_poblacional",
                detalle="cifras del modelo distintas de la cohorte del paquete",
            )
        )
    datos["riesgo_poblacional"] = esperado_json

    # C6.2 (decisión D-1 = A): un hallazgo "documentado" sin ningún ID pasa a "inferido", igual que uno con
    # todos sus IDs inválidos. Se hace antes del esquema, que rechazaría "documentado" sin IDs.
    hallazgos_crudos = datos.get("hallazgos")
    if isinstance(hallazgos_crudos, list):
        for n, h in enumerate(hallazgos_crudos):
            if isinstance(h, dict) and h.get("tipo") == "documentado" and not h.get("ids_registro"):
                h["tipo"] = "inferido"
                h["ids_registro"] = []
                correcciones.append(Correccion(tipo="hallazgo_a_inferido", campo=f"hallazgos[{n}]", detalle="sin IDs"))

    # C6.1: esquema estricto e id_solicitud.
    try:
        analisis = AnalisisIA.model_validate_json(json.dumps(datos, ensure_ascii=False))
    except ValidationError as e:
        return ResultadoValidacion(False, correcciones=correcciones, motivo_rechazo=f"esquema: {_resumen_errores(e)}")
    except (TypeError, ValueError) as e:
        return ResultadoValidacion(False, correcciones=correcciones, motivo_rechazo=f"esquema: {type(e).__name__}")
    if analisis.id_solicitud != paquete.id_solicitud:
        return ResultadoValidacion(
            False, correcciones=correcciones, motivo_rechazo="id_solicitud distinto del de la solicitud analizada"
        )

    # C6.2: citas.
    analisis, de_citas = _corregir_citas(analisis, paquete.ids_paquete())
    correcciones += de_citas

    # C6.4: bandera roja.
    if paquete.evaluacion.banderas and analisis.prioridad_sugerida != "critica" and analisis.acuerdo_con_motor.acuerdo:
        return ResultadoValidacion(
            False,
            correcciones=correcciones,
            motivo_rechazo=(
                "el motor marcó bandera roja y prioridad_sugerida no es critica: "
                "acuerdo_con_motor.acuerdo debe ser false con motivo_discrepancia"
            ),
        )

    # C6.5 regla 1: comuna, previsión o NSE no están en los datos; mencionarlos rechaza (fail-closed).
    hallado = atributo_no_disponible(analisis)
    if hallado is not None:
        campo, atributo = hallado
        return ResultadoValidacion(
            False,
            correcciones=correcciones,
            motivo_rechazo=f"{MOTIVO_EQUIDAD}: {campo} menciona {atributo}, que no está en los datos",
        )

    # C6.5 regla 2: inasistencias con un verbo de bajada se guardan marcadas; decide el médico (U3).
    marcas = frases_revision_equidad(analisis)
    correcciones += [
        Correccion(tipo="revision_equidad", campo=m.campo, detalle=DETALLE_REVISION_EQUIDAD) for m in marcas
    ]
    return ResultadoValidacion(True, analisis=analisis, correcciones=correcciones, revision_equidad=marcas)


def mensaje_reintento(usuario: str, motivo_rechazo: str) -> str:
    """C6.7: el único reintento repite el mensaje original con el error de validación agregado."""
    return (
        f"{usuario}\n\nTu respuesta anterior fue rechazada por el validador del sistema: {motivo_rechazo}. "
        "Corrige el análisis y vuelve a llamar a registrar_analisis."
    )


def entrada_de_analisis(a: AnalisisIA) -> dict[str, Any]:
    """Un análisis validado como entrada de herramienta (para comprobar la idempotencia)."""
    datos = a.model_dump(mode="json")
    datos.pop("metadatos")
    return datos
