# Arquitectura: variables, trazabilidad, flujo y vistas

Diagramas del prototipo, construidos sobre el dataset del HLF (`docs/datos.md`) y el enfoque de `docs/enfoque.md`. Están en Mermaid: se ven en GitHub y en VS Code con la extensión *Markdown Preview Mermaid Support*.

Índice:
1. [Vista general](#1-vista-general)
2. [Generación de variables (linaje)](#2-generación-de-variables-linaje)
3. [Modelo de datos y trazabilidad](#3-modelo-de-datos-y-trazabilidad)
4. [Niveles de priorización](#4-niveles-de-priorización)
5. [Flujo de la aplicación](#5-flujo-de-la-aplicación)
6. [Vistas](#6-vistas)

---

## 1. Vista general

Las seis tablas fuente se combinan por `id_paciente` a una **fecha de corte**. De ellas salen las variables. El puntaje clínico es determinista y la IA generativa solo extrae información y redacta explicaciones. Todo queda registrado.

```mermaid
flowchart LR
    subgraph F["Fuentes (dataset HLF)"]
        P[("pacientes")]
        L[("lista_espera")]
        E[("eventos_clinicos")]
        M[("mediciones")]
        C[("citaciones")]
        A[("agenda_box")]
    end

    subgraph I["1. Integración"]
        I1["Unir por id_paciente"]
        I2["Filtrar fecha ≤ corte"]
        I3["Excluir fallecidos y atendidos"]
        I1 --> I2 --> I3
    end

    subgraph V["2. Variables"]
        V1["Clínicas: eventos, mediciones"]
        V2["Contexto: edad, espera, prioridad inicial"]
        V3["Box: no-show, ocupación, presión de demanda"]
    end

    subgraph S["3. Motor de priorización"]
        S1["Reglas duras"]
        S2["Puntaje interpretable"]
        S3["Nivel propuesto: alta / media / baja"]
        S1 --> S3
        S2 --> S3
    end

    subgraph X["4. Explicación"]
        X1["Factores + aporte + fuente"]
        X2["LLM redactor (Bedrock): solo usa los factores entregados"]
        X1 --> X2
    end

    subgraph R["5. Registro"]
        R1[("propuesta_prioridad")]
        R2[("factor_propuesta")]
        R3[("decision_clinica")]
    end

    subgraph U["6. Vistas"]
        U1["Bandeja priorizada"]
        U2["Ficha del paciente"]
        U3["Validación clínica"]
        U4["Panel de box"]
        U5["KPIs"]
    end

    P & L & E & M & C & A --> I1
    I3 --> V1 & V2 & V3
    V1 & V2 --> S1 & S2
    S3 --> X1
    X2 --> R1
    X1 --> R2
    R1 --> U1 --> U2 --> U3 --> R3
    V3 --> U4
    R1 & R3 --> U5
    T["Texto libre RCE (futuro)"] -.->|"LLM extractor con cita literal"| E
```

**Separaciones importantes:**
- Las variables de box (`V3`) **no entran** al puntaje clínico: alimentan el panel de box y las acciones sobre la cita.
- El LLM nunca calcula el puntaje. Entra como **extractor** (texto → eventos con fragmento citado) y como **redactor** (factores → explicación).

---

## 2. Generación de variables (linaje)

Cada variable sabe de qué tabla y de qué filas sale. Así cada factor de una propuesta puede apuntar a su dato de origen.

```mermaid
flowchart LR
    P[("pacientes")] --> vp1["edad, grupo_edad"]
    P --> vp2["sexo, comuna, prevision, nivel_socioeconomico"]
    P --> vp3["fallecido, fecha_defuncion"]

    L[("lista_espera")] --> vl1["base_prioridad ← prioridad_inicial"]
    L --> vl2["dias_espera = corte − fecha_ingreso_lista"]
    L --> vl3["especialidad, diagnostico_cie10, origen_derivacion"]
    L --> vl4["activa ← estado = en_espera"]

    E[("eventos_clinicos")] --> ve1["aporte_eventos = Σ w(subtipo) · decaimiento"]
    E --> ve2["n_graves_30d, dias_desde_ultimo_grave"]
    E --> ve3["n_mejora_90d: buena respuesta, estabilización, reducción dosis"]

    M[("mediciones")] --> vm1["ultimo_valor por tipo"]
    M --> vm2["desviacion_rango = distancia al rango / ancho del rango"]
    M --> vm3["pendiente_empeora (≥ 3 mediciones, normalizada)"]
    M --> vm4["pct_fuera_rango_90d"]

    C[("citaciones")] --> vc1["n_citas, n_no_asistio, n_reprogramo"]
    C --> vc2["riesgo_no_show"]
    C --> vc3["proxima_cita, ultima_asistencia"]

    A[("agenda_box")] --> va1["ocupacion por especialidad y semana"]
    A --> va2["cupos_libres por especialidad"]
    A --> va3["presion_demanda = % demanda / % capacidad"]
    A --> va4["sobretiempo_medio"]

    vp3 & vl4 --> EXC{{"Exclusión"}}
    vp1 & vl1 & vl2 --> CTX{{"Contexto del puntaje"}}
    ve1 & ve2 & ve3 & vm2 & vm3 & vm4 --> CLI{{"Señales clínicas"}}
    ve2 --> DUR{{"Reglas duras"}}
    vc1 & vc2 & vc3 & va1 & va2 & va3 & va4 --> BOX{{"Panel de box"}}
    vp2 --> EQ{{"Auditoría de equidad"}}
```

### Catálogo de variables

| Variable | Origen | Cálculo (siempre con fecha ≤ corte) | Uso |
|---|---|---|---|
| `base_prioridad` | `lista_espera.prioridad_inicial` | alta = 20, media = 10, baja = 0 | Puntaje |
| `dias_espera` | `lista_espera.fecha_ingreso_lista` | `corte − fecha_ingreso_lista` | Puntaje (peso bajo) |
| `factor_edad` | `pacientes.edad` | Escalonado: ≥ 75 años suma más | Puntaje (peso bajo) |
| `aporte_eventos` | `eventos_clinicos` | `Σ w(tipo, subtipo) · exp(−λ·Δt)`, con λ = ln 2 / 90 días | Puntaje |
| `n_graves_30d` | `eventos_clinicos` | Eventos con `severidad = grave` en los últimos 30 días | Regla dura |
| `n_mejora_90d` | `eventos_clinicos` | buena respuesta, estabilización, reducción dosis en 90 días | Puntaje (resta) |
| `desviacion_rango` | `mediciones` | `max(0, valor − max, min − valor) / (max − min)` del último valor | Puntaje |
| `pendiente_empeora` | `mediciones` | Pendiente por 30 días / ancho del rango; signo invertido en saturación y peak flow | Puntaje (la mejor señal según el EDA) |
| `pct_fuera_rango_90d` | `mediciones` | Proporción de mediciones fuera de rango en 90 días | Puntaje |
| `riesgo_no_show` | `citaciones` | `n_no_asistio / n_citas` con suavizado hacia la tasa global (23 %) | Panel de box |
| `presion_demanda` | `lista_espera` + `agenda_box` | `% pacientes en espera / % capacidad` por especialidad | Panel de box |
| `ocupacion`, `cupos_libres`, `sobretiempo_medio` | `agenda_box` | Por especialidad y semana | Panel de box |
| `excluido` | `pacientes`, `lista_espera` | `fallecido` o `estado ≠ en_espera` | Exclusión |

Las variables demográficas (`sexo`, `comuna`, `prevision`, `nivel_socioeconomico`) **no entran al puntaje clínico**. Se usan para auditar la equidad: comparar la distribución de los cambios de prioridad entre grupos.

---

## 3. Modelo de datos y trazabilidad

Tablas fuente (solo lectura) y tablas que genera el sistema. Cada `factor_propuesta` apunta a la fila exacta que lo originó.

```mermaid
erDiagram
    PACIENTES ||--|| LISTA_ESPERA : "tiene"
    PACIENTES ||--o{ EVENTOS_CLINICOS : "registra"
    PACIENTES ||--o{ MEDICIONES : "registra"
    PACIENTES ||--o{ CITACIONES : "recibe"
    AGENDA_BOX ||--o{ CITACIONES : "id_box"

    LISTA_ESPERA ||--o{ PROPUESTA_PRIORIDAD : "se evalúa en"
    PROPUESTA_PRIORIDAD ||--|{ FACTOR_PROPUESTA : "se explica por"
    PROPUESTA_PRIORIDAD ||--o| DECISION_CLINICA : "se valida con"
    FACTOR_PROPUESTA }o--o| EVENTOS_CLINICOS : "fuente"
    FACTOR_PROPUESTA }o--o| MEDICIONES : "fuente"
    FACTOR_PROPUESTA }o--o| CITACIONES : "fuente"

    PACIENTES {
        string id_paciente PK
        int edad
        string sexo
        string comuna
        string prevision
        string nivel_socioeconomico
        bool fallecido
        date fecha_defuncion
    }
    LISTA_ESPERA {
        string id_solicitud PK
        string id_paciente FK
        string especialidad
        string diagnostico_cie10
        string prioridad_inicial "alta, media, baja; nunca se modifica"
        date fecha_ingreso_lista
        string origen_derivacion
        string estado "en_espera, citado, atendido, egresado, fallecido"
    }
    EVENTOS_CLINICOS {
        string id_evento PK
        string id_paciente FK
        date fecha_evento
        string tipo_evento
        string subtipo
        string severidad "leve, moderada, grave"
    }
    MEDICIONES {
        string id_paciente FK "PK compuesta con fecha y tipo"
        date fecha_medicion
        string tipo_medicion
        float valor
        bool fuera_de_rango
    }
    CITACIONES {
        string id_cita PK
        string id_paciente FK
        string id_box FK
        date fecha_cita
        string estado_cita "asistio, no_asistio, reprogramo, cancelo"
    }
    AGENDA_BOX {
        string id_box PK "PK compuesta con fecha"
        date fecha
        string especialidad
        int capacidad_cupos
        int cupos_usados
        int minutos_sobretiempo
    }
    PROPUESTA_PRIORIDAD {
        string id_propuesta PK
        string id_solicitud FK
        date fecha_corte
        datetime fecha_calculo
        float puntaje
        string prioridad_propuesta "alta, media, baja"
        string prioridad_vigente "la que estaba al calcular"
        string cambio "sube, baja, igual"
        bool alerta "regla dura activada"
        string version_reglas
        string huella_datos "hash de las filas usadas"
        string explicacion_texto "redactada por el LLM"
    }
    FACTOR_PROPUESTA {
        string id_propuesta FK
        string factor
        float aporte
        string tipo_fuente "evento, medicion, cita, lista, paciente"
        string ref_fuente "EV-000123 o PAC/fecha/tipo"
        date fecha_dato
    }
    DECISION_CLINICA {
        string id_decision PK
        string id_propuesta FK
        string decision "acepta, ajusta, rechaza"
        string prioridad_final "alta, media, baja"
        string motivo
        string usuario
        datetime fecha
    }
```

**Reglas de trazabilidad:**
- `prioridad_inicial` **no se modifica nunca**. La propuesta y la decisión viven en tablas aparte.
- Cada propuesta guarda la `fecha_corte`, la `version_reglas` y una `huella_datos`. Con eso se puede reproducir exactamente el mismo cálculo.
- `ref_fuente` usa el ID de la fila cuando existe (`EV-…`, `CT-…`, `IC-…`). Las mediciones no tienen ID, así que se referencian por `id_paciente/fecha_medicion/tipo_medicion`.
- La explicación del LLM se guarda junto a los factores. Se valida que solo mencione factores presentes en `factor_propuesta`.

---

## 4. Niveles de priorización

### Escalas definidas en los datos

| Escala | Valores | Dónde |
|---|---|---|
| Prioridad | **alta · media · baja** | `lista_espera.prioridad_inicial` (y la propuesta usa la misma escala) |
| Severidad del evento | **grave · moderada · leve** | `eventos_clinicos.severidad` |
| Estado de la solicitud | en_espera · citado · atendido · egresado · fallecido | `lista_espera.estado` (en el dataset solo aparecen en_espera, atendido y fallecido) |
| Resultado de la cita | asistio · no_asistio · reprogramo · cancelo | `citaciones.estado_cita` |
| Medición | dentro / fuera de rango | `mediciones.fuera_de_rango` |

### Cómo se asigna el nivel propuesto

```mermaid
flowchart TD
    A["Solicitud a la fecha de corte"] --> B{"¿Paciente fallecido o<br/>estado ≠ en_espera?"}
    B -- "sí" --> X["EXCLUIDA<br/>sale de la bandeja, sin nuevas citas"]
    B -- "no" --> C{"Regla dura:<br/>¿evento grave en los últimos 30 días?<br/>urgencia ESI 2, descompensación grave,<br/>hospitalización, ingreso UCI"}
    C -- "sí" --> H["ALTA + ALERTA<br/>revisión clínica prioritaria"]
    C -- "no" --> D["Puntaje de nivel =<br/>base_prioridad + aporte_eventos + aporte_mediciones<br/>+ patrones + ajuste por riesgo basal"]
    D --> E{"Puntaje"}
    E -- "≥ 20" --> AL["ALTA"]
    E -- "10 a 19,9" --> ME["MEDIA"]
    E -- "< 10" --> BA["BAJA"]
    AL & ME & BA --> G{"¿La propuesta baja el nivel<br/>sin evidencia de mejora?"}
    G -- "sí" --> K["Se mantiene la prioridad vigente<br/>la falta de datos no baja la prioridad"]
    G -- "no" --> Z["Propuesta final"]
    H --> Z
    K --> Z
    Z --> V["El equipo clínico acepta, ajusta o rechaza"]
```

- **Umbrales iniciales:** alta ≥ 20, media 10–19,9, baja < 10, aplicados al **puntaje de nivel**. Con `base_prioridad` alta = 20 y media = 10, un paciente sin señales conserva su nivel. Los umbrales se versionan en `version_reglas` y se calibran con el equipo clínico.
- **Dos puntajes (implementado en el MVP, `reglas-v0.1`):** el *puntaje de nivel* decide el nivel y solo incluye la base y las señales clínicas. El *puntaje de orden* le suma el contexto (riesgo basal, edad, espera) y ordena dentro del nivel. Así el contexto nunca cambia el nivel por sí solo, pero desempata. Ver `docs/mvp.md`.
- **Bajar de nivel** exige evidencia de mejora (`n_mejora_90d > 0` o mediciones normales sostenidas). Un paciente sin registros nunca baja.
- **Prioridad vigente** = la última `prioridad_final` aceptada por el equipo clínico o, si no hay ninguna, `prioridad_inicial`. La propuesta se compara contra ella para marcar `cambio` (sube, baja, igual).
- **Riesgo basal por diagnóstico (abordado en el MVP, a validar con clínicos).** Dos pacientes con diagnósticos de riesgo muy distinto (por ejemplo I50 insuficiencia cardíaca y K21 reflujo) podían quedar en el mismo nivel y empatados. En `reglas-v0.1`, cada CIE-10 tiene una clase de riesgo basal (alto, medio o bajo) que (1) ajusta el peso de las señales clínicas (×1,25 alto, ×0,8 bajo) y (2) suma al puntaje de orden dentro del nivel. Ver `docs/enfoque.md`, sección "Pendiente: riesgo basal según el diagnóstico".
- **`riesgo_no_show` no cambia el nivel.** Se muestra como una marca aparte con una acción sugerida (confirmar la cita, ofrecer otro horario).

### Ejemplo con los casos de referencia

| Caso | Prioridad inicial | Señal principal | Nivel propuesto |
|---|---|---|---|
| PAC-HLF-00002 · deterioro agudo | baja | Urgencia ESI 2 (2026-07-20) | **alta + alerta** desde el corte 2026-07-20 |
| PAC-HLF-00001 · deterioro progresivo | alta | Pendiente del PHQ-9 de 4 a 19 | alta (se mantiene, con la tendencia destacada) |
| PAC-HLF-00028 · mejora | baja | Buena respuesta, PHQ-9 = 0 | baja (no puede bajar más) |
| PAC-HLF-00020 · inasistencia | media | 2 no-show, mediciones en rango | media + marca de riesgo de no-show |
| PAC-HLF-00032 · atendido | baja | Atendido 2026-06-30 | excluida desde 2026-06-30 |
| PAC-HLF-00009 · fallecido | baja | Urgencia con descompensación grave (2026-08-29) | alta + alerta; excluida desde 2026-09-08 |

### Ciclo de vida de una solicitud

```mermaid
stateDiagram-v2
    [*] --> en_espera : ingreso a la lista
    state en_espera {
        [*] --> vigente
        vigente --> propuesta_pendiente : evento o medición nueva → recálculo
        propuesta_pendiente --> vigente : acepta / ajusta / rechaza
    }
    en_espera --> citado : se asigna cupo
    citado --> en_espera : no_asistio / reprogramo / cancelo
    citado --> atendido : asistio
    en_espera --> fallecido : fecha_defuncion
    citado --> fallecido : fecha_defuncion
    en_espera --> egresado : otra causal
    atendido --> [*]
    fallecido --> [*]
    egresado --> [*]
```

---

## 5. Flujo de la aplicación

Desde que entra un dato nuevo hasta que queda registrada la decisión clínica.

```mermaid
sequenceDiagram
    autonumber
    participant F as Fuente (carga de datos)
    participant I as Integración
    participant V as Variables
    participant M as Motor de priorización
    participant LLM as LLM redactor (Bedrock)
    participant DB as Registro
    participant UI as Vistas
    actor C as Equipo clínico

    F->>I: Nuevo evento / medición / cita
    I->>I: Unir por id_paciente, filtrar fecha ≤ corte
    I->>V: Historia del paciente a la fecha de corte
    V->>M: Variables clínicas + contexto
    M->>M: Exclusión → reglas duras → puntaje → nivel
    M->>DB: propuesta_prioridad + factor_propuesta (con ref_fuente)
    M->>LLM: Factores estructurados (sin datos fuera del entorno autorizado)
    LLM-->>M: Explicación en lenguaje clínico
    M->>M: Validar que la explicación solo cite factores entregados
    M->>DB: explicacion_texto
    DB->>UI: Bandeja actualizada (sube / baja / alerta)
    C->>UI: Abre la ficha, revisa línea de tiempo y factores
    C->>UI: Acepta, ajusta o rechaza, con motivo
    UI->>DB: decision_clinica (usuario, fecha, prioridad_final)
    DB->>UI: KPIs: tiempo a reevaluación, cobertura, concordancia
```

En el prototipo, la "fuente" es el dataset completo. Se simula la llegada de datos avanzando la fecha de corte día a día.

---

## 6. Vistas

```mermaid
flowchart TB
    subgraph B["Bandeja priorizada"]
        B1["Filtros: especialidad, nivel, cambio, alerta"]
        B2["Tabla: paciente · dx · prioridad vigente → propuesta · motivo principal · días de espera"]
        B3["Marcas: ⚠️ alerta · ↑ sube · ↓ baja · 📵 riesgo no-show"]
    end

    subgraph P["Ficha del paciente"]
        P1["Línea de tiempo: eventos, mediciones con rango normal, citas"]
        P2["Evolución del puntaje en el tiempo"]
        P3["Factores con aporte y enlace a su dato de origen"]
        P4["Explicación redactada por el LLM"]
    end

    subgraph D["Validación clínica"]
        D1["Aceptar / ajustar nivel / rechazar"]
        D2["Motivo obligatorio si ajusta o rechaza"]
        D3["Historial de propuestas y decisiones"]
    end

    subgraph X["Panel de box"]
        X1["Ocupación y cupos libres por especialidad y semana"]
        X2["Demanda vs. capacidad por especialidad"]
        X3["No-show y sobretiempo"]
        X4["Pacientes en alta sin cita vs. cupos libres"]
    end

    subgraph K["KPIs"]
        K1["Tiempo a reevaluación"]
        K2["Cobertura"]
        K3["Concordancia (kappa) con las decisiones"]
        K4["Equidad: cambios por edad, sexo, comuna, previsión"]
    end

    S["Selector de fecha de corte"] -.-> B & P & X & K
    B -- "clic en paciente" --> P
    P -- "validar" --> D
    D -- "guardar" --> B
    B -- "pestaña" --> X
    B -- "pestaña" --> K
```

| Vista | Pregunta que responde | Datos que usa |
|---|---|---|
| Bandeja priorizada | ¿A quién reviso primero hoy? | `propuesta_prioridad` vigente, `lista_espera`, alertas |
| Ficha del paciente | ¿Por qué cambió su prioridad? | `eventos_clinicos`, `mediciones`, `citaciones`, `factor_propuesta` |
| Validación clínica | ¿Estoy de acuerdo con la propuesta? | `propuesta_prioridad` → `decision_clinica` |
| Panel de box | ¿Está bien usada la capacidad? | `agenda_box`, `citaciones`, demanda por especialidad |
| KPIs | ¿Funciona la herramienta? | Propuestas, decisiones y eventos (`docs/kpis.md`) |
