import { AlertTriangle, CalendarDays, CalendarRange, Gauge, LayoutGrid, Users } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Registro, useApi } from "../api";
import { Aviso, Cargando, Disponibilidad, Encabezado, EnlacePaciente, IconoAlerta, Metrica, NivelBadge, Pasos, Pestanas, Tabla } from "../componentes/comunes";
import { useApp } from "../contexto";
import { COLORES_SERIE, num, pct } from "../utils";

type IdPestana = "agenda" | "panel";

export default function Agenda() {
  const [pestana, setPestana] = useState<IdPestana>("agenda");
  return (
    <>
      <Encabezado icono={CalendarDays} titulo="Agenda y box"
        descripcion="Los cupos del día van a los pacientes de mayor prioridad que están listos; quien no lo está no pierde su lugar." />
      <Pestanas opciones={[{ id: "agenda", etiqueta: "Agenda del día", icono: CalendarRange }, { id: "panel", etiqueta: "Uso del box", icono: LayoutGrid }]}
        activa={pestana} onCambio={setPestana} />
      {pestana === "agenda" ? <AgendaDia /> : <PanelBox />}
    </>
  );
}

const columnasPaciente = [
  { clave: "posicion_dinamica", titulo: "Pos.", num: true },
  { clave: "nombre", titulo: "Paciente", render: (f: Registro) => <EnlacePaciente id={f.id_solicitud} nombre={f.nombre} idPaciente={f.id_paciente} /> },
  { clave: "alerta", titulo: "", render: (f: Registro) => <IconoAlerta activa={f.alerta} /> },
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
      <Pasos actual={-1} pasos={[
        { titulo: "Elige día y especialidad" },
        { titulo: "Revisa la agenda propuesta", detalle: "mayor prioridad que está lista" },
        { titulo: "Gestiona a los no listos", detalle: "acción sugerida, sin perder su lugar" },
      ]} />
      <div className="tarjeta compacta fila">
        <label className="campo"><span>Día</span>
          <input type="date" value={fecha} min={meta.agenda.min} max={meta.agenda.max} onChange={(e) => e.target.value && setFecha(e.target.value)} />
        </label>
        <label className="campo"><span>Cola</span>
          <select value={especialidad} onChange={(e) => setEspecialidad(e.target.value)}>
            {meta.especialidades.map((e) => <option key={e}>{e}</option>)}
          </select>
        </label>
        <small className="suave" style={{ maxWidth: 480 }}>La cola se evalúa con lo conocido la noche anterior a ese día.</small>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {cargando && !data && <Cargando />}
      {data && (data.bloques?.length ?? 0) === 0 && (
        <Aviso tipo="info">Sin agenda de {especialidad} el {fecha}.</Aviso>
      )}
      {data && data.bloques?.length > 0 && (
        <>
          <div className="metricas">
            <Metrica icono={LayoutGrid} etiqueta="Box de la especialidad" valor={data.bloques.length}
              detalle={data.bloques.map((b: Registro) => `${b.id_box} (${b.cupos_libres} libres de ${b.capacidad_cupos})`).join(" · ")} />
            <Metrica destacada icono={Users} etiqueta="Cupos libres" valor={data.cupos_libres} />
            <Metrica icono={AlertTriangle} tono="alta" etiqueta="Alertas atendidas hoy" valor={`${data.alertas_atendidas_dinamica} de ${data.alertas_en_cola}`}
              detalle={`con la lista congelada serían ${data.alertas_atendidas_estatica}`} />
            <Metrica etiqueta="No listos con acción" valor={data.acciones.length} detalle="mantienen su lugar" />
          </div>
          <div className="tarjeta pila">
            <h3>Agenda propuesta</h3>
            <Tabla filas={data.asignados} vacia="No hay pacientes listos para asignar."
              columnas={[{ clave: "id_box", titulo: "Box" }, ...columnasPaciente,
                { clave: "disponibilidad", titulo: "Disponibilidad", render: (f) => <Disponibilidad estado={f.disponibilidad} /> }]} />
          </div>
          <div className="grid-2">
            <div className="tarjeta pila">
              <h3>Reemplazos si alguien cancela</h3>
              <Tabla filas={data.reemplazos} columnas={columnasPaciente} vacia="Sin reemplazos disponibles." />
            </div>
            <div className="tarjeta pila">
              <h3>Prioritarios no listos: qué hacer</h3>
              <Tabla filas={data.acciones} vacia="Todos los pacientes de mayor prioridad están listos."
                columnas={[...columnasPaciente.slice(0, 4),
                  { clave: "disponibilidad", titulo: "Pendiente", render: (f) => <Disponibilidad estado={f.disponibilidad} /> },
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
        <Metrica icono={Gauge} etiqueta="Ocupación global" valor={pct(data.ocupacion_global)} detalle={`${data.desde} → ${data.hasta}`} />
        <Metrica etiqueta="Inasistencia (no-show)" valor={pct(data.no_show_global)} detalle="citas ofrecidas hasta el corte" />
        <Metrica etiqueta="Duración real de la atención" valor={`${num(data.duracion_real_mediana, 0)} min`}
          detalle={`cupo teórico ${num(data.cupo_teorico_mediana, 0)} min (bloque de 5 h / cupos)`} />
        <Metrica destacada etiqueta="Mayor desbalance demanda / capacidad" valor={`${esp[0].especialidad}`}
          detalle={`${num(esp[0].demanda_sobre_capacidad, 1)}× más demanda que capacidad`} />
      </div>
      <div className="grid-2">
        <div className="tarjeta">
          <h3>Demanda vs. capacidad por especialidad</h3>
          <small className="suave">% de los pacientes en espera frente al % de los cupos de box.</small>
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
          <small className="suave">Cupos usados / capacidad, por semana.</small>
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
        <small className="suave">Se comparan proporciones: la lista es una muestra y la agenda es la del hospital completo.</small>
      </div>
    </div>
  );
}
