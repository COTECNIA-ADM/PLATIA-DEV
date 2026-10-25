# API de la plataforma

Todas las rutas cuelgan de `http://localhost:8080/api` y exigen sesión
(`Authorization: Bearer <token>`). La aplicación activa va en `X-App-Code`
(por defecto `operations`; las rutas de `/admin` necesitan `admin`). Decisiones en
[ADR-010](adr/ADR-010-backend-negocio-y-colas.md).

## Contrato común

| Tema | Regla |
| --- | --- |
| Listados | `{"items": [...], "pagination": {"page", "per_page", "total", "pages"}}`; `?page=` y `?per_page=` (máx. 100) |
| Fechas | ISO 8601 en UTC con `Z` (`2026-11-15T13:00:00Z`) |
| Importes | Texto con dos decimales (`"180000.00"`) |
| Modificar | `PATCH` con solo los campos que cambian **y** `version` (la que leíste). Si otra persona guardó antes: 409 |
| Errores | `{"error": "mensaje", "type": "validation|conflict|business_rule|forbidden|not_found"}`; en validación, `fields` |
| Borrado | Lógico (el registro deja de verse, no se destruye) |

Límites por usuario y minuto: lectura 60, escritura 20, subida 10, exportación 5, búsqueda
120 e IA 10 (429 con `Retry-After`). `search_unavailable` (503) aparece solo si el buscador
no responde y el plan B en MySQL está desactivado. Los errores de IA añaden los tipos `ai_unavailable` (503),
`ai_disabled` (503), `ai_rejected` (422), `guardrail` (422) y `budget_exceeded` (429).

## Recursos

Esta tabla la comprueba `backend/tests/test_api_docs.py`: toda ruta de Flask tiene que
estar aquí y todo lo que está aquí tiene que existir. Notación: `GET/POST /ruta` (varios
métodos), `[/{id}]` (tramo opcional) y rutas sin el prefijo `/api`.

| Módulo | Rutas principales | Permiso |
| --- | --- | --- |
| Sesión | `POST /auth/login` (`email`, `password`; con MFA devuelve `mfa_token`), `POST /auth/mfa/verify` (`mfa_token`, `code`), `POST /auth/refresh` (cookie de refresco), `POST /auth/logout`, `GET /auth/me` (persona, aplicaciones, permisos y ajustes), `POST /auth/password` (`current_password`, `new_password`), `POST /auth/mfa/setup`, `POST /auth/mfa/enable` (`code`), `POST /auth/mfa/disable` (`password`, `code`). Detalle en [seguridad.md](seguridad.md) | Sesión iniciada (salvo `login`, `mfa/verify` y `refresh`) |
| Salud | `GET /health` (base de datos y Redis; sin sesión, para el balanceador), `GET /health/full` (todos los servicios) | — / `health.read` |
| Clientes | `GET/POST /clients`, `GET/PATCH/DELETE /clients/{id}`, `POST/PATCH/DELETE /clients/{id}/contacts[/{cid}]`, `POST/PATCH/DELETE /clients/{id}/projects[/{pid}]` | `clients` |
| Oportunidades | `GET/POST /opportunities` (filtros `status`, `phase=F1..F5`, `owner=me`, `client_id`, `service_line`, `min_score`, `deadline_from/to`, `q`, `sort`), `GET/PATCH/DELETE /opportunities/{id}`, `POST /opportunities/{id}/status`, `POST /opportunities/{id}/score`, `POST/DELETE /opportunities/{id}/documents[/{doc}]`, `GET /opportunities/export` | `opportunities` |
| Documentos | `GET/POST /documents` (multipart: `file`, `title`, `doc_type`), `GET/PATCH/DELETE /documents/{id}`, `GET /documents/{id}/status`, `GET /documents/{id}/download`, `POST /documents/{id}/versions`, `POST /documents/{id}/reprocess` | `documents` |
| Propuestas | `GET/POST /proposals`, `GET/PATCH/DELETE /proposals/{id}`, `POST /proposals/{id}/status`, `POST /proposals/{id}/reviews`, `POST /proposals/{id}/package`, `POST/PATCH/DELETE /proposals/{id}/sections[/{sid}]`, `POST /proposals/{id}/attachments` (multipart: `file`, `kind`), `GET/DELETE /proposals/{id}/attachments/{aid}` | `proposals` |
| Plantillas | `GET/POST /proposal-templates`, `GET/PATCH/DELETE /proposal-templates/{id}` | `templates` |
| Portfolio | `GET/POST /portfolio/service-lines`, `PATCH /portfolio/service-lines/{id}` | `portfolio` |
| Talento | `GET/POST /talent/profiles` (filtros `family`, `seniority`, `skill`, `available`, `q`), `GET/PATCH/DELETE /talent/profiles/{id}` | `talent` |
| Notificaciones | `GET /notifications` (`unread=true`, `type`), `GET /notifications/unread-count`, `POST /notifications/{id}/read`, `POST /notifications/read-all` | `notifications` |
| Alertas | `GET /alerts` (`open=true`), `POST /alerts/{id}/resolve` | `alerts` |
| IA | `POST /ai/ask` (`question`, `document_ids`, `history`), `POST /ai/search` (`query`, `limit`, `document_ids`, `doc_types`), `POST /ai/feedback` (`usage_log_id`, `rating` 1-5), `GET /ai/analyses/{id}` | `documents.read` + módulo de IA |
| IA en documentos | `POST/GET /documents/{id}/analysis` (GO/NO-GO), `POST /documents/{id}/reindex`; `PATCH /documents/{id}` admite `allowed_roles` | `documents` |
| IA en oportunidades | `POST/GET /opportunities/{id}/analysis`, `GET /opportunities/{id}/similar` (`only_open=true`) | `opportunities` |
| IA en propuestas | `POST /proposals/{id}/generate` (`sections`, `instructions`); `POST /proposals/{id}/cv` (`profile_id`, CV a medida; además exige `talent.read` y ser responsable o `manage`) | `proposals.write` + `proposal_generator` |
| IA (admin) | `GET/POST /admin/ai/prompts` (publicar versión), `GET /admin/ai/prompts/{name}/versions`, `POST /admin/ai/prompts/{name}/versions/{v}/activate`, `POST /admin/ai/prompts/{name}/preview`, `GET/PATCH /admin/ai/services[/{tipo}]`, `GET/POST /admin/ai/pricing`, `GET/POST/PUT /admin/ai/budgets[/{id}]`, `GET /admin/ai/usage`, `GET /admin/ai/usage/summary`, `GET /admin/ai/roi`, `GET/PUT /admin/ai/baselines[/{tipo}]`, `GET /admin/ai/quality`, `GET /admin/ai/rag/collections`, `POST /admin/ai/rag/reindex`, `GET /admin/ai/health`, `GET /admin/ai/compliance`, `GET /admin/ai/gdpr/users/{id}`, `POST /admin/ai/gdpr/users/{id}/erase` | `prompts`, `llm_config`, `audit`, `users` |
| Búsqueda | `GET /search?q=&limit=` (oportunidades, documentos y clientes a la vez), `POST /search/opportunities`, `POST /search/documents`, `POST /search/click` (`query_log_id`, `kind`, `object_id`, `position`) | `opportunities.read` / `documents.read` |
| Asistente | `POST /assistant/query` (`query` máx. 500, `history`, `document_ids`, `opportunity_id`), `POST /assistant/feedback` (`query_log_id`, `rating` 1-5, `expected_intent`) | `opportunities.read` + `copilot_chat` |
| Búsqueda (admin) | `GET/POST /admin/search/intent-patterns`, `PATCH/DELETE /admin/search/intent-patterns/{id}`, `POST /admin/search/intent/test`, `GET /admin/search/quality?days=`, `GET /admin/search/indexes`, `POST /admin/search/reindex` (`index`) | `search` |
| Copiloto | `GET/POST /copilot/conversations`, `GET/PATCH/DELETE /copilot/conversations/{id}`, `POST /copilot/conversations/{id}/messages` (SSE; `content` máx. 4.000, `opportunity_id`, `document_ids`), `POST /copilot/runs/{run_id}/approval` (SSE; `approve`, `comment`), `GET /copilot/runs/{run_id}`, `GET/POST/DELETE /copilot/memories`, `PATCH/DELETE /copilot/memories/{id}`, `GET /copilot/export` | `copilot` + `copilot_chat` |
| Agentes (admin) | `GET /admin/agents/tools`, `GET/POST /admin/agents`, `GET/PATCH /admin/agents/{id}`, `PUT /admin/agents/{id}/tools`, `GET /admin/agents/{id}/versions`, `POST /admin/agents/{id}/versions/{n}/restore`, `POST /admin/agents/{id}/test` (`input`, `expect_tools`), `GET /admin/agents/{id}/metrics?days=`, `GET /admin/agents/runs` | `agents` |
| Colas (admin) | `GET /admin/tasks/queues`, `GET /admin/tasks/failed`, `POST /admin/tasks/failed/{id}/review`, `POST /admin/tasks/failed/{id}/retry` | `tasks` |
| Analítica | `GET /analytics/overview?months=&service_line=&sector=` (indicadores, embudo, evolución mensual, por línea y sector, mapa sector × línea, clientes y propuestas), `GET /analytics/ai?months=` (ahorro y coste de la IA por mes). Solo con `X-App-Code: analytics` | `dashboards.read` |
| Inteligencia comercial | `GET /analytics/heatmap?period=AAAA-MM` (puntuaciones del mes, `config`, `periods`; el mes en curso se calcula si falta, uno pasado sin datos da 404), `PUT /analytics/heatmap/config` (`weight_demand`, `weight_traction`, `weight_economic`, `weight_right_to_win` que suman 100, `lookback_months` 3-36, `version`), `POST /analytics/heatmap/recalculate`, `GET /analytics/service-lines`, `GET/POST /analytics/targets` (`year`; `metric`, `period`, `service_line`, `target_value`), `PATCH/DELETE /analytics/targets/{id}`, `GET /analytics/import/template`, `POST /analytics/import?dry_run=true\|false` (multipart `file`, `.xlsx` hasta 5 MB). `overview` añade `previous`, `pipeline_history` y `targets`. Solo con `X-App-Code: analytics` | `dashboards.read` / `dashboards.write` |
| Competidores | `GET /analytics/competitors` (`q`, `type`, `service_line`), `POST /analytics/competitors`, `GET/PATCH/DELETE /analytics/competitors/{id}` | `competitors` |
| Pregunta a tus datos | `POST /analytics/ask` (`question`, `months`, `service_line`, `sector`) | `dashboards.read` + `analytics_assistant` |
| Usuarios (admin) | `GET /admin/users` (`q`, `status=active\|inactive`, `app`; `items` + `pagination`), `POST /admin/users`, `GET /admin/users/{id}`, `PUT/DELETE /admin/users/{id}/memberships/{app}` (`role`), `POST /admin/users/{id}/deactivate`, `POST /admin/users/{id}/reactivate`, `POST /admin/users/{id}/mfa/reset` | `users`, `roles` |
| Roles (admin) | `GET /admin/apps` (aplicaciones con módulos, acciones y roles), `PATCH /admin/roles/{id}` (`version`, `permissions`) | `roles` |
| Auditoría (admin) | `GET /admin/audit` (`action`, `severity`, `user_id`, `days`; `items` + `pagination`), `GET /admin/audit/actions` | `audit` |

## Flujos

**Oportunidad** (12 estados, 5 fases):
`detected → qualifying → qualified → (analyzing) → go_no_go → preparing_proposal →
proposal_review → proposal_sent → (negotiation) → won | lost`. Desde casi todos se puede
pasar a `discarded` (con motivo en `comment`), y una descartada se puede reabrir.
El detalle incluye `allowed_transitions`.

**Propuesta**: `draft → in_review → approved → sent → won | lost → archived`.
- `approved` solo se alcanza con `POST /reviews` (`kind`: technical, executive, area, general;
  `decision`: approve o reject, este último con `comment`).
- Revisiones necesarias: premium y executive, técnica + ejecutiva; custom, la de área;
  base y competitive, una cualquiera. La base puede enviarse directamente desde borrador.
- Competitiva: necesita un adjunto `kind=competitive_analysis` antes de entrar en revisión.
- Enviar exige el permiso `proposals.send` (gestor) e importe total.
- Al aprobarse se genera el DOCX en segundo plano y llega una notificación `REPORT_READY`.

**Documento**: al subirlo queda `pending`; el worker `celery_ai` extrae el texto (PDF,
DOCX, TXT, MD, CSV) y lo deja `processed` o `failed`. Consulta `GET /documents/{id}/status`.
Un fichero idéntico a otro ya subido devuelve 409 con `existing_document_id`.
Después se vectoriza (`index_status`: `pending → indexed`) y se cataloga con IA
(`ai_summary`, `ai_keywords`, `ai_entities`). Con `allowed_roles` (por ejemplo
`["manager"]`) solo lo ven su propietario, esos roles y quien tenga `documents.manage`;
para el resto no existe (404), tampoco en las búsquedas ni en las respuestas de la IA.

**IA** (decisiones en [ADR-011](adr/ADR-011-nucleo-ia.md)):
- `POST /ai/ask` responde solo con fragmentos que la persona puede ver, con citas `[n]`,
  `sources` y `sufficient_context` (false si los documentos no bastan). Sin fuentes no se
  llama al modelo. La pregunta pasa por guardarraíles (máx. 2.000 caracteres, intentos de
  inyección, datos personales que se ocultan).
- El análisis GO/NO-GO y la redacción de propuestas van en segundo plano (202) y avisan
  con una notificación `REPORT_READY`. La redacción solo rellena `ai_content`: lo editado a
  mano (`edited_content`) no se toca, salvo que pidas esa sección en `sections`.
- Módulos de IA por rol (`ai_modules_access`): el analista tiene `document_analyzer` y
  `copilot_chat`; el gestor, todos; el de consulta, ninguno.

**Búsqueda** (decisiones en [ADR-012](adr/ADR-012-busqueda-e-intencion.md)):
- `POST /search/opportunities` admite `q`, `status`, `phase`, `sector`, `service_line`,
  `source`, `cpv` (prefijos: `["72"]`), `value_min/max`, `deadline_from/to`,
  `deadline_within_days`, `published_from/to`, `published_within_days`, `min_relevance`,
  `owner` (`"me"` o id), `client_id`, `only_open`, `sort` (`relevance`, `-relevance_score`,
  `deadline`, `-published`, `-value`, `value`, `-created`), `facets` y `semantic` (reordena
  la primera página por significado). Cada resultado trae `highlight.title` y
  `highlight.snippet` con `<mark>` (el resto del texto va escapado) y `score`.
- La respuesta dice el motor (`engine`: `meilisearch` o `mysql` si el buscador no
  responde; entonces sin facetas y con un aviso en `notes`). Con `q` incluye
  `query_log_id` para registrar el clic.
- Los documentos se filtran por los mismos permisos que en el resto de la API.

**Asistente**: `POST /assistant/query` clasifica la frase y responde siempre con
`intent` (`type`, `subtype`, `confidence`, `layer`: `pattern`, `llm` o `fallback`) y
`query_log_id`, más según el `type`:
- `search_results`: `target` (`opportunities`, `documents`, `clients`), `filters` que se
  entendieron de la frase, `items` y `pagination`.
- `rag_answer`: como `POST /ai/ask`.
- `workflow_suggestion`: `action`, `target`, `message` y `confirm` (`method`, `path`,
  `body`) para que la interfaz lo lance si la persona confirma. **Nunca se ejecuta solo.**
  `confirm` es `null` si falta el destino o el rol no lo permite.
- `off_topic`: `message` orientativo.

**Copiloto** (decisiones en [ADR-013](adr/ADR-013-copiloto-y-agentes.md)):
- Las conversaciones son de quien las crea; nadie más las ve. `@oportunidad:{id}`,
  `@documento:{id}`, `@cliente:{id}` y `@propuesta:{id}` en el texto se convierten en
  referencias (solo las que la persona puede ver).
- `POST .../messages` y `POST /copilot/runs/{id}/approval` responden con
  `text/event-stream`. Eventos: `intent`, `agent` (`slug`, `name`), `delta` (`text`),
  `replace` (`text`: sustituye lo mostrado), `tool_call` (`name`, `title`, `summary`),
  `tool_result` (`name`, `ok`, `ms`), `notice` (`message`), `rag_answer` (`sources`,
  `citations`), `approval_required` (`run_id`, `expires_at`, `actions`), `done` (`status`,
  `stop_reason`, `iterations`, `tool_calls`, `cost_usd`, `message_id`) y `error` (`message`,
  `retract`: si es true, hay que borrar lo mostrado).
- Una entrada bloqueada por los guardarraíles devuelve 422 antes de abrir el stream.
- `approval_required`: el agente se ha parado. La persona responde con
  `POST /copilot/runs/{run_id}/approval` antes de 15 minutos; la respuesta sigue por SSE.
  Una segunda respuesta a la misma ejecución da 409.
- Herramientas que piden aprobación siempre: analizar oportunidad o documento, crear o
  redactar propuesta, CV a medida y exportar el paquete. Las de consulta no la piden.
- El paquete de una propuesta aprobada trae DOCX, PDF y PPTX; el CV a medida, DOCX y PDF
  (adjuntos `kind=cv`).

## Quién puede qué (operations)

| Acción | viewer | analyst | manager | admin |
| --- | --- | --- | --- | --- |
| Consultar todo | ✓ | ✓ | ✓ | ✓ |
| Crear oportunidades y propuestas, subir documentos | | ✓ (las suyas) | ✓ | ✓ |
| Modificar las de otros, reasignar | | | ✓ | ✓ |
| Clientes, plantillas, portfolio, talento (escritura) | | | ✓ | ✓ |
| Aprobar y enviar propuestas, exportar CSV | | | ✓ | ✓ |

## Probarlo

Con la plataforma levantada y tu usuario administrador:

```bash
python scripts/demo_fase4.py --email tu@empresa.com
python scripts/demo_fase5.py --email tu@empresa.com   # llamadas reales a Claude (céntimos)
python scripts/demo_fase5c.py --email tu@empresa.com  # chat con el copiloto y una aprobación
```

Piden la contraseña sin mostrarla. La de la fase 4 recorre cliente, oportunidad,
documento y propuesta con revisiones. La de la fase 5 sube un pliego de ejemplo, le hace
una pregunta, lo analiza (GO/NO-GO), puntúa una oportunidad, redacta una propuesta y
muestra el coste y el ahorro. `--sin-propuesta` se salta la redacción (la parte cara).
