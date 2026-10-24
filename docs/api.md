# API de negocio (fase 4)

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

Límites por usuario y minuto: lectura 60, escritura 20, subida 10, exportación 5 (429 con `Retry-After`).

## Recursos

| Módulo | Rutas principales | Permiso |
| --- | --- | --- |
| Clientes | `GET/POST /clients`, `GET/PATCH/DELETE /clients/{id}`, `POST/PATCH/DELETE /clients/{id}/contacts[/{cid}]`, `.../projects[/{pid}]` | `clients` |
| Oportunidades | `GET/POST /opportunities` (filtros `status`, `phase=F1..F5`, `owner=me`, `client_id`, `service_line`, `min_score`, `deadline_from/to`, `q`, `sort`), `GET/PATCH/DELETE /opportunities/{id}`, `POST /opportunities/{id}/status`, `POST /opportunities/{id}/score`, `POST/DELETE /opportunities/{id}/documents[/{doc}]`, `GET /opportunities/export` | `opportunities` |
| Documentos | `GET/POST /documents` (multipart: `file`, `title`, `doc_type`), `GET/PATCH/DELETE /documents/{id}`, `GET /documents/{id}/status`, `GET /documents/{id}/download`, `POST /documents/{id}/versions`, `POST /documents/{id}/reprocess` | `documents` |
| Propuestas | `GET/POST /proposals`, `GET/PATCH/DELETE /proposals/{id}`, `POST /proposals/{id}/status`, `POST /proposals/{id}/reviews`, `POST /proposals/{id}/package`, `POST/PATCH/DELETE /proposals/{id}/sections[/{sid}]`, `POST /proposals/{id}/attachments` (multipart: `file`, `kind`), `GET/DELETE /proposals/{id}/attachments/{aid}` | `proposals` |
| Plantillas | `GET/POST /proposal-templates`, `GET/PATCH/DELETE /proposal-templates/{id}` | `templates` |
| Portfolio | `GET/POST /portfolio/service-lines`, `PATCH /portfolio/service-lines/{id}` | `portfolio` |
| Talento | `GET/POST /talent/profiles` (filtros `family`, `seniority`, `skill`, `available`, `q`), `GET/PATCH/DELETE /talent/profiles/{id}` | `talent` |
| Notificaciones | `GET /notifications` (`unread=true`, `type`), `GET /notifications/unread-count`, `POST /notifications/{id}/read`, `POST /notifications/read-all` | `notifications` |
| Alertas | `GET /alerts` (`open=true`), `POST /alerts/{id}/resolve` | `alerts` |
| Colas (admin) | `GET /admin/tasks/queues`, `GET /admin/tasks/failed`, `POST /admin/tasks/failed/{id}/review`, `POST /admin/tasks/failed/{id}/retry` | `tasks` |

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
```

Pide la contraseña sin mostrarla y recorre el flujo completo: cliente, oportunidad
puntuada, documento procesado, propuesta premium con doble revisión y paquete DOCX.
