# Pilot Operations Runbook

This runbook covers the single-Ubuntu-VPS pilot stack in `docker-compose.prod.yml`. Development Compose remains separate and unchanged.

## Text-only pilot

Migration `municipalities.0005_municipality_photo_uploads_enabled` adds a per-municipality switch with `False` as the default for existing and new municipalities. Keep it off for every pilot municipality. Verify the `photo_uploads_enabled` value returned by `/api/municipalities/<slug>/form-options/` before onboarding.

The React and legacy Django forms hide photo uploads when the switch is off. Both submission paths reject uploaded files before image processing or report creation; text-only React submissions use JSON. Existing attachments, private download permissions, retention rules, and backups are preserved. Municipal crests are not citizen photo uploads and remain supported.

For a later photo-enabled offering, explicitly enable the municipality's **Овозможи фотографии во пријави** setting in Django admin only after updating the public policy/copy, agreeing the service scope, and validating storage, backup, and image-processing capacity. Existing image-processing tests cover the enabled path. Do not delete attachment tables, historical migrations, or stored files to turn off uploads.

The image benchmarking instructions below apply only when preparing that later offering. The k6 profile covers text submissions for the pilot; photo-enabled capacity requires a separate representative upload benchmark. Redis and Celery still support shared throttles, caches, email delivery, and existing-data maintenance; removing photos does not remove these responsibilities.

## First deployment

1. Copy `.env.production.example` to `.env.production`, replace every placeholder, and keep that file off Git. Remove any old `ENV_FILE=.env.production.example` assignment from existing copies. Set `DOMAIN` to the public DNS hostname (no scheme, port, or path), include that exact hostname in `DJANGO_ALLOWED_HOSTS`, and include `https://<DOMAIN>` in `CSRF_TRUSTED_ORIGINS`.

   Every production command must use `--env-file .env.production`: this loads Compose substitutions such as the Nginx domain and certificate email. The service-level `env_file` separately loads application credentials. Validate configuration without printing secrets before issuing certificates or starting services:

   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
   ```

   Unset conflicting exported deployment variables first: shell variables take precedence over the selected env file. For a custom env file, select the same file for both mechanisms, for example `ENV_FILE=/secure/sredi.env docker compose --env-file /secure/sredi.env -f docker-compose.prod.yml config --quiet`. Run production commands from the repository root. Compose validation checks required substitutions; Django checks the domain/allowed-host/CSRF relationship when the application starts.
2. Point the domain's A/AAAA records at the VPS. Open only SSH, TCP 80, and TCP 443. PostgreSQL has no published host port.
3. Issue the first certificate while Nginx is stopped:

   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml --profile tools run --rm --service-ports certbot-issue
   ```

4. Start the stack. The mandatory `migrate` service applies migration `0006` and all later migrations before Django, Celery, or Nginx can become ready:

   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml up -d
   ```

5. Verify `/health/live/`, `/health/ready/`, SPA fallback, `/admin/`, response security headers, and that `/media/...` returns 404. Approved crests are served only through `/api/municipalities/<slug>/crest/`; issue attachments require an authenticated staff API request.
6. Send a real SMTP probe:

   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml exec app python manage.py test_email --to ops@example.mk
   ```

Schedule renewal twice daily on the host (run from the deployed checkout):

```cron
0 */12 * * * cd /srv/sredi && ./scripts/renew_certificates.sh >> /var/log/sredi-renewal.log 2>&1
```

The one-shot Certbot service renews certificates, then the script validates and gracefully reloads Nginx. A renewal or validation failure exits nonzero. Monitor the scheduled job and the certificate served externally; running `docker compose up` alone does not schedule renewals.

Production startup rejects debug mode, the development secret, console email, wildcard/local hosts, missing SMTP settings, non-HTTPS CSRF origins, an invalid domain, or a domain missing from the allowed hosts or trusted HTTPS origins. Start HSTS at 300 seconds; increase it in stages only after HTTPS renewal has been proven.

## Backups and restore

Run the encrypted Restic job daily from systemd/cron:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml --profile tools run --rm backup
```

The job prints `<snapshot-id> <run-id>` and creates one Restic snapshot containing both a custom-format PostgreSQL dump and private media. It holds the media-maintenance advisory lock while creating that snapshot, then retains 7 daily, 4 weekly, and 6 monthly snapshots. Restic credentials and the encryption password belong only in `.env.production`; keep an offline copy of the password.

Before launch and after infrastructure changes, verify the exact snapshot ID printed by the backup:

```bash
RESTIC_SNAPSHOT_ID=<snapshot-id> docker compose --env-file .env.production -f docker-compose.prod.yml \
  --profile tools run --rm restore-verify
```

Verification restores that one snapshot to a temporary database and staging directory, checks every active attachment row against its file and expected size, samples repository data, and then cleans up. Never run the `restore` service against production without a change window, an explicit `RESTIC_SNAPSHOT_ID`, a fresh snapshot, and `CONFIRM_RESTORE=RESTORE-<database>`.

Configure the off-host Restic repository before launch. The example uses an S3-compatible endpoint; replace its endpoint, bucket, access key, secret key, and independent encryption password with real backup credentials. Create the bucket and scope its credentials to that backup location. Local repositories are refused unless `ALLOW_LOCAL_BACKUP=true` is explicitly supplied for a disposable test. The `/data/restic` volume is retained for compatibility, but the production example no longer stores the only backup on the application server. Keep a separate offline copy of the Restic password.

The backup lock holder disables its statement timeout and fails immediately if another maintenance job owns the lock. The job monitors that connection throughout the dump and media snapshot, aborting if it dies. Restore verification now fails on PostgreSQL restore/query errors rather than treating an empty attachment list as success.

## Account recovery

The platform superuser can reset ordinary staff 2FA from the API. If the sole superuser loses every factor, use the VPS console only:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec \
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
docker compose --env-file .env.production -f docker-compose.prod.yml exec app \
  python manage.py reprocess_issue_attachments --dry-run --batch-size 100
docker compose --env-file .env.production -f docker-compose.prod.yml exec app \
  python manage.py reprocess_issue_attachments --apply --batch-size 100
```

The command processes at most one batch, reports its last attachment ID, and prints the `--resume-from` value for the next batch. `--municipality <slug>` narrows a run. Invalid files remain untouched; successfully committed replacements delete the old file afterward. Repeating the command skips rows already marked with the current processing version.

Before rollout, benchmark five representative high-resolution images on the target VPS. The operational target is less than 10 seconds per five-image submission and less than 400 MB peak image-processing RSS. Deploy code and schema first, verify new uploads, then migrate old media in batches. Compare `media_usage`, filesystem use, and Restic snapshot size before and after. Reserve disk capacity for PostgreSQL, Docker layers, logs, temporary image processing, backups, and deploy operations.

## Scalability and outage checks

The repeatable production integration test runs on an isolated project with disposable volumes, generated secrets, a temporary self-signed certificate, and no published host ports:

```bash
python3 scripts/test_production_startup.py --smoke
```

It needs Docker Compose 2.24.4+, Python 3, and OpenSSL. It builds the actual production images, applies migrations, verifies the configured health probe and HTTPS through Nginx, seeds 78,000 synthetic reports, runs cold/warm 100-request mixed bursts, and submits 20 concurrent reports from one shared IP followed by retries. It requires exactly 20 new report/outbox rows. A real Redis/Celery worker delivers receipts using an in-memory test mail backend. It stops Redis, verifies submissions fail closed without creating data, restarts Redis, and verifies readiness recovers. It also delays a real backup beyond the old 15-second database timeout, then verifies restoration from its encrypted snapshot in a disposable local repository. No public certificate or external email is requested. The 100-request read-burst acceptance threshold is p95 below five seconds on the test host; record the actual result on the target VPS.

For a longer disposable staging run:

```bash
python manage.py seed_load_profile --municipality konce --reports 78000 --confirm SEED-konce-78000
k6 run -e BASE_URL=https://staging.example.mk -e MUNICIPALITY_SLUG=konce \
  -e SETTLEMENT_ID=1 -e CATEGORY_ID=1 -e SUBMISSION_COUNT=20 load/k6.js
```

The k6 profile starts with 100 simultaneous reads, then paces reads at three requests/second for five minutes. Submissions are opt-in and replay the same key to verify deduplication. `STAFF_SESSION_COOKIE` adds authenticated inbox requests. `CHECK_THROTTLING=1` separately checks the per-browser quota; it needs settlement/category IDs and must run without exhausting that network's quota first. Expected 429 responses in that scenario are distinguished from failures. Keep production limits enabled for shared-IP tests. For sustained capacity above the per-IP edge limit, use multiple authorized load-generator addresses or explicitly raise only staging edge limits; never trust a fabricated forwarding header.

Record p95 latency, unexpected 429/5xx responses, PostgreSQL connections, container RSS/restarts, Redis `used_memory`, `used_memory_rss`, `maxmemory` and rejected writes, receipt queue age, and disk usage. The Redis container reserves 384 MiB around a 192 MiB data limit; tune from measured RSS including persistence overhead. Cache and broker sockets use bounded timeouts. Existing two-worker Gunicorn and 40-connection PostgreSQL limits remain in place pending measurements on the production server.

## Submission and authentication reliability

All staff APIs and legacy staff views require completed authentication: mandatory password changes and any required second factor cannot be bypassed by an old password-only session. Alternate Django login URLs redirect to the main login flow.

The citizen UI sends a random UUID `submission_key`; API clients may send `Idempotency-Key` instead. Repeating a key with the same data returns the original report (201), even after the submission quota is reached. Reusing it with different data returns 409. Keys are municipality-scoped and enforced by a database uniqueness constraint. The legacy form also supplies a key. Clients that omit a key retain the old behavior and cannot safely retry. The browser keeps its key and receipt in session storage until the tab closes or the citizen explicitly starts a new report; contact details are not stored with the receipt. If browser storage is disabled, retries within the open page still retain their key.

A signed anonymous browser cookie separates people sharing an IP. Defaults are three attempts/hour and ten/day per browser, plus 100/hour and 500/day for the shared municipality/IP. Clients without the cookie fall back to the stricter IP quota. All counters fail closed on Redis failure. Tune the documented environment variables against observed legitimate traffic; rotating cookies cannot bypass the aggregate IP limit. The frontend honors both API cooldown metadata and the edge proxy's Retry-After header.

## Receipt delivery and monitoring

Report and receipt-outbox creation commit together. HTTP requests never publish email jobs to Redis. Beat dispatches due rows every minute; broker publication failures, lost messages, and abandoned worker leases remain recoverable. Workers serialize delivery with a database lease and persist retry backoff. Six failed send attempts mark a delivery failed. SMTP cannot provide exactly-once delivery: a process crash after SMTP acceptance but before recording success can still cause a duplicate email.

Monitor `/health/ready/` externally: database/Redis failures return 503; `dependencies.receipts` exposes pending/failed counts and oldest queued age without citizen data. Alert if receipt status is warning, queue age exceeds ten minutes, a scheduled backup is over 24 hours old, or TLS expiry is approaching. The worker also logs queue warnings and attempts operational email alerts, but external monitoring is necessary when the worker or SMTP itself is unavailable.

After resolving a delivery incident, superusers can retry selected failed deliveries through the ReceiptDelivery admin action. Verify queued rows return to sent. Public statistics cache locks suppress duplicate cold calculations and release on failure; brief contention returns 503 with Retry-After. Staff metrics refresh within 15 seconds; assignment choices refresh within 30 seconds and invalidate immediately for configuration changes.

## Rollout

Back up and verify a restore before deploying. Migration `issues.0009_submission_recovery_and_search` adds retry/outbox metadata and replaces the search indexes with matching uppercase trigram expressions. It also requeues historical publication failures that never attempted an SMTP send. Apply it through the existing migration service before app/worker startup. Deploy app, worker, and beat together; an old worker cannot safely process the new outbox behavior. Configure the off-host repository and host renewal schedule, then run readiness, a real SMTP probe, and a restore verification before onboarding users.

For an existing deployment, use a maintenance window after the verified backup:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop nginx app worker beat
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm migrate
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

If building or migrating fails, resolve that failure before restarting application services. Index replacement runs inside the migration transaction and can block writes; do not run this migration against an active deployment without the maintenance window.

Local Docker regression sample with 78,000 synthetic reports: 100 simultaneous cold reads all returned 200 (p95 1.10 s), as did 100 warm reads (p95 0.86 s). Twenty concurrent report submissions plus retries produced exactly twenty reports and twenty delivered outbox entries. These measurements validate the tested configuration on the development machine; repeat them on the target VPS before launch.

Run `python3 scripts/test_production_startup.py` for configuration-only checks and `python3 scripts/test_operations.py` for maintenance failure checks. Both avoid contacting production services.
