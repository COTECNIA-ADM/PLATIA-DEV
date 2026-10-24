#!/usr/bin/env bash
# Copia de seguridad (Capítulo 21): base de datos, documentos subidos y .env.
#
#   ./scripts/backup.sh            # entorno de desarrollo (docker-compose.yml)
#   ./scripts/backup.sh --prod     # producción (añade docker-compose.prod.yml)
#
# Deja una carpeta backups/AAAAMMDD-HHMMSS con:
#   mysql.sql.gz      los tres esquemas (volcado coherente, sin parar la plataforma)
#   documents.tgz     los ficheros subidos
#   env               el .env (sin él no se pueden descifrar los secretos MFA)
# Qdrant y Meilisearch no se copian: se regeneran desde MySQL con `flask reindex`.
# Borra las copias de más de BACKUP_KEEP_DAYS días (14 por defecto).
#
# La carpeta backups/ contiene datos personales y secretos: cópiala fuera del servidor
# (otro disco, almacenamiento de objetos cifrado) y restringe quién puede leerla.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f docker-compose.yml)
[ "${1:-}" = "--prod" ] && COMPOSE+=(-f docker-compose.prod.yml)
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"

umask 077
dest="backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$dest"

echo "Base de datos..."
"${COMPOSE[@]}" exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot \
  --single-transaction --routines --triggers --set-gtid-purged=OFF --add-drop-database \
  --databases "$DB_NAME_CORE" "$DB_NAME_OPS" "$DB_NAME_ANALYTICS"' | gzip > "$dest/mysql.sql.gz"

echo "Documentos..."
"${COMPOSE[@]}" exec -T backend tar czf - -C /data/documents . > "$dest/documents.tgz"

cp .env "$dest/env"

# Comprobación mínima: un volcado vacío o cortado no es una copia
gzip -t "$dest/mysql.sql.gz"
zcat "$dest/mysql.sql.gz" | tail -n 1 | grep -q "Dump completed" || { echo "El volcado de MySQL está incompleto"; exit 1; }

find backups -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +
echo "Copia en $dest ($(du -sh "$dest" | cut -f1))"
