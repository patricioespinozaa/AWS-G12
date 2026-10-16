"""Consolidación nocturna (F0006). En AWS la lanza EventBridge Scheduler cada noche como tarea ECS.

    python -m servicios.nocturno                      # buzón configurado (HLF_BUZON o S3), confirma sola
    python -m servicios.nocturno --buzon data/buzon   # buzón en una carpeta local
    python -m servicios.nocturno --sin-confirmar      # deja las entregas en `lista` para la vista Cargas

Requiere la base (HLF_DATABASE_URL o HLF_DB_SECRET_ID). Código de salida 1 si una entrega tuvo errores o la
consolidación falló: así la ejecución queda marcada como fallida en ECS y en la alarma.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from priorizacion import config

from . import buzon as B
from .proceso import correr


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m servicios.nocturno", description=__doc__.split("\n")[0])
    p.add_argument("--buzon", help="Carpeta local con una subcarpeta por entrega (en vez de HLF_BUZON o S3)")
    p.add_argument("--sin-confirmar", action="store_true", help="Solo vista previa: no suma nada a raw")
    p.add_argument("--publicar-athena", action="store_true", help="Publica en Athena al terminar (o HLF_ATHENA_PUBLICAR=1)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if not config.usa_rds():
        print("La consolidación nocturna requiere la base (HLF_DATABASE_URL o HLF_DB_SECRET_ID).", file=sys.stderr)
        return 2
    buzon = B.BuzonLocal(args.buzon) if args.buzon else B.desde_config()
    publicar = None
    if args.publicar_athena or config.ATHENA_PUBLICAR:
        from db import athena
        publicar = athena.publicador_consolidacion()
    try:
        resultado = correr(buzon, autoconfirmar=False if args.sin_confirmar else None, publicar=publicar)
    except Exception:  # noqa: BLE001 — la corrida ya quedó `fallida` en la bitácora con el error
        logging.getLogger("hlf.nocturno").exception("La consolidación nocturna falló")
        return 1
    print(json.dumps(resultado, ensure_ascii=False, default=str, indent=2))
    return 1 if resultado.get("con_errores") else 0


if __name__ == "__main__":
    sys.exit(main())
