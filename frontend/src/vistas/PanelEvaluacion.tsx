import { ListaEvidencia } from "../componentes/EnlaceEvidencia";
import { InsigniaPrioridad, InsigniaTipo } from "../componentes/Insignias";
import { TEXTO_CITA_ASISTIDA, TEXTO_GESTION } from "../textos";
import type { Evaluacion, IndiceEvidencia } from "../tipos";
import { textoExclusion } from "./VistaLista";

interface Props {
  evaluacion: Evaluacion;
  evidencia: IndiceEvidencia;
  fechaReferencia: string;
}

export default function PanelEvaluacion({ evaluacion: ev, evidencia, fechaReferencia }: Props) {
  return (
    <section aria-labelledby="titulo-evaluacion">
      <h2 id="titulo-evaluacion">Evaluación del motor de reglas</h2>
      <p>
        <InsigniaTipo valor={ev.tipo} />
      </p>
      {ev.tipo === "exclusion" ? (
        <p>{textoExclusion(ev, fechaReferencia)}</p>
      ) : (
        <>
          <dl className="ficha">
            <dt>Prioridad inicial</dt>
            <dd>
              <InsigniaPrioridad valor={ev.prioridad_inicial} />
            </dd>
            <dt>Prioridad calculada por reglas (propuesta, no aplicada)</dt>
            <dd>
              <InsigniaPrioridad valor={ev.prioridad_calculada} />
            </dd>
            <dt>Puntaje del motor</dt>
            <dd>{ev.score ?? "—"}</dd>
          </dl>

          <h3>Motivos</h3>
          <ul className="motivos">
            {ev.motivos.map((m, k) => (
              <li key={k}>
                <span className="puntos">{m.puntos > 0 ? `+${m.puntos}` : m.puntos}</span> {m.motivo}
                <ListaEvidencia ids={m.registro_ids} evidencia={evidencia} />
              </li>
            ))}
          </ul>

          {ev.banderas_rojas.length > 0 && (
            <>
              <h3>Banderas rojas</h3>
              <ul>
                {ev.banderas_rojas.map((b, k) => (
                  <li key={k}>
                    {b.bandera}
                    <ListaEvidencia ids={b.registro_ids} evidencia={evidencia} />
                  </li>
                ))}
              </ul>
            </>
          )}

          {ev.alertas_gestion.length > 0 && (
            <>
              <h3>Gestión</h3>
              <ul>
                {ev.alertas_gestion.map((g, k) => (
                  <li key={k}>
                    {TEXTO_GESTION}
                    <ListaEvidencia ids={g.registro_ids} evidencia={evidencia} />
                  </li>
                ))}
              </ul>
            </>
          )}

          {ev.inconsistencias.length > 0 && (
            <>
              <h3>Inconsistencias</h3>
              <ul>
                {ev.inconsistencias.map((i, k) => (
                  <li key={k}>
                    <strong>{TEXTO_CITA_ASISTIDA}.</strong> {i.descripcion}
                    <ListaEvidencia ids={i.registro_ids} evidencia={evidencia} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
