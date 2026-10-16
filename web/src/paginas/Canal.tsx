import {
  AlertOctagon, Bot, Check, ClipboardCheck, FileUp, Headset, Inbox, MessageCircle, PhoneOff, Smartphone, Stethoscope, X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { postJSON, Registro, useApi } from "../api";
import { Derivaciones, SimuladorAsistente } from "../componentes/SimuladorAsistente";
import { subirExamen, ValidacionExamen } from "../componentes/ValidacionExamen";
import { Aviso, Cargando, Disponibilidad, Encabezado, NivelBadge, Pasos, Pestanas } from "../componentes/comunes";
import { useApp } from "../contexto";
import { num } from "../utils";

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

type IdPestana = "validar" | "asistente" | "derivaciones" | "simular";

export default function Canal() {
  const { meta, version } = useApp();
  const pendientes = useApi<{ evidencias: Registro[]; alarmas: Registro[] }>("/api/canal-pendientes", version);
  const n = (pendientes.data?.evidencias.length ?? 0) + (pendientes.data?.alarmas.length ?? 0);
  const conAsistente = meta?.base_de_datos === "rds";
  const [pestana, setPestana] = useState<IdPestana>("validar");
  const opciones: { id: IdPestana; etiqueta: string; icono: typeof Inbox; contador?: number }[] = [
    { id: "validar", etiqueta: "Por validar", icono: ClipboardCheck, contador: n },
    ...(conAsistente ? [
      { id: "asistente" as const, etiqueta: "Asistente (WhatsApp)", icono: Bot },
      { id: "derivaciones" as const, etiqueta: "Derivaciones", icono: Headset },
    ] : []),
    { id: "simular", etiqueta: "Simular mensajes del paciente", icono: Smartphone },
  ];
  return (
    <>
      <Encabezado icono={MessageCircle} titulo="Canal del paciente"
        descripcion="Lo que envían los pacientes (exámenes, síntomas, confirmaciones) entra pendiente: cuenta para la prioridad solo cuando lo validas." />
      <Pestanas opciones={opciones} activa={pestana} onCambio={setPestana} />
      {pestana === "validar" && <Validacion />}
      {pestana === "asistente" && <SimuladorAsistente />}
      {pestana === "derivaciones" && <Derivaciones />}
      {pestana === "simular" && <SimularPaciente onEnviado={() => setPestana("validar")} />}
    </>
  );
}

/** Simula lo que un paciente envía por el canal, para probar la validación. */
function SimularPaciente({ onEnviado }: { onEnviado: () => void }) {
  const { corte, version, refrescar } = useApp();
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
      texto: e.tipo_medicion ? `Examen ${e.tipo_medicion} = ${e.valor} (${e.fecha_examen}, ${e.lugar || "lugar no indicado"})` : `Examen enviado (${e.lugar || "lugar no indicado"})`,
      estado: e.estado })),
  ].sort((a, b) => a.fecha.localeCompare(b.fecha)) : [];

  return (
    <div className="grid-lateral">
      <div className="pila">
        <Pasos actual={-1} pasos={[
          { titulo: "Elige un paciente", detalle: "de la lista de espera" },
          { titulo: "Envía un mensaje o examen", detalle: "desde el teléfono" },
          { titulo: "Valídalo en «Por validar»", detalle: "recién ahí se reevalúa" },
        ]} />
        <label className="campo"><span>Paciente</span>
          <select value={idPaciente} onChange={(e) => setIdPaciente(e.target.value)}>
            {(lista.data ?? []).map((s) => (
              <option key={s.id_paciente} value={s.id_paciente}>{s.nombre} · {s.id_paciente} · {s.especialidad}{s.caso_referencia ? ` · ★ ${s.caso_referencia}` : ""}</option>
            ))}
          </select>
        </label>
        {data && (
          <div className="tarjeta compacta pila-compacta">
            <span className="suave">Disponibilidad para box al {corte}</span>
            <Disponibilidad estado={data.disponibilidad.estado} accion={data.disponibilidad.accion} />
            {data.disponibilidad.accion && <small>{data.disponibilidad.accion}</small>}
          </div>
        )}
        {respuesta && (
          <Aviso tipo="exito">
            Enviado. <button className="boton chico" onClick={onEnviado}><ClipboardCheck size={14} /> Ir a validar</button>
          </Aviso>
        )}
      </div>
      <div>
        {error && <Aviso tipo="error">{error}</Aviso>}
        {!data ? <Cargando /> : (
          <div className="telefono">
            <div className="telefono-cabecera">
              <div className="marca-logo" style={{ width: 30, height: 30 }}><MessageCircle size={16} /></div>
              <div><b>Hospital La Florida</b><small>Lista de espera de especialidades</small></div>
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
              <button className="boton" onClick={() => enviarMensaje("confirma_asistencia", "Confirmo que asistiré")}><Check size={14} /> Confirmo</button>
              <button className="boton" onClick={() => enviarMensaje("no_puede_asistir", "No puedo en la fecha ofrecida")}><X size={14} /> No puedo</button>
              <button className={`boton${modo === "examen" ? " activo" : ""}`} onClick={() => setModo(modo === "examen" ? "" : "examen")}><FileUp size={14} /> Examen</button>
              <button className={`boton${modo === "sintoma" ? " activo" : ""}`} onClick={() => setModo(modo === "sintoma" ? "" : "sintoma")}><Stethoscope size={14} /> Síntomas</button>
              <button className="boton" onClick={() => enviarMensaje("sin_respuesta", "")} title="Simula que el paciente no responde a los mensajes"><PhoneOff size={14} /> Sin respuesta</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function FormExamen({ idPaciente, onListo }: { idPaciente: string; onListo: (t: string) => void }) {
  const { meta, corte } = useApp();
  const [tipo, setTipo] = useState("PHQ9");
  const [valor, setValor] = useState("");
  const [fecha, setFecha] = useState(corte);
  const [lugar, setLugar] = useState("Laboratorio privado");
  const [archivo, setArchivo] = useState<{ nombre: string; base64: string } | null>(null);
  const [archivoDirecto, setArchivoDirecto] = useState<File | null>(null);
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const directo = meta?.base_de_datos === "rds";             // F0012: subida a S3 y lectura asistida
  const tipoMeta = meta?.tipos_medicion.find((t) => t.tipo === tipo);
  const leerArchivo = (f: File | undefined) => {
    if (!f) return setArchivo(null);
    const lector = new FileReader();
    lector.onload = () => setArchivo({ nombre: f.name, base64: String(lector.result) });
    lector.readAsDataURL(f);
  };
  const enviar = async () => {
    if (directo) {
      if (!archivoDirecto) return setError("Elige el PDF o la foto del examen.");
      setSubiendo(true);
      try {
        onListo(await subirExamen(idPaciente, archivoDirecto, lugar));
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setSubiendo(false);
      }
      return;
    }
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
    directo ? (
      <div className="formulario-chat">
        <input type="file" accept="application/pdf,image/jpeg,image/png" onChange={(e) => setArchivoDirecto(e.target.files?.[0] ?? null)} />
        <input value={lugar} onChange={(e) => setLugar(e.target.value)} placeholder="Lugar del examen" />
        <small>El archivo va directo a S3, cifrado. Se escanea, se lee con IA y una persona confirma los datos antes de usarlos.</small>
        {error && <small style={{ color: "#c0392b" }}>{error}</small>}
        <button className="boton primario" onClick={enviar} disabled={subiendo}>{subiendo ? "Subiendo…" : "Enviar examen"}</button>
      </div>
    ) : (
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
    )
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
  const [resultados, setResultados] = useState<Registro[]>([]);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [falla, setFalla] = useState<string | null>(null);
  const revisar = async (tipo: "evidencias" | "mensajes", id: string, estado: "validada" | "rechazada", nombre: string,
                         valores: Registro = {}) => {
    setOcupado(id);
    setFalla(null);
    try {
      const r = await postJSON<Registro>(`/api/canal/${tipo}/${id}/revision`, { estado, corte, ...valores });
      setResultados([{ ...r, id, estado, nombre }, ...resultados]);
      refrescar();
    } catch (e) {
      setFalla((e as Error).message);
    } finally {
      setOcupado(null);
    }
  };
  return (
    <div className="pila">
      <div className="tarjeta pila">
        <div className="tarjeta-titulo">
          <h2><ClipboardCheck size={18} /> Por validar</h2>
          <small className="suave">Al validar, el dato entra a la ficha y la prioridad se reevalúa de inmediato.</small>
        </div>
        {error && <Aviso tipo="error">{error}</Aviso>}
        {falla && <Aviso tipo="error">{falla}</Aviso>}
        {!data ? <Cargando /> : data.evidencias.length + data.alarmas.length === 0 ? (
          <Aviso tipo="exito">Nada pendiente de validar.</Aviso>
        ) : (
          <>
            {data.evidencias.map((e) => (
              <ValidacionExamen key={e.id_evidencia} e={e} ocupado={ocupado === e.id_evidencia}
                onRevisar={(estado, valores) => revisar("evidencias", e.id_evidencia, estado, e.nombre, valores)} />
            ))}
            {data.alarmas.map((m) => (
              <div key={m.id_mensaje} className="tarjeta compacta pila">
                <div className="fila entre">
                  <b className="transicion"><AlertOctagon size={16} className="cambio-sube" /> Síntoma de alarma · {m.nombre}</b>
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
          <h3>Reevaluaciones de esta sesión</h3>
          {resultados.map((r, i) => (
            <div key={i} className="aviso info">
              <b>{r.id}</b> {r.estado} · {r.nombre}: <NivelBadge nivel={r.antes.nivel_propuesto} /> (puntaje {num(r.antes.puntaje_nivel)})
              {" → "}<NivelBadge nivel={r.despues.nivel_propuesto} /> (puntaje {num(r.despues.puntaje_nivel)}){r.despues.alerta ? " · con alerta" : ""}
              <div><small>{r.despues.motivo_principal}</small></div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
