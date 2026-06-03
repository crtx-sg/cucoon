#!/bin/bash
# =============================================================================
#  Runs ONCE, automatically, on the very first Postgres boot (empty data dir).
#  Creates a cleanly partitioned database + least-privilege role per app, so
#  Postiz and Odysseus share one engine without sharing data.
#  Dropped into /docker-entrypoint-initdb.d/ by docker-compose.
# =============================================================================
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL
    -- ---- Odysseus -------------------------------------------------------
    CREATE ROLE ${ODYSSEUS_DB_USER} WITH LOGIN PASSWORD '${ODYSSEUS_DB_PASSWORD}';
    CREATE DATABASE odysseus OWNER ${ODYSSEUS_DB_USER};
    GRANT ALL PRIVILEGES ON DATABASE odysseus TO ${ODYSSEUS_DB_USER};

    -- ---- Postiz ---------------------------------------------------------
    CREATE ROLE ${POSTIZ_DB_USER} WITH LOGIN PASSWORD '${POSTIZ_DB_PASSWORD}';
    CREATE DATABASE postiz OWNER ${POSTIZ_DB_USER};
    GRANT ALL PRIVILEGES ON DATABASE postiz TO ${POSTIZ_DB_USER};
EOSQL

# Ensure schema-level privileges on each DB (PG15+ locks down public schema).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "odysseus" \
  -c "GRANT ALL ON SCHEMA public TO ${ODYSSEUS_DB_USER};"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postiz" \
  -c "GRANT ALL ON SCHEMA public TO ${POSTIZ_DB_USER};"

echo "[init] odysseus + postiz databases and roles created."
