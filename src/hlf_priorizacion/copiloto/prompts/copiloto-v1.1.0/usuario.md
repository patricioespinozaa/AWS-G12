Analiza la solicitud $id_solicitud a la fecha de corte $fecha_corte (reglas $version_reglas).

Los datos incluyen: el paciente (edad y sexo a la fecha de corte), la solicitud y otras solicitudes del paciente, todos sus eventos, mediciones y citas hasta el corte (cada uno con su ID), la evaluación del motor (puntaje, factores con su aporte e IDs, banderas, pisos, contradicciones y alertas), la evaluación del día anterior si existe (`evaluacion_anterior`; si no es nula, explica qué cambió), los hallazgos de calidad de datos y el riesgo poblacional de la cohorte (o `null` si no hay cohorte).

<datos_clinicos>
$datos_clinicos
</datos_clinicos>

Responde solo con la herramienta `registrar_analisis`. El campo `id_solicitud` debe ser $id_solicitud. Incluye siempre `nota_preconsulta`, y cada hallazgo `documentado` con al menos un ID de los datos (si no hay ID que citar, márcalo `inferido`).
