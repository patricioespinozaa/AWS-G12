"""Línea de comandos de la base de datos.

RDS PostgreSQL (base operativa):
    python -m db probar                          # prueba la conexión
    python -m db esquema [--esquema E]           # crea raw, priorizacion, canal, consulta o todos (por defecto)
    python -m db cargar [--reemplazar]           # carga completa; --reemplazar RECONSTRUYE (borra lo que no venga)
    python -m db cargar --incremental --periodo DESDE:HASTA --datos DIR [--confirmar]
                                                 # suma la exportación de un periodo (nunca borra), versionada
    python -m db verificar                       # raw: conteos, huérfanos, propiedades. Resto: estructura y protecciones
    python -m db restaurar                       # todos los esquemas + reconstrucción desde la historia completa
    python -m db permisos [--esquema E]          # roles de la app, el asistente y las Lambdas
    python -m db borrar --esquema E --confirmar  # elimina un esquema (o todos); nunca deja FKs huérfanas
    python -m db reloj [--demo FECHA | --avanzar [N] | --real]   # fecha de corte (reloj de la demo)

S3 + Athena (capa de consulta y análisis):
    python -m db athena publicar                 # raw a S3 (CSV + Parquet), tablas en Athena y verificación
    python -m db athena descargar [--destino DIR]    # baja los CSV publicados y verifica su sha256 (contenedor)
    python -m db athena exportar [--desde --hasta]   # historial nocturno de RDS a S3, una partición por fecha
    python -m db athena verificar                # conteos y huérfanos en Athena contra el manifiesto
    python -m db athena consultar "SELECT …" [-p VALOR …]   # SQL de solo lectura, parametrizado

E es raw, priorizacion, canal, consulta o todos. Modelo: docs/feature/F0001, F0002 y F0003.
RDS: HLF_DATABASE_URL, HLF_DB_SECRET_ID + HLF_DB_HOST o PGHOST (db/conexion.py).
S3/Athena: HLF_S3_BUCKET, HLF_S3_PREFIJO, HLF_ATHENA_WORKGROUP, HLF_ATHENA_DB, AWS_REGION (db/athena.py).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from priorizacion.config import DATA_DIR

from . import carga, conexion, esquema, verificacion

OPCIONES = [*esquema.ESQUEMAS, "todos"]


def _imprimir_verificacion(chequeos) -> bool:
    ancho = max(len(c.nombre) for c in chequeos)
    for c in chequeos:
        marca = "ℹ " if c.informativo else ("✔ " if c.ok else "✘ ")
        print(f"  {marca}{c.nombre:<{ancho}}  {c.detalle}")
    fallas = [c for c in chequeos if not c.ok and not c.informativo]
    print(f"\n{'Verificación OK' if not fallas else f'{len(fallas)} chequeo(s) fallaron'}")
    return not fallas


def _verificar_todo(conn) -> bool:
    return _imprimir_verificacion(verificacion.verificar(conn) + verificacion.verificar_app(conn))


def _aplicar(conn, opcion: str, funcion) -> None:
    with conn.transaction():
        for nombre in esquema.resolver(opcion):
            print(f"  {nombre}: {', '.join(funcion(conn, nombre))}")


def _imprimir_tabla(res) -> None:
    if not res.columnas:
        print("(sin filas)")
        return
    texto = [[("" if v is None else str(v)) for v in f] for f in res.filas]
    anchos = [max([len(c)] + [len(f[i]) for f in texto]) for i, c in enumerate(res.columnas)]
    print("  ".join(c.ljust(a) for c, a in zip(res.columnas, anchos)))
    print("  ".join("─" * a for a in anchos))
    for f in texto:
        print("  ".join(v.ljust(a) for v, a in zip(f, anchos)))
    print(f"\n{len(res.filas)} fila(s) · {res.bytes_escaneados / 1e6:.2f} MB escaneados · {res.milisegundos} ms · "
          f"{res.id_consulta}")


def _reloj(conn, args) -> None:
    with conn.transaction():
        if args.demo:
            conn.execute("UPDATE priorizacion.reloj SET modo = 'demo', fecha_demo = %s, dias_por_tick = %s, "
                         "actualizado_en = now(), actualizado_por = 'sistema' WHERE id = 1",
                         (date.fromisoformat(args.demo), args.dias_por_tick))
        elif args.avanzar is not None:
            if conn.execute("SELECT priorizacion.avanzar_reloj(%s)", (args.avanzar or None,)).fetchone()[0] is None:
                raise carga.ErrorCarga("El reloj está en modo real: fija una fecha con --demo AAAA-MM-DD")
        elif args.real:
            conn.execute("UPDATE priorizacion.reloj SET modo = 'real', actualizado_en = now(), "
                         "actualizado_por = 'sistema' WHERE id = 1")
        modo, fecha, tick = conn.execute("SELECT modo, priorizacion.fecha_corte(), dias_por_tick "
                                         "FROM priorizacion.reloj").fetchone()
    print(f"Reloj en modo {modo} · fecha de corte {fecha}" + (f" · {tick} día(s) por tick" if modo == "demo" else ""))


def _athena(args) -> int:
    from . import athena
    cfg = athena.Config.desde_entorno()
    if args.accion == "publicar":
        print(f"Publicando raw en s3://{cfg.bucket}/{cfg.prefijo}/ · workgroup {cfg.workgroup}")
        return 0 if _imprimir_verificacion(athena.publicar(cfg, args.datos)) else 1
    s3, cliente = athena.clientes(cfg)
    if args.accion == "descargar":
        print(f"Descargando CSV de s3://{cfg.bucket}/{cfg.clave('csv')}/ a {args.destino}")
        athena.descargar_csv(s3, cfg, args.destino)
        return 0
    if args.accion == "exportar":
        print(f"Conectando a {conexion.describir(args.url)}")
        with conexion.conectar(args.url) as conn:
            desde = date.fromisoformat(args.desde) if args.desde else date(2000, 1, 1)
            hasta = date.fromisoformat(args.hasta) if args.hasta else \
                conn.execute("SELECT priorizacion.fecha_corte()").fetchone()[0]
            print(f"Exportando historial a s3://{cfg.bucket}/{cfg.clave('historial')}/")
            athena.exportar_historial(conn, s3, cfg, desde, hasta)
        return 0
    motor = athena.Athena(cfg, cliente)
    if args.accion == "verificar":
        return 0 if _imprimir_verificacion(athena.verificar(motor, athena.leer_manifiesto(s3, cfg))) else 1
    if args.accion == "consultar":
        if not athena.es_solo_lectura(args.sql):
            print("Solo se permiten consultas de lectura (SELECT, WITH, SHOW, DESCRIBE, EXPLAIN).", file=sys.stderr)
            return 2
        _imprimir_tabla(motor.ejecutar(args.sql, args.parametro or None))
    return 0


def _cargar_incremental(conn, args) -> int:
    desde = hasta = None
    if args.periodo:
        try:
            a, b = args.periodo.split(":")
            desde, hasta = (date.fromisoformat(a) if a else None), (date.fromisoformat(b) if b else None)
        except ValueError:
            print("--periodo debe ser AAAA-MM-DD:AAAA-MM-DD", file=sys.stderr)
            return 2
    previa = carga.vista_previa(conn, args.datos, (desde, hasta), cargado_por=os.environ.get("HLF_USUARIA", "sistema"))
    print(f"Vista previa de la carga {previa['id_carga']} ({previa['estado']}):")
    for tabla, r in previa["resumen"].items():
        print(f"  {tabla:<17} {r['filas']:>6} filas: +{r['nuevas']} nuevas, ~{r['modificadas']} modificadas, "
              f"{r['sin_cambio']} sin cambio")
    print(f"  Pacientes afectados: {len(previa['pacientes_afectados'])} (nuevos: {len(previa['pacientes_nuevos'])})")
    for a in previa["advertencias"]:
        print(f"  ⚠ {a['mensaje']}: {a['cantidad']} (ej. {'; '.join(a['ejemplos'][:3])})")
    for e in previa["errores"]:
        print(f"  ✘ {e['archivo']}{f' línea ' + str(e['linea']) if e['linea'] else ''}: {e['mensaje']}")
    if previa["estado"] != "lista":
        return 1
    if not args.confirmar:
        print("\nNada se escribió. Repite con --confirmar para aplicarla.")
        return 0
    res = carga.aplicar_incremental(conn, previa["id_carga"], args.datos)
    print(f"\nAplicada como versión {res['version']}.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m db",
                                description="Base del proyecto: RDS PostgreSQL (operativa) y S3 + Athena (consulta)")
    p.add_argument("--url", help="URL de conexión a RDS (por defecto HLF_DATABASE_URL u otras variables)")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("probar", help="Prueba la conexión")
    e = sub.add_parser("esquema", help="Crea los esquemas que falten (idempotente)")
    e.add_argument("--esquema", choices=OPCIONES, default="todos")
    c = sub.add_parser("cargar", help="Carga los CSV al esquema raw")
    modo = c.add_mutually_exclusive_group()
    modo.add_argument("--reemplazar", action="store_true",
                      help="Reconstruye raw desde la historia COMPLETA: borra lo que no venga en los CSV")
    modo.add_argument("--incremental", action="store_true",
                      help="Suma la exportación de un periodo nuevo sin borrar nada (F0005)")
    c.add_argument("--periodo", metavar="DESDE:HASTA", help="Con --incremental: periodo de la exportación")
    c.add_argument("--confirmar", action="store_true", help="Con --incremental: aplica después de la vista previa")
    c.add_argument("--datos", type=Path, default=DATA_DIR, help=f"Carpeta de los CSV (por defecto {DATA_DIR})")
    sub.add_parser("verificar", help="Verifica raw y la estructura de los demás esquemas")
    r = sub.add_parser("restaurar", help="Todos los esquemas + carga sincronizada + verificación")
    r.add_argument("--datos", type=Path, default=DATA_DIR)
    pe = sub.add_parser("permisos", help="Crea los roles de la base (requiere CREATEROLE)")
    pe.add_argument("--esquema", choices=OPCIONES, default="todos")
    b = sub.add_parser("borrar", help="Elimina un esquema o todos")
    b.add_argument("--esquema", choices=OPCIONES, required=True)
    b.add_argument("--confirmar", action="store_true", help="Necesario para borrar")
    rl = sub.add_parser("reloj", help="Muestra o cambia la fecha de corte (reloj de la demo)")
    accion = rl.add_mutually_exclusive_group()
    accion.add_argument("--demo", metavar="AAAA-MM-DD", help="Pasa a modo demo en esa fecha")
    accion.add_argument("--avanzar", type=int, nargs="?", const=0, metavar="DIAS",
                        help="Avanza el reloj (por defecto, los días por tick)")
    accion.add_argument("--real", action="store_true", help="Vuelve a la fecha real")
    rl.add_argument("--dias-por-tick", type=int, default=1, help="Con --demo: días que avanza cada tick")
    at = sub.add_parser("athena", help="Capa de consulta en S3 + Athena")
    at_sub = at.add_subparsers(dest="accion", required=True)
    ap = at_sub.add_parser("publicar", help="Sube raw a S3, crea las tablas en Athena y verifica")
    ap.add_argument("--datos", type=Path, default=DATA_DIR)
    ad = at_sub.add_parser("descargar", help="Baja los CSV publicados y los verifica contra el manifiesto")
    ad.add_argument("--destino", type=Path, default=DATA_DIR)
    ae = at_sub.add_parser("exportar", help="Exporta el historial nocturno de RDS a S3")
    ae.add_argument("--desde", metavar="AAAA-MM-DD")
    ae.add_argument("--hasta", metavar="AAAA-MM-DD", help="Por defecto, la fecha de corte del reloj")
    at_sub.add_parser("verificar", help="Verifica las tablas de Athena contra el manifiesto")
    aq = at_sub.add_parser("consultar", help="Ejecuta SQL de solo lectura en Athena")
    aq.add_argument("sql")
    aq.add_argument("-p", "--parametro", action="append", help="Valor para cada ? de la consulta, en orden")
    args = p.parse_args(argv)

    try:
        if args.comando == "athena":
            return _athena(args)
        print(f"Conectando a {conexion.describir(args.url)}")
        with conexion.conectar(args.url) as conn:
            if args.comando == "probar":
                version = conn.execute("SELECT version()").fetchone()[0]
                print(f"OK · {version.split(',')[0]} · base {conn.info.dbname} · usuario {conn.info.user}")
            elif args.comando == "esquema":
                print("Esquemas aplicados:")
                _aplicar(conn, args.esquema, esquema.aplicar)
            elif args.comando == "cargar" and args.incremental:
                return _cargar_incremental(conn, args)
            elif args.comando in ("cargar", "restaurar"):
                if args.comando == "restaurar" or args.reemplazar:
                    print("Atención: reconstruye raw desde la historia COMPLETA y borra lo que no venga en los CSV.\n"
                          "Para sumar la exportación de un periodo nuevo usa: python -m db cargar --incremental\n")
                if args.comando == "restaurar":
                    print("Esquemas aplicados:")
                    _aplicar(conn, "todos", esquema.aplicar)
                reemplazar = args.comando == "restaurar" or args.reemplazar
                res = carga.cargar(conn, args.datos, reemplazar=reemplazar)
                print(f"Carga completa en {res['segundos']} s: {sum(res['filas'].values()):,} filas")
                if args.comando == "restaurar":
                    print("\nVerificación:")
                    return 0 if _verificar_todo(conn) else 1
            elif args.comando == "verificar":
                return 0 if _verificar_todo(conn) else 1
            elif args.comando == "permisos":
                print("Permisos aplicados:")
                _aplicar(conn, args.esquema, esquema.aplicar_permisos)
            elif args.comando == "reloj":
                _reloj(conn, args)
            elif args.comando == "borrar":
                if not args.confirmar:
                    que = "todos los esquemas" if args.esquema == "todos" else f"el esquema {args.esquema}"
                    print(f"Esto elimina {que} con sus datos. Repite con --confirmar.")
                    return 2
                borrados = carga.borrar(conn, args.esquema)
                print(f"Eliminados: {', '.join(borrados)}" if borrados else "No había nada que borrar.")
        return 0
    except (conexion.ErrorConfiguracion, carga.ErrorCarga) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — errores de red, de AWS o de PostgreSQL, con mensaje legible
        print(f"Error ({type(e).__name__}): {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
