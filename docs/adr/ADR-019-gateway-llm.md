# ADR-019: Llamar a Claude a través del gateway LLM corporativo

**Fecha:** 2026-10-31 · **Estado:** Aceptado

## Contexto
La empresa ha montado un gateway LLM propio (repositorio `cotecnia-adm/platia-gateway`):
una sola puerta hacia los modelos para todas las aplicaciones internas, con claves por
aplicación, auditoría de cada llamada, precios por modelo y, en fases siguientes, cuotas,
presupuestos y reserva entre proveedores. PLATIA es la primera aplicación que se conecta.

Hasta ahora `ai_service` llamaba directamente a Anthropic con `ANTHROPIC_API_KEY` y, si
fallaba, a un proveedor compatible con OpenAI. El backend ya registra el uso de cada tarea
en `llm_usage_log` y aplica presupuestos por tarea (ADR-011); eso no cambia.

## Decisión

**Un interruptor, sin cambiar el código de negocio**
- Con `LLM_GATEWAY_ENABLED=true`, el cliente de Anthropic de `ai_service` apunta a
  `LLM_GATEWAY_URL` y se autentica con `LLM_GATEWAY_API_KEY` (clave `plgw-app-platia-…`).
  El gateway habla el mismo contrato que Anthropic, así que el SDK, el streaming y los
  modelos se usan igual. Con `false` todo sigue como antes: la vuelta atrás es cambiar la
  variable y rearrancar `ai_service`.
- La clave de Anthropic deja de estar en PLATIA: la guarda cifrada el gateway.

**Red compartida solo para el servicio de IA**
- El gateway crea la red `platia_llm_net` y responde en ella como `platia-gateway`.
  `docker-compose.gateway.yml` añade esa red solo a `ai_service`; el backend, los workers y
  los datos no la ven (ADR-005). `deploy.sh` y `restore.sh` añaden el fichero cuando el
  `.env` tiene el gateway activo.

**El gateway sabe qué tarea y qué persona hay detrás de cada llamada**
- `ai_service` envía `X-Platia-Purpose` con el tipo de tarea (`document_summary`,
  `copilot`…), `X-Platia-User-Id` con el id de la persona (el backend lo pasa como
  `user_ref`) y `X-Request-ID` con el `correlation_id` de la llamada. Con ese id se cruza
  una fila de `llm_usage_log` con la auditoría del gateway para comparar costes.
- La aplicación `platia` del gateway es de confianza (puede declarar la persona) y admite
  cualquier propósito (`*`): la lista de tareas la gobierna PLATIA.

**Fallar cerrado**
- Con el gateway activo, el proveedor de reserva directo (`FALLBACK_LLM_*`) se desactiva:
  si el gateway no responde, la llamada falla con `connection` y el backend lo trata como
  hoy. Saltarse el gateway rompería la auditoría y los presupuestos centrales. La reserva
  entre proveedores pasa a ser cosa del gateway (fase G6).
- `/health` de `ai_service` comprueba la clave del gateway en lugar de la de Anthropic.

## Consecuencias
- Un salto de red más (milisegundos) en cada llamada a Claude.
- Dos registros de uso con el mismo `correlation_id`: el de PLATIA (por tarea y negocio) y
  el del gateway (por aplicación, persona y proveedor). Deben coincidir en tokens; el coste
  puede diferir si los precios de las dos tablas no se mantienen iguales.
- Los embeddings no pasan por el gateway: siguen siendo locales o de Voyage.
