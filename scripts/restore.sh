#!/usr/bin/env bash
set -euo pipefail

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

if [[ "${CONFIRM_RESTORE:-}" != "RESTORE-${POSTGRES_DB}" ]]; then
  echo "Refusing restore. Set CONFIRM_RESTORE=RESTORE-${POSTGRES_DB}." >&2
  exit 2
fi

export PGPASSWORD="${POSTGRES_PASSWORD}"
restic dump latest --tag sredi-database postgres.dump \
  | pg_restore --clean --if-exists --no-owner --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" --dbname="${POSTGRES_DB}"
restic restore latest --tag sredi-media --target /restore --include /data/media
echo "Database restored. Review /restore/data/media before replacing the media volume."
