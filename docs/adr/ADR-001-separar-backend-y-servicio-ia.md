# ADR-001: Backend Flask y servicio de IA FastAPI separados

**Fecha:** 2026-10-23 · **Estado:** Aceptado

## Contexto
El backend reunirá unos 22 módulos de negocio con autorización por rol, y sus peticiones
responden en milisegundos. Las llamadas a Claude tardan de 2 a 60 segundos, consumen más
memoria, necesitan streaming y deben gestionar los límites de tasa del proveedor.

## Decisión
- Backend de negocio en **Flask 3** con un blueprint por módulo.
- Servicio de IA en **FastAPI + Uvicorn**, con async nativo para streaming SSE.
- Comunicación interna por HTTP con `X-API-Key`. El servicio de IA no se publica fuera.

## Alternativas
- **FastAPI para todo:** viable, pero complica un backend que es síncrono por naturaleza.
- **Flask para todo:** el streaming y la concurrencia de peticiones largas exigen parches (gevent).
- **Django:** sus convenciones chocan con los tres esquemas y con la autenticación multi-aplicación.

## Consecuencias
- Cada servicio usa el framework en su terreno natural y escala por separado.
- Hay dos imágenes que construir y mantener: complejidad asumida.
