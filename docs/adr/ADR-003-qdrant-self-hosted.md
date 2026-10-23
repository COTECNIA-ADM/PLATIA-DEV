# ADR-003: Qdrant alojado por nosotros como base vectorial

**Fecha:** 2026-10-23 · **Estado:** Aceptado

## Contexto
La búsqueda semántica (documentos similares, CV, RAG del chat) trabajará con propuestas,
currículos y datos de clientes, que no deben salir del perímetro de la organización.
Migrar millones de vectores después es caro, así que la elección debe ser estable.

## Decisión
**Qdrant** en contenedor propio, con API key, una colección por tipo de contenido.

## Alternativas
- **Pinecone:** sin operación, pero los datos quedan en un tercero y el coste crece con el volumen.
- **Weaviate:** válido, con menos documentación de rendimiento para este volumen.
- **pgvector:** exigiría PostgreSQL (ver ADR-002).

## Consecuencias
- Los datos se quedan en nuestra infraestructura; hay que darle memoria y disco propios.
- Los embeddings los genera un proveedor externo (OpenAI, Azure) o un modelo local (Ollama), configurable.
