import { AlertTriangle, CheckCircle2, FlaskConical, Info, Loader2, LucideIcon, PhoneOff, UserCheck, UserX, XCircle } from "lucide-react";
import { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Registro } from "../api";
import { ETIQUETA_DISP } from "../utils";

export function NivelBadge({ nivel }: { nivel: string | null | undefined }) {
  if (!nivel) return <span className="suave">—</span>;
  return <span className={`nivel ${nivel}`}>{nivel}</span>;
}

/** Encabezado de cada vista: qué es, en una línea, y sus acciones. */
export function Encabezado(props: { icono: LucideIcon; titulo: string; descripcion?: ReactNode; children?: ReactNode }) {
  const Icono = props.icono;
  return (
    <header className="encabezado">
      <div className="encabezado-icono"><Icono size={20} strokeWidth={2} /></div>
      <div className="encabezado-texto">
        <h1>{props.titulo}</h1>
        {props.descripcion && <p>{props.descripcion}</p>}
      </div>
      {props.children && <div className="encabezado-acciones">{props.children}</div>}
    </header>
  );
}

/** Paso a paso de un flujo. `actual` es el índice del paso en curso (los anteriores quedan hechos). */
export function Pasos({ pasos, actual }: { pasos: { titulo: string; detalle?: string }[]; actual: number }) {
  return (
    <ol className="pasos">
      {pasos.map((p, i) => (
        <li key={p.titulo} className={i < actual ? "hecho" : i === actual ? "actual" : ""}>
          <span className="pasos-numero">{i < actual ? <CheckCircle2 size={16} /> : i + 1}</span>
          <span className="pasos-texto"><b>{p.titulo}</b>{p.detalle && <small>{p.detalle}</small>}</span>
        </li>
      ))}
    </ol>
  );
}

export function Metrica(props: {
  etiqueta: string; valor: ReactNode; detalle?: ReactNode; destacada?: boolean; titulo?: string; icono?: LucideIcon;
  tono?: "alta" | "media" | "baja" | "exito";
}) {
  const Icono = props.icono;
  return (
    <div className={`metrica${props.destacada ? " destacada" : ""}${props.tono ? ` tono-${props.tono}` : ""}`} title={props.titulo}>
      <div className="etiqueta">{Icono && <Icono size={14} />}{props.etiqueta}</div>
      <div className="valor">{props.valor}</div>
      {props.detalle && <div className="detalle">{props.detalle}</div>}
    </div>
  );
}

export function Cargando({ texto = "Cargando…" }: { texto?: string }) {
  return <div className="cargando"><Loader2 size={18} className="girando" /> {texto}</div>;
}

const ICONO_AVISO = { error: XCircle, atencion: AlertTriangle, info: Info, exito: CheckCircle2 };

export function Aviso({ tipo, children }: { tipo: "error" | "atencion" | "info" | "exito"; children: ReactNode }) {
  const Icono = ICONO_AVISO[tipo];
  return (
    <div className={`aviso ${tipo}`} role={tipo === "error" ? "alert" : undefined}>
      <Icono size={18} className="aviso-icono" />
      <div>{children}</div>
    </div>
  );
}

export function Pestanas<T extends string>(props: {
  opciones: { id: T; etiqueta: string; icono?: LucideIcon; contador?: number }[]; activa: T; onCambio: (id: T) => void;
}) {
  return (
    <div className="pestanas" role="tablist">
      {props.opciones.map((o) => {
        const Icono = o.icono;
        return (
          <button key={o.id} role="tab" aria-selected={o.id === props.activa} className={o.id === props.activa ? "activa" : ""}
            onClick={() => props.onCambio(o.id)}>
            {Icono && <Icono size={15} />}
            {o.etiqueta}
            {o.contador ? <span className="contador">{o.contador}</span> : null}
          </button>
        );
      })}
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
  if (!filas || filas.length === 0) return <p className="vacio">{props.vacia ?? "Sin registros."}</p>;
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
    <Link to={`/ficha/${id}`} onClick={(e) => e.stopPropagation()} className="enlace-paciente">
      <b>{nombre}</b> <small>{idPaciente}</small>
    </Link>
  );
}

/** Indicador de alerta clínica (en tablas). */
export function IconoAlerta({ activa, titulo = "Alerta para revisión clínica prioritaria" }: { activa: boolean | number; titulo?: string }) {
  if (!activa) return null;
  return <span className="icono-alerta" title={titulo}><AlertTriangle size={15} /></span>;
}

const ICONO_DISP: Record<string, LucideIcon> = { lista: UserCheck, faltan_examenes: FlaskConical, no_confirma: UserX, sin_contacto: PhoneOff };

/** Disponibilidad para box: independiente de la prioridad clínica (un paciente no listo no pierde su lugar). */
export function Disponibilidad({ estado, accion }: { estado: string; accion?: string | null }) {
  const Icono = ICONO_DISP[estado] ?? Info;
  return (
    <span className={`disp disp-${estado}`} title={accion ?? ""}>
      <Icono size={14} />{ETIQUETA_DISP[estado] ?? estado}
    </span>
  );
}
