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

from priorizacion import config  # noqa: E402

if not (config.DATA_DIR / "lista_espera.csv").exists():
    pytest.skip(f"Dataset no disponible en {config.DATA_DIR}", allow_module_level=True)


@pytest.fixture(scope="session")
def repo():
    from priorizacion.datos import Repositorio
    return Repositorio.desde_csv()
