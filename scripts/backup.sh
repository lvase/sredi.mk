#!/usr/bin/env bash
set -euo pipefail

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

case "${RESTIC_REPOSITORY}" in
  s3:*|sftp:*|rest:*|b2:*|azure:*|gs:*|rclone:*) ;;
  *)
    if [[ "${ALLOW_LOCAL_BACKUP:-false}" != "true" ]]; then
      echo "Configure an off-host RESTIC_REPOSITORY; ALLOW_LOCAL_BACKUP=true is for disposable tests only." >&2
      exit 2
    fi
    ;;
esac

BACKUP_RUN_ID="${BACKUP_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
MEDIA_LOCK_ID="${MEDIA_MAINTENANCE_LOCK_ID:-734733}"
STAGING_DIR="${BACKUP_STAGING_DIR:-/tmp/sredi-backup-staging}"
LOCK_READY_FILE="${STAGING_DIR}/advisory-lock-ready"
MIN_FREE_BYTES="${BACKUP_MIN_FREE_BYTES:-2147483648}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

if [[ ! "${MEDIA_LOCK_ID}" =~ ^-?[0-9]+$ ]]; then
  echo "MEDIA_MAINTENANCE_LOCK_ID must be an integer." >&2
  exit 2
fi

available_bytes="$(df -Pk /tmp | awk 'NR == 2 {printf "%.0f\n", $4 * 1024}')"
if (( available_bytes < MIN_FREE_BYTES )); then
  echo "Insufficient free staging space for backup." >&2
  exit 3
fi

mkdir -p "${STAGING_DIR}"
lock_pid=""
work_pid=""
cleanup() {
  if [[ -n "${work_pid}" ]]; then
    kill "${work_pid}" >/dev/null 2>&1 || true
    wait "${work_pid}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${lock_pid}" ]]; then
    kill "${lock_pid}" >/dev/null 2>&1 || true
    wait "${lock_pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${STAGING_DIR}/postgres.dump" "${LOCK_READY_FILE}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

run_locked() {
  "$@" &
  work_pid="$!"
  while kill -0 "${work_pid}" 2>/dev/null; do
    if ! kill -0 "${lock_pid}" 2>/dev/null; then
      echo "Backup aborted: media-maintenance lock connection was lost." >&2
      return 4
    fi
    sleep 1
  done
  wait "${work_pid}"
  work_pid=""
  kill -0 "${lock_pid}" 2>/dev/null || { echo "Backup lock was lost." >&2; return 4; }
}

if ! restic snapshots >/dev/null 2>&1; then
  restic init
fi

rm -f "${LOCK_READY_FILE}"
(
  printf 'SET statement_timeout = 0;\n'
  printf 'SELECT 1 / CASE WHEN pg_try_advisory_lock(%s) THEN 1 ELSE 0 END;\n' "${MEDIA_LOCK_ID}"
  printf '\\! touch %s\n' "${LOCK_READY_FILE}"
  printf 'SELECT pg_sleep(86400);\n'
) | psql -X --set=ON_ERROR_STOP=1 --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" \
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

run_locked pg_dump --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" --format=custom \
  --compress=9 --file="${STAGING_DIR}/postgres.dump" "${POSTGRES_DB}"

run_locked restic backup "${STAGING_DIR}/postgres.dump" /data/media \
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
