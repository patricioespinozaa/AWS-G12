import pandas as pd

RANGO = {"presion_sistolica": (90, 139), "presion_diastolica": (60, 89), "HbA1c": (4.0, 6.4),
         "glicemia": (70, 140), "saturacion_o2": (95, 100), "peak_flow": (350, 600),
         "escala_dolor_eva": (0, 3), "PHQ9": (0, 9)}

# Límites físicos: fuera de esto, el dato es un error (no un paciente grave)
PLAUSIBLE = {"presion_sistolica": (50, 260), "presion_diastolica": (25, 150), "HbA1c": (4.0, 18.0),
             "glicemia": (20, 700), "saturacion_o2": (50, 100), "peak_flow": (50, 900),
             "escala_dolor_eva": (0, 10), "PHQ9": (0, 27)}


def es_plausible(tipo, v) -> bool:
    lo, hi = PLAUSIBLE.get(tipo, (float("-inf"), float("inf")))
    return lo <= v <= hi


def auditar(repo) -> pd.DataFrame:
    hallazgos = []

    def add(codigo, nivel, pid, desc, ids):
        hallazgos.append({"codigo": codigo, "nivel": nivel, "id_paciente": pid,
                          "descripcion": desc, "registro_ids": ids})

    m, ev, cit, lista, pac = (repo.t[k] for k in ("mediciones", "eventos", "citaciones", "lista", "pacientes"))

    # 1. Valores imposibles
    for r in m.itertuples():
        if not es_plausible(r.tipo_medicion, r.valor):
            add("DQ-01", "descartar", r.id_paciente,
                f"{r.tipo_medicion}={r.valor} {r.unidad} fuera de límites fisiológicos", [r.id_medicion])

    # 2. HbA1c con frecuencia no fisiológica (refleja aprox. 3 meses)
    for pid, g in m[m.tipo_medicion == "HbA1c"].sort_values("fecha_medicion").groupby("id_paciente"):
        dias = g.fecha_medicion.diff().dt.days
        if (dias < 30).any():
            add("DQ-02", "verificar", pid,
                f"HbA1c repetida con intervalo mínimo de {int(dias.min())} días", g.id_medicion.tolist())

    # 3. "Fuera de rango" en dirección sin riesgo clínico
    for r in m[(m.tipo_medicion == "peak_flow") & (m.valor > 600) & m.fuera_de_rango].itertuples():
        add("DQ-03", "info", r.id_paciente, "Peak flow alto marcado como fuera de rango (no indica riesgo)",
            [r.id_medicion])

    # 4. Registros antes del ingreso o después de la defunción
    ing = lista.set_index("id_paciente").fecha_ingreso_lista
    dfn = pac.set_index("id_paciente").fecha_defuncion
    for tabla, col, idc in (("eventos", "fecha_evento", "id_evento"), ("mediciones", "fecha_medicion", "id_medicion")):
        d = repo.t[tabla]
        malos = d[(d[col] < d.id_paciente.map(ing)) | (d[col] > d.id_paciente.map(dfn))]
        for r in malos.itertuples():
            add("DQ-04", "verificar", r.id_paciente, f"{tabla} fuera de la ventana [ingreso, defunción]",
                [getattr(r, idc)])

    # 5. Citas desordenadas en el origen (solo si viene del JSON)
    if "orden_origen" in cit:
        for pid, g in cit.groupby("id_paciente"):
            if not g.sort_values("orden_origen").fecha_cita.is_monotonic_increasing:
                add("DQ-05", "info", pid, "Citas no cronológicas en el origen", g.id_cita.tolist())

    # 6. Asistió a su especialidad pero sigue en_espera
    l = lista.set_index("id_paciente")
    for r in cit[cit.estado_cita == "asistio"].itertuples():
        s = l.loc[r.id_paciente]
        if s.estado == "en_espera" and r.especialidad == s.especialidad:
            add("DQ-06", "verificar", r.id_paciente, "Asistió a la especialidad pero la solicitud sigue en_espera",
                [r.id_cita, s.id_solicitud])

    # 7. IDs duplicados
    for r in m[m.id_medicion.duplicated(keep=False)].itertuples():
        add("DQ-07", "verificar", r.id_paciente, "Medición duplicada", [r.id_medicion])

    return pd.DataFrame(hallazgos)