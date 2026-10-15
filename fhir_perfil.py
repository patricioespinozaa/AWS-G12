LOINC = {  # validar con el equipo de terminología / guía CL Core de HL7 Chile
    "presion_sistolica": ("8480-6", "Presión sistólica"),
    "presion_diastolica": ("8462-4", "Presión diastólica"),
    "HbA1c": ("4548-4", "Hemoglobina A1c"),
    "glicemia": ("2339-0", "Glucosa en sangre"),
    "saturacion_o2": ("59408-5", "SpO2 por oximetría de pulso"),
    "peak_flow": ("19935-6", "Flujo espiratorio máximo"),
    "PHQ9": ("44261-6", "PHQ-9 puntaje total"),
    "escala_dolor_eva": ("72514-3", "Severidad del dolor 0-10"),
}
CLASE_ENC = {"visita_urgencia": "EMER", "hospitalizacion": "IMP"}
ESTADO_CITA = {"asistio": "fulfilled", "no_asistio": "noshow", "cancelo": "cancelled", "reprogramo": "cancelled"}


def perfil_a_bundle(p, corte, ids_a_verificar: set[str] = frozenset()) -> dict:
    from ingesta_json import id_medicion
    from calidad import RANGO
    pid, ref = p.id_paciente, {"reference": f"Patient/{p.id_paciente}"}
    rec = [
        {"resourceType": "Patient", "id": pid, "gender": {"F": "female", "M": "male"}[p.paciente.sexo],
         "address": [{"district": p.paciente.comuna}], "deceasedBoolean": p.paciente.fallecido},
        {"resourceType": "ServiceRequest", "id": p.lista_espera.id_solicitud, "status": "active",
         "intent": "order", "subject": ref, "priority": {"alta": "urgent", "media": "routine", "baja": "routine"}
         [p.lista_espera.prioridad_inicial],
         "reasonCode": [{"coding": [{"system": "http://hl7.org/fhir/sid/icd-10",
                                     "code": p.lista_espera.diagnostico_cie10,
                                     "display": p.lista_espera.diagnostico_texto}]}],
         "authoredOn": str(p.lista_espera.fecha_ingreso_lista)},
    ]
    rec += [{"resourceType": "Encounter", "id": e.id_evento, "status": "finished", "subject": ref,
             "class": {"code": CLASE_ENC.get(e.tipo_evento, "AMB")}, "type": [{"text": e.subtipo}],
             "period": {"start": str(e.fecha_evento)},
             "basedOn": [{"reference": f"ServiceRequest/{p.lista_espera.id_solicitud}"}]}
            for e in p.eventos_clinicos if e.fecha_evento <= corte]
    for m in p.mediciones:
        if m.fecha_medicion > corte:
            continue
        mid = id_medicion(pid, m.fecha_medicion, m.tipo_medicion, m.valor)
        code, disp = LOINC[m.tipo_medicion]
        lo, hi = RANGO[m.tipo_medicion]
        obs = {"resourceType": "Observation", "id": mid, "status": "final", "subject": ref,
               "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": disp}]},
               "effectiveDateTime": str(m.fecha_medicion),
               "valueQuantity": {"value": m.valor, "unit": m.unidad},
               "referenceRange": [{"low": {"value": lo}, "high": {"value": hi}}]}
        if mid in ids_a_verificar:
            obs["note"] = [{"text": "Valor marcado por auditoría de calidad: verificar antes de usar"}]
        rec.append(obs)
    rec += [{"resourceType": "Appointment", "id": c.id_cita, "status": ESTADO_CITA[c.estado_cita],
             "start": f"{c.fecha_cita}T08:30:00-03:00", "participant": [{"actor": ref, "status": "accepted"}],
             **({"cancelationReason": {"text": "reprogramada"}} if c.estado_cita == "reprogramo" else {})}
            for c in p.citaciones if c.fecha_cita <= corte]
    return {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": r} for r in rec]}