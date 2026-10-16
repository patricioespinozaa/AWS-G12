"""Latencia por turno del asistente por voz (F0011) con Bedrock real: meta p90 < 2,5 s.

Simula llamadas completas con el núcleo y el adaptador de voz (los mismos que usa la Lambda de Lex), contra una base
PostgreSQL con el esquema canal y los contactos de demo (por ejemplo la de pruebas), y con el modelo del asistente en
Bedrock. Mide solo el núcleo (sin la red de Connect ni la Lambda, que suman ~0,2 s).

    HLF_TEST_DATABASE_URL=… python scripts/latencia_voz.py --llamadas 5
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
TURNOS = ["hola", "¿tengo alguna cita?", "en qué lugar de la lista voy", "¿qué debo llevar a la cita?"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--llamadas", type=int, default=5)
    p.add_argument("--url", default=os.environ.get("HLF_TEST_DATABASE_URL") or os.environ.get("HLF_DATABASE_URL"))
    args = p.parse_args(argv)
    import psycopg
    from servicios.asistente import voz
    from servicios.asistente.nucleo import ModeloBedrock, Nucleo
    conn = psycopg.connect(args.url, autocommit=True)

    @contextmanager
    def conexion():
        yield conn
    nucleo = Nucleo(conexion, modelo=ModeloBedrock(), enviar_sms=lambda tel, codigo: True)
    print(f"Modelo: {nucleo.modelo.modelo}")
    tiempos = []
    for i in range(args.llamadas):
        atributos = {"telefono": "+56900000001", "contactId": f"latencia-{int(time.time())}-{i}"}
        for texto in TURNOS:
            evento = {"sessionId": atributos["contactId"], "inputTranscript": texto, "inputMode": "Speech",
                      "transcriptions": [{"transcriptionConfidence": 0.9}],
                      "sessionState": {"intent": {"name": "FallbackIntent"}, "sessionAttributes": atributos}}
            t0 = time.perf_counter()
            r = voz.atender(evento, nucleo.procesar)
            ms = (time.perf_counter() - t0) * 1000
            tiempos.append(ms)
            atributos = r["sessionState"]["sessionAttributes"]
            print(f"  {ms:7.0f} ms · {texto:<34} → {r['messages'][0]['content'][:90]}")
    tiempos.sort()
    p90 = tiempos[min(len(tiempos) - 1, int(round(0.9 * len(tiempos))) - 1)]
    print(f"\n{len(tiempos)} turnos · mediana {tiempos[len(tiempos) // 2]:.0f} ms · p90 {p90:.0f} ms (meta < 2500 ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
