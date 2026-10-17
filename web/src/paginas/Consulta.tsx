import { FormEvent, useEffect, useState } from "react";
import { postJSON, Registro, useApi } from "../api";
import { Aviso, Cargando, Tabla } from "../componentes/comunes";
import { useApp } from "../contexto";

/** Respuesta de POST /api/consulta (servicios/consulta_ia/servicio.py). */
interface Respuesta {
  id_pregunta: number | null;
  ruta: "texto" | "conteo" | "rechazada";
  respuesta: string;
  motivo: string;
  sql: string | null;
  columnas: string[];
  filas: (string | number | boolean | null)[][];
  n_filas: number | null;
  id_consulta_athena: string | null;
  bytes_escaneados: number | null;
  fuentes: { orden: number; tipo: string; clave: string; s3_uri: string; fragmento: string }[];
  filtros: Record<string, string>;
  guardrail_intervino: boolean;
  latencia_ms: number;
  modelo: string;
  fecha_corte: string;
}

interface Turno {
  pregunta: string;
  r: Respuesta | null;
  error?: string;
}

const EJEMPLOS = [
  "¿Cuántos pacientes de Cardiología en espera tienen un evento grave?",
  "¿Cuántas solicitudes en espera hay por especialidad?",
  "Resume la evolución de la paciente 00028",
  "¿Por qué subió la prioridad del paciente 00002?",
  "¿Cómo fue la ocupación del BOX-03 en septiembre?",
];
const RUTA: Record<Respuesta["ruta"], { etiqueta: string; clase: string }> = {
  conteo: { etiqueta: "Conteo exacto · Athena", clase: "baja" },
  texto: { etiqueta: "Texto · Base de conocimiento", clase: "media" },
  rechazada: { etiqueta: "No respondida", clase: "alta" },
};
const TIPO_DOC: Record<string, string> = {
  perfil_paciente: "Perfil", resumen_especialidad: "Resumen de especialidad", resumen_box_mes: "Box y mes",
  diccionario: "Diccionario",
};

function Estado() {
  const [version, setVersion] = useState(0);
  const { data, error } = useApi<Registro>("/api/consulta/estado", version);
  const [aviso, setAviso] = useState<string | null>(null);
  useEffect(() => {
    if (!data?.preparando) return;
    const t = window.setTimeout(() => setVersion((v) => v + 1), 10000);
    return () => window.clearTimeout(t);
  }, [data]);
  if (error) return <Aviso tipo="info">{error}</Aviso>;
  if (!data) return null;
  const kb = data.kb_vigente as Registro | null;
  const sincronizar = async () => {
    setAviso(null);
    try {
      await postJSON("/api/consulta/preparar");
      setVersion((v) => v + 1);
    } catch (e) {
      setAviso((e as Error).message);
    }
  };
  return (
    <div className="fila entre">
      <small className="suave">
        {kb ? <>Base de conocimiento con datos al <b>{String(kb.fecha_corte)}</b> ({String(kb.n_documentos)} documentos). </>
          : <>La base de conocimiento aún no tiene una sincronización completa: las preguntas de texto no se responden todavía. </>}
        Modelo: <code>{String(data.modelo)}</code>.
      </small>
      <span>
        {data.preparando ? <small>⏳ Sincronizando documentos…</small> : (
          <button className="boton chico" onClick={sincronizar} disabled={!data.kb_configurada}
            title="Regenera los documentos con los datos a la fecha de corte y los vuelve a indexar (unos minutos)">
            Sincronizar
          </button>
        )}
        {aviso && <small className="cambio-sube"> {aviso}</small>}
      </span>
    </div>
  );
}

function Detalle({ r }: { r: Respuesta }) {
  return (
    <div className="pila">
      {r.ruta === "conteo" && r.columnas.length > 0 && !(r.columnas.length === 1 && r.filas.length === 1) && (
        <Tabla filas={r.filas.map((f) => Object.fromEntries(r.columnas.map((c, i) => [c, f[i]])))} />
      )}
      {r.sql && (
        <details open={r.ruta === "conteo"}>
          <summary>SQL {r.ruta === "conteo" ? "ejecutado en Athena" : "generado (no se ejecutó)"}</summary>
          <pre className="codigo">{r.sql}</pre>
          {r.ruta === "conteo" && (
            <small className="suave">
              {r.n_filas} fila(s) · {((r.bytes_escaneados ?? 0) / 1e6).toFixed(2)} MB escaneados · consulta {r.id_consulta_athena}
            </small>
          )}
        </details>
      )}
      {r.fuentes.length > 0 && (
        <details>
          <summary>{r.fuentes.length} fuente(s) citada(s)</summary>
          <ol className="fuentes">
            {r.fuentes.map((f) => (
              <li key={f.orden}>
                <b>{TIPO_DOC[f.tipo] ?? f.tipo} · {f.clave}</b>
                <pre className="fragmento">{f.fragmento}</pre>
              </li>
            ))}
          </ol>
        </details>
      )}
      <small className="suave">
        {(r.latencia_ms / 1000).toFixed(1)} s · datos al {r.fecha_corte}
        {Object.keys(r.filtros).length > 0 && <> · filtros: {Object.entries(r.filtros).map(([k, v]) => `${k}=${v}`).join(", ")}</>}
        {r.ruta === "rechazada" && r.motivo && <> · motivo: {r.motivo}</>}
      </small>
    </div>
  );
}

export default function Consulta() {
  const { meta } = useApp();
  const [texto, setTexto] = useState("");
  const [turnos, setTurnos] = useState<Turno[]>([]);
  const [enviando, setEnviando] = useState(false);
  const historial = useApi<Registro[]>("/api/consulta/historial");

  if (meta && meta.base_de_datos !== "rds")
    return (
      <div className="tarjeta pila">
        <h2>Consulta en lenguaje natural</h2>
        <Aviso tipo="info">La consulta usa Amazon Bedrock, Athena y la base de datos (RDS): está disponible en la app desplegada en AWS.</Aviso>
      </div>
    );

  const preguntar = async (pregunta: string) => {
    const q = pregunta.trim();
    if (q.length < 3 || enviando) return;
    setEnviando(true);
    setTexto("");
    setTurnos((t) => [{ pregunta: q, r: null }, ...t]);
    try {
      const r = await postJSON<Respuesta>("/api/consulta", { texto: q });
      setTurnos((t) => [{ pregunta: q, r }, ...t.slice(1)]);
    } catch (e) {
      setTurnos((t) => [{ pregunta: q, r: null, error: (e as Error).message }, ...t.slice(1)]);
    } finally {
      setEnviando(false);
    }
  };
  const enviar = (e: FormEvent) => {
    e.preventDefault();
    preguntar(texto);
  };

  return (
    <>
      <div className="encabezado">
        <h1>🔎 Consulta</h1>
        <p>
          Pregunta en lenguaje natural. Los conteos se responden con SQL exacto en Athena (se muestra el SQL); los resúmenes,
          con la base de conocimiento de perfiles y resúmenes, citando los fragmentos. La herramienta solo lee: no modifica
          datos ni prioridades, no diagnostica y no entrega datos que identifiquen a una persona.
        </p>
      </div>
      <div className="tarjeta pila">
        <Estado />
        <form className="fila" onSubmit={enviar}>
          <input className="consulta-entrada" value={texto} onChange={(e) => setTexto(e.target.value)} maxLength={500}
            placeholder="Ej.: ¿Cuántos pacientes de Cardiología en espera tienen un evento grave?" />
          <button className="boton primario" disabled={enviando || texto.trim().length < 3}>{enviando ? "Consultando…" : "Preguntar"}</button>
        </form>
        <div className="fila">
          {EJEMPLOS.map((q) => <button key={q} className="boton chico" onClick={() => preguntar(q)} disabled={enviando}>{q}</button>)}
        </div>
      </div>
      {turnos.map((t, i) => (
        <div key={turnos.length - i} className="tarjeta pila">
          <div className="fila entre">
            <b>{t.pregunta}</b>
            {t.r && <span className={`nivel ${RUTA[t.r.ruta].clase}`}>{RUTA[t.r.ruta].etiqueta}</span>}
          </div>
          {!t.r && !t.error && <Cargando texto="Consultando…" />}
          {t.error && <Aviso tipo="error">{t.error}</Aviso>}
          {t.r && (
            <>
              {t.r.ruta === "rechazada" ? <Aviso tipo="atencion">{t.r.respuesta}</Aviso> : <p className="respuesta-ia">{t.r.respuesta}</p>}
              <Detalle r={t.r} />
            </>
          )}
        </div>
      ))}
      <div className="tarjeta pila">
        <h3>Preguntas anteriores</h3>
        {historial.error && <Aviso tipo="info">{historial.error}</Aviso>}
        {!historial.data ? <Cargando /> : (
          <Tabla filas={historial.data} vacia="Aún no hay preguntas." columnas={[
            { clave: "creada_en", titulo: "Fecha", render: (f) => String(f.creada_en).slice(0, 16).replace("T", " ") },
            { clave: "texto", titulo: "Pregunta" }, { clave: "ruta", titulo: "Ruta" },
            { clave: "respuesta", titulo: "Respuesta", render: (f) => String(f.respuesta).slice(0, 140) },
            { clave: "latencia_ms", titulo: "s", num: true, render: (f) => ((f.latencia_ms as number) / 1000).toFixed(1) },
          ]} />
        )}
        <small className="suave">Cada pregunta queda registrada con su ruta, el SQL o las fuentes, y la persona que preguntó.</small>
      </div>
    </>
  );
}
