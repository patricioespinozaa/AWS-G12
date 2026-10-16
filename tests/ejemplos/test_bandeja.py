"""Pruebas de ejemplo de U3 (PBT-10).

- Recorrido de la demo sobre el dataset real y las salidas reales (solo lectura; se salta si faltan).
- Cada error del formulario de decisión, corte sin propuestas, solicitud sin análisis o con análisis
  fallido y huella distinta, con un lote sintético en carpetas temporales.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ayudantes import evento
from estrategias.bandeja import (
    CORTE_A,
    CORTE_B,
    FRASE_EQUIDAD,
    V,
    guardar_registros,
    perfiles_demo,
    preparar_salidas,
    registro_analisis,
)
from estrategias.copiloto import escribir_dataset
from hlf_priorizacion.bandeja.cambios import CortesInvalidos, comparar, validar_cortes
from hlf_priorizacion.bandeja.datos import (
    ADVERTENCIA_EQUIDAD,
    CorteSinPropuestas,
    cargar_corte,
    cargar_repositorio,
    cobertura,
    comando_copiloto,
    comando_lote,
    cortes_disponibles,
    reconstruir_contexto,
    rutas,
)
from hlf_priorizacion.bandeja.decisiones import (
    ErrorDecision,
    crear_decision,
    estados_del_corte,
    guardar_decision,
    historial,
    leer_decisiones,
    ruta_decisiones,
)
from hlf_priorizacion.bandeja.filas import Filtros, construir_filas, filtrar, ordenar
from hlf_priorizacion.logs import FormatoJSON, obtener_logger
from hlf_priorizacion.modelos import Evaluacion

RAIZ = Path(__file__).resolve().parents[2]
DATOS_REALES = RAIZ / "data" / "dataset_hlf_ambulatorio"
SALIDAS_REALES = RAIZ / "salidas"
C_0719, C_0720 = date(2026, 7, 19), date(2026, 7, 20)


# --------------------------------------------------------------------------- recorrido de la demo (datos reales)


@pytest.fixture(scope="module")
def reales() -> tuple[Path, Path]:
    if not (DATOS_REALES / "perfiles.json").is_file():
        pytest.skip(f"Dataset real no disponible en {DATOS_REALES} (está en .gitignore)")
    if C_0720 not in cortes_disponibles(SALIDAS_REALES) or C_0719 not in cortes_disponibles(SALIDAS_REALES):
        pytest.skip(f"Faltan las salidas reales de 2026-07-19/20 en {SALIDAS_REALES}: corra {comando_lote(C_0719)}")
    return DATOS_REALES, SALIDAS_REALES


def test_demo_00002_baja_el_0719_y_critica_el_0720_con_ev_000004(reales: tuple[Path, Path]) -> None:
    datos, salidas = reales
    a, b = cargar_corte(salidas, C_0719), cargar_corte(salidas, C_0720)
    ev_a = a.propuestas["IC-HLF-00002"]
    assert ev_a.nivel_propuesto == "baja" and ev_a.tipo_resultado == "sin_alerta" and not ev_a.alertas_gestion
    # Paso 1: en la bandeja por defecto no aparece (sin alerta); con "incluir sin alerta", sí y en baja.
    filas_a = ordenar(construir_filas(a.propuestas.values(), a.especialidades, {}, [], {}))
    assert "IC-HLF-00002" not in {f.id_solicitud for f in filtrar(filas_a, Filtros())}
    assert "IC-HLF-00002" in {f.id_solicitud for f in filtrar(filas_a, Filtros(incluir_sin_alerta=True))}

    # Paso 2: ¿Qué cambió? 07-19 -> 07-20.
    repo = cargar_repositorio(datos)
    cmp = comparar(
        a.propuestas.values(),
        b.propuestas.values(),
        C_0719,
        C_0720,
        lambda ev: reconstruir_contexto(repo, ev).linea_tiempo,
    )
    (c,) = [c for c in cmp.cambios if c.id_solicitud == "IC-HLF-00002"]
    assert (c.nivel_a, c.nivel_b) == ("baja", "critica")
    assert "EV-000004" in c.registros_nuevos
    assert "BR_EVENTO_GRAVE_30D" in c.banderas_nuevas
    assert cmp.cambios[0].nivel_b == "critica"

    # Paso 3: detalle 07-20 con factores citados, línea de tiempo verificada y análisis del copiloto.
    ev_b = b.propuestas["IC-HLF-00002"]
    assert any("EV-000004" in f.ids_registro for f in ev_b.factores)
    rc = reconstruir_contexto(repo, ev_b)
    assert rc.estado == "ok"
    assert "EV-000004" in {r.id_registro for r in rc.linea_tiempo}
    assert all(r.fecha <= C_0720 for r in rc.linea_tiempo)
    assert b.estado_analisis("IC-HLF-00002") == "si"
    analisis = b.analisis["IC-HLF-00002"].analisis
    assert analisis.prioridad_sugerida == "critica" and analisis.acuerdo_con_motor.acuerdo
    assert analisis.nota_preconsulta


def test_demo_00349_muestra_la_advertencia_de_equidad(reales: tuple[Path, Path]) -> None:
    _, salidas = reales
    a = cargar_corte(salidas, C_0719)
    marcas = a.marcas_equidad("IC-HLF-00349")
    assert [m.campo for m in marcas] == ["resumen"]
    # Guardado antes de la marca del sistema: la regla de U2 se aplica al leer (sin modelo).
    assert a.analisis["IC-HLF-00349"].revision_equidad == []
    assert ADVERTENCIA_EQUIDAD.startswith("El análisis menciona inasistencias junto a una bajada de prioridad.")
    assert ADVERTENCIA_EQUIDAD.endswith("La inasistencia no baja la prioridad clínica: revise antes de decidir")
    assert cobertura(a, [])["analisis_equidad"] == 1


def test_demo_cobertura_0720_coincide_con_el_resumen_del_lote(reales: tuple[Path, Path]) -> None:
    _, salidas = reales
    b = cargar_corte(salidas, C_0720)
    cob = cobertura(b, [])
    assert b.resumen is not None
    assert cob["evaluadas"] == b.resumen["solicitudes"]["evaluadas"]
    assert cob["exclusiones"] == b.resumen["solicitudes"]["exclusiones"]
    assert cob["cambios_de_nivel"] == b.resumen["solicitudes"]["cambios_de_nivel"]
    assert cob["analisis_guardados"] == 5


# --------------------------------------------------------------------------- lote sintético en temporales


@pytest.fixture
def lote(tmp_path: Path) -> tuple[Path, Path]:
    return preparar_salidas(tmp_path)


def _ev(salidas: Path, id_solicitud: str = "IC-TST-00001", corte: date = CORTE_B) -> Evaluacion:
    return cargar_corte(salidas, corte).propuestas[id_solicitud]


def test_rutas_por_variables_de_entorno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HLF_SALIDAS", raising=False)
    monkeypatch.delenv("HLF_DATOS", raising=False)
    assert rutas(tmp_path) == (tmp_path / "salidas", tmp_path / "data" / "dataset_hlf_ambulatorio")
    monkeypatch.setenv("HLF_SALIDAS", str(tmp_path / "s"))
    monkeypatch.setenv("HLF_DATOS", str(tmp_path / "d"))
    assert rutas(RAIZ) == (tmp_path / "s", tmp_path / "d")


def test_corte_sin_propuestas_muestra_el_comando(lote: tuple[Path, Path], tmp_path: Path) -> None:
    _, salidas = lote
    assert cortes_disponibles(salidas) == [CORTE_A, CORTE_B]
    assert cortes_disponibles(tmp_path / "vacia") == []
    with pytest.raises(CorteSinPropuestas) as e:
        cargar_corte(salidas, date(2026, 8, 10))
    assert e.value.comando == "uv run hlf-lote --fecha-corte 2026-08-10"


def test_solicitud_sin_analisis_queda_pendiente_con_el_comando(lote: tuple[Path, Path]) -> None:
    _, salidas = lote
    dc = cargar_corte(salidas, CORTE_B)
    assert dc.analisis == {} and dc.estado_analisis("IC-TST-00001") == "no"
    assert dc.marcas_equidad("IC-TST-00001") == []
    assert comando_copiloto(CORTE_B) == "uv run hlf-copiloto --fecha-corte 2026-07-20"


def test_analisis_fallido_trae_su_motivo(lote: tuple[Path, Path]) -> None:
    _, salidas = lote
    carpeta = salidas / "analisis" / f"fecha_corte={CORTE_B.isoformat()}" / f"version_reglas={V}"
    carpeta.mkdir(parents=True)
    fallido = {
        "id_solicitud": "IC-TST-00001",
        "fecha_corte": CORTE_B.isoformat(),
        "version_reglas": V,
        "version_prompt": "copiloto-v1.2.0",
        "model_id": "modelo-falso",
        "id_ejecucion": "prueba",
        "motivo": "validacion: esquema",
        "intentos": 2,
    }
    (carpeta / "fallidos.jsonl").write_text(json.dumps(fallido) + "\n", encoding="utf-8")
    dc = cargar_corte(salidas, CORTE_B)
    assert dc.estado_analisis("IC-TST-00001") == "fallido"
    assert dc.fallidos["IC-TST-00001"].motivo == "validacion: esquema"
    assert cobertura(dc, [])["analisis_fallidos"] == 1


def test_analisis_con_marca_de_equidad_y_estado_en_la_fila(lote: tuple[Path, Path]) -> None:
    _, salidas = lote
    guardar_registros(salidas, [registro_analisis(_ev(salidas), FRASE_EQUIDAD)])
    dc = cargar_corte(salidas, CORTE_B)
    assert dc.estado_analisis("IC-TST-00001") == "si"
    assert [(m.campo, m.texto) for m in dc.marcas_equidad("IC-TST-00001")] == [("justificacion", FRASE_EQUIDAD)]
    fila = next(
        f
        for f in construir_filas(
            dc.propuestas.values(), dc.especialidades, {i: dc.estado_analisis(i) for i in dc.propuestas},
            ["IC-TST-00001"], {},
        )
        if f.id_solicitud == "IC-TST-00001"
    )
    assert fila.tiene_analisis and fila.revision_equidad and fila.estado_decision == "pendiente"
    assert fila.especialidad == "Cardiología"


def test_huella_distinta_no_muestra_linea_de_tiempo(lote: tuple[Path, Path]) -> None:
    datos, salidas = lote
    ev = _ev(salidas)
    assert reconstruir_contexto(cargar_repositorio(datos), ev).estado == "ok"
    perfiles = perfiles_demo()
    perfiles[0]["eventos_clinicos"].append(evento("EV-000002", "2026-07-10", "hospitalizacion", "ingreso UCI", "grave"))
    escribir_dataset(datos, perfiles)  # los datos cambiaron después del lote
    rc = reconstruir_contexto(cargar_repositorio(datos), ev)
    assert rc.estado == "huella_distinta" and rc.contexto is None and rc.linea_tiempo == []
    escribir_dataset(datos, perfiles_demo()[1:])  # el paciente desapareció
    assert reconstruir_contexto(cargar_repositorio(datos), ev).estado == "contexto_no_disponible"


def test_que_cambio_sintetico(lote: tuple[Path, Path]) -> None:
    datos, salidas = lote
    a, b = cargar_corte(salidas, CORTE_A), cargar_corte(salidas, CORTE_B)
    repo = cargar_repositorio(datos)
    cmp = comparar(a.propuestas.values(), b.propuestas.values(), CORTE_A, CORTE_B,
                   lambda ev: reconstruir_contexto(repo, ev).linea_tiempo)
    (c,) = [c for c in cmp.cambios if c.id_solicitud == "IC-TST-00001"]
    assert c.nivel_b == "critica" and c.registros_nuevos == ("EV-000001",)
    with pytest.raises(CortesInvalidos):
        validar_cortes(CORTE_B, CORTE_A)
    with pytest.raises(CortesInvalidos):
        validar_cortes(CORTE_B, CORTE_B)


# --------------------------------------------------------------------------- formulario de decisión


INSTANTE = datetime(2026, 7, 20, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("opcion", "final", "motivo", "usuario", "mensaje"),
    [
        ("ajustar", None, "baja por evolución", "MED-DEMO-01", "ajustar exige prioridad_final"),
        ("ajustar", "critica", "igual a la propuesta", "MED-DEMO-01", "ajustar exige una prioridad_final distinta"),
        ("ajustar", "alta", "   ", "MED-DEMO-01", "ajustar exige motivo"),
        ("rechazar", None, None, "MED-DEMO-01", "rechazar exige motivo"),
        ("rechazar", None, "x" * 1001, "MED-DEMO-01", "el motivo admite hasta 1000 caracteres"),
        ("aceptar", None, None, "", "String should have at least 1 character"),
        ("borrar", None, None, "MED-DEMO-01", "elija aceptar, ajustar o rechazar"),
    ],
)
def test_cada_error_del_formulario_no_guarda(
    lote: tuple[Path, Path], opcion: str, final: str | None, motivo: str | None, usuario: str, mensaje: str
) -> None:
    _, salidas = lote
    ev = _ev(salidas)
    assert ev.nivel_propuesto == "critica"
    with pytest.raises(ErrorDecision) as e:
        crear_decision(evaluacion=ev, opcion=opcion, usuario=usuario, prioridad_final=final, motivo=motivo)
    assert any(mensaje in m for m in e.value.mensajes), e.value.mensajes
    assert not ruta_decisiones(salidas).exists()


def test_exclusion_no_se_decide() -> None:
    ev = Evaluacion(
        id_solicitud="IC-X", fecha_corte=CORTE_B, version_reglas=V, huella_contexto="sha256:x",
        prioridad_inicial="baja",
        puntaje=None, nivel_calculado=None, nivel_propuesto=None, tipo_resultado="exclusion",
        codigo_exclusion="EX_FALLECIDO", confianza="alta",
    )
    with pytest.raises(ErrorDecision):
        crear_decision(evaluacion=ev, opcion="aceptar", usuario="MED-DEMO-01")


def test_decisiones_se_agregan_y_la_ultima_es_la_vigente(lote: tuple[Path, Path]) -> None:
    _, salidas = lote
    ev = _ev(salidas)
    d1 = crear_decision(evaluacion=ev, opcion="aceptar", usuario="MED-DEMO-01", id_analisis="AN-1",
                        reloj=lambda: INSTANTE)
    d2 = crear_decision(evaluacion=ev, opcion="ajustar", usuario="MED-DEMO-02", prioridad_final="alta",
                        motivo="MOTIVO-SECRETO-NO-VA-A-AUDITORIA", reloj=lambda: INSTANTE.replace(hour=13))
    registro = io.StringIO()
    manejador = logging.StreamHandler(registro)
    manejador.setFormatter(FormatoJSON())
    logger = obtener_logger()
    logger.addHandler(manejador)
    nivel_previo = logger.level
    logger.setLevel(logging.INFO)
    try:
        guardar_decision(salidas, d1)
        guardar_decision(salidas, d2)
    finally:
        logger.removeHandler(manejador)
        logger.setLevel(nivel_previo)
    logs = registro.getvalue()
    assert logs.count("decisión médica guardada") == 2 and "MOTIVO-SECRETO" not in logs
    assert d1.prioridad_final == "critica" and d1.id_analisis == "AN-1" and len(d1.id_decision) == 26
    assert leer_decisiones(salidas) == [d1, d2]
    assert historial(leer_decisiones(salidas), "IC-TST-00001", CORTE_B, V) == [d2, d1]
    assert estados_del_corte(leer_decisiones(salidas), CORTE_B, V) == {"IC-TST-00001": "ajustada"}
    auditoria = (salidas / "auditoria" / "eventos.jsonl").read_text(encoding="utf-8")
    eventos = [json.loads(x) for x in auditoria.splitlines()]
    medicas = [e for e in eventos if e["tipo"] == "decision_medica"]
    assert [(e["id_decision"], e["decision"], e["prioridad_final"]) for e in medicas] == [
        (d1.id_decision, "aceptada", "critica"),
        (d2.id_decision, "ajustada", "alta"),
    ]
    assert medicas[1]["actor"] == "medico:MED-DEMO-02"
    assert all("motivo" not in e for e in medicas)
    assert "MOTIVO-SECRETO" not in (salidas / "auditoria" / "eventos.jsonl").read_text(encoding="utf-8")
    # Las propuestas no cambian con las decisiones (B5.6).
    assert _ev(salidas) == ev
