import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { EstadoConsolidacion, getJSON, Meta } from "./api";

interface Estado {
  meta: Meta | null;
  corte: string;
  setCorte: (f: string) => void;
  /** Aumenta cada vez que se guarda algo, para que las vistas vuelvan a pedir sus datos. */
  version: number;
  refrescar: () => void;
  /** Vuelve a pedir /api/meta (tras una carga cambia la fecha de referencia). */
  recargarMeta: () => void;
  /** Recálculo en segundo plano (F0006). Mientras corre se consulta cada 3 s; al terminar se refresca todo. */
  consolidacion: EstadoConsolidacion | null;
  seguirConsolidacion: () => void;
}

const Contexto = createContext<Estado | null>(null);

export function ProveedorApp({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [corte, setCorteEstado] = useState<string>("");
  const [version, setVersion] = useState(0);

  const recargarMeta = useCallback(() => {
    getJSON<Meta>("/api/meta").then((m) => {
      setMeta(m);
      let guardado: string | null = null;
      try {
        guardado = localStorage.getItem("corte");
      } catch {
        /* almacenamiento no disponible */
      }
      const valido = guardado && guardado >= m.fecha_min && guardado <= m.fecha_referencia;
      setCorteEstado(valido ? guardado! : m.fecha_referencia);
    });
  }, []);

  useEffect(recargarMeta, [recargarMeta]);

  const setCorte = useCallback(
    (f: string) => {
      if (!meta || !f) return;
      const acotada = f < meta.fecha_min ? meta.fecha_min : f > meta.fecha_referencia ? meta.fecha_referencia : f;
      setCorteEstado(acotada);
      try {
        localStorage.setItem("corte", acotada);
      } catch {
        /* almacenamiento no disponible */
      }
    },
    [meta],
  );

  const refrescar = useCallback(() => setVersion((v) => v + 1), []);

  const [consolidacion, setConsolidacion] = useState<EstadoConsolidacion | null>(null);
  const [seguimiento, setSeguimiento] = useState(0);
  useEffect(() => {
    let vigente = true;
    let espera: number | undefined;
    let enCurso = seguimiento > 0; // si se pidió seguir, al terminar se refresca aunque haya sido rápido
    const consultar = () =>
      getJSON<EstadoConsolidacion>("/api/nocturno/estado")
        .then((e) => {
          if (!vigente) return;
          setConsolidacion(e);
          if (e.en_curso) {
            enCurso = true;
            espera = window.setTimeout(consultar, 3000);
          } else if (enCurso) {
            enCurso = false;
            recargarMeta();
            refrescar();
          }
        })
        .catch(() => {
          if (vigente && enCurso) espera = window.setTimeout(consultar, 10000);
        });
    consultar();
    return () => {
      vigente = false;
      window.clearTimeout(espera);
    };
  }, [seguimiento, recargarMeta, refrescar]);
  const seguirConsolidacion = useCallback(() => setSeguimiento((s) => s + 1), []);

  return (
    <Contexto.Provider value={{ meta, corte, setCorte, version, refrescar, recargarMeta, consolidacion, seguirConsolidacion }}>
      {children}
    </Contexto.Provider>
  );
}

export function useApp(): Estado {
  const c = useContext(Contexto);
  if (!c) throw new Error("useApp fuera de ProveedorApp");
  return c;
}
