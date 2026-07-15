# Codex Context — Opštinski Inbox + Sredi

Last updated: 2026-07-14
Project path: `/Users/vaselazarev/Desktop/work/cs/opstinski-inbox`

## Product context

This is a municipal issue-reporting MVP for North Macedonia.

Two-layer naming:

- **Opštinski Inbox** — admin/staff-facing side for municipality employees.
- **Sredi** — citizen-facing side for submitting and tracking municipal problems.

Initial pilot target:

1. **Општина Конче**
2. Later: **Општина Радовиш**

The MVP is Macedonian-only for now.

## Current architecture decisions

Backend-first web application, mobile app later.

Current stack:

- Django 5.2
- PostgreSQL 16
- Docker Compose
- Django REST Framework API backend
- React 19.2.7 + Vite 8.1.4 + TypeScript frontend in `frontend/`
- Tailwind 3.4 + shadcn-style local components for the React UI
- pytest + pytest-django
- No Redis for MVP
- Django templates still exist as backend fallback/reference, but the primary local frontend is the React app.

Ports:

- Django API/admin host port: `8004`, container port: `8000`
- React/Vite host port: `5173`, container port: `5173`
- PostgreSQL host port: `5444`, container port: `5432`

Reason for non-default ports: user already has services on common ports like `5432`, `5433`, and `8080`.

## Existing implemented MVP features

Citizen side:

- React owns the primary local citizen routes on `http://localhost:5173`.
- `/` — active municipality chooser
- `/privatnost` — draft privacy policy
- `/uslovi` — draft terms of use
- `/<municipality_slug>` — public landing page for a selected municipality
- `/<municipality_slug>/prijavi` — submit municipal issue
- `/<municipality_slug>/statistika` — public aggregate statistics
- `/<municipality_slug>/sledi?code=...` — track report by tracking code inside that municipality
- `/sredi/` — legacy redirect to the chooser

Staff/admin side:

- React owns the primary local staff routes on `http://localhost:5173/staff`.
- `/staff` — staff dashboard, login required
- `/staff/issues/<id>` — issue detail, login required
- `/staff/users/new` — superuser staff creation flow
- `/admin/` on Django remains Django admin
- `/api/` on Django exposes the DRF API used by React

Implemented data model includes:

- Municipality
- Settlement
- Department
- StaffProfile
- IssueCategory
- Issue
- IssueAttachment
- IssueStatusEvent
- IssueComment
- IssueDuplicateLink
- SlaPolicy
- AuditLog

Anonymous reporting:

- Citizens can submit without name/email/phone.
- Contact fields are optional.
- IP and user-agent are stored only as hashes.
- Basic honeypot spam field exists.

Public statistics:

- Aggregate only for now.
- Does not expose individual issue titles/descriptions.
- Scoped by municipality URL slug.

Legal/privacy pages:

- Draft Macedonian privacy policy exists at `/privatnost/`.
- Draft Macedonian terms of use exist at `/uslovi/`.
- Footer links point to both pages.
- Citizen report form links to both pages near submission.
- Text is intentionally marked as MVP draft and must be reviewed by a lawyer and participating municipalities before public launch.
- `PLATFORM_OPERATOR_NAME` and `PRIVACY_CONTACT_EMAIL` are configurable via environment variables.
- Django admin includes superuser-only privacy actions to export selected issues as CSV and anonymize citizen contact fields; both actions write audit logs.

Multi-municipality routing:

- Public citizen pages are now served under URL slugs such as `/konce/` and `/radovis/`.
- Root `/` lists active municipalities.
- Public forms, statistics, and tracking are scoped to the selected municipality.
- Non-superuser staff can only read and act on reports owned by `StaffProfile.municipality`; superusers retain cross-municipality access.
- React calls same-origin `/api/` through Vite in development; production target remains same-domain reverse proxy with React at `/`, Django at `/api/`, `/admin/`, and `/media/`.

Media:

- Local development media folder.
- Citizen upload field supports up to 5 photos in the current view logic.

Security baseline:

- CSRF enabled
- Auth-protected staff views
- Municipality-scoped staff read and workflow access, with cross-municipality access reserved for superusers
- Public submissions have atomic database-backed rate limiting by municipality + hashed IP, with forwarded client IPs accepted only from configured trusted proxies.
- Public upload validation checks max photos, extension/content type, max size, and verifies image files with Pillow.
- Submission limits and proxy trust are configurable with `ISSUE_RATE_LIMIT_HOURLY`, `ISSUE_RATE_LIMIT_DAILY`, `TRUSTED_PROXY_IPS`, `MAX_ISSUE_PHOTOS`, and `MAX_ISSUE_IMAGE_SIZE_BYTES`.
- Suspicious assessments store staff-visible reason codes, labels, and point contributions for rapid submissions, daily volume, repeated descriptions/locations, and unusually many attachments.
- `django-otp` installed/scaffolded for future 2FA, but full 2FA enrollment/enforcement UI is not implemented yet
- Secure-ish cookie/header settings for a dev baseline

Staff workflow:

- Staff can change issue status from the issue detail page.
- Staff can set priority, assigned department, assigned staff member, internal note, and public resolution note.
- Assignment form choices are scoped to the issue municipality.
- Staff can add internal or public comments on an issue.
- Staff roles are enforced server-side:
- Non-superuser staff roles can only read reports from their own municipality.
  - `VIEWER`: read-only access.
  - `FIELD_WORKER`: can add comments and change assigned issues in their municipality only to `in_progress` or `resolved`.
  - `DEPARTMENT_MANAGER`: can comment and update status on issues assigned to their department.
  - `COORDINATOR` and `MUNICIPALITY_ADMIN`: can triage, assign, update issue fields, change status, and comment across their municipality.
  - Django superusers can access all staff issues.
- `StaffProfile.department` exists for department-scoped staff roles.
- Django admin is restricted to Django superusers only for the MVP; municipality staff should use `/staff/`.
- Staff dashboard supports filters for status, settlement, category, priority, department, assignee, “my issues”, and overdue issues.
- Staff dashboard displays status/priority badges, overdue badges, assigned user, and quick status action buttons where allowed by role.
- Staff actions write `AuditLog` entries for status changes, issue updates, comments, and staff user creation.
- Sensitive statuses require a staff note: resolved, duplicate, spam/rejected, and not-in-jurisdiction.
- Status changes to accepted/assigned apply the category default department when the issue has no department.
- Superusers can create staff users from `/staff/users/new/` without opening Django admin.
- Overdue calculations now use `SlaPolicy` category-specific or municipality-default hours.

## Important implementation notes

The app is intentionally still MVP-level. Do not treat it as production-ready yet.

Known things to verify/improve before a real pilot:

- Verify the Konče settlement list. Current seed list is a starter and may be incomplete/unverified.
- Verify and expand the Radoviš settlement list. Current Radoviš seed data includes only a minimal starter settlement.
- Add proper staff user creation/onboarding flow.
- Add 2FA enforcement for staff accounts.
- Tune anti-abuse thresholds and consider admin-visible abuse/audit reporting before public launch.
- Add production deployment settings: HTTPS, static/media storage, backups, logging, monitoring.
- Legal/privacy page drafts must be reviewed and finalized by a lawyer and each participating municipality.
- Add real municipality branding/content.

Recent design pass:

- Root municipality chooser has improved hierarchy, eyebrow label, larger hero spacing, search/filter input, icon-backed municipality cards, hover lift, and a disabled "Наскоро" placeholder card.
- Shared navbar uses a stronger wordmark, border, shadow, and pill-style hover states.
- Footer uses a lighter tint, denser links, darker text contrast, and a quick citizen action.
- Selected municipality landing page has clearer CTAs with Bootstrap Icons and a compact public-status card.
- Serious UI/UX polish pass added a softer civic-product visual system, guided citizen report form sections, polished success/tracking screens, public statistics dashboard styling, staff dashboard metric cards/filter/table layout, and a case-management style staff issue detail view.
- React migration pass added `apps.api`, DRF endpoints for public/staff/auth/legal flows, React app shell/pages, Docker Compose `frontend` service, CORS/CSRF dev settings, and API tests.

## Docker commands

Start the app:

```bash
cd /Users/vaselazarev/Desktop/work/cs/opstinski-inbox
docker compose up -d web frontend
```

Stop the app:

```bash
docker compose down
```

Run migrations:

```bash
docker compose run --rm web python manage.py migrate
```

Create migrations:

```bash
docker compose run --rm web python manage.py makemigrations
```

Seed Konče pilot data:

```bash
docker compose run --rm web python manage.py seed_konce
```

Seed Radoviš pilot data:

```bash
docker compose run --rm web python manage.py seed_radovis
```

Run tests:

```bash
docker compose run --rm web pytest
```

Run Django checks:

```bash
docker compose run --rm web python manage.py check
```

Run React checks:

```bash
docker compose run --rm frontend npm run lint
docker compose run --rm frontend npm run build
```

Create admin superuser:

```bash
docker compose run --rm web python manage.py createsuperuser
```

## Validation already performed

The initial scaffold was validated successfully:

- Docker build passed
- Migrations generated and applied
- Konče seed command passed
- `python manage.py check` passed with no issues
- pytest passed: `2 passed`
- After staff workflow continuation, pytest passed: `5 passed`
- After staff workflow continuation, `python manage.py check` passed with no issues
- After multi-municipality routing continuation, pytest passed: `10 passed`
- After multi-municipality routing continuation, `python manage.py check` passed with no issues
- After multi-municipality routing continuation, `seed_radovis` passed
- After legal/privacy page continuation, pytest passed: `12 passed`
- After legal/privacy page continuation, `python manage.py check` passed with no issues
- After Bootstrap conversion, pytest passed: `12 passed`
- After Bootstrap conversion, `python manage.py check` passed with no issues
- After staff permission/admin hardening, `makemigrations --check` passed with no changes.
- After staff permission/admin hardening, `python manage.py check` passed with no issues.
- After staff permission/admin hardening, pytest passed: `18 passed`.
- After staff permission/admin hardening, `accounts.0003_staffprofile_department` was applied locally.
- After anti-abuse and staff dashboard continuation, `makemigrations --check` passed with no changes.
- After anti-abuse and staff dashboard continuation, `python manage.py check` passed with no issues.
- After anti-abuse and staff dashboard continuation, pytest passed: `22 passed`.
- After anti-abuse and staff dashboard continuation, `issues.0002_submissionratelimit` was applied locally.
- After pilot-hardening implementation, `makemigrations --check` passed with no changes.
- After pilot-hardening implementation, `python manage.py check` passed with no issues.
- After pilot-hardening implementation, pytest passed: `29 passed`.
- After public UI design pass, `python manage.py check` passed with no issues.
- After public UI design pass, pytest passed: `29 passed`.
- After serious UI/UX polish pass, `python manage.py check` passed with no issues.
- After serious UI/UX polish pass, pytest passed: `29 passed`.
- After serious UI/UX polish pass, public route smoke check returned 200 for `/`, `/konce/`, `/konce/prijavi/`, `/konce/statistika/`, and `/konce/sledi/`.
- After React migration pass, `python manage.py check` passed with no issues.
- After React migration pass, pytest passed: `32 passed`.
- After React migration pass, `docker compose run --rm frontend npm run lint` passed.
- After React migration pass, `docker compose run --rm frontend npm run build` passed.
- After React migration pass, Vite proxy smoke check from the frontend container returned API municipality data.
- Historical live smoke tests returned expected responses before slug routing.
- Current smoke routes to verify after starting the app:
  - `/` => municipality chooser
  - `/konce/` => Konče public landing page
  - `/konce/prijavi/` => Konče issue form
  - `/konce/statistika/` => Konče statistics
  - `/radovis/` => Radoviš public landing page after `seed_radovis`
  - `/staff/` => redirects to login when logged out
  - `/admin/` => redirects to admin login when logged out

## Git state

Repository was initialized and branch renamed to `main`.

At time of handoff, files were created but not committed.

Suggested first CLI check:

```bash
cd /Users/vaselazarev/Desktop/work/cs/opstinski-inbox
git status --short
```

## Suggested next development steps

Recommended order:

1. Create a superuser and inspect the admin.
2. Improve the first citizen UI flow and Macedonian copy.
3. Build staff dashboard v1 more seriously:
   - status filters
   - settlement/category filters
   - assignment fields
   - comments/internal notes
4. Add explicit anti-abuse/rate-limit strategy for anonymous submissions.
5. Add verified settlement data for Konče and later Radoviš.
6. Add 2FA enrollment/enforcement for staff accounts.
7. Add production-ready deployment config.
8. Finalize legal/privacy text and pilot agreement with municipality review.

## User preferences / constraints

- User wants planning-first, but implementation has now started.
- User prefers Macedonian-only MVP.
- User chose no Redis for now.
- User wants API/web port not to be `8080`; current port is `8004`.
- React/Vite frontend runs on `5173`.
- User wants PostgreSQL host port not to be `5432`; current host port is `5444`.
- User likes the two-layer brand: **Opštinski Inbox with Sredi**.

## Notes for future Codex sessions

When continuing from VS Code / CLI Codex:

- Start by reading this file and `README.md`.
- Then run `git status --short` before editing.
- Preserve user changes; do not overwrite uncommitted work.
- Prefer small, verified increments.
- If changing files in this project from a sandboxed environment, the project may be outside the default writable root and may require permission.
