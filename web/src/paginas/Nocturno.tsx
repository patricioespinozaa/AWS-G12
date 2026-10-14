import { useState } from "react";
import { postJSON, Registro, useApi } from "../api";
import { Aviso, Cargando, Metrica, Tabla } from "../componentes/comunes";
import { useApp } from "../contexto";

const PASOS = [
  { t: "Ingesta", d: "Lee lista de espera, eventos, mediciones, citas y agenda. No modifica las fuentes.", aws: "S3 raw · Glue / Lambda" },
  { t: "Consolidación por paciente", d: "Une todo por id_paciente y lo organiza por tipo: diagnósticos, atenciones, fármacos, exámenes.", aws: "Glue job · S3 procesado (Parquet por fecha)" },
  { t: "Corte a la noche", d: "Para cada noche usa solo datos con fecha ≤ esa noche. Excluye fallecidos y atendidos.", aws: "Partición fecha_corte=AAAA-MM-DD" },
  { t: "Motor de reglas", d: "Regla dura → puntaje de nivel → nivel → resguardo sin evidencia de mejora. Determinista y versionado.", aws: "Lambda (Python)" },
  { t: "Propuesta y explicación", d: "Si cambia el nivel o se enciende una alerta, registra la propuesta con factores, fuentes y huella.", aws: "RDS / DynamoDB · Bedrock solo para redactar" },
  { t: "Bandeja del equipo clínico", d: "A la mañana, el equipo ve los cambios de la noche y acepta, ajusta o rechaza.", aws: "API Gateway + app web" },
];

export default function Nocturno() {
  const { version, refrescar } = useApp();
  const { data, error } = useApi<Registro>("/api/nocturno", version);
  const [corriendo, setCorriendo] = useState(false);
  const [resultado, setResultado] = useState<Registro | null>(null);
  const [fallo, setFallo] = useState<string | null>(null);
  const ejecutar = async () => {
    setCorriendo(true);
    setFallo(null);
    try {
      setResultado(await postJSON<Registro>("/api/nocturno/ejecutar"));
      refrescar();
    } catch (e) {
      setFallo((e as Error).message);
    } finally {
      setCorriendo(false);
    }
  };
  return (
    <>
      <div className="encabezado">
        <h1>🌙 Consolidación nocturna</h1>
        <p>
          Las fuentes siguen guardando su información por separado. Cada noche un proceso las lee, arma la ficha
          consolidada y recalcula la prioridad de toda la lista. Para probar con el dataset se re-procesa la historia
          completa, noche a noche, como si el proceso hubiera corrido todos los días.
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
              <h3>Ejecutar ahora</h3>
              <button className="boton primario" onClick={ejecutar} disabled={corriendo}>
                {corriendo ? "Re-procesando la historia completa…" : "▶ Re-procesar la historia completa"}
              </button>
            </div>
            <small>Recalcula todas las noches con las reglas <code>{data.version_reglas}</code>, las decisiones clínicas y la evidencia validada. Toma unos segundos.</small>
            {resultado && <Aviso tipo="exito">Listo: {resultado.n_evaluaciones.toLocaleString("es-CL")} evaluaciones y {resultado.n_propuestas} propuestas en {resultado.segundos} s.</Aviso>}
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
            <Tabla filas={data.corridas} columnas={[
              { clave: "id_corrida", titulo: "#", num: true }, { clave: "inicio", titulo: "Inicio" }, { clave: "alcance", titulo: "Alcance" },
              { clave: "desde", titulo: "Desde" }, { clave: "hasta", titulo: "Hasta" }, { clave: "version_reglas", titulo: "Reglas" },
              { clave: "n_evaluaciones", titulo: "Evaluaciones", num: true }, { clave: "n_propuestas", titulo: "Propuestas", num: true },
              { clave: "segundos", titulo: "Segundos", num: true },
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
