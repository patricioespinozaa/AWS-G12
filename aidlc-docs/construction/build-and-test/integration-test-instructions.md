# Pruebas de integración

Las unidades se comunican por archivos en `salidas/`. Las integraciones se prueban de punta a punta con el dataset real.

## Escenario 1 — U1 lote → archivos

```powershell
uv run hlf-lote --fecha-corte 2026-07-19
uv run hlf-lote --fecha-corte 2026-07-20
```

Esperado: código 0; "Cobertura: 100.0 %"; "Errores: 0". Al repetir el mismo corte: "Propuestas nuevas: 0" (idempotente). Tiempo medido para 2026-10-13: 2,9 s.

## Escenario 2 — U1 → U2 copiloto (consume tokens de Bedrock)

```powershell
uv run pytest -m bedrock -s                                   # 1 análisis real de IC-HLF-00002 al 2026-08-10
uv run hlf-copiloto --fecha-corte 2026-07-20 --max-llamadas 20
```

Esperado: la prueba marcada pasa (prioridad sugerida `critica`, citas válidas, riesgo poblacional igual a la cohorte). El copiloto guarda cada análisis apenas termina; al repetir el comando, 0 llamadas nuevas. Solo puede haber una ejecución a la vez por carpeta de salidas: una segunda termina con código 2 sin llamar a Bedrock. Ctrl+C es seguro (código 130) y una nueva ejecución continúa.

## Escenario 3 — U1 + U2 → U3 bandeja

```powershell
uv run streamlit run app/bandeja.py      # http://127.0.0.1:8501
```

Recorrido: médico → corte 2026-07-19 → "¿Qué cambió?" 07-19 → 07-20 (IC-HLF-00002: baja → crítica por EV-000004) → clic en la fila abre el Detalle → análisis del copiloto → elegir y guardar una decisión → aparece en `salidas/decisiones/decisiones.jsonl` y en la auditoría. IC-HLF-00349 (07-19) muestra la advertencia de equidad antes del análisis.

Automatizado en `tests/ejemplos/test_bandeja.py` y `tests/interfaz/test_app_bandeja.py` (sobre carpetas temporales). El clic en la fila fue confirmado a mano por el usuario.

## Limpieza

Las pruebas no escriben en `salidas/`. Para rehacer todo desde cero: borrar `salidas/` (se regenera; las decisiones médicas y la auditoría se perderían, así que en una demo con decisiones reales no se borra).
