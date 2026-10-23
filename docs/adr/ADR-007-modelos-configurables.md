# ADR-007: Modelos y proveedores de LLM configurables

**Fecha:** 2026-10-23 · **Estado:** Aceptado

## Contexto
Los modelos cambian cada pocos meses y los precios también. El libro usaba la generación
4.x de Claude; hoy hay una más reciente. Además se quiere tener un proveedor de respaldo.

## Decisión
- Tres niveles configurables en `.env`: `CLAUDE_DEFAULT_MODEL` (tareas estándar),
  `CLAUDE_PREMIUM_MODEL` (máxima calidad) y `CLAUDE_FAST_MODEL` (clasificación y tareas rápidas).
- Valores por defecto actuales: `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-5-5`.
- En la fase 5, una factoría de LLM con Claude como principal y respaldos opcionales
  (Azure OpenAI, OpenAI, Ollama), elegidos por tipo de tarea desde la base de datos.

## Alternativas
- **Modelo fijo en el código:** cada cambio exigiría desplegar.

## Consecuencias
- Cambiar de modelo es cambiar una variable o un registro, no código.
- Cada cambio de modelo se valida con las métricas de calidad (fase 7) antes de darlo por bueno.
