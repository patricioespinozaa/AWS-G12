import {
  BarChart3, CalendarClock, CalendarDays, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Cross,
  Inbox, ListOrdered, LogOut, MessageSquareText, MoonStar, Sparkles, SlidersHorizontal, Upload, UserRound,
} from "lucide-react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { Registro, useApi } from "./api";
import { useSesion } from "./auth/ProveedorSesion";
import { Cargando } from "./componentes/comunes";
import { useApp } from "./contexto";
import Agenda from "./paginas/Agenda";
import Bandeja from "./paginas/Bandeja";
import Canal from "./paginas/Canal";
import Consulta from "./paginas/Consulta";
import Cargas from "./paginas/Cargas";
import Ficha from "./paginas/Ficha";
import Kpis from "./paginas/Kpis";
import Nocturno from "./paginas/Nocturno";
import Reglas from "./paginas/Reglas";
import { sumarDias } from "./utils";

function AvisoRecalculo() {
  const { consolidacion } = useApp();
  if (!consolidacion) return null;
  if (consolidacion.en_curso)
    return (
      <div className="aviso info recalculo" role="status">
        <div>
          <b>Recalculando prioridades</b> desde las {consolidacion.inicio?.slice(11, 16) ?? "ahora"}. Puedes seguir
          trabajando: la vista se actualiza al terminar.
        </div>
      </div>
    );
  if (consolidacion.error)
    return <div className="aviso error recalculo" role="alert"><div>El último recálculo falló: {consolidacion.error}</div></div>;
  return null;
}

/** Fecha de corte: el "hoy" de la vista. Se usa solo lo que el hospital sabía hasta esa noche. */
function BarraCorte() {
  const { meta, corte, setCorte } = useApp();
  if (!meta) return null;
  const esHoy = corte === meta.fecha_referencia;
  return (
    <>
      <div className="barra">
        <div className="corte">
          <label htmlFor="corte"><CalendarClock size={16} /> Fecha de corte</label>
          <button className="boton icono" onClick={() => setCorte(sumarDias(corte, -30))} title="30 días antes"><ChevronsLeft size={16} /></button>
          <button className="boton icono" onClick={() => setCorte(sumarDias(corte, -1))} title="Noche anterior"><ChevronLeft size={16} /></button>
          <input id="corte" type="date" value={corte} min={meta.fecha_min} max={meta.fecha_referencia}
            onChange={(e) => e.target.value && setCorte(e.target.value)} />
          <button className="boton icono" onClick={() => setCorte(sumarDias(corte, 1))} title="Noche siguiente" disabled={esHoy}><ChevronRight size={16} /></button>
          <button className="boton icono" onClick={() => setCorte(sumarDias(corte, 30))} title="30 días después" disabled={esHoy}><ChevronsRight size={16} /></button>
          <button className={`boton chico${esHoy ? " activo" : ""}`} onClick={() => setCorte(meta.fecha_referencia)}>Hoy</button>
        </div>
        <span className="nota-corte">
          {esHoy ? <>Datos al <b>{meta.datos_al}</b></> : <>Viendo el pasado: <b>{corte}</b> · datos al {meta.datos_al}</>}
          {meta.modo_fecha === "manual" ? " (fecha fijada para un ensayo)" : ""}
        </span>
      </div>
      <AvisoRecalculo />
    </>
  );
}

function Cabecera() {
  const { meta } = useApp();
  const { salir } = useSesion();
  if (!meta) return null;
  const nombre = meta.sesion.nombre.replace(/\s*\(.*\)\s*$/, "");
  const iniciales = nombre.split(/\s+/).filter((p) => /^\p{L}/u.test(p)).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div className="cabecera">
      <div className="institucion">
        <b>Hospital Clínico Dra. Eloísa Díaz · La Florida</b>
        <small>Servicio de Salud Metropolitano Sur Oriente · Lista de espera de especialidades</small>
      </div>
      <div className="cabecera-derecha">
        {meta.llm.activo && (
          <span className="distintivo ia" title={`Amazon Bedrock · ${meta.llm.modelo}`}><Sparkles size={13} /> IA Amazon Bedrock</span>
        )}
        <div className="usuario">
          <span className="usuario-avatar">{iniciales || "A"}</span>
          <div>
            <b>{nombre}</b>
            <small>{meta.sesion.autenticacion === "cognito" ? "Administradora" : "Modo local"}</small>
          </div>
          {meta.sesion.autenticacion === "cognito" && (
            <button className="boton icono" onClick={salir} title="Cerrar sesión"><LogOut size={16} /></button>
          )}
        </div>
      </div>
    </div>
  );
}

function Lateral() {
  const { version } = useApp();
  const pendientes = useApi<{ evidencias: Registro[]; alarmas: Registro[] }>("/api/canal-pendientes", version);
  const nPendientes = (pendientes.data?.evidencias.length ?? 0) + (pendientes.data?.alarmas.length ?? 0);
  const enlace = (a: string, Icono: typeof Inbox, texto: string, contador?: number) => (
    <NavLink to={a}><Icono size={17} />{texto}{contador ? <span className="contador">{contador}</span> : null}</NavLink>
  );
  return (
    <aside className="lateral">
      <div className="marca">
        <div className="marca-logo"><Cross size={18} strokeWidth={2.6} /></div>
        <div>
          <b>Priorización dinámica</b>
          <small>Lista de espera · HLF</small>
        </div>
      </div>
      <nav className="nav">
        <div className="nav-grupo">
          <span>Trabajo diario</span>
          {enlace("/bandeja", ListOrdered, "Lista priorizada")}
          {enlace("/ficha", UserRound, "Ficha del paciente")}
          {enlace("/canal", Inbox, "Canal del paciente", nPendientes)}
          {enlace("/agenda", CalendarDays, "Agenda y box")}
        </div>
        <div className="nav-grupo">
          <span>Análisis</span>
          {enlace("/kpis", BarChart3, "Indicadores")}
          {enlace("/consulta", MessageSquareText, "Consulta")}
        </div>
        <div className="nav-grupo">
          <span>Datos y reglas</span>
          {enlace("/cargas", Upload, "Cargas de datos")}
          {enlace("/nocturno", MoonStar, "Proceso nocturno")}
          {enlace("/reglas", SlidersHorizontal, "Reglas del puntaje")}
        </div>
      </nav>
    </aside>
  );
}

export default function App() {
  const { meta, corte } = useApp();
  return (
    <div className="app">
      <Lateral />
      <main className="principal">
        <Cabecera />
        <BarraCorte />
        <div className="contenido">
          {!meta || !corte ? (
            <Cargando texto="Conectando con el servidor…" />
          ) : (
            <Routes>
              <Route path="/" element={<Navigate to="/bandeja" replace />} />
              <Route path="/bandeja" element={<Bandeja />} />
              <Route path="/ficha" element={<Ficha />} />
              <Route path="/ficha/:idSolicitud" element={<Ficha />} />
              <Route path="/agenda" element={<Agenda />} />
              <Route path="/consulta" element={<Consulta />} />
              <Route path="/canal" element={<Canal />} />
              <Route path="/kpis" element={<Kpis />} />
              <Route path="/nocturno" element={<Nocturno />} />
              <Route path="/reglas" element={<Reglas />} />
              <Route path="/cargas" element={<Cargas />} />
              <Route path="*" element={<Navigate to="/bandeja" replace />} />
            </Routes>
          )}
        </div>
      </main>
    </div>
  );
}
