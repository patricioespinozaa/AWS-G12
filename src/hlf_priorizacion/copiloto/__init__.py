"""U2 — Copiloto IA en modo barrido (``hlf-copiloto``).

Analiza con Amazon Bedrock las solicitudes que el motor dejó en ``priorizacion`` y guarda un
``AnalisisIA`` validado y citado, siempre pendiente de revisión médica. Las funciones que deciden qué
analizar, arman el paquete y validan la salida son puras; solo el cliente del modelo y la persistencia
hacen E/S, y ambos se inyectan.
"""
