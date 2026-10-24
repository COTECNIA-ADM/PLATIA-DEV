# ADR-010: Backend de negocio por dominios, contrato de API común y colas Celery segmentadas

**Fecha:** 2026-10-24 · **Estado:** Aceptado

## Contexto
La fase 4 construye las APIs de negocio del caso B2B (clientes, oportunidades, documentos,
propuestas, talento, notificaciones) y el procesamiento asíncrono (capítulos 7 a 9). Hay que
decidir cómo se organizan los módulos, qué contrato comparten y cómo se reparten las tareas
en segundo plano, sin adelantar lo que depende de la IA (fase 5) ni de la RPA (posterior).

## Decisión

**API**
- Un blueprint por dominio en `backend/app/routes/` y la lógica de dominio en
  `backend/app/services/`. Las rutas solo hacen HTTP, permisos y serialización.
- **Tres capas explícitas en cada endpoint**: `@platform_guard`, `@require_permission` y
  `@rate_limit`, con límites distintos por tipo de operación: lectura 60/min, escritura
  20/min, subida 10/min, exportación 5/min (el libro propone 10/min para escritura; se
  sube a 20 porque editar una propuesta sección a sección lo supera con facilidad).
- **Registro de permisos** (`security/registry.py`): `require_permission` falla al importar
  si el módulo o la acción no existen, y un test comprueba que los roles sembrados solo usan
  permisos registrados. Evita el fallo del capítulo 7 (un endpoint protegido con el módulo
  equivocado).
- **Autorización por objeto**: escribir en un módulo no basta para modificar cualquier
  registro. Oportunidades, documentos y propuestas solo los modifica su responsable o quien
  tenga la acción `manage` (gestor). Reasignar también exige `manage`.
- **Validación con Pydantic** y `extra="forbid"`: los campos desconocidos se rechazan, y las
  estructuras anidadas (secciones de plantilla, habilidades, CPV) se validan enteras.
- **Bloqueo optimista**: columna `row_version` (`version_id_col` de SQLAlchemy). Cada recurso
  devuelve `version` y hay que enviarla al modificarlo; si no coincide, 409.
- **Contrato común**: listados `{"items", "pagination"}` con máximo 100 por página, fechas
  ISO UTC con `Z`, errores `{"error", "type"}`. Los 500 nunca devuelven detalles internos.
- Búsquedas `LIKE` con los comodines del usuario escapados y longitud limitada.
- Exportación CSV en streaming, con protección contra inyección de fórmulas.

**Colas (capítulo 8)**
- Siete colas (`default`, `priority`, `ai`, `documents`, `sync`, `crm`, `automation`) con
  routing centralizado en `app/queue.py`: el código que encola no elige la cola.
- Tres contenedores: `celery_default` (priority, default, sync, crm), `celery_ai` (ai,
  documents) y `celery_beat`. `celery_automation` llegará con la RPA.
- JSON como serializador, `acks_late` y `reject_on_worker_lost`; por eso las tareas son
  idempotentes y las que no deben solaparse usan un bloqueo en Redis (`task_lock`).
- Reintentos con backoff exponencial y jitter del 25 %. Al agotarlos, la tarea va a la
  **dead-letter queue** en MySQL (`failed_tasks`), visible y reencolable desde Admin. Solo se
  reencolan nombres de tarea propios (`tasks.*`).
- Prioridad dentro de cada cola: 3 si una persona espera, 7 programadas, 9 mantenimiento.
- Si el broker no responde al encolar, la petición no falla: la tarea programada
  `recover_pending` relanza los documentos pendientes cada 15 minutos.

**Servicios de negocio (capítulo 9)**
- Oportunidades: máquina de 12 estados en 5 fases; descartar o perder exige motivo.
- Propuestas: máquina de estados por tipo. `approved` solo se alcanza con revisiones
  (premium y ejecutiva: técnica + ejecutiva; custom: responsable de área; base y competitiva:
  una). Cuatro ojos: el responsable no revisa su propia propuesta (salvo un administrador).
  Las competitivas necesitan un análisis de competencia adjunto antes de revisión. Al
  aprobarse se genera el paquete en segundo plano y se avisa al responsable. Los cambios de
  la propuesta mueven la oportunidad en el embudo si la transición es válida.
- Relevancia de oportunidades (0-10) contra las líneas del portfolio: texto 50 %,
  taxonomía CPV 30 %, histórico de éxito 20 %, como en el libro. Hasta la fase 5 la parte
  «semántica» se calcula con palabras clave; después se sustituye por similitud en Qdrant.
- Ingesta de feeds ATOM con `defusedxml` (sin XXE), deduplicación por `source` +
  `external_id` y hash de contenido. Entiende la extensión CODICE de los feeds públicos
  españoles (CPV, importe, órgano y plazo).
- Notificaciones tipadas con enlace profundo y deduplicación (no se repite un aviso sin leer
  del mismo tipo sobre el mismo recurso).

## Alternativas descartadas
- **Generación en bloque de todos los blueprints**: se ha seguido el ciclo del capítulo 7
  (patrón de referencia en clientes, revisión, y después el resto).
- **Fijar la versión con `updated_at`**: MySQL guarda segundos, dos ediciones en el mismo
  segundo no se detectarían.
- **Swagger/OpenAPI**: como en el libro, el contrato lo darán los tipos TypeScript del
  frontal (fase 6). La guía de endpoints está en `docs/api.md`.

## Consecuencias
- Cualquier cliente de la API debe guardar `version` y reenviarla al modificar.
- El paquete de propuesta es solo DOCX en esta fase; PDF y PPTX llegan con la generación
  de documentos de la fase 5. El análisis con IA de documentos, también en la fase 5.
- El correo de las notificaciones de prioridad alta queda para la fase 8 (no hay SMTP).
- Beat no es de alta disponibilidad (una instancia); `celery-redbeat` queda pendiente, igual
  que en el libro.
