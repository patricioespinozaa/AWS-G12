"""Preparación de la Knowledge Base del equipo clínico (F0009): documentos a la fecha de corte → S3 kb/equipo/ → ingesta.

    python -m servicios.preparacion_kb            # genera, sube, registra y sincroniza (tarea ECS)
    python -m servicios.preparacion_kb --local DIR    # solo genera los documentos en una carpeta (sin AWS)
"""
