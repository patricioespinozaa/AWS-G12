import { useMemo, useState } from "react";
import { conCorte, useDatos } from "../api";
import EstadoCarga from "../componentes/EstadoCarga";
import { InsigniaEstado, InsigniaPrioridad, InsigniaTipo } from "../componentes/Insignias";
import { hrefRuta } from "../rutas";
import { ETIQUETA_PRIORIDAD, PRIORIDADES } from "../textos";
import type { Evaluacion, RespuestaLista } from "../tipos";

export function textoExclusion(e: Evaluacion, fechaReferencia: string): string {
  if (e.motivo_exclusion === "fallecido") return `Fallecimiento registrado el ${e.fecha_defuncion ?? "fecha no registrada"}`;
  if (e.motivo_exclusion === "ya_atendido") return `Atendido según estado al ${fechaReferencia}`;
  return "Excluido por el motor de reglas";
}

export default function VistaLista({ corte, fechaReferencia }: { corte: string; fechaReferencia: string }) {
  const { datos, error, cargando, recargar } = useDatos<RespuestaLista>(conCorte("/api/lista", corte));
  const [especialidad, setEspecialidad] = useState("");
  const [prioridad, setPrioridad] = useState("");

  const especialidades = useMemo(
    () => [...new Set((datos?.items ?? []).map((i) => i.especialidad))].sort(),
    [datos],
  );
  const filas = (datos?.items ?? []).filter(
    (i) => (!especialidad || i.especialidad === especialidad) && (!prioridad || i.prioridad_calculada === prioridad),
  );

  return (
    <section aria-labelledby="titulo-lista">
      <h1 id="titulo-lista">Lista de espera a la fecha de corte {corte}</h1>
      <p className="nota">
        Orden del motor de reglas: prioridad calculada, puntaje y días en espera. La prioridad calculada es una
        propuesta para revisión; no se aplica a la solicitud.
      </p>
      <EstadoCarga cargando={cargando} error={error} onReintentar={recargar} textoCarga="Calculando evaluación a la fecha de corte…">
        {datos && (
          <>
            <div className="filtros" role="group" aria-label="Filtros de la lista">
              <label>
                Especialidad
                <select value={especialidad} onChange={(e) => setEspecialidad(e.target.value)}>
                  <option value="">Todas</option>
                  {especialidades.map((e) => (
                    <option key={e} value={e}>
                      {e}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Prioridad calculada por reglas
                <select value={prioridad} onChange={(e) => setPrioridad(e.target.value)}>
                  <option value="">Todas</option>
                  {PRIORIDADES.map((p) => (
                    <option key={p} value={p}>
                      {ETIQUETA_PRIORIDAD[p]}
                    </option>
                  ))}
                </select>
              </label>
              <p className="conteo" aria-live="polite">
                {filas.length} de {datos.items.length} solicitudes
              </p>
            </div>
            <div className="tabla-contenedor">
              <table>
                <caption>Solicitudes evaluadas al {corte}</caption>
                <thead>
                  <tr>
                    <th scope="col">Paciente</th>
                    <th scope="col">Especialidad</th>
                    <th scope="col">CIE-10</th>
                    <th scope="col">Prioridad inicial</th>
                    <th scope="col">Prioridad calculada por reglas (propuesta, no aplicada)</th>
                    <th scope="col">Puntaje</th>
                    <th scope="col">Días en espera</th>
                    <th scope="col">Tipo</th>
                    <th scope="col">Estado del aviso</th>
                  </tr>
                </thead>
                <tbody>
                  {filas.map((i) => (
                    <tr key={i.alerta_id}>
                      <th scope="row">
                        <a href={hrefRuta("paciente", corte, i.id_paciente)}>{i.id_paciente}</a>
                      </th>
                      <td>{i.especialidad}</td>
                      <td>{i.cie10}</td>
                      <td>
                        <InsigniaPrioridad valor={i.prioridad_inicial} />
                      </td>
                      <td>
                        <InsigniaPrioridad valor={i.prioridad_calculada} />
                      </td>
                      <td className="num">{i.score ?? "—"}</td>
                      <td className="num">{i.dias_en_espera ?? "—"}</td>
                      <td>
                        <InsigniaTipo valor={i.tipo} />
                      </td>
                      <td>{i.tipo === "sin_alerta" ? "—" : <InsigniaEstado valor={i.estado_aviso} />}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {datos.n_sin_solicitud_a_la_fecha > 0 && (
              <p className="nota">
                {datos.n_sin_solicitud_a_la_fecha} pacientes aún no tenían solicitud ingresada a esta fecha de corte.
              </p>
            )}
            <section aria-labelledby="titulo-excluidos">
              <h2 id="titulo-excluidos">Excluidos a la fecha de corte</h2>
              {datos.excluidos.length === 0 ? (
                <p>Sin excluidos a esta fecha de corte.</p>
              ) : (
                <ul>
                  {datos.excluidos.map((e) => (
                    <li key={e.alerta_id}>
                      <a href={hrefRuta("paciente", corte, e.id_paciente)}>{e.id_paciente}</a> ({e.especialidad}):{" "}
                      {textoExclusion(e, fechaReferencia)}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </EstadoCarga>
    </section>
  );
}
