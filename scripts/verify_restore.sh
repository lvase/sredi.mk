#!/usr/bin/env bash
set -euo pipefail

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

VERIFY_DB="sredi_restore_verify_$(date +%s)"
export PGPASSWORD="${POSTGRES_PASSWORD}"
cleanup() { dropdb --if-exists --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" "${VERIFY_DB}"; }
trap cleanup EXIT
createdb --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" "${VERIFY_DB}"
restic dump latest --tag sredi-database postgres.dump \
  | pg_restore --no-owner --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" --dbname="${VERIFY_DB}"
psql --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" --dbname="${VERIFY_DB}" \
  --command="SELECT COUNT(*) AS municipalities FROM municipalities_municipality;"
restic check --read-data-subset=5%
echo "Isolated restore verification passed; the temporary database will now be removed."
