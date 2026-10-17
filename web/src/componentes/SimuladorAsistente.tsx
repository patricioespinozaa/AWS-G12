import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { postJSON, Registro, useApi } from "../api";
import { Aviso, Tabla } from "./comunes";

/** Respuesta del núcleo del asistente (servicios/asistente/nucleo.py, Salida). */
interface Salida {
  texto: string;
  id_conversacion: number;
  nivel: "ninguna" | "basica" | "reforzada";
  herramientas: string[];
  divulgaciones: number;
  derivacion: string | null;
  codigo_demo: string | null;
  latencia_ms: number;
}

interface Linea {
  quien: "paciente" | "asistente";
  texto: string;
  detalle?: string;
}

const NIVEL: Record<Salida["nivel"], string> = {
  ninguna: "sin verificar", basica: "verificación básica (número registrado)", reforzada: "verificación reforzada (código)",
};

function nuevaSesion() {
  return `s${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

/** El mismo núcleo que WhatsApp, desde la app (F0010): la demo funciona aunque WhatsApp no esté aprobado. */
export function SimuladorAsistente() {
  const contactos = useApi<Registro[]>("/api/asistente/contactos-demo");
  const [telefono, setTelefono] = useState("");
  const [sesion, setSesion] = useState(nuevaSesion);
  const [lineas, setLineas] = useState<Linea[]>([]);
  const [ultima, setUltima] = useState<Salida | null>(null);
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chat = useRef<HTMLDivElement>(null);
  useEffect(() => { chat.current?.scrollTo(0, chat.current.scrollHeight); }, [lineas]);
  useEffect(() => {
    if (!telefono && contactos.data?.length) setTelefono(String(contactos.data[0].telefono));
  }, [contactos.data, telefono]);
  const elegido = useMemo(() => contactos.data?.find((c) => c.telefono === telefono), [contactos.data, telefono]);

  const reiniciar = (tel = telefono) => {
    setTelefono(tel);
    setSesion(nuevaSesion());
    setLineas([]);
    setUltima(null);
    setError(null);
  };
  const enviar = async (e?: FormEvent, mensaje = texto) => {
    e?.preventDefault();
    const q = mensaje.trim();
    if (!q || enviando) return;
    setEnviando(true);
    setTexto("");
    setError(null);
    setLineas((l) => [...l, { quien: "paciente", texto: q }]);
    try {
      const s = await postJSON<Salida>("/api/asistente/simulador", { sesion, telefono, texto: q });
      const detalle = [
        s.herramientas.length ? `herramientas: ${s.herramientas.join(", ")}` : "",
        s.divulgaciones ? `${s.divulgaciones} dato(s) registrados en canal.divulgacion` : "",
        s.derivacion ? `derivado a una persona (${s.derivacion})` : "",
        `${(s.latencia_ms / 1000).toFixed(1)} s`,
      ].filter(Boolean).join(" · ");
      setLineas((l) => [...l, { quien: "asistente", texto: s.texto, detalle }]);
      setUltima(s);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setEnviando(false);
    }
  };

  if (contactos.error) return <Aviso tipo="info">{contactos.error}</Aviso>;
  return (
    <div className="tarjeta pila">
      <div className="fila entre">
        <h3>Asistente del paciente · simulador de WhatsApp</h3>
        <small className="suave">{ultima ? NIVEL[ultima.nivel] : "conversación nueva"}</small>
      </div>
      <p className="suave">
        Usa el mismo núcleo que WhatsApp: verificación de identidad, herramientas sobre las vistas del paciente y
        auditoría de cada dato informado. Los números son ficticios (contactos de demo); el código de verificación, que en
        producción llega por SMS, se muestra aquí.
      </p>
      <div className="fila">
        <label className="campo"><span>Escribe como</span>
          <select value={telefono} onChange={(e) => reiniciar(e.target.value)}>
            {(contactos.data ?? []).map((c) => (
              <option key={String(c.telefono)} value={String(c.telefono)}>
                {String(c.id_paciente)} · {String(c.patron ?? "")} · *** {String(c.telefono).slice(-4)}
              </option>
            ))}
            <option value="+56911112222">Número no registrado · *** 2222</option>
          </select>
        </label>
        <button className="boton chico" onClick={() => reiniciar()}>Nueva conversación</button>
      </div>
      <div className="chat" ref={chat}>
        {lineas.length === 0 && <p className="suave">Escribe un mensaje, por ejemplo: "¿Tengo citas?" o "¿En qué lugar de la lista voy?".</p>}
        {lineas.map((l, i) => (
          <div key={i} className={`burbuja ${l.quien === "paciente" ? "paciente" : "hospital"}`}>
            <div>{l.texto}</div>
            {l.detalle && <small className="suave">{l.detalle}</small>}
          </div>
        ))}
      </div>
      {ultima?.codigo_demo && (
        <Aviso tipo="info">Código enviado al número registrado (en la demo se muestra aquí): <b>{ultima.codigo_demo}</b></Aviso>
      )}
      {error && <Aviso tipo="error">{error}</Aviso>}
      <form className="fila" onSubmit={enviar}>
        <input className="consulta-entrada" value={texto} onChange={(e) => setTexto(e.target.value)} maxLength={1000}
          placeholder={elegido ? `Mensaje de ${String(elegido.id_paciente)}…` : "Mensaje…"} />
        <button className="boton primario" disabled={enviando || !texto.trim()}>{enviando ? "…" : "Enviar"}</button>
      </form>
      <div className="fila">
        {["¿Tengo citas?", "¿En qué lugar de la lista voy?", "¿Qué registros tienen de mí?", "Confirmo mi asistencia",
          "¿Qué debo llevar a la cita?", "Me duele mucho el pecho desde ayer", "Quiero hablar con una persona"].map((q) => (
          <button key={q} className="boton chico" disabled={enviando} onClick={() => enviar(undefined, q)}>{q}</button>
        ))}
      </div>
    </div>
  );
}

/** Casos que el asistente pasó a una persona: alarmas, verificación fallida, pide persona, preguntas clínicas. */
export function Derivaciones() {
  const [version, setVersion] = useState(0);
  const { data, error } = useApi<Registro[]>("/api/asistente/derivaciones", version);
  if (error) return null;
  const actualizar = async (id: number, estado: string) => {
    await postJSON(`/api/asistente/derivaciones/${id}`, { estado });
    setVersion((v) => v + 1);
  };
  return (
    <div className="tarjeta pila">
      <h3>Derivaciones a una persona</h3>
      <Tabla filas={data ?? []} vacia="No hay derivaciones." columnas={[
        { clave: "creada_en", titulo: "Fecha", render: (f) => String(f.creada_en).slice(0, 16).replace("T", " ") },
        { clave: "urgencia", titulo: "Urgencia", render: (f) => <span className={`nivel ${f.urgencia === "inmediata" ? "alta" : f.urgencia === "mismo_dia" ? "media" : "baja"}`}>{String(f.urgencia)}</span> },
        { clave: "motivo", titulo: "Motivo" }, { clave: "canal", titulo: "Canal" },
        { clave: "id_paciente", titulo: "Paciente", render: (f) => String(f.id_paciente ?? "no identificado") },
        { clave: "ultimo_mensaje", titulo: "Último mensaje", render: (f) => String(f.ultimo_mensaje ?? "").slice(0, 90) },
        { clave: "estado", titulo: "Estado" },
        { clave: "acciones", titulo: "", render: (f) => (f.estado === "pendiente" || f.estado === "en_gestion") ? (
          <span className="fila">
            {f.estado === "pendiente" && <button className="boton chico" onClick={() => actualizar(Number(f.id_derivacion), "en_gestion")}>Tomar</button>}
            <button className="boton chico" onClick={() => actualizar(Number(f.id_derivacion), "resuelta")}>Resuelta</button>
          </span>) : null },
      ]} />
    </div>
  );
}
