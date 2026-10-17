"""Ficha consolidada por paciente: la información de todas las fuentes, organizada por tipo.

Responde a "no existe un concentrador": diagnósticos, atenciones, fármacos y exámenes en un solo
lugar, cada dato con su referencia de origen. Las fuentes no se modifican.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import reglas as R
from .datos import Historia, Solicitud
from .motor import Resultado, _num, _pendiente_por_dia


def _eventos_df(eventos) -> pd.DataFrame:
    return pd.DataFrame([{"fecha": e.fecha.isoformat(), "tipo": R.NOMBRE_TIPO_EVENTO[e.tipo], "detalle": e.subtipo,
                          "severidad": e.severidad, "fuente": e.id_evento} for e in eventos],
                        columns=["fecha", "tipo", "detalle", "severidad", "fuente"])


def ficha_consolidada(sol: Solicitud, hist: Historia, corte: date, evidencias: pd.DataFrame,
                      mensajes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    eventos = hist.eventos_hasta(corte)
    meds = hist.mediciones_hasta(corte)
    filas_examenes = []
    for tipo, lst in meds.items():
        if not lst:
            continue
        lo, hi = R.RANGOS_NORMALES[tipo]
        u = lst[-1]
        rec = [m for m in lst if (corte - m.fecha).days <= R.VENTANA_TENDENCIA_DIAS]
        tendencia = "—"
        if len(rec) >= R.MIN_MEDICIONES_TENDENCIA:
            p = _pendiente_por_dia([((m.fecha - rec[0].fecha).days, m.valor) for m in rec])
            if p is not None:
                norm = p * 30 / (hi - lo) * (-1 if tipo in R.MEJOR_ALTO else 1)
                tendencia = "empeora" if norm > R.UMBRAL_TENDENCIA else "mejora" if norm < -R.UMBRAL_TENDENCIA else "estable"
        filas_examenes.append({
            "examen": R.NOMBRE_MEDICION[tipo], "n": len(lst), "último valor": f"{_num(u.valor)} {u.unidad}",
            "fecha último": u.fecha.isoformat(), "rango normal": f"{_num(lo)}–{_num(hi)}",
            "fuera de rango": "sí" if u.fuera_de_rango else "no", "tendencia (180 d)": tendencia,
            "origen": "externo validado" if u.origen == "externa" else "hospital"})
    ev_pac = evidencias[evidencias["id_paciente"] == sol.id_paciente] if len(evidencias) else evidencias
    msj_pac = mensajes[mensajes["id_paciente"] == sol.id_paciente] if len(mensajes) else mensajes
    clase, razon = R.RIESGO_BASAL_DX.get(sol.cie10, ("medio", "sin clasificar"))
    return {
        "diagnosticos": pd.DataFrame([
            {"diagnóstico": f"{sol.cie10} {sol.diagnostico}", "origen": "Interconsulta (lista de espera)",
             "riesgo basal": f"{clase} · {razon}", "fuente": sol.id_solicitud},
        ]),
        "atenciones": _eventos_df([e for e in eventos if e.tipo in ("visita_urgencia", "hospitalizacion")]),
        "controles": _eventos_df([e for e in eventos if e.tipo == "control_aps"]),
        "farmacos": _eventos_df([e for e in eventos if e.tipo == "cambio_farmaco"]),
        "examenes_alterados": _eventos_df([e for e in eventos if e.tipo == "examen_alterado"]),
        "examenes": pd.DataFrame(filas_examenes),
        "citas": pd.DataFrame([{"fecha": c.fecha.isoformat(), "box": c.id_box, "especialidad": c.especialidad,
                                "resultado": c.estado, "minutos": c.minutos, "fuente": c.id_cita}
                               for c in hist.citas_hasta(corte)]),
        "evidencia_externa": ev_pac,
        "mensajes": msj_pac,
    }


def resumen_clinico(sol: Solicitud, hist: Historia, corte: date, r: Resultado) -> str:
    """Resumen de 3 a 5 líneas, anclado a los datos (plantilla determinista)."""
    eventos = hist.eventos_hasta(corte)
    cuenta = lambda tipo: sum(e.tipo == tipo for e in eventos)  # noqa: E731
    sexo = {"F": "mujer", "M": "hombre"}.get(sol.sexo, sol.sexo)
    lineas = [
        f"{sol.edad} años, {sexo}, {sol.comuna}, {sol.prevision}.",
        f"Espera {sol.especialidad} ({sol.sub_especialidad}) por {sol.cie10} {sol.diagnostico} desde "
        f"{sol.fecha_ingreso.isoformat()} ({(corte - sol.fecha_ingreso).days} días); derivado desde "
        f"{sol.origen_derivacion} vía {R.CANAL_ORIGEN.get(sol.origen_derivacion, '—')}.",
    ]
    partes = []
    for tipo, nombre in [("visita_urgencia", "urgencias"), ("hospitalizacion", "hospitalizaciones"),
                         ("cambio_farmaco", "cambios de fármaco"), ("examen_alterado", "exámenes alterados"),
                         ("control_aps", "controles APS")]:
        if (n := cuenta(tipo)):
            partes.append(f"{n} {nombre}")
    lineas.append("Durante la espera: " + (", ".join(partes) if partes else "sin eventos registrados") + ".")
    meds = []
    for tipo, lst in hist.mediciones_hasta(corte).items():
        if lst:
            u = lst[-1]
            meds.append(f"{R.NOMBRE_MEDICION[tipo]} {_num(u.valor)} {u.unidad} ({u.fecha.isoformat()}"
                        f"{', fuera de rango' if u.fuera_de_rango else ''})")
    if meds:
        lineas.append("Últimas mediciones: " + "; ".join(meds) + ".")
    if r.excluido:
        lineas.append(f"Fuera de la lista: {r.motivo_exclusion}.")
    return " ".join(lineas)
