# Aclaración — Resiliencia (contradicción R1 ↔ R2)

Detecté una contradicción entre dos respuestas que necesito resolver antes de redactar los requisitos.

## La contradicción
- **R1 = B** → estrategia **Pilot Light** (RPO/RTO de decenas de minutos). Pilot Light mantiene **datos vivos replicados en una segunda región**, con los servicios apagados listos para escalar. Es, por definición, una estrategia **multi-región**.
- **R2 = A** → **una sola región, multi-AZ**, sin DR entre regiones.

No pueden coexistir: Pilot Light requiere una segunda región; "una sola región" la excluye.

Además, el sistema es un **lote nocturno** con ventana de cumplimiento de 72 h (KPI principal). Eso significa que, ante una caída, re-ejecutar el lote al día siguiente suele estar dentro del objetivo, lo que hace que un RPO/RTO de "decenas de minutos" multi-región sea más costoso de lo que el negocio realmente necesita.

Elige una sola dirección:

## Aclaración 1 — ¿Qué estrategia de DR fijamos?

A) **Una región + multi-AZ, Backup & Restore (RPO/RTO en horas).** Coherente con el lote nocturno y la ventana de 72 h. Menor costo. (Equivale a R1=A + R2=A.)

B) **Multi-región Pilot Light (RPO/RTO decenas de minutos).** Mantiene datos replicados en una segunda región; mayor costo y complejidad. (Equivale a R1=B + R2=B activo-pasivo.)

C) **Una región + multi-AZ con Pilot Light "intra-región"**: réplicas en reposo en otras zonas de la misma región (no sobrevive a caída de región completa, pero acelera la recuperación dentro de la región).

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. Para un batch nocturno con holgura de 72 h, Backup & Restore multi-AZ cumple el objetivo de negocio al menor costo. Si más adelante el sistema pasa a near-real-time o se vuelve crítico 24/7, se puede escalar a Pilot Light multi-región.
