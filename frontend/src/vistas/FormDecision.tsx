import { useState, type FormEvent } from "react";
import { enviar, ErrorApi } from "../api";
import { ETIQUETA_PRIORIDAD, PRIORIDADES } from "../textos";
import type { HistorialAviso, Prioridad, SolicitudDecision } from "../tipos";

const PATRON_MEDICO = /^[A-Za-z0-9-]{3,32}$/;
type Decision = SolicitudDecision["decision"];

interface Props {
  alertaId: string;
  historial: HistorialAviso;
  onRegistrada: () => void;
}

export default function FormDecision({ alertaId, historial, onRegistrada }: Props) {
  const [medico, setMedico] = useState("");
  const [decision, setDecision] = useState<Decision | "">("");
  const [prioridad, setPrioridad] = useState<Prioridad | "">("");
  const [comentario, setComentario] = useState("");
  const [errores, setErrores] = useState<Record<string, string>>({});
  const [errorServidor, setErrorServidor] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function guardar(e: FormEvent) {
    e.preventDefault();
    const nuevos: Record<string, string> = {};
    if (!PATRON_MEDICO.test(medico)) nuevos.medico = "Use 3 a 32 letras, números o guiones.";
    if (!decision) nuevos.decision = "Seleccione una decisión.";
    if (!prioridad) nuevos.prioridad = "Seleccione la prioridad final decidida.";
    setErrores(nuevos);
    setExito(null);
    setErrorServidor(null);
    if (Object.keys(nuevos).length || !decision || !prioridad) return;
    setEnviando(true);
    try {
      const r = await enviar<{ nota: string }>(`/api/avisos/${alertaId}/decision`, {
        medico_id: medico,
        decision,
        prioridad_final: prioridad,
        comentario,
      } satisfies SolicitudDecision);
      setExito(r.nota);
      onRegistrada();
    } catch (err) {
      setErrorServidor(err instanceof ErrorApi ? err.message : "Error inesperado.");
    } finally {
      setEnviando(false);
    }
  }

  const vigente = historial.decisiones.at(-1);

  return (
    <section aria-labelledby="titulo-decision">
      <h2 id="titulo-decision">Decisión del profesional</h2>
      <p className="nota">
        La decisión queda registrada en auditoría. No modifica la prioridad de la solicitud ni genera citaciones.
      </p>
      {vigente && (
        <p>
          Decisión vigente: <strong>{vigente.decision}</strong>, prioridad final {vigente.prioridad_final}, por{" "}
          {vigente.medico_id} ({vigente.timestamp}).
        </p>
      )}
      <form onSubmit={guardar} noValidate>
        <div className="campo">
          <label htmlFor="medico-id">Identificador del profesional</label>
          <input
            id="medico-id"
            value={medico}
            onChange={(e) => setMedico(e.target.value)}
            maxLength={32}
            aria-invalid={errores.medico ? "true" : "false"}
            aria-describedby="medico-nota medico-error"
            autoComplete="off"
          />
          <span id="medico-nota" className="ayuda">
            Identificador declarado, sin verificación.
          </span>
          <span id="medico-error" className="error-campo">
            {errores.medico}
          </span>
        </div>

        <fieldset className="campo" aria-describedby="decision-error">
          <legend>Decisión sobre la propuesta</legend>
          {(["aceptada", "modificada", "rechazada"] as Decision[]).map((d) => (
            <label key={d} className="opcion">
              <input type="radio" name="decision" value={d} checked={decision === d} onChange={() => setDecision(d)} /> {d}
            </label>
          ))}
          <span id="decision-error" className="error-campo">
            {errores.decision}
          </span>
        </fieldset>

        <div className="campo">
          <label htmlFor="prioridad-final">Prioridad final decidida por el profesional</label>
          <select
            id="prioridad-final"
            value={prioridad}
            onChange={(e) => setPrioridad(e.target.value as Prioridad | "")}
            aria-invalid={errores.prioridad ? "true" : "false"}
            aria-describedby="prioridad-error"
          >
            <option value="">Seleccione…</option>
            {PRIORIDADES.map((p) => (
              <option key={p} value={p}>
                {ETIQUETA_PRIORIDAD[p]}
              </option>
            ))}
          </select>
          <span id="prioridad-error" className="error-campo">
            {errores.prioridad}
          </span>
        </div>

        <div className="campo">
          <label htmlFor="comentario">Comentario (opcional)</label>
          <textarea id="comentario" value={comentario} maxLength={1000} rows={3} onChange={(e) => setComentario(e.target.value)} />
        </div>

        <button type="submit" className="primario" disabled={enviando}>
          Registrar decisión en auditoría
        </button>
      </form>
      <div aria-live="polite">{exito && <p className="exito">{exito}</p>}</div>
      {errorServidor && (
        <p role="alert" className="error">
          {errorServidor}
        </p>
      )}

      {historial.decisiones.length > 0 && (
        <>
          <h3>Decisiones registradas</h3>
          <ul>
            {historial.decisiones.map((d, k) => (
              <li key={k}>
                {d.timestamp}: {d.medico_id} · {d.decision} · prioridad final {d.prioridad_final}
                {d.comentario ? ` · ${d.comentario}` : ""}
              </li>
            ))}
          </ul>
        </>
      )}
      {historial.analisis.length > 0 && (
        <>
          <h3>Análisis registrados</h3>
          <ul>
            {historial.analisis.map((a, k) => (
              <li key={k}>
                {a.timestamp}: inferencia {a.origen_inferencia} · prioridad sugerida {a.prioridad_sugerida ?? "—"}
              </li>
            ))}
          </ul>
        </>
      )}
      {historial.lineas_invalidas > 0 && (
        <p className="advertencia">{historial.lineas_invalidas} líneas de auditoría no se pudieron leer.</p>
      )}
    </section>
  );
}
