import type { EstadoAviso, TipoResultado } from "../tipos";
import { ETIQUETA_ESTADO_AVISO, ETIQUETA_TIPO, etiquetaPrioridad } from "../textos";

// Siempre texto además de color.
export function InsigniaPrioridad({ valor }: { valor: string | null | undefined }) {
  return <span className={`insignia prioridad-${valor ?? "nd"}`}>{etiquetaPrioridad(valor)}</span>;
}

export function InsigniaTipo({ valor }: { valor: TipoResultado }) {
  return <span className={`insignia tipo-${valor}`}>{ETIQUETA_TIPO[valor]}</span>;
}

export function InsigniaEstado({ valor }: { valor: EstadoAviso }) {
  return <span className={`insignia estado-${valor}`}>{ETIQUETA_ESTADO_AVISO[valor]}</span>;
}
