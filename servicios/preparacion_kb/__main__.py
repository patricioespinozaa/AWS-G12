"""Preparación de la Knowledge Base del equipo clínico (F0009).

    python -m servicios.preparacion_kb                  # tarea ECS: genera, sube, registra y sincroniza
    python -m servicios.preparacion_kb --local DIR      # solo escribe los documentos en DIR (sin AWS; con los CSV)
    python -m servicios.preparacion_kb --sin-esperar    # lanza la ingesta y no espera su fin
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m servicios.preparacion_kb", description=__doc__.split("\n")[0])
    p.add_argument("--local", type=Path, help="Carpeta donde escribir los documentos (no usa AWS)")
    p.add_argument("--corte", help="Fecha de corte para --local (por defecto la última fecha con datos)")
    p.add_argument("--sin-esperar", action="store_true")
    p.add_argument("--faq", action="store_true", help="Sincroniza la KB del paciente (preguntas frecuentes, F0010)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.local:
        from priorizacion.datos import Repositorio
        from . import documentos as D
        repo = Repositorio.crear()
        corte = date.fromisoformat(args.corte) if args.corte else repo.fecha_max_datos
        docs = D.generar(repo, corte)
        for d in docs:
            destino = args.local / d.ruta
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(d.contenido, encoding="utf-8")
            Path(f"{destino}.metadata.json").write_text(d.metadata_json(), encoding="utf-8")
        print(f"{len(docs)} documentos en {args.local} (corte {corte})")
        return 0
    from priorizacion import config
    if not config.usa_rds():
        print("La preparación de la KB requiere la base (HLF_DATABASE_URL o HLF_DB_SECRET_ID).", file=sys.stderr)
        return 2
    from .proceso import ErrorPreparacion, preparar, preparar_faq
    try:
        resultado = (preparar_faq if args.faq else preparar)(esperar=not args.sin_esperar)
    except ErrorPreparacion as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(resultado, ensure_ascii=False, default=str, indent=2))
    return 0 if resultado.get("estado", "completa") == "completa" else 1


if __name__ == "__main__":
    sys.exit(main())
