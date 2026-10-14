# AWS-G12 · Priorización dinámica de la lista de espera (HLF)

Prototipo para el desafío "Evaluación dinámica del riesgo y priorización asistencial" del Hospital Clínico Dra. Eloísa Díaz La Florida, en el Hackatón de IA Generativa AWS Breaking Barriers Chile 2026.

> La herramienta propone y explica; el equipo clínico decide.

## Inicio rápido

```bash
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
uvicorn api.main:app --port 8000      # http://127.0.0.1:8000
python -m pytest                      # tests
```

Requiere el dataset del HLF en `data/dataset_hlf_ambulatorio/dataset_hlf_ambulatorio/` (no se versiona).

## Documentación

- `docs/mvp.md`: el MVP (vistas, backend, puntaje y servicios AWS)
- `docs/contexto.md`, `docs/datos.md`, `docs/eda.md`: el problema, los datos y el análisis exploratorio
- `docs/arquitectura.md`, `docs/enfoque.md`, `docs/propuestas-solucion.md`: diseño de la solución
- `docs/kpis.md`, `docs/casos-ejemplo.md`, `docs/glosario.md`
