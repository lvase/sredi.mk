#!/usr/bin/env bash
set -euo pipefail

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
: "${RESTIC_SNAPSHOT_ID:?RESTIC_SNAPSHOT_ID is required; do not use latest}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

VERIFY_DB="sredi_restore_verify_$(date +%s)"
VERIFY_DIR="/tmp/sredi-restore-verify"
MIN_FREE_BYTES="${RESTORE_MIN_FREE_BYTES:-2147483648}"
export PGPASSWORD="${POSTGRES_PASSWORD}"
cleanup() {
  dropdb --if-exists --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" "${VERIFY_DB}" >/dev/null 2>&1 || true
  rm -rf "${VERIFY_DIR}"
}
trap cleanup EXIT

available_bytes="$(df -Pk /tmp | awk 'NR == 2 {print $4 * 1024}')"
if (( available_bytes < MIN_FREE_BYTES )); then
  echo "Insufficient free verification staging space." >&2
  exit 3
fi

mkdir -p "${VERIFY_DIR}"
createdb --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" "${VERIFY_DB}"
restic dump "${RESTIC_SNAPSHOT_ID}" /tmp/sredi-backup-staging/postgres.dump \
  | pg_restore --no-owner --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" --dbname="${VERIFY_DB}"
restic restore "${RESTIC_SNAPSHOT_ID}" --target "${VERIFY_DIR}" --include /data/media

missing=0
while IFS='|' read -r image_name expected_size; do
  file_path="${VERIFY_DIR}/data/media/${image_name}"
  if [[ ! -f "${file_path}" ]]; then
    echo "Missing active attachment object: ${image_name}" >&2
    missing=$((missing + 1))
    continue
  fi
  actual_size="$(stat -c %s "${file_path}")"
  if [[ -n "${expected_size}" && "${actual_size}" != "${expected_size}" ]]; then
    echo "Attachment size mismatch: ${image_name}" >&2
    missing=$((missing + 1))
  fi
done < <(psql --host="${POSTGRES_HOST:-db}" --username="${POSTGRES_USER}" --dbname="${VERIFY_DB}" --tuples-only --no-align --field-separator='|' --command="SELECT image, COALESCE(stored_size_bytes::text, '') FROM issues_issueattachment WHERE deletion_state = 'active';")

if (( missing > 0 )); then
  echo "Restore verification failed for ${missing} active attachment(s)." >&2
  exit 4
fi
restic check --read-data-subset=5%
echo "Snapshot ${RESTIC_SNAPSHOT_ID} restore verification passed."
