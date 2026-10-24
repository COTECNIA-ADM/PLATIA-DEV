# ADR-016: Despliegue en un servidor con Docker Compose, imágenes en GHCR y vuelta atrás automática

**Fecha:** 2026-10-24 · **Estado:** Aceptado

## Contexto
La fase 8 lleva la plataforma a producción (capítulos 21 y 22): HTTPS, imágenes versionadas,
despliegue repetible, copias de seguridad, observabilidad de las colas y avisos por correo.
El equipo es pequeño y la plataforma cabe en un servidor; un orquestador (Kubernetes,
Swarm) añadiría más piezas que operar que problemas resuelve.

## Decisión

**Un servidor con Docker Compose**
- `docker-compose.prod.yml` se aplica encima de `docker-compose.yml` (no lo sustituye): las
  redes, los volúmenes y las variables siguen en un solo sitio y desarrollo y producción no
  se separan con el tiempo.
- En producción no se compila nada: las imágenes de `backend`, `ai_service` y `frontend`
  vienen de GitHub Container Registry con la etiqueta `sha-<commit>`.
- nginx es el único servicio con puertos publicados (80 y 443). El 80 solo atiende la
  validación de Let's Encrypt y redirige a HTTPS. HSTS en todas las respuestas.
- Certificados propios o de Let's Encrypt (perfil `letsencrypt`, renovación con `certbot`
  y recarga de nginx cada 6 horas).
- Registros en JSON con rotación (20 MB × 5 por contenedor).
- Flower para ver las colas, detrás de nginx con usuario y contraseña. Se ejecuta con la
  imagen del backend (`celery -A celery_app flower`) y no con la imagen oficial de Flower:
  los workers usan opciones de transporte propias (prioridades y separador `:` en las
  claves de Redis) y un cliente que no las conozca rompe las órdenes de control
  (`inspect`) de todos los workers.

**CI/CD**
- `release.yml`: tras pasar la CI en `main`, construye y publica las tres imágenes.
- `deploy.yml`: manual (`workflow_dispatch`), con el entorno `production` de GitHub, que
  exige la aprobación de un revisor. Entra por SSH con una clave solo para desplegar y la
  huella del servidor fijada (`known_hosts`), y ejecuta `scripts/deploy.sh`.
- `deploy.sh`: copia de seguridad, descarga de imágenes, migraciones (el contenedor
  `migrations` va antes que el backend), arranque y comprobación de salud por HTTPS. Si en
  3 minutos no responde sano, vuelve a la versión anterior (código e imágenes).
- Las migraciones no se deshacen solas. Se escriben compatibles hacia atrás (primero se
  añade, en otra versión se borra), así la versión anterior funciona con el esquema nuevo;
  para lo demás está la copia que se acaba de hacer.

**Copias de seguridad**
- `scripts/backup.sh`: volcado coherente de los tres esquemas (`--single-transaction`),
  documentos subidos y `.env` (sin él no se descifran los secretos MFA). Retención de 14
  días en el servidor; la copia fuera del servidor es responsabilidad de quien opera.
- Qdrant y Meilisearch no se copian: se regeneran desde MySQL (`flask reindex`).
- `scripts/restore.sh` pide confirmación escrita, borra y recrea los tres esquemas.

**Correo y marcado de la IA**
- Los avisos de prioridad alta o urgente sin leer se envían por SMTP (tarea programada cada
  2 minutos, `notifications.emailed_at` para no repetir). Sin `SMTP_HOST` no se envía nada.
- Los ficheros generados (propuesta en DOCX, PDF y PPTX; CV a medida) llevan en sus
  metadatos que se han hecho con IA y un aviso visible configurable (`AI_DISCLOSURE_TEXT`).
  Las respuestas de la IA en pantalla llevan la marca «Generado con IA».
- Los costes de IA se guardan en dólares (la moneda de los precios del proveedor) y se
  muestran en euros con `AI_USD_EUR_RATE`, que el frontal recibe en `/api/auth/me`. Los
  límites de los presupuestos se escriben en euros y se guardan convertidos.

## Consecuencias
- Un solo servidor es un punto único de fallo: la recuperación es restaurar la copia en
  otro servidor (documentado en `docs/despliegue.md`). Si hiciera falta alta
  disponibilidad, el siguiente paso sería MySQL gestionado y dos nodos detrás de un
  balanceador, con las mismas imágenes.
- Cambiar el tipo de cambio cambia las cifras en euros de todo el histórico: es una
  conversión para leer, no contabilidad.
- Una migración que borre columnas o tablas debe ir en una versión posterior a la que deja
  de usarlas; si no, la vuelta atrás automática no sirve.
