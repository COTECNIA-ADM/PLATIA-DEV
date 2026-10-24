"""Capa de IA del backend (Capítulos 11-12, ADR-011).

El backend es el dueño de la gobernanza: qué modelo usa cada tarea, qué versión
de prompt, cuánto se puede gastar y el registro de cada llamada con su coste.
El servicio ``ai_service`` es la pasarela técnica hacia los proveedores de LLM,
el modelo de embeddings y Qdrant.
"""
