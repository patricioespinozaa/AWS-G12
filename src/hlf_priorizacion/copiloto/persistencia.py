"""Salidas del copiloto en ``salidas/`` (C5, C7.3) y lectura de lo que dejó el lote.

- ``analisis/fecha_corte=…/version_reglas=…/analisis.jsonl``: solo agregado, clave de idempotencia
  ``(id_solicitud, fecha_corte, version_reglas, version_prompt, model_id)``; nunca se sobrescribe.
- ``…/fallidos.jsonl``: solo agregado, una línea por solicitud fallida y ejecución.
- ``copiloto_io/fecha_corte=…/<huella>.json``: texto completo de entrada y salida del modelo,
  referenciado por huella desde la auditoría (los logs nunca llevan ese texto).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from hlf_priorizacion.copiloto.modelos import AnalisisFallido, RegistroAnalisis
from hlf_priorizacion.modelos import HallazgoDQ, ResultadoCohorte
from hlf_priorizacion.persistencia.salidas import ErrorPersistencia, agregar_jsonl, escribir_json

ARCHIVO_ANALISIS = "analisis.jsonl"
ARCHIVO_FALLIDOS = "fallidos.jsonl"


def carpeta_analisis(raiz: Path, fecha_corte: date, version_reglas: str) -> Path:
    return raiz / "analisis" / f"fecha_corte={fecha_corte.isoformat()}" / f"version_reglas={version_reglas}"


def clave_idempotencia(r: dict[str, Any]) -> str:
    return f"{r['id_solicitud']}|{r['fecha_corte']}|{r['version_reglas']}|{r['version_prompt']}|{r['model_id']}"


def _clave_fallido(r: dict[str, Any]) -> str:
    return f"{clave_idempotencia(r)}|{r['id_ejecucion']}"


def _leer_jsonl(ruta: Path) -> list[dict[str, Any]]:
    if not ruta.exists():
        return []
    try:
        with ruta.open(encoding="utf-8") as f:
            return [json.loads(linea) for linea in f if linea.strip()]
    except (OSError, json.JSONDecodeError) as e:
        raise ErrorPersistencia(f"no se pudo leer {ruta}: {type(e).__name__}") from e


def leer_analisis(raiz: Path, fecha_corte: date, version_reglas: str) -> list[RegistroAnalisis]:
    """Lectura para U3: análisis guardados de un corte, ordenados por ``id_solicitud`` y clave.

    ``RegistroAnalisis.revision_equidad`` trae las oraciones marcadas por C6.5 (regla 2): si no está vacía,
    U3 debe mostrar una advertencia visible. Los registros anteriores a la marca la leen como lista vacía.
    """
    filas = _leer_jsonl(carpeta_analisis(raiz, fecha_corte, version_reglas) / ARCHIVO_ANALISIS)
    registros = [RegistroAnalisis.model_validate_json(json.dumps(f, ensure_ascii=False)) for f in filas]
    return sorted(registros, key=lambda r: (r.id_solicitud, r.version_prompt, r.model_id))


def leer_fallidos(raiz: Path, fecha_corte: date, version_reglas: str) -> list[AnalisisFallido]:
    filas = _leer_jsonl(carpeta_analisis(raiz, fecha_corte, version_reglas) / ARCHIVO_FALLIDOS)
    return [AnalisisFallido.model_validate_json(json.dumps(f, ensure_ascii=False)) for f in filas]


def ya_analizadas(
    raiz: Path, fecha_corte: date, version_reglas: str, version_prompt: str | None, model_id: str
) -> set[str]:
    """IDs con un ``AnalisisIA`` guardado para ``(id_solicitud, fecha_corte, version_reglas, model_id)`` (C5.1).

    Con ``version_prompt=None`` vale un análisis de cualquier versión de prompt (desviación D-2: no se
    recalculan los análisis de una versión anterior al publicar otra). Con una versión, solo esa
    (``--forzar``: se puede volver a analizar con el prompt nuevo, nunca se duplica la clave completa).
    """
    filas = _leer_jsonl(carpeta_analisis(raiz, fecha_corte, version_reglas) / ARCHIVO_ANALISIS)
    return {
        str(f["id_solicitud"])
        for f in filas
        if f.get("model_id") == model_id and (version_prompt is None or f.get("version_prompt") == version_prompt)
    }


def guardar_analisis(
    raiz: Path,
    fecha_corte: date,
    version_reglas: str,
    registros: list[RegistroAnalisis],
    *,
    vistos_por_ruta: dict[Path, set[str]] | None = None,
) -> int:
    """Solo agregado e idempotente. ``vistos_por_ruta``: caché de claves por ejecución (escritura incremental)."""
    filas = [r.model_dump(mode="json") for r in sorted(registros, key=lambda r: r.id_solicitud)]
    ruta = carpeta_analisis(raiz, fecha_corte, version_reglas) / ARCHIVO_ANALISIS
    return agregar_jsonl(ruta, filas, clave_idempotencia, vistos_por_ruta=vistos_por_ruta)


def guardar_fallidos(
    raiz: Path,
    fecha_corte: date,
    version_reglas: str,
    fallidos: list[AnalisisFallido],
    *,
    vistos_por_ruta: dict[Path, set[str]] | None = None,
) -> int:
    filas = [f.model_dump(mode="json") for f in sorted(fallidos, key=lambda f: f.id_solicitud)]
    ruta = carpeta_analisis(raiz, fecha_corte, version_reglas) / ARCHIVO_FALLIDOS
    return agregar_jsonl(ruta, filas, _clave_fallido, vistos_por_ruta=vistos_por_ruta)


def guardar_io(raiz: Path, fecha_corte: date, huella: str, contenido: dict[str, Any]) -> Path:
    nombre = huella.removeprefix("sha256:")
    ruta = raiz / "copiloto_io" / f"fecha_corte={fecha_corte.isoformat()}" / f"{nombre}.json"
    if not ruta.exists():
        escribir_json(ruta, contenido)
    return ruta


def leer_hallazgos_dq(raiz: Path, fecha_corte: date) -> dict[str, list[HallazgoDQ]]:
    """Hallazgos DQ que guardó el lote, por solicitud (``hallazgos_dq/fecha_corte=…/hallazgos.jsonl``)."""
    ruta = raiz / "hallazgos_dq" / f"fecha_corte={fecha_corte.isoformat()}" / "hallazgos.jsonl"
    por_solicitud: dict[str, list[HallazgoDQ]] = {}
    for f in _leer_jsonl(ruta):
        campos = {k: f[k] for k in ("codigo", "nivel", "ids_registro", "detalle")}
        por_solicitud.setdefault(str(f["id_solicitud"]), []).append(
            HallazgoDQ.model_validate_json(json.dumps(campos, ensure_ascii=False))
        )
    return por_solicitud


def leer_cohortes(raiz: Path, fecha_corte: date, version_reglas: str) -> dict[str, ResultadoCohorte]:
    """Cohortes que guardó el lote (``cohortes/fecha_corte=…/version_reglas=…/cohortes.jsonl``)."""
    ruta = (
        raiz
        / "cohortes"
        / f"fecha_corte={fecha_corte.isoformat()}"
        / f"version_reglas={version_reglas}"
        / "cohortes.jsonl"
    )
    salida: dict[str, ResultadoCohorte] = {}
    for f in _leer_jsonl(ruta):
        campos = {k: v for k, v in f.items() if k not in {"id_solicitud", "fecha_corte", "version_reglas"}}
        salida[str(f["id_solicitud"])] = ResultadoCohorte.model_validate_json(json.dumps(campos, ensure_ascii=False))
    return salida
