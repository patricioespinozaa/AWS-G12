import type { MouseEvent } from "react";
import type { IndiceEvidencia } from "../tipos";
import { ETIQUETA_FUENTE } from "../textos";

interface Props {
  id: string;
  evidencia: IndiceEvidencia;
}

/** Enlaza un registro_id con su registro en la línea de tiempo (o lo marca no verificable). */
export default function EnlaceEvidencia({ id, evidencia }: Props) {
  const ref = evidencia[id];
  if (!ref) {
    return (
      <span className="evidencia no-verificable">
        {id} · No verificable a la fecha de corte
      </span>
    );
  }
  const irAlRegistro = (e: MouseEvent<HTMLAnchorElement>) => {
    // El hash se usa para el enrutamiento: se desplaza y enfoca sin cambiarlo.
    e.preventDefault();
    const destino = document.getElementById(`reg-${id}`);
    if (destino) {
      destino.scrollIntoView({ block: "center" });
      destino.focus();
    }
  };
  return (
    <a className="evidencia" href={`#reg-${id}`} onClick={irAlRegistro}>
      {id} · {ETIQUETA_FUENTE[ref.fuente]} · {ref.fecha ?? "sin fecha"} · {ref.origen}
    </a>
  );
}

export function ListaEvidencia({ ids, evidencia }: { ids: string[]; evidencia: IndiceEvidencia }) {
  if (!ids.length) return <span className="evidencia no-verificable">Sin registro citado</span>;
  return (
    <ul className="lista-evidencia" aria-label="Evidencia citada">
      {ids.map((id) => (
        <li key={id}>
          <EnlaceEvidencia id={id} evidencia={evidencia} />
        </li>
      ))}
    </ul>
  );
}
