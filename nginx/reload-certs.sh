#!/bin/sh
# Recarga nginx cada 6 horas para que use el certificado renovado (Let's Encrypt
# renueva en el contenedor certbot). Recargar no corta las conexiones abiertas.
(while sleep 21600; do nginx -s reload; done) &
