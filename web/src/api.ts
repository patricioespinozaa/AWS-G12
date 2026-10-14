import { useEffect, useState } from "react";

export type Nivel = "alta" | "media" | "baja";
export type Registro = Record<string, any>;

export interface Meta {
  fecha_referencia: string;
  fecha_min: string;
  especialidades: string[];
  version_reglas: string;
  umbrales: { media: number; alta: number };
  llm: { activo: boolean; modelo: string };
  agenda: { min: string; max: string };
  tipos_medicion: { tipo: string; nombre: string; unidad: string; rango: [number, number] }[];
  casos_referencia: { id_paciente: string; id_solicitud: string; patron: string }[];
}

export interface FilaBandeja {
  id_solicitud: string;
  id_paciente: string;
  nombre: string;
  edad: number;
  sexo: string;
  comuna: string;
  prevision: string;
  especialidad: string;
  cie10: string;
  diagnostico: string;
  riesgo_basal: string;
  canal_origen: string;
  prioridad_inicial: Nivel;
  prioridad_vigente: Nivel;
  nivel_propuesto: Nivel;
  cambio: "sube" | "baja" | "igual";
  alerta: number;
  puntaje: number;
  puntaje_nivel: number;
  motivo_principal: string;
  dias_espera: number;
  disponibilidad: string;
  accion: string | null;
  riesgo_no_show: number;
  posicion_dinamica: number;
  posicion_estatica: number;
  total_cola: number;
  avance_posiciones: number;
  caso_referencia: string | null;
}

export interface Factor {
  codigo: string;
  descripcion: string;
  aporte: number;
  categoria: string;
  tipo_fuente: string;
  ref_fuente: string;
  fecha_dato: string | null;
}

export interface Resultado {
  id_solicitud: string;
  fecha_corte: string;
  excluido: boolean;
  motivo_exclusion: string | null;
  puntaje: number;
  puntaje_nivel: number;
  nivel_calculado: Nivel;
  nivel_propuesto: Nivel;
  prioridad_inicial: Nivel;
  prioridad_vigente: Nivel;
  cambio: "sube" | "baja" | "igual";
  alerta: boolean;
  motivos_alerta: string[];
  resguardo_aplicado: boolean;
  evidencia_mejora: boolean;
  factores: Factor[];
  version_reglas: string;
  motivo_principal: string;
}

export interface Disponibilidad {
  estado: string;
  pendientes: string[];
  riesgo_no_show: number;
  n_citas: number;
  n_no_asistio: number;
  accion: string | null;
}

export interface FichaPaciente {
  corte: string;
  solicitud: Registro;
  resultado: Resultado;
  disponibilidad: Disponibilidad;
  resumen: string;
  explicacion: string;
  huella_datos: string;
  ficha: Record<string, Registro[]>;
  decisiones: Registro[];
  propuestas: Registro[];
}

export interface PuntoSerie {
  fecha: string;
  id_solicitud: string;
  puntaje: number;
  puntaje_nivel: number;
  nivel_propuesto: Nivel;
  prioridad_vigente: Nivel;
  prioridad_inicial: Nivel;
  cambio: string;
  alerta: number;
  motivo_principal: string;
  posicion_dinamica: number;
  posicion_estatica: number;
  total_cola: number;
}

export interface EventoClinico {
  fecha: string;
  tipo: string;
  subtipo: string;
  severidad: "leve" | "moderada" | "grave";
  id_evento: string;
}

export interface SerieRespuesta {
  serie: PuntoSerie[];
  cambios: Registro[];
  eventos: EventoClinico[];
  externas: { fecha: string; tipo: string; valor: number; ref: string }[];
  decisiones: Registro[];
  umbrales: { media: number; alta: number };
}

export interface ClinicoRespuesta {
  fecha_ingreso: string;
  fecha_defuncion: string | null;
  mediciones: {
    tipo: string;
    nombre: string;
    unidad: string;
    rango: [number, number];
    puntos: { fecha: string; valor: number; fuera: boolean; origen: string; ref: string }[];
  }[];
  eventos: EventoClinico[];
  citas: { fecha: string; estado: string; id_box: string; id_cita: string }[];
}

async function leerError(r: Response): Promise<string> {
  try {
    const j = await r.json();
    return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
  } catch {
    return `${r.status} ${r.statusText}`;
  }
}

export async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await leerError(r));
  return r.json();
}

export async function postJSON<T>(url: string, cuerpo?: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
  });
  if (!r.ok) throw new Error(await leerError(r));
  return r.json();
}

/** Lee un recurso y lo vuelve a pedir cuando cambia la URL o `version` (tras guardar algo). */
export function useApi<T>(url: string | null, version = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);
  useEffect(() => {
    if (!url) return;
    let vigente = true;
    setCargando(true);
    setError(null);
    getJSON<T>(url)
      .then((d) => vigente && setData(d))
      .catch((e: Error) => vigente && setError(e.message))
      .finally(() => vigente && setCargando(false));
    return () => {
      vigente = false;
    };
  }, [url, version]);
  return { data, error, cargando };
}
