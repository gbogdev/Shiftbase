# Shiftbase

Workforce management web app for small and medium shift-based businesses: employees, scheduling, availability, leave, attendance and timesheets, with multiple organizations and locations.

Django + Django REST Framework + PostgreSQL backend, React + TypeScript (Vite) frontend, served as one application.

## Main features

- Organizations with locations, departments, positions, qualifications; roles: owner, admin, manager, employee (manager access can be limited to locations/departments)
- Invitation-based account activation, password reset, login rate limiting
- Weekly and monthly schedule, drag-and-drop assignment, recurring shifts, templates, open shifts, draft/published schedules, change tracking
- Configurable validation (overlaps, leave, qualifications, availability, rest, weekly hours); errors block publishing, warnings do not
- Self-service: availability, time off, shift swaps / offers, open-shift applications, with optional manager approval
- Clock in/out with breaks, manager corrections with mandatory reason, timesheet approval, CSV export of approved time
- In-app + email notifications (de-duplicated, failures recorded and retried)
- Reports with filters and CSV export; append-only audit log

See [docs/FEATURES.md](docs/FEATURES.md) for what is and is not implemented.

## Requirements

Python 3.13+ (3.14 tested locally), Node 20+, PostgreSQL 16 (SQLite works for local development and most tests), or Docker.

## Run locally (without Docker)

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt
cd frontend && npm install && npm run build && cd ..
cd backend
export SECRET_KEY=dev DEBUG=true SECURE_SSL_REDIRECT=false
python manage.py migrate
python manage.py seed_demo          # fictional demo org; prints logins
python manage.py runserver          # http://localhost:8000
```

For frontend hot reload run `npm run dev` in `frontend/` (proxies `/api` to port 8000).

## Run with Docker Compose

```bash
docker compose up --build           # http://localhost:8000 (development settings)
docker compose exec web python manage.py seed_demo
```

## Tests and checks

```bash
cd backend && pytest -q && ruff check .
cd frontend && npm run build        # type-checks, then builds
```

Set `DATABASE_URL=postgres://...` to run against PostgreSQL; two concurrency tests only run there. CI (`.github/workflows/ci.yml`) runs everything against PostgreSQL.

## Deployment, security, operations

- [docs/OPERATIONS.md](docs/OPERATIONS.md): deployment, backup/restore, retention, database access
- [docs/SECURITY.md](docs/SECURITY.md): production checklist and known risks
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/SCHEDULING_RULES.md](docs/SCHEDULING_RULES.md)

## Acknowledgment

Parts of this project were written with the help of an AI coding assistant (Claude Code). The code has not had an independent security review.
