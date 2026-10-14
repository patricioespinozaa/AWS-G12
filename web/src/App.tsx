import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { Cargando } from "./componentes/comunes";
import { useApp } from "./contexto";
import Agenda from "./paginas/Agenda";
import Bandeja from "./paginas/Bandeja";
import Canal from "./paginas/Canal";
import Ficha from "./paginas/Ficha";
import Kpis from "./paginas/Kpis";
import Nocturno from "./paginas/Nocturno";
import { sumarDias } from "./utils";

function BarraCorte() {
  const { meta, corte, setCorte } = useApp();
  if (!meta) return null;
  const esHoy = corte === meta.fecha_referencia;
  return (
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
      <span className="nota-corte">
        Se usa solo lo que el hospital sabía hasta esa noche, como en la consolidación nocturna.
      </span>
      <span className="ia">
        {meta.llm.activo ? `IA generativa: Amazon Bedrock · ${meta.llm.modelo}` : "IA generativa desactivada · explicaciones con plantilla"}
      </span>
    </div>
  );
}

export default function App() {
  const { meta, corte } = useApp();
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
          <span>Equipo clínico</span>
          <NavLink to="/bandeja">📋 Bandeja priorizada</NavLink>
          <NavLink to="/ficha">🩺 Ficha del paciente</NavLink>
          <NavLink to="/agenda">🗓️ Agenda y box</NavLink>
        </nav>
        <nav className="nav-grupo">
          <span>Paciente (maqueta)</span>
          <NavLink to="/canal">💬 Canal del paciente</NavLink>
        </nav>
        <nav className="nav-grupo">
          <span>Gestión</span>
          <NavLink to="/kpis">📊 KPIs</NavLink>
          <NavLink to="/nocturno">🌙 Consolidación nocturna</NavLink>
        </nav>
        <div className="principio">
          La herramienta <b>propone y explica</b>; el equipo clínico <b>decide</b>.
          <br />
          La posición en la lista no equivale a una fecha garantizada de atención.
          {meta && <><br /><br />Reglas <b>{meta.version_reglas}</b></>}
        </div>
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
              <Route path="/canal" element={<Canal />} />
              <Route path="/kpis" element={<Kpis />} />
              <Route path="/nocturno" element={<Nocturno />} />
              <Route path="*" element={<Navigate to="/bandeja" replace />} />
            </Routes>
          )}
        </div>
      </main>
    </div>
  );
}
