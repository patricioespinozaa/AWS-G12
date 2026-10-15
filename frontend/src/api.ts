import { useCallback, useEffect, useRef, useState } from "react";

// Vacío = mismo origen (proxy de Vite hacia 127.0.0.1:8000).
const BASE = import.meta.env.VITE_API_BASE ?? "";

export class ErrorApi extends Error {
  constructor(
    public status: number,
    public codigo: string,
    mensaje: string,
  ) {
    super(mensaje);
  }
}

async function leerError(resp: Response): Promise<ErrorApi> {
  let codigo = "error_http";
  let mensaje = `El servidor respondió ${resp.status}.`;
  try {
    const cuerpo = await resp.json();
    const detalle = cuerpo?.detail;
    if (detalle && typeof detalle === "object" && !Array.isArray(detalle)) {
      codigo = detalle.codigo ?? codigo;
      mensaje = detalle.mensaje ?? mensaje;
    } else if (Array.isArray(detalle)) {
      codigo = "validacion";
      mensaje = "La solicitud no es válida: revise los datos ingresados.";
    }
  } catch {
    // respuesta sin JSON
  }
  return new ErrorApi(resp.status, codigo, mensaje);
}

async function pedir<T>(ruta: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(BASE + ruta, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ErrorApi(0, "sin_conexion", "No se pudo conectar con el servidor local (python -m servidor).");
  }
  if (!resp.ok) throw await leerError(resp);
  return (await resp.json()) as T;
}

export const obtener = <T,>(ruta: string) => pedir<T>(ruta);
export const enviar = <T,>(ruta: string, cuerpo: unknown) =>
  pedir<T>(ruta, { method: "POST", body: JSON.stringify(cuerpo) });

export function conCorte(ruta: string, corte: string): string {
  return `${ruta}?fecha_corte=${encodeURIComponent(corte)}`;
}

export interface EstadoDatos<T> {
  datos: T | null;
  error: ErrorApi | null;
  cargando: boolean;
  recargar: () => void;
}

/** Carga una ruta GET. Con ruta null no consulta nada (p. ej. sin fecha de corte). */
export function useDatos<T>(ruta: string | null): EstadoDatos<T> {
  const [datos, setDatos] = useState<T | null>(null);
  const [error, setError] = useState<ErrorApi | null>(null);
  const [cargando, setCargando] = useState(false);
  const [version, setVersion] = useState(0);
  const rutaAnterior = useRef<string | null>(null);

  useEffect(() => {
    // Con otra ruta (p. ej. otra fecha de corte) nunca se muestran datos anteriores.
    if (rutaAnterior.current !== ruta) setDatos(null);
    rutaAnterior.current = ruta;
    if (!ruta) {
      setError(null);
      return;
    }
    let vigente = true;
    setCargando(true);
    setError(null);
    obtener<T>(ruta)
      .then((d) => vigente && setDatos(d))
      .catch((e: unknown) => {
        if (!vigente) return;
        setDatos(null);
        setError(e instanceof ErrorApi ? e : new ErrorApi(0, "desconocido", "Error inesperado."));
      })
      .finally(() => vigente && setCargando(false));
    return () => {
      vigente = false;
    };
  }, [ruta, version]);

  const recargar = useCallback(() => setVersion((v) => v + 1), []);
  return { datos, error, cargando, recargar };
}
