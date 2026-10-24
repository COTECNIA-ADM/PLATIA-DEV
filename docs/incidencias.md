# Guía de incidencias

Qué hacer cuando algo falla en producción. Cada caso sigue el mismo orden: **síntoma**,
**comprobar**, **resolver** y **después**. La instalación y el despliegue están en
[despliegue.md](despliegue.md).

Todas las órdenes se lanzan en el servidor, en `/opt/platia`, con este alias:

```bash
alias pc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
```

En local (Windows), quita `-f docker-compose.prod.yml`: `docker compose ...`.

## 0. Primeros cinco minutos

1. **¿Qué está caído?**
   - `pc ps`: busca contenedores `Restarting`, `Exited` o `unhealthy`.
   - `curl -s https://SERVER_NAME/api/health`: base de datos y Redis. Responde sin sesión.
   - Administración > Estado (o `/api/health/full`): todos los servicios.
2. **¿Desde cuándo?** Mira `pc logs --since 30m <servicio>`. Cada línea es JSON y lleva
   `request_id`, que cruza nginx, backend y workers.
3. **¿Ha habido un despliegue?** `cat .deploy/current .deploy/previous`. Si el fallo
   empezó con la versión nueva, vuelve atrás (caso 2) antes de investigar.
4. **Avisa** a las personas usuarias si la caída va a durar más de 15 minutos.
5. **Apunta** la hora, lo que ves y lo que haces. Sirve para el informe y, si hay datos
   personales afectados, para el plazo de 72 horas del RGPD (caso 14).

| Gravedad | Ejemplo | Respuesta |
| --- | --- | --- |
| Crítica | Plataforma caída, sospecha de acceso indebido o fuga de datos | Inmediata |
| Alta | IA o búsqueda sin servicio, tareas en segundo plano paradas | En la jornada |
| Media | Una función degradada con alternativa (búsqueda en MySQL, modelo de reserva) | 2 días |
| Baja | Error puntual, estético o de una sola persona | Planificada |

## 1. La plataforma no carga (502, 504 o página en blanco)

**Comprobar**
- `pc ps`: ¿están `nginx`, `backend` y `mysql` en marcha y sanos?
- `pc logs --tail 200 backend`: errores al arrancar (variables que faltan, la base de datos
  no responde, un módulo de permisos sin registrar).
- `pc logs --tail 50 migrations`: si una migración falló, el backend no arranca.
- `df -h` y `free -h`: disco o memoria agotados.

**Resolver**
- Un contenedor parado: `pc up -d <servicio>`.
- Falta una variable nueva tras actualizar: `python3 scripts/generate_env.py --actualizar`
  y después `pc up -d`.
- Una migración falló: no la repitas a ciegas. Mira el error, vuelve a la versión anterior
  (caso 2) y abre una incidencia con el registro.
- Página en blanco solo para algunas personas: suele ser la caché. Ctrl+F5.

## 2. Un despliegue ha fallado

`deploy.sh` vuelve solo a la versión anterior si `/api/health` no responde sano en
3 minutos. El flujo **Despliegue** de GitHub sale en rojo.

**Comprobar**
- El registro del flujo en GitHub (*Actions > Despliegue*).
- `cat .deploy/current`: debe ser la versión anterior.
- `pc logs --since 15m backend migrations`.

**Resolver**
- Si la vuelta atrás funcionó, la plataforma sigue con la versión anterior. Corrige el
  fallo en una rama nueva y vuelve a desplegar.
- Si la vuelta atrás no funcionó: lanza el flujo **Despliegue** con la versión de
  `.deploy/previous`, o en el servidor
  `git checkout <commit> && ./scripts/deploy.sh sha-xxxxxxx`.
- Si una migración dañó datos: restaura la copia que hizo el propio despliegue (caso 13).

## 3. MySQL no responde o el disco está lleno

**Síntoma:** errores 500 en todas partes y `database_platform` en rojo en `/api/health`.

**Comprobar**
- `pc logs --tail 100 mysql`.
- `df -h`: MySQL se para si se llena el disco. Mira también `docker system df`.

**Resolver**
- Disco lleno: borra copias antiguas fuera del plazo (`backups/`), imágenes sin uso
  (`docker image prune -a`, solo las que no usa ninguna versión desplegada) y registros
  rotados. Después, `pc up -d mysql` y espera a que esté sano.
- MySQL no arranca por tablas dañadas: no lo fuerces. Para el resto de servicios
  (`pc stop backend celery_default celery_ai celery_beat`) y restaura la última copia
  (caso 13).

**Después:** vigila el disco (alerta al 80 %) y comprueba que las copias salen del servidor.

## 4. Redis caído

**Síntoma:** nadie puede entrar o la sesión se cierra sola; las tareas no avanzan;
`redis` en rojo en `/api/health`.

Redis guarda las sesiones revocadas, los límites por minuto, las colas de Celery y la
caché. Por seguridad, sin Redis la plataforma **no deja entrar** (falla cerrada).

**Resolver**
- `pc logs --tail 100 redis` y `pc up -d redis`.
- Las tareas que estaban en cola pueden perderse. Revisa Administración > Tareas y
  relanza lo que falte (por ejemplo, reprocesar un documento).

## 5. Las tareas en segundo plano no avanzan

**Síntoma:** documentos que se quedan en «pendiente», análisis GO/NO-GO o paquetes de
propuesta que no llegan, avisos por correo que no salen.

**Comprobar**
- `pc ps`: `celery_default`, `celery_ai` y `celery_beat` en marcha.
- Flower (`https://SERVER_NAME/flower/`): workers conectados, tareas activas y en cola.
- Administración > Tareas: colas y **tareas fallidas** con su error.

**Resolver**
- Un worker parado o colgado: `pc restart celery_ai` (o `celery_default`). Las tareas son
  idempotentes: repetirlas no duplica nada.
- Tareas fallidas por un error ya corregido: **Reintentar** desde Administración > Tareas.
  Si el error no se va a corregir, márcala como revisada.
- No se lanzan las tareas programadas (fotos de cartera, mapa de oportunidad, limpieza RGPD):
  `pc logs --tail 100 celery_beat` y `pc restart celery_beat`. Solo debe haber **un** beat.
- Un documento concreto: en su ficha, **Reprocesar**.

## 6. La IA no responde

**Síntoma:** mensajes «La IA no está disponible» (`ai_unavailable`, 503) o
«desactivada» (`ai_disabled`).

**Comprobar**
- Administración > Estado (servicio de IA), o `pc logs --tail 100 ai_service`.
- ¿Está `AI_ENABLED=true` en `.env`?
- Errores 401 del proveedor: la `ANTHROPIC_API_KEY` es incorrecta, ha caducado o se ha
  revocado. Errores 429 o 529: límite de uso o saturación del proveedor.
- La página de estado del proveedor de IA.

**Resolver**
- Clave inválida: crea una nueva en la consola del proveedor, ponla en `.env` del servidor
  (nunca en un chat ni en un commit) y `pc up -d ai_service`.
- Saturación del proveedor: cada tarea tiene un modelo de reserva y la plataforma lo usa
  sola. Si persiste, cambia el modelo de la tarea en Administración > Modelos.
- Mientras tanto, la plataforma sigue funcionando sin IA: búsqueda, oportunidades,
  propuestas a mano y analítica.

## 7. Presupuesto de IA agotado o coste disparado

**Síntoma:** `budget_exceeded` (429) o una alerta de presupuesto.

**Comprobar**
- Administración > Modelos y costes > Uso: qué tarea, qué persona y desde cuándo.
- Un salto brusco suele ser un bucle (un agente que repite herramientas), una importación
  masiva de documentos o un uso indebido.

**Resolver**
- Uso legítimo: amplía el presupuesto en Administración > Modelos y costes > Presupuestos.
- Uso anómalo de una persona: desactívala en Administración > Usuarios (cierra sus
  sesiones) y revisa la auditoría.
- Para cortar todo el gasto al momento: `AI_ENABLED=false` en `.env` y
  `pc up -d backend celery_ai`. Las funciones de IA se apagan; el resto sigue.

## 8. La búsqueda no encuentra lo que debería

**Comprobar**
- Administración > Búsqueda: estado de los índices y documentos indexados.
- Si Meilisearch no responde, la búsqueda pasa sola a MySQL (con un aviso en pantalla y
  sin facetas) mientras `SEARCH_SQL_FALLBACK=true`.

**Resolver**
- `pc up -d meilisearch` y, si los índices están vacíos o desfasados,
  **Reindexar** en Administración > Búsqueda o `pc exec backend flask reindex`.
- Las preguntas a los documentos (RAG) usan Qdrant: `pc logs --tail 100 qdrant` y el mismo
  `flask reindex`, que reconstruye ambos desde MySQL.
- Clasificación de intención equivocada: añade un patrón en Administración > Búsqueda y
  pruébalo allí mismo.

## 9. La IA bloquea una pregunta o una respuesta legítima

**Síntoma:** «No se puede procesar la pregunta» o «La respuesta no se puede mostrar por
seguridad» (`guardrail`, 422).

**Comprobar:** Administración > Auditoría, acciones de IA bloqueadas: verás el motivo
(posible inyección, datos personales, filtración de instrucciones).

**Resolver**
- Pide a la persona que reformule sin pegar instrucciones o textos ajenos a la consulta.
- Si se repite con preguntas normales, ajusta el prompt de esa tarea (Administración >
  Prompts, publicar una versión nueva) y abre una incidencia con ejemplos. **No desactives
  los guardarraíles.**

## 10. Certificado HTTPS caducado o inválido

**Comprobar:** `echo | openssl s_client -connect SERVER_NAME:443 2>/dev/null | openssl x509 -noout -dates`
y `pc logs --tail 50 certbot`.

**Resolver**
- Let's Encrypt: `pc restart certbot` (intenta renovar al arrancar) y después
  `pc exec nginx nginx -s reload`. Comprueba que `COMPOSE_PROFILES=letsencrypt` sigue en
  `.env` y que el puerto 80 está abierto.
- Certificado propio: sustituye `certs/fullchain.pem` y `certs/privkey.pem` y recarga nginx.

## 11. Una persona no puede entrar

| Caso | Qué hacer |
| --- | --- |
| Cuenta bloqueada tras 5 fallos | Esperar 15 minutos |
| Perdió el móvil del MFA | Que use un código de respaldo |
| Sin móvil ni códigos | Administración > Usuarios > **Restablecer MFA**, o en el servidor `pc run --rm migrations flask reset-mfa --email persona@empresa.com` |
| Olvidó la contraseña | En el servidor, `pc run --rm migrations flask reset-password --email persona@empresa.com`: pide una provisional sin mostrarla, desbloquea la cuenta y cierra sus sesiones. Dásela por un canal seguro (por teléfono, no por correo) y que la cambie en «Mi cuenta» |
| «No tienes acceso a esta aplicación» | Darle un rol en esa aplicación (Administración > Usuarios) |

Nunca pidas ni envíes contraseñas por chat o correo.

## 12. Sospecha de cuenta comprometida o acceso indebido

**Señales:** en Auditoría, entradas CRITICAL de **reutilización del token de refresco**,
muchos inicios de sesión fallidos, accesos desde IP o países raros, exportaciones o
consultas fuera de lo normal.

**Resolver**
1. Desactiva la cuenta (Administración > Usuarios > Desactivar). Cierra todas sus sesiones.
2. Restablece su MFA y dale una contraseña nueva por un canal seguro.
3. Revisa en Auditoría qué hizo esa cuenta desde la hora sospechosa.
4. Si pudo ver o sacar datos personales, sigue el caso 14.

**Si se sospecha de muchas cuentas o del propio servidor:** cambia `JWT_SECRET_KEY` en
`.env` y `pc up -d backend`. Se cierran **todas** las sesiones. No cambies
`MFA_ENCRYPTION_KEY`: dejarías a todo el mundo sin MFA.

## 13. Hay que recuperar datos

1. Para la escritura: `pc stop backend celery_default celery_ai celery_beat`.
2. Elige la copia (`ls backups/`) anterior al problema.
3. `./scripts/restore.sh backups/AAAAMMDD-HHMMSS --prod` (pide escribir RESTAURAR).
4. `pc up -d`. La búsqueda y los índices de documentos se regeneran solos en unos minutos.
5. Avisa de que se ha perdido lo hecho entre la copia y la incidencia.

## 14. Fuga de datos personales o de secretos

**Secretos** (`.env`, una clave de API o un token publicado en un commit, un chat o un
issue):
1. **Revócalo** en su origen (consola del proveedor de IA, GitHub, servidor de correo) y crea
   uno nuevo. Borrarlo del historial no basta: hay que darlo por visto.
2. Pon el nuevo en `.env` del servidor y `pc up -d`.
3. Si fue `JWT_SECRET_KEY` o `DB_PASSWORD`, cámbialos también (caso 12 para el JWT; para la
   base de datos, cambia la contraseña del usuario en MySQL y en `.env` a la vez).

**Datos personales** (contactos, CV, usuarios):
1. Contén la fuga (desactiva cuentas, cierra el acceso, revoca enlaces).
2. Avisa **de inmediato** a la persona responsable de protección de datos. Si hay riesgo
   para las personas, la autoridad de control debe saberlo **en 72 horas** desde que se
   conoce la brecha (art. 33 del RGPD), y en ciertos casos las propias personas afectadas.
3. Guarda las pruebas: Auditoría, registros de nginx y del backend del periodo.
4. Registra la brecha aunque no se notifique (art. 33.5).

## 15. Los avisos por correo no llegan

**Comprobar**
- `SMTP_HOST`, `EMAIL_FROM` y el resto de `SMTP_*` en `.env`.
- `pc logs --tail 200 celery_default | grep email`: busca `email_send_failed`.
- Solo se envían los avisos de prioridad alta o urgente sin leer de las últimas 24 horas, y
  solo una vez.

**Resolver:** corrige la configuración y `pc up -d backend celery_default celery_beat`. Si
el servidor de correo rechaza los mensajes, revisa el remitente (SPF y DKIM del dominio).

## 16. La analítica sale vacía o con cifras raras

- **Mapa de oportunidad sin celdas:** hacen falta oportunidades con sector y línea de
  servicio. Pulsa **Recalcular**.
- **Sin comparación de cartera o sin evolución:** salen de las fotos nocturnas
  (`tasks.analytics.take_snapshot`, 23:50). La comparación necesita una foto anterior al
  periodo y la evolución, dos semanas. Si no se toman, revisa `celery_beat` (caso 5).
- **Importación de Excel rechazada:** la pantalla lista los errores por hoja y fila; no se
  guarda nada hasta que no haya ninguno.

## Después de cada incidencia crítica o alta

Escribe un informe breve, sin culpables: qué pasó, cuándo se detectó, qué se hizo, cuánto
duró y qué cambia para que no se repita (una alerta, un test, un paso en esta guía).
Actualiza esta guía si un caso no estaba o la solución era otra.
