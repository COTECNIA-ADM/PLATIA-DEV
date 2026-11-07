#!/usr/bin/env bash
# Restaura una copia de scripts/backup.sh. SUSTITUYE los datos actuales.
#
#   ./scripts/restore.sh backups/20261024-030000            # desarrollo
#   ./scripts/restore.sh backups/20261024-030000 --prod     # producción
#
# El .env de la copia no se restaura solo: si este servidor es nuevo, cópialo antes a
# mano (cp backups/.../env .env), porque los secretos MFA se cifraron con su clave.
set -euo pipefail
cd "$(dirname "$0")/.."

src="${1:?Uso: $0 backups/AAAAMMDD-HHMMSS [--prod]}"
COMPOSE=(docker compose -f docker-compose.yml)
APP=(nginx backend celery_default celery_ai celery_beat)
if [ "${2:-}" = "--prod" ]; then
  COMPOSE+=(-f docker-compose.prod.yml)
  APP+=(flower)
fi
# Con el gateway LLM, el servicio de IA no debe perder su red al rearrancar (ADR-019)
grep -qs '^LLM_GATEWAY_ENABLED=true' .env && COMPOSE+=(-f docker-compose.gateway.yml)
# Con n8n (ADR-020), sus flujos y credenciales vuelven con la copia si la trae
N8N=false
grep -qs '^N8N_ENABLED=true' .env && { N8N=true; COMPOSE+=(-f docker-compose.n8n.yml); APP+=(n8n); }
[ -f "$src/mysql.sql.gz" ] || { echo "No encuentro $src/mysql.sql.gz"; exit 1; }

read -r -p "Se borrarán los datos actuales y se cargará $src. Escribe RESTAURAR para seguir: " answer
[ "$answer" = "RESTAURAR" ] || { echo "Cancelado."; exit 1; }

echo "Parando la aplicación (los datos siguen arriba)..."
"${COMPOSE[@]}" stop "${APP[@]}"

echo "Base de datos (se borran y recrean los tres esquemas)..."
gunzip -c "$src/mysql.sql.gz" | "${COMPOSE[@]}" exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot'

echo "Documentos..."
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint sh backend \
  -c 'find /data/documents -mindepth 1 -delete && tar xzf - -C /data/documents' < "$src/documents.tgz"

if [ "$N8N" = true ] && [ -f "$src/n8n.tgz" ]; then
  echo "n8n..."
  "${COMPOSE[@]}" run --rm --no-deps -T --entrypoint sh n8n \
    -c 'find /home/node/.n8n -mindepth 1 -delete && tar xzf - -C /home/node/.n8n' < "$src/n8n.tgz"
fi

echo "Arrancando..."
"${COMPOSE[@]}" up -d --no-build
"${COMPOSE[@]}" exec -T backend flask reindex
echo "Restaurado. Los índices de búsqueda y de documentos se están regenerando en segundo plano."
