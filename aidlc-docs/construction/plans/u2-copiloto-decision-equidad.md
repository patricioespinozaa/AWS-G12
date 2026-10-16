# Decisión — Cómo validar la regla de equidad (C6.5)

## Situación

El flujo de correcciones de U2 terminó por llegar al máximo de iteraciones. Cuatro de los cinco cambios quedaron bien y aprobados por el revisor:
- `max_tokens = 8192` ratificado en el diseño.
- `--max-llamadas` como presupuesto real de invocaciones, también con concurrencia.
- El motivo `contexto_no_disponible`.
- El código de salida 4 para un modelo no permitido.

Queda pendiente la regla de equidad C6.5: rechazar un análisis que use comuna, previsión, nivel socioeconómico o inasistencias como motivo para **bajar** la prioridad.

El validador actual busca ese patrón con expresiones regulares que respetan la negación (para aceptar "las inasistencias **no** se usan para bajar la prioridad"). Ya van tres revisiones, y cada arreglo deja pasar una frase nueva:
- 1.ª: "no hay motivo urgente **y** por su comuna conviene bajarla"
- 2.ª: "**sin** ⟨atributo⟩", "**no solo** por ⟨atributo⟩"
- 3.ª: "no se debe bajar por la clínica, **sino** por su comuna"; "no corresponde bajarla, **salvo** por su previsión"; y conjugaciones como "**se baja**" o "**bajamos**"

**La causa de fondo:** interpretar negaciones en español libre con expresiones regulares no tiene fin. Seguir parchando así no va a dar una regla confiable. Hay que cambiar de enfoque.

## Un dato que simplifica el problema

El copiloto **nunca recibe** comuna, previsión ni nivel socioeconómico: `ContextoPaciente` no tiene esos campos. Si un análisis los menciona, el modelo los está inventando o suponiendo. En los dos casos es sospechoso, sin importar si lo dice en negativo. El único de los cuatro atributos que sí está en los datos es **inasistencias** (las citas `no_asistio`).

---

## Pregunta E-1 — Nuevo enfoque para C6.5

A) **Regla simple que rechaza ante la duda, sin interpretar negaciones:**
   - Si el texto menciona comuna, previsión o nivel socioeconómico (que no están en los datos), se rechaza el análisis.
   - Si menciona inasistencias junto a cualquier forma del verbo bajar, postergar o reducir **en la misma frase**, se rechaza, aunque esté en negativo.
   - El prompt pasa a `copiloto-v1.2.0` con la instrucción de no mencionar esos atributos y de referirse a las inasistencias solo como riesgo de no asistir, sin vincularlas a la prioridad.
   - Costo: los 2 análisis reales que decían "las inasistencias no se usan para bajar" quedarían rechazados y habría que reanalizarlos (2 a 4 llamadas). Rechaza más de la cuenta, pero nunca deja pasar una frase prohibida.

B) **Marcar sin rechazar:** misma detección que A, pero el análisis se guarda con una marca `revision_equidad` y una advertencia visible en la bandeja (U3). El médico ve la frase y decide. No se pierden análisis y no se gastan llamadas, pero la frase llega a la pantalla.

C) **A + B:** se rechaza lo inequívoco (mención de comuna, previsión o NSE) y se marca para revisión lo de inasistencias con un verbo de bajada.

X) Other (describe después de `[Answer]:`)

[Answer]: C

> Recomendación: **C**. Rechaza siempre lo que el modelo no puede saber (comuna, previsión, NSE). Para inasistencias, que sí están en los datos y que el modelo suele mencionar justamente para decir que no cuentan, deja la decisión al médico con una advertencia clara, que es el principio del sistema. En los dos casos se corrigen las conjugaciones de "bajar" y la regla queda determinista y fácil de probar.
