import { conCorte, useDatos } from "../api";
import EstadoCarga from "../componentes/EstadoCarga";
import { InsigniaEstado, InsigniaPrioridad, InsigniaTipo } from "../componentes/Insignias";
import { hrefRuta } from "../rutas";
import { TEXTO_CITA_ASISTIDA, TEXTO_GESTION } from "../textos";
import type { ItemLista } from "../tipos";

export default function VistaAvisos({ corte }: { corte: string }) {
  const { datos, error, cargando, recargar } = useDatos<ItemLista[]>(conCorte("/api/avisos", corte));

  return (
    <section aria-labelledby="titulo-avisos">
      <h1 id="titulo-avisos">Avisos generados por el motor de reglas al {corte}</h1>
      <p className="nota">
        El software genera y administra los avisos. Cada aviso requiere revisión profesional; ninguno cambia la
        prioridad por sí mismo.
      </p>
      <EstadoCarga cargando={cargando} error={error} onReintentar={recargar} textoCarga="Calculando avisos a la fecha de corte…">
        {datos && (
          <div className="tabla-contenedor">
            <table>
              <caption>{datos.length} avisos al {corte}</caption>
              <thead>
                <tr>
                  <th scope="col">Paciente</th>
                  <th scope="col">Especialidad</th>
                  <th scope="col">Tipo</th>
                  <th scope="col">Prioridad calculada por reglas (propuesta)</th>
                  <th scope="col">Banderas rojas</th>
                  <th scope="col">Gestión y verificación</th>
                  <th scope="col">Estado</th>
                </tr>
              </thead>
              <tbody>
                {datos.map((a) => (
                  <tr key={a.alerta_id}>
                    <th scope="row">
                      <a href={hrefRuta("paciente", corte, a.id_paciente)}>{a.id_paciente}</a>
                    </th>
                    <td>{a.especialidad}</td>
                    <td>
                      <InsigniaTipo valor={a.tipo} />
                    </td>
                    <td>
                      <InsigniaPrioridad valor={a.prioridad_calculada} />
                    </td>
                    <td>
                      {a.banderas_rojas.length ? (
                        <ul className="compacta">
                          {a.banderas_rojas.map((b) => (
                            <li key={b.bandera}>{b.bandera}</li>
                          ))}
                        </ul>
                      ) : (
                        "Ninguna"
                      )}
                    </td>
                    <td>
                      <ul className="compacta">
                        {a.alertas_gestion.length > 0 && <li>{TEXTO_GESTION}</li>}
                        {a.inconsistencias.length > 0 && <li>{TEXTO_CITA_ASISTIDA}</li>}
                      </ul>
                    </td>
                    <td>
                      <InsigniaEstado valor={a.estado_aviso} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </EstadoCarga>
    </section>
  );
}
