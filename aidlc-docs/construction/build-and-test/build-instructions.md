# Instrucciones de construcción

## Requisitos

| | |
|---|---|
| Sistema | Windows 10/11 con PowerShell (probado); Linux/macOS deberían funcionar, no probado |
| Python | 3.12 (probado con 3.12.7) |
| Gestor | [uv](https://docs.astral.sh/uv/) 0.12 o superior (probado con 0.12.0) |
| Datos | Dataset sintético del HLF en `data/dataset_hlf_ambulatorio/` (no se versiona) |
| AWS (solo copiloto) | Credenciales en la cadena estándar de AWS con acceso a Bedrock en `us-east-1` y a un modelo permitido (`us.anthropic.claude-sonnet-5` por defecto) |

Variables de entorno opcionales:

| Variable | Uso | Por defecto |
|---|---|---|
| `HLF_BEDROCK_MODEL_ID` | Modelo del copiloto | `us.anthropic.claude-sonnet-5` |
| `HLF_BEDROCK_REGION` | Región de Bedrock | `us-east-1` |
| `HLF_COPILOTO_CONCURRENCIA` | Llamadas simultáneas (1–8) | 4 |
| `HLF_SALIDAS` / `HLF_DATOS` | Carpetas de la bandeja | `salidas/` y `data/dataset_hlf_ambulatorio/` |
| `HYPOTHESIS_PROFILE` | Perfil de pruebas de propiedades | `ci` |

## Pasos

```powershell
. .\scripts\entorno-demo.ps1        # consola en UTF-8 (una vez por terminal)
uv sync --locked                    # instala las versiones exactas de uv.lock en .venv
uv build                            # opcional: genera el paquete (wheel y sdist) en dist/
```

Resultado esperado (verificado el 2026-10-16): `uv sync --locked` → "Checked 90 packages"; `uv build` → `hlf_priorizacion-0.1.0-py3-none-any.whl` (109 KB) y `hlf_priorizacion-0.1.0.tar.gz` (79 KB).

Comandos que quedan disponibles: `hlf-lote`, `hlf-copiloto` y `streamlit` (para `app/bandeja.py`).

## Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| Caracteres raros (`路`, `p谩gina`) | Consola en página de códigos 936 | Ejecutar `. .\scripts\entorno-demo.ps1` |
| `uv sync --locked` falla | `pyproject.toml` cambió sin actualizar `uv.lock` | `uv lock` y revisar el diff antes de confirmar |
| `hlf-copiloto` termina con código 4 | Modelo no permitido o credenciales sin acceso | Usar el modelo de respaldo `us.anthropic.claude-haiku-4-5-20251001-v1:0` o renovar credenciales |
| `ExpiredToken` / `UnrecognizedClientException` | Credenciales temporales del workshop vencidas | Renovarlas en el portal del evento; `aws sts get-caller-identity` |
