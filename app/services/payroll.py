"""
Shared payroll calculation logic.

Why this file exists (bug-fix context): the gross/net salary formula used to be
copy-pasted independently in workers.py (worker ledger) and attendance.py
(monthly summary). Both copies had the same bug - deductions were being ADDED
to net payable instead of subtracted - and employee (fixed monthly_salary)
staff always showed 0 gross earning because only daily_rate was ever used.

Keeping ONE calculation function means a future fix (or a future bug) only
has to happen in one place.
"""

# Standard overtime multiplier (1.5x hourly rate). Hourly rate is derived
# from an assumed 8-hour working day. Adjust here if the business uses a
# different OT policy - this is the only place it needs to change.
OT_MULTIPLIER = 1.5
STANDARD_WORK_HOURS = 8


def calc_gross_earning(worker, days_present: int, half_days: int, overtime_hours: float) -> dict:
    """
    - Labour (daily wage): (present days + 0.5 * half days) * daily_rate
    - Employee (fixed salary): monthly_salary as-is (unpaid-leave proration is
      a separate feature - not folded silently into this calculation)
    - Overtime is paid on top for BOTH worker types, using the daily_rate-derived
      hourly rate (employees with no daily_rate configured simply get 0 OT pay)
    """
    from app.models.models import WorkerTypeEnum

    hourly_rate = (worker.daily_rate or 0) / STANDARD_WORK_HOURS
    overtime_pay = round((overtime_hours or 0) * hourly_rate * OT_MULTIPLIER, 2)

    if worker.worker_type == WorkerTypeEnum.employee:
        base = worker.monthly_salary or 0
    else:
        base = (days_present + half_days * 0.5) * (worker.daily_rate or 0)

    return {
        "base_earning": round(base, 2),
        "overtime_pay": overtime_pay,
        "gross_earning": round(base + overtime_pay, 2),
    }


def calc_net_payable(gross_earning: float, advance_paid: float, deductions: float, previous_due: float) -> float:
    """
    BUG FIX: deductions must SUBTRACT from net payable. The old formula added
    them (net = gross - advance + deductions + previous_due), which meant a
    worker with MORE deductions ended up with a HIGHER take-home number.
    """
    return round(gross_earning - advance_paid - deductions + (previous_due or 0), 2)
