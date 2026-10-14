# Enfoque técnico propuesto

> Propuesta inicial para discutir con el equipo. Las decisiones de stack están por definir.

## Flujo general

```
 Fuentes (lista de espera, RCE, eventos, comorbilidades)
        │
        ▼
 1. Ingesta y normalización ── CIE-10 normalizado, fechas ISO, ID anonimizado
        │
        ▼
 2. Extracción de texto libre ── diagnósticos, síntomas, indicaciones de control
        │                        (NER en español y/o LLM con cita del fragmento)
        ▼
 3. Detección de eventos ─────── urgencia, hospitalización, cambio de tratamiento,
        │                        descompensación, inasistencia
        ▼
 4. Puntaje de prioridad ─────── reglas interpretables + factores ponderados
        │
        ▼
 5. Propuesta + explicación ──── prioridad propuesta, factores, fuentes, versión
        │
        ▼
 6. Validación clínica ───────── el equipo acepta, ajusta o rechaza (queda registrado)
```

## 1. Ingesta y normalización
- Unir todas las tablas por el ID anonimizado.
- Normalizar CIE-10 (catálogo DEIS/MINSAL). El paquete R `ciecl` o una tabla equivalente sirven de referencia.

## 2. Extracción de texto libre
Dos objetivos:
- **Hallazgos clínicos:** diagnósticos y síntomas en las notas del RCE y en la interconsulta. Datasets útiles: Chilean Waiting List Corpus y SympTEMIST (ver `docs/datasets-externos.md`).
- **Indicaciones de control:** frases como "control en 3 meses" o "citar en 6 semanas", convertidas en `plazo_dias` y `fecha_control_esperada`. Esto ataca la brecha 2 (controles invisibles).

Si se usa un LLM:
- Pedir salida estructurada (JSON) con el **fragmento literal** de origen.
- Validar que el fragmento exista realmente en la nota.
- No enviar datos fuera del entorno autorizado.

## 3. Detección de eventos
Un evento es **relevante** si puede indicar progresión de la enfermedad por la que espera o de una comorbilidad que la agrava. Ejemplos en oftalmología:
- Urgencia u hospitalización por hiperglicemia o crisis hipertensiva → riesgo de retinopatía diabética o hipertensiva.
- Inicio o ajuste de insulina, o deterioro de la función renal → mal control metabólico.
- Urgencia oftalmológica (dolor ocular, pérdida súbita de visión) → posible urgencia propia.

## 4. Puntaje de prioridad (borrador)

```
puntaje(t) = w1·severidad_dx_derivacion
           + w2·comorbilidad (Charlson y/o ACG)
           + w3·factor_edad
           + w4·factor_tiempo_espera_vs_plazo_clinico
           + Σ_eventos  w_tipo(e) · relevancia(e, dx) · exp(−λ·(t − t_e))
```

- `relevancia(e, dx)`: qué tan relacionado está el evento con el diagnóstico en espera (por ejemplo, hiperglicemia ↔ retinopatía diabética = alta).
- Los pesos `w` y `λ` se **calibran con el equipo clínico** y se validan con kappa contra la priorización experta.
- Pasar el puntaje a la escala de prioridad que use hoy el HLF.

**Regla dura sugerida:** ciertos hallazgos (por ejemplo, pérdida súbita de visión) generan una alerta inmediata, sin importar el puntaje.

## 5. Explicación
Cada propuesta guarda algo como:
```json
{
  "id_solicitud": "...",
  "prioridad_anterior": "baja",
  "prioridad_propuesta": "alta",
  "factores": [
    {"factor": "urgencia por hiperglicemia", "fecha": "2026-08-02", "aporte": 12.4,
     "fuente": "evento#123"},
    {"factor": "diabetes mellitus tipo 2 (E11)", "aporte": 6.0, "fuente": "comorbilidad"}
  ],
  "version_modelo": "reglas-v0.1"
}
```

## 6. Interfaz (MVP)
- Lista priorizada con los **cambios recientes** destacados.
- Detalle por paciente: línea de tiempo de eventos y explicación del cambio.
- Botón para **aceptar, ajustar o rechazar**, con registro de quién decidió y por qué.
- Panel de KPIs (`docs/kpis.md`).
