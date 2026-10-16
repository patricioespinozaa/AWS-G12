"""Estrategias de dominio compartidas (PBT-07, sección 16.3 de docs/contexto-tecnico.md).

Generan perfiles crudos (``dict`` con el formato de ``perfiles.json``) que cumplen el contrato:
paciente (edad 19-90), solicitud (CIE-10 del catálogo), eventos (solo combinaciones catalogadas),
mediciones (normales, de riesgo, extremas, imposibles y en el borde exacto de los rangos), citas
(estados válidos) y una fecha de corte válida. Incluyen casos borde: perfil sin registros, evento el
mismo día del corte y defunción el día del corte.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from hypothesis import strategies as st

from hlf_priorizacion.calidad.reglas import LIMITES_PLAUSIBILIDAD
from hlf_priorizacion.contrato.catalogos import COMBINACIONES_EVENTO, ESTADOS_CITA, UNIDAD_POR_TIPO
from hlf_priorizacion.motor.parametros import cargar_parametros

FECHA_EXTRACCION = date(2026, 10, 13)
INICIO_INGRESOS = date(2025, 4, 1)
FIN_INGRESOS = date(2026, 9, 30)

CIE10_POR_ESPECIALIDAD = {
    "Broncopulmonar": ["J45", "J44"],
    "Cardiología": ["I10", "I20", "I50"],
    "Endocrinología": ["E11", "E66", "E03"],
    "Gastroenterología": ["K21", "K70"],
    "Neurología": ["G43", "G40"],
    "Salud Mental": ["F41", "F32"],
    "Traumatología": ["M54", "M75", "M17"],
}
ESPECIALIDADES = sorted(CIE10_POR_ESPECIALIDAD)
COMBINACIONES = sorted(COMBINACIONES_EVENTO.items())
_PARAMS = cargar_parametros()
RANGOS = _PARAMS.mediciones.rangos
TIPOS = sorted(UNIDAD_POR_TIPO)
CATEGORIAS_MEDICION = ("normal", "riesgo", "extremo", "imposible", "borde")


def fechas(desde: date, hasta: date) -> st.SearchStrategy[date]:
    if hasta < desde:
        hasta = desde
    return st.integers(0, (hasta - desde).days).map(lambda d: desde + timedelta(days=d))


def _a_json(tipo: str, valor: float) -> int | float:
    return round(valor, 1) if tipo == "HbA1c" else round(valor)


@st.composite
def valores_medicion(draw: st.DrawFn, tipo: str, categoria: str | None = None) -> int | float:
    """Valor de una medición según la categoría: normal, riesgo, extremo, imposible o borde."""
    cat = categoria or draw(st.sampled_from(CATEGORIAS_MEDICION))
    r = RANGOS[tipo]
    p_inf, p_sup = (float(x) for x in LIMITES_PLAUSIBILIDAD[tipo])
    paso = 0.1 if tipo == "HbA1c" else 1.0
    if cat == "normal":
        v = draw(st.floats(r.minimo, r.maximo))
    elif cat == "riesgo":
        lados = []
        if r.minimo - paso >= p_inf:
            lados.append(draw(st.floats(p_inf, r.minimo - paso)))
        if r.maximo + paso <= p_sup:
            lados.append(draw(st.floats(r.maximo + paso, p_sup)))
        v = draw(st.sampled_from(lados)) if lados else r.maximo
    elif cat == "extremo":
        v = draw(st.sampled_from([p_inf, p_sup, p_inf + paso, p_sup - paso]))
    elif cat == "imposible":
        v = draw(st.one_of(st.floats(p_inf - 50, p_inf - paso), st.floats(p_sup + paso, p_sup + 50)))
    else:  # borde exacto del rango normal o de plausibilidad
        v = draw(st.sampled_from([r.minimo, r.maximo, p_inf, p_sup]))
    valor = _a_json(tipo, v)
    # Tras redondear, un valor "imposible" debe seguir fuera de plausibilidad.
    if cat == "imposible" and p_inf <= float(valor) <= p_sup:
        valor = _a_json(tipo, p_sup + paso * 2)
    return valor


@st.composite
def mediciones(draw: st.DrawFn, desde: date, hasta: date, categoria: str | None = None) -> dict[str, Any]:
    tipo = draw(st.sampled_from(TIPOS))
    valor = draw(valores_medicion(tipo, categoria))
    r = RANGOS[tipo]
    return {
        "fecha_medicion": draw(fechas(desde, hasta)).isoformat(),
        "tipo_medicion": tipo,
        "valor": valor,
        "unidad": UNIDAD_POR_TIPO[tipo],
        "fuera_de_rango": not (r.minimo <= float(Decimal(str(valor))) <= r.maximo),
    }


@st.composite
def eventos(draw: st.DrawFn, id_evento: str, desde: date, hasta: date, especialidad: str) -> dict[str, Any]:
    (tipo, subtipo), severidad = draw(st.sampled_from(COMBINACIONES))
    esp = draw(st.one_of(st.just(especialidad), st.sampled_from(ESPECIALIDADES)))
    return {
        "id_evento": id_evento,
        "fecha_evento": draw(fechas(desde, hasta)).isoformat(),
        "tipo_evento": tipo,
        "subtipo": subtipo,
        "severidad": severidad,
        "detalle": f"{subtipo} ({esp})",
    }


@st.composite
def citas(
    draw: st.DrawFn, id_cita: str, desde: date, hasta: date, especialidad: str, estados: tuple[str, ...] = ESTADOS_CITA
) -> dict[str, Any]:
    estado = draw(st.sampled_from(estados))
    return {
        "id_cita": id_cita,
        "id_box": f"BOX-{draw(st.integers(1, 20)):02d}",
        "fecha_cita": draw(fechas(desde, hasta)).isoformat(),
        "especialidad": draw(st.one_of(st.just(especialidad), st.sampled_from(ESPECIALIDADES))),
        "estado_cita": estado,
        "minutos_atencion_real": draw(st.integers(15, 55)) if estado == "asistio" else "",
    }


@st.composite
def perfiles(
    draw: st.DrawFn,
    estado: str | None = None,
    max_eventos: int = 6,
    max_mediciones: int = 10,
    max_citas: int = 4,
    permitir_fallecido: bool = True,
) -> dict[str, Any]:
    """Perfil crudo completo y válido según el contrato."""
    i = draw(st.integers(1, 99999))
    especialidad = draw(st.sampled_from(ESPECIALIDADES))
    ingreso = draw(fechas(INICIO_INGRESOS, FIN_INGRESOS))
    fallecido = permitir_fallecido and estado is None and draw(st.integers(0, 4)) == 0
    defuncion = draw(fechas(ingreso, FECHA_EXTRACCION)) if fallecido else None
    fin = defuncion or FECHA_EXTRACCION
    if estado is None:
        estado = "fallecido" if fallecido else draw(st.sampled_from(["en_espera", "en_espera", "atendido"]))
    sin_registros = draw(st.integers(0, 9)) == 0
    n_ev = 0 if sin_registros else draw(st.integers(0, max_eventos))
    n_med = 0 if sin_registros else draw(st.integers(0, max_mediciones))
    n_ci = 0 if sin_registros else draw(st.integers(0, max_citas))
    desde = ingreso - timedelta(days=draw(st.sampled_from([0, 0, 0, 20])))
    return {
        "id_paciente": f"PAC-HLF-{i:05d}",
        "paciente": {
            "nombre_fantasia": f"Paciente Sintético {i:03d}",
            "edad": draw(st.integers(19, 90)),
            "sexo": draw(st.sampled_from(["F", "M"])),
            "comuna": draw(st.sampled_from(["La Florida", "Puente Alto", "La Pintana"])),
            "prevision": draw(st.sampled_from(["FONASA A", "FONASA B", "ISAPRE"])),
            "nivel_socioeconomico": draw(st.sampled_from(["bajo", "medio-bajo", "medio"])),
            "fallecido": fallecido,
            "fecha_defuncion": defuncion.isoformat() if defuncion else None,
        },
        "lista_espera": {
            "id_solicitud": f"IC-HLF-{i:05d}",
            "especialidad": especialidad,
            "sub_especialidad": f"{especialidad} adulto",
            "diagnostico_cie10": draw(st.sampled_from(CIE10_POR_ESPECIALIDAD[especialidad])),
            "diagnostico_texto": "diagnóstico sintético",
            "prioridad_inicial": draw(st.sampled_from(["alta", "media", "baja"])),
            "fecha_ingreso_lista": ingreso.isoformat(),
            "origen_derivacion": draw(st.sampled_from(["CESFAM/APS", "Urgencia", "Hospitalización"])),
            "estado": estado,
        },
        "eventos_clinicos": [draw(eventos(f"EV-{k + 1:06d}", desde, fin, especialidad)) for k in range(n_ev)],
        "mediciones": [draw(mediciones(desde, fin)) for _ in range(n_med)],
        "citaciones": [draw(citas(f"CT-{k + 1:06d}", desde, fin, especialidad)) for k in range(n_ci)],
    }


TIPOS_SIC_EXTRA = ("par_listado", "misma_especialidad", "otra_especialidad", "duplicada")
_DOC = _PARAMS.documento_relaciones
PARES_DIAGNOSTICO = [(p.a, p.b) for p in _DOC.diagnosticos.pares] if _DOC is not None else []
ESPECIALIDAD_DE_CIE10 = {c: e for e, cs in CIE10_POR_ESPECIALIDAD.items() for c in cs}


@st.composite
def solicitudes_extra(
    draw: st.DrawFn,
    principal: dict[str, Any],
    id_solicitud: str,
    tipo: str | None = None,
    hasta: date = FIN_INGRESOS,
    estados: tuple[str, ...] = ("en_espera", "en_espera", "en_espera", "atendido"),
) -> dict[str, Any]:
    """Otra SIC del mismo paciente (reglas-v0.2.0, R11): con un par de diagnósticos listado en el documento de
    relaciones (de la misma u otra especialidad), de la misma especialidad con otro CIE-10, de otra especialidad
    (casi siempre sin par) o duplicada (misma especialidad y CIE-10, otra subespecialidad)."""
    tipo = tipo or draw(st.sampled_from(TIPOS_SIC_EXTRA))
    esp, cie_principal = principal["especialidad"], principal["diagnostico_cie10"]
    socios = [b if a == cie_principal else a for a, b in PARES_DIAGNOSTICO if cie_principal in (a, b)]
    if tipo == "par_listado" and socios:
        cie10 = draw(st.sampled_from(socios))
        esp = ESPECIALIDAD_DE_CIE10[cie10]
    elif tipo == "duplicada":
        cie10 = cie_principal
    elif tipo in {"misma_especialidad", "par_listado"}:
        otros = [c for c in CIE10_POR_ESPECIALIDAD[esp] if c != cie_principal]
        cie10 = draw(st.sampled_from(otros))
    else:
        esp = draw(st.sampled_from([e for e in ESPECIALIDADES if e != principal["especialidad"]]))
        cie10 = draw(st.sampled_from(CIE10_POR_ESPECIALIDAD[esp]))
    return {
        "id_solicitud": id_solicitud,
        "especialidad": esp,
        "sub_especialidad": f"{esp} subespecialidad {draw(st.integers(1, 3))}",
        "diagnostico_cie10": cie10,
        "diagnostico_texto": "diagnóstico sintético",
        "prioridad_inicial": draw(st.sampled_from(["alta", "media", "baja"])),
        "fecha_ingreso_lista": draw(fechas(INICIO_INGRESOS, hasta)).isoformat(),
        "origen_derivacion": draw(st.sampled_from(["CESFAM/APS", "Urgencia", "Hospitalización"])),
        "estado": draw(st.sampled_from(estados)),
    }


@st.composite
def perfil_multi_y_corte(
    draw: st.DrawFn, min_solicitudes: int = 1, max_solicitudes: int = 3, **kw: Any
) -> tuple[dict[str, Any], date]:
    """Perfil con 1 a 3 SIC (``lista_espera`` como lista) y una fecha de corte válida para la primera.

    Las SIC extra pueden ingresar después del corte (para probar que no hay fuga de información futura).
    Por defecto sin fallecidos: un paciente fallecido excluye todas sus SIC y no ejercita R11.
    """
    kw.setdefault("permitir_fallecido", False)
    raw, corte = draw(perfil_y_corte(**kw))
    principal = raw["lista_espera"]
    # sampled_from se reduce hacia el primer elemento: se ordena para que lo simple sea "2 SIC vigentes".
    n = draw(st.sampled_from([k for k in (2, 3, 1) if min_solicitudes <= k <= max_solicitudes]))
    sufijo = principal["id_solicitud"].rsplit("-", 1)[1]
    extras = []
    for k in range(1, n):
        # Casi siempre ingresada al corte; a veces después (no debe aportar).
        hasta = FIN_INGRESOS if draw(st.integers(0, 4)) == 4 else max(corte, INICIO_INGRESOS)
        extras.append(draw(solicitudes_extra(principal, f"IC-MUL{k}-{sufijo}", hasta=hasta)))
    raw["lista_espera"] = [principal, *extras]
    return raw, corte


def fechas_registro(perfil: dict[str, Any]) -> list[date]:
    return [date.fromisoformat(e["fecha_evento"]) for e in perfil["eventos_clinicos"]] + [
        date.fromisoformat(m["fecha_medicion"]) for m in perfil["mediciones"]
    ]


@st.composite
def fechas_corte(draw: st.DrawFn, perfil: dict[str, Any]) -> date:
    """Fecha de corte válida (entre el ingreso y la extracción), con casos borde."""
    ingreso = date.fromisoformat(perfil["lista_espera"]["fecha_ingreso_lista"])
    bordes = [f for f in fechas_registro(perfil) if f >= ingreso]
    if perfil["paciente"]["fecha_defuncion"]:
        bordes.append(date.fromisoformat(perfil["paciente"]["fecha_defuncion"]))
    bordes.append(FECHA_EXTRACCION)
    return draw(st.one_of(fechas(ingreso, FECHA_EXTRACCION), st.sampled_from(bordes)))


@st.composite
def perfil_y_corte(draw: st.DrawFn, **kw: Any) -> tuple[dict[str, Any], date]:
    perfil = draw(perfiles(**kw))
    return perfil, draw(fechas_corte(perfil))
