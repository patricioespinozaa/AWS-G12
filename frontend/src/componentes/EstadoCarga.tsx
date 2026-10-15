import type { ReactNode } from "react";
import type { ErrorApi } from "../api";

interface Props {
  cargando: boolean;
  error: ErrorApi | null;
  onReintentar?: () => void;
  textoCarga?: string;
  children?: ReactNode;
}

export default function EstadoCarga({ cargando, error, onReintentar, textoCarga, children }: Props) {
  return (
    <div aria-busy={cargando}>
      <div aria-live="polite" className="estado-vivo">
        {cargando && <p className="cargando">{textoCarga ?? "Cargando…"}</p>}
      </div>
      {error && (
        <div role="alert" className="error">
          <p>{error.message}</p>
          {onReintentar && (
            <button type="button" onClick={onReintentar}>
              Reintentar
            </button>
          )}
        </div>
      )}
      {/* Las vistas solo renderizan contenido si hay datos de la ruta vigente. */}
      {!error && children}
    </div>
  );
}

export function SinCorte() {
  return <p className="aviso-corte">Seleccione una fecha de corte para evaluar.</p>;
}
