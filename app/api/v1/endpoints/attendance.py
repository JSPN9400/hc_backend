from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import extract, func
from typing import List, Optional
from datetime import date, datetime
from app.db.session import get_db
from app.core.deps import get_current_user, require_perm
from app.models.models import Attendance, Worker, Site, AttendanceStatus
from app.schemas.schemas import AttendanceCreate, AttendanceBulk, AttendanceOut, MonthlySummaryItem
from app.models.models import Advance
import uuid

router = APIRouter(prefix="/attendance", tags=["attendance"])


def gen_id(): return str(uuid.uuid4())


@router.get("/daily", response_model=List[AttendanceOut])
def get_daily_attendance(
    date_: date = Query(..., alias="date"),
    site_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(Attendance).filter(
        Attendance.tenant_id == tid,
        Attendance.date == date_
    )
    if site_id:
        q = q.filter(Attendance.site_id == site_id)
    records = q.all()

    result = []
    for a in records:
        w = db.query(Worker).filter(Worker.id == a.worker_id).first()
        s = db.query(Site).filter(Site.id == a.site_id).first() if a.site_id else None
        out = AttendanceOut.model_validate(a)
        out.worker_name = w.name if w else "Unknown"
        out.site_name = s.name if s else None
        result.append(out)
    return result


@router.get("/workers-for-date")
def workers_for_attendance(
    date_: date = Query(..., alias="date"),
    site_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns all workers with their attendance status for a given date"""
    tid = current_user["tenant_id"]
    q = db.query(Worker).filter(Worker.tenant_id == tid, Worker.is_active == True)
    if site_id:
        q = q.filter(Worker.default_site_id == site_id)

    workers = q.order_by(Worker.name).all()
    att_map = {}
    att_records = db.query(Attendance).filter(
        Attendance.tenant_id == tid,
        Attendance.date == date_
    ).all()
    for a in att_records:
        att_map[a.worker_id] = a

    result = []
    for w in workers:
        a = att_map.get(w.id)
        site = db.query(Site).filter(Site.id == (a.site_id if a else w.default_site_id)).first() if (a and a.site_id) or w.default_site_id else None
        result.append({
            "worker_id": w.id,
            "worker_name": w.name,
            "role": w.role,
            "worker_type": w.worker_type.value,
            "daily_rate": w.daily_rate,
            "default_site_id": w.default_site_id,
            "default_site_name": site.name if site else None,
            "status": a.status.value if a else "A",
            "site_id": a.site_id if a else w.default_site_id,
            "overtime_hours": a.overtime_hours if a else 0,
            "note": a.note if a else None,
            "att_id": a.id if a else None,
        })
    return result


@router.post("/bulk-save")
def bulk_save_attendance(
    data: AttendanceBulk,
    current_user: dict = Depends(require_perm("attendance")),
    db: Session = Depends(get_db)
):
    """Save attendance for multiple workers at once (supervisor daily entry)"""
    tid = current_user["tenant_id"]
    saved, updated = 0, 0

    for rec in data.records:
        worker_id = rec.get("worker_id")
        status = rec.get("status", "A")
        site_id = rec.get("site_id") or data.site_id
        overtime = rec.get("overtime_hours", 0)
        note = rec.get("note")

        # Validate worker belongs to this tenant
        w = db.query(Worker).filter(Worker.id == worker_id, Worker.tenant_id == tid).first()
        if not w:
            continue

        existing = db.query(Attendance).filter(
            Attendance.worker_id == worker_id,
            Attendance.date == data.date
        ).first()

        if existing:
            existing.status = status
            existing.site_id = site_id
            existing.overtime_hours = overtime
            existing.note = note
            existing.entered_by = current_user["id"]
            updated += 1
        else:
            a = Attendance(
                id=gen_id(),
                tenant_id=tid,
                worker_id=worker_id,
                site_id=site_id,
                date=data.date,
                status=status,
                overtime_hours=overtime,
                note=note,
                entered_by=current_user["id"]
            )
            db.add(a)
            saved += 1

    db.commit()
    return {"saved": saved, "updated": updated, "date": str(data.date)}


@router.post("/single", response_model=AttendanceOut)
def save_single_attendance(
    data: AttendanceCreate,
    current_user: dict = Depends(require_perm("attendance")),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    existing = db.query(Attendance).filter(
        Attendance.worker_id == data.worker_id,
        Attendance.date == data.date
    ).first()

    if existing:
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(existing, k, v)
        existing.entered_by = current_user["id"]
        db.commit()
        db.refresh(existing)
        a = existing
    else:
        a = Attendance(
            id=gen_id(), tenant_id=tid,
            entered_by=current_user["id"],
            **data.model_dump()
        )
        db.add(a)
        db.commit()
        db.refresh(a)

    w = db.query(Worker).filter(Worker.id == a.worker_id).first()
    s = db.query(Site).filter(Site.id == a.site_id).first() if a.site_id else None
    out = AttendanceOut.model_validate(a)
    out.worker_name = w.name if w else ""
    out.site_name = s.name if s else None
    return out


@router.get("/monthly-summary")
def monthly_summary(
    month: str = Query(..., description="YYYY-MM"),
    site_id: Optional[str] = None,
    worker_type: Optional[str] = None,
    current_user: dict = Depends(require_perm("salary")),
    db: Session = Depends(get_db)
):
    """Monthly salary sheet: days present, gross, advance, net payable per worker"""
    tid = current_user["tenant_id"]
    yr, mn = month.split("-")

    wq = db.query(Worker).filter(Worker.tenant_id == tid, Worker.is_active == True)
    if site_id:
        wq = wq.filter(Worker.default_site_id == site_id)
    if worker_type:
        wq = wq.filter(Worker.worker_type == worker_type)
    workers = wq.all()

    result = []
    for w in workers:
        att = db.query(Attendance).filter(
            Attendance.worker_id == w.id,
            extract("year", Attendance.date) == int(yr),
            extract("month", Attendance.date) == int(mn)
        ).all()

        days_p = sum(1 for a in att if a.status == AttendanceStatus.P)
        days_h = sum(1 for a in att if a.status == AttendanceStatus.H)
        days_a = sum(1 for a in att if a.status == AttendanceStatus.A)
        ot_hrs = sum(a.overtime_hours or 0 for a in att)
        gross = round((days_p + days_h * 0.5) * (w.daily_rate or 0), 2)

        advs = db.query(Advance).filter(
            Advance.worker_id == w.id,
            extract("year", Advance.date) == int(yr),
            extract("month", Advance.date) == int(mn)
        ).all()
        adv_paid = sum(a.amount for a in advs if a.advance_type != "deduction")
        deductions = sum(a.amount for a in advs if a.advance_type == "deduction")
        net = gross - adv_paid + deductions + (w.previous_due or 0)

        result.append({
            "worker_id": w.id,
            "worker_name": w.name,
            "worker_type": w.worker_type.value,
            "role": w.role,
            "daily_rate": w.daily_rate,
            "days_present": days_p,
            "half_days": days_h,
            "absent_days": days_a,
            "overtime_hours": ot_hrs,
            "gross_earning": gross,
            "advance_paid": adv_paid,
            "deductions": deductions,
            "previous_due": w.previous_due or 0,
            "net_payable": round(net, 2)
        })

    total_gross = sum(r["gross_earning"] for r in result)
    total_adv = sum(r["advance_paid"] for r in result)
    total_net = sum(r["net_payable"] for r in result)

    return {
        "month": month,
        "workers": result,
        "totals": {
            "gross": round(total_gross, 2),
            "advance": round(total_adv, 2),
            "net": round(total_net, 2),
            "worker_count": len(result)
        }
    }


@router.get("/calendar/{worker_id}")
def worker_attendance_calendar(
    worker_id: str,
    month: str = Query(..., description="YYYY-MM"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Monthly attendance calendar for a single worker"""
    tid = current_user["tenant_id"]
    w = db.query(Worker).filter(Worker.id == worker_id, Worker.tenant_id == tid).first()
    if not w:
        raise HTTPException(404, "Worker not found")

    yr, mn = month.split("-")
    att = db.query(Attendance).filter(
        Attendance.worker_id == worker_id,
        extract("year", Attendance.date) == int(yr),
        extract("month", Attendance.date) == int(mn)
    ).order_by(Attendance.date).all()

    att_map = {str(a.date): {"status": a.status.value, "site_id": a.site_id, "overtime": a.overtime_hours} for a in att}
    return {"worker_id": worker_id, "worker_name": w.name, "month": month, "calendar": att_map}
