#!/usr/bin/env bash
set -euo pipefail

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

BACKUP_RUN_ID="${BACKUP_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
MEDIA_LOCK_ID="${MEDIA_MAINTENANCE_LOCK_ID:-734733}"
STAGING_DIR="/tmp/sredi-backup-staging"
LOCK_READY_FILE="${STAGING_DIR}/advisory-lock-ready"
MIN_FREE_BYTES="${BACKUP_MIN_FREE_BYTES:-2147483648}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

if [[ ! "${MEDIA_LOCK_ID}" =~ ^-?[0-9]+$ ]]; then
  echo "MEDIA_MAINTENANCE_LOCK_ID must be an integer." >&2
  exit 2
fi

available_bytes="$(df -Pk /tmp | awk 'NR == 2 {print $4 * 1024}')"
if (( available_bytes < MIN_FREE_BYTES )); then
  echo "Insufficient free staging space for backup." >&2
  exit 3
fi

mkdir -p "${STAGING_DIR}"
lock_pid=""
cleanup() {
  if [[ -n "${lock_pid}" ]]; then
    kill "${lock_pid}" >/dev/null 2>&1 || true
    wait "${lock_pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${STAGING_DIR}/postgres.dump" "${LOCK_READY_FILE}"
}
trap cleanup EXIT

if ! restic snapshots >/dev/null 2>&1; then
  restic init
fi

rm -f "${LOCK_READY_FILE}"
(
  printf 'SELECT pg_advisory_lock(%s);\n' "${MEDIA_LOCK_ID}"
  printf '\\! touch %s\n' "${LOCK_READY_FILE}"
  printf 'SELECT pg_sleep(86400);\n'
) | psql --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DB}" >/dev/null 2>&1 &
lock_pid="$!"

for _ in $(seq 1 50); do
  if [[ -f "${LOCK_READY_FILE}" ]]; then
    break
  fi
  sleep 0.1
done
if [[ ! -f "${LOCK_READY_FILE}" ]]; then
  echo "Could not acquire media-maintenance advisory lock." >&2
  exit 4
fi

pg_dump --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" --format=custom \
  --compress=9 --file="${STAGING_DIR}/postgres.dump" "${POSTGRES_DB}"

restic backup "${STAGING_DIR}/postgres.dump" /data/media \
  --tag sredi-consistent --tag "run:${BACKUP_RUN_ID}"
snapshot_id="$(restic snapshots --tag "run:${BACKUP_RUN_ID}" --latest 1 --json | tr -d '\n' | sed -n 's/.*"short_id":"\([^"]*\)".*/\1/p')"
if [[ -z "${snapshot_id}" ]]; then
  echo "Backup completed but its snapshot ID could not be determined." >&2
  exit 5
fi
echo "${snapshot_id} ${BACKUP_RUN_ID}"

kill "${lock_pid}" >/dev/null 2>&1 || true
wait "${lock_pid}" >/dev/null 2>&1 || true
lock_pid=""

restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
restic check
