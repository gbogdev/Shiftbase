# Implemented features and limitations

## Implemented

- **Accounts:** invitation activation (hashed single-use tokens, 7-day expiry), login with rate limiting, password reset (1-hour tokens), session auth + CSRF, deactivation drops sessions
- **Roles:** owner / admin / manager / employee, server-enforced; managers can be limited to locations/departments (set through the API)
- **Employees:** profiles, departments, positions, locations, qualifications, contracted hours, optional pay rate (admin/self only), availability, deactivate, archive
- **Scheduling:** week and month views, create/edit/delete/duplicate, weekly recurrence, templates, open shifts, drag an assignment between employees, validation (see SCHEDULING_RULES.md), draft vs published, "changed since publish" flag and per-shift history, optimistic locking, publish with notifications
- **Self-service:** view published schedule, availability, leave requests/cancel, swap offers (direct or open), open-shift applications; org setting decides whether approval is needed
- **Leave:** configurable types, optional annual allowance, approve/reject with note, decision record, staffing warning, list of scheduled shifts that clash
- **Attendance:** clock in/out, breaks, late-arrival and missed-clock-out notifications, scheduled vs actual, corrections with mandatory reason and full before/after history, submit/approve (no self-approval), approved-only CSV export
- **Notifications:** in-app (bell) and email, de-duplicated, email failures recorded and retried
- **Reports:** scheduled hours, worked hours, absences, overtime warnings, open shifts, attendance discrepancies, coverage, labor cost (admins); filters; CSV
- **Settings:** time zone, week start, date format, policies, locations/departments/positions/qualifications/leave types, user roles, audit log viewer
- **Ops:** Docker Compose (dev + prod-shaped), CI, backup/restore docs, security checklist

## Limitations / not done

- Not verified: Docker images and compose files (no Docker on the development machine). Locally everything ran on SQLite; the full suite, including the two threaded concurrency tests, passes against PostgreSQL 16 in GitHub Actions
- No payroll integration (CSV export only), no mobile app, no SSO/MFA, no organization self-sign-up (`create_organization` command)
- "Upcoming shift" reminders are not implemented
- Organization date format is stored and shown in settings but dates in the UI are rendered ISO-style
- Drag-and-drop changes the assignee only; change day/time in the edit dialog
- Shift qualifications, manager location/department scope, and per-user notification preferences have API support only or are org-wide only, with no UI
- Leave: no accrual, pro-rating, half-days or carry-over; counts calendar days
- Staffing shortage = open shifts and the leave cover warning; there is no per-shift headcount target
- Availability rules ignore the end day of overnight shifts
- Data retention/erasure workflows are documented procedures, not features
- Frontend has no automated tests; accessibility has had a basic pass only (labels, roles, keyboard activation of shifts)
- Rejection notes use a browser prompt dialog
