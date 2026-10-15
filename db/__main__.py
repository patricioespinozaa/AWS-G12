"""Línea de comandos de la base de datos.

    python -m db probar                 # prueba la conexión
    python -m db esquema                # crea el esquema raw (idempotente)
    python -m db cargar [--reemplazar]  # carga los CSV en una transacción
    python -m db verificar              # conteos, huérfanos y propiedades conocidas
    python -m db restaurar              # esquema + carga (reemplazando) + verificación: todo de una vez
    python -m db permisos               # rol de solo lectura hlf_lectura_raw
    python -m db borrar --confirmar     # elimina el esquema raw

La conexión se toma de HLF_DATABASE_URL, HLF_DB_SECRET_ID + HLF_DB_HOST o PGHOST (ver db/conexion.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from priorizacion.config import DATA_DIR

from . import carga, conexion, esquema, verificacion


def _imprimir_verificacion(chequeos) -> bool:
    ancho = max(len(c.nombre) for c in chequeos)
    for c in chequeos:
        marca = "ℹ " if c.informativo else ("✔ " if c.ok else "✘ ")
        print(f"  {marca}{c.nombre:<{ancho}}  {c.detalle}")
    fallas = [c for c in chequeos if not c.ok and not c.informativo]
    print(f"\n{'Verificación OK' if not fallas else f'{len(fallas)} chequeo(s) fallaron'}")
    return not fallas


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m db", description="Base PostgreSQL del proyecto (esquema raw)")
    p.add_argument("--url", help="URL de conexión (por defecto HLF_DATABASE_URL u otras variables)")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("probar", help="Prueba la conexión")
    sub.add_parser("esquema", help="Crea el esquema raw si no existe")
    c = sub.add_parser("cargar", help="Carga los CSV al esquema raw")
    c.add_argument("--reemplazar", action="store_true", help="Vacía las tablas antes de cargar")
    c.add_argument("--datos", type=Path, default=DATA_DIR, help=f"Carpeta de los CSV (por defecto {DATA_DIR})")
    sub.add_parser("verificar", help="Verifica conteos e integridad")
    r = sub.add_parser("restaurar", help="Esquema + carga reemplazando + verificación")
    r.add_argument("--datos", type=Path, default=DATA_DIR)
    sub.add_parser("permisos", help="Crea el rol de solo lectura hlf_lectura_raw (requiere CREATEROLE)")
    b = sub.add_parser("borrar", help="Elimina el esquema raw")
    b.add_argument("--confirmar", action="store_true", help="Necesario para borrar")
    args = p.parse_args(argv)

    try:
        print(f"Conectando a {conexion.describir(args.url)}")
        with conexion.conectar(args.url) as conn:
            if args.comando == "probar":
                version = conn.execute("SELECT version()").fetchone()[0]
                print(f"OK · {version.split(',')[0]} · base {conn.info.dbname} · usuario {conn.info.user}")
            elif args.comando == "esquema":
                with conn.transaction():
                    print("Aplicados:", ", ".join(esquema.aplicar(conn, "raw")))
            elif args.comando in ("cargar", "restaurar"):
                reemplazar = args.comando == "restaurar" or args.reemplazar
                res = carga.cargar(conn, args.datos, reemplazar=reemplazar)
                print(f"Carga completa en {res['segundos']} s: {sum(res['filas'].values()):,} filas")
                if args.comando == "restaurar":
                    print("\nVerificación:")
                    return 0 if _imprimir_verificacion(verificacion.verificar(conn)) else 1
            elif args.comando == "verificar":
                return 0 if _imprimir_verificacion(verificacion.verificar(conn)) else 1
            elif args.comando == "permisos":
                with conn.transaction():
                    print("Aplicados:", ", ".join(esquema.aplicar_permisos(conn, "raw")))
            elif args.comando == "borrar":
                if not args.confirmar:
                    print("Esto elimina el esquema raw completo. Repite con --confirmar.")
                    return 2
                carga.borrar(conn)
                print("Esquema raw eliminado.")
        return 0
    except (conexion.ErrorConfiguracion, carga.ErrorCarga) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — errores de red o de PostgreSQL, con mensaje legible
        print(f"Error ({type(e).__name__}): {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
