#!/usr/bin/env bash
# Runs once, as the postgres superuser, on first container start.
#
# Role model (least privilege):
#   zuschlag_migrator  owns the schema and runs Alembic. NOSUPERUSER, NOBYPASSRLS.
#   zuschlag_app       runtime role for the API. Not the table owner, NOBYPASSRLS,
#                      so every query is subject to row-level security.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username postgres --dbname postgres \
  -v db="$ZUSCHLAG_DB_NAME" \
  -v migrator_pw="$ZUSCHLAG_MIGRATOR_PASSWORD" \
  -v app_pw="$ZUSCHLAG_APP_PASSWORD" <<'SQL'
CREATE ROLE zuschlag_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'migrator_pw';
CREATE ROLE zuschlag_app      LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'app_pw';
CREATE DATABASE :"db" OWNER zuschlag_migrator ENCODING 'UTF8' TEMPLATE template0;
SQL

psql -v ON_ERROR_STOP=1 --username postgres --dbname "$ZUSCHLAG_DB_NAME" <<'SQL'
-- Extensions need superuser; create them here so migrations don't.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO zuschlag_migrator;
GRANT USAGE ON SCHEMA public TO zuschlag_app;
SQL
