# Pruebas de seguridad

```powershell
uv run pip-audit                         # dependencias con vulnerabilidades conocidas
```

Esperado: "No known vulnerabilities found" (solo se omite el propio paquete local, que no está en PyPI). Verificado el 2026-10-16.

| Control | Cómo se verifica |
|---|---|
| SECURITY-10 dependencias fijadas | `uv sync --locked` falla si `uv.lock` no coincide con `pyproject.toml` |
| SECURITY-03 logs sin datos clínicos | Pruebas de ejemplo comprueban que stderr del lote, del copiloto y de la bandeja no contiene valores clínicos, texto del modelo ni el motivo del médico |
| SECURITY-05 validación de entradas | Pruebas de cada error de fecha (C2.3), del contrato (cuarentena) y del formulario de decisión |
| Equidad (C6.5) | 40+ frases de ejemplo y propiedades P16a/b/c con frases adversarias generadas |
| Inyección de instrucciones | Datos en bloque `<datos_clinicos>`; herramientas sin parámetros de identidad; validación de salida |
| Exposición de red | La bandeja escucha solo en `127.0.0.1` (verificado con `Get-NetTCPConnection`) |
| Credenciales | Ninguna en el repositorio (revisión previa al commit `cddbde1`); solo la cadena estándar de AWS |

Fuera del MVP local (exigidos al desplegar, ver sección 13 de `docs/contexto-tecnico.md`): autenticación (Cognito, MFA), cabeceras HTTP, WAF, red privada, Bedrock Guardrails.
