import { History, RotateCcw, Save, Search, SlidersHorizontal, FlaskConical } from "lucide-react";
import { useMemo, useState } from "react";
import { postJSON, Registro, useApi } from "../api";
import { Aviso, Cargando, Encabezado, Metrica, NivelBadge, Pasos, Pestanas, Tabla } from "../componentes/comunes";
import { useApp } from "../contexto";

type Valor = number | string;
interface Parametro {
  clave: string;
  grupo: string;
  nombre: string;
  descripcion: string;
  tipo: "numero" | "entero" | "opcion";
  unidad: string;
  minimo: number | null;
  maximo: number | null;
  opciones: string[];
  valor: Valor;
  fabrica: Valor;
}
interface Catalogo {
  version: string;
  numero: number;
  parametros: Parametro[];
  solo_lectura: { grupo: string; nombre: string; valor: string }[];
  fecha_corte: string;
}
interface Cambio { clave: string; nombre: string; grupo: string; anterior: Valor; nuevo: Valor }
interface Version {
  numero: number;
  version: string;
  motivo: string;
  creada_por: string | null;
  creada_en: string | null;
  restaura: number | null;
  cambios: Cambio[];
  vigente: boolean;
}
interface Simulacion {
  fecha_corte: string;
  total: number;
  suben: number;
  bajan: number;
  cambian_puntaje: number;
  niveles: Record<string, { actual: number; simulado: number }>;
  mayores_cambios: Registro[];
  cambios: Cambio[];
}

/** Mensaje de la API: 422 con {mensaje, errores} por parámetro, o un texto. */
function leer(e: unknown): { texto: string; errores: Record<string, string> } {
  const texto = (e as Error).message;
  try {
    const d = JSON.parse(texto);
    if (d && typeof d === "object" && d.errores) return { texto: d.mensaje ?? "Hay parámetros inválidos", errores: d.errores };
  } catch {
    /* texto plano */
  }
  return { texto, errores: {} };
}

function fuera(p: Parametro, v: Valor): string | null {
  if (p.tipo === "opcion") return p.opciones.includes(String(v)) ? null : "opción no válida";
  const n = Number(v);
  if (v === "" || Number.isNaN(n)) return "debe ser un número";
  if (p.tipo === "entero" && !Number.isInteger(n)) return "debe ser entero";
  if ((p.minimo != null && n < p.minimo) || (p.maximo != null && n > p.maximo)) return `entre ${p.minimo} y ${p.maximo}`;
  return null;
}

export default function Reglas() {
  const { version, consolidacion, seguirConsolidacion } = useApp();
  const [refresco, setRefresco] = useState(0);
  const { data, error } = useApi<Catalogo>("/api/reglas", version + refresco);
  const historial = useApi<{ vigente: number; versiones: Version[] }>("/api/reglas/versiones", version + refresco);
  const [pestana, setPestana] = useState<"parametros" | "historial">("parametros");
  const [editados, setEditados] = useState<Record<string, Valor>>({});
  const [filtro, setFiltro] = useState("");
  const [motivo, setMotivo] = useState("");
  const [sim, setSim] = useState<Simulacion | null>(null);
  const [falla, setFalla] = useState<{ texto: string; errores: Record<string, string> } | null>(null);
  const [ocupado, setOcupado] = useState<"simular" | "guardar" | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const enCurso = !!consolidacion?.en_curso;

  const params = data?.parametros ?? [];
  const cambios = useMemo(() => params.filter((p) => p.clave in editados && String(editados[p.clave]) !== String(p.valor)),
    [params, editados]);
  const invalidos = cambios.filter((p) => fuera(p, editados[p.clave]));
  const valores = () => Object.fromEntries(cambios.map((p) => [p.clave, p.tipo === "opcion" ? editados[p.clave] : Number(editados[p.clave])]));
  const grupos = useMemo(() => {
    const f = filtro.trim().toLowerCase();
    const visibles = params.filter((p) => !f || `${p.nombre} ${p.grupo} ${p.descripcion}`.toLowerCase().includes(f));
    return [...new Set(visibles.map((p) => p.grupo))].map((g) => ({ grupo: g, filas: visibles.filter((p) => p.grupo === g) }));
  }, [params, filtro]);

  const cambiar = (p: Parametro, v: Valor) => {
    setSim(null);
    setEditados((e) => ({ ...e, [p.clave]: v }));
  };
  const descartar = () => {
    setEditados({});
    setSim(null);
    setFalla(null);
  };
  const simular = async () => {
    setOcupado("simular");
    setFalla(null);
    try {
      setSim(await postJSON<Simulacion>("/api/reglas/simulacion", { valores: valores() }));
    } catch (e) {
      setFalla(leer(e));
    } finally {
      setOcupado(null);
    }
  };
  const guardar = async () => {
    setOcupado("guardar");
    setFalla(null);
    try {
      const r = await postJSON<{ version: string }>("/api/reglas/versiones", { valores: valores(), motivo });
      setAviso(`Guardada la versión ${r.version}. Se está recalculando la historia completa con los valores nuevos.`);
      setEditados({});
      setMotivo("");
      setSim(null);
      setRefresco((x) => x + 1);
      seguirConsolidacion();
    } catch (e) {
      setFalla(leer(e));
    } finally {
      setOcupado(null);
    }
  };
  const restaurar = async (v: Version) => {
    const m = window.prompt(`Motivo para volver a ${v.version}:`);
    if (!m) return;
    setFalla(null);
    try {
      const r = await postJSON<{ version: string }>(`/api/reglas/versiones/${v.numero}/restaurar`, { motivo: m });
      setAviso(`Se creó la versión ${r.version} con los valores de ${v.version}. Se está recalculando la historia.`);
      setRefresco((x) => x + 1);
      seguirConsolidacion();
    } catch (e) {
      setFalla(leer(e));
    }
  };

  return (
    <>
      <Encabezado icono={SlidersHorizontal} titulo="Reglas del puntaje"
        descripcion="Pesos, umbrales y ventanas del motor. Cada cambio es una versión nueva con motivo, y siempre se puede volver atrás." />
      {error && <Aviso tipo="error">{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      {enCurso && <Aviso tipo="atencion">Hay un recálculo en curso: espera a que termine para simular o guardar otra versión.</Aviso>}
      {falla && (
        <Aviso tipo="error">
          {falla.texto}
          {Object.values(falla.errores).length > 0 && <ul>{Object.values(falla.errores).map((m) => <li key={m}>{m}</li>)}</ul>}
        </Aviso>
      )}
      {!data ? <Cargando /> : (
        <>
          <div className="metricas">
            <Metrica etiqueta="Versión vigente" valor={data.version} destacada
              detalle={data.numero === 0 ? "valores de fábrica" : `versión ${data.numero}`} />
            <Metrica etiqueta="Parámetros editables" valor={params.length} />
            <Metrica etiqueta="Distintos de fábrica" valor={params.filter((p) => String(p.valor) !== String(p.fabrica)).length} />
          </div>
          <Pestanas opciones={[{ id: "parametros", etiqueta: "Parámetros", icono: SlidersHorizontal }, { id: "historial", etiqueta: "Historial de versiones", icono: History }]}
            activa={pestana} onCambio={setPestana} />

          {pestana === "parametros" && (
            <>
              <Pasos actual={sim ? 2 : cambios.length ? 1 : 0} pasos={[
                { titulo: "Cambia los valores", detalle: "se marcan y validan al escribir" },
                { titulo: "Simula el efecto", detalle: "quién sube o baja, sin guardar" },
                { titulo: "Guarda con motivo", detalle: "versión nueva y recálculo" },
              ]} />
              <div className="tarjeta pila reglas-acciones">
                <div className="fila entre">
                  <div className="buscador">
                    <Search size={15} />
                    <input placeholder="Buscar regla: UCI, glicemia…" value={filtro} onChange={(e) => setFiltro(e.target.value)} />
                  </div>
                  <b>{cambios.length === 0 ? "Sin cambios" : `${cambios.length} cambio${cambios.length > 1 ? "s" : ""}`}</b>
                </div>
                {cambios.length > 0 && (
                  <>
                    <textarea placeholder="Motivo del cambio (obligatorio): qué se acordó y con quién" value={motivo}
                      onChange={(e) => setMotivo(e.target.value)} rows={2} />
                    <div className="fila">
                      <button className="boton" onClick={simular} disabled={!!ocupado || enCurso || invalidos.length > 0}>
                        <FlaskConical size={15} /> {ocupado === "simular" ? "Simulando…" : "Simular el efecto"}
                      </button>
                      <button className="boton primario" onClick={guardar}
                        disabled={!!ocupado || enCurso || invalidos.length > 0 || motivo.trim().length < 5}
                        title={motivo.trim().length < 5 ? "Escribe el motivo" : ""}>
                        <Save size={15} /> {ocupado === "guardar" ? "Guardando…" : "Guardar como versión nueva"}
                      </button>
                      <button className="boton" onClick={descartar} disabled={!!ocupado}>Descartar</button>
                      {invalidos.length > 0 && <small style={{ color: "#c0392b" }}>Corrige los valores marcados en rojo.</small>}
                    </div>
                  </>
                )}
              </div>

              {sim && (
                <div className="tarjeta pila">
                  <h3>Simulación a la fecha de corte {sim.fecha_corte} (no se guardó nada)</h3>
                  <div className="metricas">
                    <Metrica etiqueta="Suben de nivel" valor={sim.suben} detalle={`de ${sim.total} solicitudes`} />
                    <Metrica etiqueta="Bajan de nivel" valor={sim.bajan} />
                    <Metrica etiqueta="Cambian de puntaje" valor={sim.cambian_puntaje} />
                    {Object.entries(sim.niveles).map(([n, c]) => (
                      <Metrica key={n} etiqueta={`Nivel ${n}`} valor={`${c.actual} → ${c.simulado}`} />
                    ))}
                  </div>
                  <Tabla filas={sim.mayores_cambios} vacia="Ninguna solicitud cambia de puntaje con estos valores."
                    columnas={[
                      { clave: "nombre", titulo: "Paciente" }, { clave: "especialidad", titulo: "Especialidad" },
                      { clave: "nivel_actual", titulo: "Nivel hoy", render: (f) => <NivelBadge nivel={f.nivel_actual} /> },
                      { clave: "nivel_simulado", titulo: "Nivel simulado", render: (f) => <NivelBadge nivel={f.nivel_simulado} /> },
                      { clave: "puntaje_actual", titulo: "Puntaje hoy" }, { clave: "puntaje_simulado", titulo: "Simulado" },
                      { clave: "diferencia", titulo: "Diferencia", render: (f) => (f.diferencia > 0 ? "+" : "") + f.diferencia },
                    ]} />
                </div>
              )}

              {grupos.map(({ grupo, filas }) => (
                <div key={grupo} className="tarjeta pila">
                  <h3>{grupo}</h3>
                  <table className="reglas">
                    <thead><tr><th>Regla</th><th>Valor</th><th>Fábrica</th><th>Límites</th><th /></tr></thead>
                    <tbody>
                      {filas.map((p) => {
                        const v = p.clave in editados ? editados[p.clave] : p.valor;
                        const cambiado = String(v) !== String(p.valor);
                        const problema = cambiado ? fuera(p, v) : null;
                        return (
                          <tr key={p.clave} className={cambiado ? "cambiada" : ""}>
                            <td><b>{p.nombre}</b>{p.descripcion && <div><small className="suave">{p.descripcion}</small></div>}</td>
                            <td className="valor">
                              {p.tipo === "opcion" ? (
                                <select value={String(v)} onChange={(e) => cambiar(p, e.target.value)}>
                                  {p.opciones.map((o) => <option key={o} value={o}>{o}</option>)}
                                </select>
                              ) : (
                                <input type="number" value={v} step={p.tipo === "entero" ? 1 : "any"}
                                  min={p.minimo ?? undefined} max={p.maximo ?? undefined}
                                  onChange={(e) => cambiar(p, e.target.value)}
                                  className={problema ? "invalido" : ""} title={problema ?? ""} />
                              )}
                              {p.unidad && <small className="suave"> {p.unidad}</small>}
                              {problema && <div><small style={{ color: "#c0392b" }}>{problema}</small></div>}
                            </td>
                            <td className={String(p.valor) !== String(p.fabrica) ? "distinto" : "suave"}>{String(p.fabrica)}</td>
                            <td className="suave">{p.tipo === "opcion" ? p.opciones.join(" · ") : `${p.minimo} a ${p.maximo}`}</td>
                            <td>
                              {(cambiado || String(p.valor) !== String(p.fabrica)) && (
                                <button className="boton chico" title="Volver al valor de fábrica" disabled={!!ocupado}
                                  onClick={() => cambiar(p, p.fabrica)}><RotateCcw size={13} /></button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ))}
              <div className="tarjeta pila">
                <h3>Referencia (no editable)</h3>
                <Tabla filas={data.solo_lectura} columnas={[
                  { clave: "grupo", titulo: "Grupo" }, { clave: "nombre", titulo: "Regla" }, { clave: "valor", titulo: "Valor" }]} />
              </div>
            </>
          )}

          {pestana === "historial" && (
            !historial.data ? <Cargando /> : (
              <div className="pila">
                {historial.data.versiones.map((v) => (
                  <div key={v.numero} className="tarjeta compacta pila">
                    <div className="fila entre">
                      <b>{v.version}{v.vigente && <span className="etiqueta-vigente"> vigente</span>}</b>
                      <small className="suave">
                        {v.creada_en ? `${v.creada_en.replace("T", " ").slice(0, 16)} · ${v.creada_por}` : "incluida en el código"}
                        {v.restaura != null && ` · restaura la versión ${v.restaura}`}
                      </small>
                    </div>
                    <div>{v.motivo}</div>
                    {v.cambios.length > 0 && (
                      <ul className="cambios">
                        {v.cambios.map((c) => <li key={c.clave}><b>{c.nombre}</b>: {String(c.anterior)} → {String(c.nuevo)}</li>)}
                      </ul>
                    )}
                    {!v.vigente && (
                      <div><button className="boton chico" disabled={enCurso} onClick={() => restaurar(v)}>Volver a esta versión</button></div>
                    )}
                  </div>
                ))}
              </div>
            )
          )}
        </>
      )}
    </>
  );
}
