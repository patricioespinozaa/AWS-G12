// Rutas por hash: #/lista?corte=AAAA-MM-DD, #/avisos, #/calidad, #/paciente/{pid}
import { useEffect, useState } from "react";

export type Vista = "lista" | "avisos" | "calidad" | "paciente";

export interface Ruta {
  vista: Vista;
  pid: string | null;
  corte: string | null;
}

const PATRON_FECHA = /^\d{4}-\d{2}-\d{2}$/;
const PATRON_PID = /^PAC-[A-Z]+-\d{5}$/;

export function leerRuta(hash: string = window.location.hash): Ruta {
  const [camino, consulta = ""] = hash.replace(/^#/, "").split("?");
  const partes = camino.split("/").filter(Boolean);
  const corte = new URLSearchParams(consulta).get("corte");
  const corteValido = corte && PATRON_FECHA.test(corte) ? corte : null;
  if (partes[0] === "paciente" && partes[1] && PATRON_PID.test(partes[1])) {
    return { vista: "paciente", pid: partes[1], corte: corteValido };
  }
  const vista: Vista = partes[0] === "avisos" || partes[0] === "calidad" ? partes[0] : "lista";
  return { vista, pid: null, corte: corteValido };
}

export function hrefRuta(vista: Vista, corte: string | null, pid?: string): string {
  const camino = vista === "paciente" && pid ? `#/paciente/${pid}` : `#/${vista}`;
  return corte ? `${camino}?corte=${corte}` : camino;
}

export function useRuta(): Ruta {
  const [ruta, setRuta] = useState<Ruta>(() => leerRuta());
  useEffect(() => {
    const alCambiar = () => setRuta(leerRuta());
    window.addEventListener("hashchange", alCambiar);
    return () => window.removeEventListener("hashchange", alCambiar);
  }, []);
  return ruta;
}
