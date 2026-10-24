# Plan por fases

| # | Fase | Qué se construye | Capítulos del libro | Estado |
| --- | --- | --- | --- | --- |
| 0 | Preparación y núcleo | Estructura, `.env`, docker-compose de 8 contenedores, health checks | 1–3, Ap. F | Hecha |
| 1 | Requisitos y arquitectura | `docs/requisitos.md`, `docs/arquitectura.md` y `docs/adr/` | 4 | Hecha |
| 2 | Base de datos | Modelos SQLAlchemy en 3 esquemas, Alembic, borrado lógico y auditoría | 5, Ap. A | Hecha |
| 3 | Seguridad e IAM | JWT con refresh, MFA, roles por aplicación, cabeceras OWASP, rate limiting | 6 | Hecha |
| 4 | Backend | Blueprints de negocio, colas Celery, tareas programadas, servicios de negocio | 7–10, Ap. B | Hecha |
| 5a | Núcleo de IA | Factoría con reserva, prompts en BD, costes y presupuestos, guardarraíles, RAG con control de acceso, análisis GO/NO-GO, redacción de propuestas, ROI | 9–12, Ap. C y E | Hecha |
| 5b | Búsqueda e intención | Meilisearch (búsqueda de texto) y clasificador de intención con Haiku | 13 | Hecha |
| 5c | Copiloto | Agente con herramientas, chat con streaming (SSE), CV a medida, PDF y PPTX del paquete de propuesta | 14–15 | Hecha |
| 6a | Frontend de operaciones | App principal: oportunidades, documentos, propuestas, copiloto, búsqueda, clientes, talento y avisos | 16–17 | Hecha |
| 6b | Frontend de analytics y admin | Paneles de analítica y administración | 16–17 | Hecha |
| 7 | Testing y calidad | Tests de integración, seguridad y calidad de IA | 18–20 | Pendiente |
| 8 | Despliegue y operación | CI/CD con imágenes en GHCR y despliegue aprobado con vuelta atrás, `docker-compose.prod.yml`, HTTPS, Flower, copias de seguridad, avisos por correo, marcado de contenido IA | 21–22, Ap. D | Hecha |
| 9a | Inteligencia comercial | Mapa de oportunidad con pesos, comparación con el periodo anterior y fotos de cartera, objetivos, competidores con DAFO, importación desde Excel y «Pregunta a tus datos» | 23 | En revisión |
| 9b | Documentación | Manual de usuario, guía de incidencias, borrador de DPIA y comprobación automática de `docs/api.md` | 24 | Pendiente |

## Del núcleo mínimo a los 17 servicios del libro

Ya están: `celery_default`, `celery_ai` y `celery_beat` (fase 4). Se añadirán cuando la
fase lo necesite: Meilisearch, `celery_automation`, frontales de analytics y
admin, y Selenium Grid con 3 nodos de Chrome en una red `rpa_net` aislada.

## Diferencias deliberadas con el libro

- Una sola instancia de MySQL con 3 esquemas (el libro usa 3 instancias en producción).
- Modelos de Claude actualizados a la generación vigente (`claude-sonnet-5-5`,
  `claude-opus-5-5`, `claude-haiku-5-5`); el de cada tarea se cambia en Admin.
- Embeddings con un modelo multilingüe local en lugar de los de OpenAI (ADR-011): sin
  otra clave de pago y sin enviar los documentos a un tercero para indexarlos.
- Los prompts iniciales son de redacción propia, con la estructura del Apéndice E.
- Los agentes no tienen herramientas de terminal ni de ficheros: solo un catálogo cerrado
  que llama a los servicios de negocio (ADR-013).
- Mapa de oportunidad con puntuaciones relativas (100 = mejor cruce del mes), importación
  de Excel síncrona con límites en lugar de una tarea en segundo plano, y «Pregunta a tus
  datos» sobre un resumen calculado, sin texto a SQL (ADR-017).

## Qué queda de los capítulos 7–10 para fases posteriores

- Análisis de documentos con IA, generación de secciones y similitud semántica en la
  puntuación de oportunidades: hechos en la fase 5a.
- Clasificación de intención con Haiku: hecha en la fase 5b. CV a medida y PDF/PPTX del paquete de
  propuesta: hechos en la fase 5c.
- Correo de notificaciones de prioridad alta: fase 8 (SMTP).
- Integración con CRM (OAuth2) y bots RPA con Selenium (capítulo 10): cuando haya un CRM y
  un portal reales contra los que probar; las colas `crm` y `automation` ya existen.
