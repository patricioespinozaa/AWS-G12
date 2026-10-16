# U1 — Entidades de dominio

Fuente: sección 4 de `docs/contexto-tecnico.md`, ajustada a la estructura real de `perfiles.json`. Todas las entidades son inmutables (Pydantic `frozen=True`). Las fechas son `date` ISO; los valores numéricos, `Decimal`.

## Entrada (contrato `contrato-v1.0.0`)

| Entidad | Campos | Notas |
|---|---|---|
| `PerfilCrudo` | `id_paciente`, `paciente`, `lista_espera`, `eventos_clinicos[]`, `mediciones[]`, `citaciones[]` | `lista_espera` llega como **objeto**; se acepta también una lista. Se normaliza a lista |
| `Paciente` | `edad`, `sexo`, `comuna`, `prevision`, `nivel_socioeconomico`, `fallecido`, `fecha_defuncion` | `nombre_fantasia` se descarta al validar |
| `Solicitud` | `id_solicitud`, `especialidad`, `sub_especialidad`, `diagnostico_cie10`, `diagnostico_texto`, `prioridad_inicial`, `fecha_ingreso_lista`, `origen_derivacion`, `estado` | CIE-10 normalizado a mayúsculas |
| `Evento` | `id_evento`, `fecha_evento`, `tipo_evento`, `subtipo`, `severidad`, `detalle`, `especialidad_evento` | `especialidad_evento` se extrae del paréntesis de `detalle` (`"<subtipo> (<especialidad>)"`); si no se puede, se asume la de la solicitud y se emite un hallazgo `info` |
| `Medicion` | `id_medicion`, `fecha_medicion`, `tipo_medicion`, `valor`, `unidad`, `fuera_de_rango_origen` | `id_medicion` = `MED-` + 16 hex de SHA-256 de `id_paciente|fecha|tipo|valor normalizado` |
| `Cita` | `id_cita`, `id_box`, `fecha_cita`, `especialidad`, `estado_cita`, `minutos_atencion_real` | |

Enumerados cerrados (fuera de ellos → cuarentena): `prioridad_inicial` {alta, media, baja}; `estado` {en_espera, atendido, fallecido, citado, egresado}; `tipo_evento` y combinaciones `tipo/subtipo/severidad` de la tabla de `docs/datos.md`; `tipo_medicion` y su `unidad`; `estado_cita` {asistio, no_asistio, reprogramo, cancelo}.

## Intermedias

| Entidad | Contenido | Quién la produce |
|---|---|---|
| `ResultadoValidacion` | `ok: bool`, `perfil: PerfilValido | None`, `motivos: list[str]`, `version_contrato` | `contrato` |
| `ContextoPaciente` | `id_solicitud`, `fecha_corte`, `fecha_extraccion`, `edad`, `sexo`, `solicitud` (con `estado_a_la_fecha`), `fallecido_a_la_fecha`, `fecha_egreso_inferida`, `eventos[]`, `mediciones[]`, `citas[]`, `otras_solicitudes[]`, `huella` | `repositorio` |
| `HallazgoDQ` | `codigo`, `nivel` {descartar, verificar, info}, `ids_registro[]`, `detalle` | `calidad` |
| `ResultadoCohorte` | `clave`, `nivel_relajacion` (0–2), `n`, `k`, `p`, `ic95_inf`, `ic95_sup`, `advertencia_muestra_pequena`, `advertencia_sesgo_acceso` | `repositorio` |

`ContextoPaciente` **no tiene** los campos `comuna`, `prevision`, `nivel_socioeconomico` ni `nombre_fantasia`. Es la garantía estructural de la regla de equidad.

`estado_a_la_fecha`: igual a `estado` si `fecha_corte = fecha_extraccion`; si no, `desconocido_a_la_fecha`.

## Salida

| Entidad | Campos | Notas |
|---|---|---|
| `Factor` | `factor` {base, evento, medicion_zona, medicion_brusco, medicion_tendencia, aceleracion, espera}, `detalle`, `aporte` (2 decimales), `ids_registro[]` | Todo factor tiene al menos un ID |
| `Bandera` | `codigo`, `ids_registro[]` | |
| `Piso` | `codigo`, `ids_registro[]` | |
| `Contradiccion` | `id_evento`, `ids_medicion[]`, `pregunta_clinica` | |
| `AlertaGestion` | `codigo`, `ids_registro[]`, `accion_sugerida` | |
| `Evaluacion` | Formato de la sección 6.8 del contexto técnico: `id_solicitud`, `fecha_corte`, `version_reglas`, `huella_contexto`, `prioridad_inicial`, `puntaje`, `nivel_calculado`, `nivel_propuesto`, `tipo_resultado`, `banderas[]`, `pisos[]`, `contradicciones[]`, `factores[]`, `alertas_gestion[]`, `confianza`, `motivo_confianza[]`, `marcas_inferido[]`, `estado_revision` | `estado_revision` siempre `pendiente_revision_medica` al crearse |
| `ParametrosReglas` | Contenido de `reglas-v0.1.0.yaml` | Se carga una vez y se pasa a `evaluar()` |

## Relaciones

```
PerfilCrudo 1 ── 1 Paciente
PerfilCrudo 1 ── 1..N Solicitud        (hoy 1)
PerfilCrudo 1 ── 0..N Evento / Medicion / Cita
Solicitud   1 ── 1 ContextoPaciente     (por fecha de corte)
ContextoPaciente 1 ── 0..N HallazgoDQ
ContextoPaciente + HallazgoDQ[] + ParametrosReglas ──► 1 Evaluacion
Evaluacion  1 ── 1..N Factor, 0..N Bandera/Piso/Contradiccion/AlertaGestion
```
