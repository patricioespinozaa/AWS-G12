# U3 — Entidades de dominio

Decisiones: H-1=B (cuatro vistas + "¿Qué cambió?"), H-2=A (solo lectura, salvo decisiones), H-3=A (usar los análisis existentes), H-4=B (lista fija de médicos ficticios).

U3 no redefine contratos: usa `Evaluacion`, `ContextoPaciente`, `HallazgoDQ`, `ResultadoCohorte` y `Decision` de `modelos.py`, y `RegistroAnalisis` de `copiloto/modelos.py`.

## Fuentes (todas de solo lectura, salvo `decisiones.jsonl`)

| Dato | Lectura | Notas |
|---|---|---|
| Cortes disponibles | Carpetas `salidas/propuestas/fecha_corte=*/version_reglas=*/` | Hoy: 2026-07-19, 07-20, 07-21, 08-10, 10-13 |
| Propuestas | `leer_propuestas(raiz, corte, version)` | Una `Evaluacion` por solicitud |
| Análisis IA | `leer_analisis(...)`, `leer_fallidos(...)` | Solo 07-19 a 07-21. `RegistroAnalisis.revision_equidad` puede traer frases marcadas |
| Hallazgos DQ, cohortes | `leer_hallazgos_dq`, `leer_cohortes` | |
| Línea de tiempo | `contexto_a_fecha()` + `linea_tiempo()` sobre el dataset | La `Evaluacion` no guarda el contexto. Se reconstruye y se verifica `huella_contexto` igual que en U2. Si no coincide, el detalle lo advierte y no muestra la línea de tiempo |
| Especialidad | Del dataset (solicitud) | La `Evaluacion` no la trae; la propuesta en Parquet sí tiene la columna `especialidad` |
| Decisiones | `salidas/decisiones/decisiones.jsonl` | Solo agregar |

## Entidades propias de U3

| Entidad | Campos | Uso |
|---|---|---|
| `Medico` | `id` (`MED-DEMO-01`…), `nombre` ficticio | Lista fija en `app/config_demo.py` (H-4). Sin datos reales |
| `FilaBandeja` | `id_solicitud`, `especialidad`, `prioridad_inicial`, `nivel_propuesto`, `magnitud` (diferencia de niveles), `puntaje`, `tipo_resultado`, `banderas`, `tiene_analisis`, `revision_equidad` (bool), `estado_decision` (`pendiente`, `aceptada`, `ajustada`, `rechazada`) | Vista bandeja |
| `CambioEntreCortes` | `id_solicitud`, `nivel_a`, `nivel_b`, `puntaje_a`, `puntaje_b`, `registros_nuevos[]` (IDs con fecha en (corte_a, corte_b]), `banderas_nuevas[]`, `factores_nuevos[]` | Vista "¿Qué cambió?" |
| `ResumenCobertura` | Contenido de `salidas/resumen/…/resumen.json` + conteo de análisis y fallidos del corte | Panel |
| `EstadoDecision` | Última `Decision` por `(id_solicitud, fecha_corte, version_reglas)` | Las anteriores se muestran como historial; ninguna se edita |
