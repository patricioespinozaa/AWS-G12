import { useEffect, useRef } from "react";

interface Props {
  abierto: boolean;
  onConfirmar: () => void;
  onCancelar: () => void;
}

/** Confirmación explícita antes de enviar datos a la API externa (modo real). */
export default function DialogoConfirmacion({ abierto, onConfirmar, onCancelar }: Props) {
  const dialogo = useRef<HTMLDialogElement>(null);
  const cancelar = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const d = dialogo.current;
    if (!d) return;
    if (abierto && !d.open) {
      d.showModal();
      cancelar.current?.focus();
    } else if (!abierto && d.open) {
      d.close();
    }
  }, [abierto]);

  return (
    <dialog
      ref={dialogo}
      className="dialogo"
      aria-labelledby="dialogo-titulo"
      aria-describedby="dialogo-texto"
      onCancel={(e) => {
        e.preventDefault(); // Escape
        onCancelar();
      }}
    >
      <h2 id="dialogo-titulo">Confirmar envío a la API real</h2>
      <p id="dialogo-texto">
        Se enviarán datos sintéticos seudonimizados de este paciente a la API externa de
        Anthropic. ¿Confirmar envío?
      </p>
      <div className="acciones">
        <button ref={cancelar} type="button" onClick={onCancelar}>
          Cancelar
        </button>
        <button type="button" className="primario" onClick={onConfirmar}>
          Confirmar envío
        </button>
      </div>
    </dialog>
  );
}
