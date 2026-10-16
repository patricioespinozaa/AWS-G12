import { useState } from "react";
import { Link } from "react-router-dom";
import { descargar, postJSON, Registro, useApi } from "../api";
import { Aviso, Cargando, Tabla } from "../componentes/comunes";
import { useApp } from "../contexto";

const ARCHIVOS = ["pacientes.csv", "lista_espera.csv", "eventos_clinicos.csv", "mediciones.csv", "citaciones.csv", "agenda_box.csv"];

interface Previa {
  id_carga: number;
  estado: "lista" | "fallida";
  resumen: Record<string, { filas: number; nuevas: number; modificadas: number; sin_cambio: number }>;
  pacientes_afectados: string[];
  pacientes_nuevos: string[];
  advertencias: { tipo: string; mensaje: string; cantidad: number; ejemplos: string[] }[];
  errores: { archivo: string; linea: number | null; mensaje: string }[];
  archivos: string[];
}

function aBase64(f: File): Promise<string> {
  return new Promise((ok, mal) => {
    const lector = new FileReader();
    lector.onload = () => ok(String(lector.result));
    lector.onerror = () => mal(lector.error);
    lector.readAsDataURL(f);
  });
}

export default function Cargas() {
  const { meta, refrescar, seguirConsolidacion, version } = useApp();
  if (meta && meta.base_de_datos !== "rds") {
    return (
      <div className="tarjeta pila">
        <h2>Cargas de datos por periodo</h2>
        <Aviso tipo="info">
          Las cargas por periodo guardan versiones en la base de datos (RDS). Esta instancia corre en modo local:
          los datos se leen de los CSV de <code>HLF_DATA_DIR</code>.
        </Aviso>
      </div>
    );
  }
  return (
    <div className="pila">
      <Subida onAplicada={() => { refrescar(); seguirConsolidacion(); }} />
      <Historial version={version} />
    </div>
  );
}

function Subida({ onAplicada }: { onAplicada: () => void }) {
  const [archivos, setArchivos] = useState<File[]>([]);
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [previa, setPrevia] = useState<Previa | null>(null);
  const [resultado, setResultado] = useState<Registro | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState<"" | "validando" | "aplicando">("");

  const validar = async () => {
    setOcupado("validando"); setError(null); setPrevia(null); setResultado(null);
    try {
      const cuerpo = {
        periodo_desde: desde || null, periodo_hasta: hasta || null,
        archivos: await Promise.all(archivos.map(async (f) => ({ nombre: f.name, contenido_base64: await aBase64(f) }))),
      };
      setPrevia(await postJSON<Previa>("/api/cargas", cuerpo));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setOcupado("");
    }
  };
  const confirmar = async () => {
    if (!previa) return;
    setOcupado("aplicando"); setError(null);
    try {
      setResultado(await postJSON<Registro>(`/api/cargas/${previa.id_carga}/confirmar`));
      setPrevia(null); setArchivos([]);
      onAplicada();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setOcupado("");
    }
  };
  const descartar = async () => {
    if (!previa) return;
    await postJSON(`/api/cargas/${previa.id_carga}/descartar`);
    setPrevia(null);
    onAplicada();
  };

  const desconocidos = archivos.filter((f) => !ARCHIVOS.includes(f.name));
  const resumen = previa ? Object.entries(previa.resumen).map(([tabla, r]) => ({ tabla, ...r })) : [];
  return (
    <div className="tarjeta pila">
      <h2>Cargar datos de un periodo nuevo</h2>
      <p className="suave">
        Sube los CSV exportados del periodo (todos o algunos de: {ARCHIVOS.join(", ")}). Los datos se <b>suman</b> a lo
        que ya existe: un paciente con datos previos recibe la información nueva sobre su historia y nada se borra.
        Antes de confirmar verás exactamente qué cambia.
      </p>
      <div className="fila">
        <label className="campo"><span>Periodo desde</span><input type="date" value={desde} onChange={(e) => setDesde(e.target.value)} /></label>
        <label className="campo"><span>Periodo hasta</span><input type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} /></label>
        <label className="campo"><span>Archivos CSV</span>
          <input type="file" accept=".csv,text/csv" multiple onChange={(e) => { setArchivos(Array.from(e.target.files ?? [])); setPrevia(null); setResultado(null); }} />
        </label>
      </div>
      {archivos.length > 0 && <small>{archivos.length} archivo(s): {archivos.map((f) => f.name).join(", ")}</small>}
      {desconocidos.length > 0 && <Aviso tipo="atencion">No son archivos del dataset: {desconocidos.map((f) => f.name).join(", ")}</Aviso>}
      <div className="fila">
        <button className="boton primario" disabled={!archivos.length || !!ocupado} onClick={validar}>
          {ocupado === "validando" ? "Validando…" : "Validar y ver vista previa"}
        </button>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {resultado && (
        <Aviso tipo="exito">
          Versión <b>{String(resultado.version)}</b> aplicada ({(resultado.pacientes_afectados as string[]).length} pacientes
          con datos nuevos). Las prioridades se están recalculando en segundo plano: el aviso de arriba indica cuándo
          termina. <Link to="/bandeja">Ir a la bandeja →</Link>
        </Aviso>
      )}
      {previa && (
        <div className="pila">
          <h3>Vista previa (carga {previa.id_carga}) — nada se ha escrito todavía</h3>
          {previa.estado === "fallida" ? (
            <>
              <Aviso tipo="error">La carga tiene errores y no se puede confirmar. Corrige los archivos y vuelve a subirlos.</Aviso>
              <Tabla filas={previa.errores as unknown as Registro[]}
                columnas={[{ clave: "archivo", titulo: "Archivo" }, { clave: "linea", titulo: "Línea", num: true }, { clave: "mensaje", titulo: "Problema" }]} />
            </>
          ) : (
            <>
              <Tabla filas={resumen as unknown as Registro[]}
                columnas={[{ clave: "tabla", titulo: "Tabla" }, { clave: "filas", titulo: "Filas", num: true },
                  { clave: "nuevas", titulo: "Nuevas", num: true }, { clave: "modificadas", titulo: "Modificadas", num: true },
                  { clave: "sin_cambio", titulo: "Sin cambio", num: true }]} />
              <p>
                <b>{previa.pacientes_afectados.length}</b> pacientes reciben datos nuevos o modificados
                ({previa.pacientes_nuevos.length} pacientes nuevos). Sus solicitudes se recalculan al confirmar.
              </p>
              {previa.advertencias.map((a) => (
                <Aviso key={a.tipo} tipo="atencion">
                  <b>{a.mensaje}: {a.cantidad}</b>
                  <br /><small>{a.ejemplos.slice(0, 5).join(" · ")}{a.cantidad > 5 ? " · …" : ""}</small>
                </Aviso>
              ))}
            </>
          )}
          <div className="fila">
            <button className="boton primario" disabled={previa.estado !== "lista" || !!ocupado} onClick={confirmar}>
              {ocupado === "aplicando" ? "Aplicando y recalculando…" : "Confirmar carga"}
            </button>
            <button className="boton" disabled={!!ocupado} onClick={descartar}>Descartar</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Historial({ version }: { version: number }) {
  const { data, error } = useApi<Registro[]>("/api/cargas", version);
  const [elegida, setElegida] = useState<number | null>(null);
  const detalle = useApi<Registro>(elegida ? `/api/cargas/${elegida}` : null, version);
  const total = (r: Registro, campo: string) =>
    r.resumen ? Object.values(r.resumen as Record<string, Record<string, number>>).reduce((s, x) => s + (x[campo] ?? x[campo === "nuevas" ? "insertadas" : "actualizadas"] ?? 0), 0) : 0;
  return (
    <div className="tarjeta pila">
      <h2>Versiones de los datos</h2>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!data ? <Cargando /> : (
        <Tabla filas={data} onFila={(f) => setElegida(Number(f.id_carga))} vacia="Aún no hay cargas."
          columnas={[
            { clave: "version", titulo: "Versión", render: (f) => (f.version ? <b>v{String(f.version)}</b> : "—") },
            { clave: "estado", titulo: "Estado" }, { clave: "modo", titulo: "Modo" },
            { clave: "periodo_desde", titulo: "Periodo", render: (f) => (f.periodo_desde || f.periodo_hasta ? `${f.periodo_desde ?? "…"} a ${f.periodo_hasta ?? "…"}` : "—") },
            { clave: "cargado_por", titulo: "Subió" },
            { clave: "inicio", titulo: "Fecha", render: (f) => String(f.inicio ?? "").slice(0, 16).replace("T", " ") },
            { clave: "nuevas", titulo: "Nuevas", num: true, render: (f) => total(f, "nuevas") },
            { clave: "modificadas", titulo: "Modificadas", num: true, render: (f) => total(f, "modificadas") },
            { clave: "archivos", titulo: "Originales", render: (f) => (f.uri_archivos ? Object.keys((f.archivos as object) ?? {}).map((n) => (
              <a key={n} href="#" onClick={(e) => { e.preventDefault(); e.stopPropagation(); descargar(`/api/cargas/${f.id_carga}/archivos/${n}`, `carga${f.id_carga}_${n}`).catch((err) => alert((err as Error).message)); }}>{n.replace(".csv", "")} </a>)) : "—") },
          ]} />
      )}
      {elegida && detalle.data && (
        <div className="pila">
          <h3>Cambios de la carga {elegida} (valor anterior → nuevo)</h3>
          <Tabla filas={(detalle.data.cambios as Registro[]) ?? []} vacia="Esta carga no modificó filas existentes (solo agregó)."
            columnas={[
              { clave: "tabla", titulo: "Tabla" },
              { clave: "llave", titulo: "Fila", render: (f) => Object.values(f.llave as object).join(" · ") },
              { clave: "antes", titulo: "Cambio", render: (f) => {
                const a = f.antes as Registro, d = f.despues as Registro;
                return Object.keys(d).filter((k) => JSON.stringify(a[k]) !== JSON.stringify(d[k]))
                  .map((k) => `${k}: ${String(a[k])} → ${String(d[k])}`).join("; ");
              } },
            ]} />
        </div>
      )}
    </div>
  );
}
