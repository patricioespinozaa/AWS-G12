"""Pruebas de interfaz de ``app/bandeja.py`` con ``streamlit.testing.v1.AppTest``.

Cada prueba apunta ``HLF_SALIDAS`` a una carpeta temporal: las decisiones nunca se escriben en ``salidas/``
real. Las de datos reales copian las salidas de 2026-07-19/20 a la carpeta temporal y leen el dataset real
(solo lectura); se saltan si faltan.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Markdown, Warning

from ayudantes import evento
from estrategias.bandeja import (
    CORTE_B,
    FRASE_EQUIDAD,
    guardar_registros,
    perfiles_demo,
    preparar_salidas,
    registro_analisis,
)
from estrategias.copiloto import escribir_dataset
from hlf_priorizacion.bandeja.datos import ADVERTENCIA_EQUIDAD, ROTULO_COPILOTO, cargar_corte
from hlf_priorizacion.bandeja.decisiones import leer_decisiones, ruta_decisiones

RAIZ = Path(__file__).resolve().parents[2]
APP = RAIZ / "app" / "bandeja.py"
DATOS_REALES = RAIZ / "data" / "dataset_hlf_ambulatorio"
SALIDAS_REALES = RAIZ / "salidas"
TIEMPO = 120


def _app(salidas: Path, datos: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("HLF_SALIDAS", str(salidas))
    monkeypatch.setenv("HLF_DATOS", str(datos))
    at = AppTest.from_file(str(APP), default_timeout=TIEMPO)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _ir(at: AppTest, pestana: str) -> None:
    at.session_state["app-pestana"] = pestana
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def _abrir_detalle(at: AppTest, medico: str, corte: str, id_solicitud: str) -> None:
    if medico:
        at.selectbox(key="lateral-medico").select(medico).run()
    at.selectbox(key="lateral-corte").select(corte).run()
    _ir(at, "Detalle")
    at.selectbox(key="detalle-solicitud").select(id_solicitud).run()
    assert not at.exception, [e.value for e in at.exception]


def _textos(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown] + [w.value for w in at.warning] + [i.value for i in at.info]


@pytest.fixture
def lote(tmp_path: Path) -> tuple[Path, Path]:
    return preparar_salidas(tmp_path)


# --------------------------------------------------------------------------- lote sintético


def test_la_app_carga_sin_errores_y_muestra_la_bandeja(
    lote: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    datos, salidas = lote
    at = _app(salidas, datos, monkeypatch)
    assert at.radio(key="app-pestana").options == ["Bandeja", "Detalle", "¿Qué cambió?", "Cobertura"]
    assert at.radio(key="app-pestana").value == "Bandeja"
    assert at.selectbox(key="lateral-medico").value == ""
    assert at.selectbox(key="lateral-corte").options == ["2026-07-19", "2026-07-20"]
    assert any("Demo local con datos sintéticos" in c.value for c in at.caption)
    at.selectbox(key="lateral-corte").select("2026-07-20").run()
    assert any("solicitudes ·" in m.value and "críticas" in m.value for m in at.markdown)
    assert at.dataframe  # tabla de la bandeja
    assert any("uv run hlf-copiloto --fecha-corte 2026-07-20" in i.value for i in at.info)


def test_sin_medico_no_se_puede_decidir(lote: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    datos, salidas = lote
    at = _app(salidas, datos, monkeypatch)
    _abrir_detalle(at, "", "2026-07-20", "IC-TST-00001")
    assert at.button(key="detalle-decision-guardar").disabled
    assert at.radio(key="detalle-decision-radio").disabled
    assert any("Elija un médico" in w.value for w in at.warning)


def test_guardar_una_decision_aceptada_en_carpeta_temporal(
    lote: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    datos, salidas = lote
    at = _app(salidas, datos, monkeypatch)
    _abrir_detalle(at, "MED-DEMO-01", "2026-07-20", "IC-TST-00001")
    assert any(ROTULO_COPILOTO in m.value for m in at.markdown)
    assert any("Análisis IA pendiente" in i.value for i in at.info)
    at.radio(key="detalle-decision-radio").set_value("aceptar")
    at.button(key="detalle-decision-guardar").click().run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    assert any("Decisión guardada: aceptada por Dra. Demo Uno" in s.value for s in at.success)
    (d,) = leer_decisiones(salidas)
    assert (d.id_solicitud, d.decision, d.usuario, d.prioridad_final) == (
        "IC-TST-00001",
        "aceptada",
        "MED-DEMO-01",
        "critica",
    )
    assert len(ruta_decisiones(salidas).read_text(encoding="utf-8").splitlines()) == 1
    auditoria = (salidas / "auditoria" / "eventos.jsonl").read_text(encoding="utf-8")
    eventos = [json.loads(x) for x in auditoria.splitlines()]
    (evento,) = [e for e in eventos if e["tipo"] == "decision_medica"]
    assert evento["id_decision"] == d.id_decision and "motivo" not in evento
    assert any("Vigente" in m.value and "aceptada" in m.value for m in at.markdown)
    _ir(at, "Bandeja")
    tabla = at.dataframe[0].value
    assert tabla.loc[tabla["ID"] == "IC-TST-00001", "Decisión"].tolist() == ["✔ aceptada"]


def test_error_del_formulario_se_muestra_y_no_guarda(lote: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    datos, salidas = lote
    at = _app(salidas, datos, monkeypatch)
    _abrir_detalle(at, "MED-DEMO-02", "2026-07-20", "IC-TST-00001")
    at.radio(key="detalle-decision-radio").set_value("rechazar").run()
    at.button(key="detalle-decision-guardar").click().run()
    assert any("rechazar exige motivo" in e.value for e in at.error)
    assert not ruta_decisiones(salidas).exists()
    at.radio(key="detalle-decision-radio").set_value("ajustar").run()
    assert "critica" not in at.selectbox(key="detalle-decision-prioridad").options
    at.text_area(key="detalle-decision-motivo").input("MOTIVO-PRIVADO")
    at.button(key="detalle-decision-guardar").click().run()
    assert any("ajustar exige prioridad_final" in e.value for e in at.error)
    assert not ruta_decisiones(salidas).exists()
    at.selectbox(key="detalle-decision-prioridad").select("alta")
    at.text_area(key="detalle-decision-motivo").input("MOTIVO-PRIVADO")
    at.button(key="detalle-decision-guardar").click().run()
    (d,) = leer_decisiones(salidas)
    assert (d.decision, d.prioridad_final, d.motivo) == ("ajustada", "alta", "MOTIVO-PRIVADO")
    assert "MOTIVO-PRIVADO" not in (salidas / "auditoria" / "eventos.jsonl").read_text(encoding="utf-8")


def test_advertencia_de_equidad_antes_del_analisis(lote: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    datos, salidas = lote
    ev = cargar_corte(salidas, CORTE_B).propuestas["IC-TST-00001"]
    guardar_registros(salidas, [registro_analisis(ev, FRASE_EQUIDAD)])
    at = _app(salidas, datos, monkeypatch)
    _abrir_detalle(at, "MED-DEMO-01", "2026-07-20", "IC-TST-00001")
    (aviso,) = [w for w in at.warning if ADVERTENCIA_EQUIDAD in w.value]
    assert "justificacion" in aviso.value and "inasistencias previas" in aviso.value
    orden = [n for n in at.main if isinstance(n, Warning | Markdown)]  # recorrido en orden de la página
    i_aviso = next(i for i, n in enumerate(orden) if ADVERTENCIA_EQUIDAD in n.value)
    i_rotulo = next(i for i, n in enumerate(orden) if ROTULO_COPILOTO in n.value)
    assert i_aviso < i_rotulo
    assert at.text_area(key="detalle-nota-IC-TST-00001").disabled


def test_que_cambio_y_cobertura_cargan(lote: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    datos, salidas = lote
    at = _app(salidas, datos, monkeypatch)
    _ir(at, "¿Qué cambió?")
    assert at.selectbox(key="cambios-corte-a").value == "2026-07-19"
    tabla = at.dataframe[0].value
    fila = tabla[tabla["ID"] == "IC-TST-00001"]
    assert fila["Registros nuevos"].tolist() == ["EV-000001"]
    at.selectbox(key="cambios-corte-a").select("2026-07-20").run()
    assert any("El corte A debe ser anterior al corte B" in w.value for w in at.warning)
    _ir(at, "Cobertura")
    assert {m.label for m in at.metric} >= {"Solicitudes evaluadas", "Decisiones pendientes", "Análisis guardados"}


def test_sin_propuestas_muestra_el_comando(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(tmp_path / "salidas_vacias", tmp_path / "sin_datos", monkeypatch)
    assert any("uv run hlf-lote --fecha-corte AAAA-MM-DD" in w.value for w in at.warning)


def test_huella_distinta_se_advierte_en_el_detalle(lote: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    datos, salidas = lote
    perfiles = perfiles_demo()
    perfiles[0]["eventos_clinicos"].append(evento("EV-000002", "2026-07-10", "hospitalizacion", "ingreso UCI", "grave"))
    escribir_dataset(datos, perfiles)  # los datos cambiaron después del lote
    at = _app(salidas, datos, monkeypatch)
    _abrir_detalle(at, "MED-DEMO-01", "2026-07-20", "IC-TST-00001")
    assert any("la huella del contexto reconstruido no coincide" in w.value for w in at.warning)


# --------------------------------------------------------------------------- datos reales (copia temporal)


@pytest.fixture
def reales(tmp_path: Path) -> tuple[Path, Path]:
    cortes = ("2026-07-19", "2026-07-20")
    origen = [SALIDAS_REALES / "propuestas" / f"fecha_corte={c}" for c in cortes]
    if not (DATOS_REALES / "perfiles.json").is_file() or not all(o.is_dir() for o in origen):
        pytest.skip("Dataset o salidas reales de 2026-07-19/20 no disponibles (ignorados por git)")
    salidas = tmp_path / "salidas"
    for carpeta in ("propuestas", "analisis", "hallazgos_dq", "cohortes", "resumen"):
        for c in cortes:
            fuente = SALIDAS_REALES / carpeta / f"fecha_corte={c}"
            if fuente.is_dir():
                shutil.copytree(fuente, salidas / carpeta / f"fecha_corte={c}")
    return DATOS_REALES, salidas


def test_real_00002_en_detalle_y_decision_aceptada(
    reales: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    datos, salidas = reales
    at = _app(salidas, datos, monkeypatch)
    _abrir_detalle(at, "MED-DEMO-01", "2026-07-20", "IC-HLF-00002")
    assert at.selectbox(key="detalle-resaltar").value == "EV-000004"
    linea = next(df.value for df in at.dataframe if "Elegido" in df.value.columns)
    assert linea.loc[linea["ID"] == "EV-000004", "Elegido"].tolist() == ["▶ elegido"]
    assert any("BR_EVENTO_GRAVE_30D" in m.value for m in at.markdown)
    assert at.metric[2].value == "🔴 crítica"  # nivel propuesto
    assert not any(ADVERTENCIA_EQUIDAD in w.value for w in at.warning)
    at.radio(key="detalle-decision-radio").set_value("aceptar")
    at.button(key="detalle-decision-guardar").click().run()
    (d,) = leer_decisiones(salidas)
    assert (d.id_solicitud, d.fecha_corte, d.decision) == ("IC-HLF-00002", date(2026, 7, 20), "aceptada")
    assert d.id_analisis is not None


def test_real_que_cambio_0719_0720(reales: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    datos, salidas = reales
    at = _app(salidas, datos, monkeypatch)
    _ir(at, "¿Qué cambió?")
    tabla = at.dataframe[0].value
    fila = tabla[tabla["ID"] == "IC-HLF-00002"]
    assert fila["Nivel A → B"].tolist() == ["🟢 baja → 🔴 crítica"]
    assert "EV-000004" in fila["Registros nuevos"].iloc[0]
    assert "BR_EVENTO_GRAVE_30D" in fila["Banderas nuevas"].iloc[0]


def test_real_00349_advertencia_de_equidad(reales: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    datos, salidas = reales
    at = _app(salidas, datos, monkeypatch)
    _abrir_detalle(at, "", "2026-07-19", "IC-HLF-00349")
    (aviso,) = [w for w in at.warning if ADVERTENCIA_EQUIDAD in w.value]
    assert "resumen" in aviso.value


def test_abrir_desde_tabla_cambia_a_detalle(lote, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Simula el callback de selección de fila (AppTest no puede hacer clic en st.dataframe): la vista
    activa pasa a Detalle y la solicitud elegida queda seleccionada."""
    datos, salidas = lote
    at = _app(salidas, datos, monkeypatch)
    ids = at.selectbox(key="lateral-corte").options
    assert ids
    at.session_state["detalle-solicitud"] = None
    at.session_state["app-pestana"] = "Detalle"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.radio(key="app-pestana").value == "Detalle"
    assert at.selectbox(key="detalle-solicitud").value is not None


def test_decision_sin_opcion_preseleccionada(lote, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """El radio no viene en "aceptar": guardar sin elegir no guarda nada."""
    datos, salidas = lote
    at = _app(salidas, datos, monkeypatch)
    _abrir_detalle(at, "MED-DEMO-01", "2026-07-20", "IC-TST-00001")
    assert at.radio(key="detalle-decision-radio").value is None
    at.button(key="detalle-decision-guardar").click().run()
    assert any("elija aceptar, ajustar o rechazar" in e.value for e in at.error)
    assert not ruta_decisiones(salidas).exists()


def test_fallo_de_auditoria_no_se_informa_como_fallo_de_guardado(lote, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Si la auditoría falla, la decisión ya quedó guardada: aviso distinto y sin pedir que se reintente."""
    from hlf_priorizacion.auditoria.registro import RegistroAuditoria

    def falla(*_a: object, **_k: object) -> None:
        raise OSError("disco lleno")

    datos, salidas = lote
    at = _app(salidas, datos, monkeypatch)
    _abrir_detalle(at, "MED-DEMO-01", "2026-07-20", "IC-TST-00001")
    monkeypatch.setattr(RegistroAuditoria, "registrar", falla)
    at.radio(key="detalle-decision-radio").set_value("aceptar")
    at.button(key="detalle-decision-guardar").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(leer_decisiones(salidas)) == 1
    assert any("quedó guardada" in w.value and "No la vuelva a guardar" in w.value for w in at.warning)
    assert not any("No se pudo guardar" in e.value for e in at.error)
