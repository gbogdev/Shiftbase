# Architecture

One Django project (`backend/config`), one Django app per domain, one React SPA. No microservices, no task queue.

```
core/          organizations, users, roles, invitations, auth API, audit log, access helpers
people/        locations, departments, positions, qualifications, employees, availability
scheduling/    shifts, templates, swaps, open-shift applications, validation rules, publish
leave/         leave types, requests, approval, staffing warnings
attendance/    time entries, breaks, corrections, approval, CSV export
notifications/ in-app notifications, email delivery
reports/       read-only report queries + CSV
```

## Decisions

- **Business logic lives in `services.py`** per app; `api.py` files only parse input, call a service, serialize. Every state change that touches several rows is one `transaction.atomic()` block.
- **Tenancy:** every tenant table has `organization_id`. The organization is always taken from `request.user`, never from the request body. All querysets go through `core.access.org_scoped`, plus `scope_rows` / `scope_employees` for managers restricted to locations or departments. Out-of-org ids return 404 (no existence leak). A user belongs to exactly one organization.
- **Authorization** is checked on the server by role (`core.access.IsManager/IsAdmin/IsOwner`) and object scope (`can_manage_employee`, `can_manage_row`). The frontend only hides navigation.
- **Concurrency:** rows that a decision depends on are locked with `select_for_update` (swap/application decisions, leave decisions, publishing, timesheet approval). Decisions re-check status after locking, so a second approval gets HTTP 409. A partial unique index guarantees one open time entry per employee. Shifts carry a `version` for optimistic concurrency on edits. `select_for_update` is a no-op on SQLite, so the concurrency tests need PostgreSQL.
- **Time:** all timestamps are UTC (`USE_TZ=True`). Leave uses organization-local calendar dates. Recurring shifts and templates are anchored in the organization's time zone, so a 09:00 shift stays 09:00 local across DST changes. The UI converts with `Intl` using the organization's zone.
- **Validation rules** (`scheduling/validation.py`) are plain functions in a `RULES` list returning `Issue(severity, code, ...)`. Add a function to extend; see `docs/SCHEDULING_RULES.md`.
- **Notifications:** `notify()` creates the in-app record once per `(user, dedupe_key)` (unique constraint) and sends email after commit. Email failure is stored on the notification and retried by `manage.py run_periodic`; it never rolls back the business event.
- **Audit:** `AuditLog` refuses updates/deletes through the ORM and has no API for writes. See SECURITY.md for DB-level hardening.
- **Sessions + CSRF:** cookie sessions with Django CSRF; the SPA is served same-origin, so no CORS and no tokens in JavaScript storage.
- **Frontend:** Vite build output is served by Django (WhiteNoise) under `/static/`; unknown non-API paths return the SPA shell.
