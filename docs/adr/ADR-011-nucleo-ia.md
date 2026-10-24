# ADR-011: Núcleo de IA: gobierno en el backend, pasarela sin estado en ai_service

**Fecha:** 2026-10-24 · **Estado:** Aceptado

## Contexto
La fase 5a construye la capa de IA de los capítulos 11 y 12: factoría de modelos con
reserva, prompts versionados, costes y presupuestos, guardarraíles, RAG sobre los
documentos y retorno de la inversión. Hay que decidir qué vive en el backend y qué en el
servicio de IA, cómo se protegen los documentos restringidos dentro de la búsqueda
semántica y qué modelo de embeddings se usa sin exigir otra clave de pago.

## Decisión

**Reparto de responsabilidades**
- **El backend gobierna.** Lee de MySQL el modelo de cada tarea (`llm_service_config`), la
  versión activa del prompt, la tabla de precios y los presupuestos. Registra en
  `llm_usage_log` **cada intento**, también los fallidos y los que respondió un modelo de
  reserva, con tokens, coste, latencia y hash del prompt. Ningún otro código llama al
  servicio de IA para generar texto (`app/ai/gateway.py`).
- **ai_service es una pasarela sin estado.** Recibe la cadena de modelos en cada petición,
  la recorre con un circuit breaker por proveedor (5 fallos en 30 s lo abren 120 s) y
  devuelve los intentos. También vectoriza y habla con Qdrant. No conoce usuarios ni
  precios: se puede escalar o reiniciar sin perder nada.

**Modelos (Claude 5.x)**
- El modelo de cada tarea se elige en Admin. Por defecto: Haiku 5.5 para catalogar
  documentos, reescribir preguntas y evaluar; Sonnet 5.5 para análisis GO/NO-GO y
  respuestas; Opus 5.5 para redactar propuestas. Cada uno con otro de reserva.
- Los modelos 5.x no admiten `temperature`: la profundidad se controla con `effort`
  (`low`, `medium`, `high`...). La columna `temperature` se conserva pero no se envía.
- **Salidas estructuradas** (`output_config.format` con esquema JSON) en todas las tareas
  que devuelven datos: el backend no interpreta texto libre.
- Las instrucciones estables van en el bloque de sistema con `cache_control` para
  aprovechar la caché de prompts; las variables, en el mensaje del usuario.
- Reserva externa opcional con API compatible con OpenAI (Azure OpenAI, OpenAI, Ollama).

**Embeddings**
- Por defecto, un modelo multilingüe **local** (`paraphrase-multilingual-MiniLM-L12-v2`,
  384 dimensiones, fastembed sobre ONNX en CPU) que se descarga al construir la imagen:
  sin clave, sin coste y sin enviar documentos fuera. Alternativa: Voyage AI con clave.
- El nombre físico de cada colección lleva la huella del modelo (`documents__<modelo>`):
  cambiar de modelo empieza con colecciones vacías y obliga a reindexar, en lugar de
  mezclar vectores incompatibles.

**RAG con control de acceso**
- Fragmentación en dos niveles: bloques padre (~2.400 caracteres) que respetan cláusulas,
  secciones o filas según el tipo de documento, y fragmentos hijo (~500) que son los que se
  vectorizan. Al modelo se le pasan los bloques padre leídos de MySQL.
- `documents.allowed_roles` restringe un documento a unos roles. La regla se aplica **tres
  veces**: en MySQL (listados y descargas), en el filtro de Qdrant (payload) y otra vez en
  el backend sobre los resultados, por si el payload aún no se ha actualizado.
- La IA solo recibe fragmentos que la persona puede abrir; si no hay fuentes, no se llama
  al modelo. El modelo debe citar y marcar `sufficient_context` cuando no le bastan.
- Una muestra de respuestas (5 %) se evalúa automáticamente con un modelo rápido.

**Gobierno y costes**
- Prompts versionados en BD con hash SHA-256; una tarea programada detecta cambios hechos
  fuera del versionado. Una versión nueva no puede perder variables que usa el código.
- Presupuestos global, por tarea y por persona con tres niveles: aviso (80 %), frenado
  (95 %) y bloqueo (100 %).
- ROI: cada tarea completada se compara con el tiempo de referencia de una persona
  (`human_baseline_config`, editable).
- RGPD: muestra de 500 caracteres de cada respuesta solo para buscar datos personales, que
  se borra a los 30 días; exportación y desvinculación de los datos de IA de una persona.
- Los campos que escriben los procesos en segundo plano (indexado, enriquecimiento, estado
  de una redacción) no cuentan como edición: no cambian `row_version`, así no chocan entre
  sí ni provocan un 409 a quien está editando.

## Alternativas
- **Gobierno en ai_service** (como algunos ejemplos del libro): obligaría a darle acceso a
  MySQL y a duplicar usuarios y permisos en dos servicios.
- **Embeddings de OpenAI** (los del libro): otra clave de pago y los documentos saldrían a
  un tercero solo para indexarlos.
- **Filtrar solo en Qdrant:** un cambio de permisos que no llegue a Qdrant dejaría ver
  fragmentos restringidos. El segundo filtro en el backend lo evita.

## Consecuencias
- La calidad de búsqueda del modelo local es menor que la de un modelo comercial grande;
  si se queda corto, se cambia a Voyage y se reindexa desde Admin.
- Haiku 5.5 cobra más por encima de 100.000 tokens de entrada; la tabla de precios usa el
  precio base, así que el coste de documentos muy largos con Haiku sale algo infravalorado.
- Cada documento subido hace una llamada a Haiku para catalogarlo (céntimos). Se puede
  desactivar con `AI_AUTO_ENRICH=false`.
