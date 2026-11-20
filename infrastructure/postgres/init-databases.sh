#!/bin/bash
# Выполняется один раз при первом запуске контейнера PostgreSQL.
# Database per service: у каждого сервиса своя база и свой пользователь,
# чужие базы ему недоступны (REVOKE CONNECT ... FROM PUBLIC).
set -euo pipefail

create_db() {
  local user="$1" db="$2" password="$3"
  echo "Creating database ${db} for user ${user}"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    CREATE USER ${user} WITH PASSWORD '${password}';
    CREATE DATABASE ${db} OWNER ${user};
    REVOKE CONNECT ON DATABASE ${db} FROM PUBLIC;
    GRANT CONNECT ON DATABASE ${db} TO ${user};
EOSQL
}

create_db auth         auth_db         "${AUTH_DB_PASSWORD}"
create_db restaurant   restaurant_db   "${RESTAURANT_DB_PASSWORD}"
create_db orders       order_db        "${ORDER_DB_PASSWORD}"
create_db payment      payment_db      "${PAYMENT_DB_PASSWORD}"
create_db delivery     delivery_db     "${DELIVERY_DB_PASSWORD}"
create_db notification notification_db "${NOTIFICATION_DB_PASSWORD}"
create_db review       review_db       "${REVIEW_DB_PASSWORD}"
