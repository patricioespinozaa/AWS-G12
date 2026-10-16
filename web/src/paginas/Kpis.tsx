import { BarChart3, Clock, Scale, ShieldCheck, Target, Users } from "lucide-react";
import { Fragment } from "react";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Registro, useApi } from "../api";
import { Aviso, Cargando, Encabezado, EnlacePaciente, Metrica, NivelBadge, Tabla } from "../componentes/comunes";
import { useApp } from "../contexto";
import { COLOR_NIVEL, fechaEje, num, pct, ticksMensuales, ts } from "../utils";

const NOMBRE_VAR: Record<string, string> = {
  grupo_edad: "Grupo de edad", sexo: "Sexo", comuna: "Comuna", prevision: "Previsión", nivel_socioeconomico: "Nivel socioeconómico",
};

export default function Kpis() {
  const { corte, version } = useApp();
  const { data, error } = useApi<Registro>(`/api/kpis?corte=${corte}`, version);
  return (
    <>
      <Encabezado icono={BarChart3} titulo="Indicadores" descripcion={<>Metas del desafío, calculadas sobre la serie nocturna hasta el <b>{corte}</b>.</>} />
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!data ? <Cargando texto="Calculando KPIs (la primera vez toma unos segundos)…" /> : <Contenido d={data} />}
    </>
  );
}

function Contenido({ d }: { d: Registro }) {
  const re = d.reevaluacion;
  const conc = d.concordancia;
  const niveles: string[] = d.foto_vs_pelicula.niveles;
  const matriz: number[][] = d.foto_vs_pelicula.matriz;
  const maxCelda = Math.max(1, ...matriz.flat());
  const porNoche = (d.por_noche as Registro[]).map((p) => ({ ...p, t: ts(p.fecha) }));
  const invisibles = d.invisibles as Registro[];
  return (
    <div className="pila">
      <div className="metricas">
        <Metrica destacada icono={Clock} etiqueta="Reevaluación < 72 h" valor={pct(re.pct_menos_72h)}
          detalle={`${re.eventos} eventos · mediana ≤ ${num(re.mediana_horas, 0)} h · meta < 72 h`} />
        <Metrica icono={ShieldCheck} etiqueta="Eventos graves con alerta" valor={pct(re.pct_alerta_graves)} detalle="la misma noche" />
        <Metrica icono={Target} etiqueta="Cobertura" valor={pct(d.cobertura.pct)} detalle={`${d.cobertura.con_propuesta} de ${d.cobertura.activas} solicitudes · meta 100 %`} />
        <Metrica icono={Scale} etiqueta="Concordancia (κ)" valor={conc.n >= 2 && conc.kappa !== null ? num(conc.kappa, 2) : "—"}
          detalle={conc.n ? `${conc.n} decisiones · ${pct(conc.pct_acepta)} aceptadas · meta ≥ 0,70` : "sin decisiones aún · meta ≥ 0,70"} />
      </div>

      <div className="grid-2">
        <div className="tarjeta pila">
          <h3>Prioridad inicial → propuesta al corte</h3>
          <div className="matriz">
            <div className="cab">inicial ↓ / propuesta →</div>
            {niveles.map((n) => <div key={n} className="cab"><NivelBadge nivel={n} /></div>)}
            {niveles.map((fila, i) => (
              <Fragment key={fila}>
                <div className="cab"><NivelBadge nivel={fila} /></div>
                {niveles.map((col, j) => (
                  <div key={`${fila}${col}`} style={{
                    background: i === j ? "#eef2f3" : `rgba(${j < i ? "192,57,43" : "30,132,73"}, ${0.12 + (0.55 * matriz[i][j]) / maxCelda})`,
                    fontWeight: i === j ? 400 : 700,
                  }}>{matriz[i][j]}</div>
                ))}
              </Fragment>
            ))}
          </div>
          <small className="suave">Diagonal: sin cambio. Rojo: sube. Verde: baja (solo con evidencia de mejora).</small>
        </div>
        <div className="tarjeta">
          <h3>Pacientes en prioridad alta cada noche</h3>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={porNoche} margin={{ right: 16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e8edee" />
              <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={fechaEje} tick={{ fontSize: 11 }}
                ticks={porNoche.length ? ticksMensuales([porNoche[0].t, porNoche[porNoche.length - 1].t], 9) : undefined} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip labelFormatter={(t: number) => new Date(t).toISOString().slice(0, 10)} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Area dataKey="en_lista" name="En lista" fill="#eef2f3" stroke="#bdc3c7" isAnimationActive={false} />
              <Line dataKey="alta_inicial" name="Alta según lista congelada" stroke="#7f8c8d" strokeDasharray="5 4" dot={false} isAnimationActive={false} />
              <Line dataKey="alta_propuesta" name="Alta según propuesta nocturna" stroke={COLOR_NIVEL.alta} strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="alertas" name="Alertas" stroke="#7d3c98" dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="tarjeta pila">
        <h3 className="transicion"><Users size={16} /> Los que la lista congelada no ve: {invisibles.length}</h3>
        <small className="suave">Prioridad inicial baja o media con al menos un evento grave en el último año.</small>
        <Tabla filas={invisibles} alta vacia="No hay pacientes en esta situación al corte." columnas={[
          { clave: "nombre", titulo: "Paciente", render: (f) => <EnlacePaciente id={f.id_solicitud} nombre={f.nombre} idPaciente={f.id_paciente} /> },
          { clave: "especialidad", titulo: "Especialidad" },
          { clave: "ultimo_evento_grave", titulo: "Último evento grave" },
          { clave: "prioridad_inicial", titulo: "Inicial", render: (f) => <NivelBadge nivel={f.prioridad_inicial} /> },
          { clave: "nivel_propuesto", titulo: "Propuesta", render: (f) => <NivelBadge nivel={f.nivel_propuesto} /> },
          { clave: "posicion_estatica", titulo: "Pos. lista congelada", num: true },
          { clave: "posicion_dinamica", titulo: "Pos. dinámica", num: true },
          { clave: "total_cola", titulo: "Total cola", num: true },
        ]} />
      </div>

      <div className="tarjeta pila">
        <h3>Equidad: ¿a quién mueve la propuesta?</h3>
        <small className="suave">% de cada grupo con propuesta de subir o bajar. Diferencias grandes sin explicación clínica deben revisarse.</small>
        <div className="grid-3">
          {Object.entries(d.equidad as Record<string, Registro[]>).map(([var_, filas]) => (
            <div key={var_}>
              <div className="grafico-titulo">{NOMBRE_VAR[var_] ?? var_}</div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={filas.map((f) => ({ ...f, grupo: String(f.grupo) }))} margin={{ right: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e8edee" />
                  <XAxis dataKey="grupo" tick={{ fontSize: 10 }} interval={0} angle={var_ === "comuna" ? -25 : 0} textAnchor={var_ === "comuna" ? "end" : "middle"} height={var_ === "comuna" ? 55 : 30} />
                  <YAxis tickFormatter={(v) => pct(v)} tick={{ fontSize: 10 }} />
                  <Tooltip formatter={(v: number) => pct(v, 1)} />
                  <Bar dataKey="sube" isAnimationActive={false} name="Sube" fill={COLOR_NIVEL.alta} />
                  <Bar dataKey="baja" isAnimationActive={false} name="Baja" fill="#1e8449" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
