import { FileText } from "lucide-react";
import { useEffect, useState } from "react";
import { getJSON, postJSON, Registro } from "../api";
import { useApp } from "../contexto";
import { Aviso } from "./comunes";

interface CampoPropuesto { valor: string | null; cita: string | null; confianza: number | null; nota: string | null }
interface Lectura {
  escaneo_malware: string;
  estado_lectura: string;
  propuesta: Record<string, CampoPropuesto>;
  documento_url: string | null;
}

const ESTADO_LECTURA: Record<string, string> = {
  esperando_escaneo: "esperando el escaneo de malware", leyendo: "leyendo el documento…", leida: "lectura propuesta",
  fallida: "no se pudo leer: completa los datos a mano", bloqueada: "bloqueado: el escaneo encontró una amenaza",
  no_aplica: "",
};
const NOMBRE_CAMPO: Record<string, string> = {
  tipo_medicion: "Tipo", valor: "Valor", unidad: "Unidad", fecha_examen: "Fecha", lugar: "Lugar",
};

/** Un examen pendiente: propuesta de la IA con su cita, y los valores que confirma la persona (F0012). */
export function ValidacionExamen({ e, ocupado, onRevisar }: {
  e: Registro;
  ocupado: boolean;
  onRevisar: (estado: "validada" | "rechazada", valores: Registro) => void;
}) {
  const { meta } = useApp();
  const conArchivo = typeof e.archivo === "string" && e.archivo.startsWith("s3://");
  const [lectura, setLectura] = useState<Lectura | null>(null);
  const [tipo, setTipo] = useState<string>(e.tipo_medicion ?? "");
  const [valor, setValor] = useState<string>(e.valor != null ? String(e.valor) : "");
  const [fecha, setFecha] = useState<string>(e.fecha_examen ?? "");
  const [lugar, setLugar] = useState<string>(e.lugar ?? "");

  useEffect(() => {
    if (!conArchivo) return;
    let vigente = true;
    let espera: number | undefined;
    const pedir = () => getJSON<Lectura>(`/api/canal/evidencias/${e.id_evidencia}/lectura`).then((l) => {
      if (!vigente) return;
      setLectura(l);
      const p = l.propuesta;
      if (p.tipo_medicion?.valor) setTipo((t) => t || p.tipo_medicion.valor!);
      if (p.valor?.valor) setValor((v) => v || p.valor.valor!);
      if (p.fecha_examen?.valor) setFecha((f) => f || p.fecha_examen.valor!);
      if (p.lugar?.valor) setLugar((x) => x || p.lugar.valor!);
      if (["esperando_escaneo", "leyendo"].includes(l.estado_lectura)) espera = window.setTimeout(pedir, 4000);
    }).catch(() => undefined);
    pedir();
    return () => {
      vigente = false;
      window.clearTimeout(espera);
    };
  }, [conArchivo, e.id_evidencia]);

  const bloqueada = lectura?.estado_lectura === "bloqueada";
  const completo = tipo && valor !== "" && !Number.isNaN(Number(valor)) && fecha;
  const unidad = meta?.tipos_medicion.find((t) => t.tipo === tipo)?.unidad ?? "";
  return (
    <div className="tarjeta compacta pila">
      <div className="fila entre">
        <b className="transicion"><FileText size={16} /> Examen · {e.nombre}</b>
        <small>recibido {e.fecha_recepcion}{lectura ? ` · ${ESTADO_LECTURA[lectura.estado_lectura] ?? lectura.estado_lectura}` : ""}</small>
      </div>
      {bloqueada && <Aviso tipo="error">El escaneo de malware encontró una amenaza: el archivo no se lee ni se muestra. Recházalo.</Aviso>}
      {lectura && lectura.estado_lectura === "leida" && (
        <div className="pila-compacta">
          <small className="suave">Propuesta de la IA (Textract + Claude). Cada valor trae la cita del documento; lo que no se pudo leer queda vacío. Confirma o corrige antes de validar.</small>
          <table className="propuesta">
            <tbody>
              {Object.entries(NOMBRE_CAMPO).map(([campo, nombre]) => {
                const c = lectura.propuesta[campo];
                return (
                  <tr key={campo}>
                    <th>{nombre}</th>
                    <td>{c?.valor ?? <span className="suave">—</span>}</td>
                    <td>{c?.cita ? <q>{c.cita}</q> : <small className="suave">{c?.nota ?? ""}</small>}
                      {c?.valor && c?.nota ? <div><small className="suave">{c.nota}</small></div> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {lectura?.documento_url && <a href={lectura.documento_url} target="_blank" rel="noreferrer">Ver el documento (enlace de 5 minutos)</a>}
      {!bloqueada && (
        <div className="fila">
          <select value={tipo} onChange={(ev) => setTipo(ev.target.value)}>
            <option value="">Tipo de examen…</option>
            {meta?.tipos_medicion.map((t) => <option key={t.tipo} value={t.tipo}>{t.nombre}</option>)}
          </select>
          <input type="number" step="any" placeholder={`Valor ${unidad}`} value={valor} onChange={(ev) => setValor(ev.target.value)} style={{ width: 110 }} />
          <input type="date" value={fecha} onChange={(ev) => setFecha(ev.target.value)} />
          <input value={lugar} placeholder="Lugar" onChange={(ev) => setLugar(ev.target.value)} style={{ width: 160 }} />
        </div>
      )}
      <div className="fila">
        <button className="boton primario chico" disabled={ocupado || bloqueada || !completo}
          title={completo ? "" : "Confirma tipo, valor y fecha"}
          onClick={() => onRevisar("validada", { tipo_medicion: tipo, valor: Number(valor), fecha_examen: fecha, lugar })}>
          Validar
        </button>
        <button className="boton peligro chico" disabled={ocupado} onClick={() => onRevisar("rechazada", {})}>Rechazar</button>
      </div>
    </div>
  );
}

/** Subida directa a S3 con URL prefirmada (F0012): el archivo no pasa por la API. */
export async function subirExamen(idPaciente: string, archivo: File, lugar: string): Promise<string> {
  const tipo = archivo.type || (archivo.name.toLowerCase().endsWith(".pdf") ? "application/pdf" : "");
  const firmado = await postJSON<{ url: string; campos: Record<string, string>; clave: string }>(
    "/api/canal/evidencias/subida", { id_paciente: idPaciente, nombre: archivo.name, tipo_mime: tipo });
  const formulario = new FormData();
  Object.entries(firmado.campos).forEach(([k, v]) => formulario.append(k, v));
  formulario.append("file", archivo);
  const r = await fetch(firmado.url, { method: "POST", body: formulario });
  if (!r.ok) throw new Error(`S3 rechazó el archivo (${r.status}). Revisa el tipo (PDF, JPG o PNG) y el tamaño (hasta 10 MB).`);
  const listo = await postJSON<{ respuesta: string }>("/api/canal/evidencias/completar",
    { id_paciente: idPaciente, clave: firmado.clave, lugar });
  return listo.respuesta;
}
