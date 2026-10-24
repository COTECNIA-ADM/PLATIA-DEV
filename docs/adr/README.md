# Registros de decisiones de arquitectura (ADR)

Cada ADR cuenta en menos de una página qué se decidió, por qué y qué alternativas se
descartaron, para que dentro de seis meses no haya que reconstruirlo de memoria.
Para proponer un cambio, se escribe un ADR nuevo que sustituya al anterior.

| ADR | Decisión | Estado |
| --- | --- | --- |
| [001](ADR-001-separar-backend-y-servicio-ia.md) | Backend Flask y servicio de IA FastAPI separados | Aceptado |
| [002](ADR-002-mysql-tres-esquemas.md) | MySQL 8.0 con tres esquemas | Aceptado |
| [003](ADR-003-qdrant-self-hosted.md) | Qdrant alojado por nosotros como base vectorial | Aceptado |
| [004](ADR-004-operaciones-ia-asincronas.md) | Operaciones de IA asíncronas con Celery; SSE solo para lo interactivo | Aceptado |
| [005](ADR-005-redes-minimo-privilegio.md) | Redes Docker con mínimo privilegio | Aceptado |
| [006](ADR-006-crecimiento-incremental.md) | Empezar con 8 contenedores y crecer con motivos concretos | Aceptado |
| [007](ADR-007-modelos-configurables.md) | Modelos y proveedores de LLM configurables | Aceptado |
| [008](ADR-008-migraciones-multi-bind.md) | Modelos y migraciones en tres esquemas | Aceptado |
| [009](ADR-009-seguridad-iam.md) | JWT con refresco rotatorio, MFA TOTP y roles por aplicación verificados en BD | Aceptado |
| [010](ADR-010-backend-negocio-y-colas.md) | Backend de negocio por dominios, contrato de API común y colas Celery segmentadas | Aceptado |
| [011](ADR-011-nucleo-ia.md) | Núcleo de IA: gobierno en el backend, pasarela sin estado, embeddings locales y RAG con control de acceso | Aceptado |
| [012](ADR-012-busqueda-e-intencion.md) | Búsqueda con Meilisearch sincronizada desde MySQL y clasificador de intención en dos capas | Aceptado |
| [013](ADR-013-copiloto-y-agentes.md) | Copiloto con agentes en el backend, catálogo cerrado de herramientas, aprobación humana y memoria editable | Aceptado |
| [014](ADR-014-frontal-operaciones.md) | Frontal de operaciones con sesión en memoria, React Query y permisos desde `/me` | Aceptado |
| [015](ADR-015-analitica-y-administracion.md) | Analítica y administración como tres aplicaciones en un solo frontal, con historial de estados | Aceptado |
