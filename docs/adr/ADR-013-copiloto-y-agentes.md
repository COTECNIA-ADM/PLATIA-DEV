# ADR-013: Copiloto con agentes en el backend, aprobación humana y memoria editable

**Fecha:** 2026-10-24 · **Estado:** Aceptado

## Contexto
La fase 5c construye los capítulos 14 y 15: un copiloto conversacional que responde
mientras escribe, consulta la plataforma con herramientas y prepara trabajo (análisis,
propuestas, CV a medida, paquete en PDF y PowerPoint), más un estudio para configurar y
probar agentes. Hay que decidir dónde vive el bucle del agente, qué puede hacer sin
preguntar, cómo se para a pedir permiso sin perder el hilo, qué recuerda de cada persona y
cómo se sirve el streaming con el backend actual.

## Decisión

**El bucle del agente vive en el backend; `ai_service` sigue siendo una pasarela sin estado**
- El agente necesita permisos, datos y auditoría, y eso está en el backend (ADR-011).
  `ai_service` solo añade `/v1/stream` (eventos `delta`, `final`, `error`) y acepta
  `tools` y bloques de contenido; no ejecuta nada.
- Cada turno del modelo pasa por `gateway.converse(...)`: mismos presupuestos, prompt
  activo, modelo de reserva y registro de tokens, coste y latencia que el resto de la IA.
- Los bloques de razonamiento (`thinking`) se reenvían tal cual dentro de una ejecución.

**Catálogo cerrado de herramientas (`app/agents/tools.py`)**
- 14 herramientas que llaman a los servicios de negocio, nunca a la base de datos por su
  cuenta: 8 de lectura (oportunidades, documentos, clientes, perfiles sin correo,
  propuestas y plantillas) y 6 que cambian cosas (analizar, crear y redactar propuestas,
  CV a medida y exportar el paquete).
- Diferencia con el libro: **no hay herramientas de terminal ni de ficheros**. Un agente de
  negocio no las necesita y serían la vía más directa para un ataque por inyección.
- Esquemas estrictos (`strict`, `additionalProperties: false`): el modelo no puede
  inventar campos. Cada resultado se recorta a 12.000 caracteres.
- Cada herramienta declara su nivel mínimo (`auto`, `notify`, `approve`). En el estudio se
  puede subir, nunca bajar. Máximo 12 herramientas por agente.

**Permisos del usuario, no del agente**
- El agente actúa como la persona (`Actor`): rol de la aplicación `operations` leído de
  la BD. Las herramientas que su rol no permite ni se le ofrecen al modelo, y se vuelve a
  comprobar el permiso al ejecutarlas. Los documentos pasan por `Viewer` como en el RAG.

**Aprobación humana con estado guardado**
- Las herramientas `approve` paran la ejecución: los mensajes, los resultados y las
  acciones pendientes se guardan en `agent_runs` con caducidad de 15 minutos y la
  interfaz recibe `approval_required`.
- `POST /copilot/runs/{id}/approval` reclama la ejecución con un `UPDATE` atómico
  (`awaiting_approval → running`): dos clics no la ejecutan dos veces (409).
- Un rechazo vuelve al modelo como resultado de error, para que lo explique o proponga
  otra cosa. Un mensaje nuevo cancela lo pendiente de esa conversación. Cada cinco
  minutos se marcan como caducadas las que nadie contestó.

**Límites por agente**
- Iteraciones (10), llamadas a herramientas (15) y tiempo (180 s), configurables en el
  estudio. Al llegar a uno se para con `stop_reason` y se avisa a la persona.

**Chat por SSE con historial resumido**
- `POST /copilot/conversations/{id}/messages` responde con `text/event-stream`. Antes de
  abrir el stream se aplican los guardarraíles a la entrada (422 si se bloquea).
- La intención (ADR-012) decide el camino: `OFF_TOPIC` responde sin modelo, `CHAT_RAG`
  usa el RAG con citas y el resto va al agente. Los flujos de análisis o redacción eligen
  el agente especializado. `@oportunidad:<id>` y similares añaden la referencia al
  contexto (solo si la persona puede verla).
- La salida se revisa con `guardrails.check_output` a medida que llega: si hay que
  ocultar algo, el evento `replace` sustituye el texto ya enviado.
- Se envían enteros los últimos 10 turnos; los anteriores se resumen con Haiku en
  segundo plano (`chat_summary`).
- **Regla del streaming**: Flask cierra la sesión de SQLAlchemy al devolver la respuesta,
  antes de que empiece a enviarse el cuerpo. Por eso la vista solo comprueba y pasa ids,
  y el generador vuelve a cargar los registros. Si no, los cambios se pierden.
- Gunicorn pasa a `gthread` (2 procesos × 8 hilos, 300 s): un chat abierto ocupa un
  hilo, no un proceso entero. Nginx no almacena el stream (`X-Accel-Buffering: no`).

**Memoria por persona, visible y borrable**
- Tras cada dos intercambios, Haiku extrae como mucho 3 hechos útiles (preferencias,
  contexto, forma de trabajar), sin datos personales (se ocultan antes de guardar) y sin
  repetir (hash del contenido). Máximo 50 por persona.
- Se inyectan los 10 mejores según `0,6 × recencia (vida media de 30 días) + 0,4 ×
  frecuencia de uso (log)`.
- La persona los ve, corrige y borra (`/copilot/memories`), y puede exportar todo lo suyo.
  El borrado RGPD de Admin elimina conversaciones y memoria y anonimiza las ejecuciones.

**Agent Studio (`/api/admin/agents`)**
- Agentes en BD con versión y bloqueo optimista. Cada cambio guarda una instantánea que
  se puede restaurar. Su prompt es `agent.<slug>` (versionado como el resto).
- Pruebas en modo `sandbox`: las herramientas `approve` se simulan en lugar de ejecutarse.
  Métricas por agente con umbrales de alerta: finalización, errores, límite de
  iteraciones, rechazos de aprobación y coste medio.
- Se siembran tres agentes: `copiloto` (generalista), `analista_documental` y
  `preparador_propuestas`.

**CV a medida y paquete completo**
- El CV a medida solo puede usar habilidades que están en el perfil, y las experiencias
  se eligen por índice. Empresa y fechas salen de la BD, no del modelo. Se guarda en
  DOCX y PDF como adjunto `cv` de la propuesta.
- El paquete de una propuesta aprobada incluye DOCX, PDF (reportlab) y PPTX
  (python-pptx). Las diapositivas las resume Haiku con un esquema fijo; si falla, se
  generan a partir de las secciones.

## Alternativas descartadas
- **Bucle del agente en `ai_service`**: duplicaría permisos y acceso a datos en un
  servicio que no debe tocar MySQL.
- **Herramientas genéricas (SQL, terminal, ficheros)**: demasiado poder para lo que
  aporta. Un catálogo cerrado se audita y se prueba.
- **WebSockets**: el chat es unidireccional mientras responde y SSE pasa por Nginx y
  proxies corporativos sin configuración extra.
- **Aprobación bloqueando la petición**: con 15 minutos de margen y personas que se van a
  comer, guardar el estado y retomarlo es lo único fiable.
- **Memoria como embeddings en Qdrant**: con 50 recuerdos por persona, una puntuación
  simple en MySQL basta y es fácil de enseñar y borrar.

## Consecuencias
- Un agente nunca puede más que la persona que lo usa, y nada que cambie datos ocurre sin
  un clic suyo: el nivel mínimo de cada herramienta impide quitarle la aprobación.
- Cada iteración del agente es una llamada registrada: el coste y la latencia del copiloto
  se ven en el mismo panel que el resto de la IA.
- Añadir una herramienta exige código (`tools.py`) y un test; configurarla en un agente,
  no.
