"""Documentos de la Knowledge Base del equipo clínico (F0009). Puro: genera Markdown desde el repositorio, sin AWS.

- Un perfil por paciente con su solicitud, eventos en orden, mediciones con su rango, citas y la evolución de la
  propuesta. Solo datos hasta la fecha de corte (el RAG no "ve el futuro").
- Un resumen por especialidad y uno por box y mes.
- El diccionario de datos.

Minimización: los perfiles no llevan el nombre (aunque sea ficticio): el paciente se identifica por su ID. Cada
hecho lleva su referencia de origen ([EV-…], [CT-…]) para que la respuesta del RAG sea trazable.
Cada documento trae sus metadatos para los filtros de Bedrock (tipo, especialidad, estado, comuna, id_paciente).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from priorizacion import reglas as R
from priorizacion.datos import Repositorio
from priorizacion.motor import evaluar

from ..comun import diccionario

VERSION_PLANTILLA = "kb-v1"
ESTADO_ACTIVO = "en_espera"


@dataclass
class Documento:
    tipo: str                 # perfil_paciente | resumen_especialidad | resumen_box_mes | diccionario
    clave: str                # id_paciente, especialidad, BOX-01/2026-06, datos
    ruta: str                 # ruta relativa dentro de kb/equipo/
    contenido: str
    metadatos: dict = field(default_factory=dict)
    id_paciente: str | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.contenido.encode("utf-8")).hexdigest()

    def metadata_json(self) -> str:
        """El archivo <documento>.metadata.json que lee Bedrock para los filtros."""
        return json.dumps({"metadataAttributes": self.metadatos}, ensure_ascii=False)


def _slug(texto: str) -> str:
    reemplazos = str.maketrans("áéíóúñÁÉÍÓÚÑ ", "aeiounAEIOUN-")
    return "".join(c for c in texto.translate(reemplazos).lower() if c.isalnum() or c == "-")


def _num(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")


EVENTO = {"visita_urgencia": "Urgencia", "hospitalizacion": "Hospitalización", "examen_alterado": "Examen alterado",
          "cambio_farmaco": "Cambio de fármaco", "control_aps": "Control en APS"}
CITA = {"asistio": "asistió", "no_asistio": "no asistió", "reprogramo": "reprogramó", "cancelo": "canceló"}


def _evolucion(serie: pd.DataFrame | None, id_solicitud: str) -> list[str]:
    """Las noches en que cambió el nivel propuesto, según la simulación nocturna."""
    if serie is None or serie.empty:
        return []
    s = serie[serie["id_solicitud"] == id_solicitud].sort_values("fecha")
    if s.empty:
        return []
    lineas, anterior = [], None
    for f in s.itertuples(index=False):
        if f.nivel_propuesto != anterior:
            desde = f"{anterior} → " if anterior else "inicio: "
            lineas.append(f"- {f.fecha}: {desde}{f.nivel_propuesto} ({f.motivo_principal})")
            anterior = f.nivel_propuesto
    return lineas


def perfil(repo: Repositorio, id_paciente: str, corte: date, serie: pd.DataFrame | None = None,
           decisiones: dict | None = None) -> Documento:
    sol = repo.solicitud_de_paciente(id_paciente)
    hist = repo.historias[id_paciente]
    r = evaluar(sol, hist, corte, (decisiones or {}).get(sol.id_solicitud))
    estado = ESTADO_ACTIVO if not r.excluido else ("fallecido" if sol.fecha_defuncion and sol.fecha_defuncion <= corte
                                                    else "atendido")
    lineas = [f"# Perfil del paciente {id_paciente}", "",
              f"Datos hasta la fecha de corte {corte.isoformat()} (lista de espera, eventos, mediciones y citas del "
              "HLF). Cada hecho lleva su referencia de origen entre corchetes.", "",
              "## Paciente", "",
              f"- Edad {sol.edad} · sexo {sol.sexo} · comuna {sol.comuna} · previsión {sol.prevision} · "
              f"nivel socioeconómico {sol.nivel_socioeconomico}"]
    if sol.fecha_defuncion and sol.fecha_defuncion <= corte:
        lineas.append(f"- Falleció el {sol.fecha_defuncion.isoformat()}")
    dias = (corte - sol.fecha_ingreso).days
    lineas += ["", f"## Solicitud {sol.id_solicitud}", "",
               f"- Especialidad {sol.especialidad} ({sol.sub_especialidad}) · diagnóstico {sol.cie10} {sol.diagnostico}",
               f"- Prioridad inicial {sol.prioridad_inicial} · ingreso a la lista {sol.fecha_ingreso.isoformat()} "
               f"({dias} días a la fecha de corte) · derivado desde {sol.origen_derivacion} [{sol.id_solicitud}]"]
    if r.excluido:
        lineas.append(f"- Fuera de la lista activa: {r.motivo_exclusion}")
    else:
        lineas.append(f"- Prioridad vigente {r.prioridad_vigente} · propuesta del sistema {r.nivel_propuesto} "
                      f"(puntaje de nivel {_num(r.puntaje_nivel)}) · motivo principal: {r.motivo_principal}")
        if r.alerta:
            lineas.append("- Alerta: " + "; ".join(r.motivos_alerta))
    if evol := _evolucion(serie, sol.id_solicitud):
        lineas += ["", "## Evolución de la propuesta (simulación noche a noche)", "", *evol]

    eventos = hist.eventos_hasta(corte)
    lineas += ["", f"## Eventos clínicos ({len(eventos)})", ""]
    lineas += [f"- {e.fecha.isoformat()} · {EVENTO.get(e.tipo, e.tipo)} · {e.subtipo} · {e.severidad} [{e.id_evento}]"
               for e in eventos] or ["- Sin eventos registrados durante la espera"]

    mediciones = hist.mediciones_hasta(corte)
    total = sum(len(v) for v in mediciones.values())
    lineas += ["", f"## Mediciones ({total})", ""]
    for tipo, lista in mediciones.items():
        if not lista:
            continue
        rango = R.RANGOS_NORMALES.get(tipo)
        lineas.append(f"### {R.NOMBRE_MEDICION.get(tipo, tipo)}"
                      + (f" (rango normal {_num(rango[0])}–{_num(rango[1])} {R.UNIDADES.get(tipo, '')})" if rango else ""))
        lineas += [f"- {m.fecha.isoformat()}: {_num(m.valor)} {m.unidad}{' (fuera de rango)' if m.fuera_de_rango else ''}"
                   f"{' (examen externo)' if m.origen == 'externa' else ''} [{m.ref}]" for m in lista]
    if not total:
        lineas.append("- Sin mediciones")

    citas = hist.citas_hasta(corte)
    lineas += ["", f"## Citas de especialidad ({len(citas)})", ""]
    lineas += [f"- {c.fecha.isoformat()} · {c.especialidad} · {c.id_box} · {CITA.get(c.estado, c.estado)}"
               + (f" ({int(c.minutos)} min)" if c.minutos and c.estado == "asistio" else "") + f" [{c.id_cita}]"
               for c in citas] or ["- Sin citas"]

    meta = {"tipo": "perfil_paciente", "id_paciente": id_paciente, "id_solicitud": sol.id_solicitud,
            "especialidad": sol.especialidad, "estado": estado, "comuna": sol.comuna,
            "prioridad_inicial": sol.prioridad_inicial, "fecha_corte": corte.isoformat()}
    if not r.excluido:
        meta.update(prioridad_vigente=r.prioridad_vigente, nivel_propuesto=r.nivel_propuesto)
    return Documento("perfil_paciente", id_paciente, f"perfiles/{id_paciente}.md", "\n".join(lineas) + "\n", meta,
                     id_paciente)


def resumen_especialidad(repo: Repositorio, especialidad: str, corte: date, decisiones: dict | None = None) -> Documento:
    activas = [s for s in repo.activas(corte) if s.especialidad == especialidad]
    resultados = [(s, evaluar(s, repo.historias[s.id_paciente], corte, (decisiones or {}).get(s.id_solicitud)))
                  for s in activas]
    dias = sorted((corte - s.fecha_ingreso).days for s in activas)
    lineas = [f"# Resumen de {especialidad}", "",
              f"Lista de espera de {especialidad} a la fecha de corte {corte.isoformat()}.", "",
              f"- Solicitudes en espera: {len(activas)}"]
    if activas:
        for campo, nombre in (("prioridad_vigente", "Prioridad vigente"), ("nivel_propuesto", "Nivel propuesto")):
            conteo = pd.Series([getattr(r, campo) for _, r in resultados]).value_counts()
            lineas.append(f"- {nombre}: " + ", ".join(f"{n} {conteo.get(n, 0)}" for n in ("alta", "media", "baja")))
        lineas += [f"- Con alerta clínica: {sum(r.alerta for _, r in resultados)}",
                   f"- Propuestas que suben: {sum(r.cambio == 'sube' for _, r in resultados)} · que bajan: "
                   f"{sum(r.cambio == 'baja' for _, r in resultados)}",
                   f"- Días de espera: mediana {dias[len(dias) // 2]}, máximo {dias[-1]}"]
        graves = [(s, e) for s in activas for e in repo.historias[s.id_paciente].eventos_hasta(corte)
                  if e.severidad == "grave" and (corte - e.fecha).days <= 30]
        lineas.append(f"- Eventos graves en los últimos 30 días: {len(graves)}"
                      + (" (" + ", ".join(f"{s.id_paciente} [{e.id_evento}]" for s, e in graves[:15]) + ")" if graves else ""))
        alta = sorted((r for _, r in resultados if r.nivel_propuesto == "alta"), key=lambda r: -r.puntaje)[:10]
        if alta:
            lineas += ["", "## Solicitudes con propuesta alta (mayor puntaje primero)", ""]
            lineas += [f"- {r.id_paciente} [{r.id_solicitud}]: {r.motivo_principal}" for r in alta]
    meta = {"tipo": "resumen_especialidad", "especialidad": especialidad, "fecha_corte": corte.isoformat()}
    return Documento("resumen_especialidad", especialidad, f"resumenes/especialidad/{_slug(especialidad)}.md",
                     "\n".join(lineas) + "\n", meta)


def resumenes_box_mes(repo: Repositorio, corte: date) -> list[Documento]:
    agenda = repo.tablas["agenda"].copy()
    agenda = agenda[pd.to_datetime(agenda["fecha"]).dt.date <= corte]
    if agenda.empty:
        return []
    agenda["mes"] = pd.to_datetime(agenda["fecha"]).dt.strftime("%Y-%m")
    citas = repo.tablas["citas"].copy()
    citas = citas[pd.to_datetime(citas["fecha_cita"]).dt.date <= corte]
    citas["mes"] = pd.to_datetime(citas["fecha_cita"]).dt.strftime("%Y-%m")
    docs = []
    for (box, mes), g in agenda.groupby(["id_box", "mes"]):
        cap, usados = int(g["capacidad_cupos"].sum()), int(g["cupos_usados"].sum())
        c = citas[(citas["id_box"] == box) & (citas["mes"] == mes)]
        estados = c["estado_cita"].value_counts()
        especialidad = g["especialidad"].iloc[0]
        lineas = [f"# Box {box} · {mes}", "",
                  f"Uso del box {box} ({especialidad}) en {mes}, con datos hasta {corte.isoformat()}.", "",
                  f"- Días con bloque: {len(g)} · cupos ofrecidos {cap} · usados {usados} "
                  f"({_num(100 * usados / cap) if cap else 0} % de ocupación)",
                  f"- Sobretiempo: total {int(g['minutos_sobretiempo'].sum())} min · promedio por día "
                  f"{_num(g['minutos_sobretiempo'].mean())} min",
                  f"- Citas registradas: {len(c)} (" + ", ".join(f"{CITA.get(k, k)} {v}" for k, v in estados.items()) + ")"
                  if len(c) else "- Sin citas registradas"]
        meta = {"tipo": "resumen_box_mes", "id_box": box, "mes": mes, "especialidad": especialidad,
                "fecha_corte": corte.isoformat()}
        docs.append(Documento("resumen_box_mes", f"{box}/{mes}", f"resumenes/box/{box}_{mes}.md",
                              "\n".join(lineas) + "\n", meta))
    return docs


def generar(repo: Repositorio, corte: date, serie: pd.DataFrame | None = None,
            decisiones: dict | None = None) -> list[Documento]:
    """Todos los documentos de la KB del equipo clínico a la fecha de corte."""
    pacientes = sorted({s.id_paciente for s in repo.solicitudes.values() if s.fecha_ingreso <= corte})
    docs = [perfil(repo, pid, corte, serie, decisiones) for pid in pacientes]
    docs += [resumen_especialidad(repo, e, corte, decisiones)
             for e in sorted({s.especialidad for s in repo.solicitudes.values()})]
    docs += resumenes_box_mes(repo, corte)
    docs.append(Documento("diccionario", "datos", "diccionario/datos.md", diccionario.como_markdown(corte.isoformat()),
                          {"tipo": "diccionario", "fecha_corte": corte.isoformat()}))
    return docs
