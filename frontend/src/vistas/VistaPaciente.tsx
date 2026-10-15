import { conCorte, useDatos } from "../api";
import EstadoCarga from "../componentes/EstadoCarga";
import { InsigniaPrioridad } from "../componentes/Insignias";
import { hrefRuta } from "../rutas";
import { TEXTO_ESTADO_NO_RECONSTRUIBLE } from "../textos";
import type { EstadoServidor, RespuestaPaciente } from "../tipos";
import FormDecision from "./FormDecision";
import LineaTiempo from "./LineaTiempo";
import PanelCopiloto from "./PanelCopiloto";
import PanelEvaluacion from "./PanelEvaluacion";

interface Props {
  pid: string;
  corte: string;
  estado: EstadoServidor;
}

export default function VistaPaciente({ pid, corte, estado }: Props) {
  const { datos, error, cargando, recargar } = useDatos<RespuestaPaciente>(conCorte(`/api/pacientes/${pid}`, corte));
  const conAviso = datos && (datos.evaluacion.tipo === "priorizacion" || datos.evaluacion.tipo === "gestion");

  return (
    <section aria-labelledby="titulo-paciente">
      <p>
        <a href={hrefRuta("lista", corte)}>← Volver a la lista</a>
      </p>
      <h1 id="titulo-paciente">
        Paciente {pid} al {corte}
      </h1>
      <EstadoCarga cargando={cargando} error={error} onReintentar={recargar} textoCarga="Cargando antecedentes a la fecha de corte…">
        {datos && (
          <>
            <section aria-labelledby="titulo-ficha">
              <h2 id="titulo-ficha">Ficha y solicitud</h2>
              {!datos.solicitud.estado_reconstruible && (
                <p className="banner-historico" role="note">
                  {TEXTO_ESTADO_NO_RECONSTRUIBLE}. El estado conocido corresponde al {estado.fecha_referencia} y no se
                  aplica retroactivamente.
                </p>
              )}
              <dl className="ficha">
                <dt>Edad</dt>
                <dd>{datos.perfil.edad}</dd>
                <dt>Sexo</dt>
                <dd>{datos.perfil.sexo ?? "—"}</dd>
                <dt>Solicitud</dt>
                <dd>
                  <code>{datos.solicitud.registro_id}</code>
                </dd>
                <dt>Especialidad</dt>
                <dd>
                  {datos.solicitud.especialidad} {datos.solicitud.sub_especialidad && `(${datos.solicitud.sub_especialidad})`}
                </dd>
                <dt>Diagnóstico de derivación</dt>
                <dd>
                  {datos.solicitud.cie10} · {datos.solicitud.diagnostico}
                </dd>
                <dt>Prioridad inicial</dt>
                <dd>
                  <InsigniaPrioridad valor={datos.solicitud.prioridad_inicial} />
                </dd>
                <dt>Ingreso a la lista</dt>
                <dd>{datos.solicitud.fecha_ingreso}</dd>
                <dt>Días en espera al corte</dt>
                <dd>{datos.solicitud.dias_en_espera}</dd>
                <dt>Origen de la derivación</dt>
                <dd>{datos.solicitud.origen ?? "—"}</dd>
                <dt>Estado de la solicitud</dt>
                <dd>{datos.solicitud.estado_reconstruible ? datos.solicitud.estado : "No reconstruible a esta fecha"}</dd>
              </dl>
            </section>

            <div className="columnas">
              <LineaTiempo eventos={datos.eventos} calidad={datos.calidad} corte={corte} />
              <PanelEvaluacion evaluacion={datos.evaluacion} evidencia={datos.evidencia} fechaReferencia={estado.fecha_referencia} />
            </div>

            {conAviso ? (
              <>
                <PanelCopiloto
                  pid={pid}
                  corte={corte}
                  estado={estado}
                  evidencia={datos.evidencia}
                  previo={datos.historial.ultimo_analisis}
                  origenPrevio={datos.historial.origen_ultimo_analisis}
                  onAnalizado={recargar}
                />
                <FormDecision alertaId={datos.evaluacion.alerta_id} historial={datos.historial} onRegistrada={recargar} />
              </>
            ) : (
              <p className="nota">
                El motor de reglas no generó un aviso para este paciente a la fecha de corte; no hay propuesta ni decisión
                pendiente.
              </p>
            )}
          </>
        )}
      </EstadoCarga>
    </section>
  );
}
