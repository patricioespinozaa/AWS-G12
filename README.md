# AWS-G12 · Priorización dinámica de la lista de espera (HLF)

Prototipo para el desafío "Evaluación dinámica del riesgo y priorización asistencial" del Hospital Clínico Dra. Eloísa Díaz La Florida, en el Hackatón de IA Generativa AWS Breaking Barriers Chile 2026.

> La herramienta propone y explica; el equipo clínico decide.

## Acceso a la demo

| | |
|---|---|
| **URL** | https://d27qviveikaea2.cloudfront.net |
| **Usuario** | `admin` |
| **Contraseña** | `HlfDemo2026Admin` |

Cuenta compartida de la Administradora, solo para la demo del hackatón con **datos sintéticos**. Cognito exige al menos 12 caracteres con mayúscula, minúscula y número, por eso no puede ser `admin`/`admin`. Todo lo que se haga con esta cuenta queda registrado a nombre de `admin`.

Crear o restablecer la cuenta (también sirve si alguien cambió la contraseña):

```bash
pool=$(aws cloudformation describe-stacks --stack-name HlfDemo-Identidad \
    --query "Stacks[0].Outputs[?OutputKey=='SalidaUserPool'].OutputValue" --output text)
aws cognito-idp admin-create-user --user-pool-id "$pool" --username admin --message-action SUPPRESS \
    --user-attributes Name=name,Value="Administradora demo" 2>/dev/null || true
aws cognito-idp admin-set-user-password --user-pool-id "$pool" --username admin \
    --password HlfDemo2026Admin --permanent
aws cognito-idp admin-add-user-to-group --user-pool-id "$pool" --username admin --group-name administracion
```

**Después del hackatón o antes de usar datos reales**, desactívala: `aws cognito-idp admin-disable-user --user-pool-id "$pool" --username admin`. Con datos reales cada persona tiene su propia cuenta (`infra/scripts/crear_cuenta.sh`), con MFA.

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
