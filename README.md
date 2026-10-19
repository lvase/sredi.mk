# Opštinski Inbox / Sredi

**Opštinski Inbox** is the municipality-facing workflow system.
**Sredi** is the citizen-facing report portal and public aggregate dashboard.

Initial pilot targets: Opština Konče and Opština Radoviš.

## Local development

Follow the [Git development workflow](docs/GIT_WORKFLOW.md) for branches, commits, pull requests, and production releases.

```bash
cp .env.example .env
docker compose up --build web frontend
```

Local services:

- React frontend: http://localhost:5173
- Django API/admin: http://localhost:8004
- PostgreSQL: localhost:5444

Inside Docker, Django connects to PostgreSQL at `db:5432`.
The React dev server proxies `/api/` and `/media/` to Django.

## First setup commands

After containers start:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_konce
docker compose exec web python manage.py seed_radovis
docker compose exec web python manage.py createsuperuser
```

The default `web` command already runs migrations and starts Django.
The default `frontend` command starts Vite on port `5173`.

## Key routes

- React municipality chooser: `http://localhost:5173/`
- React Konče citizen portal: `http://localhost:5173/konce`
- React Konče submit report: `http://localhost:5173/konce/prijavi`
- React staff dashboard: `http://localhost:5173/staff`
- Django API: `http://localhost:8004/api/`
- Django admin: `http://localhost:8004/admin/`

## Local ports

- Django host port: `8004`
- React host port: `5173`
- PostgreSQL host port: `5444`
- Redis: not used in the first MVP

## Rate limiting behind a proxy

Public submission limits are enforced atomically per municipality and hashed client IP. The app ignores `X-Forwarded-For` unless the immediate proxy is listed in `TRUSTED_PROXY_IPS` as an IP or CIDR range. In production, only list proxies that replace or safely append that header.

```env
ISSUE_RATE_LIMIT_HOURLY=3
ISSUE_RATE_LIMIT_DAILY=10
TRUSTED_PROXY_IPS=10.0.0.0/8,192.0.2.10
```

## Privacy and municipality configuration

- Uploaded issue photos are available only through authenticated staff API routes; do not expose `MEDIA_ROOT` directly from a reverse proxy.
- Superusers can preview and apply municipality retention policies from Django admin.
- Bundled Konče and Radoviš data is intentionally marked unverified. Import and verify official JSON configuration through Django admin, or validate it with `python manage.py check_municipality_config`.

## Isolated browser tests

The Playwright suite uses a separate ephemeral database and does not touch normal development data:

```bash
./scripts/run_e2e.sh
```

Frontend unit tests use Vitest and React Testing Library:

```bash
cd frontend
npm test
```

## Production pilot

Production uses the separate `docker-compose.prod.yml` stack with Gunicorn, Nginx, Certbot, private PostgreSQL/media volumes, SMTP, health checks, and encrypted Restic backups. Follow [the pilot operations runbook](docs/PILOT_OPERATIONS.md); do not reuse development `.env` values.

## Architecture documentation

- [Detailed database schema](docs/DB_SCHEMA.md)
- [End-to-end system flow](docs/SYSTEM_FLOW.md)
