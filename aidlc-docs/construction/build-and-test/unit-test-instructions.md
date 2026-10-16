# Pruebas unitarias y de propiedades

```powershell
. .\scripts\entorno-demo.ps1
uv run ruff check
uv run mypy src              # estricto
uv run pytest                # por defecto excluye la prueba con Bedrock real (-m "not bedrock")
```

Resultado esperado (verificado el 2026-10-16): ruff "All checks passed!", mypy "no issues found in 45 source files", **pytest 286 passed, 1 deselected**.

| Carpeta | Contenido |
|---|---|
| `tests/ejemplos/` | Casos concretos: los 6 pacientes de `docs/casos-ejemplo.md`, reglas del copiloto, bloqueo de ejecución única, bandeja. Los que leen el dataset real se saltan con un mensaje si no está |
| `tests/propiedades/` | Hypothesis (PBT-02 a PBT-06): round-trip, invariantes (equidad, fecha de corte, pisos y banderas), idempotencia, oráculos, máquinas de estado (bandeja, corte de circuito) |
| `tests/estrategias/` | Generadores de dominio compartidos (PBT-07) |
| `tests/interfaz/` | `streamlit.testing.v1.AppTest` sobre `app/bandeja.py` con carpetas temporales |
| `tests/integracion/` | `test_bedrock_real.py`, marcada `bedrock` (ver integración) |

**Reproducibilidad (PBT-08):** el perfil `ci` de Hypothesis usa `derandomize=True`; ante un fallo se imprime el ejemplo mínimo y el blob de reproducción. Un fallo intermitente se investiga, no se reintenta. Cada contraejemplo encontrado se agrega como prueba de ejemplo.

Un archivo o subconjunto: `uv run pytest tests/ejemplos/test_casos_referencia.py -q`.
