# Pilot Operations Runbook

This runbook covers the single-Ubuntu-VPS pilot stack in `docker-compose.prod.yml`. Development Compose remains separate and unchanged.

## First deployment

1. Copy `.env.production.example` to `.env.production`, replace every placeholder, and keep that file off Git.
2. Point the domain's A/AAAA records at the VPS. Open only SSH, TCP 80, and TCP 443. PostgreSQL has no published host port.
3. Issue the first certificate while Nginx is stopped:

   ```bash
   docker compose -f docker-compose.prod.yml --profile tools run --rm --service-ports certbot-issue
   ```

4. Apply migrations, then start the application:

   ```bash
   docker compose -f docker-compose.prod.yml --profile tools run --rm migrate
   docker compose -f docker-compose.prod.yml up -d app nginx certbot db
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

The job backs up a custom-format PostgreSQL dump and the private media volume, then retains 7 daily, 4 weekly, and 6 monthly snapshots. Restic credentials and the encryption password belong only in `.env.production`; keep an offline copy of the password.

Before launch and after infrastructure changes, run `docker compose -f docker-compose.prod.yml --profile tools run --rm restore-verify`. It restores to a uniquely named temporary database, runs a sanity query, samples repository data, and removes the temporary database. Never run the `restore` service against production without a change window, a fresh snapshot, and `CONFIRM_RESTORE=RESTORE-<database>`.

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
- Review audit records for public-title moderation, account changes, and workflow changes.
- Confirm certificate renewal and Restic snapshot age weekly. Test an isolated restore monthly.
- If a staff account is compromised, disable it, rotate its password, reset 2FA, and review audit history.
- Legal/privacy drafts, settlement lists, retention rules, branding, and municipal contacts still require formal approval before launch.
