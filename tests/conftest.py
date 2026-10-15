import os
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Base temporal: los tests nunca tocan data/processed/
_TMP = tempfile.mkdtemp(prefix="hlf_tests_")
os.environ["HLF_DB_PATH"] = str(Path(_TMP) / "test.sqlite")
os.environ.pop("LLM_PROVEEDOR", None)

from priorizacion import config as config_app  # noqa: E402

# El dataset del HLF no se versiona (CLAUDE.md): en CI no existe. Las pruebas que lo necesitan llevan el
# marcador `datos` y se saltan; las demás (esquemas, CLI, Athena simulado, PostgreSQL) corren igual.
DATOS_DISPONIBLES = (config_app.DATA_DIR / "lista_espera.csv").exists()


def pytest_collection_modifyitems(config, items):
    if DATOS_DISPONIBLES:
        return
    salto = pytest.mark.skip(reason=f"Dataset no disponible en {config_app.DATA_DIR} (no se versiona)")
    for item in items:
        if "datos" in item.keywords:
            item.add_marker(salto)


@pytest.fixture(scope="session")
def repo():
    from priorizacion.datos import Repositorio
    return Repositorio.desde_csv()
