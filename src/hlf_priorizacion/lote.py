"""CLI del lote: ``hlf-lote --fecha-corte AAAA-MM-DD [--datos RUTA] [--salidas RUTA] [--reglas RUTA]``.

Flujo (``business-logic-model.md``): cargar perfiles -> contrato/cuarentena -> ingesta y conciliación ->
contexto a la fecha de corte -> calidad de datos -> motor -> cohortes -> salidas idempotentes ->
auditoría -> cobertura y resumen.

Códigos de salida: 0 correcto; 1 cobertura < 100 %; 2 argumentos, configuración o fuente inválidos
(fail-closed); 3 error inesperado.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from hlf_priorizacion.auditoria.registro import RegistroAuditoria, nuevo_ulid
from hlf_priorizacion.calidad.auditoria import auditar
from hlf_priorizacion.contrato.catalogos import VERSION_CONTRATO
from hlf_priorizacion.contrato.esquema import PerfilValido
from hlf_priorizacion.contrato.validacion import ResultadoValidacion, validar_perfil
from hlf_priorizacion.ingesta.carga import ErrorCarga, cargar_perfiles, cargar_tablas
from hlf_priorizacion.ingesta.conciliacion import conciliar
from hlf_priorizacion.ingesta.normalizacion import PerfilNormalizado, normalizar_perfil
from hlf_priorizacion.logs import configurar_logging, fijar_id_ejecucion, obtener_logger
from hlf_priorizacion.modelos import ORDEN_NIVEL, Evaluacion, HallazgoDQ
from hlf_priorizacion.motor.evaluar import evaluar
from hlf_priorizacion.motor.parametros import ErrorParametros, ParametrosReglas, cargar_parametros
from hlf_priorizacion.persistencia.salidas import (
    ErrorPersistencia,
    agregar_jsonl,
    escribir_json,
    escribir_propuestas,
)
from hlf_priorizacion.repositorio.cohortes import cohorte
from hlf_priorizacion.repositorio.contexto import FECHA_EXTRACCION_DATASET, Repositorio

SALIDA_OK, SALIDA_COBERTURA, SALIDA_ENTRADA, SALIDA_INESPERADA = 0, 1, 2, 3
_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATOS_POR_DEFECTO = Path("data/dataset_hlf_ambulatorio")
SALIDAS_POR_DEFECTO = Path("salidas")


class ErrorEntrada(Exception):
    """Argumento, configuración o fuente inválidos: el lote no arranca."""


# --------------------------------------------------------------------------- argumentos


def _fecha(texto: str) -> date:
    if not _RE_FECHA.match(texto):
        raise argparse.ArgumentTypeError("formato esperado AAAA-MM-DD")
    try:
        return date.fromisoformat(texto)
    except ValueError as e:
        raise argparse.ArgumentTypeError("fecha inexistente") from e


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hlf-lote", description="Lote del motor de priorización clínica dinámica (U1).")
    p.add_argument("--fecha-corte", required=True, type=_fecha, help="fecha de corte AAAA-MM-DD")
    p.add_argument("--datos", type=Path, default=DATOS_POR_DEFECTO, help="carpeta con perfiles.json y los CSV")
    p.add_argument("--salidas", type=Path, default=SALIDAS_POR_DEFECTO, help="carpeta de salidas")
    p.add_argument("--reglas", type=Path, default=None, help="archivo reglas-vX.Y.Z.yaml (por defecto el empaquetado)")
    p.add_argument(
        "--fecha-extraccion",
        type=_fecha,
        default=FECHA_EXTRACCION_DATASET,
        help="fecha de extracción del dataset (por defecto 2026-10-13)",
    )
    return p


@dataclass(frozen=True)
class Configuracion:
    fecha_corte: date
    fecha_extraccion: date
    datos: Path
    salidas: Path
    reglas: Path | None


def validar_configuracion(args: argparse.Namespace) -> Configuracion:
    fecha_corte: date = args.fecha_corte
    fecha_extraccion: date = args.fecha_extraccion
    if fecha_corte > fecha_extraccion:
        raise ErrorEntrada("--fecha-corte no puede ser posterior a la fecha de extracción")
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
    return Configuracion(fecha_corte, fecha_extraccion, datos, salidas, reglas)


# --------------------------------------------------------------------------- lote


@dataclass
class ResultadoLote:
    resumen: dict[str, Any]
    evaluaciones: list[Evaluacion] = field(default_factory=list)

    @property
    def cobertura_completa(self) -> bool:
        return bool(self.resumen["cobertura"]["completa"])


def _huella_salida(ev: Evaluacion) -> str:
    return "sha256:" + hashlib.sha256(ev.model_dump_json().encode("utf-8")).hexdigest()


def _clave_hallazgo(r: dict[str, Any]) -> str:
    return f"{r['id_solicitud']}|{r['codigo']}|{','.join(r['ids_registro'])}"


def ejecutar_lote(cfg: Configuracion, params: ParametrosReglas, id_ejecucion: str) -> ResultadoLote:
    log = obtener_logger()
    corte = cfg.fecha_corte
    auditoria = RegistroAuditoria(cfg.salidas / "auditoria" / "eventos.jsonl", id_ejecucion)

    # 1. Carga (fail-closed si la fuente no se puede leer).
    crudos = cargar_perfiles(cfg.datos)
    log.info("perfiles cargados", extra={"campos": {"n": len(crudos), "etapa": "carga"}})

    # 2. Contrato y cuarentena (R1). Un perfil que falla no detiene el lote.
    validos: list[PerfilValido] = []
    cuarentena: list[ResultadoValidacion] = []
    errores: Counter[str] = Counter()
    for raw in crudos:
        try:
            res = validar_perfil(raw)
        except Exception as e:  # defensivo: un perfil nunca detiene el lote
            errores["validacion"] += 1
            log.error("error al validar un perfil", extra={"campos": {"tipo_error": type(e).__name__}})
            continue
        if res.ok and res.perfil is not None:
            validos.append(res.perfil)
        else:
            cuarentena.append(res)
            log.warning(
                "perfil en cuarentena",
                extra={"campos": {"id_paciente": res.id_paciente, "codigo": "perfil_en_cuarentena"}},
            )

    # 3. Ingesta: normalización y conciliación.
    normalizados: list[PerfilNormalizado] = []
    hallazgos_ingesta: dict[str, list[HallazgoDQ]] = {}
    for perfil in validos:
        try:
            rn = normalizar_perfil(perfil)
        except Exception as e:
            errores["normalizacion"] += 1
            log.error(
                "error al normalizar un perfil",
                extra={"campos": {"id_paciente": perfil.id_paciente, "tipo_error": type(e).__name__}},
            )
            continue
        normalizados.append(rn.perfil)
        hallazgos_ingesta[perfil.id_paciente] = list(rn.hallazgos)
    tablas = cargar_tablas(cfg.datos)
    if tablas.faltantes:
        log.warning("tablas no disponibles para conciliar", extra={"campos": {"tablas": list(tablas.faltantes)}})
    informe = conciliar(validos, tablas)
    for pid, hs in informe.hallazgos.items():
        hallazgos_ingesta.setdefault(pid, []).extend(hs)

    repo = Repositorio(normalizados, cfg.fecha_extraccion)
    fallidos_normalizacion = {p.id_paciente for p in validos} - {p.id_paciente for p in normalizados}

    # 4. Contexto, calidad y motor por solicitud vigente a la fecha de corte.
    evaluaciones: list[Evaluacion] = []
    especialidad: dict[str, str] = {}
    filas_dq: list[dict[str, Any]] = []
    no_vigentes = 0
    en_espera = Counter[str]()
    sin_cubrir: list[str] = []
    for perfil in sorted(validos, key=lambda p: p.id_paciente):
        for s in perfil.lista_espera:
            if s.fecha_ingreso_lista > corte:
                no_vigentes += 1
                continue
            if s.estado == "en_espera":
                en_espera["vigentes"] += 1
            if perfil.id_paciente in fallidos_normalizacion:
                sin_cubrir.append(s.id_solicitud)
                continue
            try:
                ctx = repo.contexto_a_fecha(s.id_solicitud, corte)
                presentes = ctx.ids_presentes()
                previos = [
                    h.model_copy(update={"ids_registro": [i for i in h.ids_registro if i in presentes]})
                    for h in hallazgos_ingesta.get(perfil.id_paciente, [])
                    if any(i in presentes for i in h.ids_registro)
                ]
                dq = previos + auditar(ctx)
                ev = evaluar(ctx, dq, params)
            except Exception as e:
                errores["evaluacion"] += 1
                sin_cubrir.append(s.id_solicitud)
                log.error(
                    "error al evaluar una solicitud",
                    extra={"campos": {"id_solicitud": s.id_solicitud, "tipo_error": type(e).__name__}},
                )
                auditoria.registrar(
                    "error_proceso",
                    id_solicitud=s.id_solicitud,
                    fecha_corte=corte.isoformat(),
                    version_reglas=params.version,
                    etapa="evaluacion",
                    tipo_error=type(e).__name__,
                )
                continue
            evaluaciones.append(ev)
            especialidad[ev.id_solicitud] = s.especialidad
            if s.estado == "en_espera":
                en_espera["evaluadas"] += 1
            filas_dq.extend(
                {"id_solicitud": s.id_solicitud, "fecha_corte": corte.isoformat(), **h.model_dump(mode="json")}
                for h in dq
            )
            auditoria.registrar(
                "evaluacion_motor",
                id_solicitud=ev.id_solicitud,
                fecha_corte=corte.isoformat(),
                version_reglas=params.version,
                huella_entrada=ev.huella_contexto,
                huella_salida=_huella_salida(ev),
                tipo_resultado=ev.tipo_resultado,
            )

    if validos and not evaluaciones and not sin_cubrir:
        raise ErrorEntrada("--fecha-corte es anterior al ingreso de todas las solicitudes: no hay nada que evaluar")

    # 5. Cohortes (R9) para las priorizaciones.
    filas_cohorte = []
    for ev in evaluaciones:
        if ev.tipo_resultado != "priorizacion":
            continue
        try:
            rc = cohorte(repo.perfiles, ev.id_solicitud, corte, cfg.fecha_extraccion)
        except Exception as e:
            errores["cohorte"] += 1
            log.error(
                "error al calcular la cohorte",
                extra={"campos": {"id_solicitud": ev.id_solicitud, "tipo_error": type(e).__name__}},
            )
            continue
        filas_cohorte.append(
            {
                "id_solicitud": ev.id_solicitud,
                "fecha_corte": corte.isoformat(),
                "version_reglas": params.version,
                **rc.model_dump(mode="json"),
            }
        )

    # 6-7. Salidas idempotentes.
    escrituras = escribir_propuestas(cfg.salidas, [(ev, especialidad[ev.id_solicitud]) for ev in evaluaciones])
    particion = f"fecha_corte={corte.isoformat()}"
    agregar_jsonl(cfg.salidas / "hallazgos_dq" / particion / "hallazgos.jsonl", filas_dq, _clave_hallazgo)
    agregar_jsonl(
        cfg.salidas / "cohortes" / particion / f"version_reglas={params.version}" / "cohortes.jsonl",
        filas_cohorte,
        lambda r: str(r["id_solicitud"]),
    )
    agregar_jsonl(
        cfg.salidas / "cuarentena" / f"fecha_extraccion={cfg.fecha_extraccion.isoformat()}" / "cuarentena.jsonl",
        [
            {
                "id_paciente": r.id_paciente,
                "ids_solicitud": r.ids_solicitud,
                "motivos": r.motivos,
                "version_contrato": r.version_contrato,
                "alerta_gestion": "perfil_en_cuarentena",
                "accion_sugerida": "Corrección en origen",
            }
            for r in cuarentena
        ],
        lambda r: f"{r['id_paciente']}|{','.join(r['ids_solicitud'])}|{'/'.join(r['motivos'])}",
    )

    # 8. Cobertura (R1.3) y resumen.
    ids_cuarentena = [i for r in cuarentena for i in r.ids_solicitud]
    vigentes = len(evaluaciones) + len(sin_cubrir)
    universo = vigentes + len(ids_cuarentena)
    cubiertas = len(evaluaciones) + len(ids_cuarentena)
    cobertura = 100.0 if universo == 0 else round(100.0 * cubiertas / universo, 2)
    cambios = Counter[str]()
    for ev in evaluaciones:
        if ev.nivel_propuesto is not None and ev.nivel_propuesto != ev.prioridad_inicial:
            sube = ORDEN_NIVEL[ev.nivel_propuesto] > ORDEN_NIVEL[ev.prioridad_inicial]
            cambios["sube" if sube else "baja"] += 1
    resumen: dict[str, Any] = {
        "fecha_corte": corte.isoformat(),
        "fecha_extraccion": cfg.fecha_extraccion.isoformat(),
        "version_reglas": params.version,
        "version_contrato": VERSION_CONTRATO,
        "perfiles": {
            "total": len(crudos),
            "validos": len(validos),
            "cuarentena": len(cuarentena),
            "con_diferencias_conciliacion": informe.perfiles_con_diferencias,
        },
        "solicitudes": {
            "evaluadas": len(evaluaciones),
            "en_cuarentena": len(ids_cuarentena),
            "sin_cubrir": sorted(sin_cubrir),
            "no_vigentes_a_la_fecha": no_vigentes,
            "por_tipo_resultado": dict(sorted(Counter(ev.tipo_resultado for ev in evaluaciones).items())),
            "exclusiones": dict(
                sorted(Counter(ev.codigo_exclusion for ev in evaluaciones if ev.codigo_exclusion).items())
            ),
            "cambios_de_nivel": dict(sorted(cambios.items())),
            "por_nivel_propuesto": dict(
                sorted(Counter(ev.nivel_propuesto for ev in evaluaciones if ev.nivel_propuesto).items())
            ),
        },
        "en_espera": {
            "vigentes_validas": en_espera["vigentes"],
            "evaluadas": en_espera["evaluadas"],
        },
        "cobertura": {
            "universo": universo,
            "cubiertas": cubiertas,
            "porcentaje": cobertura,
            "completa": not sin_cubrir,
        },
        "hallazgos_dq": dict(sorted(Counter(f["nivel"] for f in filas_dq).items())),
        "cohortes_calculadas": len(filas_cohorte),
        "errores": dict(sorted(errores.items())),
        "propuestas": {
            "nuevas": sum(r.nuevas for r in escrituras),
            "ya_existentes": sum(r.existentes for r in escrituras),
            "conflictos": sum(r.conflictos for r in escrituras),
        },
    }
    # El resumen persistido solo lleva conteos deterministas del corte (idéntico al re-ejecutar);
    # los contadores de escritura dependen de la ejecución y solo se informan por consola y log.
    persistido = {k: v for k, v in resumen.items() if k != "propuestas"}
    escribir_json(cfg.salidas / "resumen" / particion / f"version_reglas={params.version}" / "resumen.json", persistido)
    return ResultadoLote(resumen=resumen, evaluaciones=evaluaciones)


# --------------------------------------------------------------------------- punto de entrada


def _salida_utf8() -> None:
    """En Windows la consola o la tubería pueden usar otra codificación; los mensajes van en UTF-8."""
    for flujo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if callable(reconfigurar):
            reconfigurar(encoding="utf-8", errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    _salida_utf8()
    log = configurar_logging()
    id_ejecucion = f"lote-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{nuevo_ulid()[-8:]}"
    fijar_id_ejecucion(id_ejecucion)
    args = construir_parser().parse_args(argv)
    try:
        cfg = validar_configuracion(args)
        params = cargar_parametros(cfg.reglas)
        log.info(
            "inicio del lote",
            extra={"campos": {"fecha_corte": cfg.fecha_corte.isoformat(), "version_reglas": params.version}},
        )
        resultado = ejecutar_lote(cfg, params, id_ejecucion)
    except (ErrorEntrada, ErrorParametros, ErrorCarga) as e:
        log.error(f"entrada inválida: {e}", extra={"campos": {"tipo_error": type(e).__name__}})
        return SALIDA_ENTRADA
    except ErrorPersistencia as e:
        log.error(f"error de escritura de salidas: {e}", extra={"campos": {"tipo_error": type(e).__name__}})
        return SALIDA_INESPERADA
    except Exception as e:  # manejador global: no se filtran mensajes ni trazas con datos
        log.error("error inesperado; el lote se detuvo", extra={"campos": {"tipo_error": type(e).__name__}})
        return SALIDA_INESPERADA

    r = resultado.resumen
    log.info(
        "fin del lote",
        extra={
            "campos": {
                "cobertura_pct": r["cobertura"]["porcentaje"],
                "conteos": {
                    "evaluadas": r["solicitudes"]["evaluadas"],
                    "cuarentena": r["perfiles"]["cuarentena"],
                    "errores": sum(r["errores"].values()),
                },
            }
        },
    )
    _imprimir_resumen(r, id_ejecucion)
    if not resultado.cobertura_completa:
        log.error("cobertura incompleta", extra={"campos": {"cobertura_pct": r["cobertura"]["porcentaje"]}})
        return SALIDA_COBERTURA
    return SALIDA_OK


def _imprimir_resumen(r: dict[str, Any], id_ejecucion: str) -> None:
    s = r["solicitudes"]
    lineas = [
        f"Lote {id_ejecucion} · corte {r['fecha_corte']} · {r['version_reglas']}",
        f"  Perfiles: {r['perfiles']['total']} ({r['perfiles']['validos']} válidos, "
        f"{r['perfiles']['cuarentena']} en cuarentena)",
        f"  Solicitudes evaluadas: {s['evaluadas']} · no vigentes a la fecha: {s['no_vigentes_a_la_fecha']}",
        f"  Por tipo de resultado: {s['por_tipo_resultado']}",
        f"  Exclusiones: {s['exclusiones']}",
        f"  Cambios de nivel: {s['cambios_de_nivel']}",
        f"  En espera vigentes evaluadas: {r['en_espera']['evaluadas']}/{r['en_espera']['vigentes_validas']}",
        f"  Cobertura: {r['cobertura']['porcentaje']} % ({r['cobertura']['cubiertas']}/{r['cobertura']['universo']})",
        f"  Propuestas nuevas: {r['propuestas']['nuevas']} · ya existentes: {r['propuestas']['ya_existentes']} · "
        f"conflictos: {r['propuestas']['conflictos']}",
        f"  Errores: {r['errores'] or 0}",
    ]
    sys.stdout.write("\n".join(lineas) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
