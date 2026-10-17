import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import {
  cargarConfig, cerrarSesion, completarLogin, ConfigAuth, expiraEn, iniciarLogin, registrarAlVencer, renovar,
} from "./sesion";

interface Sesion {
  modo: ConfigAuth["modo"];
  salir: () => void;
}

const Contexto = createContext<Sesion | null>(null);
const RENOVAR_ANTES_MS = 5 * 60 * 1000;

/** Una sola vez por carga de página (StrictMode monta dos veces; el código de Cognito se canjea una sola vez). */
let arranque: Promise<{ cfg: ConfigAuth; conSesion: boolean }> | null = null;
function arrancar() {
  arranque ??= (async () => {
    const cfg = await cargarConfig();
    if (cfg.modo === "desactivada") return { cfg, conSesion: true };
    registrarAlVencer(() => iniciarLogin(cfg));
    return { cfg, conSesion: await completarLogin(cfg) };
  })();
  return arranque;
}

/** La app solo se muestra con sesión (o en modo local sin autenticación). Sin sesión, lleva al login de Cognito. */
export function ProveedorSesion({ children }: { children: ReactNode }) {
  const [cfg, setCfg] = useState<ConfigAuth | null>(null);
  const [lista, setLista] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const espera = useRef<number | undefined>(undefined);

  const programarRenovacion = useCallback((c: ConfigAuth) => {
    window.clearTimeout(espera.current);
    espera.current = window.setTimeout(async () => {
      if (await renovar(c)) programarRenovacion(c);
      else iniciarLogin(c);
    }, Math.max(expiraEn() - RENOVAR_ANTES_MS, 10_000));
  }, []);

  useEffect(() => {
    let vigente = true;
    (async () => {
      try {
        const { cfg: c, conSesion } = await arrancar();
        if (!vigente) return;
        setCfg(c);
        if (!conSesion) {
          await iniciarLogin(c);
          return;
        }
        if (c.modo === "cognito") programarRenovacion(c);
        setLista(true);
      } catch (e) {
        if (vigente) setError((e as Error).message);
      }
    })();
    return () => {
      vigente = false;
      window.clearTimeout(espera.current);
    };
  }, [programarRenovacion]);

  if (error)
    return (
      <div className="pantalla-sesion">
        <div className="tarjeta pila">
          <h2>No se pudo iniciar sesión</h2>
          <p>{error}</p>
          <button className="boton primario" onClick={() => window.location.assign("/")}>Intentar de nuevo</button>
        </div>
      </div>
    );
  if (!lista || !cfg) return <div className="pantalla-sesion"><p className="suave">Verificando la sesión…</p></div>;
  return (
    <Contexto.Provider value={{ modo: cfg.modo, salir: () => (cfg.modo === "cognito" ? cerrarSesion(cfg) : undefined) }}>
      {children}
    </Contexto.Provider>
  );
}

export function useSesion(): Sesion {
  const s = useContext(Contexto);
  if (!s) throw new Error("useSesion fuera de ProveedorSesion");
  return s;
}
