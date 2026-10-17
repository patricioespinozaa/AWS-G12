"""Herramientas del asistente (F0010). Cada una corre con el rol hlf_asistente_ia y la conversación de la sesión
(`SET LOCAL canal.id_conversacion`): solo puede ver al paciente verificado de ESA conversación, aunque el modelo pida
otra cosa. Ninguna recibe un id de paciente como argumento.

Cada herramienta devuelve (resultado para el modelo, divulgaciones). Las divulgaciones se registran en
canal.divulgacion junto al turno del asistente: qué dato, de qué vista y de qué fila salió.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

FAQ = (Path(__file__).parent / "faq" / "preguntas_frecuentes.md").read_text(encoding="utf-8")


@dataclass
class Divulgacion:
    tipo_dato: str
    vista_fuente: str
    ref_fuente: str
    valor_informado: str


@dataclass
class Resultado:
    datos: dict
    divulgaciones: list[Divulgacion] = field(default_factory=list)


def _v(x):
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, date):
        return x.isoformat()
    return x


# Nombre → (descripción, esquema de entrada, verificación mínima, intención de canal.intencion)
CATALOGO = {
    "estado_en_lista": ("Prioridad vigente, posición en la lista y rango estimado de espera del paciente verificado.",
                        {}, "reforzada", "consultar_prioridad"),
    "mis_citas": ("Citas próximas y pasadas del paciente verificado.", {}, "basica", "consultar_citas"),
    "mis_registros": ("Qué registros clínicos tiene el hospital del paciente verificado (eventos, mediciones, "
                      "exámenes externos validados). Solo informa qué hay; no lo interpreta.", {}, "reforzada",
                      "consultar_registros"),
    "confirmar_asistencia": ("Registra que el paciente confirma que asistirá a su próxima cita.", {}, "basica",
                             "confirmar_asistencia"),
    "no_puedo_asistir": ("Registra que el paciente no podrá asistir a su próxima cita.",
                         {"motivo": {"type": "string", "description": "Motivo, si lo dio"}}, "basica", "no_puede_asistir"),
    "reportar_sintoma": ("Registra un síntoma nuevo que informa el paciente, para que el equipo lo revise. No es para "
                         "síntomas de alarma (esos se derivan automáticamente).",
                         {"descripcion": {"type": "string"}}, "basica", "reportar_sintoma"),
    "enviar_examen": ("Registra un examen hecho fuera del hospital que el paciente informa, como pendiente de validación.",
                      {"tipo_medicion": {"type": "string", "enum": ["HbA1c", "PHQ9", "escala_dolor_eva", "glicemia",
                                                                     "peak_flow", "presion_diastolica",
                                                                     "presion_sistolica", "saturacion_o2"]},
                       "valor": {"type": "number"}, "fecha_examen": {"type": "string", "description": "AAAA-MM-DD"},
                       "lugar": {"type": "string"}}, "basica", "enviar_examen"),
    "hablar_con_persona": ("Deriva la conversación a una persona del equipo del hospital.",
                           {"motivo": {"type": "string", "enum": ["pide_persona", "pregunta_clinica", "reclamo",
                                                                  "dato_sensible"]}}, "ninguna", "hablar_con_persona"),
    "preguntas_frecuentes": ("Información general del hospital y de la lista de espera (qué llevar, horarios, cómo "
                             "cancelar, cómo se protegen los datos). No requiere verificación.",
                             {"pregunta": {"type": "string"}}, "ninguna", None),
}
REQUERIDOS = {"reportar_sintoma": ["descripcion"], "enviar_examen": ["tipo_medicion", "valor", "fecha_examen"],
              "preguntas_frecuentes": ["pregunta"]}


def especificaciones(nombres: list[str]) -> list[dict]:
    """toolSpec de Converse para las herramientas disponibles en este turno."""
    salida = []
    for n in nombres:
        desc, props, _, _ = CATALOGO[n]
        salida.append({"toolSpec": {"name": n, "description": desc, "inputSchema": {"json": {
            "type": "object", "properties": props, "required": REQUERIDOS.get(n, [])}}}})
    return salida


def estado_en_lista(conn, args) -> Resultado:
    filas = conn.execute(
        "SELECT id_solicitud, especialidad, estado, prioridad_vigente, dias_en_espera, posicion_vigente, total_cola, "
        "dias_estimados_min, dias_estimados_max, confianza_estimacion, fecha_estimacion, fecha_corte "
        "FROM canal.v_ia_estado_solicitud ORDER BY fecha_ingreso_lista").fetchall()
    if not filas:
        return Resultado({"solicitudes": [], "mensaje": "No hay solicitudes en lista de espera para informar."})
    solicitudes, divs = [], []
    for f in filas:
        s = {"especialidad": f[1], "estado": f[2], "prioridad_vigente": f[3], "dias_en_espera": f[4],
             "datos_al": _v(f[11])}
        divs += [Divulgacion("estado_solicitud", "canal.v_ia_estado_solicitud", f[0], f[2]),
                 Divulgacion("prioridad", "canal.v_ia_estado_solicitud", f[0], f[3])]
        if f[5] is not None:
            s.update(posicion=f[5], total_en_la_cola=f[6])
            divs.append(Divulgacion("posicion", "canal.v_ia_estado_solicitud", f"{f[0]}/{_v(f[10])}", f"{f[5]} de {f[6]}"))
        if f[7] is not None:
            s.update(dias_estimados_min=f[7], dias_estimados_max=f[8], confianza=f[9])
            divs.append(Divulgacion("tiempo_estimado", "canal.v_ia_estado_solicitud", f"{f[0]}/{_v(f[10])}",
                                    f"{f[7]} a {f[8]} días"))
        else:
            s["tiempo_estimado"] = "no disponible por este medio"
        solicitudes.append(s)
    return Resultado({"solicitudes": solicitudes, "recordatorio": "La posición no es una fecha garantizada de atención."},
                     divs)


def mis_citas(conn, args) -> Resultado:
    filas = conn.execute("SELECT ref_fuente, especialidad, id_box, fecha, hora_inicio, estado, temporalidad "
                         "FROM canal.v_ia_citas ORDER BY fecha DESC").fetchall()
    proximas = [f for f in filas if f[6] == "proxima"][-3:]
    pasadas = [f for f in filas if f[6] == "pasada"][:3]
    divs = [Divulgacion("cita_proxima" if f[6] == "proxima" else "cita_pasada", "canal.v_ia_citas", f[0],
                        f"{_v(f[3])} {f[1]} ({f[5]})") for f in proximas + pasadas]
    a_dict = lambda f: {"especialidad": f[1], "fecha": _v(f[3]), "hora": _v(f[4]) if f[4] else None,  # noqa: E731
                        "box": f[2], "estado": f[5]}
    return Resultado({"proximas": [a_dict(f) for f in sorted(proximas, key=lambda f: f[3])],
                      "ultimas_pasadas": [a_dict(f) for f in pasadas]}, divs)


def mis_registros(conn, args) -> Resultado:
    filas = conn.execute("SELECT tipo_registro, ref_fuente, fecha, categoria, descripcion, valor, unidad, sensible "
                         "FROM canal.v_ia_registros ORDER BY fecha DESC").fetchall()
    visibles = [f for f in filas if not f[7]][:10]
    sensibles = sum(1 for f in filas if f[7])
    divs = [Divulgacion("registro_clinico", "canal.v_ia_registros", f[1], f"{_v(f[2])} {f[4]}") for f in visibles]
    datos = {"registros": [{"tipo": f[0], "fecha": _v(f[2]), "categoria": f[3], "descripcion": f[4],
                            "valor": _v(f[5]), "unidad": f[6]} for f in visibles],
             "total": len(filas)}
    if sensibles:
        datos["registros_que_se_conversan_con_una_persona"] = sensibles
        datos["indicacion"] = ("Hay registros sensibles (hospitalizaciones, eventos graves o salud mental) que no se "
                               "informan por este medio: ofrece derivar a una persona.")
    return Resultado(datos, divs)


def _mensaje(conn, tipo: str, detalle: str, canal_origen: str, estado: str) -> str:
    fila = conn.execute(
        "INSERT INTO canal.mensaje_paciente (id_paciente, id_conversacion, canal_origen, fecha, tipo, detalle, estado) "
        "SELECT canal.paciente_verificado('basica'), nullif(current_setting('canal.id_conversacion'), '')::bigint, "
        "%s, priorizacion.fecha_corte(), %s, %s, %s RETURNING id_mensaje", (canal_origen, tipo, detalle[:500], estado)
    ).fetchone()
    return str(fila[0])


def confirmar_asistencia(conn, args, canal_origen="whatsapp") -> Resultado:
    _mensaje(conn, "confirma_asistencia", "", canal_origen, "registrado")
    return Resultado({"registrado": True, "mensaje": "Quedó registrada la confirmación de asistencia."})


def no_puedo_asistir(conn, args, canal_origen="whatsapp") -> Resultado:
    _mensaje(conn, "no_puede_asistir", args.get("motivo", ""), canal_origen, "registrado")
    return Resultado({"registrado": True, "mensaje": "Quedó registrado que no podrá asistir; el equipo podrá reasignar el cupo."})


def reportar_sintoma(conn, args, canal_origen="whatsapp") -> Resultado:
    _mensaje(conn, "sintoma_sin_alarma", args.get("descripcion", ""), canal_origen, "pendiente")
    return Resultado({"registrado": True, "mensaje": "El síntoma quedó registrado para que el equipo lo revise."})


def enviar_examen(conn, args, canal_origen="whatsapp") -> Resultado:
    try:
        fecha = date.fromisoformat(str(args.get("fecha_examen")))
        valor = float(args.get("valor"))
    except (TypeError, ValueError):
        return Resultado({"registrado": False, "mensaje": "Falta la fecha (AAAA-MM-DD) o el valor del examen."})
    origen = "whatsapp" if canal_origen in ("whatsapp", "voz") else "web"
    conn.execute(
        "INSERT INTO canal.evidencia_externa (id_paciente, id_conversacion, canal_origen, fecha_examen, tipo_medicion, "
        "valor, lugar, fecha_recepcion) SELECT canal.paciente_verificado('basica'), "
        "nullif(current_setting('canal.id_conversacion'), '')::bigint, %s, least(%s::date, priorizacion.fecha_corte()), "
        "%s, %s, %s, priorizacion.fecha_corte()",
        (origen, fecha, args.get("tipo_medicion"), valor, (args.get("lugar") or "")[:120]))
    return Resultado({"registrado": True, "mensaje": "El examen quedó pendiente de revisión por el equipo; cuenta para la "
                                                     "prioridad solo cuando lo validan."})


def hablar_con_persona(conn, args) -> Resultado:
    motivo = args.get("motivo") if args.get("motivo") in ("pide_persona", "pregunta_clinica", "reclamo", "dato_sensible") \
        else "pide_persona"
    conn.execute("INSERT INTO canal.derivacion_humana (id_conversacion, motivo, urgencia) VALUES "
                 "(nullif(current_setting('canal.id_conversacion'), '')::bigint, %s, 'normal')", (motivo,))
    return Resultado({"derivado": True, "mensaje": "Una persona del equipo del hospital tomará el caso."})


def preguntas_frecuentes(conn, args, buscar=None) -> Resultado:
    """Con la KB del paciente configurada, los fragmentos más cercanos; si no, el documento completo (es corto)."""
    if buscar is not None:
        try:
            fragmentos = buscar(args.get("pregunta", ""))
            if fragmentos:
                return Resultado({"fragmentos": fragmentos})
        except Exception:  # noqa: BLE001 — sin KB, el documento local
            pass
    return Resultado({"documento": FAQ})


EJECUTORES = {"estado_en_lista": estado_en_lista, "mis_citas": mis_citas, "mis_registros": mis_registros,
              "confirmar_asistencia": confirmar_asistencia, "no_puedo_asistir": no_puedo_asistir,
              "reportar_sintoma": reportar_sintoma, "enviar_examen": enviar_examen,
              "hablar_con_persona": hablar_con_persona, "preguntas_frecuentes": preguntas_frecuentes}
CON_CANAL = {"confirmar_asistencia", "no_puedo_asistir", "reportar_sintoma", "enviar_examen"}
