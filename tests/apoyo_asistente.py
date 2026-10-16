"""Apoyo de las pruebas del asistente (F0010, F0011): base PostgreSQL preparada y modelo simulado."""
import json
import os

URL = os.environ.get("HLF_TEST_DATABASE_URL")


class ModeloGuion:
    """Decide la herramienta por palabras clave y redacta con lo que devuelve; registra cada llamada."""
    modelo = "simulado"

    def __init__(self):
        self.llamadas = 0

    def converse(self, **pedido):
        self.llamadas += 1
        ultimo = pedido["messages"][-1]["content"]
        if "toolResult" in ultimo[0]:
            datos = json.loads(ultimo[0]["toolResult"]["content"][0]["text"])
            return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [
                {"text": "RESULTADO " + json.dumps(datos, ensure_ascii=False)}]}}}
        texto = ultimo[0].get("text", "").lower().split("\n")[-1]
        herramienta = next((h for clave, h in (("lugar", "estado_en_lista"), ("cita", "mis_citas"),
                                               ("registros", "mis_registros"), ("confirmo", "confirmar_asistencia"),
                                               ("persona", "hablar_con_persona")) if clave in texto), None)
        if not herramienta:
            return {"stopReason": "end_turn", "output": {"message": {"role": "assistant",
                                                                      "content": [{"text": "¿En qué le ayudo?"}]}}}
        entrada = {"id_paciente": "PAC-HLF-00001"} if "pac-hlf-00001" in texto else {}       # intenta pedir a otra persona
        return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": f"t{self.llamadas}", "name": herramienta, "input": entrada}}]}}}


def preparar():
    """Base con todos los esquemas, el dataset, los contactos de demo y una estimación publicable de IC-HLF-00002."""
    import psycopg
    from db import carga, conexion, esquema
    from priorizacion.config import DATA_DIR
    from servicios.asistente import contactos_demo
    with conexion.conectar(URL) as c:
        carga.borrar(c, "todos")
        with c.transaction():
            for nombre in esquema.ESQUEMAS:
                esquema.aplicar(c, nombre)
            esquema.aplicar_permisos(c, "canal")
        carga.cargar(c, DATA_DIR, progreso=lambda *_: None)
        for i, pid in enumerate(contactos_demo.CASOS):
            contactos_demo.registrar(c, pid, contactos_demo.numero_ficticio(i))
        c.execute("INSERT INTO priorizacion.estimacion_espera (id_solicitud, fecha_calculo, prioridad_vigente, "
                  "posicion_vigente, total_cola, dias_estimados_min, dias_estimados_max, confianza, metodo, "
                  "version_metodo, publicable) VALUES ('IC-HLF-00002', priorizacion.fecha_corte(), 'baja', 3, 64, "
                  "14, 35, 'media', 'throughput_8_semanas', 'v1', true)")
        c.commit()
    return psycopg.connect(URL, autocommit=True)
