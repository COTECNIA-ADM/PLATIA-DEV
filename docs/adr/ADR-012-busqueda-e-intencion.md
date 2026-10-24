# ADR-012: Búsqueda con Meilisearch y clasificador de intención en dos capas

**Fecha:** 2026-10-24 · **Estado:** Aceptado

## Contexto
La fase 5b construye el capítulo 13: un buscador rápido de oportunidades, documentos y
clientes (con filtros, facetas y búsqueda mientras se escribe) y un asistente que recibe
una frase libre y decide qué hacer con ella. Hay que elegir el motor de búsqueda, cómo se
mantiene al día sin frenar la API, cómo se protegen los documentos restringidos y cómo se
clasifica la intención sin pagar una llamada al modelo por cada consulta.

## Decisión

**Motor: Meilisearch v1.54 (contenedor propio, solo en `data_net`)**
- Responde en milisegundos con tolerancia a erratas, sinónimos, palabras vacías en
  español, facetas y filtros numéricos. Un solo binario con 512 MB de memoria de
  indexado basta para millones de oportunidades.
- El backend usa la clave maestra: Meilisearch no se publica fuera de la red de datos y
  solo el backend y los workers lo ven. Crear claves con permisos reducidos añade
  gestión sin ganar aislamiento real en esta topología.
- Fechas como segundos Unix e importes como número (los filtros de rango son
  numéricos). Los códigos CPV se guardan con sus prefijos (2, 3, 4, 5 y 8 cifras): filtrar
  por `72` encuentra todos los servicios TI.

**MySQL es la fuente de verdad; el índice se puede tirar y reconstruir**
- Un evento de SQLAlchemy apunta en Redis (`search:dirty:<índice>`) el id de cada
  oportunidad, documento o cliente que cambia, **después** de confirmar la transacción.
  Una tarea Celery (cola `sync`) los envía en lotes a los pocos segundos y, por si acaso,
  cada minuto. Si Meilisearch está caído, los ids se quedan en Redis y no se pierde nada.
- Los cambios en segundo plano (`set_system_fields`) solo reindexan si tocan un campo
  indexado. Renombrar un cliente reindexa sus oportunidades.
- La reconstrucción llena un índice temporal y lo intercambia (`swap-indexes`): las
  búsquedas no se cortan. Cada 10 minutos se compara el recuento de MySQL con cada índice
  y se reconstruye el que no cuadra; así también se llenan la primera vez.

**Resultados siempre desde MySQL y con permisos dos veces**
- Meilisearch devuelve ids; el backend lee los registros de MySQL. Lo borrado después
  de indexar desaparece, y el formato es el del resto de la API.
- Los documentos llevan `allowed_roles` en el índice y la consulta se filtra por ellos;
  después, `Viewer.can_view` vuelve a comprobar cada resultado en MySQL (la misma regla
  que en el RAG de ADR-011).
- Los filtros se construyen como objetos (`app/search/filters.py`) y se escapan al
  convertirlos: un valor del usuario no puede cerrar la comilla y añadir
  `OR allowed_roles = "*"`.
- El resaltado se escapa como HTML antes de añadir `<mark>`: un título de un portal
  público no puede inyectar código en la interfaz.

**Búsqueda híbrida y plan B**
- Con `semantic=true`, Meilisearch filtra y ordena por texto y los primeros 50 se
  reordenan por similitud de embeddings (los mismos de ADR-011, vía `ai_service`):
  `puntuación = (1 − w) · texto + w · significado`, con `w = SEARCH_RERANK_WEIGHT`.
- Si Meilisearch no responde, oportunidades y documentos se buscan en MySQL con los mismos
  filtros (más lento y sin facetas). La salud lo marca como **Aviso**, no como error.

**Clasificador de intención en dos capas**
- Cuatro intenciones: `CHAT_RAG`, `AGENT_TOOLS` (buscar), `WORKFLOW` (analizar,
  redactar, resumir) y `OFF_TOPIC`.
- **Capa 1**: expresiones regulares guardadas en `intent_patterns`, editables en Admin y
  en caché 5 minutos. Se aplican al texto en minúsculas, sin tildes y con un máximo de 500
  caracteres. Dos coincidencias de la misma intención dan 0,92 de confianza; una, 0,78;
  un empate, 0,6. Se rechazan patrones con cuantificadores anidados (ReDoS).
- **Capa 2**: solo si la capa 1 no llega a 0,75. La frase pasa por los guardarraíles y la
  clasifica Haiku 5.5 por la pasarela (`intent_classification`, prompt `intent.classify`)
  con salida estructurada que también propone filtros.
- **Plan B**: si el modelo falla o duda (< 0,5), la mejor suposición de la capa 1 o
  `CHAT_RAG`, que nunca cambia datos.
- Los filtros de una búsqueda se sacan de la frase con un extractor propio en español
  ("más de 100.000 euros", "que cierran este mes", "publicadas esta semana"); la capa 2
  completa lo que falte.
- **Los encargos nunca se ejecutan solos.** Un `WORKFLOW` devuelve la acción propuesta y
  la ruta para confirmarla; la persona pulsa. Analizar o redactar cuesta dinero y crea
  datos (el agente de la fase 5c seguirá la misma regla).
- Cada consulta queda en `search_query_log` (texto sin datos personales, capa,
  confianza, reformulación en 30 s, primer clic, valoración, intención esperada). Admin
  muestra la calidad y avisa si la capa 1 resuelve menos del 70 % o más del 95 %.

## Alternativas descartadas
- **MySQL FULLTEXT**: sin tolerancia a erratas, sinónimos ni facetas, y con el parser de
  español limitado. Se queda solo como plan B.
- **Elasticsearch / OpenSearch**: más potente, pero pide varios GB de memoria y operación
  propia. Sobra para este volumen.
- **Solo búsqueda vectorial (Qdrant)**: no es buena con códigos de expediente, CPV,
  importes ni fechas. Se combina con ella en el reordenado.
- **Clasificar siempre con el modelo**: cientos de milisegundos y un coste por consulta,
  cuando la mayoría de frases encajan en patrones conocidos.
- **Escribir en Meilisearch dentro de la petición**: acopla la API a la disponibilidad del
  buscador y deja índices a medias si la transacción se deshace.

## Consecuencias
- Un contenedor más (11). `MEILI_MASTER_KEY` va en `.env`
  (`python scripts/generate_env.py --actualizar` la añade).
- Un modelo nuevo que deba buscarse se registra en `app/search/indexes.py`; la
  sincronización es automática.
- El índice puede ir unos segundos por detrás de MySQL; por eso los resultados se releen
  de MySQL y los permisos se vuelven a comprobar.
