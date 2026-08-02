from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from app.db.session import get_db
from app.core.deps import get_current_user, require_perm
from app.models.models import Site, User, Worker, Expense, Attendance, AttendanceStatus, WorkerTypeEnum, Advance
from app.schemas.schemas import SiteCreate, SiteUpdate, SiteOut
import uuid

router = APIRouter(prefix="/sites", tags=["sites"])


def gen_id(): return str(uuid.uuid4())


def enrich_site(site: Site, db: Session) -> SiteOut:
    out = SiteOut.model_validate(site)
    if site.supervisor_id:
        sup = db.query(User).filter(User.id == site.supervisor_id).first()
        out.supervisor_name = sup.name if sup else None
    totals = db.query(
        func.sum(Expense.debit).label("exp"),
        func.sum(Expense.credit).label("rec")
    ).filter(Expense.site_id == site.id, Expense.is_deleted == False).first()
    out.total_expense = float(totals.exp or 0)
    out.total_receipt = float(totals.rec or 0)
    out.worker_count = db.query(func.count(Worker.id)).filter(
        Worker.default_site_id == site.id, Worker.is_active == True
    ).scalar()
    return out


@router.get("/", response_model=List[SiteOut])
def list_sites(
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(Site).filter(Site.tenant_id == tid, Site.is_deleted == False)
    if status:
        q = q.filter(Site.status == status)

    # Supervisors only see their assigned sites
    if current_user["role"] == "supervisor":
        import json
        assigned = json.loads(current_user.get("assigned_site_ids") or "[]")
        if assigned:
            q = q.filter(Site.id.in_(assigned))
        else:
            q = q.filter(Site.supervisor_id == current_user["id"])

    sites = q.order_by(Site.created_at.desc()).all()
    return [enrich_site(s, db) for s in sites]


@router.post("/", response_model=SiteOut)
def create_site(
    data: SiteCreate,
    current_user: dict = Depends(require_perm("sites")),
    db: Session = Depends(get_db)
):
    site = Site(id=gen_id(), tenant_id=current_user["tenant_id"], **data.model_dump())
    db.add(site)
    db.commit()
    db.refresh(site)
    return enrich_site(site, db)


@router.get("/{site_id}", response_model=SiteOut)
def get_site(
    site_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    site = db.query(Site).filter(Site.id == site_id, Site.tenant_id == current_user["tenant_id"]).first()
    if not site:
        raise HTTPException(404, "Site not found")
    return enrich_site(site, db)


@router.patch("/{site_id}", response_model=SiteOut)
def update_site(
    site_id: str,
    data: SiteUpdate,
    current_user: dict = Depends(require_perm("edit")),
    db: Session = Depends(get_db)
):
    site = db.query(Site).filter(Site.id == site_id, Site.tenant_id == current_user["tenant_id"]).first()
    if not site:
        raise HTTPException(404, "Site not found")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(site, k, v)
    db.commit()
    db.refresh(site)
    return enrich_site(site, db)


@router.delete("/{site_id}")
def delete_site(
    site_id: str,
    current_user: dict = Depends(require_perm("edit")),
    db: Session = Depends(get_db)
):
    """
    BUG FIX: this used to hard-delete the site, cascading to ALL its attendance
    and expense records (see cascade="all, delete" on the Site model) -
    permanent loss of an entire site's financial history. Soft-deletes instead.
    """
    site = db.query(Site).filter(Site.id == site_id, Site.tenant_id == current_user["tenant_id"]).first()
    if not site:
        raise HTTPException(404, "Site not found")
    site.is_deleted = True
    db.commit()
    return {"message": "Site deleted (soft-delete, history preserved)"}


@router.get("/{site_id}/pl")
def site_pl(
    site_id: str,
    month: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Site P&L — expenses vs receipts with category breakdown"""
    from sqlalchemy import extract
    from app.services.payroll import calc_gross_earning

    site = db.query(Site).filter(Site.id == site_id, Site.tenant_id == current_user["tenant_id"]).first()
    if not site:
        raise HTTPException(404)

    q = db.query(Expense).filter(Expense.site_id == site_id, Expense.is_deleted == False)
    if month:
        yr, mn = month.split("-")
        q = q.filter(extract("year", Expense.date) == int(yr), extract("month", Expense.date) == int(mn))
    expenses = q.all()

    cat_map = {}
    for e in expenses:
        cat = e.category or "Other"
        if cat not in cat_map:
            cat_map[cat] = {"debit": 0, "credit": 0, "count": 0}
        cat_map[cat]["debit"] += e.debit or 0
        cat_map[cat]["credit"] += e.credit or 0
        cat_map[cat]["count"] += 1

    # BUG FIX: labour wages are usually the single biggest site cost, but this
    # endpoint only ever looked at the Expense table (vendor bills, materials,
    # misc payments). Worker wages are earned via Attendance, not Expense, so
    # they never showed up here - P&L was understating true site cost.
    att_q = db.query(Attendance).join(Worker, Worker.id == Attendance.worker_id).filter(
        Attendance.site_id == site_id, Worker.tenant_id == current_user["tenant_id"]
    )
    if month:
        yr, mn = month.split("-")
        att_q = att_q.filter(extract("year", Attendance.date) == int(yr), extract("month", Attendance.date) == int(mn))
    att_rows = att_q.all()

    worker_cache = {}
    labour_cost = 0.0
    for a in att_rows:
        w = worker_cache.get(a.worker_id)
        if w is None:
            w = db.query(Worker).filter(Worker.id == a.worker_id).first()
            worker_cache[a.worker_id] = w
        if not w or w.worker_type != WorkerTypeEnum.labour:
            continue
        days_p = 1 if a.status == AttendanceStatus.P else 0
        days_h = 1 if a.status == AttendanceStatus.H else 0
        earning = calc_gross_earning(w, days_p, days_h, a.overtime_hours or 0)
        labour_cost += earning["gross_earning"]
    labour_cost = round(labour_cost, 2)
    if labour_cost:
        cat_map["Labour (wages)"] = {"debit": labour_cost, "credit": 0, "count": len(att_rows)}

    total_exp = sum(e.debit or 0 for e in expenses) + labour_cost
    total_rec = sum(e.credit or 0 for e in expenses)
    return {
        "site_id": site_id,
        "site_name": site.name,
        "budget": site.budget,
        "labour_cost": labour_cost,
        "other_expense": round(sum(e.debit or 0 for e in expenses), 2),
        "total_expense": round(total_exp, 2),
        "total_receipt": round(total_rec, 2),
        "balance": round(total_rec - total_exp, 2),
        "budget_used_pct": round((total_exp / site.budget * 100) if site.budget else 0, 1),
        "category_breakdown": cat_map
    }
