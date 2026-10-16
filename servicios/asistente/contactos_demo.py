"""Contactos y consentimientos de demo (F0010): el dataset no trae teléfonos.

    python -m servicios.asistente.contactos_demo                         # números ficticios para los 6 casos
    python -m servicios.asistente.contactos_demo --telefono PAC-HLF-00002=+56912345678   # un número real del equipo

Por defecto registra números ficticios (+56 9 0000 000N, no asignados) para los seis pacientes de referencia, con
consentimiento para el asistente, consulta de estado y recordatorios por WhatsApp y voz. Con --telefono se registra
el número de una persona del equipo (con su permiso) para probar WhatsApp o la llamada real. Idempotente. Los
números se guardan cifrados (KMS) y con su HMAC; nunca se imprimen completos.
"""
from __future__ import annotations

import argparse
import sys

from ..comun import cifrado

CASOS = ["PAC-HLF-00002", "PAC-HLF-00001", "PAC-HLF-00028", "PAC-HLF-00020", "PAC-HLF-00032", "PAC-HLF-00009"]
FINALIDADES = ("asistente_ia", "consulta_estado", "recordatorios")
CANALES = ("whatsapp", "voz")


def numero_ficticio(i: int) -> str:
    return f"+5690000000{i + 1}"


def registrar(conn, id_paciente: str, telefono: str, tipos=("whatsapp", "movil")) -> None:
    e164 = cifrado.normalizar(telefono)
    valor_hash, blob = cifrado.hmac_telefono(e164), cifrado.cifrar(e164)
    with conn.transaction():
        for tipo in tipos:
            conn.execute(
                "INSERT INTO canal.contacto_paciente (id_paciente, tipo, valor_cifrado, valor_hash, ultimos_digitos, "
                "es_principal, verificado_en) VALUES (%s, %s, %s, %s, %s, NOT EXISTS (SELECT 1 FROM "
                "canal.contacto_paciente WHERE id_paciente = %s AND tipo = %s AND es_principal AND vigente), now()) "
                "ON CONFLICT (id_paciente, tipo, valor_hash) DO NOTHING",
                (id_paciente, tipo, blob, valor_hash, e164[-4:], id_paciente, tipo))
        for canal in CANALES:
            for finalidad in FINALIDADES:
                conn.execute(
                    "INSERT INTO canal.consentimiento (id_paciente, canal, finalidad, otorgado, medio_registro, "
                    "registrado_por) SELECT %s, %s, %s, true, 'presencial', 'sistema' WHERE NOT EXISTS ("
                    "SELECT 1 FROM canal.v_consentimiento_vigente WHERE id_paciente = %s AND canal = %s "
                    "AND finalidad = %s AND otorgado)", (id_paciente, canal, finalidad, id_paciente, canal, finalidad))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m servicios.asistente.contactos_demo", description=__doc__.split("\n")[0])
    p.add_argument("--telefono", action="append", default=[], metavar="PAC=E164",
                   help="Registra el número de una persona del equipo para un paciente (repetible)")
    args = p.parse_args(argv)
    from db.conexion import conectar
    with conectar() as conn:
        for i, pid in enumerate(CASOS):
            registrar(conn, pid, numero_ficticio(i))
            print(f"  {pid}: número ficticio *** {numero_ficticio(i)[-4:]}")
        for par in args.telefono:
            pid, _, tel = par.partition("=")
            registrar(conn, pid.strip(), tel.strip())
            print(f"  {pid.strip()}: número del equipo *** {cifrado.normalizar(tel)[-4:]}")
        conn.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
