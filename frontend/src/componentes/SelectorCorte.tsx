import { useEffect, useState } from "react";

interface Props {
  valor: string | null;
  min?: string;
  max?: string;
  onCambio: (corte: string | null) => void;
}

/** Fecha de corte obligatoria: sin ella ninguna vista consulta datos. */
export default function SelectorCorte({ valor, min, max, onCambio }: Props) {
  const [texto, setTexto] = useState(valor ?? "");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setTexto(valor ?? ""), [valor]);

  function aplicar(nuevo: string) {
    setTexto(nuevo);
    if (!nuevo) {
      setError("La fecha de corte es obligatoria.");
      onCambio(null);
      return;
    }
    if ((min && nuevo < min) || (max && nuevo > max)) {
      setError(`Debe estar entre ${min} y ${max}.`);
      return;
    }
    setError(null);
    onCambio(nuevo);
  }

  return (
    <div className="selector-corte">
      <label htmlFor="fecha-corte">Fecha de corte (obligatoria)</label>
      <input
        id="fecha-corte"
        type="date"
        required
        aria-required="true"
        min={min}
        max={max}
        value={texto}
        aria-invalid={error ? "true" : "false"}
        aria-describedby="fecha-corte-ayuda fecha-corte-error"
        onChange={(e) => aplicar(e.target.value)}
      />
      <span id="fecha-corte-ayuda" className="ayuda">
        Solo se usa información registrada hasta esta fecha{min && max ? ` (rango ${min} a ${max})` : ""}.
      </span>
      <span id="fecha-corte-error" className="error-campo" role={error ? "alert" : undefined}>
        {error}
      </span>
    </div>
  );
}
