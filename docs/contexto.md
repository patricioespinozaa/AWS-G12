# Contexto del desafío

**Desafío:** Evaluación dinámica del riesgo y priorización asistencial
**Institución:** Hospital Clínico Dra. Eloísa Díaz La Florida (HLF), Servicio de Salud Metropolitano Sur Oriente (SSMSO)
**Evento:** Hackatón de IA Generativa AWS Breaking Barriers Chile 2026 · 14 al 16 de octubre · Universidad de Chile, Beauchef 851, Santiago
**Referente:** Víctor Arancibia, Gestor de Salud, equipo CR Ambulatorio HLF

> "La lista de espera es una foto; la salud de las personas, una película. Ayúdanos a ver quién empeora mientras espera."

## El hospital

Hospital público de alta complejidad del SSMSO. Atiende a la población de La Florida y a personas derivadas desde la red, en consultas de especialidad, urgencia, hospitalización y cirugía.

| Indicador (2023) | Valor |
|---|---|
| Consultas de especialidad al año | 154.531 |
| Consultas de urgencia al año | 83.370 |
| Camas dotadas | 397 |
| Consultas de especialidad en lista de espera | 26.356 |

## El problema

La prioridad se asigna **una vez** y queda congelada. La información que mostraría el deterioro existe, pero está:
- **dispersa** entre distintas fuentes,
- en **texto libre**,
- **sin un mecanismo** que la reevalúe.

El problema golpea más a quien tiene más carga de enfermedad: personas mayores y con diabetes o hipertensión, cuyo daño visual avanza mientras esperan y puede ser irreversible.

### Dimensión nacional
- 364.390 consultas de oftalmología esperan en Chile: el **17 %** de toda la lista no GES.
- **198 días** de mediana de espera para una consulta nueva de oftalmología.

### Caso ilustrativo: don Manuel

> Don Manuel tiene 68 años y es diabético. Su CESFAM lo deriva a oftalmología por baja de visión y entra a la lista como «no urgente». Mientras espera, consulta dos veces en urgencia por hiperglicemia y queda hospitalizado. Nadie conecta esos eventos con sus ojos: su lugar en la lista no cambia. Cuando por fin llega al oftalmólogo, la retinopatía ya le quitó visión que no va a recuperar.

Es un caso construido a partir de trayectorias frecuentes. Sirve como **caso de prueba de referencia**: el sistema debería subir su prioridad tras la primera urgencia por hiperglicemia.

## Ruta del paciente

```
1. Atención primaria (CESFAM)  → detecta baja de visión o un hallazgo en el fondo de ojo
2. Interconsulta (SIC)         → el médico deriva al HLF con un diagnóstico de sospecha
3. Lista de espera: consulta nueva → priorización manual, una sola vez, criterios heterogéneos
        ── BRECHA 1: la prioridad no cambia aunque el paciente empeore
4. Primera consulta de oftalmología → diagnóstico e indicación de control en «X meses», a menudo en texto libre
        ── BRECHA 2: si la indicación no se formaliza, el control no existe en la lista
5. Lista de controles
6. Control, cirugía o alta     → se resuelve el problema o empieza un nuevo ciclo
```

### Señales que hoy se pierden
- Consulta de urgencia
- Hospitalización
- Cambio de tratamiento
- Descompensación de una enfermedad crónica
- El **riesgo ACG** que ya calcula la red, que tampoco se integra

Estas señales quedan registradas en el RCE y en otras fuentes, pero desconectadas de la priorización.

## Qué se resuelve ahora y hasta dónde puede crecer

**Ahora:** oftalmología del HLF, con listas separadas de consultas nuevas y de controles.

| Antes | Después |
|---|---|
| Priorización manual, una sola vez, con criterios heterogéneos | Cada evento clínico relevante gatilla una reevaluación y una propuesta de prioridad explicada, que el equipo clínico valida |
| Controles invisibles | Día 1: toda la lista revisada con el mismo criterio y la demanda de controles visible |

**Después:**
- **Replicable** en otras especialidades del HLF y en hospitales públicos con registro clínico electrónico.
- **Escalable** a la Red Sur Oriente, integrando el riesgo ACG, y a los 29 servicios de salud del país.
- **Efecto multiplicador:** demanda real visible para planificar la oferta de horas y supervisar la lista.

## Pregunta del desafío

> ¿Cómo podríamos reconocer los cambios en la necesidad clínica de cada persona mientras espera, y traducirlos en una priorización oportuna, consistente y explicable?

La solución debería:
1. **Detectar** cambios.
2. **Reevaluar** el riesgo.
3. **Proponer** una prioridad explicable y trazable.
4. Dejar que el **equipo clínico decida**.

## Principio

> La herramienta propone y explica; el equipo clínico decide. La posición en la lista no equivale a una fecha garantizada de atención.
