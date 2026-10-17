import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Registro, useApi } from "../api";
import { Aviso, Cargando, EnlacePaciente, Metrica, NivelBadge, Pestanas, Tabla } from "../componentes/comunes";
import { useApp } from "../contexto";
import { COLORES_SERIE, ETIQUETA_DISP, num, pct } from "../utils";

type IdPestana = "agenda" | "panel";

export default function Agenda() {
  const [pestana, setPestana] = useState<IdPestana>("agenda");
  return (
    <>
      <div className="encabezado">
        <h1>🗓️ Agenda y uso del box</h1>
        <p>
          La prioridad clínica y la disponibilidad son dos ejes distintos: un paciente de prioridad alta al que le faltan
          exámenes <b>no pierde su lugar</b>, pero tampoco ocupa la hora de hoy. Se gatilla una acción para que esté listo y
          se llama al siguiente que sí lo está.
        </p>
      </div>
      <Pestanas opciones={[{ id: "agenda", etiqueta: "Agenda propuesta del día" }, { id: "panel", etiqueta: "Panel de box" }]}
        activa={pestana} onCambio={setPestana} />
      {pestana === "agenda" ? <AgendaDia /> : <PanelBox />}
    </>
  );
}

const columnasPaciente = [
  { clave: "posicion_dinamica", titulo: "Pos.", num: true },
  { clave: "nombre", titulo: "Paciente", render: (f: Registro) => <EnlacePaciente id={f.id_solicitud} nombre={f.nombre} idPaciente={f.id_paciente} /> },
  { clave: "alerta", titulo: "⚠️", render: (f: Registro) => (f.alerta ? "⚠️" : "") },
  { clave: "nivel_propuesto", titulo: "Propuesta", render: (f: Registro) => <NivelBadge nivel={f.nivel_propuesto} /> },
  { clave: "puntaje", titulo: "Puntaje", num: true, render: (f: Registro) => num(f.puntaje) },
  { clave: "motivo_principal", titulo: "Motivo principal" },
];

function AgendaDia() {
  const { meta, corte, version } = useApp();
  const fechaInicial = meta ? (corte > meta.agenda.max ? meta.agenda.max : corte < meta.agenda.min ? meta.agenda.min : corte) : corte;
  const [fecha, setFecha] = useState(fechaInicial);
  const [especialidad, setEspecialidad] = useState("Cardiología");
  const { data, error, cargando } = useApi<Registro>(`/api/agenda?fecha=${fecha}&especialidad=${encodeURIComponent(especialidad)}`, version);
  if (!meta) return null;
  return (
    <div className="pila">
      <div className="tarjeta compacta fila">
        <label className="campo"><span>Día</span>
          <input type="date" value={fecha} min={meta.agenda.min} max={meta.agenda.max} onChange={(e) => e.target.value && setFecha(e.target.value)} />
        </label>
        <label className="campo"><span>Cola</span>
          <select value={especialidad} onChange={(e) => setEspecialidad(e.target.value)}>
            {meta.especialidades.map((e) => <option key={e}>{e}</option>)}
          </select>
        </label>
        <small style={{ maxWidth: 520 }}>
          Cupos libres = capacidad del bloque − cupos usados registrados ese día en <code>agenda_box</code>. La cola se
          evalúa con los datos disponibles la noche anterior a ese día.
        </small>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {cargando && !data && <Cargando />}
      {data && (data.bloques?.length ?? 0) === 0 && (
        <Aviso tipo="info">No hay bloques de {especialidad} el {fecha} (día no hábil o sin agenda para esa especialidad).</Aviso>
      )}
      {data && data.bloques?.length > 0 && (
        <>
          <div className="metricas">
            <Metrica etiqueta="Box de la especialidad ese día" valor={data.bloques.length}
              detalle={data.bloques.map((b: Registro) => `${b.id_box} (${b.cupos_libres} libres de ${b.capacidad_cupos})`).join(" · ")} />
            <Metrica destacada etiqueta="Cupos libres a asignar" valor={data.cupos_libres} />
            <Metrica etiqueta="Alertas atendidas con priorización dinámica" valor={data.alertas_atendidas_dinamica}
              detalle={`de ${data.alertas_en_cola} alertas en la cola`} />
            <Metrica etiqueta="… y con la lista congelada" valor={data.alertas_atendidas_estatica}
              detalle="mismos cupos, ordenando por prioridad inicial" />
            <Metrica etiqueta="Acciones para no listos" valor={data.acciones.length} detalle="mantienen su lugar en la cola" />
          </div>
          <div className="tarjeta pila">
            <h3>Agenda propuesta: pacientes de mayor prioridad que están listos</h3>
            <Tabla filas={data.asignados} vacia="No hay pacientes listos para asignar."
              columnas={[{ clave: "id_box", titulo: "Box" }, ...columnasPaciente,
                { clave: "disponibilidad", titulo: "Disponibilidad", render: (f) => ETIQUETA_DISP[f.disponibilidad] }]} />
          </div>
          <div className="grid-2">
            <div className="tarjeta pila">
              <h3>Lista de reemplazo (si alguien cancela)</h3>
              <Tabla filas={data.reemplazos} columnas={columnasPaciente} vacia="Sin reemplazos disponibles." />
            </div>
            <div className="tarjeta pila">
              <h3>Prioritarios que aún no están listos: acción sugerida</h3>
              <Tabla filas={data.acciones} vacia="Todos los pacientes de mayor prioridad están listos."
                columnas={[...columnasPaciente.slice(0, 4),
                  { clave: "disponibilidad", titulo: "Pendiente", render: (f) => ETIQUETA_DISP[f.disponibilidad] },
                  { clave: "accion", titulo: "Acción sugerida" }]} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function PanelBox() {
  const { corte, version } = useApp();
  const { data, error } = useApi<Registro>(`/api/box?corte=${corte}`, version);
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!data) return <Cargando texto="Calculando el uso del box…" />;
  if (!data.hay_agenda) return <Aviso tipo="info">La agenda de box del dataset empieza el 2026-04-14: elige una fecha de corte posterior.</Aviso>;
  const esp: Registro[] = data.por_especialidad;
  const especialidades = esp.map((e) => e.especialidad as string);
  const proporcion = esp.map((e) => ({ especialidad: e.especialidad, demanda: e.pct_demanda * 100, capacidad: e.pct_capacidad * 100 }));
  return (
    <div className="pila">
      <div className="metricas">
        <Metrica etiqueta="Ocupación global" valor={pct(data.ocupacion_global)} detalle={`${data.desde} → ${data.hasta}`} />
        <Metrica etiqueta="Inasistencia (no-show)" valor={pct(data.no_show_global)} detalle="citas ofrecidas hasta el corte" />
        <Metrica etiqueta="Duración real de la atención" valor={`${num(data.duracion_real_mediana, 0)} min`}
          detalle={`cupo teórico ${num(data.cupo_teorico_mediana, 0)} min (bloque de 5 h / cupos)`} />
        <Metrica destacada etiqueta="Mayor desbalance demanda / capacidad" valor={`${esp[0].especialidad}`}
          detalle={`${num(esp[0].demanda_sobre_capacidad, 1)}× más demanda que capacidad`} />
      </div>
      <div className="grid-2">
        <div className="tarjeta">
          <h3>Demanda vs. capacidad por especialidad</h3>
          <p className="suave">% de los pacientes en espera frente al % de los cupos de box. Si la demanda supera mucho a la capacidad, conviene redistribuir box.</p>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={proporcion} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e8edee" />
              <XAxis type="number" unit=" %" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="especialidad" width={130} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => `${num(v, 1)} %`} />
              <Legend />
              <Bar dataKey="demanda" isAnimationActive={false} name="% de la demanda (en espera)" fill="#c0392b" />
              <Bar dataKey="capacidad" isAnimationActive={false} name="% de la capacidad de box" fill="#2471a3" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="tarjeta">
          <h3>Ocupación semanal por especialidad</h3>
          <p className="suave">Cupos usados / capacidad, por semana.</p>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data.semanal} margin={{ right: 16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e8edee" />
              <XAxis dataKey="semana" tick={{ fontSize: 10 }} minTickGap={24} />
              <YAxis domain={[0.5, 1]} tickFormatter={(v) => pct(v)} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => pct(v, 1)} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {especialidades.map((e, i) => <Line key={e} dataKey={e} stroke={COLORES_SERIE[i % COLORES_SERIE.length]} dot={false} strokeWidth={1.6} isAnimationActive={false} />)}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="tarjeta">
          <h3>Inasistencia por especialidad</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data.citas} margin={{ right: 16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e8edee" />
              <XAxis dataKey="especialidad" tick={{ fontSize: 10 }} interval={0} angle={-20} textAnchor="end" height={50} />
              <YAxis tickFormatter={(v) => pct(v)} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => pct(v, 1)} />
              <ReferenceLine y={data.no_show_global} stroke="#5d6d7e" strokeDasharray="4 3" />
              <Bar dataKey="tasa_no_show" isAnimationActive={false} name="Tasa de no-show" fill="#c27c0e" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="tarjeta">
          <h3>Sobretiempo por especialidad</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={esp} margin={{ right: 16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e8edee" />
              <XAxis dataKey="especialidad" tick={{ fontSize: 10 }} interval={0} angle={-20} textAnchor="end" height={50} />
              <YAxis unit=" min" tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => `${num(v, 0)} min`} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="sobretiempo_medio" isAnimationActive={false} name="Promedio" fill="#5d6d7e" />
              <Bar dataKey="sobretiempo_p90" isAnimationActive={false} name="Percentil 90" fill="#aab7b8" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="tarjeta pila">
        <h3>Detalle por especialidad</h3>
        <Tabla filas={esp} columnas={[
          { clave: "especialidad", titulo: "Especialidad" }, { clave: "box", titulo: "Box", num: true },
          { clave: "pct_demanda", titulo: "% demanda", num: true, render: (f) => pct(f.pct_demanda, 1) },
          { clave: "pct_capacidad", titulo: "% capacidad", num: true, render: (f) => pct(f.pct_capacidad, 1) },
          { clave: "demanda_sobre_capacidad", titulo: "Demanda / capacidad", num: true, render: (f) => <b>{num(f.demanda_sobre_capacidad, 2)}×</b> },
          { clave: "ocupacion", titulo: "Ocupación", num: true, render: (f) => pct(f.ocupacion, 1) },
          { clave: "alertas_en_cola", titulo: "Alertas en cola", num: true },
          { clave: "sobretiempo_medio", titulo: "Sobretiempo medio", num: true, render: (f) => `${num(f.sobretiempo_medio, 0)} min` },
        ]} />
        <small>La lista del dataset es una muestra de 500 pacientes y la agenda es la del hospital: por eso se comparan proporciones y no cifras absolutas.</small>
      </div>
    </div>
  );
}
