# Pilot Operations Runbook

This runbook covers the single-Ubuntu-VPS pilot stack in `docker-compose.prod.yml`. Development Compose remains separate and unchanged.

## First deployment

1. Copy `.env.production.example` to `.env.production`, replace every placeholder, and keep that file off Git.
2. Point the domain's A/AAAA records at the VPS. Open only SSH, TCP 80, and TCP 443. PostgreSQL has no published host port.
3. Issue the first certificate while Nginx is stopped:

   ```bash
   docker compose -f docker-compose.prod.yml --profile tools run --rm --service-ports certbot-issue
   ```

4. Start the stack. The mandatory `migrate` service applies migration `0006` and all later migrations before Django, Celery, or Nginx can become ready:

   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```

5. Verify `/health/live/`, `/health/ready/`, SPA fallback, `/admin/`, response security headers, and that `/media/...` returns 404. Approved crests are served only through `/api/municipalities/<slug>/crest/`; issue attachments require an authenticated staff API request.
6. Send a real SMTP probe:

   ```bash
   docker compose -f docker-compose.prod.yml exec app python manage.py test_email --to ops@example.mk
   ```

Production startup rejects debug mode, the development secret, console email, wildcard/local hosts, missing SMTP settings, and non-HTTPS CSRF origins. Start HSTS at 300 seconds; increase it in stages only after HTTPS renewal has been proven.

## Backups and restore

Run the encrypted Restic job daily from systemd/cron:

```bash
docker compose -f docker-compose.prod.yml --profile tools run --rm backup
```

The job prints `<snapshot-id> <run-id>` and creates one Restic snapshot containing both a custom-format PostgreSQL dump and private media. It holds the media-maintenance advisory lock while creating that snapshot, then retains 7 daily, 4 weekly, and 6 monthly snapshots. Restic credentials and the encryption password belong only in `.env.production`; keep an offline copy of the password.

Before launch and after infrastructure changes, verify the exact snapshot ID printed by the backup:

```bash
RESTIC_SNAPSHOT_ID=<snapshot-id> docker compose -f docker-compose.prod.yml \
  --profile tools run --rm restore-verify
```

Verification restores that one snapshot to a temporary database and staging directory, checks every active attachment row against its file and expected size, samples repository data, and then cleans up. Never run the `restore` service against production without a change window, an explicit `RESTIC_SNAPSHOT_ID`, a fresh snapshot, and `CONFIRM_RESTORE=RESTORE-<database>`.

The bundled `/data/restic` repository is on the same VPS and is only a temporary recovery copy—not disaster recovery. Move the repository off-host before onboarding a second municipality or before filesystem use reaches 50%, whichever occurs first. Keep local media through the 320 GB upgrade; move it to S3-compatible storage at 160 GB of media, when application servers are replicated, or when off-host disaster recovery becomes mandatory.

## Account recovery

The platform superuser can reset ordinary staff 2FA from the API. If the sole superuser loses every factor, use the VPS console only:

```bash
docker compose -f docker-compose.prod.yml exec \
  -e ENABLE_EMERGENCY_2FA_RESET=true app \
  python manage.py emergency_reset_superuser_2fa owner --confirm RESET-owner
```

Unset the flag immediately. The next superuser login requires fresh enrollment. Password changes, 2FA resets, recovery-code regeneration, and repeated suspicious authentication failures revoke trusted devices.

## Routine operations

- Use JSON application logs and `/health/*` probes; request IDs are returned in `X-Request-ID`. Logs omit query strings, request bodies, contacts, tracking codes, and uploaded content.
- Review attachment use without changing data with `python manage.py media_usage`. Monitor the media filesystem separately and alert at approximately 70%, 80%, and 90% use; storage warnings must not make the normal readiness probe fail.
- Review audit records for public-title moderation, account changes, and workflow changes.
- Confirm certificate renewal and Restic snapshot age weekly. Test an isolated restore monthly.
- If a staff account is compromised, disable it, rotate its password, reset 2FA, and review audit history.
- Legal/privacy drafts, settlement lists, retention rules, branding, and municipal contacts still require formal approval before launch.

## Existing attachment reduction

New uploads are normalized synchronously to metadata-free WebP files (2048 px longest edge, 800 KiB maximum). Reprocess legacy attachments only after both a successful Restic backup and a successful `restore-verify` run:

```bash
docker compose -f docker-compose.prod.yml exec app \
  python manage.py reprocess_issue_attachments --dry-run --batch-size 100
docker compose -f docker-compose.prod.yml exec app \
  python manage.py reprocess_issue_attachments --apply --batch-size 100
```

The command processes at most one batch, reports its last attachment ID, and prints the `--resume-from` value for the next batch. `--municipality <slug>` narrows a run. Invalid files remain untouched; successfully committed replacements delete the old file afterward. Repeating the command skips rows already marked with the current processing version.

Before rollout, benchmark five representative high-resolution images on the target VPS. The operational target is less than 10 seconds per five-image submission and less than 400 MB peak image-processing RSS. Deploy code and schema first, verify new uploads, then migrate old media in batches. Compare `media_usage`, filesystem use, and Restic snapshot size before and after. Reserve disk capacity for PostgreSQL, Docker layers, logs, temporary image processing, backups, and deploy operations.

## Scalability profile

Use a disposable database to seed either target dataset, then run the checked-in k6 profile with 20 concurrent public visitors, a five-request upload burst, and (when a session cookie is supplied) the staff inbox:

```bash
python manage.py seed_load_profile --municipality konce --reports 5200 --confirm SEED-konce-5200
k6 run -e BASE_URL=https://staging.example.mk -e MUNICIPALITY_SLUG=konce \
  -e SETTLEMENT_ID=1 -e CATEGORY_ID=1 -e TRACKING_CODE=<code> load/k6.js
```

Repeat with `--reports 78000 --confirm SEED-konce-78000`. Raise only the staging submission throttle for the controlled upload scenario. Record host memory, image-process RSS, queue depth, filesystem use, orphan-file checks, worker restarts, and k6 p95 results; do not reuse the generated reports in production.
