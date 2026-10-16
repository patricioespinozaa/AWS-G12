"""Estrategias y ayudantes de U3 (bandeja): evaluaciones, filas, filtros, líneas de tiempo y decisiones.

Los ayudantes de salidas arman un lote sintético en carpetas temporales (nunca en ``salidas/`` real) y
guardan análisis construidos a mano: ninguna prueba llama a Bedrock.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from hypothesis import strategies as st

from ayudantes import evento, medicion, perfil_base
from estrategias.copiloto import correr_lote, entrada_desde_datos, escribir_dataset
from hlf_priorizacion.bandeja.filas import ESTADOS_DECISION, TIPOS_RESULTADO, FilaBandeja, Filtros, construir_filas
from hlf_priorizacion.copiloto.modelos import RegistroAnalisis, UsoModelo
from hlf_priorizacion.copiloto.persistencia import guardar_analisis
from hlf_priorizacion.modelos import NIVELES, AnalisisIA, Bandera, Decision, Evaluacion, Piso, RegistroCitado

V = "reglas-v0.1.0"
CORTE_A = date(2026, 7, 19)
CORTE_B = date(2026, 7, 20)
CODIGOS_BANDERA = ("BR_EVENTO_GRAVE_30D", "BR_MEDICION_EXTREMA")
CODIGOS_PISO = ("PISO_CRITICO", "PISO_ALTO")
ESPECIALIDADES = ("Cardiología", "Neurología", "Traumatología")
MEDICOS = ("MED-DEMO-01", "MED-DEMO-02", "MED-DEMO-03")


# --------------------------------------------------------------------------- evaluaciones y filas


@st.composite
def evaluaciones(draw: st.DrawFn, id_solicitud: str, corte: date = CORTE_B) -> Evaluacion:
    """``Evaluacion`` válida y mínima. Puntajes con empates frecuentes para ejercitar el desempate por ID."""
    tipo = draw(st.sampled_from(TIPOS_RESULTADO))
    inicial = draw(st.sampled_from(["baja", "media", "alta"]))
    ids = ["EV-000001"]
    if tipo == "exclusion":
        return Evaluacion(
            id_solicitud=id_solicitud,
            fecha_corte=corte,
            version_reglas=V,
            huella_contexto="sha256:prueba",
            prioridad_inicial=inicial,
            puntaje=None,
            nivel_calculado=None,
            nivel_propuesto=None,
            tipo_resultado="exclusion",
            codigo_exclusion=draw(st.sampled_from(["EX_FALLECIDO", "EX_ATENDIDO_INFERIDO"])),
            confianza="alta",
        )
    nivel = draw(st.sampled_from(NIVELES))
    puntaje = draw(st.one_of(st.sampled_from([0.0, 37.5, 50.0, 100.0]), st.floats(0, 100, allow_nan=False)))
    return Evaluacion(
        id_solicitud=id_solicitud,
        fecha_corte=corte,
        version_reglas=V,
        huella_contexto="sha256:prueba",
        prioridad_inicial=inicial,
        puntaje=puntaje,
        nivel_calculado=nivel,
        nivel_propuesto=nivel,
        tipo_resultado=tipo,
        banderas=[Bandera(codigo=c, ids_registro=ids) for c in draw(st.sets(st.sampled_from(CODIGOS_BANDERA)))],
        pisos=[Piso(codigo=c, ids_registro=ids) for c in draw(st.sets(st.sampled_from(CODIGOS_PISO), max_size=1))],
        confianza=draw(st.sampled_from(["alta", "media", "baja"])),
    )


def ids_solicitud(max_size: int = 25) -> st.SearchStrategy[list[str]]:
    return st.lists(st.integers(1, 60).map(lambda i: f"IC-HLF-{i:05d}"), unique=True, max_size=max_size)


@st.composite
def listas_evaluaciones(draw: st.DrawFn, corte: date = CORTE_B, max_size: int = 25) -> list[Evaluacion]:
    return [draw(evaluaciones(i, corte)) for i in draw(ids_solicitud(max_size))]


@st.composite
def filas(draw: st.DrawFn) -> list[FilaBandeja]:
    evs = draw(listas_evaluaciones())
    ids = [ev.id_solicitud for ev in evs]
    analisis = {i: draw(st.sampled_from(["si", "no", "fallido"])) for i in ids}
    equidad = [i for i in ids if analisis[i] == "si" and draw(st.booleans())]
    decisiones = {i: draw(st.sampled_from(ESTADOS_DECISION)) for i in ids}
    especialidades = {i: draw(st.sampled_from(ESPECIALIDADES)) for i in ids}
    return construir_filas(evs, especialidades, analisis, equidad, decisiones)


@st.composite
def filtros(draw: st.DrawFn) -> Filtros:
    return Filtros(
        especialidades=frozenset(draw(st.sets(st.sampled_from(ESPECIALIDADES), max_size=2))),
        niveles=frozenset(draw(st.sets(st.sampled_from(NIVELES), max_size=2))),
        tipos=frozenset(draw(st.sets(st.sampled_from(TIPOS_RESULTADO), max_size=2))),
        incluir_sin_alerta=draw(st.booleans()),
        solo_con_analisis=draw(st.booleans()),
        solo_con_equidad=draw(st.booleans()),
        estados_decision=frozenset(draw(st.sets(st.sampled_from(ESTADOS_DECISION), max_size=2))),
    )


@st.composite
def cortes_y_lineas(
    draw: st.DrawFn,
) -> tuple[date, date, list[Evaluacion], list[Evaluacion], dict[str, list[RegistroCitado]]]:
    """Dos cortes (A <= B), sus propuestas (con solicitudes compartidas) y una línea de tiempo por solicitud."""
    a = draw(st.dates(date(2026, 6, 1), date(2026, 9, 30)))
    b = a + timedelta(days=draw(st.integers(0, 20)))
    ids = draw(ids_solicitud())
    solo_a = draw(st.sets(st.sampled_from(ids))) if ids else set()
    solo_b = draw(st.sets(st.sampled_from(ids))) if ids else set()
    props_a = [draw(evaluaciones(i, a)) for i in ids if i not in solo_b]
    props_b = [draw(evaluaciones(i, b)) for i in ids if i not in solo_a]
    lineas = {
        i: [
            RegistroCitado(
                fecha=a + timedelta(days=draw(st.integers(-10, 25))),
                tipo_registro="evento",
                id_registro=f"EV-{n:06d}",
                descripcion="evento sintético",
            )
            for n in range(draw(st.integers(0, 4)))
        ]
        for i in ids
    }
    return a, b, props_a, props_b, lineas


# --------------------------------------------------------------------------- decisiones


@st.composite
def decisiones_validas(draw: st.DrawFn, id_solicitud: str = "IC-HLF-00002") -> Decision:
    propuesta = draw(st.sampled_from(NIVELES))
    tipo = draw(st.sampled_from(["aceptada", "ajustada", "rechazada"]))
    final: str | None
    if tipo == "aceptada":
        final = draw(st.sampled_from([propuesta, None]))
    elif tipo == "ajustada":
        final = draw(st.sampled_from([n for n in NIVELES if n != propuesta]))
    else:
        final = None
    motivo = draw(st.text(min_size=1, max_size=40).filter(str.strip)) if tipo != "aceptada" else None
    return Decision.model_validate(
        {
            "id_decision": draw(st.text("0123456789ABCDEFGHJKMNPQRSTVWXYZ", min_size=26, max_size=26)),
            "id_solicitud": id_solicitud,
            "fecha_corte": CORTE_B,
            "version_reglas": V,
            "id_analisis": draw(st.one_of(st.none(), st.just("01ANALISIS"))),
            "decision": tipo,
            "prioridad_propuesta": propuesta,
            "prioridad_final": final,
            "motivo": motivo,
            "usuario": draw(st.sampled_from(MEDICOS)),
            "timestamp": datetime(2026, 7, 20, tzinfo=UTC) + timedelta(seconds=draw(st.integers(0, 5))),
        }
    )


# --------------------------------------------------------------------------- salidas sintéticas en temporales


def perfiles_demo() -> list[dict[str, Any]]:
    """Dos pacientes: IC-TST-00001 sube a crítica el 2026-07-20 (urgencia ESI 2); IC-TST-00002 sin registros."""
    p1 = perfil_base(
        eventos_clinicos=[evento("EV-000001", "2026-07-20", "visita_urgencia", "triage ESI 2", "grave")],
        mediciones=[
            medicion("2026-06-01", "presion_sistolica", 120, "mmHg"),
            medicion("2026-07-08", "presion_sistolica", 167, "mmHg", True),
        ],
    )
    p2 = perfil_base(id_paciente="PAC-TST-00002")
    p2["lista_espera"]["id_solicitud"] = "IC-TST-00002"
    return [p1, p2]


def preparar_salidas(base: Path, cortes: tuple[date, ...] = (CORTE_A, CORTE_B)) -> tuple[Path, Path]:
    """``(datos, salidas)`` temporales con el lote sintético corrido para ``cortes``."""
    datos = escribir_dataset(base / "datos", perfiles_demo())
    salidas = base / "salidas"
    correr_lote(datos, salidas, list(cortes))
    return datos, salidas


def registro_analisis(ev: Evaluacion, justificacion: str = "Coincide con la propuesta del motor.") -> RegistroAnalisis:
    """Análisis guardable construido a mano (sin modelo), coherente con la evaluación."""
    entrada = entrada_desde_datos(
        {
            "evaluacion_motor": json.loads(ev.model_dump_json()),
            "eventos": [],
            "riesgo_poblacional_cohorte": None,
        },
        ev.id_solicitud,
    )
    entrada["justificacion"] = justificacion
    entrada["metadatos"] = {
        "model_id": "modelo-falso",
        "version_prompt": "copiloto-v1.1.0",
        "request_id": None,
        "fecha_corte": ev.fecha_corte.isoformat(),
        "id_ejecucion": "prueba",
    }
    analisis = AnalisisIA.model_validate_json(json.dumps(entrada))
    return RegistroAnalisis(
        id_analisis=f"AN-{ev.id_solicitud}",
        id_solicitud=ev.id_solicitud,
        fecha_corte=ev.fecha_corte,
        version_reglas=ev.version_reglas,
        version_prompt="copiloto-v1.1.0",
        huella_prompt="sha256:prompt",
        model_id="modelo-falso",
        temperatura_enviada=None,
        intentos=1,
        huella_paquete="sha256:paquete",
        huella_salida="sha256:salida",
        uso=UsoModelo(tokens_entrada=1, tokens_salida=1, latencia_ms=1),
        analisis=analisis,
    )


def guardar_registros(salidas: Path, registros: list[RegistroAnalisis]) -> None:
    for corte in sorted({r.fecha_corte for r in registros}):
        guardar_analisis(salidas, corte, V, [r for r in registros if r.fecha_corte == corte])


FRASE_EQUIDAD = "Tiene inasistencias previas y se recomienda disminuir la prioridad."
