# U3 — Componentes de interfaz (Streamlit)

App única `app/bandeja.py`, en español, con barra lateral y cuatro vistas por pestañas. Ejecución: `uv run streamlit run app/bandeja.py`.

## Barra lateral

| Elemento | Tipo | Estado | Validación |
|---|---|---|---|
| Médico | `selectbox` con la lista fija (H-4) y opción vacía | `st.session_state["medico"]` | Sin médico, los botones de decisión quedan deshabilitados con el aviso "Elija un médico" |
| Fecha de corte | `selectbox` con los cortes disponibles | `["corte"]` | Solo cortes con propuestas |
| Versión de reglas | Texto fijo (`reglas-v0.1.0`) | — | — |
| Aviso fijo | Texto | — | "Demo local con datos sintéticos. El sistema propone; el médico decide." |

## Pestaña 1 — Bandeja

| Elemento | Detalle |
|---|---|
| Filtros | Especialidad (multiselect), nivel propuesto, tipo de resultado, casillas "solo con análisis", "solo con advertencia de equidad", "incluir sin alerta", estado de decisión |
| Tabla | `st.dataframe` de solo lectura con: ID, especialidad, inicial → propuesto (con flecha y color), puntaje, banderas, análisis (sí/no/fallido), equidad (⚠), decisión. Selección de fila con `on_select` |
| Contador | "N solicitudes · M críticas · K con análisis" |
| Acción | Elegir una fila abre el Detalle |

Los colores siempre van acompañados de texto o ícono (crítica/alta/media/baja), no son la única señal (accesibilidad).

## Pestaña 2 — Detalle

| Sección | Contenido |
|---|---|
| Encabezado | ID, especialidad, diagnóstico CIE-10, edad y sexo, días en espera; inicial / calculado / **propuesto**; puntaje; confianza y sus motivos |
| Banderas, pisos, contradicciones, alertas | Lista con código, explicación y IDs |
| Factores | Tabla: factor, detalle, aporte, IDs. Gráfico de barras horizontal de aportes |
| Línea de tiempo | Tabla por fecha: tipo, detalle, valor, ID. El ID elegido en factores se resalta. Mensaje si la huella no coincide |
| Calidad de datos | Hallazgos del corte para esta solicitud |
| Advertencia de equidad | `st.warning` antes del análisis, si aplica (B3.5) |
| Análisis del copiloto | Encabezado "Sugerencia del copiloto — no es una decisión"; prioridad sugerida y acuerdo con el motor; resumen; hallazgos (documentado con IDs / inferido); riesgo poblacional con n, IC95 y advertencias; acciones sugeridas; datos faltantes; correcciones del validador; modelo y versión de prompt. Si no hay: "Análisis IA pendiente" + comando |
| Nota de pre-consulta | `st.text_area` deshabilitada (solo lectura) |
| Decisión | Formulario `st.form`: radio aceptar/ajustar/rechazar; selector de prioridad final (solo si ajustar, sin la propuesta); `text_area` motivo (máx. 1000; obligatorio en ajustar y rechazar); botón Guardar. Error de validación con `st.error` sin guardar. Éxito con `st.success` |
| Historial | Decisiones anteriores de esta solicitud y corte (solo lectura) |

## Pestaña 3 — ¿Qué cambió?

| Elemento | Detalle |
|---|---|
| Selectores | Corte A y corte B; aviso si A ≥ B |
| Tabla de cambios | ID, nivel A → B, puntaje A → B, banderas nuevas, registros nuevos (IDs). Selección abre el Detalle en el corte B |
| Secciones aparte | Ingresos nuevos en B; pasaron a exclusión |

## Pestaña 4 — Cobertura

Métricas (`st.metric`) y tablas de B6 para el corte elegido.

## Identificadores para pruebas automatizadas

Cada widget interactivo lleva `key` estable con el patrón `{vista}-{elemento}` (`bandeja-filtro-especialidad`, `detalle-decision-radio`, `detalle-decision-motivo`, `detalle-decision-guardar`, `cambios-corte-a`, `lateral-medico`), que usan `AppTest` y la verificación en el navegador.

## Configuración (`app/.streamlit/config.toml`)

`server.address = "127.0.0.1"`, `server.headless = true`, `browser.gatherUsageStats = false`, `client.toolbarMode = "minimal"`.
