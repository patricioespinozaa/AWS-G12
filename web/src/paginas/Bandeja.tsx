import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FilaBandeja, useApi } from "../api";
import { Aviso, Cargando, EnlacePaciente, Metrica, NivelBadge } from "../componentes/comunes";
import { useApp } from "../contexto";
import { ETIQUETA_DISP, ICONO_CAMBIO, num, pct, VALOR_NIVEL } from "../utils";

const NIVELES = ["alta", "media", "baja"] as const;

export default function Bandeja() {
  const { corte, version } = useApp();
  const navegar = useNavigate();
  const { data, error, cargando } = useApi<{ corte: string; filas: FilaBandeja[] }>(`/api/bandeja?corte=${corte}`, version);
  const [especialidad, setEspecialidad] = useState<string>("Todas");
  const [niveles, setNiveles] = useState<string[]>([...NIVELES]);
  const [disp, setDisp] = useState<string>("");
  const [texto, setTexto] = useState("");
  const [soloCambios, setSoloCambios] = useState(false);
  const [soloAlertas, setSoloAlertas] = useState(false);
  const [soloCasos, setSoloCasos] = useState(false);

  const filas = data?.filas ?? [];
  const colas = useMemo(() => {
    const m = new Map<string, { total: number; alertas: number; suben: number; alta: number }>();
    for (const f of filas) {
      const c = m.get(f.especialidad) ?? { total: 0, alertas: 0, suben: 0, alta: 0 };
      c.total += 1;
      c.alertas += f.alerta;
      c.suben += f.cambio === "sube" ? 1 : 0;
      c.alta += f.nivel_propuesto === "alta" ? 1 : 0;
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
    if (soloCambios) v = v.filter((f) => f.cambio !== "igual");
    if (soloAlertas) v = v.filter((f) => f.alerta === 1);
    if (soloCasos) v = v.filter((f) => f.caso_referencia);
    if (especialidad === "Todas") {
      v = [...v].sort((a, b) => b.alerta - a.alerta || VALOR_NIVEL[b.nivel_propuesto] - VALOR_NIVEL[a.nivel_propuesto] || b.puntaje_vigente - a.puntaje_vigente);
    } else {
      v = [...v].sort((a, b) => a.posicion_dinamica - b.posicion_dinamica);
    }
    return v;
  }, [cola, niveles, disp, texto, soloCambios, soloAlertas, soloCasos, especialidad]);
  const maxPuntaje = Math.max(1, ...filas.map((f) => f.puntaje_vigente));

  return (
    <>
      <div className="encabezado">
        <h1>📋 Bandeja priorizada</h1>
        <p>
          Colas individuales por especialidad al <b>{corte}</b>. Orden: alerta → nivel propuesto → puntaje (incluye el
          riesgo basal del diagnóstico y, si lo hay, el ajuste de la Administradora ✎) → orden de llegada. <b>Lista congelada</b> es la posición que tendría el paciente
          si su prioridad no se hubiera actualizado nunca.
        </p>
      </div>
      {error && <Aviso tipo="error">No se pudo cargar la bandeja: {error}</Aviso>}
      {cargando && !data && <Cargando texto="Evaluando la lista a la fecha de corte…" />}
      {data && (
        <>
          <div className="colas">
            <button className={`cola${especialidad === "Todas" ? " activa" : ""}`} onClick={() => setEspecialidad("Todas")}>
              <b>Todas las colas</b>
              <div className="fila"><span>{filas.length} en lista</span><span>⚠️ {filas.reduce((s, f) => s + f.alerta, 0)}</span></div>
            </button>
            {colas.map(([esp, c]) => (
              <button key={esp} className={`cola${especialidad === esp ? " activa" : ""}`} onClick={() => setEspecialidad(esp)}>
                <b>{esp}</b>
                <div className="fila">
                  <span>{c.total} en lista</span>
                  <span>⚠️ {c.alertas}</span>
                  <span>↑ {c.suben}</span>
                  <span className="nivel alta">{c.alta}</span>
                </div>
              </button>
            ))}
          </div>

          <div className="metricas">
            <Metrica etiqueta="En lista" valor={cola.length} detalle={especialidad === "Todas" ? "todas las colas" : especialidad} />
            <Metrica etiqueta="⚠️ Alertas" valor={cola.reduce((s, f) => s + f.alerta, 0)} detalle="evento grave reciente o síntoma de alarma validado" />
            <Metrica etiqueta="↑ Propuestas de subir" valor={cola.filter((f) => f.cambio === "sube").length} />
            <Metrica etiqueta="↓ Propuestas de bajar" valor={cola.filter((f) => f.cambio === "baja").length} detalle="solo con evidencia de mejora" />
            <Metrica etiqueta="No listos para box" valor={cola.filter((f) => f.disponibilidad !== "lista").length} detalle="no pierden su lugar" />
            <Metrica etiqueta="Adelantan ≥ 10 posiciones" valor={cola.filter((f) => f.avance_posiciones >= 10).length} detalle="vs. lista congelada" />
          </div>

          <div className="tarjeta compacta">
            <div className="fila">
              <input placeholder="Buscar paciente, ID o diagnóstico…" value={texto} onChange={(e) => setTexto(e.target.value)} style={{ minWidth: 260 }} />
              <span className="suave">Nivel:</span>
              {NIVELES.map((n) => (
                <label key={n} className="interruptor">
                  <input type="checkbox" checked={niveles.includes(n)}
                    onChange={(e) => setNiveles(e.target.checked ? [...niveles, n] : niveles.filter((x) => x !== n))} />
                  <NivelBadge nivel={n} />
                </label>
              ))}
              <select value={disp} onChange={(e) => setDisp(e.target.value)}>
                <option value="">Toda disponibilidad</option>
                {Object.entries(ETIQUETA_DISP).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <label className="interruptor"><input type="checkbox" checked={soloCambios} onChange={(e) => setSoloCambios(e.target.checked)} />Solo propuestas de cambio</label>
              <label className="interruptor"><input type="checkbox" checked={soloAlertas} onChange={(e) => setSoloAlertas(e.target.checked)} />Solo alertas</label>
              <label className="interruptor"><input type="checkbox" checked={soloCasos} onChange={(e) => setSoloCasos(e.target.checked)} />Solo casos de referencia</label>
            </div>
          </div>

          <p className="suave">{visibles.length} solicitudes · haz clic en una fila para abrir la ficha.</p>
          <div className="tabla-envoltura alta">
            <table>
              <thead>
                <tr>
                  <th className="num" title="Posición en la cola de su especialidad si se aceptan las propuestas">Pos.</th>
                  <th className="num" title="Posición con la prioridad inicial y orden de llegada">Lista congelada</th>
                  <th className="num" title="Posiciones que adelanta (+) o retrocede (−)">Δ</th>
                  <th>⚠️</th>
                  <th>Paciente</th>
                  {especialidad === "Todas" && <th>Especialidad</th>}
                  <th>Diagnóstico</th>
                  <th>Riesgo basal</th>
                  <th>Inicial</th>
                  <th>Vigente</th>
                  <th>Propuesta</th>
                  <th>Cambio</th>
                  <th>Puntaje</th>
                  <th>Motivo principal</th>
                  <th className="num">Días espera</th>
                  <th>Disponibilidad</th>
                  <th className="num">No-show</th>
                </tr>
              </thead>
              <tbody>
                {visibles.map((f) => (
                  <tr key={f.id_solicitud} className={`clic${f.alerta ? " marcada" : ""}`} onClick={() => navegar(`/ficha/${f.id_solicitud}`)}>
                    <td className="num"><b>{f.posicion_dinamica}</b><small className="suave">/{f.total_cola}</small></td>
                    <td className="num suave">{f.posicion_estatica}</td>
                    <td className={`num ${f.avance_posiciones > 0 ? "cambio-sube" : f.avance_posiciones < 0 ? "cambio-baja" : "suave"}`}>
                      {f.avance_posiciones > 0 ? `+${f.avance_posiciones}` : f.avance_posiciones}
                    </td>
                    <td>{f.alerta ? "⚠️" : ""}</td>
                    <td>
                      <EnlacePaciente id={f.id_solicitud} nombre={f.nombre} idPaciente={f.id_paciente} />
                      {f.caso_referencia && <> <span className="etiqueta-chip caso">★ {f.caso_referencia}</span></>}
                    </td>
                    {especialidad === "Todas" && <td>{f.especialidad}</td>}
                    <td>{f.cie10} {f.diagnostico}</td>
                    <td><span className="etiqueta-chip">{f.riesgo_basal}</span></td>
                    <td><NivelBadge nivel={f.prioridad_inicial} /></td>
                    <td><NivelBadge nivel={f.prioridad_vigente} /></td>
                    <td><NivelBadge nivel={f.nivel_propuesto} /></td>
                    <td className={f.cambio === "sube" ? "cambio-sube" : f.cambio === "baja" ? "cambio-baja" : "suave"}>{ICONO_CAMBIO[f.cambio]}</td>
                    <td>
                      <div className="barra-puntaje" title={`Nivel ${num(f.puntaje_nivel)} · orden ${num(f.puntaje_vigente)}` +
                        (f.ajuste_puntaje ? ` (motor ${num(f.puntaje)}, ajuste de la Administradora ${f.ajuste_puntaje > 0 ? "+" : "−"}${num(Math.abs(f.ajuste_puntaje))})` : "")}>
                        <div style={{ width: `${(70 * Math.max(0, f.puntaje_vigente)) / maxPuntaje}px` }} />
                        {num(f.puntaje_vigente)}{f.ajuste_puntaje ? " ✎" : ""}
                      </div>
                    </td>
                    <td style={{ minWidth: 260 }}>{f.motivo_principal}</td>
                    <td className="num">{f.dias_espera}</td>
                    <td title={f.accion ?? ""}>{ETIQUETA_DISP[f.disponibilidad] ?? f.disponibilidad}</td>
                    <td className="num">{pct(f.riesgo_no_show)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
