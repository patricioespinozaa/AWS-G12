---
inclusion: always
---

# Tecnología

- Python.
- Pydantic para contratos de entrada y salida.
- pytest para pruebas.
- SDK oficial de Anthropic para inferencia.

# Arquitectura

Separar ingesta, validación, cronología, construcción de contexto,
inferencia y validación de respuesta.

Los cálculos se realizan en Python.
La IA interpreta evidencia previamente organizada.

El JSON consolidado y los CSV no son evidencias independientes.
No duplicar registros al cargar ambas representaciones.

Las pruebas deben funcionar sin llamadas reales a la API.
Usar clientes simulados para las pruebas de integración.