# Enfoque técnico propuesto

> Propuesta inicial para discutir con el equipo. Las decisiones de stack están por definir.
> Basada en el dataset entregado (`docs/datos.md`): 7 especialidades, eventos y mediciones con fecha, agenda de box y citaciones. No hay respuesta de referencia.

El reto tiene dos ejes:
1. **Priorización clínica evolutiva:** que la prioridad se mueva según cómo evoluciona el paciente mientras espera.
2. **Uso del recurso box:** aprovechar mejor los cupos (inasistencias, ocupación, sobretiempo).

Se mantienen **separados**: el riesgo de no asistir no debe subir ni bajar la prioridad clínica.

## Flujo general

```
 pacientes, lista_espera, eventos_clinicos, mediciones, citaciones, agenda_box
        │
        ▼
 1. Ingesta y normalización ── fechas ISO, CIE-10, exclusión de fallecidos
        │
        ▼
 2. Vista a fecha de corte ──── solo registros con fecha ≤ t
        │
        ▼
 3. Señales por paciente ────── eventos ponderados + tendencia de mediciones
        │
        ▼
 4. Puntaje clínico ─────────── reglas interpretables → prioridad propuesta
        │                        (alta / media / baja)
        ▼
 5. Propuesta + explicación ─── factores, aporte de cada uno, fuente, versión
        │
        ├──► 6. Uso del box ─── riesgo de no-show, ocupación, sobretiempo
        │
        ▼
 7. Validación clínica ──────── el equipo acepta, ajusta o rechaza (queda registrado)
```

## 1. Ingesta y normalización
- Cargar los CSV (o `perfiles.json`, que ya viene anidado por paciente).
- Unir por `id_paciente`. Hay una solicitud por paciente.
- CIE-10: mayúsculas; los códigos del dataset son de 3 caracteres.
- **Excluir** de la lista activa a quien tenga `fallecido = true` a partir de `fecha_defuncion`, y a quien esté `atendido`.

## 2. Vista a fecha de corte
Toda función de puntaje recibe una fecha `t` y solo ve registros con fecha ≤ `t`. Esto permite:
- reconstruir la prioridad que se habría propuesto cualquier día (línea de tiempo del puntaje);
- medir el **tiempo a reevaluación** (`docs/kpis.md`);
- escribir tests como "antes de la urgencia, baja; después, alta" (`docs/casos-ejemplo.md`).

## 3. Señales por paciente

### Eventos clínicos
Cada evento aporta según su tipo y subtipo, con decaimiento en el tiempo. Tabla de pesos inicial (a calibrar con el equipo clínico):

| `tipo_evento` · `subtipo` | Peso inicial `w` |
|---|---|
| hospitalizacion · ingreso UCI | +12 |
| hospitalizacion · ingreso hospitalario | +9 |
| visita_urgencia · descompensación grave | +9 |
| visita_urgencia · triage ESI 2 | +8 |
| visita_urgencia · descompensación | +5 |
| examen_alterado · resultado alterado | +3 |
| cambio_farmaco · aumento dosis | +3 |
| control_aps · control / control crónico / control de rutina | 0 |
| control_aps · estabilización | −1 |
| control_aps · buena respuesta | −2 |
| cambio_farmaco · reducción dosis | −2 |

Los valores son un punto de partida para discutir, no un estándar clínico.

### Mediciones
Por paciente y `tipo_medicion`, sobre la ventana hasta `t`:
- **Último valor** y su **distancia al rango normal**, normalizada por el ancho del rango (no solo el booleano `fuera_de_rango`).
- **Tendencia:** pendiente de las últimas *k* mediciones. Captura el deterioro progresivo (PHQ-9 de 4 a 19 en PAC-HLF-00001).
- **Proporción fuera de rango** en la ventana reciente.

Para las escalas donde valores altos son malos (PHQ-9, EVA, presión, glicemia, HbA1c) la tendencia al alza suma. Para saturación O₂ y peak flow, la tendencia a la baja suma.

## 4. Puntaje clínico (borrador)

```
puntaje(t) = base(prioridad_inicial)
           + w_edad · factor_edad
           + w_espera · factor_tiempo_espera(t − fecha_ingreso_lista)
           + Σ_eventos  w(tipo, subtipo) · exp(−λ·(t − t_e))
           + Σ_mediciones  w_med · (desviación + tendencia)
```

- `base`: parte de la prioridad inicial (por ejemplo alta = 20, media = 10, baja = 0). La propuesta **se mueve desde la foto**, no la ignora.
- `exp(−λ·Δt)`: un evento de hace un año pesa menos que uno de la semana pasada. Con λ = ln 2 / 90 días, la mitad del peso se pierde en 3 meses.
- `factor_tiempo_espera`: crece lento; nunca debe superar a un evento grave reciente.
- Pasar el puntaje a **alta / media / baja** con umbrales fijos y versionados.

**Reglas duras sugeridas** (alerta inmediata, sin importar el puntaje):
- Cualquier evento grave en los últimos 30 días (urgencia ESI 2, descompensación grave, hospitalización, ingreso UCI) → proponer **alta** y alertar.

Umbrales iniciales del puntaje: alta ≥ 20, media 10–19,9, baja < 10. El árbol de decisión completo está en `docs/arquitectura.md`.

### ⚠️ Pendiente: riesgo basal según el diagnóstico

**Problema.** Dos personas pueden tener un **riesgo basal distinto por su diagnóstico** y aun así quedar con el **mismo nivel de prioridad**. Por ejemplo, una angina de pecho (I20) o una insuficiencia cardíaca (I50) no conllevan el mismo riesgo de daño durante la espera que un reflujo (K21) o un lumbago (M54), aunque las cuatro solicitudes figuren como "media". Hay que resolverlo para que la prioridad sea más justa.

**Evidencia en los datos.** El EDA muestra que la prioridad inicial no se asocia con la especialidad ni con el diagnóstico (χ² p = 0,90). Por ejemplo, solo el 7,9 % de las anginas (I20) tiene prioridad alta, frente al 28,6 % de las obesidades (E66). El borrador actual del puntaje tampoco lo corrige: `base_prioridad` sale solo de `prioridad_inicial` y no hay ningún término que dependa del diagnóstico.

**Por qué importa.**
- Con tres niveles, dentro de "media" conviven pacientes con riesgos muy distintos, y el orden de atención entre ellos queda al azar.
- Un mismo evento pesa distinto según la condición de fondo: una urgencia en un paciente con insuficiencia cardíaca es más preocupante que en uno con lumbago.

**Opciones a evaluar con el equipo clínico:**
1. **Variable `riesgo_basal_dx`** por código CIE-10 (17 diagnósticos en el dataset). Sería una tabla de puntos definida y validada con los clínicos, por ejemplo según el riesgo de daño irreversible o de muerte durante la espera. Sumaría al puntaje como un factor más, con su aporte visible en la explicación.
2. **Ordenar dentro de cada nivel** por el puntaje continuo. El nivel (alta, media, baja) se mantiene, pero la bandeja muestra primero a quien tiene más riesgo dentro del mismo nivel.
3. **Ajustar el peso de los eventos según el diagnóstico**, usando el término `relevancia(e, dx)` del borrador original: el mismo evento aporta más si agrava la condición de base.
4. **Revisar la escala de niveles**: evaluar si tres niveles bastan o si hacen falta subniveles, en coherencia con la escala que usa hoy el HLF.

Cualquiera de las opciones debe ser **explicable**: el factor "riesgo basal por diagnóstico" debe aparecer en la explicación con su aporte, y los puntos por diagnóstico deben quedar versionados en `version_reglas`.
- Paciente fallecido → excluir.

**Bajar la prioridad** solo con evidencia de mejora (eventos de mejora y mediciones normales sostenidas), nunca solo por falta de datos. Un paciente sin registros conserva su prioridad inicial.

## 5. Explicación
Cada propuesta guarda algo como:
```json
{
  "id_solicitud": "IC-HLF-00002",
  "fecha_corte": "2026-08-10",
  "prioridad_inicial": "baja",
  "prioridad_propuesta": "alta",
  "puntaje": 24.6,
  "factores": [
    {"factor": "hospitalización: ingreso hospitalario", "fecha": "2026-08-06",
     "aporte": 8.6, "fuente": "evento:EV-000004"},
    {"factor": "urgencia: triage ESI 2", "fecha": "2026-07-20",
     "aporte": 6.9, "fuente": "evento:EV-000003"},
    {"factor": "presión sistólica 167 mmHg (fuera de rango)", "fecha": "2026-07-08",
     "aporte": 3.1, "fuente": "medicion:PAC-HLF-00002/2026-07-08/presion_sistolica"}
  ],
  "version_modelo": "reglas-v0.1"
}
```
Los `id_evento` de este ejemplo son ilustrativos. Las mediciones no tienen ID propio; se referencian por `(id_paciente, fecha_medicion, tipo_medicion)`.

## 6. Uso del box

Señales del paciente (separadas del puntaje clínico):
- **Riesgo de no-show:** historial de `no_asistio` y `reprogramo` en `citaciones`. Las variables de contexto (edad, comuna, previsión, nivel socioeconómico) se pueden usar, pero revisar la equidad (ver `docs/kpis.md`) para no castigar a grupos con más barreras de acceso.
- **Acción sugerida**, no automática: confirmar la cita por teléfono, ofrecer un horario alternativo o considerar sobreagendar en bloques con alto no-show.

Señales de la agenda (`agenda_box`):
- **Ocupación** = `cupos_usados / capacidad_cupos` por box, especialidad y día (global ≈ 74 %).
- **Sobretiempo** por box y especialidad.
- **Cupos libres** por especialidad frente a la demanda de alta prioridad en espera: ¿hay capacidad ociosa en una especialidad mientras otra acumula pacientes de alta prioridad?

`citaciones` y `agenda_box` no cruzan bien bloque a bloque (`docs/datos.md`): analizarlas por separado y agregar por especialidad y semana.

## 7. Interfaz (MVP)
- Lista priorizada por especialidad, con los **cambios recientes** destacados (subió, bajó, nuevo evento grave).
- Detalle por paciente: línea de tiempo de eventos, mediciones y citas, junto a la evolución del puntaje y la explicación.
- Selector de **fecha de corte** para la demo ("¿qué habría propuesto el sistema el 2026-07-21?").
- Botón para **aceptar, ajustar o rechazar**, con registro de quién decidió y por qué.
- Panel del box: ocupación, inasistencias y sobretiempo por especialidad.
- Panel de KPIs (`docs/kpis.md`).

## Extensiones (fuera del dataset actual)
- **Texto libre del RCE** (indicaciones de control, fármacos): el dataset no lo trae. Si se agrega, extraer con NER en español o un LLM que cite el fragmento literal y validar que exista en la nota. Datasets útiles en `docs/datasets-externos.md`.
- **Comorbilidades y riesgo ACG**, cuando estén disponibles.
- **Oftalmología** y el caso de don Manuel, con datos sintéticos propios en `data/synthetic/`.
