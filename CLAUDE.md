# CLAUDE.md

Contexto para agentes de código que trabajen en este repositorio.

## Qué es este proyecto

Prototipo para el desafío **"Evaluación dinámica del riesgo y priorización asistencial"** del Hospital Clínico Dra. Eloísa Díaz La Florida (HLF, SSMSO), en el Hackatón de IA Generativa AWS Breaking Barriers Chile 2026 (14 al 16 de octubre, Universidad de Chile).

**Problema:** la prioridad de un paciente en la lista de espera de especialidad se asigna una sola vez y queda congelada, aunque su salud cambie mientras espera.

**Objetivo:** detectar eventos clínicos durante la espera (urgencias, hospitalizaciones, cambios de tratamiento, descompensaciones) y proponer una **prioridad actualizada, explicable y trazable**, que el equipo clínico valida.

**Alcance inicial:** oftalmología del HLF, con listas separadas de **consultas nuevas** y de **controles**.

## Principio rector (no negociable)

> La herramienta **propone y explica**; el equipo clínico **decide**.
> La posición en la lista no equivale a una fecha garantizada de atención.

Consecuencias para el código:
- Toda prioridad propuesta debe venir con su **explicación**: qué eventos o factores la cambiaron y cuánto aportó cada uno.
- Todo cambio de prioridad debe quedar **registrado**: valor anterior, valor nuevo, motivo, fecha y versión del modelo o las reglas.
- Nunca sobrescribir la prioridad clínica asignada por una persona. La propuesta del sistema se guarda en un campo aparte.
- Preferir reglas y puntajes interpretables por sobre modelos de caja negra. Si se usa un LLM, debe citar el fragmento de texto del que sacó cada hallazgo.

## Datos y privacidad

- El HLF entrega una base **acotada y anonimizada** de usuarios de oftalmología. Ver `docs/datos.md`.
- **Nunca** subir datos del hospital al repositorio. Van en `data/raw/`, que debe estar en `.gitignore`.
- No enviar datos de pacientes a servicios externos fuera del entorno autorizado del hackatón.
- Para tests y demos, usar datos sintéticos (`data/synthetic/`).
- No intentar reidentificar personas ni cruzar los datos con fuentes externas para ese fin.

## Documentación

| Archivo | Contenido |
|---|---|
| `docs/contexto.md` | El desafío, el problema, la ruta del paciente y el caso de don Manuel |
| `docs/datos.md` | Esquema esperado de los datos entregados por el HLF |
| `docs/kpis.md` | Métricas de éxito y cómo calcularlas |
| `docs/enfoque.md` | Propuesta de arquitectura y del puntaje de priorización |
| `docs/datasets-externos.md` | Datasets públicos de síntomas, enfermedades y severidad |
| `docs/glosario.md` | Siglas y términos del sistema de salud chileno |

Leer `docs/contexto.md` y `docs/datos.md` antes de escribir código que toque datos.

## Convenciones

- Idioma: documentación, nombres de dominio y mensajes visibles al usuario en **español**. Código e identificadores pueden ir en inglés, pero los conceptos de dominio conservan su nombre (`interconsulta`, `lista_espera`, `causal_egreso`).
- Diagnósticos en **CIE-10** (catálogo DEIS/MINSAL). Normalizar los códigos antes de compararlos (mayúsculas, con punto: `E11.3`).
- Fechas en ISO 8601. Calcular los días de espera desde la fecha de ingreso a la lista, no desde la derivación, salvo que se indique otra cosa.

## Estado

Stack, comandos de instalación y de ejecución: **por definir**. Actualizar esta sección cuando existan.
