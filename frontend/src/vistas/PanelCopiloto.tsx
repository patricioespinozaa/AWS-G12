import { useState } from "react";
import { enviar, ErrorApi } from "../api";
import DialogoConfirmacion from "../componentes/DialogoConfirmacion";
import EnlaceEvidencia, { ListaEvidencia } from "../componentes/EnlaceEvidencia";
import EtiquetaOrigen from "../componentes/EtiquetaOrigen";
import { InsigniaPrioridad } from "../componentes/Insignias";
import type { AnalisisCopiloto, EstadoServidor, IndiceEvidencia, OrigenInferencia, RespuestaAnalisis } from "../tipos";

interface Props {
  pid: string;
  corte: string;
  estado: EstadoServidor;
  evidencia: IndiceEvidencia;
  previo: AnalisisCopiloto | null;
  origenPrevio: OrigenInferencia | null;
  onAnalizado: () => void;
}

function Verificacion({ a }: { a: AnalisisCopiloto }) {
  const v = a.meta?.verificacion;
  if (!v) return <p className="advertencia">Sin verificación del backend: revisar con cautela.</p>;
  return (
    <section aria-labelledby="titulo-verificacion" className={v.requiere_atencion ? "verificacion atencion" : "verificacion"}>
      <h4 id="titulo-verificacion">Verificación automática de citas</h4>
      <p>{v.requiere_atencion ? "Requiere atención antes de usar esta propuesta." : "Sin observaciones de verificación."}</p>
      <ul>
        {v.citas_no_verificables === null ? (
          <li>Las citas no pudieron verificarse.</li>
        ) : (
          v.citas_no_verificables.length > 0 && <li>Citas no verificables: {v.citas_no_verificables.join(", ")}</li>
        )}
        {v.documentados_sin_cita.length > 0 && <li>Hallazgos documentados sin cita: {v.documentados_sin_cita.join("; ")}</li>}
        {v.discrepancias_motor.map((d) => (
          <li key={d}>Discrepancia con el motor: {d}</li>
        ))}
        {v.campos_faltantes.length > 0 && <li>Campos faltantes: {v.campos_faltantes.join(", ")}</li>}
      </ul>
    </section>
  );
}

function Propuesta({ a, origen, evidencia }: { a: AnalisisCopiloto; origen: OrigenInferencia; evidencia: IndiceEvidencia }) {
  return (
    <article className="propuesta" aria-labelledby="titulo-propuesta">
      <EtiquetaOrigen origen={origen} modelo={a.meta?.model} />
      <h3 id="titulo-propuesta">Propuesta para revisión profesional — no aplicada</h3>
      {a.resumen && <p>{a.resumen}</p>}
      <dl className="ficha">
        <dt>Prioridad sugerida (propuesta)</dt>
        <dd>
          <InsigniaPrioridad valor={a.prioridad_sugerida} />
        </dd>
        <dt>¿Coincide con el motor de reglas?</dt>
        <dd>{a.acuerdo_con_motor_reglas === null ? "No declarado" : a.acuerdo_con_motor_reglas ? "Sí" : "No"}</dd>
        <dt>Confianza declarada (cualitativa, no es probabilidad)</dt>
        <dd>{a.confianza ?? "No declarada"}</dd>
        {a.relacion_con_derivacion && (
          <>
            <dt>Relación con la derivación</dt>
            <dd>{a.relacion_con_derivacion}</dd>
          </>
        )}
        {a.justificacion && (
          <>
            <dt>Justificación</dt>
            <dd>{a.justificacion}</dd>
          </>
        )}
      </dl>

      <h4>Hallazgos</h4>
      {a.hallazgos.length === 0 ? (
        <p>Sin hallazgos registrados.</p>
      ) : (
        <ul>
          {a.hallazgos.map((h, k) => (
            <li key={k}>
              <span className={`insignia hallazgo-${h.tipo}`}>
                {h.tipo === "documentado" ? "Documentado" : "Inferido — sin registro directo"}
              </span>{" "}
              {h.hallazgo}
              <ListaEvidencia ids={h.registro_ids} evidencia={evidencia} />
            </li>
          ))}
        </ul>
      )}

      {a.linea_tiempo_relevante.length > 0 && (
        <>
          <h4>Registros relevantes</h4>
          <ul>
            {a.linea_tiempo_relevante.map((e, k) => (
              <li key={k}>
                {e.fecha ?? "sin fecha"}: {e.descripcion}{" "}
                {e.registro_id ? <EnlaceEvidencia id={e.registro_id} evidencia={evidencia} /> : "Sin registro citado"}
              </li>
            ))}
          </ul>
        </>
      )}

      {a.inconsistencias_datos.length > 0 && (
        <>
          <h4>Inconsistencias de datos</h4>
          <ul>
            {a.inconsistencias_datos.map((i, k) => (
              <li key={k}>
                {i.descripcion}
                <ListaEvidencia ids={i.registro_ids} evidencia={evidencia} />
              </li>
            ))}
          </ul>
        </>
      )}

      {a.riesgo_poblacional && (
        <>
          <h4>Contexto poblacional</h4>
          <p>{a.riesgo_poblacional}</p>
          <p className="nota">Texto descriptivo de cohortes; no es probabilidad individual.</p>
        </>
      )}
      {a.propuesta_agenda && (
        <>
          <h4>Propuesta de agenda</h4>
          <p>{a.propuesta_agenda}</p>
          <p className="nota">No genera citación.</p>
        </>
      )}
      {a.acciones_sugeridas.length > 0 && (
        <>
          <h4>Acciones sugeridas para revisión</h4>
          <ul>
            {a.acciones_sugeridas.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </>
      )}
      {a.datos_faltantes.length > 0 && (
        <>
          <h4>Datos faltantes</h4>
          <ul>
            {a.datos_faltantes.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </>
      )}
      {a.nota_preconsulta && (
        <>
          <h4>Nota preconsulta (borrador)</h4>
          <p>{a.nota_preconsulta}</p>
        </>
      )}
      <Verificacion a={a} />
    </article>
  );
}

export default function PanelCopiloto({ pid, corte, estado, evidencia, previo, origenPrevio, onAnalizado }: Props) {
  const [resultado, setResultado] = useState<RespuestaAnalisis | null>(null);
  const [error, setError] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [dialogo, setDialogo] = useState(false);
  const real = estado.requiere_confirmacion_envio;

  async function solicitar(confirmado: boolean) {
    setDialogo(false);
    setEnviando(true);
    setError(null);
    try {
      const r = await enviar<RespuestaAnalisis>(`/api/pacientes/${pid}/analisis`, {
        fecha_corte: corte,
        confirmar_envio_api_real: confirmado,
      });
      setResultado(r);
      onAnalizado();
    } catch (e) {
      const err = e instanceof ErrorApi ? e : new ErrorApi(0, "desconocido", "Error inesperado.");
      if (err.codigo === "confirmacion_requerida") setDialogo(true);
      else setError(err);
    } finally {
      setEnviando(false);
    }
  }

  const mostrado = resultado?.analisis ?? previo;
  const origen = resultado?.origen_inferencia ?? origenPrevio;

  return (
    <section aria-labelledby="titulo-copiloto">
      <h2 id="titulo-copiloto">Copiloto: propuesta con evidencia</h2>
      <p className="nota">
        Modo de inferencia del servidor: <strong>{real ? "real (API externa)" : "simulada (sin IA)"}</strong>. La IA
        organiza antecedentes y propone revisión; no diagnostica ni cambia prioridades.
      </p>
      <button type="button" className="primario" disabled={enviando} onClick={() => (real ? setDialogo(true) : solicitar(false))}>
        Solicitar propuesta del copiloto
      </button>
      <div aria-live="polite">{enviando && <p className="cargando">Generando propuesta…</p>}</div>
      {error && (
        <div role="alert" className="error">
          <p>{error.message}</p>
          <button type="button" onClick={() => (real ? setDialogo(true) : solicitar(false))}>
            Reintentar
          </button>
        </div>
      )}
      {!resultado && previo && <p className="nota">Mostrando el último análisis registrado en auditoría.</p>}
      {mostrado && origen && <Propuesta a={mostrado} origen={origen} evidencia={resultado?.evidencia ?? evidencia} />}
      <DialogoConfirmacion abierto={dialogo} onConfirmar={() => solicitar(true)} onCancelar={() => setDialogo(false)} />
    </section>
  );
}
