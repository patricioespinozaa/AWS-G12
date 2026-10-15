import { conCorte, useDatos } from "../api";
import EstadoCarga from "../componentes/EstadoCarga";
import { hrefRuta } from "../rutas";
import type { RespuestaCalidad } from "../tipos";

const NIVEL: Record<string, string> = {
  descartar: "Descartar (error de registro, no evidencia clínica)",
  verificar: "Verificar",
  info: "Informativo",
};

export default function VistaCalidad({ corte }: { corte: string }) {
  const { datos, error, cargando, recargar } = useDatos<RespuestaCalidad>(conCorte("/api/calidad", corte));

  return (
    <section aria-labelledby="titulo-calidad">
      <h1 id="titulo-calidad">Calidad de datos al {corte}</h1>
      <p className="nota">
        DQ-06 no se evalúa antes del 2026-10-13 porque depende del estado a esa fecha.
      </p>
      <EstadoCarga cargando={cargando} error={error} onReintentar={recargar} textoCarga="Revisando calidad de datos…">
        {datos && (
          <>
            <p className="nota">{datos.nota}</p>
            <h2>Resumen por código</h2>
            {datos.resumen.length === 0 ? (
              <p>Sin hallazgos de calidad sobre registros visibles a esta fecha de corte.</p>
            ) : (
              <table>
                <caption>Hallazgos por código y nivel</caption>
                <thead>
                  <tr>
                    <th scope="col">Código</th>
                    <th scope="col">Nivel</th>
                    <th scope="col">Cantidad</th>
                  </tr>
                </thead>
                <tbody>
                  {datos.resumen.map((r) => (
                    <tr key={`${r.codigo}-${r.nivel}`}>
                      <th scope="row">{r.codigo}</th>
                      <td>{NIVEL[r.nivel] ?? r.nivel}</td>
                      <td className="num">{r.n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <h2>Hallazgos</h2>
            {datos.hallazgos.length > 0 && (
              <div className="tabla-contenedor">
                <table>
                  <caption>{datos.hallazgos.length} hallazgos</caption>
                  <thead>
                    <tr>
                      <th scope="col">Código</th>
                      <th scope="col">Nivel</th>
                      <th scope="col">Paciente</th>
                      <th scope="col">Descripción</th>
                      <th scope="col">Registros</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datos.hallazgos.map((h, k) => (
                      <tr key={`${h.codigo}-${h.id_paciente}-${k}`}>
                        <th scope="row">{h.codigo}</th>
                        <td>{NIVEL[h.nivel] ?? h.nivel}</td>
                        <td>
                          <a href={hrefRuta("paciente", corte, h.id_paciente)}>{h.id_paciente}</a>
                        </td>
                        <td>{h.descripcion}</td>
                        <td>{h.registro_ids.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <h2>Cuarentena de perfiles</h2>
            {datos.cuarentena.length === 0 ? (
              <p>0 perfiles en cuarentena.</p>
            ) : (
              <ul>
                {datos.cuarentena.map((q) => (
                  <li key={q.posicion}>
                    Posición {q.posicion} ({q.id_paciente ?? "sin id"}): {q.n_errores} errores de validación
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </EstadoCarga>
    </section>
  );
}
