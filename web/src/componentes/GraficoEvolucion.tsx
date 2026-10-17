import {
  CartesianGrid, Cell, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from "recharts";
import { Nivel, SerieRespuesta } from "../api";
import { COLOR_NIVEL, COLOR_SEVERIDAD, fechaEje, NOMBRE_NIVEL, num, ticksMensuales, ts, VALOR_NIVEL } from "../utils";

const DIA = 86_400_000;
const MORADO = "#7d3c98";
const GRIS = "#7f8c8d";
const VERDE = "#16a085";

interface Props {
  datos: SerieRespuesta;
  corte: string;
  inicial: Nivel;
  especialidad: string;
}

export default function GraficoEvolucion({ datos, corte, inicial, especialidad }: Props) {
  const filas = datos.serie.map((p) => ({
    t: ts(p.fecha),
    fecha: p.fecha,
    inicial: VALOR_NIVEL[p.prioridad_inicial],
    propuesta: VALOR_NIVEL[p.nivel_propuesto],
    vigente: VALOR_NIVEL[p.prioridad_vigente],
    nivel_propuesto: p.nivel_propuesto,
    prioridad_vigente: p.prioridad_vigente,
    puntaje_nivel: p.puntaje_nivel,
    puntaje: p.puntaje,
    pos_din: p.posicion_dinamica,
    pos_est: p.posicion_estatica,
    total: p.total_cola,
    alerta: p.alerta,
    motivo: p.motivo_principal,
  }));
  if (filas.length === 0) return null;
  const dominio: [number, number] = [filas[0].t, filas[filas.length - 1].t + DIA];
  const puntajePorFecha = new Map(datos.serie.map((p) => [p.fecha, p.puntaje_nivel]));
  const eventosPorFecha = new Map<string, string[]>();
  for (const e of datos.eventos) {
    const l = eventosPorFecha.get(e.fecha) ?? [];
    l.push(`${e.tipo}: ${e.subtipo} (${e.severidad}) · ${e.id_evento}`);
    eventosPorFecha.set(e.fecha, l);
  }
  const eventos = datos.eventos
    .filter((e) => ts(e.fecha) >= dominio[0] && ts(e.fecha) <= dominio[1])
    .map((e) => ({ t: ts(e.fecha), y: puntajePorFecha.get(e.fecha) ?? 0, severidad: e.severidad }));
  const externas = datos.externas.map((m) => ({ t: ts(m.fecha), y: puntajePorFecha.get(m.fecha) ?? 0 }));
  const decisiones = datos.decisiones.map((d) => ({ t: ts(d.fecha_corte), y: VALOR_NIVEL[d.prioridad_final] }));
  const hayVigente = filas.some((f) => f.vigente !== f.inicial);

  const tramos: { x1: number; x2: number }[] = [];
  let inicio: number | null = null;
  filas.forEach((f, i) => {
    if (f.alerta && inicio === null) inicio = f.t;
    const fin = !f.alerta || i === filas.length - 1;
    if (inicio !== null && fin) {
      tramos.push({ x1: inicio, x2: (f.alerta ? f.t : filas[i - 1].t) + DIA });
      inicio = null;
    }
  });
  const tCorte = ts(corte);
  const corteVisible = tCorte >= dominio[0] && tCorte <= dominio[1];
  const maxPuntaje = Math.max(datos.umbrales.alta + 4, ...filas.map((f) => f.puntaje));
  const ejeX = {
    dataKey: "t", type: "number" as const, scale: "time" as const, domain: dominio, ticks: ticksMensuales(dominio),
    tickFormatter: fechaEje, allowDataOverflow: true, tick: { fontSize: 11 },
  };

  const comunes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="#e8edee" />
      {tramos.map((tr, i) => (
        <ReferenceArea key={i} x1={tr.x1} x2={tr.x2} fill="#c0392b" fillOpacity={0.1} ifOverflow="hidden" />
      ))}
      {corteVisible && <ReferenceLine x={tCorte} stroke="#1c2b33" strokeDasharray="4 3" />}
    </>
  );

  const Info = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null;
    const f = payload[0].payload;
    if (!f.fecha) return null;
    const evs = eventosPorFecha.get(f.fecha) ?? [];
    return (
      <div className="tooltip">
        <b>Noche del {f.fecha}</b>
        <div>Lista congelada: {inicial} · Propuesta: <b style={{ color: COLOR_NIVEL[f.nivel_propuesto] }}>{f.nivel_propuesto}</b> · Vigente: {f.prioridad_vigente}</div>
        <div>Puntaje de nivel {num(f.puntaje_nivel)} · orden {num(f.puntaje)}</div>
        <div>Posición {f.pos_din} de {f.total} (lista congelada: {f.pos_est})</div>
        {f.alerta ? <div style={{ color: "#c0392b" }}>⚠️ Alerta activa</div> : null}
        <div className="suave">{f.motivo}</div>
        {evs.map((e) => <div key={e}>• {e}</div>)}
      </div>
    );
  };

  return (
    <div>
      <div className="grafico-titulo">1 · Nivel de prioridad: lista congelada vs. propuesta de cada noche</div>
      <div className="leyenda">
        <span><i className="punteada" style={{ color: GRIS }} />Lista congelada ({inicial})</span>
        <span><i style={{ background: MORADO }} />Propuesta nocturna</span>
        {hayVigente && <span><i className="punteada" style={{ color: VERDE }} />Vigente (decisión clínica)</span>}
        {decisiones.length > 0 && <span>★ Decisión clínica</span>}
        <span><i style={{ background: "#f5c6c0", height: 10 }} />Alerta</span>
        {corteVisible && <span><i className="punteada" style={{ color: "#1c2b33" }} />Fecha de corte</span>}
      </div>
      <ResponsiveContainer width="100%" height={170}>
        <ComposedChart data={filas} syncId="evolucion" margin={{ top: 6, right: 16, left: 0, bottom: 0 }}>
          {comunes}
          <XAxis {...ejeX} hide />
          <YAxis domain={[0.5, 3.5]} ticks={[1, 2, 3]} tickFormatter={(v) => NOMBRE_NIVEL[v] ?? ""} width={52} tick={{ fontSize: 11 }} />
          <Tooltip content={<Info />} />
          <Line dataKey="inicial" type="stepAfter" stroke={GRIS} strokeDasharray="6 4" strokeWidth={2} dot={false} isAnimationActive={false} />
          {hayVigente && <Line dataKey="vigente" type="stepAfter" stroke={VERDE} strokeDasharray="2 3" strokeWidth={2} dot={false} isAnimationActive={false} />}
          <Line dataKey="propuesta" type="stepAfter" stroke={MORADO} strokeWidth={3} dot={false} isAnimationActive={false} />
          {decisiones.length > 0 && <Scatter data={decisiones} dataKey="y" fill={VERDE} shape="star" isAnimationActive={false} />}
        </ComposedChart>
      </ResponsiveContainer>

      <div className="grafico-titulo">2 · Puntaje de nivel (decide el nivel) y puntaje de orden (ordena dentro del nivel)</div>
      <div className="leyenda">
        <span><i style={{ background: "#2c3e50" }} />Puntaje de nivel</span>
        <span><i className="punteada" style={{ color: "#95a5a6" }} />Puntaje de orden (+ contexto)</span>
        <span style={{ color: COLOR_SEVERIDAD.grave }}>● evento grave</span>
        <span style={{ color: COLOR_SEVERIDAD.moderada }}>● moderado</span>
        <span style={{ color: COLOR_SEVERIDAD.leve }}>● leve</span>
        {externas.length > 0 && <span style={{ color: "#2471a3" }}>■ examen externo validado</span>}
      </div>
      <ResponsiveContainer width="100%" height={230}>
        <ComposedChart data={filas} syncId="evolucion" margin={{ top: 6, right: 16, left: 0, bottom: 0 }}>
          {comunes}
          <XAxis {...ejeX} hide />
          <YAxis domain={[0, Math.ceil(maxPuntaje / 5) * 5]} width={52} tick={{ fontSize: 11 }} />
          <Tooltip content={<Info />} />
          <ReferenceLine y={datos.umbrales.media} stroke={COLOR_NIVEL.media} strokeDasharray="3 3"
            label={{ value: "umbral media", position: "insideTopLeft", fill: COLOR_NIVEL.media, fontSize: 11 }} />
          <ReferenceLine y={datos.umbrales.alta} stroke={COLOR_NIVEL.alta} strokeDasharray="3 3"
            label={{ value: "umbral alta", position: "insideTopLeft", fill: COLOR_NIVEL.alta, fontSize: 11 }} />
          <Line dataKey="puntaje" stroke="#95a5a6" strokeDasharray="3 3" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          <Line dataKey="puntaje_nivel" stroke="#2c3e50" strokeWidth={2.5} dot={false} isAnimationActive={false} />
          <Scatter data={eventos} dataKey="y" isAnimationActive={false}>
            {eventos.map((e, i) => <Cell key={i} fill={COLOR_SEVERIDAD[e.severidad]} />)}
          </Scatter>
          {externas.length > 0 && <Scatter data={externas} dataKey="y" fill="#2471a3" shape="square" isAnimationActive={false} />}
        </ComposedChart>
      </ResponsiveContainer>

      <div className="grafico-titulo">3 · Posición en la cola de {especialidad} (1 = primero en ser llamado)</div>
      <div className="leyenda">
        <span><i className="punteada" style={{ color: GRIS }} />Con lista congelada</span>
        <span><i style={{ background: MORADO }} />Con priorización dinámica</span>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={filas} syncId="evolucion" margin={{ top: 6, right: 16, left: 0, bottom: 4 }}>
          {comunes}
          <XAxis {...ejeX} />
          <YAxis reversed domain={[1, "dataMax"]} allowDecimals={false} width={52} tick={{ fontSize: 11 }} />
          <Tooltip content={<Info />} />
          <Line dataKey="pos_est" stroke={GRIS} strokeDasharray="6 4" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="pos_din" stroke={MORADO} strokeWidth={2.5} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
