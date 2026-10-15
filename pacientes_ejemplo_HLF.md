# Pacientes de ejemplo – Dataset Atención Ambulatoria Dinámica HLF

Este documento recorre pacientes reales del dataset (semilla fija, 500 pacientes, fecha de referencia 13-10-2026) para mostrar cómo la **serie temporal** permite que la prioridad se mueva mientras el paciente espera.

Cada ejemplo reconstruye la historia del paciente uniendo `pacientes`, `lista_espera`, `eventos_clinicos`, `mediciones` y `citaciones` por `id_paciente`. Los íconos: 🔴 evento clínico · 📊 medición · 📅 cita.

Los patrones de evolución **no están etiquetados en los datos**: son el tipo de caso que el algoritmo de los equipos debe descubrir. Aquí los nombramos solo para explicar.

---

## 1. Deterioro progresivo

> La condición empeora de a poco mientras espera. El puntaje debería SUBIR con el tiempo.

**PAC-HLF-00001 — Paciente Azucena 001** · 63 años, hombre · La Florida · FONASA B
- **Diagnóstico:** Salud Mental / Psiquiatría adulto — F32 Episodio depresivo
- **Lista:** prioridad inicial **alta** · ingreso 2025-12-15 · derivado desde Urgencia · estado **en_espera**
- **Línea de tiempo:**
    - `2026-01-09`  📊 PHQ9 = 4 puntos
    - `2026-02-03`  📊 PHQ9 = 10 puntos  ⚠️ fuera de rango
    - `2026-02-28`  📊 PHQ9 = 9 puntos
    - `2026-03-15`  🔴 evento: control_aps — control crónico (leve)
    - `2026-03-25`  📊 PHQ9 = 8 puntos
    - `2026-04-19`  📊 PHQ9 = 12 puntos  ⚠️ fuera de rango
    - `2026-05-15`  📊 PHQ9 = 12 puntos  ⚠️ fuera de rango
    - `2026-06-09`  📊 PHQ9 = 14 puntos  ⚠️ fuera de rango
    - `2026-06-14`  🔴 evento: cambio_farmaco — aumento dosis (moderada)
    - `2026-07-04`  📊 PHQ9 = 14 puntos  ⚠️ fuera de rango
    - `2026-07-29`  📊 PHQ9 = 14 puntos  ⚠️ fuera de rango
    - `2026-08-23`  📊 PHQ9 = 13 puntos  ⚠️ fuera de rango
    - `2026-08-28`  🔴 evento: examen_alterado — resultado alterado (moderada)
    - `2026-09-17`  📊 PHQ9 = 19 puntos  ⚠️ fuera de rango

---

## 2. Deterioro agudo

> Entra con prioridad baja/media, pero un evento grave (urgencia u hospitalización) dispara su gravedad. El puntaje debería SALTAR.

**PAC-HLF-00002 — Paciente Violeta 002** · 49 años, hombre · Puente Alto · FONASA B
- **Diagnóstico:** Cardiología / Cardiología adulto — I20 Angina de pecho
- **Lista:** prioridad inicial **baja** · ingreso 2025-11-08 · derivado desde Hospitalización · estado **en_espera**
- **Línea de tiempo:**
    - `2025-12-26`  📊 presion_sistolica = 112 mmHg
    - `2026-02-12`  📊 presion_sistolica = 97 mmHg
    - `2026-04-02`  📊 presion_sistolica = 100 mmHg
    - `2026-05-20`  📊 presion_diastolica = 68 mmHg
    - `2026-07-08`  📊 presion_sistolica = 167 mmHg  ⚠️ fuera de rango
    - `2026-07-20`  🔴 evento: visita_urgencia — triage ESI 2 (grave)
    - `2026-08-06`  🔴 evento: hospitalizacion — ingreso hospitalario (grave)
    - `2026-08-25`  📊 presion_sistolica = 167 mmHg  ⚠️ fuera de rango

---

## 3. Mejora

> El tratamiento en APS funciona y las mediciones mejoran. El puntaje podría BAJAR.

**PAC-HLF-00028 — Paciente Petunia 028** · 26 años, mujer · La Florida · FONASA A
- **Diagnóstico:** Salud Mental / Psicología — F41 Trastorno de ansiedad
- **Lista:** prioridad inicial **baja** · ingreso 2026-07-30 · derivado desde CESFAM/APS · estado **en_espera**
- **Línea de tiempo:**
    - `2026-08-11`  📊 PHQ9 = 5 puntos
    - `2026-08-24`  📊 PHQ9 = 0 puntos
    - `2026-08-29`  🔴 evento: control_aps — buena respuesta (leve)
    - `2026-09-05`  📊 PHQ9 = 0 puntos
    - `2026-09-18`  📊 PHQ9 = 0 puntos
    - `2026-09-20`  🔴 evento: cambio_farmaco — reducción dosis (leve)
    - `2026-09-30`  📊 PHQ9 = 0 puntos
    - `2026-10-06`  📅 cita en BOX-04: reprogramo

---

## 4. Inasistencia recurrente (no-show)

> Falta a varias citas. Tensión entre prioridad clínica y uso del box: cada inasistencia es un cupo perdido.

**PAC-HLF-00020 — Paciente Azucena 020** · 76 años, mujer · La Florida · FONASA A
- **Diagnóstico:** Cardiología / Cardiología adulto — I20 Angina de pecho
- **Lista:** prioridad inicial **media** · ingreso 2026-03-30 · derivado desde Hospitalización · estado **en_espera**
- **Línea de tiempo:**
    - `2026-05-18`  📊 presion_diastolica = 80 mmHg
    - `2026-07-06`  📊 presion_sistolica = 111 mmHg
    - `2026-07-31`  📅 cita en BOX-13: no_asistio
    - `2026-08-18`  📅 cita en BOX-13: no_asistio
    - `2026-08-24`  📊 presion_diastolica = 85 mmHg
    - `2026-08-31`  📅 cita en BOX-20: reprogramo

---

## 5. Estable / ya atendido

> Poca señal, condición en rango, asistió y se resolvió. Caso de control: su prioridad no debería dispararse.

**PAC-HLF-00032 — Paciente Orquídea 032** · 85 años, hombre · La Florida · FONASA B
- **Diagnóstico:** Broncopulmonar / Asma — J45 Asma
- **Lista:** prioridad inicial **baja** · ingreso 2025-07-03 · derivado desde Otro hospital red · estado **atendido**
- **Línea de tiempo:**
    - `2025-10-27`  📊 saturacion_o2 = 100 %
    - `2026-02-21`  📊 saturacion_o2 = 97 %
    - `2026-06-18`  📊 saturacion_o2 = 97 %
    - `2026-06-30`  📅 cita en BOX-01: asistio (39 min)

---

## 6. Fallecido en espera

> Fallece mientras espera. Control de exclusión: debe salir de la lista y no recibir más citaciones. Toda su actividad es anterior a la defunción.

**PAC-HLF-00009 — Paciente Amapola 009** · 47 años, hombre · Puente Alto · FONASA B
- **Diagnóstico:** Endocrinología / Tiroides — E03 Hipotiroidismo
- **Lista:** prioridad inicial **baja** · ingreso 2026-08-07 · derivado desde CESFAM/APS · estado **fallecido**
- **Fallecimiento:** 2026-09-08
- **Línea de tiempo:**
    - `2026-08-10`  📊 glicemia = 110 mg/dL
    - `2026-08-14`  📊 HbA1c = 7.4 %  ⚠️ fuera de rango
    - `2026-08-17`  📊 glicemia = 133 mg/dL
    - `2026-08-21`  📊 glicemia = 154 mg/dL  ⚠️ fuera de rango
    - `2026-08-24`  📊 glicemia = 157 mg/dL  ⚠️ fuera de rango
    - `2026-08-28`  📊 glicemia = 147 mg/dL  ⚠️ fuera de rango
    - `2026-08-29`  🔴 evento: visita_urgencia — descompensación grave (grave)
    - `2026-08-31`  📊 HbA1c = 8.8 %  ⚠️ fuera de rango
    - `2026-09-04`  📊 glicemia = 148 mg/dL  ⚠️ fuera de rango
    - `2026-09-04`  🔴 evento: hospitalizacion — ingreso UCI (grave)

---

## Cómo usar estos ejemplos

- **Recalcular prioridad a una fecha de corte:** usar solo los registros con fecha ≤ corte. Así se simula lo que el hospital sabía ese día.
- **Comparar foto inicial vs. evolución:** la columna `prioridad_inicial` de `lista_espera` es la estratificación estática. La línea de tiempo muestra cómo cambia la realidad del paciente.
- **Uso del box:** cruzar `citaciones` (asistió / no asistió) con `agenda_box` (capacidad vs. uso) para medir cupos perdidos y sobretiempos.
