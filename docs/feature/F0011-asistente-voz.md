# F0011 · Asistente del paciente por teléfono (voz)

**Estado:** Plan · **Depende de:** F0010 · **Tamaño:** M

## Objetivo

Que el paciente llame a un número del hospital y resuelva por voz lo mismo que por WhatsApp (F0010), con transferencia a una persona cuando haga falta. Es el flujo C de `docs/diagramas/flujos-aws.pdf`. Llega a quienes no usan WhatsApp, que en la lista de espera suelen ser personas mayores.

## Qué existe hoy

- Todo el modelo de datos de la llamada está en `canal` (F0002):
  - `conversacion` tiene `canal = 'voz'`, `id_externo` (= ContactId de Amazon Connect) y `uri_grabacion` (solo con consentimiento).
  - `turno.confianza_asr` guarda la confianza del reconocimiento de voz.
  - `derivacion_humana` registra los casos que pasan a una persona.
- F0010 deja listos el núcleo del asistente, las herramientas, la verificación y la auditoría.
- No existe nada de telefonía.

## Alcance

**Entra:**
- Instancia de Amazon Connect, número y flujo de contacto.
- Bot de Lex V2 en español.
- Lambda que conecta Lex con el núcleo del asistente.
- Voz de Polly.
- Cola de atención humana.
- Mensaje de consentimiento y grabación opcional.

**No entra:** llamadas salientes automáticas (recordatorios por voz); quedan como mejora.

## Diseño

```mermaid
flowchart LR
    P[Paciente] -->|llama| CN[Amazon Connect<br/>número + flujo]
    CN -->|consentimiento, caller ID| LEX[Lex V2 · es_US<br/>voz a texto + intención]
    LEX -->|fulfillment| L[Lambda voz → núcleo del asistente]
    L --> DB[(RDS canal · v_ia_*)]
    L --> BR[Bedrock Claude Haiku]
    L -->|texto corto| LEX
    LEX -->|Polly neural| P
    CN -->|alarma, pide persona, 2 fallos| Q[Cola humana TENS / call center]
```

| Decisión | Elección | Por qué |
|---|---|---|
| Telefonía | Amazon Connect, con flujo de contacto versionado en el repositorio (JSON) | Número, colas y transferencia en un solo servicio |
| Reconocimiento y diálogo | Lex V2 en una variante de español disponible (`es_US` o `es_419`), con intenciones del catálogo `canal.intencion` y una intención de respaldo hacia el núcleo | Lex resuelve el reconocimiento de voz y los turnos; Claude solo redacta |
| Modelo | Claude Haiku, con respuestas de 1 o 2 frases | Presupuesto de latencia de ~2 s por turno |
| Verificación | Caller ID → HMAC → `contacto_paciente`, más un código o dígitos marcados en el teclado (DTMF) | Igual que en F0010. Los dígitos no se transcriben ni se guardan |
| Voz | Polly neural en una voz en español | Naturalidad para personas mayores |
| Números y fechas | El núcleo devuelve los números en palabras para voz ("lugar tres de ciento veinte"; "catorce a treinta y cinco días") | Evita lecturas ambiguas |
| Grabación | Solo con consentimiento `grabacion_llamada` y retención según `retener_hasta` | F0002, retención y protección de datos |
| Transferencia | Síntoma de alarma, pedir una persona o dos turnos sin entender → cola humana, con el resumen en atributos del contacto | El agente no vuelve a preguntar lo mismo |

## Cambios por carpeta

```
servicios/asistente/voz.py            adaptador: evento de Lex ↔ núcleo; formatos para voz
servicios/asistente/tests/test_voz.py
infra/stacks/voz.py                   instancia Connect, número, cola, flujo, bot Lex, permisos de la Lambda
infra/connect/flujo_entrante.json     flujo de contacto (consentimiento → Lex → transferencia)
```

## Tareas

1. Adaptador de voz y formatos hablados, con pruebas de cifras y fechas en palabras.
2. Bot de Lex con intenciones y respaldo hacia el núcleo.
3. Instancia de Connect, número y flujo entrante.
4. Cola humana y transferencia con resumen.
5. Prueba de latencia: medir el tiempo de cada turno y ajustar (modelo, longitud, conexión reutilizada).
6. Ensayo de la demo: llamar, verificarse y preguntar posición, tiempo estimado y próxima cita. Luego avanzar el reloj (F0006) y comprobar que la posición cambia.

## Criterios de aceptación

- Una llamada completa con verificación responde la posición y el rango estimado, y queda registrada en `conversacion`, `turno` y `divulgacion`.
- La latencia por turno es menor a 2,5 s en el p90.
- "Quiero hablar con alguien" transfiere a la cola con el motivo visible para el agente.
- Sin consentimiento de grabación, `uri_grabacion` queda vacía y no hay audio en S3.

## Riesgos y decisiones abiertas

- **Números chilenos en Connect:** la disponibilidad depende de la región y del país. Para la demo puede bastar un número de otro país o un número gratuito; con datos reales se debe usar un número local.
- **Reconocimiento de nombres propios y RUT:** no se usan para verificar. Solo dígitos por teclado y códigos.
- **Región de Connect y Lex:** debe coincidir con la región de las Lambdas o justificar el cruce.
