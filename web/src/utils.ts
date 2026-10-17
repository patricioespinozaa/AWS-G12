export const COLOR_NIVEL: Record<string, string> = { alta: "#c0392b", media: "#c27c0e", baja: "#2471a3" };
export const VALOR_NIVEL: Record<string, number> = { baja: 1, media: 2, alta: 3 };
export const NOMBRE_NIVEL: Record<number, string> = { 1: "baja", 2: "media", 3: "alta" };
export const COLOR_SEVERIDAD: Record<string, string> = { leve: "#1e8449", moderada: "#ca6f1e", grave: "#c0392b" };
export const ICONO_CAMBIO: Record<string, string> = { sube: "↑ sube", baja: "↓ baja", igual: "=" };
export const ETIQUETA_DISP: Record<string, string> = {
  lista: "✅ Lista",
  faltan_examenes: "🧪 Faltan exámenes",
  no_confirma: "📵 Confirmar asistencia",
  sin_contacto: "☎️ Sin contacto",
};
export const COLORES_SERIE = ["#0f6e6e", "#c0392b", "#2471a3", "#c27c0e", "#7d3c98", "#1e8449", "#5d6d7e"];

export function num(x: number | null | undefined, decimales = 1): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return x.toLocaleString("es-CL", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
}

export function pct(x: number | null | undefined, decimales = 0): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `${(x * 100).toLocaleString("es-CL", { maximumFractionDigits: decimales })} %`;
}

/** Fecha ISO (AAAA-MM-DD) → milisegundos UTC, para ejes de tiempo. */
export function ts(iso: string): number {
  return Date.parse(`${iso}T00:00:00Z`);
}

export function fechaEje(t: number): string {
  const d = new Date(t);
  const meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  return `${meses[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`;
}

/** Un tick por mes (primer día), espaciados para no pasar de `maximo` ticks. */
export function ticksMensuales([desde, hasta]: [number, number], maximo = 12): number[] {
  const inicio = new Date(desde);
  const ticks: number[] = [];
  for (let k = 0; ; k++) {
    const t = Date.UTC(inicio.getUTCFullYear(), inicio.getUTCMonth() + k, 1);
    if (t > hasta) break;
    if (t >= desde) ticks.push(t);
  }
  const paso = Math.max(1, Math.ceil(ticks.length / maximo));
  return ticks.filter((_, i) => i % paso === 0);
}

export function fechaISO(t: number): string {
  return new Date(t).toISOString().slice(0, 10);
}

export function sumarDias(iso: string, dias: number): string {
  return fechaISO(ts(iso) + dias * 86_400_000);
}

export function diasEntre(a: string, b: string): number {
  return Math.round((ts(b) - ts(a)) / 86_400_000);
}
