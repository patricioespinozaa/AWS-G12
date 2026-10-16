# F0015 · Rediseño del frontend

**Estado:** Implementado · **Depende de:** F0014 · **Tamaño:** S

## Objetivo

Una interfaz de software clínico, sobria y directa: sin emojis, sin textos repetidos y con cada vista guiando el paso a paso de la Administradora.

## Resultado

| Pieza | Cambio |
|---|---|
| Identidad | Cabecera institucional (HLF · SSMSO), menú lateral azul institucional agrupado por flujo de trabajo (Trabajo diario, Análisis, Datos y reglas), contador de pendientes en Canal |
| Iconos | `lucide-react` (0.460.0, versión fija) en vez de emojis |
| Estados | Distintivo "Datos sintéticos" siempre visible; el de IA solo cuando Bedrock está activo; sesión como "Administradora · Modo local" o con cierre de sesión en AWS |
| Componentes | `Encabezado` (título, una línea y acciones), `Pasos` (indicador de flujo con el paso en curso), `Disponibilidad` con icono, `IconoAlerta`, avisos con icono, carga con spinner |
| Vistas | Lista priorizada: filtros rápidos segmentados, 4 indicadores, prioridad vigente → propuesta en una columna. Ficha: banda de identificación y pestañas 1 Evolución · 2 Por qué · 3 Decidir. Canal: "Por validar" primero. Cargas y Reglas: paso a paso con el paso en curso. Proceso nocturno: la tabla de reglas pasa a la vista Reglas |
| Textos | Fuera los mensajes que ya no aplican ("maqueta", "segunda iteración", "IA desactivada", "modo local" en el menú) y las descripciones largas, reducidas a una línea |
