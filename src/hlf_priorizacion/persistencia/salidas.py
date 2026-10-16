"""Escritura y lectura de salidas en ``salidas/`` (adaptador local del MVP; U4 lo cambia por DynamoDB/S3).

- Propuestas: Parquet en ``propuestas/fecha_corte=AAAA-MM-DD/version_reglas=…/propuestas.parquet``,
  clave ``(id_solicitud, fecha_corte, version_reglas)``. Semántica de escritura condicional
  (``attribute_not_exists``): una clave existente no se sobrescribe; re-ejecutar no duplica.
- Hallazgos DQ, cuarentena y cohortes: JSONL de solo agregado e idempotente (solo se agregan las
  líneas cuya clave aún no está en el archivo).

Las escrituras de archivos completos son atómicas (archivo temporal + ``os.replace``).
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from hlf_priorizacion.modelos import ORDEN_NIVEL, Evaluacion

ARCHIVO_PROPUESTAS = "propuestas.parquet"

_CAMPOS_PROPUESTAS: list[pa.Field[Any]] = [
    pa.field("id_solicitud", pa.string(), nullable=False),
    pa.field("fecha_corte", pa.string(), nullable=False),
    pa.field("version_reglas", pa.string(), nullable=False),
    pa.field("especialidad", pa.string(), nullable=False),
    pa.field("prioridad_inicial", pa.string(), nullable=False),
    pa.field("puntaje", pa.float64()),
    pa.field("nivel_calculado", pa.string()),
    pa.field("nivel_propuesto", pa.string()),
    pa.field("magnitud_cambio", pa.int64()),
    pa.field("tipo_resultado", pa.string(), nullable=False),
    pa.field("confianza", pa.string(), nullable=False),
    pa.field("estado_revision", pa.string(), nullable=False),
    pa.field("huella_contexto", pa.string(), nullable=False),
    pa.field("evaluacion_json", pa.string(), nullable=False),
]
ESQUEMA_PROPUESTAS = pa.schema(_CAMPOS_PROPUESTAS)


class ErrorPersistencia(Exception):
    """Fallo de E/S al escribir o leer salidas."""


@dataclass(frozen=True)
class ResultadoEscritura:
    ruta: Path
    nuevas: int
    existentes: int
    conflictos: int


def ruta_propuestas(raiz: Path, fecha_corte: date, version_reglas: str) -> Path:
    return (
        raiz
        / "propuestas"
        / f"fecha_corte={fecha_corte.isoformat()}"
        / f"version_reglas={version_reglas}"
        / ARCHIVO_PROPUESTAS
    )


def _fila(ev: Evaluacion, especialidad: str) -> dict[str, Any]:
    magnitud = (
        ORDEN_NIVEL[ev.nivel_propuesto] - ORDEN_NIVEL[ev.prioridad_inicial] if ev.nivel_propuesto is not None else None
    )
    return {
        "id_solicitud": ev.id_solicitud,
        "fecha_corte": ev.fecha_corte.isoformat(),
        "version_reglas": ev.version_reglas,
        "especialidad": especialidad,
        "prioridad_inicial": ev.prioridad_inicial,
        "puntaje": ev.puntaje,
        "nivel_calculado": ev.nivel_calculado,
        "nivel_propuesto": ev.nivel_propuesto,
        "magnitud_cambio": magnitud,
        "tipo_resultado": ev.tipo_resultado,
        "confianza": ev.confianza,
        "estado_revision": ev.estado_revision,
        "huella_contexto": ev.huella_contexto,
        "evaluacion_json": ev.model_dump_json(),
    }


def _leer_filas(ruta: Path) -> list[dict[str, Any]]:
    if not ruta.exists():
        return []
    try:
        return pq.read_table(ruta, schema=ESQUEMA_PROPUESTAS).to_pylist()
    except (OSError, pa.ArrowException) as e:
        raise ErrorPersistencia(f"no se pudo leer {ruta}: {type(e).__name__}") from e


def _escribir_atomico(ruta: Path, escribir: Callable[[Path], None]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=ruta.parent)
    os.close(fd)
    try:
        escribir(Path(tmp))
        os.replace(tmp, ruta)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def escribir_propuestas(raiz: Path, propuestas: Iterable[tuple[Evaluacion, str]]) -> list[ResultadoEscritura]:
    """Escribe propuestas ``(evaluacion, especialidad)`` agrupadas por partición. Idempotente."""
    por_particion: dict[Path, list[dict[str, Any]]] = {}
    for ev, especialidad in propuestas:
        por_particion.setdefault(ruta_propuestas(raiz, ev.fecha_corte, ev.version_reglas), []).append(
            _fila(ev, especialidad)
        )

    resultados = []
    for ruta, filas in sorted(por_particion.items()):
        existentes = {f["id_solicitud"]: f for f in _leer_filas(ruta)}
        nuevas = conflictos = repetidas = 0
        combinadas = dict(existentes)
        for fila in filas:
            previa = combinadas.get(fila["id_solicitud"])
            if previa is None:
                combinadas[fila["id_solicitud"]] = fila
                nuevas += 1
            elif previa["evaluacion_json"] == fila["evaluacion_json"]:
                repetidas += 1
            else:
                conflictos += 1  # escritura condicional: se conserva la primera
        if nuevas:
            tabla = pa.Table.from_pylist([combinadas[k] for k in sorted(combinadas)], schema=ESQUEMA_PROPUESTAS)

            def _parquet(tmp: Path, t: pa.Table = tabla) -> None:
                pq.write_table(t, tmp, compression="snappy")

            try:
                _escribir_atomico(ruta, _parquet)
            except (OSError, pa.ArrowException) as e:
                raise ErrorPersistencia(f"no se pudo escribir {ruta}: {type(e).__name__}") from e
        resultados.append(ResultadoEscritura(ruta, nuevas, repetidas, conflictos))
    return resultados


def leer_propuestas(raiz: Path, fecha_corte: date, version_reglas: str) -> list[Evaluacion]:
    """Lectura para U2 y U3: las evaluaciones de una partición, ordenadas por ``id_solicitud``."""
    filas = _leer_filas(ruta_propuestas(raiz, fecha_corte, version_reglas))
    return [Evaluacion.model_validate_json(f["evaluacion_json"]) for f in filas]


def agregar_jsonl(
    ruta: Path,
    registros: Iterable[dict[str, Any]],
    clave: Callable[[dict[str, Any]], str],
    *,
    vistos_por_ruta: dict[Path, set[str]] | None = None,
) -> int:
    """Agrega al final solo los registros cuya clave no está ya en el archivo. Devuelve cuántos agregó.

    Con ``vistos_por_ruta`` (un caché por ejecución, protegido por el candado de quien escribe) el archivo
    se lee una sola vez por ruta y las escrituras siguientes solo agregan: sirve para escribir solicitud a
    solicitud sin releer un archivo que crece. Supone un solo proceso escribiendo esa ruta.
    """
    nuevos: list[str] = []
    try:
        vistos = vistos_por_ruta.get(ruta) if vistos_por_ruta is not None else None
        if vistos is None:
            vistos = set()
            if ruta.exists():
                with ruta.open(encoding="utf-8") as f:
                    for linea in f:
                        if linea.strip():
                            vistos.add(clave(json.loads(linea)))
            if vistos_por_ruta is not None:
                vistos_por_ruta[ruta] = vistos
        claves_nuevas: set[str] = set()
        for r in registros:
            k = clave(r)
            if k not in vistos and k not in claves_nuevas:
                claves_nuevas.add(k)
                nuevos.append(json.dumps(r, ensure_ascii=False, sort_keys=True))
        if nuevos:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            with ruta.open("a", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(nuevos) + "\n")
        vistos.update(claves_nuevas)  # solo después de escribir: un fallo no deja claves fantasma en el caché
    except (OSError, json.JSONDecodeError) as e:
        raise ErrorPersistencia(f"no se pudo actualizar {ruta}: {type(e).__name__}") from e
    return len(nuevos)


def escribir_json(ruta: Path, datos: dict[str, Any]) -> None:
    """Escribe un JSON completo de forma atómica (resúmenes por corte)."""
    texto = json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def _texto(tmp: Path) -> None:
        tmp.write_text(texto, encoding="utf-8", newline="\n")

    try:
        _escribir_atomico(ruta, _texto)
    except OSError as e:
        raise ErrorPersistencia(f"no se pudo escribir {ruta}: {type(e).__name__}") from e
