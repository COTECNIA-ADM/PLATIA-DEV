#!/bin/bash
# Crea los tres esquemas de la Plataforma (Capítulo 5, Apéndice A) y da permisos
# al usuario de la aplicación solo sobre ellos. Lo ejecuta la imagen de MySQL
# una única vez, cuando el volumen de datos está vacío.
set -euo pipefail

mysql --protocol=socket -uroot -p"${MYSQL_ROOT_PASSWORD}" <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME_CORE}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS \`${DB_NAME_OPS}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS \`${DB_NAME_ANALYTICS}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
GRANT ALL PRIVILEGES ON \`${DB_NAME_CORE}\`.* TO '${MYSQL_USER}'@'%';
GRANT ALL PRIVILEGES ON \`${DB_NAME_OPS}\`.* TO '${MYSQL_USER}'@'%';
GRANT ALL PRIVILEGES ON \`${DB_NAME_ANALYTICS}\`.* TO '${MYSQL_USER}'@'%';
FLUSH PRIVILEGES;
SQL
