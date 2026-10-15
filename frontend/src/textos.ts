import type { EstadoAviso, Fuente, Prioridad, TipoResultado } from "./tipos";

export const ETIQUETA_FUENTE: Record<Fuente, string> = {
  solicitud: "Solicitud",
  evento: "Evento clínico",
  medicion: "Medición",
  cita: "Cita",
};

export const ICONO_FUENTE: Record<Fuente, string> = {
  solicitud: "📄",
  evento: "🩺",
  medicion: "📈",
  cita: "📅",
};

export const ETIQUETA_TIPO: Record<TipoResultado, string> = {
  priorizacion: "Aviso de priorización",
  gestion: "Aviso de gestión",
  sin_alerta: "Sin aviso del motor",
  exclusion: "Excluido",
};

export const ETIQUETA_ESTADO_AVISO: Record<EstadoAviso, string> = {
  pendiente: "Pendiente",
  analizado: "Analizado (sin decisión)",
  decidido: "Decidido por profesional",
};

export const ETIQUETA_PRIORIDAD: Record<Prioridad, string> = {
  critica: "Crítica",
  alta: "Alta",
  media: "Media",
  baja: "Baja",
};

export const PRIORIDADES: Prioridad[] = ["critica", "alta", "media", "baja"];

export const TEXTO_SIN_REGISTROS =
  "Sin registros hasta la fecha de corte. La ausencia de registros no demuestra estabilidad.";
export const TEXTO_ESTADO_NO_RECONSTRUIBLE =
  "El estado histórico de la solicitud no puede reconstruirse a esta fecha de corte";
export const TEXTO_GESTION = "Gestión: contactar y evaluar barreras de acceso (no modifica la prioridad)";
export const TEXTO_CITA_ASISTIDA =
  "Requiere verificación: una cita asistida no cierra la solicitud sin vínculo confirmado";

export function etiquetaPrioridad(p: string | null | undefined): string {
  return p && p in ETIQUETA_PRIORIDAD ? ETIQUETA_PRIORIDAD[p as Prioridad] : "—";
}
