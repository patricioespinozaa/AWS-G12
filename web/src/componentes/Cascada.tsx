import { Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Resultado } from "../api";
import { COLOR_NIVEL, num } from "../utils";

const CATEGORIAS_NIVEL = ["base", "ajuste", "evento", "medicion", "patron"];

/** Cascada: cómo cada factor suma o resta hasta el puntaje de nivel, frente a los umbrales. */
export default function Cascada({ r, umbrales }: { r: Resultado; umbrales: { media: number; alta: number } }) {
  const orden = (c: string) => (c === "base" ? 0 : c === "ajuste" ? 2 : 1);
  const factores = r.factores
    .filter((f) => CATEGORIAS_NIVEL.includes(f.categoria) && Math.abs(f.aporte) >= 0.01)
    .sort((a, b) => orden(a.categoria) - orden(b.categoria) || b.aporte - a.aporte);
  let acumulado = 0;
  const filas = factores.map((f) => {
    const inicio = acumulado;
    acumulado += f.aporte;
    const etiqueta = f.descripcion.length > 58 ? `${f.descripcion.slice(0, 56)}…` : f.descripcion;
    return { etiqueta, descripcion: f.descripcion, base: Math.min(inicio, acumulado), valor: Math.abs(f.aporte), aporte: f.aporte, color: f.aporte >= 0 ? "#c0392b" : "#1e8449" };
  });
  filas.push({ etiqueta: "Puntaje de nivel", descripcion: "Total", base: 0, valor: r.puntaje_nivel, aporte: r.puntaje_nivel, color: "#2c3e50" });
  const maximo = Math.max(umbrales.alta + 3, ...filas.map((f) => f.base + f.valor));
  const minimo = Math.min(0, ...filas.map((f) => f.base));
  return (
    <ResponsiveContainer width="100%" height={70 + 30 * filas.length}>
      <BarChart data={filas} layout="vertical" margin={{ top: 18, right: 40, left: 8, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e8edee" horizontal={false} />
        <XAxis type="number" domain={[Math.floor(minimo), Math.ceil(maximo)]} tick={{ fontSize: 11 }} />
        <YAxis type="category" dataKey="etiqueta" width={300} tick={{ fontSize: 11 }} />
        <Tooltip cursor={{ fill: "#f2f6f6" }} content={({ active, payload }: any) => active && payload?.length ? (
          <div className="tooltip">{payload[0].payload.descripcion}: <b>{payload[0].payload.aporte >= 0 ? "+" : ""}{num(payload[0].payload.aporte, 2)}</b></div>) : null} />
        <ReferenceLine x={umbrales.media} stroke={COLOR_NIVEL.media} strokeDasharray="4 3"
          label={{ value: "media", position: "top", fill: COLOR_NIVEL.media, fontSize: 11 }} />
        <ReferenceLine x={umbrales.alta} stroke={COLOR_NIVEL.alta} strokeDasharray="4 3"
          label={{ value: "alta", position: "top", fill: COLOR_NIVEL.alta, fontSize: 11 }} />
        <Bar dataKey="base" stackId="a" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="valor" stackId="a" isAnimationActive={false}>
          {filas.map((f, i) => <Cell key={i} fill={f.color} />)}
          <LabelList dataKey="aporte" position="right" fontSize={11}
            formatter={(v: number) => (v > 0 ? "+" : "") + num(v, 1)} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
