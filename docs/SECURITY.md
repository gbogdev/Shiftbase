# Security

Implemented controls do not make the platform "secure" or "compliant" by themselves. It has had no independent review or penetration test.

## What is tested

`backend/tests/test_auth_and_isolation.py` and `test_domain.py` check, among other things: cross-organization reads/writes/IDOR return 404; client-supplied organization ids are ignored; references to another organization's objects are rejected; role escalation paths (self-edit, editing higher roles, granting admin) are blocked; employees cannot reach admin/manager endpoints or modify shifts; manager location scope; pay-rate visibility; CSRF enforcement on state-changing calls and on login; login rate limiting; invitation single use and expiry; reset token single use and no account enumeration; audit log append-only behaviour; approval cannot be repeated or self-granted; CSV formula injection neutralised.

## Production checklist

- [ ] `DEBUG=false`; a unique `SECRET_KEY` (the app refuses to start without one)
- [ ] `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `APP_BASE_URL` set to the real HTTPS origin
- [ ] TLS terminates at the proxy (Caddyfile provided) and the proxy sends `X-Forwarded-Proto`; HSTS, secure cookies and SSL redirect are on when `DEBUG=false`
- [ ] PostgreSQL not exposed publicly; strong unique DB password; app uses a non-superuser role
- [ ] Real SMTP (`EMAIL_URL`); SPF/DKIM configured for the sending domain
- [ ] `.env` not committed; secrets in a secret manager or host environment
- [ ] Backups configured **and a restore tested** (docs/OPERATIONS.md)
- [ ] Run `python manage.py check --deploy` and fix findings
- [ ] Apply audit-log DB hardening (below)
- [ ] Set `REDIS_URL` when running more than one process/container (login rate limiting uses the shared cache; the default per-process cache is weaker)
- [ ] Monitor logs; logs contain no passwords/tokens, but access logs contain IPs and request paths
- [ ] Keep dependencies updated; review Dependabot/`pip-audit`/`npm audit` output
- [ ] Review the "known risks" below against your threat model

## Audit log hardening (database level)

The ORM blocks updates/deletes, but anyone with database access could still change rows. Run as the DB owner, with the application connecting as a different role:

```sql
REVOKE UPDATE, DELETE, TRUNCATE ON core_auditlog FROM shiftbase_app;
```

(or add a trigger that raises on UPDATE/DELETE). Not applied automatically because it depends on how roles are set up.

## Known risks and gaps

- No multi-factor authentication; no "change password while signed in" screen (reset-by-email only); no email-change flow
- Rate limiting is per email+IP in the cache; distributed attackers or a shared-IP lockout are possible
- Sessions last 12 hours; there is no "sign out everywhere" except deactivating the user
- A user belongs to one organization only
- Audit log is not tamper-evident (no hash chain) and is only DB-protected after the step above
- No content-security-policy in the Django layer (the Caddyfile adds one); no automated dependency scanning is configured
- Concurrency protections rely on PostgreSQL row locks; two threaded tests (swap approval, open-shift assignment) pass in CI on PostgreSQL, but other race paths (e.g. simultaneous clock-in, publish) are covered by constraints and code review only
- Email bodies and in-app notifications contain names and shift times; email is not end-to-end protected
- No automated retention/deletion jobs (see OPERATIONS.md)
- Frontend has no automated tests
