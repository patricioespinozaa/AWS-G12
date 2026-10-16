import { AlertTriangle, ArrowDown, ArrowRight, ArrowUp, ClipboardList, ListOrdered, Search, Star, UserX } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FilaBandeja, useApi } from "../api";
import { Aviso, Cargando, Disponibilidad, Encabezado, EnlacePaciente, IconoAlerta, Metrica, NivelBadge, Pasos } from "../componentes/comunes";
import { useApp } from "../contexto";
import { ETIQUETA_DISP, num, VALOR_NIVEL } from "../utils";

const NIVELES = ["alta", "media", "baja"] as const;
type Vista = "todas" | "alertas" | "cambios" | "casos";
const VISTAS: { id: Vista; etiqueta: string; icono: typeof Star }[] = [
  { id: "todas", etiqueta: "Todas", icono: ListOrdered },
  { id: "alertas", etiqueta: "Con alerta", icono: AlertTriangle },
  { id: "cambios", etiqueta: "Propuesta de cambio", icono: ArrowUp },
  { id: "casos", etiqueta: "Casos de referencia", icono: Star },
];

export default function Bandeja() {
  const { corte, version } = useApp();
  const navegar = useNavigate();
  const { data, error, cargando } = useApi<{ corte: string; filas: FilaBandeja[] }>(`/api/bandeja?corte=${corte}`, version);
  const [especialidad, setEspecialidad] = useState<string>("Todas");
  const [niveles, setNiveles] = useState<string[]>([...NIVELES]);
  const [disp, setDisp] = useState<string>("");
  const [texto, setTexto] = useState("");
  const [vista, setVista] = useState<Vista>("todas");

  const filas = data?.filas ?? [];
  const colas = useMemo(() => {
    const m = new Map<string, { total: number; alertas: number; suben: number }>();
    for (const f of filas) {
      const c = m.get(f.especialidad) ?? { total: 0, alertas: 0, suben: 0 };
      c.total += 1;
      c.alertas += f.alerta;
      c.suben += f.cambio === "sube" ? 1 : 0;
      m.set(f.especialidad, c);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [filas]);

  const cola = especialidad === "Todas" ? filas : filas.filter((f) => f.especialidad === especialidad);
  const visibles = useMemo(() => {
    const t = texto.trim().toLowerCase();
    let v = cola.filter((f) => niveles.includes(f.nivel_propuesto));
    if (disp) v = v.filter((f) => f.disponibilidad === disp);
    if (t) v = v.filter((f) => `${f.id_paciente} ${f.nombre} ${f.cie10} ${f.diagnostico}`.toLowerCase().includes(t));
    if (vista === "alertas") v = v.filter((f) => f.alerta === 1);
    if (vista === "cambios") v = v.filter((f) => f.cambio !== "igual");
    if (vista === "casos") v = v.filter((f) => f.caso_referencia);
    if (especialidad === "Todas") {
      v = [...v].sort((a, b) => b.alerta - a.alerta || VALOR_NIVEL[b.nivel_propuesto] - VALOR_NIVEL[a.nivel_propuesto] || b.puntaje_vigente - a.puntaje_vigente);
    } else {
      v = [...v].sort((a, b) => a.posicion_dinamica - b.posicion_dinamica);
    }
    return v;
  }, [cola, niveles, disp, texto, vista, especialidad]);
  const maxPuntaje = Math.max(1, ...filas.map((f) => f.puntaje_vigente));
  const alertas = cola.reduce((s, f) => s + f.alerta, 0);
  const suben = cola.filter((f) => f.cambio === "sube").length;
  const bajan = cola.filter((f) => f.cambio === "baja").length;

  return (
    <>
      <Encabezado icono={ClipboardList} titulo="Lista de espera priorizada"
        descripcion={<>Una cola por especialidad al <b>{corte}</b>, ordenada por alerta, nivel propuesto y puntaje.</>} />
      <Pasos actual={-1} pasos={[
        { titulo: "Elige la cola", detalle: "una especialidad o todas" },
        { titulo: "Revisa alertas y propuestas", detalle: "filtra lo que requiere decisión" },
        { titulo: "Abre la ficha y decide", detalle: "acepta, ajusta o rechaza" },
      ]} />
      {error && <Aviso tipo="error">No se pudo cargar la lista: {error}</Aviso>}
      {cargando && !data && <Cargando texto="Evaluando la lista a la fecha de corte…" />}
      {data && (
        <>
          <div className="colas">
            <button className={`cola${especialidad === "Todas" ? " activa" : ""}`} onClick={() => setEspecialidad("Todas")}>
              <b>Todas las especialidades</b>
              <div className="fila">
                <span>{filas.length} en espera</span>
                <span className={filas.some((f) => f.alerta) ? "con-alerta" : ""}><AlertTriangle size={12} />{filas.reduce((s, f) => s + f.alerta, 0)}</span>
              </div>
            </button>
            {colas.map(([esp, c]) => (
              <button key={esp} className={`cola${especialidad === esp ? " activa" : ""}`} onClick={() => setEspecialidad(esp)}>
                <b>{esp}</b>
                <div className="fila">
                  <span>{c.total} en espera</span>
                  <span className={c.alertas ? "con-alerta" : ""}><AlertTriangle size={12} />{c.alertas}</span>
                  <span title="Propuestas de subir"><ArrowUp size={12} />{c.suben}</span>
                </div>
              </button>
            ))}
          </div>

          <div className="metricas">
            <Metrica etiqueta="En espera" valor={cola.length} detalle={especialidad === "Todas" ? "todas las especialidades" : especialidad} />
            <Metrica icono={AlertTriangle} tono={alertas ? "alta" : undefined} etiqueta="Alertas" valor={alertas}
              detalle="evento grave reciente o síntoma de alarma" />
            <Metrica icono={ArrowUp} etiqueta="Propuestas de cambio" valor={suben + bajan} detalle={`${suben} suben · ${bajan} bajan (con evidencia de mejora)`} />
            <Metrica icono={UserX} etiqueta="No listos para box" valor={cola.filter((f) => f.disponibilidad !== "lista").length}
              detalle="mantienen su lugar en la cola" />
          </div>

          <div className="tarjeta compacta fila">
            <div className="buscador">
              <Search size={15} />
              <input placeholder="Paciente, ID o diagnóstico" value={texto} onChange={(e) => setTexto(e.target.value)} />
            </div>
            <div className="segmentado" role="group" aria-label="Vista rápida">
              {VISTAS.map((v) => {
                const Icono = v.icono;
                return <button key={v.id} className={vista === v.id ? "activo" : ""} onClick={() => setVista(v.id)}><Icono size={14} />{v.etiqueta}</button>;
              })}
            </div>
            <div className="segmentado" role="group" aria-label="Nivel propuesto">
              {NIVELES.map((n) => (
                <button key={n} className={niveles.includes(n) ? "activo" : ""}
                  onClick={() => setNiveles(niveles.includes(n) ? niveles.filter((x) => x !== n) : [...niveles, n])}>{n}</button>
              ))}
            </div>
            <select value={disp} onChange={(e) => setDisp(e.target.value)} aria-label="Disponibilidad">
              <option value="">Cualquier disponibilidad</option>
              {Object.entries(ETIQUETA_DISP).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <small className="suave" style={{ marginLeft: "auto" }}>{visibles.length} solicitudes · clic para abrir la ficha</small>
          </div>

          <div className="tabla-envoltura alta">
            <table>
              <thead>
                <tr>
                  <th className="num" title="Posición en su cola si se aceptan las propuestas (y en la lista congelada)">Posición</th>
                  <th />
                  <th>Paciente</th>
                  {especialidad === "Todas" && <th>Especialidad</th>}
                  <th>Diagnóstico</th>
                  <th title="Prioridad vigente → propuesta del sistema">Prioridad</th>
                  <th title="Puntaje de orden dentro del nivel">Puntaje</th>
                  <th>Motivo principal</th>
                  <th className="num">Espera</th>
                  <th>Disponibilidad</th>
                </tr>
              </thead>
              <tbody>
                {visibles.map((f) => (
                  <tr key={f.id_solicitud} className={`clic${f.alerta ? " marcada" : ""}`} onClick={() => navegar(`/ficha/${f.id_solicitud}`)}>
                    <td className="num">
                      <b>{f.posicion_dinamica}</b><small className="suave">/{f.total_cola}</small>
                      <div title="Posición en la lista congelada (prioridad inicial y orden de llegada)">
                        <small className={f.avance_posiciones > 0 ? "cambio-sube" : f.avance_posiciones < 0 ? "cambio-baja" : "suave"}>
                          {f.avance_posiciones > 0 ? `+${f.avance_posiciones}` : f.avance_posiciones || "="} vs. {f.posicion_estatica}
                        </small>
                      </div>
                    </td>
                    <td><IconoAlerta activa={f.alerta} /></td>
                    <td>
                      <EnlacePaciente id={f.id_solicitud} nombre={f.nombre} idPaciente={f.id_paciente} />
                      {f.caso_referencia && <div><span className="etiqueta-chip caso"><Star size={11} />{f.caso_referencia}</span></div>}
                    </td>
                    {especialidad === "Todas" && <td>{f.especialidad}</td>}
                    <td>
                      <div>{f.cie10} {f.diagnostico}</div>
                      <small className="suave">riesgo basal {f.riesgo_basal}</small>
                    </td>
                    <td>
                      <span className="transicion">
                        <NivelBadge nivel={f.prioridad_vigente} />
                        {f.cambio !== "igual" && <>
                          {f.cambio === "sube" ? <ArrowUp size={14} className="cambio-sube" /> : f.cambio === "baja" ? <ArrowDown size={14} className="cambio-baja" /> : <ArrowRight size={14} />}
                          <NivelBadge nivel={f.nivel_propuesto} />
                        </>}
                      </span>
                    </td>
                    <td>
                      <div className="barra-puntaje" title={`Nivel ${num(f.puntaje_nivel)} · orden ${num(f.puntaje_vigente)}` +
                        (f.ajuste_puntaje ? ` (motor ${num(f.puntaje)}, ajuste de la Administradora ${f.ajuste_puntaje > 0 ? "+" : "−"}${num(Math.abs(f.ajuste_puntaje))})` : "")}>
                        <div style={{ width: `${(64 * Math.max(0, f.puntaje_vigente)) / maxPuntaje}px` }} />
                        {num(f.puntaje_vigente)}{f.ajuste_puntaje ? " *" : ""}
                      </div>
                    </td>
                    <td style={{ minWidth: 240 }}>{f.motivo_principal}</td>
                    <td className="num">{f.dias_espera} d</td>
                    <td><Disponibilidad estado={f.disponibilidad} accion={f.accion} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <small className="suave">* Puntaje ajustado por la Administradora. La lista congelada es la posición que tendría el paciente si su prioridad nunca se hubiera actualizado.</small>
        </>
      )}
    </>
  );
}
