"""Parte el dataset en exportaciones por periodo, como las entregaría el HLF (F0006).

Cada exportación es una carpeta con los CSV del periodo y un `periodo.json`:
- pacientes y solicitudes con el estado que tenían AL CIERRE del periodo (una solicitud atendida o un paciente
  fallecido después del cierre aparecen todavía en espera);
- solo los ingresos nuevos y las solicitudes o pacientes que cambiaron respecto del periodo anterior;
- eventos, mediciones, citas y agenda del periodo, con algunos días de solapamiento con el anterior;
- para un paciente que entra a la lista en este periodo, también sus registros anteriores.
Sumar todas las exportaciones en orden deja raw idéntico al dataset completo.

Uso:
    python scripts/exportaciones_demo.py --cortes 2026-06-30 2026-09-30 2026-10-13 --destino data/buzon
Las carpetas quedan listas para subirlas en la vista Cargas o dejarlas en el buzón de la consolidación nocturna
(HLF_BUZON).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

ARCHIVOS = {"pacientes": "pacientes.csv", "lista": "lista_espera.csv", "eventos": "eventos_clinicos.csv",
            "mediciones": "mediciones.csv", "citas": "citaciones.csv", "agenda": "agenda_box.csv"}
FECHA = {"eventos": "fecha_evento", "mediciones": "fecha_medicion", "citas": "fecha_cita", "agenda": "fecha"}


def _leer(data_dir: Path, archivo: str) -> tuple[list[str], list[dict]]:
    with (data_dir / archivo).open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        return list(lector.fieldnames), list(lector)


def _escribir(carpeta: Path, archivo: str, columnas: list[str], filas: list[dict]):
    with (carpeta / archivo).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, lineterminator="\n")
        w.writeheader()
        w.writerows(filas)


def _d(s: str) -> date | None:
    return date.fromisoformat(s) if s else None


def partir(data_dir: Path, cortes: list[date], destino: Path, solapamiento_dias: int = 30) -> list[Path]:
    """Escribe una carpeta por periodo en `destino` (nombre = fecha de cierre) y devuelve sus rutas en orden."""
    tablas = {k: _leer(data_dir, v) for k, v in ARCHIVOS.items()}
    cols = {k: v[0] for k, v in tablas.items()}
    filas = {k: v[1] for k, v in tablas.items()}

    asistio: dict[str, date] = {}
    for c in filas["citas"]:
        if c["estado_cita"] == "asistio":
            f = _d(c["fecha_cita"])
            asistio[c["id_paciente"]] = min(asistio.get(c["id_paciente"], f), f)
    defuncion = {p["id_paciente"]: _d(p["fecha_defuncion"]) for p in filas["pacientes"]}

    def solicitud_al(s: dict, corte: date) -> dict:
        egreso = asistio.get(s["id_paciente"]) if s["estado"] == "atendido" else \
            defuncion.get(s["id_paciente"]) if s["estado"] == "fallecido" else None
        return dict(s, estado="en_espera") if egreso and egreso > corte else dict(s)

    def paciente_al(p: dict, corte: date) -> dict:
        d = defuncion[p["id_paciente"]]
        return dict(p, fallecido="false", fecha_defuncion="") if d and d > corte else dict(p)

    destino.mkdir(parents=True, exist_ok=True)
    carpetas, anterior = [], None
    vistos_lista: dict[str, dict] = {}
    vistos_pac: dict[str, dict] = {}
    for corte in cortes:
        carpeta = destino / corte.isoformat()
        carpeta.mkdir(parents=True, exist_ok=True)
        en_lista = [s for s in filas["lista"] if _d(s["fecha_ingreso_lista"]) <= corte]
        pacientes_lista = {s["id_paciente"] for s in en_lista}
        nuevos_pac = pacientes_lista - set(vistos_pac)
        lista_out = []
        for s in en_lista:
            actual = solicitud_al(s, corte)
            if vistos_lista.get(s["id_solicitud"]) != actual:
                lista_out.append(actual)
                vistos_lista[s["id_solicitud"]] = actual
        inicio = anterior - timedelta(days=solapamiento_dias) if anterior else None
        hijos = {}
        for k in ("eventos", "mediciones", "citas"):
            hijos[k] = [f for f in filas[k] if f["id_paciente"] in pacientes_lista and _d(f[FECHA[k]]) <= corte
                        and (inicio is None or _d(f[FECHA[k]]) > inicio or f["id_paciente"] in nuevos_pac)]
        agenda = [f for f in filas["agenda"] if _d(f["fecha"]) <= corte and (inicio is None or _d(f["fecha"]) > inicio)]
        con_datos = {f["id_paciente"] for k in hijos for f in hijos[k]} | {s["id_paciente"] for s in lista_out}
        pac_out = []
        for p in filas["pacientes"]:
            if p["id_paciente"] not in pacientes_lista:
                continue
            actual = paciente_al(p, corte)
            if p["id_paciente"] in con_datos or vistos_pac.get(p["id_paciente"]) != actual:
                pac_out.append(actual)
                vistos_pac[p["id_paciente"]] = actual
        _escribir(carpeta, ARCHIVOS["pacientes"], cols["pacientes"], pac_out)
        _escribir(carpeta, ARCHIVOS["lista"], cols["lista"], lista_out)
        for k in ("eventos", "mediciones", "citas"):
            _escribir(carpeta, ARCHIVOS[k], cols[k], hijos[k])
        _escribir(carpeta, ARCHIVOS["agenda"], cols["agenda"], agenda)
        desde = (anterior + timedelta(days=1)).isoformat() if anterior else None
        (carpeta / "periodo.json").write_text(json.dumps({"desde": desde, "hasta": corte.isoformat()}), encoding="utf-8")
        carpetas.append(carpeta)
        anterior = corte
    return carpetas


def main(argv=None) -> int:
    from priorizacion.config import DATA_DIR
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--cortes", nargs="+", required=True, help="Fechas de cierre de cada periodo (AAAA-MM-DD), en orden")
    p.add_argument("--destino", type=Path, required=True)
    p.add_argument("--datos", type=Path, default=DATA_DIR)
    p.add_argument("--solapamiento", type=int, default=30, help="Días que cada periodo repite del anterior")
    args = p.parse_args(argv)
    cortes = sorted(date.fromisoformat(c) for c in args.cortes)
    for carpeta in partir(args.datos, cortes, args.destino, args.solapamiento):
        n = {a.name: sum(1 for _ in a.open(encoding="utf-8")) - 1 for a in sorted(carpeta.glob("*.csv"))}
        print(f"{carpeta}: " + ", ".join(f"{k.replace('.csv', '')} {v}" for k, v in n.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
