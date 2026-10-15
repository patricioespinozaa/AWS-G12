#!/bin/sh
# Arranque del contenedor del backend.
#  1. Si hay bucket configurado (HLF_S3_BUCKET) y faltan los CSV, los descarga de S3 y verifica su sha256
#     contra el manifiesto publicado con `python -m db athena publicar`.
#  2. Sin datos no arranca: falla con un mensaje claro en vez de levantar una API vacía.
#  3. Ejecuta el comando (por defecto, uvicorn).
set -eu

if [ ! -f "${HLF_DATA_DIR}/lista_espera.csv" ] && [ -n "${HLF_S3_BUCKET:-}" ]; then
    echo "Descargando el dataset desde s3://${HLF_S3_BUCKET}/${HLF_S3_PREFIJO:-hlf}/csv/"
    python -m db athena descargar --destino "${HLF_DATA_DIR}"
fi

if [ ! -f "${HLF_DATA_DIR}/lista_espera.csv" ]; then
    echo "No hay datos en ${HLF_DATA_DIR}. Define HLF_S3_BUCKET (AWS) o monta la carpeta del dataset (local)." >&2
    exit 1
fi

exec "$@"
