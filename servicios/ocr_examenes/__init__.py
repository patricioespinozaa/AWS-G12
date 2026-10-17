"""Lectura asistida de exámenes externos (F0012): Textract extrae el texto, Claude propone tipo, valor, unidad, fecha y
lugar citando el documento, y un validador determinista descarta todo lo que no esté literal en el texto.

La propuesta queda en canal.lectura_examen; el examen solo cuenta para la prioridad cuando una persona lo valida.
"""
