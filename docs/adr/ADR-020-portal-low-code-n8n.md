# ADR-020: Portal Low-Code con n8n como motor de automatizaciones

**Fecha:** 2026-11-07 · **Estado:** Aceptado (fases L0 a L2)

## Contexto
El ciclo comercial tiene tareas en sus extremos que hoy se hacen a mano o no se hacen:
leer un buzón de pliegos, avisar por Teams, archivar el paquete de la propuesta, sincronizar
con el CRM, vigilar resoluciones. Se quiere un portal *Low-Code* donde las personas lancen
automatizaciones y un grupo pequeño las construya, con n8n como motor.

n8n puede hacer justo lo que PLATIA prohíbe a sus agentes (ADR-013): ejecutar órdenes,
leer ficheros, llamar a cualquier sitio. Y si cada persona entrara en su editor, se
perderían los permisos de PLATIA, la auditoría y el coste por persona.

## Decisión

**PLATIA es el menú; n8n solo ejecuta**
- El portal será una cuarta aplicación del frontal, `automation` (ADR-014 y ADR-015), con
  roles `user`, `builder`, `admin` y `viewer`. Las personas lanzan desde PLATIA, que
  comprueba permisos en la BD, guarda la ejecución y llama al webhook de n8n con firma
  HMAC. n8n devuelve el resultado a la API de PLATIA con una clave de integración.
- Solo los constructores y quien administra tienen cuenta en el editor de n8n.
- Las decisiones del BPMN (GO/NO-GO, aprobar, registrar el resultado) siguen siendo de una
  persona en PLATIA. La IA de un flujo pasa por los endpoints de IA de PLATIA o por el
  gateway corporativo con su propia aplicación y cuota (ADR-019); nunca directo.

**Capa opcional, red propia y sin datos (fase L0)**
- `docker-compose.n8n.yml` añade el servicio `n8n` (imagen con versión fijada) y lo pone
  solo en `automation_net`, que comparte con Nginx y, desde la fase L1, con el backend.
  No está en `data_net`.
- Sus datos van en el volumen `n8n_data` (SQLite) y `N8N_ENCRYPTION_KEY` sale del `.env`.
  `backup.sh` y `restore.sh` los copian cuando `N8N_ENABLED=true`.
- n8n no publica puerto. El Nginx de PLATIA lo sirve en un puerto propio
  (`N8N_HTTP_PORT`, 5679) y en la raíz, porque la documentación de n8n desaconseja servirlo en
  una subruta detrás de un proxy. El fichero `nginx/n8n.conf` solo se monta con la capa.

**Recortado como los agentes**
- `NODES_EXCLUDE` quita *Execute Command*, *Local File Trigger*, *Read/Write Files from
  Disk*, *SSH* y *Git*. `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` impide leer los secretos del
  entorno desde un flujo y `N8N_RESTRICT_FILE_ACCESS_TO` acota los ficheros.
- Sin telemetría ni avisos de versión hacia fuera. Historial de ejecuciones de 14 días.

**Solo desarrollo por ahora**
- `deploy.sh` se niega a desplegar con `N8N_ENABLED=true`: en producción n8n llegará con
  HTTPS, su subdominio, cookie segura y acceso limitado.

**Catálogo leído de n8n (fase L1)**
- La app `automation` lee los flujos con la API pública de n8n (`N8N_API_KEY`) y solo
  enseña los que llevan la etiqueta `N8N_CATALOG_TAG` (`platia`): etiquetar es publicar.
  Del flujo solo salen id, nombre, estado, etiquetas y fecha; nunca nodos ni credenciales.
- Si n8n está apagado o rechaza la clave, el portal responde igual y dice por qué; el
  detalle va al log. El enlace al editor solo se da con `automations.build`.

**Ejecutar y seguir (fase L2)**
- `POST /api/automation/runs` (`automations.run`) comprueba en la API de n8n que el flujo
  lleva la etiqueta, está activo y empieza por un Webhook POST, y guarda la ejecución en
  `operations_db.automation_runs` con una copia del id y del nombre del flujo. La entrada es
  plana (hasta 30 claves de texto, número o sí/no) y pequeña.
- La tarea `tasks.automation.run` (cola `automation`, worker `celery_automation` de la capa
  n8n) llama al webhook dentro de `automation_net` con `X-Platia-Webhook-Key`, que el nodo
  Webhook comprueba con una credencial «Header Auth», y con la firma `X-Platia-Signature`
  para los flujos que quieran validar también la fecha y el cuerpo. Es idempotente y, si n8n
  no responde, reintenta con backoff y al final marca la ejecución como fallida.
- n8n responde a `POST /api/automation/runs/<id>/callback` con `X-Platia-Integration-Key`.
  Es la única ruta de la app sin sesión de persona; solo cierra una ejecución abierta, una vez.
  `tasks.automation.expire_stale` (cada 10 minutos, cola `default`) cierra las que n8n no
  contesta en `AUTOMATION_RUN_TIMEOUT_MINUTES`.
- Cada persona ve sus ejecuciones; `automations.manage`, todas. La ruta del webhook nunca
  sale de PLATIA: el catálogo solo dice si el flujo se puede lanzar (`launchable`).
- Se aplaza a L3 el catálogo propio en BD (descripción y campos de entrada de cada flujo):
  mientras, el catálogo sigue saliendo de n8n y la entrada se escribe como pares clave-valor.

## Alternativas descartadas
- **Firmar solo con HMAC, sin clave en cabecera:** el nodo Webhook de n8n no sabe comprobar
  una firma, y hacerlo en un nodo de código obligaría a escribir el secreto en el flujo,
  porque `N8N_BLOCK_ENV_ACCESS_IN_NODE` impide leerlo del entorno. La credencial «Header Auth»
  lo guarda cifrado; la firma va además para quien la quiera comprobar.
- **Esperar el resultado en la misma llamada al webhook:** un flujo largo dejaría la tarea
  colgada; con la respuesta aparte, la tarea termina en cuanto n8n acepta el trabajo.
- **Menú propio en n8n (formularios o chat de n8n) para todos:** cada persona necesitaría
  cuenta en n8n y no habría permisos de PLATIA ni auditoría. Los formularios de n8n quedan
  para casos sin usuario de PLATIA, como un formulario web público.
- **Servir el editor en `/n8n/` del mismo puerto:** la documentación de n8n avisa de
  problemas de navegación con `N8N_PATH` detrás de un proxy.
- **Unir n8n a `platia_llm_net`:** esa red es solo del servicio de IA y del gateway
  (ADR-019).
- **Contenedor suelto con `docker run`:** sin volumen se pierden flujos y credenciales al
  recrearlo, y sin versión fijada cambia solo.

## Consecuencias
- Un contenedor más (1 GB de memoria como máximo) y una clave más que guardar.
- Las fases siguientes: L1 esqueleto de la app `automation`, L2 ejecutar y seguir (tablas,
  tarea en la cola `automation`, firma y clave de integración), L3 taller y publicación,
  L4 monitorización. Cada una con su PR, tests y prueba en Docker.
- El texto del libro de proyectos de n8n que se usa como catálogo no se copia al
  repositorio: solo se citan los títulos de sus proyectos.
