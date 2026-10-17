import {
  CartesianGrid, Cell, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip,
  XAxis, YAxis,
} from "recharts";
import { ClinicoRespuesta } from "../api";
import { COLOR_SEVERIDAD, fechaEje, num, ticksMensuales, ts } from "../utils";

const DIA = 86_400_000;
const ANCHO_EJE = 120;

export default function GraficoClinico({ datos, corte }: { datos: ClinicoRespuesta; corte: string }) {
  const todas = [
    ts(datos.fecha_ingreso),
    ...datos.mediciones.flatMap((m) => m.puntos.map((p) => ts(p.fecha))),
    ...datos.eventos.map((e) => ts(e.fecha)),
  ];
  const dominio: [number, number] = [Math.min(...todas) - 7 * DIA, ts(corte) + 7 * DIA];
  const ejeX = { dataKey: "t", type: "number" as const, scale: "time" as const, domain: dominio, ticks: ticksMensuales(dominio), tickFormatter: fechaEje,
    allowDataOverflow: true, tick: { fontSize: 11 } };
  const marcas = (
    <>
      <ReferenceLine x={ts(datos.fecha_ingreso)} stroke="#7f8c8d" strokeWidth={2} />
      {datos.fecha_defuncion && <ReferenceLine x={ts(datos.fecha_defuncion)} stroke="#000" strokeWidth={3} />}
      {datos.eventos.filter((e) => e.severidad !== "leve").map((e) => (
        <ReferenceLine key={e.id_evento} x={ts(e.fecha)} stroke={COLOR_SEVERIDAD[e.severidad]}
          strokeDasharray={e.severidad === "grave" ? "5 3" : "2 3"} />
      ))}
    </>
  );

  const filasEventos = [...new Set(datos.eventos.map((e) => e.tipo)), ...(datos.citas.length ? ["Cita especialidad"] : [])];
  const puntosEventos = datos.eventos.map((e) => ({ t: ts(e.fecha), fila: e.tipo, color: COLOR_SEVERIDAD[e.severidad],
    texto: `${e.fecha} · ${e.tipo}: ${e.subtipo} (${e.severidad}) · ${e.id_evento}` }));
  const puntosCitas = datos.citas.map((c) => ({ t: ts(c.fecha), fila: "Cita especialidad", color: c.estado === "asistio" ? "#1e8449" : "#c0392b",
    texto: `${c.fecha} · cita ${c.estado} · ${c.id_box} · ${c.id_cita}` }));

  return (
    <div>
      <div className="leyenda">
        <span><i style={{ background: "#7f8c8d" }} />Ingreso a la lista</span>
        <span><i className="punteada" style={{ color: COLOR_SEVERIDAD.grave }} />Evento grave</span>
        <span><i className="punteada" style={{ color: COLOR_SEVERIDAD.moderada }} />Evento moderado</span>
        <span style={{ color: "#1e8449" }}>● en rango</span>
        <span style={{ color: "#c0392b" }}>● fuera de rango</span>
        <span>◯ borde azul: examen externo validado</span>
        <span><i style={{ background: "#d4efdf", height: 10 }} />Rango normal</span>
      </div>
      {datos.mediciones.map((m) => {
        const filas = m.puntos.map((p) => ({ ...p, t: ts(p.fecha) }));
        const valores = filas.map((f) => f.valor);
        const lo = Math.min(m.rango[0], ...valores);
        const hi = Math.max(m.rango[1], ...valores);
        const margen = (hi - lo) * 0.12 || 1;
        return (
          <div key={m.tipo}>
            <div className="grafico-titulo">{m.nombre} ({m.unidad}) · rango normal {num(m.rango[0], 1)}–{num(m.rango[1], 1)}</div>
            <ResponsiveContainer width="100%" height={140}>
              <ComposedChart data={filas} syncId="clinico" margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e8edee" />
                <ReferenceArea y1={m.rango[0]} y2={m.rango[1]} fill="#27ae60" fillOpacity={0.09} />
                {marcas}
                <XAxis {...ejeX} hide />
                <YAxis domain={[Math.floor(lo - margen), Math.ceil(hi + margen)]} width={ANCHO_EJE} tick={{ fontSize: 11 }} />
                <Tooltip content={({ active, payload }: any) => active && payload?.length ? (
                  <div className="tooltip">
                    <b>{payload[0].payload.fecha}</b>: {num(payload[0].payload.valor, 1)} {m.unidad}
                    {payload[0].payload.fuera ? " · fuera de rango" : ""}
                    {payload[0].payload.origen === "externa" ? " · examen externo validado" : ""}
                    <div className="suave">{payload[0].payload.ref}</div>
                  </div>) : null} />
                <Line dataKey="valor" stroke="#34495e" strokeWidth={1.5} isAnimationActive={false}
                  dot={(p: any) => (
                    <circle key={`${m.tipo}-${p.index}`} cx={p.cx} cy={p.cy} r={p.payload.origen === "externa" ? 6 : 4.5}
                      fill={p.payload.fuera ? "#c0392b" : "#1e8449"}
                      stroke={p.payload.origen === "externa" ? "#2471a3" : "white"} strokeWidth={p.payload.origen === "externa" ? 3 : 1} />
                  )} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        );
      })}
      {filasEventos.length > 0 && (
        <>
          <div className="grafico-titulo">Eventos clínicos y citas de especialidad</div>
          <ResponsiveContainer width="100%" height={60 + 34 * filasEventos.length}>
            <ScatterChart syncId="clinico" margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e8edee" />
              {marcas}
              <XAxis {...ejeX} />
              <YAxis type="category" dataKey="fila" allowDuplicatedCategory={false} width={ANCHO_EJE} tick={{ fontSize: 11 }} />
              <Tooltip content={({ active, payload }: any) => active && payload?.length ? (
                <div className="tooltip">{payload[0].payload.texto}</div>) : null} />
              <Scatter data={[...puntosEventos, ...puntosCitas]} isAnimationActive={false}>
                {[...puntosEventos, ...puntosCitas].map((p, i) => <Cell key={i} fill={p.color} />)}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </>
      )}
      {datos.mediciones.length === 0 && filasEventos.length === 0 && (
        <p className="suave">Sin mediciones ni eventos registrados hasta la fecha de corte.</p>
      )}
    </div>
  );
}
