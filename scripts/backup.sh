#!/usr/bin/env bash
set -euo pipefail

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

export PGPASSWORD="${POSTGRES_PASSWORD}"
if ! restic snapshots >/dev/null 2>&1; then
  restic init
fi
pg_dump --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" --format=custom "${POSTGRES_DB}" \
  | restic backup --stdin --stdin-filename postgres.dump --tag sredi-database
restic backup /data/media --tag sredi-media
restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
restic check
