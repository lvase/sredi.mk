# Development Flow

## Locked decisions

- Project slug: `opstinski-inbox`
- Product/admin name: **Opštinski Inbox**
- Citizen-facing name: **Sredi**
- Stack: Django + PostgreSQL
- Development Compose runs Django, React, and PostgreSQL; production includes Redis/Celery for shared state and background jobs.
- Django host port: `8004`
- PostgreSQL host port: `5444`
- Macedonian only
- Anonymous reports allowed, triaged before action
- Public dashboard shows aggregate stats only
- Text-only pilot: citizen photo uploads are disabled per municipality by default; retain attachment support for a later opt-in feature.
- Location MVP: settlement/village + text description, no map pin yet

## Milestones

1. Foundation: Docker, Django, PostgreSQL, settings, base templates.
2. Core data: municipalities, settlements, departments, categories, issues.
3. Citizen vertical flow: submit a text-only report and receive a private tracking code.
4. Staff vertical flow: triage, accept/reject, assign, update status.
5. Public dashboard: aggregate counts only.
6. Security hardening: rate limits, 2FA enforcement, private uploads, audit logs.
7. Deployment prep: managed VPS compose, HTTPS, backups, monitoring.
