"""CLI del copiloto en modo barrido.

``hlf-copiloto (--fecha-corte F | --desde F --hasta F) [--forzar] [--max-llamadas N] [--datos RUTA]
[--salidas RUTA] [--reglas RUTA] [--fecha-extraccion F]``

Todo se valida antes de llamar a Bedrock (SECURITY-05). ``--max-llamadas`` es el presupuesto de invocaciones
reales al modelo, incluidos los reintentos (C2.5). Códigos de salida: 0 correcto; 1 hubo solicitudes
fallidas o quedaron solicitudes sin procesar por ``limite_llamadas``; 2 entrada o configuración inválida
(incluye salidas del lote faltantes y más solicitudes pendientes que presupuesto); 3 error inesperado;
4 permiso o modelo no permitido: modelo fuera de la lista local, permisos de Bedrock denegados o
credenciales inválidas (fail-closed); 130 interrumpido con Ctrl+C (C4.8): lo ya terminado queda guardado
y una nueva ejecución del mismo comando sigue con el resto.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final, NoReturn

from hlf_priorizacion.auditoria.registro import nuevo_ulid
from hlf_priorizacion.copiloto.barrido import (
    MAX_INVOCACIONES_POR_SOLICITUD,
    ConfigBarrido,
    ErrorLoteFaltante,
    ResumenBarrido,
    ejecutar_barrido,
)
from hlf_priorizacion.copiloto.cliente import ClienteBedrock, ClienteModelo, ErrorPermisos
from hlf_priorizacion.copiloto.config import ErrorConfiguracion, ErrorModeloNoPermitido, config_desde_entorno
from hlf_priorizacion.copiloto.fechas import ErrorFecha, cortes_a_procesar, parsear_fecha
from hlf_priorizacion.copiloto.prompt import ErrorPrompt, cargar_prompt
from hlf_priorizacion.copiloto.seleccion import ErrorTope
from hlf_priorizacion.ingesta.carga import ErrorCarga
from hlf_priorizacion.logs import configurar_logging, fijar_id_ejecucion
from hlf_priorizacion.motor.parametros import ErrorParametros, cargar_parametros
from hlf_priorizacion.persistencia.salidas import ErrorPersistencia
from hlf_priorizacion.repositorio.contexto import FECHA_EXTRACCION_DATASET

SALIDA_OK, SALIDA_FALLIDAS, SALIDA_ENTRADA, SALIDA_INESPERADA, SALIDA_PERMISOS = 0, 1, 2, 3, 4
SALIDA_INTERRUMPIDA: Final = 130  # convención de shell para SIGINT
MENSAJE_REANUDAR: Final = (
    "Interrumpido con Ctrl+C. Lo ya terminado quedó guardado; vuelva a ejecutar el mismo comando para seguir "
    "con el resto.\n"
)
# Si quedaron llamadas en curso tras la espera, sus hilos no deben retener el proceso al salir.
_salir_ya: Callable[[int], NoReturn] = os._exit
MAX_LLAMADAS_POR_DEFECTO: Final = 300
MAX_LLAMADAS_TOPE: Final = 10000
DATOS_POR_DEFECTO = Path("data/dataset_hlf_ambulatorio")
SALIDAS_POR_DEFECTO = Path("salidas")


class ErrorEntrada(ValueError):
    """Ruta o argumento inválido."""


def _fecha(texto: str) -> date:
    try:
        return parsear_fecha(texto)
    except ErrorFecha as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def _max_llamadas(texto: str) -> int:
    if not texto.isdigit() or not 1 <= int(texto) <= MAX_LLAMADAS_TOPE:
        raise argparse.ArgumentTypeError(f"entero entre 1 y {MAX_LLAMADAS_TOPE}")
    return int(texto)


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hlf-copiloto", description="Copiloto IA en modo barrido (U2).")
    p.add_argument("--fecha-corte", type=_fecha, default=None, help="un corte AAAA-MM-DD")
    p.add_argument("--desde", type=_fecha, default=None, help="inicio del rango AAAA-MM-DD (incluido)")
    p.add_argument("--hasta", type=_fecha, default=None, help="fin del rango AAAA-MM-DD (incluido)")
    p.add_argument("--forzar", action="store_true", help="en rango, analizar aunque la evaluación no cambie")
    p.add_argument(
        "--max-llamadas",
        type=_max_llamadas,
        default=MAX_LLAMADAS_POR_DEFECTO,
        help=(
            "presupuesto de invocaciones reales al modelo, incluidos los reintentos de validación y de "
            "servicio; al agotarse, las solicitudes restantes quedan como limite_llamadas y se retoman en la "
            f"siguiente ejecución (por defecto {MAX_LLAMADAS_POR_DEFECTO})"
        ),
    )
    p.add_argument("--datos", type=Path, default=DATOS_POR_DEFECTO, help="carpeta con perfiles.json")
    p.add_argument("--salidas", type=Path, default=SALIDAS_POR_DEFECTO, help="carpeta de salidas del lote")
    p.add_argument("--reglas", type=Path, default=None, help="archivo reglas-vX.Y.Z.yaml (por defecto el empaquetado)")
    p.add_argument(
        "--fecha-extraccion",
        type=_fecha,
        default=FECHA_EXTRACCION_DATASET,
        help="fecha de extracción del dataset (por defecto 2026-10-13)",
    )
    return p


def _rutas(args: argparse.Namespace) -> tuple[Path, Path, Path | None]:
    datos = Path(args.datos).resolve()
    if not datos.is_dir():
        raise ErrorEntrada(f"--datos no es una carpeta existente: {datos}")
    salidas = Path(args.salidas).resolve()
    if salidas.exists() and not salidas.is_dir():
        raise ErrorEntrada(f"--salidas existe y no es una carpeta: {salidas}")
    if salidas == datos or salidas.is_relative_to(datos):
        raise ErrorEntrada("--salidas no puede estar dentro de la carpeta de datos")
    reglas = Path(args.reglas).resolve() if args.reglas is not None else None
    if reglas is not None and (not reglas.is_file() or reglas.suffix not in {".yaml", ".yml"}):
        raise ErrorEntrada(f"--reglas debe ser un archivo YAML existente: {reglas}")
    return datos, salidas, reglas


def _salida_utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if callable(reconfigurar):
            reconfigurar(encoding="utf-8", errors="backslashreplace")


def main(
    argv: Sequence[str] | None = None,
    *,
    cliente: ClienteModelo | None = None,
    entorno: Mapping[str, str] | None = None,
) -> int:
    _salida_utf8()
    log = configurar_logging()
    id_ejecucion = f"copiloto-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{nuevo_ulid()[-8:]}"
    fijar_id_ejecucion(id_ejecucion)
    args = construir_parser().parse_args(argv)
    try:
        cortes = cortes_a_procesar(args.fecha_corte, args.desde, args.hasta, args.fecha_extraccion)
        datos, salidas, reglas = _rutas(args)
        config = config_desde_entorno(os.environ if entorno is None else entorno)
        params = cargar_parametros(reglas)
        prompt = cargar_prompt()
        cfg = ConfigBarrido(
            cortes=cortes,
            modo_rango=args.fecha_corte is None,
            fecha_extraccion=args.fecha_extraccion,
            datos=datos,
            salidas=salidas,
            version_reglas=params.version,
            max_llamadas=args.max_llamadas,
            forzar=bool(args.forzar),
            datos_arg=str(args.datos) if Path(args.datos) != DATOS_POR_DEFECTO else None,
            salidas_arg=str(args.salidas) if Path(args.salidas) != SALIDAS_POR_DEFECTO else None,
            reglas_arg=str(args.reglas) if args.reglas is not None else None,
        )
        log.info(
            "inicio del copiloto",
            extra={
                "campos": {
                    "desde": cortes[0].isoformat(),
                    "hasta": cortes[-1].isoformat(),
                    "version_reglas": params.version,
                    "version_prompt": prompt.version_prompt,
                    "model_id": config.model_id,
                }
            },
        )
        resumen = ejecutar_barrido(cfg, config, prompt, cliente or ClienteBedrock(config), id_ejecucion)
    except KeyboardInterrupt:  # Ctrl+C fuera de las llamadas (antes de empezar o al escribir)
        log.warning("copiloto interrumpido", extra={"campos": {"tipo_error": "KeyboardInterrupt"}})
        sys.stdout.write(MENSAJE_REANUDAR)
        return SALIDA_INTERRUMPIDA
    except ErrorLoteFaltante as e:
        log.error("faltan salidas del lote", extra={"campos": {"tipo_error": type(e).__name__}})
        sys.stdout.write(
            f"{e}\nNo se llamó a Bedrock. Genere primero las salidas del lote:\n"
            + "".join(f"  {c}\n" for c in e.comandos)
        )
        return SALIDA_ENTRADA
    except ErrorTope as e:
        log.error("tope de llamadas superado", extra={"campos": {"llamadas": e.pendientes, "n": e.maximo}})
        sys.stdout.write(
            f"Solicitudes pendientes: {e.pendientes} (peor caso {e.pendientes * MAX_INVOCACIONES_POR_SOLICITUD} "
            f"invocaciones); presupuesto {e.maximo} invocaciones (--max-llamadas): no alcanza ni para una "
            "invocación por solicitud.\nNo se llamó a Bedrock. Reduzca el rango o suba --max-llamadas.\n"
        )
        return SALIDA_ENTRADA
    except ErrorModeloNoPermitido as e:
        error = ErrorPermisos("modelo_no_permitido")
        log.error("modelo no permitido", extra={"campos": {"codigo": error.codigo}})
        sys.stdout.write(f"{e}\nNo se llamó a Bedrock. {error.sugerencia}\n")
        return SALIDA_PERMISOS
    except (ErrorFecha, ErrorEntrada, ErrorConfiguracion, ErrorParametros, ErrorPrompt, ErrorCarga) as e:
        log.error(f"entrada inválida: {e}", extra={"campos": {"tipo_error": type(e).__name__}})
        sys.stdout.write(f"Entrada inválida: {e}\nNo se llamó a Bedrock.\n")
        return SALIDA_ENTRADA
    except ErrorPersistencia as e:
        log.error(f"error de salidas: {e}", extra={"campos": {"tipo_error": type(e).__name__}})
        return SALIDA_INESPERADA
    except Exception as e:  # manejador global: sin mensajes ni trazas que puedan llevar datos
        log.error("error inesperado; el copiloto se detuvo", extra={"campos": {"tipo_error": type(e).__name__}})
        return SALIDA_INESPERADA

    _imprimir_resumen(resumen, id_ejecucion, config.model_id, prompt.version_prompt)
    log.info(
        "fin del copiloto",
        extra={
            "campos": {
                "conteos": {
                    "analizadas": resumen.analizadas,
                    "fallidas": resumen.total_fallidas,
                    "limite_llamadas": resumen.por_limite_llamadas,
                    "interrumpidas": resumen.interrumpidas,
                },
                "llamadas": resumen.llamadas_modelo,
                "tokens_entrada": resumen.tokens_entrada,
                "tokens_salida": resumen.tokens_salida,
                "segundos": resumen.segundos,
            }
        },
    )
    if resumen.interrumpido:
        log.warning("copiloto interrumpido", extra={"campos": {"conteos": {"abandonadas": resumen.abandonadas}}})
        sys.stdout.write(MENSAJE_REANUDAR)
        if resumen.abandonadas:  # hilos con una llamada aún abierta: no esperar a que terminen
            sys.stdout.flush()
            sys.stderr.flush()
            _salir_ya(SALIDA_INTERRUMPIDA)
        return SALIDA_INTERRUMPIDA
    if resumen.error_fatal is not None:
        log.error("permisos de Bedrock denegados", extra={"campos": {"codigo": resumen.error_fatal.codigo}})
        sys.stdout.write(
            f"Bedrock rechazó la llamada ({resumen.error_fatal.codigo}). {resumen.error_fatal.sugerencia}\n"
        )
        return SALIDA_PERMISOS
    return SALIDA_FALLIDAS if resumen.total_fallidas or resumen.por_limite_llamadas else SALIDA_OK


def _imprimir_resumen(r: ResumenBarrido, id_ejecucion: str, model_id: str, version_prompt: str) -> None:
    lineas = [
        f"Copiloto {id_ejecucion} · cortes {r.cortes[0]}..{r.cortes[-1]} · {model_id} · {version_prompt}",
        f"  Solicitudes pendientes: {r.solicitudes_pendientes} · peor caso {r.invocaciones_peor_caso} invocaciones",
        f"  Presupuesto: invocaciones al modelo: {r.llamadas_modelo} de {r.max_llamadas} (--max-llamadas)"
        f" · sin procesar por limite_llamadas: {r.por_limite_llamadas}",
        f"  Analizadas: {r.analizadas}",
        f"  Omitidas por motivo: {r.omitidas}",
        f"  Fallidas por motivo: {r.fallidas or 0}",
        *([f"  Interrumpidas (Ctrl+C, se retoman al volver a ejecutar): {r.interrumpidas}"] if r.interrumpido else []),
        f"  Tokens: entrada {r.tokens_entrada} · salida {r.tokens_salida}",
        f"  Tiempo: {r.segundos} s",
    ]
    lineas += [f"  {corte}: {conteos}" for corte, conteos in r.por_corte.items()]
    sys.stdout.write("\n".join(lineas) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
