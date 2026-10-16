# Imagen del backend (FastAPI + motor de priorización + módulo db). Contexto de build: la raíz del repositorio.
#   docker build -f docker/backend/Dockerfile -t hlf-backend .
#   docker run -p 8000:8000 -v "$PWD/data/dataset_hlf_ambulatorio/dataset_hlf_ambulatorio:/app/data/dataset:ro" hlf-backend
#
# Los datos del hospital NUNCA van dentro de la imagen: en AWS el contenedor los descarga de S3 al arrancar
# (docker/backend/entrypoint.sh); en local se montan como volumen.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencias primero: esta capa se reutiliza mientras requirements/base.txt no cambie
COPY requirements/base.txt requirements/base.txt
RUN pip install -r requirements/base.txt

COPY priorizacion/ priorizacion/
COPY db/ db/
COPY api/ api/
COPY servicios/ servicios/
COPY docker/backend/entrypoint.sh /usr/local/bin/entrypoint.sh

# Usuario sin privilegios; /app/data es el único directorio escribible (datos descargados y SQLite del MVP).
# El sed deja el entrypoint en LF aunque se haya editado en Windows: con CRLF el contenedor no arranca.
RUN useradd --create-home --uid 10001 hlf \
    && mkdir -p /app/data/dataset /app/data/processed \
    && chown -R hlf:hlf /app/data \
    && sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
    && chmod 0755 /usr/local/bin/entrypoint.sh
USER hlf

ENV HLF_DATA_DIR=/app/data/dataset \
    HLF_DB_PATH=/app/data/processed/priorizacion.sqlite \
    PORT=8000
EXPOSE 8000

# El primer arranque recalcula la serie nocturna completa: el healthcheck espera hasta 5 minutos
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/salud', timeout=4)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# Un solo worker: el MVP mantiene el repositorio en memoria y escribe en SQLite (ver docs/feature/F0005)
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips '*'"]
