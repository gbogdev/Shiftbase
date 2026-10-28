# Operations

## Deploy (Docker Compose + Caddy)

The production compose file has not been run against a real domain by the authors; treat it as a starting point.

```bash
cp .env.example .env      # fill in SECRET_KEY, passwords, hostnames, SMTP
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec web python manage.py create_organization \
    --name "Acme Ltd" --owner-email owner@example.com --timezone Europe/London   # reads OWNER_PASSWORD env var
```

Migrations run on every start. The `periodic` service runs `manage.py run_periodic` every 5 minutes (retries failed emails, flags missed clock-outs). Without Docker: run gunicorn behind any TLS-terminating proxy and run that command from cron.

Updating: `git pull && docker compose -f docker-compose.prod.yml up -d --build`. Take a backup first.

## Backups

Everything is in PostgreSQL (no uploaded files).

```bash
docker compose -f docker-compose.prod.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > shiftbase-$(date +%F).dump
```

Run daily, copy off the host, encrypt at rest, keep per your retention policy. Use managed-database point-in-time recovery if available.

## Restore

```bash
docker compose -f docker-compose.prod.yml stop web periodic
docker compose -f docker-compose.prod.yml exec -T db sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose -f docker-compose.prod.yml exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < shiftbase-YYYY-MM-DD.dump
docker compose -f docker-compose.prod.yml up -d
```

Test a restore into a scratch environment regularly; an untested backup is not a backup.

## Database access

Do not publish port 5432. Administrators connect through `docker compose exec db psql` or an SSH tunnel. Use separate roles: owner (migrations), application (no DDL, no audit-log UPDATE/DELETE), read-only (reporting). Record who has access.

## Retention, export, deletion

What the application does today:

- Employees are **archived, never deleted**: login disabled, hidden from lists, shifts/time/leave/audit records kept.
- Time entries, corrections and audit entries have no automatic expiry.
- CSV exports: approved timesheets and all reports.

What it does **not** do: automatic purging, a self-service "delete my data" request, or a full per-person data export. Do these as reviewed manual procedures: export the person's rows (employee, shifts, leave, time entries, notifications) with SQL; to erase, anonymize the employee row (name, email, phone, rate) and delete the user and notifications while keeping time and audit rows if you are legally required to keep payroll or working-time records. Retention periods vary by country and record type; confirm them with legal advice, then schedule the purge.
