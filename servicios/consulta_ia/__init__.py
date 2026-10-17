"""Consulta en lenguaje natural de la Administradora (F0009): clasifica la pregunta y responde con una sola fuente.

- conteo → SQL generado por Claude, validado (solo lectura, solo hlf_raw y hlf_historial) y ejecutado en Athena.
- texto  → RetrieveAndGenerate sobre la Knowledge Base del equipo clínico, citando los fragmentos.
- rechazada → pide modificar datos, un diagnóstico o algo fuera del alcance: no se ejecuta nada.
Cada pregunta queda en consulta.pregunta (y sus fuentes en consulta.fuente_respuesta) con la persona autenticada.
"""
