import { useState } from "react";
import { postJSON, Registro, useApi } from "../api";
import { Aviso, Cargando, Metrica, Tabla } from "../componentes/comunes";
import { useApp } from "../contexto";

const PASOS = [
  { t: "Entrada", d: "Una exportación nueva: la sube la Administradora en Cargas o llega sola al buzón y la recoge el proceso de las 02:00.", aws: "S3 hlf/entrada/ · EventBridge Scheduler → ECS" },
  { t: "Suma a raw", d: "Se valida y se suma a lo que ya existe como una versión nueva. Nada se borra; cada cambio queda en el historial.", aws: "RDS · raw.carga_lote" },
  { t: "Simulación histórica", d: "Los pacientes con datos nuevos se recalculan desde su ingreso; los demás solo suman las noches nuevas. Cada noche usa solo lo conocido hasta esa noche.", aws: "ECS (Python) · serie nocturna" },
  { t: "Posiciones y propuestas", d: "Se recalculan las posiciones de las noches tocadas y se registran las propuestas cuando cambia el nivel o se enciende una alerta.", aws: "RDS · priorizacion" },
  { t: "Estimación de espera", d: "Rango de días según la posición vigente y las atenciones de las últimas 8 semanas. Uso interno.", aws: "RDS · estimacion_espera" },
  { t: "Bitácora y publicación", d: "La corrida queda registrada con su origen. Opcionalmente se publica en Athena para análisis.", aws: "S3 Parquet · Athena" },
];

const ORIGEN: Record<string, string> = {
  completo: "Historia completa", carga: "Carga confirmada", nocturno: "Consolidación nocturna", solicitud: "Puntual",
};

export default function Nocturno() {
  const { version, consolidacion, seguirConsolidacion } = useApp();
  const { data, error } = useApi<Registro>("/api/nocturno", version);
  const [fallo, setFallo] = useState<string | null>(null);
  const [pedido, setPedido] = useState(false);
  const enCurso = !!consolidacion?.en_curso;
  const ejecutar = async () => {
    setFallo(null);
    setPedido(true);
    try {
      await postJSON<Registro>("/api/nocturno/ejecutar");
      seguirConsolidacion();
    } catch (e) {
      setFallo((e as Error).message);
    } finally {
      setPedido(false);
    }
  };
  const ultimo = consolidacion && !consolidacion.en_curso ? consolidacion.resultado : null;
  return (
    <>
      <div className="encabezado">
        <h1>🌙 Consolidación nocturna</h1>
        <p>
          Cada vez que llegan datos nuevos (una carga confirmada o una exportación en el buzón), el mismo proceso los
          suma al histórico y deja al día la simulación noche a noche, las propuestas y la estimación de espera. Si el
          HLF puede dejar sus exportaciones en el buzón, la carga manual deja de ser necesaria.
        </p>
      </div>
      <div className="tarjeta"><div className="pasos">
        {PASOS.map((p) => <div key={p.t} className="paso"><b>{p.t}</b>{p.d}<small>AWS: {p.aws}</small></div>)}
      </div></div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!data ? <Cargando /> : (
        <>
          <div className="tarjeta pila">
            <div className="fila entre">
              <h3>Recalcular la historia completa</h3>
              <button className="boton primario" onClick={ejecutar} disabled={enCurso || pedido}>
                {enCurso ? "Recalculando…" : "▶ Recalcular desde cero"}
              </button>
            </div>
            <small>
              Rehace todas las noches con las reglas <code>{data.version_reglas}</code>, las decisiones clínicas y la
              evidencia validada, hasta los datos al <b>{data.fecha_corte}</b>. Solo hace falta tras cambiar las reglas: las
              cargas nuevas se consolidan solas. Corre en segundo plano.
            </small>
            {ultimo && <Aviso tipo="exito">Último recálculo ({ORIGEN[consolidacion!.origen ?? ""] ?? consolidacion!.origen}): {Number(ultimo.evaluaciones).toLocaleString("es-CL")} evaluaciones, {String(ultimo.propuestas)} propuestas y {String(ultimo.estimaciones)} estimaciones en {String(ultimo.segundos)} s.</Aviso>}
            {fallo && <Aviso tipo="error">{fallo}</Aviso>}
          </div>
          <div className="metricas">
            {(data.fuentes as Registro[]).map((f) => <Metrica key={f.tabla} etiqueta={`Fuente · ${f.tabla}`} valor={f.filas.toLocaleString("es-CL")} />)}
          </div>
          <div className="metricas">
            {Object.entries(data.registro as Record<string, number>).map(([k, v]) => (
              <Metrica key={k} etiqueta={`Registro · ${k.replace("_", " ")}`} valor={v.toLocaleString("es-CL")} />
            ))}
          </div>
          <div className="tarjeta pila">
            <h3>Bitácora de corridas</h3>
            <Tabla filas={(data.corridas as Registro[]).map((c) => ({ ...c, origen: ORIGEN[c.origen] ?? c.origen }))} columnas={[
              { clave: "id_corrida", titulo: "#", num: true }, { clave: "inicio", titulo: "Inicio" }, { clave: "origen", titulo: "Origen" },
              { clave: "estado", titulo: "Estado" }, { clave: "alcance", titulo: "Alcance" }, { clave: "hasta", titulo: "Datos al" },
              { clave: "version_reglas", titulo: "Reglas" }, { clave: "n_evaluaciones", titulo: "Evaluaciones", num: true },
              { clave: "n_propuestas", titulo: "Propuestas", num: true }, { clave: "segundos", titulo: "Segundos", num: true },
            ]} />
          </div>
          <div className="tarjeta pila">
            <h3>Reglas y pesos vigentes ({data.version_reglas})</h3>
            <p className="suave">Punto de partida para calibrar con el equipo clínico del HLF. Todo cambio crea una nueva versión de reglas y queda en la trazabilidad de cada propuesta.</p>
            <Tabla filas={data.reglas} alta columnas={[{ clave: "grupo", titulo: "Grupo" }, { clave: "regla", titulo: "Regla" }, { clave: "valor", titulo: "Valor" }]} />
          </div>
        </>
      )}
    </>
  );
}
