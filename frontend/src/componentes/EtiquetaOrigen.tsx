import type { OrigenInferencia } from "../tipos";

export default function EtiquetaOrigen({ origen, modelo }: { origen: OrigenInferencia; modelo?: string | null }) {
  return origen === "simulada" ? (
    <p className="origen origen-simulada">Inferencia SIMULADA, no es análisis de IA</p>
  ) : (
    <p className="origen origen-real">Inferencia real (modelo {modelo ?? "desconocido"})</p>
  );
}
