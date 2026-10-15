"""Inferencia simulada (por defecto) e instalación del cliente usado por copiloto.py.

``ClienteSimulado`` imita la interfaz mínima de ``anthropic.Anthropic`` que usan
``copiloto.analizar_alerta`` y ``auditoria.log_llamada``. No abre conexiones de red y
solo reempaqueta la salida del motor de reglas: no agrega reglas, cifras ni
interpretación clínica.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import copiloto

MODELO_SIMULADO = "simulado-local"
PREFIJO = ("[SIMULADO] Generado sin modelo de IA a partir del motor de reglas; "
           "no contiene interpretación clínica.")


def instalar_cliente(cliente: Any) -> None:
    """copiloto.analizar_alerta resuelve copiloto._cliente() en cada llamada."""
    copiloto._cliente = lambda: cliente


def origen_inferencia(analisis: dict | None) -> str:
    modelo = ((analisis or {}).get("_meta") or {}).get("model")
    return "simulada" if modelo == MODELO_SIMULADO else "real"


class _Uso:
    def model_dump(self) -> dict:
        return {"input_tokens": 0, "output_tokens": 0}


def _bloque(nombre: str, entrada: dict, n: int) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=f"toolu_simulado_{n}", name=nombre, input=entrada)


def _respuesta(bloque: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(content=[bloque], stop_reason="tool_use", model=MODELO_SIMULADO,
                           usage=_Uso(), _request_id=None)


def _alerta_de(mensajes: list[dict]) -> dict:
    texto = mensajes[0]["content"]
    return json.loads(texto.split("\n\n", 1)[1])


def _tool_results(mensajes: list[dict]) -> list[dict]:
    salida = []
    for m in mensajes:
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            salida += [b for b in m["content"]
                       if isinstance(b, dict) and b.get("type") == "tool_result"]
    return salida


def _descripcion(e: dict) -> str:
    """Reformatea campos del registro sin interpretarlos."""
    partes = [str(e.get("fuente", ""))]
    for k in ("tipo", "subtipo", "severidad", "especialidad", "estado"):
        if e.get(k):
            partes.append(str(e[k]))
    if e.get("valor") is not None:
        partes.append(f"{e['valor']} {e.get('unidad') or ''}".strip())
    return " · ".join(partes)


class _Mensajes:
    def __init__(self) -> None:
        self._n = 0

    def create(self, **kw: Any) -> SimpleNamespace:
        self._n += 1
        mensajes = kw["messages"]
        alerta = _alerta_de(mensajes)
        resultados = _tool_results(mensajes)

        if not resultados and "tool_choice" not in kw:
            return _respuesta(_bloque("obtener_linea_tiempo",
                                      {"pid": alerta["id_paciente"]}, self._n))

        eventos: list[dict] = []
        for r in resultados:
            try:
                datos = json.loads(r.get("content") or "{}")
            except json.JSONDecodeError:
                continue
            if isinstance(datos, dict):
                eventos += datos.get("eventos") or []

        hallazgos = [{"hallazgo": m["motivo"], "tipo": "documentado",
                      "registro_ids": list(m.get("registro_ids") or [])}
                     for m in alerta.get("motivos") or []]
        hallazgos += [{"hallazgo": f"Bandera roja del motor de reglas: {b['bandera']}",
                       "tipo": "documentado", "registro_ids": list(b.get("registro_ids") or [])}
                      for b in alerta.get("banderas_rojas") or []]

        registro = {
            "resumen": f"{PREFIJO} El motor de reglas calculó prioridad "
                       f"'{alerta.get('prioridad_calculada')}' (tipo de aviso: "
                       f"{alerta.get('tipo')}).",
            "relacion_con_derivacion": "Simulación: no se evalúa la relación con la derivación.",
            "linea_tiempo_relevante": [
                {"fecha": e.get("fecha"), "descripcion": _descripcion(e),
                 "registro_id": e["registro_id"]}
                for e in eventos[-5:] if e.get("registro_id")],
            "hallazgos": hallazgos,
            "prioridad_sugerida": alerta.get("prioridad_calculada"),
            "acuerdo_con_motor_reglas": True,
            "justificacion": "Simulación: repite la prioridad calculada por el motor de reglas.",
            "confianza": "baja",
            "acciones_sugeridas": ["Revisión profesional del aviso"],
            "datos_faltantes": ["Inferencia simulada: sin análisis clínico"],
            "inconsistencias_datos": [
                {"descripcion": i.get("descripcion", ""),
                 "registro_ids": list(i.get("registro_ids") or [])}
                for i in alerta.get("inconsistencias") or []],
            "nota_preconsulta": f"{PREFIJO} Revisar los motivos del motor de reglas citados.",
        }
        return _respuesta(_bloque("registrar_analisis", registro, self._n))


class ClienteSimulado:
    def __init__(self) -> None:
        self.messages = _Mensajes()
