"""Estimación de espera `throughput_8_semanas` (F0006). Pruebas puras: sin base de datos ni dataset."""
from datetime import date, timedelta

import pandas as pd

from priorizacion.estimacion import atenciones_por_semana, estimar

CORTE = date(2026, 10, 13)


def _citas(por_semana: list[int], especialidad="Cardiología", estado="asistio") -> pd.DataFrame:
    filas = []
    for semana, n in enumerate(por_semana):
        for i in range(n):
            filas.append({"especialidad": especialidad, "estado_cita": estado,
                          "fecha_cita": pd.Timestamp(CORTE - timedelta(days=semana * 7 + i % 7))})
    return pd.DataFrame(filas, columns=["especialidad", "estado_cita", "fecha_cita"])


def _cola(n: int, especialidad="Cardiología") -> pd.DataFrame:
    niveles = ["alta", "media", "baja"]
    return pd.DataFrame([{"id_solicitud": f"IC-{i:03d}", "especialidad": especialidad,
                          "prioridad_vigente": niveles[i % 3], "fecha_ingreso": f"2026-0{1 + i % 9}-01"}
                         for i in range(n)])


def test_cuenta_las_atenciones_de_cada_semana():
    citas = pd.concat([_citas([3, 0, 2, 1, 0, 0, 0, 4]), _citas([5], estado="no_asistio"),
                       _citas([7], especialidad="Neurología")])
    assert atenciones_por_semana(citas, "Cardiología", CORTE) == [3, 0, 2, 1, 0, 0, 0, 4]


def test_el_rango_crece_con_la_posicion_y_nunca_es_negativo():
    est = estimar(_cola(30), _citas([4, 5, 3, 6, 4, 5, 4, 5]), CORTE)
    assert len(est) == 30 and list(est["posicion_vigente"]) == list(range(1, 31))
    assert (est["dias_estimados_min"] >= 0).all()
    assert (est["dias_estimados_max"] >= est["dias_estimados_min"]).all()
    assert est["dias_estimados_min"].is_monotonic_increasing and est["dias_estimados_max"].is_monotonic_increasing
    assert set(est["total_cola"]) == {30} and set(est["confianza"]) == {"alta"}
    assert not est["publicable"].any()                       # hasta que el HLF apruebe informarla


def test_la_posicion_sigue_la_prioridad_vigente():
    est = estimar(_cola(9), _citas([2] * 8), CORTE)
    orden = list(est.sort_values("posicion_vigente")["prioridad_vigente"])
    assert orden == ["alta"] * 3 + ["media"] * 3 + ["baja"] * 3


def test_sin_atenciones_no_se_inventa():
    assert estimar(_cola(5), _citas([0] * 8), CORTE).empty
    assert estimar(_cola(5), _citas([3] * 8, estado="no_asistio"), CORTE).empty


def test_pocas_atenciones_dan_confianza_baja_y_rango_amplio():
    est = estimar(_cola(10), _citas([1, 0, 0, 0, 0, 0, 0, 0]), CORTE)
    assert set(est["confianza"]) == {"baja"}
    ultima = est.iloc[-1]
    assert ultima["dias_estimados_max"] > ultima["dias_estimados_min"] or ultima["dias_estimados_max"] >= 7 * 10
