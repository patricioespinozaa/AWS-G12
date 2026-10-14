import { useEffect, useRef, useState } from "react";
import { postJSON, Registro, useApi } from "../api";
import { Aviso, Cargando, NivelBadge } from "../componentes/comunes";
import { useApp } from "../contexto";
import { ETIQUETA_DISP, num } from "../utils";

const PREGUNTAS_ALARMA = [
  "¿Sus síntomas empeoraron de forma brusca en la última semana?",
  "¿Consultó en un servicio de urgencia desde su último control?",
  "¿Tiene un síntoma nuevo que le impide hacer sus actividades diarias?",
];
const NOMBRE_TIPO: Record<string, string> = {
  confirma_asistencia: "Confirmo mi asistencia",
  no_puede_asistir: "No puedo asistir",
  sintoma_alarma: "Informo un síntoma",
  sintoma_sin_alarma: "Cuestionario de síntomas sin señales de alarma",
  sin_respuesta: "(El paciente no responde)",
};

export default function Canal() {
  const { meta, corte, version, refrescar } = useApp();
  const lista = useApi<Registro[]>("/api/solicitudes");
  const [idPaciente, setIdPaciente] = useState("PAC-HLF-00028");
  const { data, error } = useApi<Registro>(`/api/canal/${idPaciente}?corte=${corte}`, version);
  const [modo, setModo] = useState<"" | "examen" | "sintoma">("");
  const [respuesta, setRespuesta] = useState<string | null>(null);
  const chat = useRef<HTMLDivElement>(null);
  useEffect(() => { chat.current?.scrollTo(0, chat.current.scrollHeight); }, [data, respuesta]);
  useEffect(() => { setRespuesta(null); setModo(""); }, [idPaciente]);

  const enviarMensaje = async (tipo: string, detalle = "") => {
    const r = await postJSON<{ respuesta: string }>("/api/canal/mensajes", { id_paciente: idPaciente, fecha: corte, tipo, detalle });
    setRespuesta(r.respuesta);
    setModo("");
    refrescar();
  };

  const historial = data ? [
    ...(data.mensajes as Registro[]).map((m) => ({ fecha: m.fecha, quien: m.tipo === "sin_respuesta" ? "hospital" : "paciente",
      texto: `${NOMBRE_TIPO[m.tipo] ?? m.tipo}${m.detalle ? `: ${m.detalle}` : ""}`, estado: m.estado })),
    ...(data.evidencias as Registro[]).map((e) => ({ fecha: e.fecha_recepcion, quien: "paciente",
      texto: `📄 Examen ${e.tipo_medicion} = ${e.valor} (${e.fecha_examen}, ${e.lugar || "lugar no indicado"})${e.archivo ? ` · ${e.archivo}` : ""}`, estado: e.estado })),
  ].sort((a, b) => a.fecha.localeCompare(b.fecha)) : [];

  return (
    <>
      <div className="encabezado">
        <h1>💬 Canal del paciente <small className="suave">(maqueta)</small></h1>
        <p>
          Segunda iteración: el paciente confirma su asistencia, envía exámenes hechos en otro lugar y responde un
          cuestionario breve, sin tener que pedir una hora médica solo para eso. Lo que envía entra como <b>evidencia
          pendiente</b>: un profesional la valida y recién ahí gatilla la reevaluación. Así quien paga exámenes privados no
          se salta la fila: su evidencia se evalúa con el mismo criterio que la del hospital.
        </p>
      </div>
      <div className="grid-2">
        <div className="pila">
          <label className="campo"><span>Paciente (simulación)</span>
            <select value={idPaciente} onChange={(e) => setIdPaciente(e.target.value)}>
              {(lista.data ?? []).map((s) => (
                <option key={s.id_paciente} value={s.id_paciente}>{s.id_paciente} · {s.nombre} · {s.especialidad}{s.caso_referencia ? ` ★ ${s.caso_referencia}` : ""}</option>
              ))}
            </select>
          </label>
          {error && <Aviso tipo="error">{error}</Aviso>}
          {!data ? <Cargando /> : (
            <div className="telefono">
              <div className="telefono-cabecera">
                <div className="marca-logo" style={{ width: 30, height: 30 }}>+</div>
                <div><b>Hospital La Florida</b><small>Canal de lista de espera · WhatsApp (maqueta)</small></div>
              </div>
              <div className="chat" ref={chat}>
                <div className="burbuja hospital">
                  Hola, {data.solicitud.nombre}. Usted está en la lista de espera de <b>{data.solicitud.especialidad}</b>.
                  Por aquí puede confirmar su asistencia, enviarnos exámenes recientes o contarnos si sus síntomas cambiaron.
                  {data.requisitos.length > 0 && <> Para su consulta necesitamos un examen reciente de <b>{data.requisitos.join(" o ")}</b>.</>}
                  <small>Mensaje automático</small>
                </div>
                {historial.map((h, i) => (
                  <div key={i} className={`burbuja ${h.quien}`}>
                    {h.texto}
                    <small>{h.fecha} · {h.estado}</small>
                  </div>
                ))}
                {respuesta && <div className="burbuja hospital">{respuesta}<small>Respuesta automática</small></div>}
              </div>
              {modo === "examen" && <FormExamen idPaciente={idPaciente} onListo={(t) => { setRespuesta(t); setModo(""); refrescar(); }} />}
              {modo === "sintoma" && <FormSintomas onEnviar={(alarma, detalle) => enviarMensaje(alarma ? "sintoma_alarma" : "sintoma_sin_alarma", detalle)} />}
              <div className="acciones-chat">
                <button className="boton" onClick={() => enviarMensaje("confirma_asistencia", "Confirmo que asistiré")}>✅ Confirmo asistencia</button>
                <button className="boton" onClick={() => enviarMensaje("no_puede_asistir", "No puedo en la fecha ofrecida")}>❌ No puedo asistir</button>
                <button className={`boton${modo === "examen" ? " activo" : ""}`} onClick={() => setModo(modo === "examen" ? "" : "examen")}>📄 Enviar examen</button>
                <button className={`boton${modo === "sintoma" ? " activo" : ""}`} onClick={() => setModo(modo === "sintoma" ? "" : "sintoma")}>🩺 Cuestionario de síntomas</button>
                <button className="boton" onClick={() => enviarMensaje("sin_respuesta", "")} title="Simula que el paciente no responde a los mensajes">📵 Simular sin respuesta</button>
              </div>
            </div>
          )}
          {data && (
            <div className="tarjeta compacta">
              Disponibilidad para box al {corte}: <b>{ETIQUETA_DISP[data.disponibilidad.estado]}</b>
              {data.disponibilidad.accion && <div><small>{data.disponibilidad.accion}</small></div>}
              <div><small>Los mensajes se registran con la fecha de corte seleccionada ({corte}).</small></div>
            </div>
          )}
          {meta && !meta.llm.activo && (
            <small>En producción los valores del examen se extraen del PDF o la foto con OCR + IA generativa (Bedrock) y quedan pendientes de validar. En esta maqueta se ingresan a mano.</small>
          )}
        </div>
        <Validacion />
      </div>
    </>
  );
}

function FormExamen({ idPaciente, onListo }: { idPaciente: string; onListo: (t: string) => void }) {
  const { meta, corte } = useApp();
  const [tipo, setTipo] = useState("PHQ9");
  const [valor, setValor] = useState("");
  const [fecha, setFecha] = useState(corte);
  const [lugar, setLugar] = useState("Laboratorio privado");
  const [archivo, setArchivo] = useState<{ nombre: string; base64: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tipoMeta = meta?.tipos_medicion.find((t) => t.tipo === tipo);
  const leerArchivo = (f: File | undefined) => {
    if (!f) return setArchivo(null);
    const lector = new FileReader();
    lector.onload = () => setArchivo({ nombre: f.name, base64: String(lector.result) });
    lector.readAsDataURL(f);
  };
  const enviar = async () => {
    if (valor === "" || Number.isNaN(Number(valor))) return setError("Ingresa el valor del examen.");
    try {
      const r = await postJSON<{ respuesta: string }>("/api/canal/evidencias", {
        id_paciente: idPaciente, fecha_examen: fecha, tipo_medicion: tipo, valor: Number(valor), lugar,
        fecha_recepcion: corte, archivo_nombre: archivo?.nombre ?? null, archivo_base64: archivo?.base64 ?? null,
      });
      onListo(r.respuesta);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className="formulario-chat">
      <div className="fila">
        <select value={tipo} onChange={(e) => setTipo(e.target.value)}>
          {meta?.tipos_medicion.map((t) => <option key={t.tipo} value={t.tipo}>{t.nombre}</option>)}
        </select>
        <input type="number" step="any" placeholder={`Valor (${tipoMeta?.unidad ?? ""})`} value={valor} onChange={(e) => setValor(e.target.value)} style={{ width: 120 }} />
        <input type="date" value={fecha} max={corte} onChange={(e) => setFecha(e.target.value)} />
      </div>
      <input value={lugar} onChange={(e) => setLugar(e.target.value)} placeholder="Lugar del examen" />
      <input type="file" accept="application/pdf,image/*" onChange={(e) => leerArchivo(e.target.files?.[0])} />
      {tipoMeta && <small>Rango normal {num(tipoMeta.rango[0], 1)}–{num(tipoMeta.rango[1], 1)} {tipoMeta.unidad}</small>}
      {error && <small style={{ color: "#c0392b" }}>{error}</small>}
      <button className="boton primario" onClick={enviar}>Enviar examen</button>
    </div>
  );
}

function FormSintomas({ onEnviar }: { onEnviar: (alarma: boolean, detalle: string) => void }) {
  const [resp, setResp] = useState<boolean[]>(PREGUNTAS_ALARMA.map(() => false));
  return (
    <div className="formulario-chat">
      {PREGUNTAS_ALARMA.map((p, i) => (
        <label key={p} className="interruptor">
          <input type="checkbox" checked={resp[i]} onChange={(e) => setResp(resp.map((x, j) => (j === i ? e.target.checked : x)))} />{p}
        </label>
      ))}
      <button className="boton primario" onClick={() => {
        const si = PREGUNTAS_ALARMA.filter((_, i) => resp[i]);
        onEnviar(si.length > 0, si.length ? si.join(" / ") : "Sin señales de alarma");
      }}>Enviar respuestas</button>
      <small>Una respuesta de alarma crea una alerta para revisión clínica; no cambia la prioridad automáticamente.</small>
    </div>
  );
}

function Validacion() {
  const { corte, version, refrescar } = useApp();
  const { data, error } = useApi<{ evidencias: Registro[]; alarmas: Registro[] }>("/api/canal-pendientes", version);
  const [revisor, setRevisor] = useState("tens.turno_noche");
  const [resultados, setResultados] = useState<Registro[]>([]);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const revisar = async (tipo: "evidencias" | "mensajes", id: string, estado: "validada" | "rechazada", nombre: string) => {
    setOcupado(id);
    try {
      const r = await postJSON<Registro>(`/api/canal/${tipo}/${id}/revision`, { estado, revisado_por: revisor, corte });
      setResultados([{ ...r, id, estado, nombre }, ...resultados]);
      refrescar();
    } finally {
      setOcupado(null);
    }
  };
  return (
    <div className="pila">
      <div className="tarjeta pila">
        <h2>Bandeja de validación</h2>
        <p className="suave">TENS o enfermería, con protocolo: no hace falta el especialista. Al validar, el dato entra a la ficha consolidada y la prioridad del paciente se reevalúa de inmediato.</p>
        <label className="campo"><span>Profesional que revisa</span><input value={revisor} onChange={(e) => setRevisor(e.target.value)} /></label>
        {error && <Aviso tipo="error">{error}</Aviso>}
        {!data ? <Cargando /> : data.evidencias.length + data.alarmas.length === 0 ? (
          <Aviso tipo="info">No hay evidencia pendiente. Envía un examen o un síntoma desde el teléfono de la izquierda.</Aviso>
        ) : (
          <>
            {data.evidencias.map((e) => (
              <div key={e.id_evidencia} className="tarjeta compacta pila">
                <div className="fila entre">
                  <b>📄 {e.id_evidencia} · {e.nombre}</b>
                  <small>recibido {e.fecha_recepcion}</small>
                </div>
                <div>{e.nombre_examen} = <b>{e.valor} {e.unidad}</b> · examen del {e.fecha_examen} · {e.lugar || "lugar no indicado"}{e.archivo ? ` · archivo ${e.archivo}` : ""}</div>
                <div className="fila">
                  <button className="boton primario chico" disabled={ocupado === e.id_evidencia} onClick={() => revisar("evidencias", e.id_evidencia, "validada", e.nombre)}>Validar</button>
                  <button className="boton peligro chico" disabled={ocupado === e.id_evidencia} onClick={() => revisar("evidencias", e.id_evidencia, "rechazada", e.nombre)}>Rechazar</button>
                </div>
              </div>
            ))}
            {data.alarmas.map((m) => (
              <div key={m.id_mensaje} className="tarjeta compacta pila">
                <div className="fila entre">
                  <b>🚨 {m.id_mensaje} · {m.nombre}</b>
                  <small>{m.fecha}</small>
                </div>
                <div>{m.detalle}</div>
                <div className="fila">
                  <button className="boton primario chico" disabled={ocupado === m.id_mensaje} onClick={() => revisar("mensajes", m.id_mensaje, "validada", m.nombre)}>Confirmar alarma</button>
                  <button className="boton peligro chico" disabled={ocupado === m.id_mensaje} onClick={() => revisar("mensajes", m.id_mensaje, "rechazada", m.nombre)}>Descartar</button>
                </div>
              </div>
            ))}
          </>
        )}
      </div>
      {resultados.length > 0 && (
        <div className="tarjeta pila">
          <h3>Reevaluaciones gatilladas</h3>
          {resultados.map((r, i) => (
            <div key={i} className="aviso info">
              <b>{r.id}</b> {r.estado} · {r.nombre}: <NivelBadge nivel={r.antes.nivel_propuesto} /> (puntaje {num(r.antes.puntaje_nivel)})
              {" → "}<NivelBadge nivel={r.despues.nivel_propuesto} /> (puntaje {num(r.despues.puntaje_nivel)}){r.despues.alerta ? " · ⚠️ alerta" : ""}
              <div><small>{r.despues.motivo_principal}</small></div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
