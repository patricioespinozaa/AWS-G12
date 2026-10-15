import { ETIQUETA_FUENTE, ICONO_FUENTE, TEXTO_SIN_REGISTROS } from "../textos";
import type { EventoLinea, HallazgoDQ } from "../tipos";

function descripcion(e: EventoLinea): string {
  if (e.fuente === "evento") {
    return [e.tipo, e.subtipo, e.severidad && `severidad ${e.severidad}`, e.detalle].filter(Boolean).join(" · ");
  }
  if (e.fuente === "medicion") {
    const valor = e.valor === null ? "sin valor" : `${e.valor} ${e.unidad ?? ""}`.trim();
    return `${e.tipo ?? "medición"}: ${valor}${e.fuera_de_rango ? " (marcada fuera de rango)" : ""}`;
  }
  if (e.fuente === "cita") {
    const base = [e.especialidad, e.estado && `estado ${e.estado}`, e.id_box].filter(Boolean).join(" · ");
    return e.estado === "asistio" ? `${base} (no confirma vínculo con la solicitud)` : base;
  }
  return "";
}

function marcaDQ(h: HallazgoDQ): string {
  if (h.codigo === "DQ-01") return "DQ-01 descartar: error de registro, no evidencia clínica";
  return `${h.codigo} ${h.nivel}: ${h.descripcion}`;
}

export default function LineaTiempo({ eventos, calidad, corte }: { eventos: EventoLinea[]; calidad: HallazgoDQ[]; corte: string }) {
  const dqPorRegistro = new Map<string, HallazgoDQ[]>();
  for (const h of calidad) {
    for (const id of h.registro_ids) dqPorRegistro.set(id, [...(dqPorRegistro.get(id) ?? []), h]);
  }

  return (
    <section aria-labelledby="titulo-linea">
      <h2 id="titulo-linea">Línea de tiempo hasta el {corte}</h2>
      {eventos.length === 0 ? (
        <p className="sin-registros">{TEXTO_SIN_REGISTROS}</p>
      ) : (
        <ol className="linea-tiempo">
          {eventos.map((e) => (
            <li key={e.registro_id} id={`reg-${e.registro_id}`} tabIndex={-1} className={`fuente-${e.fuente}`}>
              <time dateTime={e.fecha ?? undefined}>{e.fecha ?? "sin fecha"}</time>{" "}
              <span aria-hidden="true">{ICONO_FUENTE[e.fuente]}</span>{" "}
              <strong>{ETIQUETA_FUENTE[e.fuente]}</strong> <code>{e.registro_id}</code>
              <span className="descripcion">{descripcion(e)}</span>
              {(dqPorRegistro.get(e.registro_id) ?? []).map((h) => (
                <span key={h.codigo} className={`marca-dq nivel-${h.nivel}`}>
                  {marcaDQ(h)}
                </span>
              ))}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
