# Development Flow

## Locked decisions

- Project slug: `opstinski-inbox`
- Product/admin name: **Opštinski Inbox**
- Citizen-facing name: **Sredi**
- Stack: Django + PostgreSQL
- No Redis/Celery in first MVP
- Django host port: `8004`
- PostgreSQL host port: `5444`
- Macedonian only
- Anonymous reports allowed, triaged before action
- Public dashboard shows aggregate stats only
- Citizen photos included from MVP
- Location MVP: settlement/village + text description, no map pin yet

## Milestones

1. Foundation: Docker, Django, PostgreSQL, settings, base templates.
2. Core data: municipalities, settlements, departments, categories, issues.
3. Citizen vertical flow: submit report with photos, tracking code.
4. Staff vertical flow: triage, accept/reject, assign, update status.
5. Public dashboard: aggregate counts only.
6. Security hardening: rate limits, 2FA enforcement, private uploads, audit logs.
7. Deployment prep: managed VPS compose, HTTPS, backups, monitoring.
