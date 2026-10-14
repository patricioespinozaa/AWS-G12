import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { getJSON, Meta } from "./api";

interface Estado {
  meta: Meta | null;
  corte: string;
  setCorte: (f: string) => void;
  /** Aumenta cada vez que se guarda algo, para que las vistas vuelvan a pedir sus datos. */
  version: number;
  refrescar: () => void;
}

const Contexto = createContext<Estado | null>(null);

export function ProveedorApp({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [corte, setCorteEstado] = useState<string>("");
  const [version, setVersion] = useState(0);

  useEffect(() => {
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

  return (
    <Contexto.Provider value={{ meta, corte, setCorte, version, refrescar }}>{children}</Contexto.Provider>
  );
}

export function useApp(): Estado {
  const c = useContext(Contexto);
  if (!c) throw new Error("useApp fuera de ProveedorApp");
  return c;
}
