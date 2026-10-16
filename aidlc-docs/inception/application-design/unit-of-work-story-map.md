# Mapa requisitos → unidades

No hay User Stories (se omitieron en el plan). Se usan los requisitos funcionales RF-01..RF-13 de `aidlc-docs/inception/requirements/requirements.md`.

| Requisito | Unidad | En el MVP | Nota |
|---|---|---|---|
| RF-01 Principio rector (`pendiente_revision_medica`) | U1, U2, U3 | Sí | Solo U3 cambia el estado, por decisión explícita |
| RF-02 Determinismo | U1 | Sí | El copiloto no genera cifras; U2 valida |
| RF-03 Contrato y cuarentena | U1 | Sí | Conciliación con CSV: si da el tiempo |
| RF-04 Fecha de corte | U1 | Sí | Selector en U3 |
| RF-05 Motor de reglas | U1 | Sí | Parámetros referenciales `reglas-v0.1.0` |
| RF-06 Calidad de datos | U1 | Sí | |
| RF-07 Copiloto IA | U2 | Parcial | Solo modo barrido (U-6 = A) |
| RF-08 Salidas del agente | U1, U2, U3 | Parcial | Propuesta de agenda por box queda fuera (U5) |
| RF-09 Trazabilidad | U1, U2, U3 | Parcial | Auditoría en JSONL solo de agregado; sin Object Lock |
| RF-10 FHIR | U6 | No | Se presenta el mapeo |
| RF-11 Uso del box | U5 | No | Solo la alerta `citas_fallidas` de U1 |
| RF-12 Cadencia nocturna | U1 (CLI), U4 | Parcial | Se ejecuta a mano; programación en U4 |
| RF-13 Vistas | U3 | Parcial | Bandeja del clínico y gestor de lista; vista de box fuera |

Todos los requisitos tienen unidad asignada. Los que no entran al MVP quedan en U4, U5 o U6.
