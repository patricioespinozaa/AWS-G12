#!/bin/sh
# Arranque del contenedor del backend.
#  - La API y la consolidación nocturna (F0006) con RDS configurada leen raw de la base: no descargan CSV.
#  - En otro caso (API sin RDS, o un comando puntual como `python -m db restaurar` en una tarea ECS):
#    si hay bucket (HLF_S3_BUCKET) y faltan los CSV, los descarga de S3 y verifica su sha256 contra el
#    manifiesto publicado con `python -m db athena publicar`. Sin datos no arranca: falla con un mensaje claro.
#  - Después ejecuta el comando (por defecto, uvicorn).
set -eu

con_rds() { [ -n "${HLF_DATABASE_URL:-}${HLF_DB_SECRET_ID:-}" ]; }
lee_la_base() { case "$*" in *uvicorn*|*servicios.nocturno*) return 0 ;; *) return 1 ;; esac; }

if con_rds && lee_la_base "$@"; then
    echo "Con RDS: los datos se leen de la base (no se descargan CSV)"
    exec "$@"
fi

if [ ! -f "${HLF_DATA_DIR}/lista_espera.csv" ] && [ -n "${HLF_S3_BUCKET:-}" ]; then
    echo "Descargando el dataset desde s3://${HLF_S3_BUCKET}/${HLF_S3_PREFIJO:-hlf}/csv/"
    python -m db athena descargar --destino "${HLF_DATA_DIR}"
fi

if [ ! -f "${HLF_DATA_DIR}/lista_espera.csv" ]; then
    echo "No hay datos en ${HLF_DATA_DIR}. Define HLF_S3_BUCKET (AWS) o monta la carpeta del dataset (local)." >&2
    exit 1
fi

exec "$@"
