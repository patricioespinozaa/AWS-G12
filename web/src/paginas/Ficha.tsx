import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ClinicoRespuesta, FichaPaciente, getJSON, postJSON, Registro, SerieRespuesta, useApi } from "../api";
import Cascada from "../componentes/Cascada";
import { Aviso, Cargando, Metrica, NivelBadge, Pestanas, Tabla } from "../componentes/comunes";
import GraficoClinico from "../componentes/GraficoClinico";
import GraficoEvolucion from "../componentes/GraficoEvolucion";
import { useApp } from "../contexto";
import { diasEntre, ETIQUETA_DISP, num, VALOR_NIVEL } from "../utils";

type IdPestana = "evolucion" | "clinico" | "ficha" | "explicacion" | "validacion" | "historial";
const PESTANAS: { id: IdPestana; etiqueta: string }[] = [
  { id: "evolucion", etiqueta: "📈 Evolución de la prioridad" },
  { id: "clinico", etiqueta: "🩺 Línea de tiempo clínica" },
  { id: "ficha", etiqueta: "🗂️ Ficha consolidada" },
  { id: "explicacion", etiqueta: "🔎 Explicación y factores" },
  { id: "validacion", etiqueta: "✅ Validación clínica" },
  { id: "historial", etiqueta: "🧾 Historial y trazabilidad" },
];
const ROL: Record<string, string> = {
  base: "Base · decide nivel", evento: "Evento · decide nivel", medicion: "Medición · decide nivel",
  patron: "Patrón · decide nivel", ajuste: "Ajuste riesgo basal · decide nivel", contexto: "Contexto · ordena",
  regla_dura: "Regla dura", alerta: "Alerta",
};

export default function Ficha() {
  const { idSolicitud } = useParams();
  const navegar = useNavigate();
  const { meta, corte, version } = useApp();
  const [parametros, setParametros] = useSearchParams();
  const pestana = (PESTANAS.find((p) => p.id === parametros.get("pestana"))?.id ?? "evolucion") as IdPestana;
  const setPestana = (p: IdPestana) => setParametros(p === "evolucion" ? {} : { pestana: p }, { replace: true });
  const lista = useApi<Registro[]>("/api/solicitudes");
  const id = idSolicitud ?? meta?.casos_referencia[0]?.id_solicitud ?? null;
  const { data, error, cargando } = useApi<FichaPaciente>(id ? `/api/solicitudes/${id}?corte=${corte}` : null, version);

  useEffect(() => {
    if (!idSolicitud && id) navegar(`/ficha/${id}`, { replace: true });
  }, [idSolicitud, id, navegar]);

  return (
    <>
      <div className="encabezado">
        <h1>🩺 Ficha del paciente</h1>
        <p>Cómo evoluciona la prioridad de un paciente noche a noche, por qué cambia y qué decidió el equipo clínico.</p>
      </div>
      <div className="tarjeta compacta pila">
        <div className="fila">
          <span className="suave">Casos de referencia:</span>
          {meta?.casos_referencia.map((c) => (
            <button key={c.id_solicitud} className={`boton chico${c.id_solicitud === id ? " activo" : ""}`} onClick={() => navegar(`/ficha/${c.id_solicitud}${pestana === "evolucion" ? "" : `?pestana=${pestana}`}`)}>
              {c.patron}
            </button>
          ))}
        </div>
        <label className="campo">
          <span>Paciente</span>
          <select value={id ?? ""} onChange={(e) => navegar(`/ficha/${e.target.value}`)}>
            {(lista.data ?? []).map((s) => (
              <option key={s.id_solicitud} value={s.id_solicitud}>
                {s.id_paciente} · {s.nombre} · {s.especialidad} · {s.cie10} {s.diagnostico}{s.caso_referencia ? `  ★ ${s.caso_referencia}` : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {cargando && !data && <Cargando />}
      {data && id && (
        <>
          <Cabecera d={data} />
          <Pestanas opciones={PESTANAS} activa={pestana} onCambio={setPestana} />
          {pestana === "evolucion" && <TabEvolucion id={id} d={data} />}
          {pestana === "clinico" && <TabClinico id={id} />}
          {pestana === "ficha" && <TabFicha d={data} />}
          {pestana === "explicacion" && <TabExplicacion id={id} d={data} />}
          {pestana === "validacion" && <TabValidacion id={id} d={data} />}
          {pestana === "historial" && <TabHistorial d={data} />}
        </>
      )}
    </>
  );
}

function Cabecera({ d }: { d: FichaPaciente }) {
  const s = d.solicitud;
  const r = d.resultado;
  const sexo = s.sexo === "F" ? "mujer" : s.sexo === "M" ? "hombre" : s.sexo;
  return (
    <div className="tarjeta pila">
      <div className="fila entre">
        <div>
          <h2 style={{ marginBottom: 2 }}>
            {s.nombre} <small className="suave">{s.id_paciente}</small>
            {s.caso_referencia && <> <span className="etiqueta-chip caso">★ {s.caso_referencia}</span></>}
          </h2>
          <small>
            {s.edad} años · {sexo} · {s.comuna} · {s.prevision} · NSE {s.nivel_socioeconomico} · {s.especialidad} / {s.sub_especialidad} ·{" "}
            <b>{s.cie10} {s.diagnostico}</b> · riesgo basal <b>{s.riesgo_basal}</b> · {s.id_solicitud} · derivado desde {s.origen_derivacion} vía {s.canal_origen}
          </small>
        </div>
      </div>
      <div className="cabecera-paciente">
        <div className="dato-nivel"><span className="etiqueta">Lista congelada (prioridad inicial)</span><NivelBadge nivel={s.prioridad_inicial} /></div>
        <div className="dato-nivel"><span className="etiqueta">Vigente (decisión clínica)</span><NivelBadge nivel={r.prioridad_vigente} /></div>
        <div className="dato-nivel">
          <span className="etiqueta">Propuesta al {d.corte}</span>
          {r.excluido ? <b className="suave">Fuera de la lista</b> : (
            <>
              <NivelBadge nivel={r.nivel_propuesto} />{" "}
              <b className={r.cambio === "sube" ? "cambio-sube" : r.cambio === "baja" ? "cambio-baja" : "suave"}>
                {r.cambio === "sube" ? "↑ sube" : r.cambio === "baja" ? "↓ baja" : "= se mantiene"}
              </b>
            </>
          )}
        </div>
        <div className="dato-nivel"><span className="etiqueta">Puntaje de nivel · de orden</span>
          {r.excluido ? <span className="suave">—</span> : <><b>{num(r.puntaje_nivel)}</b> · {num(r.puntaje)}</>}
        </div>
        <div className="dato-nivel" title={d.disponibilidad.accion ?? ""}>
          <span className="etiqueta">Disponibilidad para box</span>
          {r.excluido ? <span className="suave">—</span> : ETIQUETA_DISP[d.disponibilidad.estado]}
          {!r.excluido && d.disponibilidad.accion && <div><small>{d.disponibilidad.accion}</small></div>}
        </div>
        <div className="dato-nivel" title="Rango según la posición vigente y las atenciones de las últimas 8 semanas. Uso interno: no se informa al paciente.">
          <span className="etiqueta">Espera estimada (uso interno)</span>
          {r.excluido || !d.estimacion ? <span className="suave">Sin estimación</span> : (
            <>
              <b>{d.estimacion.dias_estimados_min}–{d.estimacion.dias_estimados_max} días</b>
              <div><small>Posición {d.estimacion.posicion_vigente} de {d.estimacion.total_cola} · confianza {d.estimacion.confianza} · al {d.estimacion.fecha_calculo}</small></div>
            </>
          )}
        </div>
      </div>
      {r.excluido && <Aviso tipo="info">Fuera de la lista activa al {d.corte}: {r.motivo_exclusion}.</Aviso>}
      {r.alerta && <Aviso tipo="error">⚠️ <b>Alerta para revisión clínica prioritaria.</b> {r.motivos_alerta.join(" · ")}</Aviso>}
      {r.resguardo_aplicado && (
        <Aviso tipo="atencion">
          El puntaje por sí solo indicaría <b>{r.nivel_calculado}</b>, pero no hay evidencia de mejora: se mantiene la prioridad vigente (<b>{r.prioridad_vigente}</b>).
        </Aviso>
      )}
      <div className="resumen"><b>Resumen clínico consolidado.</b> {d.resumen}</div>
    </div>
  );
}

function TabEvolucion({ id, d }: { id: string; d: FichaPaciente }) {
  const { corte, version } = useApp();
  const { data, error } = useApi<SerieRespuesta>(`/api/solicitudes/${id}/serie`, version);
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!data) return <Cargando texto="Leyendo la serie nocturna…" />;
  if (data.serie.length === 0) return <Aviso tipo="info">La consolidación nocturna no tiene noches para esta solicitud.</Aviso>;
  const s = data.serie;
  const inicial = d.solicitud.prioridad_inicial;
  const primerCambio = data.cambios[0];
  const nochesSobre = s.filter((p) => VALOR_NIVEL[p.nivel_propuesto] > VALOR_NIVEL[inicial]).length;
  const nochesAlerta = s.filter((p) => p.alerta).length;
  const hoy = [...s].reverse().find((p) => p.fecha <= corte);
  return (
    <div className="tarjeta pila">
      <p className="suave">
        Cada punto es una corrida nocturna: esa noche el sistema recalculó la prioridad solo con los datos disponibles hasta
        entonces. Así se ve el efecto de actualizar la prioridad en el tiempo frente a la lista congelada.
      </p>
      <div className="metricas">
        <Metrica etiqueta="Primer cambio de nivel" valor={primerCambio ? primerCambio.fecha : "sin cambios"}
          detalle={primerCambio ? `día ${diasEntre(d.solicitud.fecha_ingreso, primerCambio.fecha)} de espera · ${primerCambio.desde} → ${primerCambio.nivel_propuesto}` : undefined} />
        <Metrica etiqueta="Noches con propuesta sobre la lista congelada" valor={nochesSobre}
          detalle={`de ${s.length} noches en lista · la lista congelada lo mantuvo en ${inicial}`} />
        <Metrica etiqueta="Noches con alerta" valor={nochesAlerta} />
        {hoy && (
          <Metrica destacada etiqueta={`Posición al ${hoy.fecha}`} valor={`${hoy.posicion_dinamica} de ${hoy.total_cola}`}
            detalle={`lista congelada: ${hoy.posicion_estatica} (${hoy.posicion_estatica - hoy.posicion_dinamica >= 0 ? "+" : ""}${hoy.posicion_estatica - hoy.posicion_dinamica} posiciones)`} />
        )}
      </div>
      <GraficoEvolucion datos={data} corte={corte} inicial={inicial} especialidad={d.solicitud.especialidad} />
      <h3>Noches en que cambió la propuesta</h3>
      <Tabla filas={data.cambios} vacia="La propuesta nunca cambió de nivel."
        columnas={[
          { clave: "fecha", titulo: "Noche" },
          { clave: "desde", titulo: "De", render: (f) => <NivelBadge nivel={f.desde} /> },
          { clave: "nivel_propuesto", titulo: "A", render: (f) => <NivelBadge nivel={f.nivel_propuesto} /> },
          { clave: "alerta", titulo: "Alerta", render: (f) => (f.alerta ? "⚠️" : "") },
          { clave: "motivo_principal", titulo: "Motivo principal" },
          { clave: "puntaje_nivel", titulo: "Puntaje de nivel", num: true, render: (f) => num(f.puntaje_nivel) },
        ]} />
    </div>
  );
}

function TabClinico({ id }: { id: string }) {
  const { corte, version } = useApp();
  const { data, error } = useApi<ClinicoRespuesta>(`/api/solicitudes/${id}/clinico?corte=${corte}`, version);
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!data) return <Cargando />;
  return <div className="tarjeta"><GraficoClinico datos={data} corte={corte} /></div>;
}

function TabFicha({ d }: { d: FichaPaciente }) {
  const f = d.ficha;
  const fuenteEvento = [
    { clave: "fecha", titulo: "Fecha" }, { clave: "tipo", titulo: "Tipo" }, { clave: "detalle", titulo: "Detalle" },
    { clave: "severidad", titulo: "Severidad" }, { clave: "fuente", titulo: "Fuente" },
  ];
  return (
    <div className="pila">
      <Aviso tipo="info">
        Toda la información disponible al {d.corte}, de todas las fuentes, organizada por tipo. Cada fila conserva su
        referencia de origen; las fuentes no se modifican (consolidación de solo lectura).
      </Aviso>
      <div className="grid-2">
        <div className="tarjeta pila">
          <h3>Diagnósticos</h3>
          <Tabla filas={f.diagnosticos} />
          <small>Comorbilidades (diabetes, HTA, ERC) y riesgo ACG de la red (G1–G3): no vienen en el dataset.</small>
          <h3>Urgencias y hospitalizaciones</h3>
          <Tabla filas={f.atenciones} columnas={fuenteEvento} vacia="Sin atenciones de urgencia ni hospitalizaciones." />
          <small>GRD de las hospitalizaciones: no disponible en el dataset.</small>
          <h3>Controles en APS</h3>
          <Tabla filas={f.controles} columnas={fuenteEvento} vacia="Sin controles registrados." />
          <h3>Citas de especialidad</h3>
          <Tabla filas={f.citas} vacia="Sin citas." />
        </div>
        <div className="tarjeta pila">
          <h3>Fármacos (cambios de tratamiento)</h3>
          <Tabla filas={f.farmacos} columnas={fuenteEvento} vacia="Sin cambios de fármaco." />
          <h3>Exámenes y mediciones</h3>
          <Tabla filas={f.examenes} vacia="Sin mediciones." />
          <Tabla filas={f.examenes_alterados} columnas={fuenteEvento} vacia="Sin exámenes alterados informados." />
          <h3>Exámenes enviados por el paciente</h3>
          <Tabla filas={f.evidencia_externa} vacia="Sin evidencia externa."
            columnas={[{ clave: "id_evidencia", titulo: "ID" }, { clave: "fecha_examen", titulo: "Fecha" }, { clave: "tipo_medicion", titulo: "Examen" },
              { clave: "valor", titulo: "Valor", num: true }, { clave: "lugar", titulo: "Lugar" }, { clave: "estado", titulo: "Estado" }, { clave: "revisado_por", titulo: "Revisó" }]} />
          <h3>Mensajes del paciente</h3>
          <Tabla filas={f.mensajes} vacia="Sin mensajes."
            columnas={[{ clave: "fecha", titulo: "Fecha" }, { clave: "tipo", titulo: "Tipo" }, { clave: "detalle", titulo: "Detalle" }, { clave: "estado", titulo: "Estado" }]} />
        </div>
      </div>
    </div>
  );
}

function TabExplicacion({ id, d }: { id: string; d: FichaPaciente }) {
  const { meta, corte } = useApp();
  const [ia, setIa] = useState<{ texto: string; fuente: string; aviso: string | null } | null>(null);
  const [pidiendo, setPidiendo] = useState(false);
  useEffect(() => setIa(null), [id, corte]);
  const r = d.resultado;
  if (r.excluido) return <Aviso tipo="info">{d.explicacion}</Aviso>;
  const redactar = async () => {
    setPidiendo(true);
    try {
      setIa(await postJSON(`/api/solicitudes/${id}/explicacion-ia?corte=${corte}`));
    } catch (e) {
      setIa({ texto: d.explicacion, fuente: "plantilla", aviso: (e as Error).message });
    } finally {
      setPidiendo(false);
    }
  };
  return (
    <div className="pila">
      <div className="grid-2">
        <div className="tarjeta">
          <h3>Cómo se llega al nivel propuesto</h3>
          <p className="suave">Solo la prioridad inicial y las señales clínicas deciden el nivel. El contexto (riesgo basal, edad, espera) ordena dentro del nivel.</p>
          {meta && <Cascada r={r} umbrales={meta.umbrales} />}
        </div>
        <div className="tarjeta pila">
          <div className="fila entre">
            <h3>Explicación</h3>
            <button className="boton" onClick={redactar} disabled={pidiendo}
              title="El LLM solo redacta a partir de los factores; se valida que no cite datos que no estén en ellos.">
              ✨ {pidiendo ? "Redactando…" : "Redactar con IA generativa (Bedrock)"}
            </button>
          </div>
          <div className="explicacion">{ia ? ia.texto : d.explicacion}</div>
          <small>
            Fuente: {ia ? ia.fuente : "plantilla determinista"}{ia?.aviso ? ` · ${ia.aviso}` : ""}
          </small>
          <small>Versión de reglas <code>{r.version_reglas}</code> · huella de datos <code>{d.huella_datos}</code> (permite reproducir el cálculo)</small>
        </div>
      </div>
      <div className="tarjeta">
        <h3>Todos los factores, con su dato de origen</h3>
        <Tabla filas={r.factores as unknown as Registro[]} columnas={[
          { clave: "descripcion", titulo: "Factor" },
          { clave: "categoria", titulo: "Rol", render: (f) => ROL[f.categoria] ?? f.categoria },
          { clave: "aporte", titulo: "Aporte", num: true, render: (f) => <b className={f.aporte > 0 ? "cambio-sube" : f.aporte < 0 ? "cambio-baja" : "suave"}>{f.aporte > 0 ? "+" : ""}{num(f.aporte, 2)}</b> },
          { clave: "fecha_dato", titulo: "Fecha del dato" },
          { clave: "tipo_fuente", titulo: "Fuente" },
          { clave: "ref_fuente", titulo: "Referencia", render: (f) => <code>{f.ref_fuente}</code> },
        ]} />
      </div>
    </div>
  );
}

function TabValidacion({ id, d }: { id: string; d: FichaPaciente }) {
  const { corte, refrescar } = useApp();
  const r = d.resultado;
  const [decision, setDecision] = useState<"acepta" | "ajusta" | "rechaza">("acepta");
  const [nivel, setNivel] = useState<string>("alta");
  const [motivo, setMotivo] = useState("");
  const [estado, setEstado] = useState<{ tipo: "exito" | "error"; texto: string } | null>(null);
  const [enviando, setEnviando] = useState(false);
  if (r.excluido) return <Aviso tipo="info">La solicitud no está activa a esta fecha de corte: no hay propuesta que validar.</Aviso>;
  const enviar = async () => {
    setEnviando(true);
    setEstado(null);
    try {
      const res = await postJSON<{ mensaje: string }>(`/api/solicitudes/${id}/decisiones`, {
        corte, decision, nivel_ajuste: decision === "ajusta" ? nivel : null, motivo,
      });
      setEstado({ tipo: "exito", texto: res.mensaje });
      setMotivo("");
      refrescar();
    } catch (e) {
      setEstado({ tipo: "error", texto: (e as Error).message });
    } finally {
      setEnviando(false);
    }
  };
  return (
    <div className="grid-2">
      <div className="tarjeta pila">
        <h3>Decisión de la Administradora</h3>
        <p>
          Propuesta al <b>{corte}</b>: <NivelBadge nivel={r.nivel_propuesto} /> (vigente <NivelBadge nivel={r.prioridad_vigente} />).
          La decisión rige desde esta fecha y queda registrada junto a la propuesta, sus factores y la huella de los datos.
          Nunca se sobrescribe la prioridad inicial.
        </p>
        <div className="fila">
          {([["acepta", `Aceptar (${r.nivel_propuesto})`], ["ajusta", "Ajustar a otro nivel"], ["rechaza", `Rechazar (mantener ${r.prioridad_vigente})`]] as const).map(([k, t]) => (
            <label key={k} className="interruptor"><input type="radio" checked={decision === k} onChange={() => setDecision(k)} />{t}</label>
          ))}
        </div>
        {decision === "ajusta" && (
          <label className="campo"><span>Nivel</span>
            <select value={nivel} onChange={(e) => setNivel(e.target.value)}>
              <option value="alta">alta</option><option value="media">media</option><option value="baja">baja</option>
            </select>
          </label>
        )}
        <label className="campo"><span>Motivo {decision !== "acepta" ? "(obligatorio)" : "(opcional)"}</span>
          <textarea value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="Ej.: revisado con el especialista; se adelanta la consulta" />
        </label>
        <small>Se registra a nombre de la Administradora, junto a la propuesta, sus factores y la huella de los datos.</small>
        <div><button className="boton primario" onClick={enviar} disabled={enviando}>{enviando ? "Registrando y reevaluando…" : "Registrar decisión"}</button></div>
        {estado && <Aviso tipo={estado.tipo}>{estado.texto}</Aviso>}
      </div>
      <div className="tarjeta pila">
        <h3>Decisiones registradas</h3>
        <Tabla filas={d.decisiones} vacia="Aún no hay decisiones para esta solicitud."
          columnas={[{ clave: "fecha_corte", titulo: "Rige desde" }, { clave: "prioridad_anterior", titulo: "Anterior" },
            { clave: "prioridad_propuesta", titulo: "Propuesta" }, { clave: "decision", titulo: "Decisión" },
            { clave: "prioridad_final", titulo: "Final", render: (f) => <NivelBadge nivel={f.prioridad_final} /> },
            { clave: "motivo", titulo: "Motivo" }, { clave: "usuario", titulo: "Registró" }, { clave: "fecha_registro", titulo: "Registrada" }]} />
        <small>Tras registrar, la serie nocturna del paciente y su cola se recalculan de inmediato: revisa la pestaña de evolución.</small>
      </div>
    </div>
  );
}

function TabHistorial({ d }: { d: FichaPaciente }) {
  const [sel, setSel] = useState<Registro | null>(null);
  const [factores, setFactores] = useState<Registro[] | null>(null);
  useEffect(() => {
    if (!sel) return;
    setFactores(null);
    getJSON<Registro[]>(`/api/propuestas/${sel.id_propuesta}/factores`).then(setFactores);
  }, [sel]);
  return (
    <div className="pila">
      <div className="tarjeta pila">
        <h3>Propuestas registradas</h3>
        <small>La consolidación nocturna registra una propuesta cuando cambia el nivel o se enciende una alerta; al validar también se guarda una. Haz clic para ver su explicación y sus factores.</small>
        <Tabla filas={[...d.propuestas].reverse()} onFila={setSel} vacia="Sin propuestas registradas." alta
          columnas={[{ clave: "id_propuesta", titulo: "#", num: true }, { clave: "fecha_corte", titulo: "Noche" }, { clave: "origen", titulo: "Origen" },
            { clave: "prioridad_vigente", titulo: "Vigente", render: (f) => <NivelBadge nivel={f.prioridad_vigente} /> },
            { clave: "prioridad_propuesta", titulo: "Propuesta", render: (f) => <NivelBadge nivel={f.prioridad_propuesta} /> },
            { clave: "alerta", titulo: "Alerta", render: (f) => (f.alerta ? "⚠️" : "") },
            { clave: "puntaje_nivel", titulo: "Puntaje nivel", num: true },
            { clave: "version_reglas", titulo: "Reglas" }, { clave: "huella_datos", titulo: "Huella", render: (f) => <code>{f.huella_datos}</code> }]} />
      </div>
      {sel && (
        <div className="tarjeta pila">
          <h3>Propuesta #{sel.id_propuesta} · noche del {sel.fecha_corte}</h3>
          <div className="explicacion">{sel.explicacion_texto}</div>
          {factores ? <Tabla filas={factores} columnas={[{ clave: "descripcion", titulo: "Factor" }, { clave: "categoria", titulo: "Categoría" },
            { clave: "aporte", titulo: "Aporte", num: true }, { clave: "tipo_fuente", titulo: "Fuente" }, { clave: "ref_fuente", titulo: "Referencia" }, { clave: "fecha_dato", titulo: "Fecha" }]} /> : <Cargando />}
        </div>
      )}
    </div>
  );
}
