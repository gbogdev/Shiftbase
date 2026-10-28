# Scheduling rules

Validation runs when a shift is saved (shown as feedback), when an assignment is dragged, before a swap or open-shift assignment is approved, and before publishing. **Errors block; warnings inform.**

| Rule | Severity | Configurable | Notes |
|---|---|---|---|
| `overlap` – employee has an overlapping shift (draft or published) | error | no | |
| `leave` – approved leave on the shift date | error | via leave approval | uses organization-local dates |
| `qualification` – missing required qualification | error | per shift | |
| `unavailable` – outside stated availability | warning | Settings: can be made an error | checks the shift's start day only; overnight shifts are checked until midnight |
| `rest` – less than N hours between shifts | warning | `min_rest_hours` (default 11) | |
| `weekly_hours` – scheduled hours over N in the org workweek | warning | `max_weekly_hours` (default 48) | counts all the employee's shifts, break time deducted |
| `unstaffed` – shift has no employee | warning | n/a | open shifts are allowed |

Leave approval additionally warns when fewer than `leave_min_staff_warning` colleagues in the same department remain available on any day (configurable). There is no per-shift minimum headcount model, so "staffing shortage" is currently: open shifts, plus the leave-cover warning.

## Not implemented / needs legal validation

The defaults above are placeholders, **not legal advice**. No country's labor rules (maximum daily hours, mandatory breaks, minors, overtime pay, night work, predictive-scheduling notice periods, leave entitlements) are encoded. Accrual and pro-rating of leave are not implemented; a leave type can have a flat annual day allowance that is enforced on approval. Anyone deploying this should have the rules reviewed for their jurisdiction before relying on them.

## Adding a rule

Write `def my_rule(ctx): yield Issue(WARNING, "code", "message", shift.pk, shift.employee_id)` in `scheduling/validation.py` and append it to `RULES`. `ctx.org` has the organization settings; `ctx.shifts` are the shifts being checked; `ctx.neighbours(shift)` returns the employee's nearby shifts. Per-organization rule sets would be done by selecting rules from `RULES` based on organization settings.
