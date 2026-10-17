"""Exportaciones de eventos clínicos para probar y mostrar la repriorización (vista Cargas).

Escribe dos exportaciones incrementales, cada una en su carpeta con `eventos_clinicos.csv` y `periodo.json`:

    prueba/  2026-10-14 a 2026-10-20 · 3 pacientes de Cardiología
    demo/    2026-10-21 a 2026-10-27 · 3 pacientes de Broncopulmonar y 1 de Salud Mental
    demo2/   2026-10-28 a 2026-11-03 · los mismos 4 pacientes de demo, con la evolución invertida

Cada grupo muestra los tres patrones: un evento grave (sube a alta con alerta), un deterioro progresivo (sube por
la suma de señales) y una mejora (baja un nivel porque hay evidencia). Los periodos no se cruzan: la demo funciona
aunque antes se haya cargado la prueba en el mismo ambiente.

    python scripts/eventos_demo.py --destino data/eventos_demo            # escribe las dos carpetas
    python scripts/eventos_demo.py --destino data/eventos_demo --simular  # y muestra el efecto en la cola

Los pacientes vienen de los CSV originales (data/dataset_hlf_ambulatorio). Los IDs de evento siguen al último del
dataset (EV-000786).
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

SEVERIDAD = {"descompensación grave": "grave", "ingreso UCI": "grave", "ingreso hospitalario": "grave",
             "triage ESI 2": "grave", "descompensación": "moderada", "aumento dosis": "moderada",
             "resultado alterado": "moderada", "buena respuesta": "leve", "reducción dosis": "leve",
             "estabilización": "leve"}
TIPO = {"descompensación grave": "visita_urgencia", "descompensación": "visita_urgencia", "triage ESI 2": "visita_urgencia",
        "ingreso UCI": "hospitalizacion", "ingreso hospitalario": "hospitalizacion", "aumento dosis": "cambio_farmaco",
        "reducción dosis": "cambio_farmaco", "resultado alterado": "examen_alterado", "buena respuesta": "control_aps",
        "estabilización": "control_aps"}

# (carpeta, desde, hasta, [(paciente, especialidad, patrón, [(fecha, subtipo)])])
EXPORTACIONES = [
    ("prueba", "2026-10-14", "2026-10-20", [
        ("PAC-HLF-00181", "Cardiología", "Evento grave", [("2026-10-16", "descompensación grave")]),
        ("PAC-HLF-00005", "Cardiología", "Deterioro progresivo",
         [("2026-10-14", "aumento dosis"), ("2026-10-17", "resultado alterado"), ("2026-10-19", "descompensación")]),
        ("PAC-HLF-00432", "Cardiología", "Mejora",
         [("2026-10-15", "buena respuesta"), ("2026-10-17", "reducción dosis"), ("2026-10-19", "estabilización")]),
    ]),
    ("demo", "2026-10-21", "2026-10-27", [
        ("PAC-HLF-00058", "Broncopulmonar", "Evento grave", [("2026-10-23", "ingreso UCI")]),
        ("PAC-HLF-00290", "Broncopulmonar", "Deterioro progresivo",
         [("2026-10-21", "aumento dosis"), ("2026-10-23", "resultado alterado"), ("2026-10-26", "descompensación")]),
        ("PAC-HLF-00100", "Broncopulmonar", "Mejora",
         [("2026-10-22", "buena respuesta"), ("2026-10-24", "reducción dosis"), ("2026-10-26", "estabilización")]),
        ("PAC-HLF-00221", "Salud Mental", "Evento grave", [("2026-10-25", "triage ESI 2")]),
    ]),
    ("demo2", "2026-10-28", "2026-11-03", [
        ("PAC-HLF-00058", "Broncopulmonar", "Mejora tras UCI",
         [("2026-10-28", "estabilización"), ("2026-10-31", "reducción dosis"), ("2026-11-02", "buena respuesta")]),
        ("PAC-HLF-00290", "Broncopulmonar", "Evento grave", [("2026-10-29", "ingreso hospitalario")]),
        ("PAC-HLF-00100", "Broncopulmonar", "Recaída",
         [("2026-10-29", "resultado alterado"), ("2026-10-31", "aumento dosis"), ("2026-11-02", "descompensación")]),
        ("PAC-HLF-00221", "Salud Mental", "Mejora tras urgencia",
         [("2026-10-29", "buena respuesta"), ("2026-11-01", "estabilización")]),
    ]),
]
COLUMNAS = ["id_paciente", "id_evento", "fecha_evento", "tipo_evento", "subtipo", "severidad", "detalle"]
PRIMER_ID = 787


def filas() -> dict[str, list[dict]]:
    n, salida = PRIMER_ID, {}
    for carpeta, _, _, pacientes in EXPORTACIONES:
        salida[carpeta] = []
        for pid, esp, _, eventos in pacientes:
            for fecha, subtipo in eventos:
                salida[carpeta].append({"id_paciente": pid, "id_evento": f"EV-{n:06d}", "fecha_evento": fecha,
                                        "tipo_evento": TIPO[subtipo], "subtipo": subtipo, "severidad": SEVERIDAD[subtipo],
                                        "detalle": f"{subtipo} ({esp})"})
                n += 1
    return salida


def escribir(destino: Path) -> list[Path]:
    rutas = []
    for (carpeta, desde, hasta, _), (_, lista) in zip(EXPORTACIONES, filas().items()):
        d = destino / carpeta
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "eventos_clinicos.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS)
            w.writeheader()
            w.writerows(lista)
        (d / "periodo.json").write_text(json.dumps({"desde": desde, "hasta": hasta}, indent=2), encoding="utf-8")
        rutas.append(d / "eventos_clinicos.csv")
    return rutas


def simular() -> None:
    """Aplica las exportaciones sobre una copia del dataset y compara la cola antes y después de cada una."""
    from priorizacion import config
    from priorizacion.bandeja import construir_bandeja
    from priorizacion.datos import Repositorio
    from priorizacion.registro import RegistroSQLite
    tmp = Path(tempfile.mkdtemp(prefix="hlf_eventos_"))
    datos = tmp / "datos"
    shutil.copytree(config.DATA_DIR, datos)
    registro = RegistroSQLite(tmp / "r.sqlite")
    cortes = {"inicio": date(2026, 10, 13)}
    antes = construir_bandeja(Repositorio.desde_csv(datos), registro, cortes["inicio"])[0].set_index("id_paciente")
    for (carpeta, _, hasta, pacientes), (_, lista) in zip(EXPORTACIONES, filas().items()):
        with open(datos / "eventos_clinicos.csv", "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=COLUMNAS).writerows(lista)
        despues = construir_bandeja(Repositorio.desde_csv(datos), registro, date.fromisoformat(hasta))[0].set_index("id_paciente")
        print(f"\n== {carpeta} (datos al {hasta})")
        for pid, esp, patron, _ in pacientes:
            a, d = antes.loc[pid], despues.loc[pid]
            print(f"  {d['nombre']:<24} {esp:<15} {patron:<21} {a['nivel_propuesto']:>5} → {d['nivel_propuesto']:<5} "
                  f"pos {a['posicion_dinamica']:>2} → {d['posicion_dinamica']:<2} de {d['total_cola']}"
                  f"{' · ALERTA' if d['alerta'] else ''}  ({d['motivo_principal']})")
        antes = despues
    shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--destino", type=Path, default=RAIZ / "data" / "eventos_demo")
    p.add_argument("--simular", action="store_true", help="Muestra el efecto en la cola (con una copia del dataset)")
    a = p.parse_args(argv)
    for r in escribir(a.destino):
        print(r)
    if a.simular:
        simular()
    return 0


if __name__ == "__main__":
    sys.exit(main())
