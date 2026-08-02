from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from typing import List, Optional
from datetime import date, datetime
from app.db.session import get_db
from app.core.deps import get_current_user, require_perm
from app.models.models import Worker, Attendance, Advance, Site, AttendanceStatus, WorkerTypeEnum
from app.schemas.schemas import WorkerCreate, WorkerUpdate, WorkerOut, ImportResult
import uuid, json

router = APIRouter(prefix="/workers", tags=["workers"])


def gen_id(): return str(uuid.uuid4())


from app.services.payroll import calc_gross_earning, calc_net_payable


def enrich_worker(w: Worker, db: Session, month: str = None,
                   site_map: dict = None, att_by_worker: dict = None, adv_by_worker: dict = None) -> WorkerOut:
    """
    site_map / att_by_worker / adv_by_worker let callers pre-fetch data in bulk
    for a list of workers instead of firing 3 extra queries per worker (N+1 fix).
    When not supplied (e.g. single-worker lookups), falls back to per-worker queries.
    """
    out = WorkerOut.model_validate(w)

    if w.default_site_id:
        if site_map is not None:
            out.default_site_name = site_map.get(w.default_site_id)
        else:
            site = db.query(Site).filter(Site.id == w.default_site_id).first()
            out.default_site_name = site.name if site else None

    now = datetime.now()
    ym = month or f"{now.year}-{now.month:02d}"
    yr, mn = ym.split("-")

    if att_by_worker is not None:
        att = att_by_worker.get(w.id, [])
    else:
        att = db.query(Attendance).filter(
            Attendance.worker_id == w.id,
            extract("year", Attendance.date) == int(yr),
            extract("month", Attendance.date) == int(mn)
        ).all()

    days = sum(1 for a in att if a.status == AttendanceStatus.P)
    half = sum(1 for a in att if a.status == AttendanceStatus.H)
    ot_hours = sum(a.overtime_hours or 0 for a in att)
    earning = calc_gross_earning(w, days, half, ot_hours)
    out.this_month_days = days
    out.this_month_gross = earning["gross_earning"]

    if adv_by_worker is not None:
        out.total_advance = float(adv_by_worker.get(w.id, 0))
    else:
        total_adv = db.query(func.sum(Advance.amount)).filter(
            Advance.worker_id == w.id
        ).scalar()
        out.total_advance = float(total_adv or 0)
    return out


@router.get("/", response_model=List[WorkerOut])
def list_workers(
    worker_type: Optional[str] = None,
    site_id: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = True,
    search: Optional[str] = None,
    month: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(Worker).filter(Worker.tenant_id == tid)
    if worker_type:
        q = q.filter(Worker.worker_type == worker_type)
    if site_id:
        q = q.filter(Worker.default_site_id == site_id)
    if role:
        q = q.filter(Worker.role == role)
    if is_active is not None:
        q = q.filter(Worker.is_active == is_active)
    if search:
        q = q.filter(Worker.name.ilike(f"%{search}%"))
    workers = q.order_by(Worker.name).all()
    if not workers:
        return []

    worker_ids = [w.id for w in workers]
    now = datetime.now()
    ym = month or f"{now.year}-{now.month:02d}"
    yr, mn = ym.split("-")

    # Bulk-fetch: 3 queries total instead of 3 queries PER worker (N+1 fix)
    site_ids = {w.default_site_id for w in workers if w.default_site_id}
    site_map = {
        s.id: s.name for s in db.query(Site).filter(Site.id.in_(site_ids)).all()
    } if site_ids else {}

    att_rows = db.query(Attendance).filter(
        Attendance.worker_id.in_(worker_ids),
        extract("year", Attendance.date) == int(yr),
        extract("month", Attendance.date) == int(mn)
    ).all()
    att_by_worker = {}
    for a in att_rows:
        att_by_worker.setdefault(a.worker_id, []).append(a)

    adv_rows = db.query(Advance.worker_id, func.sum(Advance.amount)).filter(
        Advance.worker_id.in_(worker_ids)
    ).group_by(Advance.worker_id).all()
    adv_by_worker = {wid: float(total or 0) for wid, total in adv_rows}

    return [
        enrich_worker(w, db, month, site_map=site_map, att_by_worker=att_by_worker, adv_by_worker=adv_by_worker)
        for w in workers
    ]


@router.post("/", response_model=WorkerOut)
def create_worker(
    data: WorkerCreate,
    current_user: dict = Depends(require_perm("workers")),
    db: Session = Depends(get_db)
):
    w = Worker(id=gen_id(), tenant_id=current_user["tenant_id"], **data.model_dump())
    db.add(w)
    db.commit()
    db.refresh(w)
    return enrich_worker(w, db)


@router.get("/{worker_id}", response_model=WorkerOut)
def get_worker(
    worker_id: str,
    month: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    w = db.query(Worker).filter(Worker.id == worker_id, Worker.tenant_id == current_user["tenant_id"]).first()
    if not w:
        raise HTTPException(404, "Worker not found")
    return enrich_worker(w, db, month)


@router.patch("/{worker_id}", response_model=WorkerOut)
def update_worker(
    worker_id: str,
    data: WorkerUpdate,
    current_user: dict = Depends(require_perm("edit")),
    db: Session = Depends(get_db)
):
    w = db.query(Worker).filter(Worker.id == worker_id, Worker.tenant_id == current_user["tenant_id"]).first()
    if not w:
        raise HTTPException(404)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(w, k, v)
    db.commit()
    db.refresh(w)
    return enrich_worker(w, db)


@router.delete("/{worker_id}")
def delete_worker(
    worker_id: str,
    current_user: dict = Depends(require_perm("edit")),
    db: Session = Depends(get_db)
):
    """
    BUG FIX: this used to hard-delete the worker, cascading to their entire
    attendance/advance history - permanent data loss with no undo, and a
    problem for audit trails. Now soft-deletes via is_active=False, same as
    the rest of the app already assumes (list_workers defaults to is_active=True).
    """
    w = db.query(Worker).filter(Worker.id == worker_id, Worker.tenant_id == current_user["tenant_id"]).first()
    if not w:
        raise HTTPException(404)
    w.is_active = False
    db.commit()
    return {"message": "Worker deactivated (history preserved)"}


@router.get("/{worker_id}/ledger")
def worker_ledger(
    worker_id: str,
    month: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Full worker ledger: attendance + advances for a month"""
    w = db.query(Worker).filter(Worker.id == worker_id, Worker.tenant_id == current_user["tenant_id"]).first()
    if not w:
        raise HTTPException(404)
    now = datetime.now()
    ym = month or f"{now.year}-{now.month:02d}"
    yr, mn = ym.split("-")

    att = db.query(Attendance).filter(
        Attendance.worker_id == worker_id,
        extract("year", Attendance.date) == int(yr),
        extract("month", Attendance.date) == int(mn)
    ).order_by(Attendance.date).all()

    advances = db.query(Advance).filter(
        Advance.worker_id == worker_id,
        extract("year", Advance.date) == int(yr),
        extract("month", Advance.date) == int(mn)
    ).order_by(Advance.date).all()

    days_p = sum(1 for a in att if a.status == AttendanceStatus.P)
    days_h = sum(1 for a in att if a.status == AttendanceStatus.H)
    ot_hours = sum(a.overtime_hours or 0 for a in att)
    earning = calc_gross_earning(w, days_p, days_h, ot_hours)
    gross = earning["gross_earning"]

    total_adv = sum(a.amount for a in advances if a.advance_type not in ["deduction"])
    total_ded = sum(a.amount for a in advances if a.advance_type == "deduction")
    net = calc_net_payable(gross, total_adv, total_ded, w.previous_due)

    return {
        "worker": {"id": w.id, "name": w.name, "role": w.role, "daily_rate": w.daily_rate,
                   "worker_type": w.worker_type.value, "monthly_salary": w.monthly_salary},
        "month": ym,
        "attendance": [
            {"date": str(a.date), "status": a.status.value, "site_id": a.site_id, "overtime_hours": a.overtime_hours}
            for a in att
        ],
        "advances": [
            {"id": a.id, "date": str(a.date), "type": a.advance_type, "amount": a.amount, "mode": a.payment_mode, "note": a.note}
            for a in advances
        ],
        "summary": {
            "days_present": days_p,
            "half_days": days_h,
            "base_earning": earning["base_earning"],
            "overtime_pay": earning["overtime_pay"],
            "gross_earning": gross,
            "advance_paid": total_adv,
            "deductions": total_ded,
            "previous_due": w.previous_due or 0,
            "net_payable": round(net, 2)
        }
    }


@router.post("/import/excel", response_model=ImportResult)
async def import_workers_excel(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_perm("workers")),
    db: Session = Depends(get_db)
):
    """Import workers from Excel. Template columns: Name, Phone, Role, Daily Rate, Site Code, Aadhar, Address"""
    import pandas as pd, io
    content = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(400, f"Invalid Excel file: {e}")

    tid = current_user["tenant_id"]
    success, failed, errors = 0, 0, []
    required = ["Name"]
    for col in required:
        if col not in df.columns:
            raise HTTPException(400, f"Column '{col}' missing in Excel")

    # BUG FIX: "Site Code" column was documented but never actually read/mapped
    # to default_site_id, so imported workers always ended up unassigned.
    sites = db.query(Site).filter(Site.tenant_id == tid).all()
    site_code_map = {s.project_code: s.id for s in sites if s.project_code}

    for i, row in df.iterrows():
        try:
            name = str(row.get("Name", "")).strip()
            if not name or name == "nan":
                continue
            site_code = str(row.get("Site Code", "") or "").strip()
            w = Worker(
                id=gen_id(),
                tenant_id=tid,
                name=name,
                phone=str(row.get("Phone", "") or ""),
                role=str(row.get("Role", "Labour") or "Labour"),
                daily_rate=float(row.get("Daily Rate", 0) or 0),
                aadhar_no=str(row.get("Aadhar", "") or ""),
                address=str(row.get("Address", "") or ""),
                default_site_id=site_code_map.get(site_code),
                worker_type="labour",
                is_active=True
            )
            db.add(w)
            success += 1
        except Exception as e:
            failed += 1
            errors.append(f"Row {i+2}: {str(e)}")

    db.commit()
    return ImportResult(success=success, failed=failed, errors=errors[:10])
