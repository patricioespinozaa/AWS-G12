"""Capa HTTP local del copiloto de lista de espera.

ADVERTENCIA: solo para uso local con datos sinteticos; sin autenticacion.

Este paquete solo compone funciones existentes del backend (datos, reglas, calidad,
copiloto, auditoria). No agrega reglas, puntajes ni logica clinica.

La guardia de entorno se ejecuta antes de cualquier import del backend: en modo
simulado (por defecto) se desactiva la lectura de .env y se fija un modelo ficticio,
de modo que importar ``config`` no lea credenciales.
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

if os.getenv("COPILOTO_INFERENCIA_REAL") != "1":
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"          # no leer .env en modo simulado
    os.environ.setdefault("ANTHROPIC_MODEL", "simulado-local")

# Los módulos del backend viven en la raíz del repositorio (estructura plana).
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
