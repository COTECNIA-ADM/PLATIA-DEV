# ADR-004: Operaciones de IA asíncronas con Celery; SSE solo para lo interactivo

**Fecha:** 2026-10-23 · **Estado:** Aceptado

## Contexto
Analizar un documento de 200 páginas puede tardar más de un minuto, y generar una propuesta,
bastante más. Si la API espera esas respuestas, todo parece lento para todos los usuarios.

## Decisión
- Las operaciones largas (análisis, propuestas, vectorización) se **encolan en Celery** con
  Redis. La API responde `202 Accepted` con un `task_id` y el frontal consulta el estado.
- El resultado de cada análisis se **guarda como un registro propio**, que otros flujos
  (GO/NO-GO, similares) leen sin repetir la llamada a Claude.
- Solo el chat y otras interacciones en vivo usan **streaming SSE** desde `ai_service`.
- Colas separadas por tipo: `default`, `documents` y `ai` (después, `automation` y `priority`).

## Alternativas
- **Llamadas síncronas:** simples, pero bloquean workers de la API y caen por timeout.
- **RQ o Dramatiq:** más ligeras, pero Celery aporta Beat, Flower y madurez.

## Consecuencias
- El frontal tiene que gestionar estados de tarea (pendiente, en curso, completada, fallida).
- Hace falta tolerancia a fallos: reintentos con espera exponencial y tareas idempotentes.
