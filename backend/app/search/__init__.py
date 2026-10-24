"""Búsqueda textual con Meilisearch y clasificador de intención (Capítulo 13).

- ``client``: cliente HTTP de Meilisearch (solo el backend y los workers lo usan).
- ``filters``: filtros como objetos, nunca texto concatenado (evita la inyección de filtros).
- ``indexes``: qué se indexa de cada tabla y con qué configuración.
- ``sync``: sincronización automática MySQL -> Meilisearch y reconstrucción sin cortes.
- ``engine``: búsquedas con permisos, facetas, resaltado y reordenación semántica.
- ``extract``: filtros (importes, plazos, estado) a partir de una frase en español.
- ``intent``: clasificador de intención en dos capas (patrones y modelo rápido).
- ``router``: decide qué motor responde a cada consulta del asistente.
"""
