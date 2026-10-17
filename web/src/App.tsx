import { NavLink, Navigate, Route, Routes } from "react-router-dom";
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

const MODO_FECHA = {
  datos: "fecha de la última carga aplicada",
  manual: "fecha fijada para un ensayo",
  local: "última fecha de los CSV locales",
};

function AvisoRecalculo() {
  const { consolidacion } = useApp();
  if (!consolidacion) return null;
  if (consolidacion.en_curso)
    return (
      <div className="aviso info recalculo" role="status">
        ⏳ Recalculando prioridades con los datos nuevos (desde {consolidacion.inicio?.slice(11, 16) ?? "ahora"}). Puedes
        seguir revisando; al terminar la vista se actualiza sola.
      </div>
    );
  if (consolidacion.error)
    return <div className="aviso error recalculo" role="alert">El último recálculo falló: {consolidacion.error}</div>;
  return null;
}

function BarraCorte() {
  const { meta, corte, setCorte } = useApp();
  if (!meta) return null;
  const esHoy = corte === meta.fecha_referencia;
  return (
    <>
    <div className="barra">
      <div className="corte">
        <label htmlFor="corte">Fecha de corte</label>
        <button className="boton chico" onClick={() => setCorte(sumarDias(corte, -30))} title="30 días antes">« 30 d</button>
        <button className="boton chico" onClick={() => setCorte(sumarDias(corte, -1))} title="Noche anterior">‹ 1 d</button>
        <input id="corte" type="date" value={corte} min={meta.fecha_min} max={meta.fecha_referencia}
          onChange={(e) => setCorte(e.target.value)} />
        <button className="boton chico" onClick={() => setCorte(sumarDias(corte, 1))} title="Noche siguiente">1 d ›</button>
        <button className="boton chico" onClick={() => setCorte(sumarDias(corte, 30))} title="30 días después">30 d »</button>
        <button className={`boton chico${esHoy ? " activo" : ""}`} onClick={() => setCorte(meta.fecha_referencia)}>
          Hoy ({meta.fecha_referencia})
        </button>
      </div>
      <span className="nota-corte" title={MODO_FECHA[meta.modo_fecha]}>
        Datos al <b>{meta.datos_al}</b>{meta.modo_fecha === "manual" ? " (fecha fijada)" : ""}. Se usa solo lo que el
        hospital sabía hasta esa noche.
      </span>
      <span className="ia">
        {meta.llm.activo ? `IA generativa: Amazon Bedrock · ${meta.llm.modelo}` : "IA generativa desactivada · explicaciones con plantilla"}
      </span>
    </div>
    <AvisoRecalculo />
    </>
  );
}

export default function App() {
  const { meta, corte } = useApp();
  const { salir } = useSesion();
  return (
    <div className="app">
      <aside className="lateral">
        <div className="marca">
          <div className="marca-logo">+</div>
          <div>
            <b>Priorización dinámica</b>
            <small>HLF · MVP con datos sintéticos</small>
          </div>
        </div>
        <nav className="nav-grupo">
          <span>Revisión</span>
          <NavLink to="/bandeja">📋 Bandeja priorizada</NavLink>
          <NavLink to="/ficha">🩺 Ficha del paciente</NavLink>
          <NavLink to="/agenda">🗓️ Agenda y box</NavLink>
          <NavLink to="/consulta">🔎 Consulta</NavLink>
        </nav>
        <nav className="nav-grupo">
          <span>Paciente (maqueta)</span>
          <NavLink to="/canal">💬 Canal del paciente</NavLink>
        </nav>
        <nav className="nav-grupo">
          <span>Gestión</span>
          <NavLink to="/kpis">📊 KPIs</NavLink>
          <NavLink to="/nocturno">🌙 Consolidación nocturna</NavLink>
          <NavLink to="/reglas">⚙️ Reglas</NavLink>
          <NavLink to="/cargas">📥 Cargas de datos</NavLink>
        </nav>
        <div className="principio">
          La herramienta <b>propone y explica</b>; la Administradora <b>decide</b>.
          <br />
          La posición en la lista no equivale a una fecha garantizada de atención.
          {meta && <><br /><br />Reglas <b>{meta.version_reglas}</b> · {meta.base_de_datos === "rds" ? "base de datos RDS" : "modo local"}</>}
        </div>
        {meta && (
          <div className="sesion">
            <span>Administradora</span>
            <b>{meta.sesion.nombre}</b>
            {meta.sesion.autenticacion === "cognito" ? (
              <button className="boton chico" onClick={salir}>Cerrar sesión</button>
            ) : (
              <small className="sin-auth">Sin autenticación: solo para desarrollo local</small>
            )}
          </div>
        )}
      </aside>
      <main className="principal">
        <BarraCorte />
        <div className="contenido">
          {!meta || !corte ? (
            <Cargando texto="Conectando con la API…" />
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
