# Bug fixes applied

Run `migration_add_soft_delete.sql` once against your database before deploying this, otherwise
sites.py / expenses.py will error on the new `is_deleted` column.

## 1. Deduction sign bug (salary was calculated backwards)
`workers.py` (worker ledger) and `attendance.py` (monthly summary) both computed:
`net = gross - advance + deductions + previous_due`
Deductions were being ADDED to net payable instead of subtracted. Fixed by moving the
formula into one shared function: `app/services/payroll.py::calc_net_payable()`.

## 2. Employee (fixed monthly_salary) workers always showed 0 gross earning
Every salary calculation only ever used `daily_rate * days_present`. `monthly_salary`
(the field meant for office/HR staff) was never read. Fixed in
`app/services/payroll.py::calc_gross_earning()` — branches on `worker_type`.

## 3. Overtime hours were recorded but never paid
`overtime_hours` was saved on every attendance record but never multiplied by any
rate anywhere. Fixed: `calc_gross_earning()` now pays overtime at 1.5x the
daily-rate-derived hourly rate (8-hour day assumed — change `OT_MULTIPLIER` /
`STANDARD_WORK_HOURS` in `payroll.py` if your policy differs).

## 4. Site P&L was missing labour cost entirely
`sites.py` `/sites/{id}/pl` only summed the `Expense` table. Worker wages are earned
through `Attendance`, not `Expense`, so the single biggest site cost never appeared
in the P&L. Fixed: the endpoint now also computes labour cost from attendance +
daily_rate/overtime for that site and month, and reports it as a separate line item.

## 5. Excel worker import silently dropped the "Site Code" column
The docstring promised a `Site Code` column would assign a worker's default site,
but the code never read it. Fixed in `workers.py::import_workers_excel` — now maps
`Site Code` to the site's `project_code` and sets `default_site_id`.

## 6. Supervisors could see other sites' expense totals
`list_expenses` restricted supervisors to their assigned sites; `/expenses/summary`
(used for dashboard totals) did not have the same restriction. Fixed by adding the
identical filter to `expense_summary`.

## 7. N+1 queries in worker list (performance)
`GET /workers/` fired 2-3 extra DB queries PER worker (site lookup, attendance,
advance sum) in a loop. Fixed: `list_workers` now does 3 bulk queries total and
passes lookup maps into `enrich_worker()`, regardless of list size.

## 8. Hard deletes with no audit trail
Deleting a worker, site, or expense used `db.delete()` — a real, permanent,
un-recoverable delete, cascading to all related attendance/expense/advance history.
Fixed: all three now soft-delete (`is_active=False` for workers — reuses the
existing column; `is_deleted=True` for sites/expenses — new column, see the
migration script). List/summary endpoints already filter these out, so behaviour
looks identical from the frontend, but history is preserved and recoverable.
