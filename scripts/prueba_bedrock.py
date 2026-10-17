"""Prueba de humo de las explicaciones con IA contra Amazon Bedrock real (F0008).

Explica los seis casos de referencia (docs/casos-ejemplo.md) con uno o más modelos de Bedrock y resume cuántos
textos acepta la validación, los tokens y la latencia. Solo envía los factores de cada propuesta (sin nombre ni RUT).

    python scripts/prueba_bedrock.py                                    # modelo de BEDROCK_MODEL_ID
    python scripts/prueba_bedrock.py --modelos us.anthropic.claude-haiku-4-5-20251001-v1:0 us.anthropic.claude-sonnet-4-5-20250929-v1:0
    python scripts/prueba_bedrock.py --corte 2026-08-10 --mostrar        # imprime cada texto

Requiere credenciales de AWS con permiso de bedrock:InvokeModel sobre el perfil (y el guardrail, si se usa).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

CASOS = {"PAC-HLF-00002": "Deterioro agudo", "PAC-HLF-00001": "Deterioro progresivo", "PAC-HLF-00028": "Mejora",
         "PAC-HLF-00020": "Inasistencia", "PAC-HLF-00032": "Estable / atendido", "PAC-HLF-00009": "Fallecido en espera"}


class _Captura(logging.Handler):
    def __init__(self):
        super().__init__()
        self.eventos: list[dict] = []

    def emit(self, record):
        try:
            self.eventos.append(json.loads(record.getMessage()))
        except ValueError:
            pass


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--modelos", nargs="+", help="Perfiles de inferencia de Bedrock (por defecto, BEDROCK_MODEL_ID)")
    p.add_argument("--corte", default="2026-10-13")
    p.add_argument("--mostrar", action="store_true", help="Imprime cada texto aceptado")
    args = p.parse_args(argv)
    os.environ["LLM_PROVEEDOR"] = "bedrock"
    from priorizacion import config
    from priorizacion import explicacion as X
    from priorizacion.datos import Repositorio
    from priorizacion.motor import evaluar
    config.LLM_PROVEEDOR = "bedrock"

    captura = _Captura()
    X.log.addHandler(captura)
    X.log.setLevel(logging.INFO)
    repo = Repositorio.crear()
    corte = date.fromisoformat(args.corte)
    resumen = []
    for modelo in args.modelos or [config.BEDROCK_MODEL_ID]:
        config.BEDROCK_MODEL_ID = modelo
        print(f"\n== {modelo} (corte {corte}) ==")
        for pid, patron in CASOS.items():
            sol = repo.solicitud_de_paciente(pid)
            r = evaluar(sol, repo.historias[pid], corte)
            if r.excluido:
                print(f"  {pid:<14} {patron:<22} fuera de la lista ({r.motivo_exclusion}): no se llama al modelo")
                continue
            e = X.explicacion_llm(r)
            ev = captura.eventos[-1] if captura.eventos else {}
            resumen.append({"modelo": modelo, **ev})
            print(f"  {pid:<14} {patron:<22} {ev.get('resultado', '?'):<10} "
                  f"{ev.get('tokens_entrada')}→{ev.get('tokens_salida')} tokens, {ev.get('latencia_ms')} ms"
                  + (f"  · {ev['motivo']}" if ev.get("motivo") else ""))
            if args.mostrar and e.fuente == "bedrock":
                print(f"      {e.texto}\n")
    print("\nResumen por modelo:")
    for modelo in dict.fromkeys(x["modelo"] for x in resumen):
        filas = [x for x in resumen if x["modelo"] == modelo]
        aceptados = sum(x.get("resultado") == "aceptado" for x in filas)
        lat = sorted(x["latencia_ms"] for x in filas if x.get("latencia_ms") is not None)
        tok_in = sum(x.get("tokens_entrada") or 0 for x in filas)
        tok_out = sum(x.get("tokens_salida") or 0 for x in filas)
        print(f"  {modelo}: {aceptados}/{len(filas)} aceptados · latencia mediana "
              f"{lat[len(lat) // 2] if lat else '—'} ms · tokens {tok_in} entrada / {tok_out} salida")
    return 0


if __name__ == "__main__":
    sys.exit(main())
