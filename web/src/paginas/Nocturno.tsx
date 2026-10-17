import { MoonStar, Play, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { postJSON, Registro, useApi } from "../api";
import { Aviso, Cargando, Encabezado, Metrica, Tabla } from "../componentes/comunes";
import { useApp } from "../contexto";

const PASOS = [
  { t: "Entrada", d: "Carga desde la vista Cargas o exportación en el buzón (02:00).", aws: "S3 · EventBridge → ECS" },
  { t: "Suma a los datos", d: "Se valida y se suma como versión nueva. Nada se borra.", aws: "RDS · raw" },
  { t: "Simulación noche a noche", d: "Cada noche usa solo lo conocido hasta esa noche.", aws: "ECS · serie nocturna" },
  { t: "Propuestas y posiciones", d: "Se registra una propuesta si cambia el nivel o hay alerta.", aws: "RDS · priorizacion" },
  { t: "Estimación de espera", d: "Rango de días según la posición. Uso interno.", aws: "RDS · estimacion_espera" },
  { t: "Bitácora", d: "Queda registrada con su origen; se publica en Athena.", aws: "S3 Parquet · Athena" },
];

const ORIGEN: Record<string, string> = {
  completo: "Historia completa", carga: "Carga confirmada", nocturno: "Consolidación nocturna", solicitud: "Puntual",
  reglas: "Cambio de reglas",
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
      <Encabezado icono={MoonStar} titulo="Proceso nocturno"
        descripcion="Cada noche (y al confirmar una carga) se suman los datos nuevos y se recalculan propuestas, posiciones y estimaciones." />
      <div className="flujo">
        {PASOS.map((p, i) => (
          <div key={p.t} className="flujo-paso">
            <div className="fila"><span className="pasos-numero">{i + 1}</span><b>{p.t}</b></div>
            <small>{p.d}</small>
            <small className="aws">{p.aws}</small>
          </div>
        ))}
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!data ? <Cargando /> : (
        <>
          <div className="tarjeta pila">
            <div className="fila entre">
              <h3>Recalcular la historia completa</h3>
              <button className="boton primario" onClick={ejecutar} disabled={enCurso || pedido}>
                <Play size={15} /> {enCurso ? "Recalculando…" : "Recalcular desde cero"}
              </button>
            </div>
            <small className="suave">
              Rehace todas las noches hasta el {data.fecha_corte} con las reglas <code>{data.version_reglas}</code>. Normalmente
              no hace falta: las cargas y los cambios de reglas recalculan solos.
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
          <Aviso tipo="info">
            Las reglas y pesos vigentes se ven y se editan en <Link to="/reglas"><SlidersHorizontal size={13} /> Reglas del puntaje</Link>.
          </Aviso>
        </>
      )}
    </>
  );
}
