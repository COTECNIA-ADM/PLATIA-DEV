# Despliegue y operación (fase 8)

Guía para poner PLATIA en un servidor Linux con HTTPS y desplegar desde GitHub. Las
decisiones están en [ADR-016](adr/ADR-016-despliegue-y-operacion.md).

Nunca escribas contraseñas ni tokens en un chat, un issue o un commit. Van en el `.env`
del servidor o en los secretos de GitHub, y se teclean en tu propia terminal.

## 1. Lo que hace falta

- Un servidor Linux (Ubuntu 24.04 o similar) con 4 CPU, 16 GB de RAM y 100 GB de disco.
- Docker Engine con Compose 2.24 o posterior (`docker compose version`).
- Un dominio (por ejemplo `platia.tu-dominio.es`) que apunte a la IP del servidor.
- Puertos 80 y 443 abiertos hacia el servidor. El resto, cerrados (incluido MySQL).

## 2. Preparar el servidor (una vez)

```bash
# Usuario solo para desplegar, en el grupo docker
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
sudo mkdir -p /opt/platia && sudo chown deploy:deploy /opt/platia

# Como deploy: clave SSH de solo lectura para clonar el repositorio
sudo -iu deploy
ssh-keygen -t ed25519 -f ~/.ssh/github_read -N ""
cat ~/.ssh/github_read.pub
```

Añade esa clave pública en GitHub, en *Settings > Deploy keys* del repositorio, **sin**
permiso de escritura. Después:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/github_read
EOF
git clone git@github.com:COTECNIA-ADM/PLATIA-DEV.git /opt/platia
```

**Acceso a las imágenes.** Si el repositorio es privado, las imágenes de GHCR también lo
son. Crea en GitHub un *personal access token (classic)* solo con `read:packages` y, en el
servidor, inicia sesión pegándolo cuando te lo pida (no lo pongas en la línea de órdenes):

```bash
docker login ghcr.io -u TU_USUARIO_DE_GITHUB
```

## 3. El `.env` de producción

```bash
cd /opt/platia
python3 scripts/generate_env.py
nano .env
```

Revisa sobre todo:

| Variable | Valor |
| --- | --- |
| `SERVER_NAME` | el dominio, p. ej. `platia.tu-dominio.es` |
| `ANTHROPIC_API_KEY` | la clave de la API de Claude |
| `REGISTRY` | `ghcr.io/cotecnia-adm/platia-dev` (en minúsculas) |
| `SMTP_*`, `EMAIL_FROM` | el servidor de correo de los avisos (opcional) |
| `AI_USD_EUR_RATE` | el cambio de dólar a euro con el que se muestran los costes |
| `AI_DISCLOSURE_TEXT` | el aviso de IA en los documentos generados (vacío: solo metadatos) |

`PLATIA_VERSION` la escribe `deploy.sh` en cada despliegue; no hace falta tocarla.
El `.env` contiene todos los secretos: `chmod 600 .env` y no lo copies a ningún otro sitio
que no sea la copia de seguridad.

## 4. Certificados

**Opción A: Let's Encrypt** (el dominio tiene que resolver ya a este servidor):

```bash
./scripts/init_letsencrypt.sh tu-correo@tu-dominio.es
```

Crea un certificado provisional, arranca nginx, pide el real y deja el contenedor `certbot`
renovándolo. Para que siga activo en cada despliegue, añade al `.env`:

```bash
COMPOSE_PROFILES=letsencrypt
```

**Opción B: certificado de tu empresa.** Copia la cadena completa y la clave privada en
`certs/fullchain.pem` y `certs/privkey.pem` (`chmod 600 certs/privkey.pem`). nginx relee
los certificados cada 6 horas; para cambiarlos al momento:
`docker compose -f docker-compose.yml -f docker-compose.prod.yml exec nginx nginx -s reload`.

## 5. Contraseña de Flower

Flower (estado de las colas) queda en `https://SERVER_NAME/flower/`, protegido con usuario
y contraseña. Crea el fichero en el servidor; la contraseña se teclea, no se escribe en la
orden:

```bash
docker run --rm -it httpd:2.4-alpine htpasswd -nB admin > nginx/auth/flower.htpasswd
chmod 640 nginx/auth/flower.htpasswd
```

## 6. Configurar GitHub

1. *Settings > Actions > General > Workflow permissions*: deja "Read repository contents".
   El flujo **Imágenes** pide por su cuenta permiso para escribir paquetes.
2. *Settings > Environments > New environment*: `production`.
   - *Required reviewers*: quién aprueba los despliegues.
   - *Deployment branches*: solo `main`.
   - Secretos del entorno:

| Secreto | Qué es |
| --- | --- |
| `DEPLOY_HOST` | IP o nombre del servidor |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | clave privada **solo para desplegar** (ver abajo) |
| `DEPLOY_KNOWN_HOSTS` | la huella del servidor (ver abajo) |

Clave para desplegar (créala en tu equipo, no en el servidor):

```bash
ssh-keygen -t ed25519 -f platia_deploy -N "" -C "github-actions-deploy"
# platia_deploy.pub -> al final de /home/deploy/.ssh/authorized_keys en el servidor
# platia_deploy     -> secreto DEPLOY_SSH_KEY (y después bórrala de tu equipo)
ssh-keyscan -t ed25519 TU_SERVIDOR    # la salida -> secreto DEPLOY_KNOWN_HOSTS
```

Comprueba la huella de `ssh-keyscan` con la que te dé el proveedor del servidor: es lo que
impide que el despliegue se conecte a un servidor suplantado.

## 7. Primer despliegue

1. Haz merge en `main`. Cuando la CI pase, el flujo **Imágenes** sube a GHCR las
   imágenes `backend`, `ai_service` y `frontend` con la etiqueta `sha-xxxxxxx`.
2. En *Actions > Despliegue > Run workflow*, deja la versión vacía (último commit de
   `main`) o escribe una `sha-xxxxxxx`. Quien revise lo aprueba y empieza.
3. Crea el primer administrador en el servidor:

```bash
cd /opt/platia
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm migrations \
  flask create-admin --email tu@empresa.com --name "Tu Nombre"
```

Para desplegar a mano desde el servidor: `./scripts/deploy.sh sha-xxxxxxx` (después de
`git fetch && git checkout <commit>`).

## 8. Qué hace cada despliegue y cómo se vuelve atrás

`scripts/deploy.sh`:

1. Copia de seguridad (si ya había una versión desplegada).
2. Descarga las imágenes de la versión y arranca. El contenedor `migrations` aplica las
   migraciones antes de que arranque el backend.
3. Comprueba `https://SERVER_NAME/api/health` durante 3 minutos.
4. Si no responde sano, vuelve al commit y a las imágenes de la versión anterior.

La versión desplegada está en `.deploy/current` y la anterior en `.deploy/previous`.
Para volver atrás a mano, lanza el flujo **Despliegue** con la versión anterior.

Las migraciones no se deshacen solas. Por eso se escriben compatibles hacia atrás: una
versión añade columnas o tablas, y solo una versión posterior borra lo que ya no se usa.
Si una migración rompe datos, restaura la copia que hizo el propio despliegue (apartado 9).

## 9. Copias de seguridad

```bash
./scripts/backup.sh --prod
```

Deja en `backups/AAAAMMDD-HHMMSS/` el volcado de los tres esquemas, los documentos subidos
y el `.env`. Borra las copias de más de `BACKUP_KEEP_DAYS` días (14). Qdrant y Meilisearch
no se copian: se reconstruyen desde MySQL.

Programarla cada noche (`crontab -e` como `deploy`):

```cron
30 2 * * * cd /opt/platia && ./scripts/backup.sh --prod >> backups/backup.log 2>&1
```

**Una copia que solo está en el servidor no es una copia.** Llévala cada día a otro sitio
cifrada, por ejemplo con `rclone` a un almacenamiento de objetos con cifrado, o con
`restic`. La carpeta contiene datos personales y todos los secretos.

Restaurar (borra los datos actuales; pide escribir RESTAURAR):

```bash
./scripts/restore.sh backups/20261024-023000 --prod
```

En un servidor nuevo, copia antes el `.env` de la copia (`cp backups/.../env .env`): los
secretos MFA de los usuarios se cifraron con su clave. Al terminar, los índices de búsqueda
y de documentos se regeneran solos en unos minutos (`flask reindex`).

Prueba una restauración completa en otra máquina al menos una vez por trimestre.

## 10. Conexión con el gateway LLM (opcional)

Con el gateway corporativo (`cotecnia-adm/platia-gateway`) levantado en el mismo servidor,
PLATIA puede llamar a Claude a través de él (ADR-019):

1. En el gateway, `scripts/alta_platia.sh` da de alta la aplicación `platia` con sus
   modelos y precios, y escribe una clave `plgw-app-platia-…`.
2. En el `.env` de PLATIA: `LLM_GATEWAY_ENABLED=true` y `LLM_GATEWAY_API_KEY=<esa clave>`.
3. Rearrancar con el fichero de la red compartida:
   `docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.gateway.yml up -d`.
   `deploy.sh` y `restore.sh` lo añaden solos cuando el `.env` tiene el gateway activo.

Volver a la llamada directa: `LLM_GATEWAY_ENABLED=false`, `ANTHROPIC_API_KEY` puesta y
rearrancar `ai_service`. Mientras el gateway esté activo no hay reserva directa: si el
gateway cae, la IA de PLATIA no responde hasta que vuelva.

## 11. Operación diaria

```bash
alias pc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
pc ps                          # estado de los contenedores
pc logs -f --tail 100 backend  # registros (JSON, rotados: 20 MB x 5 por contenedor)
pc exec backend flask reindex  # reconstruir búsqueda y RAG desde MySQL
```

- Estado completo: Administración > Estado, o `https://SERVER_NAME/api/health/full`.
- Colas y tareas: `https://SERVER_NAME/flower/`.
- Avisos por correo: con `SMTP_HOST` y `EMAIL_FROM`, los avisos de prioridad alta o urgente
  sin leer se envían en menos de 2 minutos. Solo se envían los de las últimas 24 horas, así
  que activar el correo no manda el histórico.
