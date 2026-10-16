"""Bandeja HLF (U3): demo local en Streamlit. Solo presenta; la lógica vive en ``hlf_priorizacion.bandeja``.

Ejecución (desde la raíz del repositorio): ``uv run streamlit run app/bandeja.py``.

- B1: solo lectura de ``salidas/``; nunca ejecuta el lote ni el copiloto y no llama a Bedrock. El único
  archivo que escribe es ``salidas/decisiones/decisiones.jsonl`` (más su evento de auditoría).
- B7: los textos del modelo y de los datos se muestran como texto plano (sin ``unsafe_allow_html``); los
  errores se muestran con un mensaje genérico y el detalle va a los logs sin datos clínicos.
- Rutas: ``HLF_SALIDAS`` y ``HLF_DATOS`` (por defecto ``salidas/`` y ``data/dataset_hlf_ambulatorio/``).
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable, Sequence
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from hlf_priorizacion.bandeja.cambios import CambioEntreCortes, comparar
from hlf_priorizacion.bandeja.datos import (
    ADVERTENCIA_EQUIDAD,
    ANALISIS_PENDIENTE,
    AVISO_DEMO,
    ROTULO_COPILOTO,
    VERSION_REGLAS,
    CorteSinPropuestas,
    DatosCorte,
    ResultadoContexto,
    cargar_corte,
    cargar_repositorio,
    cobertura,
    comando_copiloto,
    comando_lote,
    cortes_disponibles,
    reconstruir_contexto,
    rutas,
)
from hlf_priorizacion.bandeja.decisiones import (
    MAX_MOTIVO,
    OPCIONES,
    DecisionSinAuditoria,
    ErrorDecision,
    crear_decision,
    estados_del_corte,
    guardar_decision,
    historial,
    leer_decisiones,
    niveles_ajuste,
)
from hlf_priorizacion.bandeja.filas import (
    ESTADOS_DECISION,
    TIPOS_RESULTADO,
    Filtros,
    construir_filas,
    contador,
    filtrar,
    ordenar,
)
from hlf_priorizacion.logs import configurar_logging
from hlf_priorizacion.modelos import NIVELES, Decision, Evaluacion
from hlf_priorizacion.repositorio.contexto import Repositorio

_APP = Path(__file__).resolve().parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))
from config_demo import MEDICOS  # noqa: E402

PESTANAS = ("Bandeja", "Detalle", "¿Qué cambió?", "Cobertura")
NOMBRES_MEDICO = {m.id: m.nombre for m in MEDICOS}
ETIQUETA_NIVEL = {"critica": "🔴 crítica", "alta": "🟠 alta", "media": "🟡 media", "baja": "🟢 baja"}
ETIQUETA_ANALISIS = {"si": "✅ sí", "no": "— no", "fallido": "❌ fallido"}
ETIQUETA_DECISION = {
    "pendiente": "⏳ pendiente",
    "aceptada": "✔ aceptada",
    "ajustada": "✎ ajustada",
    "rechazada": "✖ rechazada",
}
ETIQUETA_OPCION = {"aceptar": "Aceptar", "ajustar": "Ajustar", "rechazar": "Rechazar"}
MENSAJE_ERROR_LECTURA = "No se pudieron leer las salidas. El detalle quedó en los logs."
_RE_MARKDOWN = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


# --------------------------------------------------------------------------- formato


def plano(texto: str) -> str:
    """Texto de datos o del modelo como texto literal en Markdown (sin formato ni HTML)."""
    return _RE_MARKDOWN.sub(r"\\\1", texto)


def nivel(n: str | None) -> str:
    return ETIQUETA_NIVEL[n] if n else "— exclusión"


def cambio_nivel(inicial: str, propuesto: str | None, magnitud: int) -> str:
    flecha = f"▲ sube {magnitud}" if magnitud > 0 else f"▼ baja {-magnitud}" if magnitud < 0 else "= sin cambio"
    return f"{nivel(inicial)} → {nivel(propuesto)}  {flecha if propuesto else ''}".rstrip()


def puntaje(p: float | None) -> str:
    return "—" if p is None else f"{p:.2f}"


# --------------------------------------------------------------------------- caché y E/S


@st.cache_resource
def _logger() -> logging.Logger:
    return configurar_logging()


@st.cache_data(show_spinner=False, ttl=60)
def _cortes(raiz: str) -> list[date]:
    return cortes_disponibles(Path(raiz), VERSION_REGLAS)


@st.cache_data(show_spinner="Leyendo las salidas del corte…")
def _corte(raiz: str, corte: str, version: str) -> DatosCorte:
    return cargar_corte(Path(raiz), date.fromisoformat(corte), version)


@st.cache_resource(show_spinner="Cargando el dataset para la línea de tiempo…")
def _repositorio(datos: str) -> Repositorio | None:
    if not (Path(datos) / "perfiles.json").is_file():
        return None
    return cargar_repositorio(Path(datos))


@st.cache_data(show_spinner=False)
def _decisiones(raiz: str) -> list[Decision]:
    return leer_decisiones(Path(raiz))


def _seguro[T](funcion: Callable[[], T], etapa: str, corte: date | None = None) -> T | None:
    """Ejecuta una lectura; ante un error muestra un mensaje genérico y registra solo tipo y etapa (B7.2)."""
    try:
        return funcion()
    except CorteSinPropuestas:
        raise
    except Exception as e:
        campos: dict[str, Any] = {"etapa": etapa, "tipo_error": type(e).__name__}
        if corte is not None:
            campos["fecha_corte"] = corte.isoformat()
        _logger().error("error en la bandeja", extra={"campos": campos})
        st.error(MENSAJE_ERROR_LECTURA)
        return None


def _contexto(datos: Path, ev: Evaluacion) -> ResultadoContexto:
    repo = _seguro(lambda: _repositorio(str(datos)), "dataset")
    if repo is None:
        return ResultadoContexto("contexto_no_disponible")
    return reconstruir_contexto(repo, ev)


# --------------------------------------------------------------------------- navegación


def _abrir(clave_tabla: str, ids: Sequence[str], corte: str | None = None) -> None:
    """Callback de selección de una tabla: abre el Detalle (en el corte ``corte`` si se indica)."""
    estado = st.session_state.get(clave_tabla)
    filas = list(estado["selection"]["rows"]) if estado else []
    if not filas:
        return
    if corte is not None:
        st.session_state["lateral-corte"] = corte
    st.session_state["detalle-solicitud"] = ids[filas[0]]
    st.session_state["app-pestana"] = "Detalle"


# --------------------------------------------------------------------------- barra lateral


def _lateral(cortes: list[date]) -> tuple[str, date | None]:
    with st.sidebar:
        st.header("Bandeja HLF")
        medico = st.selectbox(
            "Médico",
            ["", *NOMBRES_MEDICO],
            format_func=lambda i: NOMBRES_MEDICO.get(i, "— elija un médico —"),
            key="lateral-medico",
        )
        corte: date | None = None
        if cortes:
            opciones = [c.isoformat() for c in cortes]
            if st.session_state.get("lateral-corte") not in opciones:
                st.session_state["lateral-corte"] = opciones[0]
            corte = date.fromisoformat(st.selectbox("Fecha de corte", opciones, key="lateral-corte"))
        st.text(f"Versión de reglas: {VERSION_REGLAS}")
        st.caption(AVISO_DEMO)
    return medico or "", corte


# --------------------------------------------------------------------------- pestaña Bandeja


def _vista_bandeja(dc: DatosCorte, decisiones: list[Decision]) -> None:
    estados = estados_del_corte(decisiones, dc.corte, dc.version_reglas)
    filas = ordenar(
        construir_filas(
            dc.propuestas.values(),
            dc.especialidades,
            {i: dc.estado_analisis(i) for i in dc.propuestas},
            [i for i in dc.analisis if dc.marcas_equidad(i)],
            estados,
        )
    )
    if not dc.analisis:
        st.info(f"{ANALISIS_PENDIENTE} en este corte. Para generarlo: `{comando_copiloto(dc.corte)}`")

    c1, c2, c3, c4 = st.columns(4)
    especialidades = c1.multiselect(
        "Especialidad", sorted({f.especialidad for f in filas}), key="bandeja-filtro-especialidad"
    )
    niveles = c2.multiselect("Nivel propuesto", NIVELES, format_func=nivel, key="bandeja-filtro-nivel")
    tipos = c3.multiselect("Tipo de resultado", TIPOS_RESULTADO, key="bandeja-filtro-tipo")
    estados_sel = c4.multiselect(
        "Estado de decisión", ESTADOS_DECISION, format_func=ETIQUETA_DECISION.get, key="bandeja-filtro-decision"
    )
    k1, k2, k3 = st.columns(3)
    solo_analisis = k1.checkbox("Solo con análisis", key="bandeja-filtro-analisis")
    solo_equidad = k2.checkbox("Solo con advertencia de equidad", key="bandeja-filtro-equidad")
    sin_alerta = k3.checkbox("Incluir sin alerta", key="bandeja-filtro-sin-alerta")

    visibles = filtrar(
        filas,
        Filtros(
            especialidades=frozenset(especialidades),
            niveles=frozenset(niveles),
            tipos=frozenset(tipos),
            incluir_sin_alerta=sin_alerta,
            solo_con_analisis=solo_analisis,
            solo_con_equidad=solo_equidad,
            estados_decision=frozenset(estados_sel),
        ),
    )
    n, m, k = contador(visibles)
    st.markdown(f"**{n} solicitudes · {m} críticas · {k} con análisis**")
    tabla = pd.DataFrame(
        [
            {
                "ID": f.id_solicitud,
                "Especialidad": f.especialidad,
                "Inicial → propuesto": cambio_nivel(f.prioridad_inicial, f.nivel_propuesto, f.magnitud),
                "Puntaje": puntaje(f.puntaje),
                "Tipo": f.tipo_resultado,
                "Banderas": " ".join(f"🚩 {b}" for b in f.banderas),
                "Análisis": ETIQUETA_ANALISIS[f.analisis],
                "Equidad": "⚠ revisar" if f.revision_equidad else "",
                "Decisión": ETIQUETA_DECISION[f.estado_decision],
            }
            for f in visibles
        ],
        columns=["ID", "Especialidad", "Inicial → propuesto", "Puntaje", "Tipo", "Banderas", "Análisis", "Equidad",
                 "Decisión"],
    )
    st.caption("Elija una fila para abrir el Detalle.")
    ids = tuple(f.id_solicitud for f in visibles)
    st.dataframe(
        tabla,
        key="bandeja-tabla",
        on_select=partial(_abrir, "bandeja-tabla", ids),
        selection_mode="single-row",
        hide_index=True,
    )


# --------------------------------------------------------------------------- pestaña Detalle


def _ids_citados(ev: Evaluacion) -> list[str]:
    ids: list[str] = []
    for grupo in (
        [b.ids_registro for b in ev.banderas],
        [p.ids_registro for p in ev.pisos],
        [[c.id_evento, *c.ids_medicion] for c in ev.contradicciones],
        [a.ids_registro for a in ev.alertas_gestion],
        [f.ids_registro for f in ev.factores],
    ):
        for lista in grupo:
            ids.extend(i for i in lista if i not in ids)
    return ids


def _encabezado(dc: DatosCorte, ev: Evaluacion, rc: ResultadoContexto) -> None:
    st.subheader(f"{ev.id_solicitud} · {plano(dc.especialidades.get(ev.id_solicitud, ''))}")
    if rc.contexto is not None:
        s = rc.contexto.solicitud
        espera = (ev.fecha_corte - s.fecha_ingreso_lista).days
        st.markdown(
            f"Diagnóstico **{plano(s.diagnostico_cie10)}** ({plano(s.diagnostico_texto)}) · "
            f"{rc.contexto.edad} años · sexo {plano(rc.contexto.sexo)} · {espera} días en espera"
        )
    c = st.columns(4)
    c[0].metric("Prioridad inicial", nivel(ev.prioridad_inicial))
    c[1].metric("Nivel calculado", nivel(ev.nivel_calculado))
    c[2].metric("Nivel propuesto", nivel(ev.nivel_propuesto))
    c[3].metric("Puntaje", puntaje(ev.puntaje))
    motivos = "; ".join(plano(m) for m in ev.motivo_confianza) or "sin motivos registrados"
    st.markdown(f"Confianza **{ev.confianza}** ({motivos}) · Estado: `{ev.estado_revision}` · "
                f"Tipo de resultado: `{ev.tipo_resultado}`")
    if ev.codigo_exclusion:
        st.markdown(f"Exclusión: `{ev.codigo_exclusion}`")


def _senales(ev: Evaluacion) -> None:
    st.markdown("#### Banderas, pisos, contradicciones y alertas")
    lineas = [f"- 🚩 Bandera `{b.codigo}` · IDs: {', '.join(b.ids_registro)}" for b in ev.banderas]
    lineas += [f"- ⬆ Piso `{p.codigo}` · IDs: {', '.join(p.ids_registro)}" for p in ev.pisos]
    lineas += [
        f"- ❓ Contradicción: {plano(c.pregunta_clinica)} · IDs: {', '.join([c.id_evento, *c.ids_medicion])}"
        for c in ev.contradicciones
    ]
    lineas += [
        f"- 📋 Alerta de gestión `{a.codigo}`: {plano(a.accion_sugerida)} · IDs: {', '.join(a.ids_registro)}"
        for a in ev.alertas_gestion
    ]
    lineas += [f"- ℹ Inferido `{plano(m.campo)}` = {plano(m.valor)} · IDs: {', '.join(m.ids_registro)}"
               for m in ev.marcas_inferido]
    st.markdown("\n".join(lineas) if lineas else "Sin banderas, pisos, contradicciones ni alertas.")


def _factores(ev: Evaluacion) -> None:
    st.markdown("#### Factores")
    if not ev.factores:
        st.markdown("Sin factores (exclusión).")
        return
    tabla = pd.DataFrame(
        [
            {"Factor": f.factor, "Detalle": f.detalle, "Aporte": round(f.aporte, 2), "IDs": ", ".join(f.ids_registro)}
            for f in ev.factores
        ]
    )
    st.dataframe(tabla, hide_index=True, key="detalle-factores")
    st.bar_chart(tabla, x="Factor", y="Aporte", horizontal=True)


def _linea_tiempo(ev: Evaluacion, rc: ResultadoContexto) -> None:
    st.markdown("#### Línea de tiempo (registros hasta el corte)")
    if rc.estado == "huella_distinta":
        st.warning(
            "⚠ Los datos cambiaron desde el lote: la huella del contexto reconstruido no coincide con la de la "
            "evaluación. No se muestra la línea de tiempo."
        )
        return
    if rc.estado == "contexto_no_disponible":
        st.warning(
            "⚠ El contexto de esta solicitud no está disponible en el dataset: "
            "no se muestra la línea de tiempo."
        )
        return
    citados = _ids_citados(ev)
    por_defecto = ev.banderas[0].ids_registro[0] if ev.banderas else ""
    if st.session_state.get("_resaltar_de") != ev.id_solicitud or st.session_state.get(
        "detalle-resaltar"
    ) not in ["", *citados]:
        st.session_state["detalle-resaltar"] = por_defecto
        st.session_state["_resaltar_de"] = ev.id_solicitud
    elegido = st.selectbox(
        "ID a resaltar (citado en factores, banderas o alertas)",
        ["", *citados],
        format_func=lambda i: i or "— ninguno —",
        key="detalle-resaltar",
    )
    tabla = pd.DataFrame(
        [
            {
                "Elegido": "▶ elegido" if r.id_registro == elegido else "",
                "Fecha": r.fecha.isoformat(),
                "Tipo": r.tipo_registro,
                "Detalle": r.descripcion,
                "ID": r.id_registro,
            }
            for r in rc.linea_tiempo
        ],
        columns=["Elegido", "Fecha", "Tipo", "Detalle", "ID"],
    )

    def _resaltar(fila: pd.Series) -> list[str]:
        estilo = "background-color: #fff3b0; font-weight: bold" if fila["ID"] == elegido else ""
        return [estilo] * len(fila)

    st.dataframe(tabla.style.apply(_resaltar, axis=1), hide_index=True, key="detalle-linea-tiempo")


def _calidad(dc: DatosCorte, ev: Evaluacion) -> None:
    st.markdown("#### Calidad de datos")
    hallazgos = dc.hallazgos_dq.get(ev.id_solicitud, [])
    if not hallazgos:
        st.markdown("Sin hallazgos de calidad de datos en este corte.")
        return
    st.markdown(
        "\n".join(
            f"- `{h.nivel}` `{h.codigo}`: {plano(h.detalle)} · IDs: {', '.join(h.ids_registro)}" for h in hallazgos
        )
    )


def _analisis(dc: DatosCorte, ev: Evaluacion) -> None:
    marcas = dc.marcas_equidad(ev.id_solicitud)
    if marcas:  # B3.5: antes del análisis
        frases = "\n".join(f"- `{plano(m.campo)}`: {plano(m.texto)}" for m in marcas)
        st.warning(f"⚠ {ADVERTENCIA_EQUIDAD}\n\n{frases}")
    st.markdown(f"### {ROTULO_COPILOTO}")
    registro = dc.analisis.get(ev.id_solicitud)
    if registro is None:
        fallido = dc.fallidos.get(ev.id_solicitud)
        if fallido is not None:
            st.error(f"❌ El análisis IA falló: {plano(fallido.motivo)}")
            st.markdown(f"Para reintentar: `{comando_copiloto(dc.corte)}`")
        elif ev.tipo_resultado == "priorizacion":
            st.info(f"{ANALISIS_PENDIENTE}. Para generarlo: `{comando_copiloto(dc.corte)}`")
        else:
            st.info(f"{ANALISIS_PENDIENTE}: el copiloto analiza solo las solicitudes en priorización.")
        return
    a = registro.analisis
    c = st.columns(3)
    c[0].metric("Prioridad sugerida", nivel(a.prioridad_sugerida))
    c[1].metric("Acuerdo con el motor", "✔ de acuerdo" if a.acuerdo_con_motor.acuerdo else "✖ discrepa")
    c[2].metric("Confianza", a.confianza)
    if not a.acuerdo_con_motor.acuerdo:
        st.warning(f"Motivo de la discrepancia: {plano(a.acuerdo_con_motor.motivo_discrepancia or '')}")
    st.markdown(f"**Resumen.** {plano(a.resumen)}")
    st.markdown(
        f"**Relación con la derivación** (`{a.relacion_con_derivacion.tipo}`): {plano(a.relacion_con_derivacion.texto)}"
    )
    st.markdown(f"**Justificación.** {plano(a.justificacion)}")
    st.markdown("**Hallazgos**")
    st.markdown(
        "\n".join(
            f"- 📄 documentado · {plano(h.texto)} · IDs: {', '.join(h.ids_registro)}"
            if h.tipo == "documentado"
            else f"- 💭 inferido (no documentado) · {plano(h.texto)}"
            for h in a.hallazgos
        )
        or "Sin hallazgos."
    )
    st.markdown("**Riesgo poblacional**")
    r = a.riesgo_poblacional
    if r is None:
        st.markdown("Sin cohorte disponible.")
    else:
        p = "—" if r.p is None else f"{r.p:.1%}"
        ic = "—" if r.ic95_inf is None or r.ic95_sup is None else f"[{r.ic95_inf:.1%}, {r.ic95_sup:.1%}]"
        avisos = []
        if r.advertencia_muestra_pequena:
            avisos.append("⚠ muestra pequeña")
        if r.advertencia_sesgo_acceso:
            avisos.append("⚠ sesgo de acceso: solo pacientes que llegaron a la lista")
        st.markdown(f"n = {r.n} · k = {r.k} · p = {p} · IC95 {ic}" + (f" · {' · '.join(avisos)}" if avisos else ""))
    for titulo, items in (
        ("Acciones sugeridas", a.acciones_sugeridas),
        ("Datos faltantes", a.datos_faltantes),
        ("Escalas sustitutas", a.escalas_sustitutas),
    ):
        if items:
            st.markdown(f"**{titulo}**\n\n" + "\n".join(f"- {plano(i)}" for i in items))
    if a.inconsistencias_datos:
        st.markdown(
            "**Inconsistencias de datos**\n\n"
            + "\n".join(f"- {plano(i.texto)} · IDs: {', '.join(i.ids_registro)}" for i in a.inconsistencias_datos)
        )
    st.markdown("**Correcciones del validador**")
    st.markdown(
        "\n".join(f"- `{c.tipo}` en `{plano(c.campo)}`: {plano(c.detalle)}" for c in registro.correcciones)
        or "Sin correcciones."
    )
    st.caption(
        f"Modelo {registro.model_id} · prompt {registro.version_prompt} · análisis {registro.id_analisis} · "
        f"estado {a.metadatos.estado}"
    )
    st.text_area(
        "Nota de pre-consulta (solo lectura)", a.nota_preconsulta, disabled=True, key=f"detalle-nota-{ev.id_solicitud}"
    )


def _formulario(raiz: Path, dc: DatosCorte, ev: Evaluacion, medico: str) -> None:
    st.markdown("#### Decisión médica")
    if ev.nivel_propuesto is None:
        st.info("Las exclusiones no tienen prioridad propuesta que decidir.")
        return
    if st.session_state.pop("_limpiar_formulario", False):
        for k in ("detalle-decision-radio", "detalle-decision-prioridad", "detalle-decision-motivo"):
            st.session_state.pop(k, None)
    mensaje = st.session_state.pop("_mensaje_decision", None)
    if mensaje:
        st.success(mensaje)
    sin_medico = not medico
    if sin_medico:
        st.warning("Elija un médico en la barra lateral para decidir.")
    with st.container(border=True):
        opcion = st.radio(
            "Decisión",
            OPCIONES,
            format_func=ETIQUETA_OPCION.get,
            horizontal=True,
            index=None,  # sin opción preseleccionada: el médico elige explícitamente
            key="detalle-decision-radio",
            disabled=sin_medico,
        )
        with st.form("detalle-decision-formulario", border=False):
            final = None
            if opcion == "ajustar":
                final = st.selectbox(
                    "Prioridad final",
                    niveles_ajuste(ev.nivel_propuesto),
                    format_func=nivel,
                    index=None,
                    placeholder="Elija la prioridad final",
                    key="detalle-decision-prioridad",
                    disabled=sin_medico,
                )
            motivo = st.text_area(
                "Motivo (obligatorio al ajustar o rechazar)",
                max_chars=MAX_MOTIVO,
                key="detalle-decision-motivo",
                disabled=sin_medico,
            )
            guardar = st.form_submit_button("Guardar decisión", key="detalle-decision-guardar", disabled=sin_medico)
    if not guardar or sin_medico:
        return
    if opcion is None:
        st.error("No se guardó: elija aceptar, ajustar o rechazar.")
        return
    registro = dc.analisis.get(ev.id_solicitud)
    try:
        decision = crear_decision(
            evaluacion=ev,
            opcion=opcion,
            usuario=medico,
            prioridad_final=final,
            motivo=motivo,
            id_analisis=registro.id_analisis if registro is not None else None,
        )
    except ErrorDecision as e:
        for m in e.mensajes:
            st.error(f"No se guardó: {m}")
        return
    try:
        guardar_decision(raiz, decision)
    except DecisionSinAuditoria as e:
        _logger().error(
            "decisión guardada sin evento de auditoría",
            extra={"campos": {"id_solicitud": ev.id_solicitud, "id_decision": e.id_decision,
                              "etapa": "auditoria", "tipo_error": e.tipo_error}},
        )
        _decisiones.clear()
        st.warning(
            f"La decisión quedó guardada ({e.id_decision}), pero no se pudo registrar en la auditoría. "
            "No la vuelva a guardar; avise al equipo técnico."
        )
        return
    except Exception as e:
        _logger().error(
            "no se pudo guardar la decisión",
            extra={"campos": {"id_solicitud": ev.id_solicitud, "etapa": "decision", "tipo_error": type(e).__name__}},
        )
        st.error("No se pudo guardar la decisión. El detalle quedó en los logs.")
        return
    _decisiones.clear()
    st.session_state["_limpiar_formulario"] = True
    st.session_state["_mensaje_decision"] = (
        f"Decisión guardada: {decision.decision} por {NOMBRES_MEDICO.get(medico, medico)}."
    )
    st.rerun()


def _historial(dc: DatosCorte, ev: Evaluacion, decisiones: list[Decision]) -> None:
    previas = historial(decisiones, ev.id_solicitud, dc.corte, dc.version_reglas)
    if not previas:
        st.caption("Sin decisiones registradas para esta solicitud en este corte.")
        return
    for n, d in enumerate(previas):
        rotulo = "Vigente" if n == 0 else "Historial"
        final = f" → {nivel(d.prioridad_final)}" if d.prioridad_final else ""
        motivo = f" · motivo: {plano(d.motivo)}" if d.motivo else ""
        st.markdown(
            f"**{rotulo}:** {ETIQUETA_DECISION[d.decision]}{final} · "
            f"{NOMBRES_MEDICO.get(d.usuario, plano(d.usuario))} · "
            f"{d.timestamp.isoformat()}{motivo}"
        )


def _vista_detalle(raiz: Path, datos: Path, dc: DatosCorte, decisiones: list[Decision], medico: str) -> None:
    ids = sorted(dc.propuestas)
    if not ids:
        st.info("El corte no tiene solicitudes.")
        return
    if st.session_state.get("detalle-solicitud") not in ids:
        st.session_state["detalle-solicitud"] = ids[0]
    id_sel = st.selectbox("Solicitud", ids, key="detalle-solicitud")
    ev = dc.propuestas[id_sel]
    rc = _contexto(datos, ev)
    _encabezado(dc, ev, rc)
    _senales(ev)
    _factores(ev)
    _linea_tiempo(ev, rc)
    _calidad(dc, ev)
    _analisis(dc, ev)
    _formulario(raiz, dc, ev, medico)
    _historial(dc, ev, decisiones)


# --------------------------------------------------------------------------- pestaña ¿Qué cambió?


@st.cache_data(show_spinner="Comparando cortes…")
def _comparacion(raiz: str, datos: str, a: str, b: str, version: str) -> list[list[CambioEntreCortes]]:
    dc_a = _corte(raiz, a, version)
    dc_b = _corte(raiz, b, version)
    repo = _repositorio(datos)

    def linea(ev: Evaluacion) -> list[Any]:
        return reconstruir_contexto(repo, ev).linea_tiempo if repo is not None else []

    cmp = comparar(dc_a.propuestas.values(), dc_b.propuestas.values(), dc_a.corte, dc_b.corte, linea)
    return [cmp.cambios, cmp.ingresos_nuevos, cmp.a_exclusion]


def _tabla_cambios(cambios: list[CambioEntreCortes], clave: str, corte_b: str) -> None:
    if not cambios:
        st.markdown("Ninguna.")
        return
    tabla = pd.DataFrame(
        [
            {
                "ID": c.id_solicitud,
                "Nivel A → B": f"{nivel(c.nivel_a) if c.tipo_a else '—'} → {nivel(c.nivel_b)}",
                "Puntaje A → B": f"{puntaje(c.puntaje_a)} → {puntaje(c.puntaje_b)}",
                "Banderas nuevas": " ".join(f"🚩 {b}" for b in c.banderas_nuevas),
                "Pisos nuevos": " ".join(c.pisos_nuevos),
                "Registros nuevos": ", ".join(c.registros_nuevos),
            }
            for c in cambios
        ]
    )
    ids = tuple(c.id_solicitud for c in cambios)
    st.dataframe(
        tabla,
        key=clave,
        on_select=partial(_abrir, clave, ids, corte_b),
        selection_mode="single-row",
        hide_index=True,
    )


def _vista_cambios(raiz: Path, datos: Path, cortes: list[date]) -> None:
    if len(cortes) < 2:
        st.info("Se necesitan al menos dos cortes con propuestas para comparar.")
        return
    opciones = [c.isoformat() for c in cortes]
    c1, c2 = st.columns(2)
    a = c1.selectbox("Corte A (anterior)", opciones, index=0, key="cambios-corte-a")
    b = c2.selectbox("Corte B (posterior)", opciones, index=1, key="cambios-corte-b")
    if a >= b:
        st.warning("El corte A debe ser anterior al corte B.")
        return
    if _repositorio(str(datos)) is None:
        st.warning("Dataset no disponible: no se pueden listar los registros nuevos.")
    resultado = _seguro(lambda: _comparacion(str(raiz), str(datos), a, b, VERSION_REGLAS), "comparacion")
    if resultado is None:
        return
    cambios, ingresos, exclusion = resultado
    st.caption("Registros nuevos: fecha en (corte A, corte B]. Elija una fila para abrir el Detalle en el corte B.")
    st.markdown(f"#### Cambiaron nivel, banderas o pisos ({len(cambios)})")
    _tabla_cambios(cambios, "cambios-tabla", b)
    st.markdown(f"#### Ingresos nuevos en B ({len(ingresos)})")
    _tabla_cambios(ingresos, "cambios-tabla-ingresos", b)
    st.markdown(f"#### Pasaron a exclusión ({len(exclusion)})")
    _tabla_cambios(exclusion, "cambios-tabla-exclusion", b)


# --------------------------------------------------------------------------- pestaña Cobertura


def _conteos(titulo: str, conteos: dict[str, int]) -> None:
    st.markdown(f"**{titulo}**")
    if conteos:
        st.dataframe(pd.DataFrame({"Código": list(conteos), "Cantidad": list(conteos.values())}), hide_index=True)
    else:
        st.markdown("Ninguno.")


def _vista_cobertura(dc: DatosCorte, decisiones: list[Decision]) -> None:
    cob = cobertura(dc, estados_del_corte(decisiones, dc.corte, dc.version_reglas))
    c = st.columns(4)
    c[0].metric("Solicitudes evaluadas", cob["evaluadas"])
    pct = cob["cobertura_pct"]
    aviso = "" if cob["cobertura_completa"] else " ⚠ incompleta"
    c[1].metric("Cobertura", "—" if pct is None else f"{pct} %{aviso}")
    c[2].metric("Perfiles en cuarentena", "—" if cob["cuarentena_perfiles"] is None else cob["cuarentena_perfiles"])
    c[3].metric(
        "Solicitudes en cuarentena", "—" if cob["cuarentena_solicitudes"] is None else cob["cuarentena_solicitudes"]
    )
    d = st.columns(5)
    d[0].metric("Análisis guardados", cob["analisis_guardados"])
    d[1].metric("Análisis fallidos", cob["analisis_fallidos"])
    d[2].metric("Con advertencia de equidad", cob["analisis_equidad"])
    d[3].metric("Decisiones tomadas", cob["decisiones_tomadas"])
    d[4].metric("Decisiones pendientes", cob["decisiones_pendientes"])
    if dc.resumen is None:
        st.info(f"Falta el resumen del lote para este corte: `{comando_lote(dc.corte)}`")
    e = st.columns(4)
    with e[0]:
        _conteos("Por tipo de resultado", cob["por_tipo_resultado"])
    with e[1]:
        _conteos("Exclusiones por código", cob["exclusiones"])
    with e[2]:
        _conteos("Cambios de nivel", cob["cambios_de_nivel"])
    with e[3]:
        _conteos("Alertas de gestión por código", cob["alertas_gestion"])


# --------------------------------------------------------------------------- aplicación


def main() -> None:
    st.set_page_config(page_title="Bandeja HLF (demo local)", layout="wide")
    _logger()
    raiz, datos = rutas(_APP.parent)
    cortes = _seguro(lambda: _cortes(str(raiz)), "cortes") or []
    medico, corte = _lateral(cortes)
    st.title("Bandeja de priorización HLF")
    if corte is None:
        st.warning(
            "No hay cortes con propuestas del lote. Genere uno con: `uv run hlf-lote --fecha-corte AAAA-MM-DD`"
        )
        return
    try:
        dc = _seguro(lambda: _corte(str(raiz), corte.isoformat(), VERSION_REGLAS), "propuestas", corte)
    except CorteSinPropuestas as e:
        st.warning(f"El corte {corte.isoformat()} no tiene propuestas. Genérelas con: `{e.comando}`")
        return
    if dc is None:
        return
    decisiones = _seguro(lambda: _decisiones(str(raiz)), "decisiones") or []

    # Navegación con un widget (no st.tabs): en el navegador, la pestaña activa de st.tabs la controla el
    # frontend y no siempre sigue al valor puesto en session_state desde un callback, así que hacer clic en
    # una fila no abría el Detalle. Un radio sí respeta session_state["app-pestana"] en cada rerun.
    if st.session_state.get("app-pestana") not in PESTANAS:
        st.session_state["app-pestana"] = PESTANAS[0]
    vista = st.radio("Vista", PESTANAS, key="app-pestana", horizontal=True, label_visibility="collapsed")
    st.divider()
    if vista == "Bandeja":
        _vista_bandeja(dc, decisiones)
    elif vista == "Detalle":
        _vista_detalle(raiz, datos, dc, decisiones, medico)
    elif vista == "¿Qué cambió?":
        _vista_cambios(raiz, datos, cortes)
    else:
        _vista_cobertura(dc, decisiones)


main()
