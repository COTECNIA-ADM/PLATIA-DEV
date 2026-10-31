#!/usr/bin/env bash
# Despliega una versión en el servidor de producción (Capítulo 21). Lo llama el flujo
# «Despliegue» de GitHub Actions, o una persona a mano desde /opt/platia:
#
#   ./scripts/deploy.sh sha-1a2b3c4
#
# Pasos: copia de seguridad, descarga de imágenes, migraciones (el contenedor
# `migrations` va antes que el backend), arranque y comprobación de salud por HTTPS.
# Si la plataforma no responde sana en 3 minutos, vuelve a la versión anterior.
# Las migraciones no se deshacen solas: se escriben compatibles hacia atrás
# (añadir antes que borrar) y, si hiciera falta, está la copia recién hecha.
set -euo pipefail
cd "$(dirname "$0")/.."

# Se ejecuta desde una copia: la vuelta atrás cambia de commit y bash lee el script
# a medida que avanza, así que no puede ser el mismo fichero.
if [ -z "${PLATIA_DEPLOY_COPY:-}" ]; then
  copy="$(mktemp)"; cp "$0" "$copy"
  PLATIA_DEPLOY_COPY=1 exec bash "$copy" "$@"
fi

VERSION="${1:?Uso: $0 sha-xxxxxxx}"
[[ "$VERSION" =~ ^sha-[0-9a-f]{7}$ ]] || { echo "Versión no válida: $VERSION"; exit 1; }
set -a; source .env; set +a
: "${SERVER_NAME:?Falta SERVER_NAME en .env}"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
# Con el gateway LLM, el servicio de IA entra también en su red (ADR-019)
[ "${LLM_GATEWAY_ENABLED:-false}" = "true" ] && COMPOSE+=(-f docker-compose.gateway.yml)
mkdir -p .deploy
PREVIOUS="$(cat .deploy/current 2>/dev/null || true)"
PREVIOUS_COMMIT="$(cat .deploy/current_commit 2>/dev/null || true)"
log() { echo "[$(date +%H:%M:%S)] $*"; }

healthy() {
  for _ in $(seq 36); do
    if curl -fsS --max-time 5 --resolve "$SERVER_NAME:443:127.0.0.1" "https://$SERVER_NAME/api/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

up() {
  # La versión queda en .env para que los `docker compose` a mano usen la misma
  if grep -q '^PLATIA_VERSION=' .env; then
    sed -i "s/^PLATIA_VERSION=.*/PLATIA_VERSION=$1/" .env
  else
    echo "PLATIA_VERSION=$1" >> .env
  fi
  PLATIA_VERSION="$1" "${COMPOSE[@]}" pull --quiet
  PLATIA_VERSION="$1" "${COMPOSE[@]}" up -d --no-build --remove-orphans
}

log "Desplegando $VERSION (antes: ${PREVIOUS:-ninguna})"
if [ -n "$PREVIOUS" ]; then
  log "Copia de seguridad previa"
  ./scripts/backup.sh --prod
fi

if up "$VERSION" && healthy; then
  echo "$VERSION" > .deploy/current
  git rev-parse HEAD > .deploy/current_commit
  [ -n "$PREVIOUS" ] && echo "$PREVIOUS" > .deploy/previous
  docker image prune -f >/dev/null
  log "Desplegada $VERSION: https://$SERVER_NAME"
  exit 0
fi

log "ERROR: $VERSION no arranca sana"
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail 50 migrations backend || true
if [ -z "$PREVIOUS" ]; then
  log "No hay versión anterior a la que volver"
  exit 1
fi
log "Volviendo a $PREVIOUS"
git checkout --quiet "$PREVIOUS_COMMIT"
up "$PREVIOUS"
healthy && log "Restaurada $PREVIOUS" || log "ATENCIÓN: $PREVIOUS tampoco responde; revisa el servidor"
exit 1
