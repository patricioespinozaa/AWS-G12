import { useDatos } from "./api";
import BannerLocal from "./componentes/BannerLocal";
import EstadoCarga, { SinCorte } from "./componentes/EstadoCarga";
import SelectorCorte from "./componentes/SelectorCorte";
import { hrefRuta, useRuta, type Vista } from "./rutas";
import type { EstadoServidor } from "./tipos";
import VistaAvisos from "./vistas/VistaAvisos";
import VistaCalidad from "./vistas/VistaCalidad";
import VistaLista from "./vistas/VistaLista";
import VistaPaciente from "./vistas/VistaPaciente";

const SECCIONES: { vista: Vista; texto: string }[] = [
  { vista: "lista", texto: "Lista de espera" },
  { vista: "avisos", texto: "Avisos" },
  { vista: "calidad", texto: "Calidad de datos" },
];

export default function App() {
  const ruta = useRuta();
  const servidor = useDatos<EstadoServidor>("/api/estado");
  const estado = servidor.datos;
  const corte =
    ruta.corte && estado && ruta.corte >= estado.fecha_corte_min && ruta.corte <= estado.fecha_corte_max
      ? ruta.corte
      : null;

  function cambiarCorte(nuevo: string | null) {
    window.location.hash = hrefRuta(ruta.vista, nuevo, ruta.pid ?? undefined);
  }

  let contenido = null;
  if (estado && !corte) contenido = <SinCorte />;
  else if (estado && corte) {
    if (ruta.vista === "paciente" && ruta.pid)
      contenido = <VistaPaciente key={`${ruta.pid}-${corte}`} pid={ruta.pid} corte={corte} estado={estado} />;
    else if (ruta.vista === "avisos") contenido = <VistaAvisos corte={corte} />;
    else if (ruta.vista === "calidad") contenido = <VistaCalidad corte={corte} />;
    else contenido = <VistaLista corte={corte} fechaReferencia={estado.fecha_referencia} />;
  }

  return (
    <>
      <a className="saltar" href="#contenido" onClick={(e) => {
        e.preventDefault();
        document.getElementById("contenido")?.focus();
      }}>
        Saltar al contenido
      </a>
      <header className="encabezado">
        <div className="titulo">
          <p className="producto">Copiloto de revisión · Lista de espera de primera consulta</p>
          <BannerLocal />
          {estado && (
            <p className={`modo modo-${estado.modo_inferencia}`}>
              Inferencia: {estado.modo_inferencia === "simulada" ? "SIMULADA (sin IA ni envío de datos)" : "REAL (requiere confirmación en cada envío)"} ·
              Datos: {estado.fuente_datos}
            </p>
          )}
        </div>
        <SelectorCorte
          valor={corte}
          min={estado?.fecha_corte_min}
          max={estado?.fecha_corte_max}
          onCambio={cambiarCorte}
        />
        <nav aria-label="Secciones">
          <ul>
            {SECCIONES.map((s) => (
              <li key={s.vista}>
                <a href={hrefRuta(s.vista, corte)} aria-current={ruta.vista === s.vista ? "page" : undefined}>
                  {s.texto}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main id="contenido" tabIndex={-1}>
        <EstadoCarga
          cargando={servidor.cargando}
          error={servidor.error}
          onReintentar={servidor.recargar}
          textoCarga="Conectando con el servidor local…"
        >
          {contenido}
        </EstadoCarga>
      </main>
    </>
  );
}
