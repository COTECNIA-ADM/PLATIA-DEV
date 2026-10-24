#!/usr/bin/env bash
# Primer certificado de Let's Encrypt (Capítulo 21). Se ejecuta una vez en el servidor,
# con el dominio ya apuntando a él y los puertos 80 y 443 abiertos:
#
#   ./scripts/init_letsencrypt.sh correo-de-avisos@tuempresa.com
#
# 1. Crea un certificado provisional autofirmado para que nginx pueda arrancar.
# 2. Pide el certificado real por el reto HTTP (webroot) y lo copia a certs/.
# 3. Recarga nginx y deja arrancado el contenedor certbot, que lo renueva solo.
set -euo pipefail
cd "$(dirname "$0")/.."

EMAIL="${1:?Uso: $0 correo@empresa.com}"
set -a; source .env; set +a
: "${SERVER_NAME:?Falta SERVER_NAME en .env}"
CERTS_DIR="${CERTS_DIR:-./certs}"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)

mkdir -p "$CERTS_DIR"
if [ ! -f "$CERTS_DIR/fullchain.pem" ]; then
  echo "Certificado provisional para $SERVER_NAME"
  openssl req -x509 -nodes -newkey rsa:2048 -days 2 -subj "/CN=$SERVER_NAME" \
    -keyout "$CERTS_DIR/privkey.pem" -out "$CERTS_DIR/fullchain.pem" >/dev/null 2>&1
fi

"${COMPOSE[@]}" up -d --no-build --no-deps nginx  # solo nginx: los upstream se resuelven al llegar cada petición

echo "Pidiendo el certificado a Let's Encrypt"
"${COMPOSE[@]}" --profile letsencrypt run --rm --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot -d "$SERVER_NAME" \
  --email "$EMAIL" --agree-tos --no-eff-email --non-interactive

"${COMPOSE[@]}" --profile letsencrypt run --rm --entrypoint sh certbot \
  -c "cp -L /etc/letsencrypt/live/$SERVER_NAME/fullchain.pem /etc/letsencrypt/live/$SERVER_NAME/privkey.pem /certs/"

"${COMPOSE[@]}" exec nginx nginx -s reload
"${COMPOSE[@]}" --profile letsencrypt up -d certbot
echo "Listo: https://$SERVER_NAME"
