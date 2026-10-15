---
inclusion: always
---

# Objetivo

Construir un copiloto de revisión de pacientes que esperan
su primera consulta de especialidad.

El software genera y administra avisos.
La IA organiza antecedentes y propone revisión.
El profesional decide cambios de prioridad.

# Límites

- Trabajar inicialmente con datos sintéticos.
- No diagnosticar ni modificar prioridades automáticamente.
- No prescribir ni realizar citaciones automáticas.
- No inventar probabilidades clínicas.
- Cada hallazgo debe referenciar evidencia verificable.
- La ausencia de registros no demuestra estabilidad.
- Una cita asistida no cierra una solicitud sin vínculo confirmado.
- No atribuir fallecimientos a la espera.
- No penalizar por previsión, nivel socioeconómico o inasistencia.

# Temporalidad

- Toda evaluación debe tener fecha de corte.
- No utilizar información posterior al corte.
- El estado actual no debe aplicarse retroactivamente.
- Señalar cuándo no puede reconstruirse el estado histórico.

# Seguridad de desarrollo

- No leer ni mostrar .env.
- No enviar datos a APIs sin autorización explícita.
- No modificar archivos originales de data/raw.
- No ejecutar acciones clínicas.