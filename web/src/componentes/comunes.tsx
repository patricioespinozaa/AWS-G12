import { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Registro } from "../api";

export function NivelBadge({ nivel }: { nivel: string | null | undefined }) {
  if (!nivel) return <span className="suave">—</span>;
  return <span className={`nivel ${nivel}`}>{nivel}</span>;
}

export function Metrica(props: { etiqueta: string; valor: ReactNode; detalle?: ReactNode; destacada?: boolean; titulo?: string }) {
  return (
    <div className={`metrica${props.destacada ? " destacada" : ""}`} title={props.titulo}>
      <div className="etiqueta">{props.etiqueta}</div>
      <div className="valor">{props.valor}</div>
      {props.detalle && <div className="detalle">{props.detalle}</div>}
    </div>
  );
}

export function Cargando({ texto = "Cargando…" }: { texto?: string }) {
  return <div className="cargando">⏳ {texto}</div>;
}

export function Aviso({ tipo, children }: { tipo: "error" | "atencion" | "info" | "exito"; children: ReactNode }) {
  return <div className={`aviso ${tipo}`}>{children}</div>;
}

export function Pestanas<T extends string>(props: { opciones: { id: T; etiqueta: string }[]; activa: T; onCambio: (id: T) => void }) {
  return (
    <div className="pestanas" role="tablist">
      {props.opciones.map((o) => (
        <button key={o.id} role="tab" className={o.id === props.activa ? "activa" : ""} onClick={() => props.onCambio(o.id)}>
          {o.etiqueta}
        </button>
      ))}
    </div>
  );
}

export interface Columna {
  clave: string;
  titulo: string;
  num?: boolean;
  render?: (fila: Registro) => ReactNode;
}

/** Tabla simple a partir de registros JSON. */
export function Tabla(props: { filas: Registro[]; columnas?: Columna[]; vacia?: string; alta?: boolean; onFila?: (f: Registro) => void }) {
  const { filas } = props;
  if (!filas || filas.length === 0) return <p className="suave">{props.vacia ?? "Sin registros."}</p>;
  const columnas: Columna[] = props.columnas ?? Object.keys(filas[0]).map((k) => ({ clave: k, titulo: k }));
  return (
    <div className={`tabla-envoltura${props.alta ? " alta" : ""}`}>
      <table>
        <thead>
          <tr>
            {columnas.map((c) => (
              <th key={c.clave} className={c.num ? "num" : ""}>{c.titulo}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.map((f, i) => (
            <tr key={i} className={props.onFila ? "clic" : ""} onClick={() => props.onFila?.(f)}>
              {columnas.map((c) => (
                <td key={c.clave} className={c.num ? "num" : ""}>
                  {c.render ? c.render(f) : formatear(f[c.clave])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatear(v: unknown): ReactNode {
  if (v === null || v === undefined || v === "") return <span className="suave">—</span>;
  if (typeof v === "number") return Number.isInteger(v) ? v : v.toLocaleString("es-CL", { maximumFractionDigits: 2 });
  if (typeof v === "boolean") return v ? "sí" : "no";
  return String(v);
}

export function EnlacePaciente({ id, nombre, idPaciente }: { id: string; nombre: string; idPaciente: string }) {
  return (
    <Link to={`/ficha/${id}`} onClick={(e) => e.stopPropagation()}>
      <b>{nombre}</b> <small>{idPaciente}</small>
    </Link>
  );
}
