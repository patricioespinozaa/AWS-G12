"""Base de datos PostgreSQL (AWS RDS) del proyecto: esquemas, carga de datos crudos y verificación.

Esquemas: raw (datos del HLF, docs/feature/F0001-subida-datos-aws.md), priorizacion y canal
(docs/feature/F0002-modelo-datos-canales.md).

Uso rápido:
    python -m db restaurar      # crea los tres esquemas, carga o sincroniza los CSV en raw y verifica
"""
