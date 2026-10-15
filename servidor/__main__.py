"""Arranque local: python -m servidor (siempre en 127.0.0.1).

ADVERTENCIA: solo para uso local con datos sinteticos; sin autenticacion.
"""
import logging
import sys

from servidor.configuracion import ADVERTENCIA, HOST, ConfigServidor


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        config = ConfigServidor.desde_entorno()
    except ValueError as e:
        logging.getLogger("servidor").critical(str(e))
        sys.exit(2)

    print(f"ADVERTENCIA: {ADVERTENCIA}")
    print("Modo de inferencia:", "REAL (requiere confirmación por solicitud)"
          if config.inferencia_real else "SIMULADA (sin llamadas a APIs externas)")

    import uvicorn
    from servidor.app import crear_app

    uvicorn.run(crear_app(config=config), host=HOST, port=config.puerto, log_level="info")


if __name__ == "__main__":
    main()
