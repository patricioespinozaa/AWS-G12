// Espejo de servidor/contratos.py

export type Prioridad = "baja" | "media" | "alta" | "critica";
export type TipoResultado = "priorizacion" | "gestion" | "sin_alerta" | "exclusion";
export type NivelDQ = "descartar" | "verificar" | "info";
export type Fuente = "solicitud" | "evento" | "medicion" | "cita";
export type EstadoAviso = "pendiente" | "analizado" | "decidido";
export type OrigenInferencia = "simulada" | "real";

export interface ConIds {
  registro_ids: string[];
}
export interface Motivo extends ConIds {
  puntos: number;
  motivo: string;
}
export interface Bandera extends ConIds {
  bandera: string;
}
export interface AlertaGestion extends ConIds {
  alerta: string;
}
export interface Inconsistencia extends ConIds {
  descripcion: string;
}

export interface Evaluacion {
  alerta_id: string;
  id_paciente: string;
  id_solicitud: string;
  especialidad: string;
  cie10: string;
  prioridad_inicial: Prioridad;
  fecha_corte: string;
  tipo: TipoResultado;
  score: number | null;
  prioridad_calculada: Prioridad | null;
  dias_en_espera: number | null;
  motivos: Motivo[];
  banderas_rojas: Bandera[];
  alertas_gestion: AlertaGestion[];
  inconsistencias: Inconsistencia[];
  motivo_exclusion: "fallecido" | "ya_atendido" | null;
  fecha_defuncion: string | null;
}

export interface ItemLista {
  alerta_id: string;
  id_paciente: string;
  id_solicitud: string;
  especialidad: string;
  cie10: string;
  prioridad_inicial: Prioridad;
  fecha_corte: string;
  tipo: TipoResultado;
  score: number | null;
  prioridad_calculada: Prioridad | null;
  dias_en_espera: number | null;
  banderas_rojas: Bandera[];
  alertas_gestion: AlertaGestion[];
  inconsistencias: Inconsistencia[];
  estado_aviso: EstadoAviso;
}

export interface RespuestaLista {
  fecha_corte: string;
  items: ItemLista[];
  excluidos: Evaluacion[];
  n_sin_solicitud_a_la_fecha: number;
}

export interface EventoLinea {
  fecha: string | null;
  registro_id: string;
  fuente: Fuente;
  tipo: string | null;
  subtipo: string | null;
  severidad: string | null;
  detalle: string | null;
  especialidad_asociada: string | null;
  valor: number | null;
  unidad: string | null;
  fuera_de_rango: boolean | null;
  especialidad: string | null;
  estado: string | null;
  id_box: string | null;
}

export interface SolicitudLinea {
  registro_id: string;
  especialidad: string | null;
  sub_especialidad: string | null;
  cie10: string | null;
  diagnostico: string | null;
  prioridad_inicial: string | null;
  fecha_ingreso: string | null;
  dias_en_espera: number;
  origen: string | null;
  estado: string | null;
  estado_reconstruible: boolean;
}

export interface HallazgoDQ extends ConIds {
  codigo: string;
  nivel: NivelDQ;
  id_paciente: string;
  descripcion: string;
}

export interface RefEvidencia {
  registro_id: string;
  fuente: Fuente;
  fecha: string | null;
  origen: string;
}
export type IndiceEvidencia = Record<string, RefEvidencia>;

export interface Verificacion {
  campos_faltantes: string[];
  citas_verificadas: boolean | null;
  citas_no_verificables: string[] | null;
  documentados_sin_cita: string[];
  discrepancias_motor: string[];
  requiere_atencion: boolean | null;
}

export interface MetaAnalisis {
  model: string | null;
  prompt_version: string | null;
  modo: string | null;
  turnos: number | null;
  fecha_corte: string | null;
  estado: string | null;
  verificacion: Verificacion | null;
}

export interface AnalisisCopiloto {
  resumen: string | null;
  relacion_con_derivacion: string | null;
  linea_tiempo_relevante: { fecha: string | null; descripcion: string | null; registro_id: string | null }[];
  hallazgos: { hallazgo: string | null; tipo: string | null; registro_ids: string[] }[];
  riesgo_poblacional: string | null;
  prioridad_sugerida: string | null;
  acuerdo_con_motor_reglas: boolean | null;
  justificacion: string | null;
  confianza: string | null;
  acciones_sugeridas: string[];
  propuesta_agenda: string | null;
  datos_faltantes: string[];
  inconsistencias_datos: { descripcion: string | null; registro_ids: string[] }[];
  nota_preconsulta: string | null;
  meta: MetaAnalisis | null;
}

export interface RespuestaAnalisis {
  alerta_id: string;
  origen_inferencia: OrigenInferencia;
  analisis: AnalisisCopiloto;
  evidencia: IndiceEvidencia;
}

export interface HistorialAviso {
  alerta_id: string;
  estado_aviso: EstadoAviso;
  analisis: { timestamp: string | null; origen_inferencia: OrigenInferencia; prioridad_sugerida: string | null; resumen: string | null }[];
  decisiones: { timestamp: string | null; medico_id: string | null; decision: string | null; prioridad_final: string | null; comentario: string | null }[];
  ultimo_analisis: AnalisisCopiloto | null;
  origen_ultimo_analisis: OrigenInferencia | null;
  lineas_invalidas: number;
}

export interface RespuestaPaciente {
  fecha_corte: string;
  perfil: { id_paciente: string; edad: number; sexo: string | null };
  solicitud: SolicitudLinea;
  eventos: EventoLinea[];
  evaluacion: Evaluacion;
  calidad: HallazgoDQ[];
  evidencia: IndiceEvidencia;
  historial: HistorialAviso;
}

export interface RespuestaCalidad {
  fecha_corte: string;
  hallazgos: HallazgoDQ[];
  resumen: { codigo: string; nivel: NivelDQ; n: number }[];
  cuarentena: { posicion: number; id_paciente: string | null; n_errores: number }[];
  nota: string;
}

export interface EstadoServidor {
  modo_inferencia: OrigenInferencia;
  requiere_confirmacion_envio: boolean;
  fecha_referencia: string;
  fecha_corte_min: string;
  fecha_corte_max: string;
  advertencia: string;
  perfiles_validos: number;
  perfiles_en_cuarentena: number;
  fuente_datos: string;
}

export interface SolicitudDecision {
  medico_id: string;
  decision: "aceptada" | "modificada" | "rechazada";
  prioridad_final: Prioridad;
  comentario: string;
}
