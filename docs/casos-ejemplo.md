# Casos de ejemplo

Seis pacientes del dataset sintético del HLF (`pacientes_ejemplo_HLF.md`), uno por patrón de evolución. Sirven como **casos de prueba de referencia**: el algoritmo debería reaccionar a cada uno como se indica. Los patrones **no vienen etiquetados** en los datos; el nombre es solo para explicar.

La historia completa de cada paciente se obtiene uniendo `pacientes`, `lista_espera`, `eventos_clinicos`, `mediciones` y `citaciones` por `id_paciente`, o directamente desde `perfiles.json`.

## Resumen

| Patrón | Paciente | Diagnóstico | Prioridad inicial | Comportamiento esperado del sistema |
|---|---|---|---|---|
| Deterioro progresivo | PAC-HLF-00001 | F32 Episodio depresivo | alta | El puntaje **sube de a poco** con la tendencia del PHQ-9 |
| Deterioro agudo | PAC-HLF-00002 | I20 Angina de pecho | baja | El puntaje **salta** con la urgencia ESI 2 y la hospitalización |
| Mejora | PAC-HLF-00028 | F41 Trastorno de ansiedad | baja | El puntaje **puede bajar** |
| Inasistencia recurrente | PAC-HLF-00020 | I20 Angina de pecho | media | La prioridad clínica **no cambia**; se marca **riesgo de no-show** |
| Estable / atendido | PAC-HLF-00032 | J45 Asma | baja | No se dispara; sale de la lista activa por estar atendido |
| Fallecido en espera | PAC-HLF-00009 | E03 Hipotiroidismo | baja | **Se excluye** desde 2026-09-08 |

## 1. Deterioro progresivo — PAC-HLF-00001

63 años, M · La Florida · FONASA B · Salud Mental / Psiquiatría adulto · F32 · ingreso 2025-12-15 desde Urgencia · en_espera

| Fecha | Tipo | Dato |
|---|---|---|
| 2026-01-09 | medición | PHQ-9 = 4 |
| 2026-02-03 | medición | PHQ-9 = 10 ⚠️ |
| 2026-03-15 | evento | control_aps · control crónico (leve) |
| 2026-04-19 → 2026-08-23 | medición | PHQ-9 entre 12 y 14 ⚠️ (6 mediciones) |
| 2026-06-14 | evento | cambio_farmaco · aumento dosis (moderada) |
| 2026-08-28 | evento | examen_alterado · resultado alterado (moderada) |
| 2026-09-17 | medición | PHQ-9 = 19 ⚠️ |

**Qué debe capturar el puntaje:** la pendiente sostenida del PHQ-9 (4 → 19), no solo que esté fuera de rango. Ningún evento aislado es grave; el deterioro está en la suma y en la tendencia. Ya parte en prioridad alta: la propuesta debería mantenerla y destacar la evolución.

## 2. Deterioro agudo — PAC-HLF-00002

49 años, M · Puente Alto · FONASA B · Cardiología adulto · I20 · ingreso 2025-11-08 desde Hospitalización · en_espera

| Fecha | Tipo | Dato |
|---|---|---|
| 2025-12-26 → 2026-05-20 | medición | Presión en rango (sistólica 97–112, diastólica 68) |
| 2026-07-08 | medición | Sistólica = 167 mmHg ⚠️ |
| 2026-07-20 | evento | visita_urgencia · triage ESI 2 (grave) |
| 2026-08-06 | evento | hospitalizacion · ingreso hospitalario (grave) |
| 2026-08-25 | medición | Sistólica = 167 mmHg ⚠️ |

**Qué debe capturar el puntaje:** de **baja a alta** tras la urgencia del 2026-07-20. Es el equivalente, en este dataset, al caso de don Manuel. Con fecha de corte 2026-07-19 la propuesta debería seguir siendo baja o media; con corte 2026-07-20 o posterior, alta.

## 3. Mejora — PAC-HLF-00028

26 años, F · La Florida · FONASA A · Salud Mental / Psicología · F41 · ingreso 2026-07-30 desde CESFAM/APS · en_espera

| Fecha | Tipo | Dato |
|---|---|---|
| 2026-08-11 | medición | PHQ-9 = 5 |
| 2026-08-24 → 2026-09-30 | medición | PHQ-9 = 0 (4 mediciones) |
| 2026-08-29 | evento | control_aps · buena respuesta (leve) |
| 2026-09-20 | evento | cambio_farmaco · reducción dosis (leve) |
| 2026-10-06 | cita | BOX-04 · reprogramo |

**Qué debe capturar el puntaje:** los eventos de mejora (buena respuesta, reducción de dosis) y las mediciones normales pueden **bajar** la propuesta. Bajar una prioridad es delicado: la explicación debe ser especialmente clara y el equipo clínico decide.

## 4. Inasistencia recurrente — PAC-HLF-00020

76 años, F · La Florida · FONASA A · Cardiología adulto · I20 · ingreso 2026-03-30 desde Hospitalización · en_espera

| Fecha | Tipo | Dato |
|---|---|---|
| 2026-05-18 | medición | Diastólica = 80 mmHg |
| 2026-07-06 | medición | Sistólica = 111 mmHg |
| 2026-07-31 | cita | BOX-13 · no_asistio |
| 2026-08-18 | cita | BOX-13 · no_asistio |
| 2026-08-24 | medición | Diastólica = 85 mmHg |
| 2026-08-31 | cita | BOX-20 · reprogramo |

**Qué debe capturar el sistema:** las inasistencias **no suben la prioridad clínica** (sus mediciones están en rango), pero sí muestran **riesgo de perder el seguimiento** y de desperdiciar cupos de box. Es la tensión entre prioridad clínica y uso del recurso: mostrarla como señal aparte (por ejemplo, confirmar la cita por teléfono o sobreagendar), no mezclada en el puntaje clínico. Ojo: 76 años, cardiopatía coronaria y derivada desde hospitalización; la inasistencia puede ser una barrera de acceso, no desinterés.

## 5. Estable / ya atendido — PAC-HLF-00032

85 años, M · La Florida · FONASA B · Broncopulmonar / Asma · J45 · ingreso 2025-07-03 desde Otro hospital red · **atendido**

| Fecha | Tipo | Dato |
|---|---|---|
| 2025-10-27 → 2026-06-18 | medición | Saturación O₂ 97–100 % (3 mediciones) |
| 2026-06-30 | cita | BOX-01 · asistio (39 min) |

**Qué debe capturar el sistema:** caso de control. Poca señal y todo en rango: la propuesta no debe dispararse por la edad ni por el tiempo de espera solamente. Desde 2026-06-30 está atendido y sale de la lista activa.

## 6. Fallecido en espera — PAC-HLF-00009

47 años, M · Puente Alto · FONASA B · Endocrinología / Tiroides · E03 · ingreso 2026-08-07 desde CESFAM/APS · **fallecido el 2026-09-08**

| Fecha | Tipo | Dato |
|---|---|---|
| 2026-08-10 → 2026-08-28 | medición | Glicemia 110 → 157 mg/dL ⚠️; HbA1c 7,4 % ⚠️ |
| 2026-08-29 | evento | visita_urgencia · descompensación grave (grave) |
| 2026-08-31 | medición | HbA1c = 8,8 % ⚠️ |
| 2026-09-04 | medición | Glicemia = 148 mg/dL ⚠️ |
| 2026-09-04 | evento | hospitalizacion · ingreso UCI (grave) |

**Qué debe capturar el sistema:**
- Con fecha de corte anterior a 2026-09-08, un deterioro agudo muy marcado: debería haber subido a alta tras la urgencia del 2026-08-29.
- Desde 2026-09-08, **exclusión**: fuera de la lista y sin nuevas citaciones.
- Nota: el diagnóstico de espera es hipotiroidismo, pero las señales son glicémicas. La relevancia evento ↔ diagnóstico no siempre es obvia; un evento grave cuenta aunque no se relacione directamente con el diagnóstico de derivación.

## Cómo usar estos casos

- **Tests de regresión:** fijar la prioridad propuesta esperada para cada paciente en varias fechas de corte (antes y después del evento clave).
- **Demo:** mostrar la línea de tiempo y la explicación del cambio para los casos 1 y 2.
- **Comparar foto vs. película:** `prioridad_inicial` es la foto; la línea de tiempo es la película.
- **Uso del box:** con el caso 4, cruzar `citaciones` con `agenda_box` para medir cupos perdidos (ver advertencias de cruce en `docs/datos.md`).
