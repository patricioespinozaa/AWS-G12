# Copiloto de Lista de Espera HLF

> **Priorización clínica dinámica con trazabilidad hacia la ficha clínica**
> Hospital La Florida · Red Sur Oriente · Dataset 100 % sintético (semilla 20261013, fecha de referencia 2026-10-13)

---

## Índice

1. [Qué problema resuelve](#1-qué-problema-resuelve)
2. [Principios del sistema](#2-principios-del-sistema)
3. [Arquitectura](#3-arquitectura)
4. [Datos de entrada](#4-datos-de-entrada)
5. [Instalación](#5-instalación)
6. [Configuración](#6-configuración)
7. [Uso](#7-uso)
8. [Motor de reglas: cómo se calcula la prioridad](#8-motor-de-reglas-cómo-se-calcula-la-prioridad)
9. [Auditoría de calidad de datos](#9-auditoría-de-calidad-de-datos)
10. [El copiloto IA: cómo se comporta](#10-el-copiloto-ia-cómo-se-comporta)
11. [Trazabilidad hacia la ficha clínica](#11-trazabilidad-hacia-la-ficha-clínica)
12. [Validación y backtest](#12-validación-y-backtest)
13. [Trabajo con Kiro](#13-trabajo-con-kiro)
14. [Seguridad, privacidad y normativa](#14-seguridad-privacidad-y-normativa)
15. [Limitaciones conocidas](#15-limitaciones-conocidas)
16. [Hoja de ruta](#16-hoja-de-ruta)
17. [Glosario](#17-glosario)

---

## 1. Qué problema resuelve

En la red pública, la espera para una **primera consulta de especialidad** puede durar meses o más de un año. Durante ese tiempo el paciente queda "congelado" con la prioridad que se le asignó al derivarlo, aunque su condición cambie.

Urgencias, APS, laboratorio y lista de espera funcionan como **silos**. Si un paciente que espera cardiología consulta en urgencias por dolor torácico, nadie en la lista de espera se entera.

Este sistema:

- **Detecta** eventos y mediciones que indican deterioro mientras el paciente espera.
- **Relaciona** esos hallazgos con el motivo de derivación.
- **Anticipa** el riesgo usando cohortes de pacientes similares, incluso para pacientes sin historial propio.
- **Sugiere** una nueva prioridad y acciones concretas al médico contralor.
- **Registra** cada dato, análisis y decisión, y los deja enlazados a la ficha clínica antes de la consulta inicial.

**Ejemplo real del dataset:** el paciente `PAC-HLF-00002`, derivado por angina con prioridad **baja**, registró una PAS de 167 mmHg el 08-07, una urgencia ESI 2 el 20-07 y una hospitalización el 06-08. Al 13-10 seguía con prioridad baja. El sistema lo alerta el **08-07, 12 días antes de la urgencia**.

---

## 2. Principios del sistema

```
El software DETECTA  →  la IA ANALIZA  →  el MÉDICO DECIDE  →  todo queda TRAZADO
```

| Principio | Implementación |
|---|---|
| La IA nunca decide | Toda salida queda con estado `pendiente_revision_medica` |
| Las cifras son deterministas | Scores, cohortes e intervalos salen de código, no del modelo |
| Toda afirmación es verificable | Cada hallazgo cita `registro_id` (`EV-`, `MED-`, `CT-`, `IC-`) |
| Sin fuga de información futura | Todo se calcula con una `fecha_corte`; las herramientas la imponen |
| Equidad | Comuna, previsión y nivel socioeconómico **nunca bajan** la prioridad |
| Datos dudosos no son evidencia | La auditoría de calidad separa errores de registro de deterioro real |
| Versionado | Cada análisis guarda modelo, `PROMPT_VERSION` y `request_id` |

---

## 3. Arquitectura

```
                     ┌──────────────────────┐
perfiles.json ──────►│ modelos.py (pydantic)│──► perfiles inválidos → CUARENTENA
 (contrato oficial)  └──────────┬───────────┘
                                ▼
                     ingesta_json.py ──► tablas + id_medicion (hash)
agenda_box.csv ────────────────►│
                                ▼
                     ┌──────────────────────┐
                     │ datos.Repositorio    │ línea de tiempo · cohortes · capacidad box
                     └──────────┬───────────┘
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                  ▼
        calidad.py         reglas.py          evaluar.py
     (DQ-01…DQ-07)   (score + banderas +   (backtest dinámico
                      contradicciones)        vs. estático)
              └────────┬────────┘
                       ▼
              copiloto.py  ◄── prompts.py · herramientas.py
         ┌─────────────┴──────────────┐
   modo REACTIVO                 modo BARRIDO
   (agente + tools)              (Batches API, perfil precargado)
         └─────────────┬──────────────┘
                       ▼
     auditoria.py (JSONL) · ficha.py (RiskAssessment + Provenance)
     fhir_perfil.py (Bundle FHIR con LOINC)
                       ▼
           Bandeja del médico → decisión → ficha clínica
```

### Módulos

| Archivo | Responsabilidad |
|---|---|
| `config.py` | Cliente Anthropic (header `anthropic-workspace-id`), modelo y versión de prompt |
| `modelos.py` | Esquema pydantic del contrato `perfiles.json` |
| `ingesta_json.py` | Carga, validación, cuarentena, tablas y conciliación con CSV |
| `datos.py` | `Repositorio`: contexto a fecha de corte, línea de tiempo, cohortes y box |
| `calidad.py` | Auditoría de calidad de datos (códigos DQ) y límites de plausibilidad |
| `reglas.py` | Score dinámico, banderas rojas, pisos, contradicciones y alertas de gestión |
| `herramientas.py` | Definición e implementación de las herramientas del copiloto |
| `prompts.py` | Prompt de sistema versionado |
| `copiloto.py` | Bucle del agente (reactivo) y barrido con Batches API |
| `auditoria.py` | Registro JSONL de llamadas, herramientas, análisis y decisiones médicas |
| `ficha.py` | `RiskAssessment` + `Provenance` FHIR del análisis |
| `fhir_perfil.py` | Bundle FHIR del perfil (Patient, ServiceRequest, Encounter, Observation, Appointment) |
| `evaluar.py` | Backtest temporal: AUC y captura del top 10 % |

---

## 4. Datos de entrada

### Contrato oficial: `perfiles.json`

Contiene un objeto por paciente con todas sus series anidadas. Es la forma en que entregaría los datos un sistema hospitalario real (equivalente a `Patient/$everything` en FHIR). Los CSV se usan para **conciliación**: deben contar la misma historia.

```json
{
  "id_paciente": "PAC-HLF-00002",
  "paciente":        { "edad": 49, "sexo": "M", "comuna": "Puente Alto", "...": "..." },
  "lista_espera":    { "id_solicitud": "IC-HLF-00002", "diagnostico_cie10": "I20",
                       "prioridad_inicial": "baja", "fecha_ingreso_lista": "2025-11-08", "...": "..." },
  "eventos_clinicos": [ { "id_evento": "EV-000004", "tipo_evento": "visita_urgencia", "...": "..." } ],
  "mediciones":       [ { "fecha_medicion": "2026-07-08", "tipo_medicion": "presion_sistolica",
                          "valor": 167, "fuera_de_rango": true, "...": "..." } ],
  "citaciones":       [ ]
}
```

### Archivos

| Archivo | Grano | Uso |
|---|---|---|
| `perfiles.json` | 1 objeto por paciente (500) | **Fuente principal** |
| `pacientes.csv` | 1 paciente | Conciliación |
| `lista_espera.csv` | 1 solicitud | Conciliación |
| `eventos_clinicos.csv` | 1 evento (786) | Conciliación |
| `mediciones.csv` | 1 medición (2.487) | Conciliación |
| `citaciones.csv` | 1 cita (257) | Conciliación |
| `agenda_box.csv` | 1 bloque de box/día (2.188) | Capacidad del hospital (solo en CSV) |

El detalle de cada campo está en [`docs/diccionario_datos.md`](docs/diccionario_datos.md).

### Reglas de interpretación

- **Fecha de corte:** solo se usan registros con fecha ≤ corte.
- **`estado` de la solicitud:** es una fotografía al 13-10-2026. Para cortes anteriores se reemplaza por `desconocido_a_la_fecha`.
- **Ausencia de registros:** no es un error. Puede significar estabilidad o un ingreso reciente. Si la ausencia es prolongada, se trata como **silencio clínico** (ver §8.5).
- **`id_medicion`:** las mediciones no traen ID en el origen. Se genera como `MED-` + hash de `(paciente, fecha, tipo, valor)`, por lo que es estable entre JSON y CSV y no depende del orden de las filas.
- **Cruce cita–box:** se hace por `id_box` + `fecha`, porque un box cambia de especialidad según el día.

---

## 5. Instalación

```bash
git clone <repo> copiloto-le-hlf
cd copiloto-le-hlf
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # completar con tus credenciales
```

**Requisitos:** Python 3.11 o superior.

```
anthropic
pandas
numpy
pydantic>=2
scikit-learn
python-dotenv
pytest
```

Ubica los datos en `data/` y los glosarios en `docs/`.

---

## 6. Configuración

### Variables de entorno (`.env`)

| Variable | Descripción |
|---|---|
| `ANTHROPIC_API_KEY` | API key de la organización |
| `ANTHROPIC_WORKSPACE_ID` | Workspace del proyecto (scoping vía header `anthropic-workspace-id`) |
| `ANTHROPIC_MODEL` | Modelo habilitado en el workspace. No se fija en el código |

### Cliente

El SDK oficial envía `anthropic-version` automáticamente. El workspace se fija una sola vez en `config.get_client()`:

```python
anthropic.Anthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    default_headers={"anthropic-workspace-id": os.environ["ANTHROPIC_WORKSPACE_ID"]},
    max_retries=3,
    timeout=120.0,
)
```

> Ningún otro módulo debe crear su propio cliente.

### Parámetros ajustables

Todos los umbrales y pesos clínicos están en `reglas.py` y `calidad.py`. **Son referenciales y deben validarse con clínicos.** Cada cambio se registra en `docs/decisiones.md` y debe pasar los tests.

---

## 7. Uso

### 7.1 Cargar y validar los datos

```python
from copiloto_le.ingesta_json import cargar_perfiles, tablas_desde_perfiles, conciliar_con_csv
from copiloto_le.datos import Repositorio

perfiles, cuarentena = cargar_perfiles("data/perfiles.json")
print(f"Válidos: {len(perfiles)} | En cuarentena: {len(cuarentena)}")

tablas = tablas_desde_perfiles(perfiles, "data/agenda_box.csv")
repo = Repositorio(tablas=tablas)

# Conciliación con los CSV (opcional, recomendado)
print(conciliar_con_csv(tablas, Repositorio().t))   # [] = sin diferencias
```

### 7.2 Auditar la calidad de los datos

```python
from copiloto_le.calidad import auditar

dq = auditar(repo)
print(dq.groupby(["codigo", "nivel"]).size())
```

### 7.3 Evaluar un paciente con el motor de reglas

```python
from copiloto_le.reglas import evaluar_paciente

r = evaluar_paciente(repo, "PAC-HLF-00002", corte="2026-07-08")
print(r["prioridad_inicial"], "→", r["prioridad_calculada"], r["score"])
for m in r["motivos"]:
    print(f'+{m["puntos"]:>5}  {m["motivo"]}  {m["registro_ids"]}')
```

### 7.4 Barrer toda la lista de espera

```python
from copiloto_le.reglas import evaluar_todos

res = evaluar_todos(repo)                          # corte = fecha de referencia
alertas = [x for x in res if x["tipo"] in ("priorizacion", "gestion")]
exclusiones = [x for x in res if x["tipo"] == "exclusion"]
```

Tipos de resultado:

| `tipo` | Significado |
|---|---|
| `priorizacion` | La prioridad calculada supera a la inicial o hay una bandera roja |
| `gestion` | No cambia la prioridad clínica, pero requiere acción (citas fallidas, silencio clínico) |
| `exclusion` | Fallecido o ya atendido: debe salir de la lista |
| `sin_alerta` | Sin cambios |

### 7.5 Análisis del copiloto: modo reactivo

Úsalo para una alerta puntual. El agente consulta herramientas hasta entregar su análisis.

```python
from copiloto_le.copiloto import analizar_alerta

analisis = analizar_alerta(repo, r)          # r = salida de evaluar_paciente
print(analisis["prioridad_sugerida"], analisis["confianza"])
print(analisis["nota_preconsulta"])
```

### 7.6 Análisis del copiloto: modo barrido (Batches API)

Úsalo para el proceso nocturno de toda la lista. Es más económico y cada solicitud lleva el perfil precargado.

```python
from copiloto_le.copiloto import lanzar_barrido, recoger_barrido

batch_id = lanzar_barrido(repo, alertas)
# ... cuando el batch termine:
analisis = recoger_barrido(batch_id, {a["alerta_id"]: a for a in alertas})
```

### 7.7 Registrar la decisión del médico

```python
from copiloto_le import auditoria

auditoria.registrar_decision_medica(
    alerta_id="ALR-PAC-HLF-00002-20260708",
    medico_id="MED-017",
    decision="aceptada",          # aceptada | modificada | rechazada
    prioridad_final="alta",
    comentario="Cita en 7 días + ECG previo.",
)
```

### 7.8 Generar los recursos para la ficha clínica

```python
from copiloto_le.ficha import a_fhir
from copiloto_le.fhir_perfil import perfil_a_bundle

bundle_analisis = a_fhir(r, analisis, decision={"medico_id": "MED-017", "prioridad_final": "alta"})
bundle_perfil = perfil_a_bundle(perfil, corte=date(2026, 7, 8),
                                ids_a_verificar=set(sum(dq.registro_ids, [])))
```

### 7.9 Backtest

```python
from copiloto_le.evaluar import backtest

print(backtest(repo, ["2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01"], horizonte_dias=60))
```

### 7.10 Tests

```bash
pytest -q
```

---

## 8. Motor de reglas: cómo se calcula la prioridad

El motor es **determinista y explicable**: cada punto del score viene con su motivo y los IDs que lo respaldan.

### 8.1 Flujo de evaluación

```
1. Exclusiones duras ─► fallecido (defunción ≤ corte) · ya atendido (solo a fecha de referencia)
2. Score base ────────► según prioridad inicial
3. Eventos clínicos ──► peso por tipo × severidad × relación × decaimiento temporal
4. Mediciones ────────► zona de riesgo · empeoramiento brusco · tendencia (bidireccional)
5. Tiempo de espera ──► exceso sobre el plazo referencial
6. Banderas rojas ────► fuerzan "critica"
7. Pisos ─────────────► fuerzan al menos "alta"
8. Contradicciones ───► "mejoría" registrada vs. mediciones de riesgo
9. Gestión ───────────► citas fallidas · silencio clínico (no alteran el score)
```

### 8.2 Puntaje

| Componente | Regla | Puntos |
|---|---|---|
| Base | baja / media / alta | 20 / 40 / 60 |
| Evento | hospitalización / urgencia / examen alterado / cambio fármaco / control APS | 35 / 25 / 10 / 8 / 0 |
| Severidad (multiplicador) | leve / moderada / grave | ×0,5 / ×1,0 / ×1,5 |
| Ingreso a UCI | adicional | +20 |
| "Estabilización" | descuento (se anula si hay contradicción) | −5 |
| Especialidad distinta a la derivación | multiplicador | ×0,5 |
| Decaimiento temporal | vida media de 90 días | ×0,5^(días/90) |
| Medición en zona de riesgo | según cuánto se aleja del rango | 5 a 15 |
| Empeoramiento brusco | desviación ≥ 0,3 sobre la mediana previa | +12 |
| Tendencia progresiva | pendiente de desviación > 0,05 / 30 días | +10 |
| Exceso de espera | días sobre el plazo (alta 30, media 90, baja 180) / 15 | máx. +15 |

**Score → prioridad:** ≥ 80 crítica · ≥ 60 alta · ≥ 40 media · < 40 baja.

### 8.3 Mediciones bidireccionales

La presión arterial y la glicemia son peligrosas **en ambas direcciones**. Una presión que "baja" puede ser hipotensión, no mejoría.

| Medición | Rango normal | Dirección dañina |
|---|---|---|
| Presión sistólica | 90–139 mmHg | ambas |
| Presión diastólica | 60–89 mmHg | ambas |
| Glicemia | 70–140 mg/dL | ambas |
| HbA1c | 4,0–6,4 % | alta |
| Saturación O₂ | 95–100 % | baja |
| Peak flow | 350–600 L/min | baja |
| EVA dolor | 0–3 | alta |
| PHQ-9 | 0–9 | alta |

### 8.4 Banderas rojas y pisos

**Banderas rojas → prioridad `critica` y contacto inmediato:**

| Medición / evento | Umbral |
|---|---|
| PAS | ≥ 180 o < 80 mmHg |
| PAD | ≥ 120 o < 45 mmHg |
| SatO₂ | < 90 % |
| Glicemia | ≥ 300 o < 54 mg/dL |
| PHQ-9 | ≥ 20 |
| Peak flow | < 200 L/min |
| Urgencia u hospitalización grave | en los últimos 30 días |

**Pisos → al menos `alta`:** EVA ≥ 8 · HbA1c ≥ 10 % · PHQ-9 ≥ 15.

Los pisos existen para no saturar la categoría "crítica" con dolor crónico o control metabólico deficiente, que son importantes pero no son una emergencia vital.

### 8.5 Contradicciones y alertas de gestión

**Contradicción:** un evento de "buena respuesta", "reducción dosis" o "estabilización" con mediciones de riesgo entre 30 días antes y 60 días después. El sistema prioriza la medición objetiva y lo reporta.

> Ejemplo: `PAC-HLF-00321` registra "reducción dosis" y una PAS de 59 mmHg. La pregunta clínica que surge es si la reducción de dosis está relacionada con la hipotensión.

**Alertas de gestión** (no modifican el score):

| Alerta | Condición | Acción sugerida |
|---|---|---|
| Citas fallidas | ≥ 2 inasistencias, reprogramaciones o cancelaciones | Contactar al paciente y evaluar barreras de acceso |
| Silencio clínico | > 180 días en espera y > 180 días sin ningún registro | Verificar vigencia y contactar |
| Estado inconsistente | Asistió a la especialidad pero sigue `en_espera` | Verificación administrativa |

> Las citas fallidas **nunca** bajan la prioridad. Un paciente con angina que no llega a sus citas está en mayor riesgo, no en menor.

---

## 9. Auditoría de calidad de datos

`calidad.py` separa los **errores de registro** del **deterioro real**. Un dato imposible no debe subir ni bajar la prioridad de nadie.

| Código | Nivel | Detecta | Ejemplo en el dataset |
|---|---|---|---|
| `DQ-01` | descartar | Valor fuera de límites fisiológicos | SatO₂ 101 % (00007, 00046), HbA1c 2,2 % (00400) |
| `DQ-02` | verificar | HbA1c repetida con < 30 días de intervalo | 00304, 00469 |
| `DQ-03` | info | Peak flow alto marcado como "fuera de rango" | 00048 (645), 00243 (667) |
| `DQ-04` | verificar | Registro antes del ingreso o después de la defunción | — |
| `DQ-05` | info | Citas no cronológicas en el origen | 00020, 00062 |
| `DQ-06` | verificar | Asistió a la especialidad pero sigue en espera | 00005, 00021, 00033… |
| `DQ-07` | verificar | Medición duplicada | — |

**Límites de plausibilidad** (fuera de ellos, el dato es un error):

| Medición | Rango plausible |
|---|---|
| PAS | 50–260 mmHg |
| PAD | 25–150 mmHg |
| HbA1c | 4,0–18 % |
| Glicemia | 20–700 mg/dL |
| SatO₂ | 50–100 % |
| Peak flow | 50–900 L/min |
| EVA | 0–10 |
| PHQ-9 | 0–27 |

El informe de auditoría también sirve al **equipo de registros del hospital** para corregir los datos en el origen.

---

## 10. El copiloto IA: cómo se comporta

### 10.1 Rol

El copiloto es un asistente para **médicos contralores**. Recibe la alerta del motor de reglas y entrega un análisis estructurado y citado. **No decide.**

Sus tareas:
1. Reconstruir la historia del paciente durante la espera.
2. Ordenar datos desordenados: inconsistencias, errores y contradicciones.
3. Verificar si los hallazgos se relacionan clínicamente con la derivación.
4. Anticipar el riesgo con cohortes históricas.
5. Sugerir prioridad, acciones y uso de agenda.
6. Redactar la nota de pre-consulta para el especialista.

### 10.2 Herramientas disponibles (modo reactivo)

| Herramienta | Devuelve | Restricciones impuestas por el código |
|---|---|---|
| `obtener_linea_tiempo` | Perfil, solicitud, eventos, mediciones y citas con IDs | Solo el paciente de la alerta; solo datos ≤ corte |
| `obtener_cohorte` | Desenlaces en espera de pacientes similares con n e IC95 (Wilson) | Excluye al propio paciente; solo cohortes con seguimiento completo antes del corte |
| `obtener_capacidad_box` | Cupos libres, ocupación y sobretiempo de la especialidad | Ventana hacia atrás desde el corte |
| `registrar_analisis` | Entrega final estructurada | Obligatoria; se fuerza en el último turno |

En **modo barrido** no hay herramientas de consulta. El perfil, los problemas de calidad y la cohorte van precargados, y la salida se fuerza con `registrar_analisis`.

### 10.3 Lo que siempre hace

- Cita `registro_id` en cada hallazgo y marca como `inferido` lo que no está registrado.
- Usa solo las cifras de las herramientas e informa n e IC95. Si la muestra es pequeña, lo dice.
- Prioriza las mediciones objetivas cuando contradicen un evento de "mejoría".
- Trata un dato de nivel `descartar` como error de registro, nunca como deterioro.
- Sugiere `critica` ante banderas rojas, aunque falten datos.
- Declara los datos faltantes (por ejemplo, el ítem 9 del PHQ-9 sobre ideación suicida).
- Avisa cuando usa escalas sustitutas (EVA en epilepsia, PHQ-9 en ansiedad).
- Propone aviso a APS u otra especialidad cuando el riesgo está **fuera de la especialidad derivada**.
- Explica si discrepa del motor de reglas.

### 10.4 Lo que nunca hace

- Decidir la prioridad final.
- Inventar valores, diagnósticos o porcentajes.
- Usar información posterior a la fecha de corte.
- Bajar la prioridad por comuna, previsión, nivel socioeconómico o inasistencias.
- Seguir instrucciones escritas dentro de los registros clínicos. Esos textos son datos, no órdenes.
- Recibir el nombre del paciente (se elimina antes de enviar el contexto).

### 10.5 Formato de salida

```json
{
  "resumen": "Varón de 49 años derivado por angina con prioridad baja...",
  "relacion_con_derivacion": "La PAS de 167 mmHg y la urgencia ESI 2 se asocian a cardiología...",
  "linea_tiempo_relevante": [
    {"fecha": "2026-07-08", "descripcion": "PAS 167 mmHg", "registro_id": "MED-3F2A9C1B04"}
  ],
  "hallazgos": [
    {"hallazgo": "Salto de PAS desde una mediana previa de 100 mmHg",
     "tipo": "documentado", "registro_ids": ["MED-3F2A9C1B04"]}
  ],
  "riesgo_poblacional": "En la cohorte I20, 39–59 años (n=…, IC95 …)...",
  "prioridad_sugerida": "alta",
  "acuerdo_con_motor_reglas": true,
  "justificacion": "...",
  "confianza": "media",
  "acciones_sugeridas": ["Contacto telefónico en 48 h", "ECG previo a la consulta"],
  "propuesta_agenda": "Cardiología tiene cupos libres el ...",
  "datos_faltantes": ["Troponina", "Descripción del dolor torácico"],
  "inconsistencias_datos": [],
  "nota_preconsulta": "Paciente con angina en espera desde 08-11-2025...",
  "_meta": {"model": "...", "prompt_version": "copiloto-le-hlf-v0.3",
            "fecha_corte": "2026-07-08", "estado": "pendiente_revision_medica"}
}
```

### 10.6 Casos de comportamiento esperado

| Paciente | Situación | Comportamiento esperado del copiloto |
|---|---|---|
| 00002 | PAS 167 → urgencia ESI 2 → hospitalización | Relacionar con la angina y sugerir alta o crítica antes de la urgencia |
| 00001 | PHQ-9 de 4 a 19 | Declarar faltante el ítem 9 y sugerir evaluación de riesgo suicida |
| 00321 / 00177 | "Reducción dosis" con PAS 59/69 | Crítica; reportar la contradicción y plantear la pregunta clínica |
| 00170 | Glicemia 33 mg/dL e inasistencia | Crítica; alerta de gestión; contacto inmediato |
| 00123 | Hipoglicemia grave en derivación por reflujo | Hallazgo fuera de especialidad: aviso a APS |
| 00010 | UCI etiquetada como "Traumatología" (hombro) | Advertir plausibilidad dudosa de la asociación |
| 00020 | Tres citas fallidas con angina | Alerta de gestión, sin bajar prioridad |
| 00457 / 00498 | Más de 500 días sin ningún registro | Silencio clínico: verificar vigencia y contactar |
| 00007 | SatO₂ 101 % | Reportar como error de registro, sin efecto en el score |

---

## 11. Trazabilidad hacia la ficha clínica

### 11.1 Registro de auditoría (`auditoria.jsonl`)

| `tipo` | Contenido |
|---|---|
| `llamada_modelo` | `request_id`, modelo, `prompt_version`, `stop_reason`, uso de tokens |
| `tool` | Herramienta, argumentos y hash del resultado |
| `analisis_ia` | Análisis completo y hash de la alerta |
| `decision_medica` | Médico, decisión, prioridad final y comentario |
| `error_batch` | Solicitudes fallidas del modo barrido |

Con este registro se puede responder **quién vio qué, cuándo, con qué datos, qué sugirió la IA y qué decidió el médico**.

### 11.2 Mapeo FHIR R4

| Elemento | Recurso | Codificación |
|---|---|---|
| Paciente | `Patient` | — |
| Solicitud de interconsulta | `ServiceRequest` | CIE-10 |
| Urgencia / hospitalización / control | `Encounter` | clase `EMER` / `IMP` / `AMB` |
| Medición | `Observation` | LOINC (ver tabla) |
| Cita | `Appointment` | `fulfilled` / `noshow` / `cancelled` |
| Análisis de riesgo | `RiskAssessment` | `preliminary` → `final` tras la decisión |
| Origen del análisis | `Provenance` | modelo + versión (assembler), médico (verifier) |

| Medición | LOINC |
|---|---|
| Presión sistólica | 8480-6 |
| Presión diastólica | 8462-4 |
| HbA1c | 4548-4 |
| Glucosa | 2339-0 |
| SpO₂ | 59408-5 |
| Peak flow | 19935-6 |
| PHQ-9 total | 44261-6 |
| Severidad del dolor | 72514-3 |

> Los códigos deben validarse con el equipo de terminología y la guía **CL Core** de HL7 Chile. Las observaciones marcadas por la auditoría de calidad se envían con una nota de "verificar antes de usar".

---

## 12. Validación y backtest

### 12.1 Backtest temporal

Como el dataset no trae una respuesta de referencia, la validación se hace así: **¿el score calculado en la fecha T anticipa urgencias, hospitalizaciones o muertes entre T y T + horizonte mejor que la prioridad estática?**

| Métrica | Qué mide |
|---|---|
| `auc_dinamico` vs `auc_estatico` | Capacidad de discriminar quién tendrá un desenlace grave |
| `captura_top10_*` | Porcentaje de desenlaces que caen en el 10 % de mayor prioridad |
| Días de anticipación | Diferencia entre la alerta y el evento grave |

Para evitar sobreajuste, calibra los pesos con los cortes iniciales y reserva los últimos meses como prueba.

### 12.2 Tests clínicos (`tests/test_casos_clinicos.py`)

| Test | Verifica |
|---|---|
| `test_00002_sube_antes_de_la_urgencia` | Detección anticipada |
| `test_hipotension_e_hipoglicemia_son_criticas` | Bidireccionalidad y contradicciones |
| `test_sato2_101_se_descarta` | Auditoría de calidad |
| `test_silencio_clinico` | Alertas de gestión |
| `test_fallecido_se_excluye` | Exclusiones |
| `test_equidad_comuna_no_cambia_prioridad` | Equidad |

**Regla:** ningún umbral cambia sin que pasen los tests y sin una entrada en `docs/decisiones.md`.

### 12.3 Validación del copiloto

- Revisión de 30 casos por médicos: ¿cita bien?, ¿inventa?, ¿discrepa con razón?
- Métricas: porcentaje de hallazgos con cita verificable, tasa de desacuerdo IA–médico por especialidad y alertas por médico por día (para vigilar la fatiga de alertas).
- Cada cambio de `PROMPT_VERSION` vuelve a pasar el set de casos de la §10.6.

---

## 13. Trabajo con Kiro

El proyecto está preparado para desarrollarse en Kiro. Kiro no se reentrena con los archivos; relee en cada tarea el contexto que se mantiene actualizado en el repositorio.

```
.kiro/
├── steering/
│   ├── product.md          (always)   principios y reglas no negociables
│   ├── tech.md             (always)   stack, cliente Anthropic, versionado
│   ├── structure.md        (always)   responsabilidad de cada módulo
│   ├── reglas-clinicas.md  (fileMatch reglas.py / calidad.py)
│   └── datos.md            (manual, #datos) incluye el diccionario y los ejemplos
├── specs/                  requisitos → diseño → tareas por funcionalidad
└── hooks/                  automatizaciones
```

### Hooks recomendados

| Hook | Disparador | Acción |
|---|---|---|
| Validar reglas | Guardar `reglas.py` o `calidad.py` | Ejecutar `pytest -q` y explicar los fallos |
| Nuevo dataset | Cambios en `data/` | Validar, conciliar, auditar y actualizar `docs/informe_calidad.md` |
| Versión de prompt | Guardar `prompts.py` | Exigir cambio de `PROMPT_VERSION` y registrarlo |
| Glosario | Cambios en `docs/*.md` | Detectar contradicciones con el steering |

### Bitácora de decisiones (`docs/decisiones.md`)

Es la memoria a largo plazo del proyecto:

```markdown
## AAAA-MM-DD · Título
- Cambio:
- Motivo (casos / datos):
- Validado por:
- Test asociado:
```

---

## 14. Seguridad, privacidad y normativa

- **Datos sintéticos únicamente en este repositorio.** Los datos reales requieren un entorno aprobado por el hospital.
- **Minimización:** el modelo no recibe nombres; en producción el RUT se pseudonimiza con hash y sal secreta.
- **Credenciales:** `.env` está fuera de control de versiones y nunca se comparte en chats.
- **Normativa chilena a revisar antes de un piloto real:**
  - Ley 20.584 (derechos y deberes del paciente; ficha clínica).
  - Ley 19.628 y Ley 21.719 (protección de datos personales).
  - Posible clasificación como software de dispositivo médico ante el ISP.
- **Responsabilidad clínica:** la institución debe definir quién revisa las alertas, en qué plazo (por ejemplo, < 24 h para las críticas) y qué ocurre si nadie las revisa.

---

## 15. Limitaciones conocidas

| Limitación | Impacto | Mitigación |
|---|---|---|
| El código aún no se ha ejecutado de punta a punta | Puede haber errores de integración | Spec `integracion-v0.3` en Kiro, con los tests como árbitro |
| Pesos y umbrales son referenciales | Pueden sobre o subpriorizar | Calibración con backtest y validación clínica |
| Datos sintéticos | Los patrones no reflejan la epidemiología real | Piloto en sombra con datos reales en un entorno aprobado |
| Detalle de eventos poco específico ("resultado alterado") | Menor precisión clínica | En producción, integrar resultados de laboratorio y diagnósticos de egreso reales |
| Escalas sustitutas por especialidad | Señal clínica limitada | Incorporar escalas específicas (GAD-7, frecuencia de crisis, troponina) |
| Cohortes pequeñas por diagnóstico y edad | Intervalos amplios | Se reportan n e IC95; advertencia si n < 10 |
| Los datos históricos reflejan a quien logró consultar | Sesgo de acceso | Advertido en el prompt; análisis por comuna y previsión en el backtest |

---

## 16. Hoja de ruta

| Etapa | Entregable |
|---|---|
| 1. Integración v0.3 | `pytest -q` en verde |
| 2. Informe de calidad | Conteo DQ real y umbrales recalibrados |
| 3. Backtest v0.2 vs v0.3 | Cuantificar el aporte de la bidireccionalidad y las contradicciones |
| 4. Barrido nocturno | Análisis IA de toda la lista con Batches API |
| 5. Bandeja del médico | UI (Streamlit) para aceptar, modificar o rechazar sugerencias |
| 6. Optimización de box | Asignación de cupos ociosos a pacientes críticos |
| 7. FHIR validado | Bundles conformes a CL Core contra un servidor de pruebas |
| 8. Piloto en sombra | Comparar sugerencias con la práctica real antes de usarlo en producción |

---

## 17. Glosario

| Término | Definición |
|---|---|
| **SIC / Interconsulta** | Solicitud de atención de especialidad (`id_solicitud`, `IC-`) |
| **APS / CESFAM** | Atención primaria de salud |
| **ESI** | Emergency Severity Index (1 = máxima urgencia, 5 = mínima) |
| **Fecha de corte** | Día que se simula; solo se usan datos conocidos hasta entonces |
| **Bandera roja** | Hallazgo de riesgo vital que fuerza la prioridad crítica |
| **Piso** | Hallazgo que fuerza al menos la prioridad alta |
| **Contradicción** | Evento de mejoría que coincide con mediciones de riesgo |
| **Silencio clínico** | Espera prolongada sin ningún registro del paciente |
| **Cuarentena** | Perfiles que no cumplen el contrato y quedan fuera hasta revisión |
| **DQ** | Data Quality: código de hallazgo de la auditoría de datos |
| **Cohorte** | Grupo de pacientes comparables (CIE-10, edad, origen) usado para estimar riesgo |
| **IC95 (Wilson)** | Intervalo de confianza del 95 % para proporciones, robusto con muestras pequeñas |
| **Nota de pre-consulta** | Resumen citado que recibe el especialista antes de la consulta inicial |
| **PROMPT_VERSION** | Versión del prompt del copiloto; cambia con cada modificación |

---

*Sistema de apoyo a la decisión clínica. Las sugerencias del copiloto requieren siempre la revisión y aprobación de un profesional de la salud.*
Un detalle sobre su uso en Kiro: puedes referenciarlo desde el steering de structure.md con #[[file:README.md]]. Así, cada vez que actualices el README con nuevas decisiones o funcionalidades, Kiro trabaja con la versión vigente.