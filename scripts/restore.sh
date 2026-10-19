#!/usr/bin/env bash
set -euo pipefail

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
: "${RESTIC_SNAPSHOT_ID:?RESTIC_SNAPSHOT_ID is required; do not use latest}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

if [[ "${CONFIRM_RESTORE:-}" != "RESTORE-${POSTGRES_DB}" ]]; then
  echo "Refusing restore. Set CONFIRM_RESTORE=RESTORE-${POSTGRES_DB}." >&2
  exit 2
fi

MIN_FREE_BYTES="${RESTORE_MIN_FREE_BYTES:-2147483648}"
available_bytes="$(df -Pk /restore | awk 'NR == 2 {print $4 * 1024}')"
if (( available_bytes < MIN_FREE_BYTES )); then
  echo "Insufficient free restore staging space." >&2
  exit 3
fi

export PGPASSWORD="${POSTGRES_PASSWORD}"
restic dump "${RESTIC_SNAPSHOT_ID}" /tmp/sredi-backup-staging/postgres.dump \
  | pg_restore --clean --if-exists --no-owner --host="${POSTGRES_HOST:-db}" \
      --username="${POSTGRES_USER}" --dbname="${POSTGRES_DB}"
restic restore "${RESTIC_SNAPSHOT_ID}" --target /restore --include /data/media
echo "Snapshot ${RESTIC_SNAPSHOT_ID} restored. Review /restore/data/media before replacing media."
