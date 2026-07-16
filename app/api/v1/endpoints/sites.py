from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from app.db.session import get_db
from app.core.deps import get_current_user, require_perm
from app.models.models import Site, User, Worker, Expense, Vendor
from app.schemas.schemas import SiteCreate, SiteUpdate, SiteOut
import uuid

router = APIRouter(prefix="/sites", tags=["sites"])


def gen_id(): return str(uuid.uuid4())


def enrich_site(site: Site, db: Session) -> SiteOut:
    out = SiteOut.model_validate(site)
    if site.supervisor_id:
        sup = db.query(User).filter(User.id == site.supervisor_id).first()
        out.supervisor_name = sup.name if sup else None
    rows = db.query(Expense.debit, Expense.credit, Expense.vendor_id).filter(Expense.site_id == site.id).all()
    # Cost = every debit row (bills + direct expenses), regardless of vendor.
    # Client revenue = credit rows that are NOT a vendor-due payment (those are cost repayments, not income).
    out.total_expense = float(sum((r.debit or 0) for r in rows))
    out.total_receipt = float(sum((r.credit or 0) for r in rows if not r.vendor_id))
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
    q = db.query(Site).filter(Site.tenant_id == tid)
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
    site = db.query(Site).filter(Site.id == site_id, Site.tenant_id == current_user["tenant_id"]).first()
    if not site:
        raise HTTPException(404, "Site not found")
    db.delete(site)
    db.commit()
    return {"message": "Site deleted"}


@router.get("/{site_id}/pl")
def site_pl(
    site_id: str,
    month: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Site P&L — cost incurred vs client revenue received, with category breakdown"""
    site = db.query(Site).filter(Site.id == site_id, Site.tenant_id == current_user["tenant_id"]).first()
    if not site:
        raise HTTPException(404)
    q = db.query(Expense).filter(Expense.site_id == site_id)
    if month:
        from sqlalchemy import extract
        yr, mn = month.split("-")
        q = q.filter(extract("year", Expense.date) == int(yr), extract("month", Expense.date) == int(mn))
    expenses = q.all()
    cat_map = {}
    for e in expenses:
        cat = e.category or "Other"
        if cat not in cat_map:
            cat_map[cat] = {"debit": 0, "credit": 0, "count": 0}
        cat_map[cat]["debit"] += e.debit or 0
        # only count as revenue if not a vendor-due repayment
        if not e.vendor_id:
            cat_map[cat]["credit"] += e.credit or 0
        cat_map[cat]["count"] += 1
    total_exp = sum(e.debit or 0 for e in expenses)          # cost incurred (accrual)
    total_rec = sum((e.credit or 0) for e in expenses if not e.vendor_id)  # client revenue only
    return {
        "site_id": site_id,
        "site_name": site.name,
        "budget": site.budget,
        "contract_value": site.contract_value,
        "total_expense": total_exp,
        "total_receipt": total_rec,
        "balance": total_rec - total_exp,
        "budget_used_pct": round((total_exp / site.budget * 100) if site.budget else 0, 1),
        "receivable_from_client": round((site.contract_value or 0) - total_rec, 2),
        "category_breakdown": cat_map
    }


@router.get("/{site_id}/ledger")
def site_ledger(
    site_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Vyapar-style 'Account Book' for a site — treats the Site like a Party:
    a chronological Day Book with running balance, vendor-wise breakdown
    (who got paid how much on this job), category breakdown, and
    budget/contract-value tracking, all scoped to one site.
    """
    tid = current_user["tenant_id"]
    site = db.query(Site).filter(Site.id == site_id, Site.tenant_id == tid).first()
    if not site:
        raise HTTPException(404, "Site not found")

    q = db.query(Expense).filter(Expense.site_id == site_id)
    if date_from:
        q = q.filter(Expense.date >= date_from)
    if date_to:
        q = q.filter(Expense.date <= date_to)
    txns = q.order_by(Expense.date, Expense.created_at).all()

    # Opening balance = net P&L position before date_from
    opening = 0.0
    if date_from:
        pre = db.query(Expense.debit, Expense.credit, Expense.vendor_id).filter(
            Expense.site_id == site_id, Expense.date < date_from
        ).all()
        opening = sum((r.credit or 0) for r in pre if not r.vendor_id) - sum((r.debit or 0) for r in pre)

    balance = opening
    day_book = []
    vendor_map = {}
    cat_map = {}
    total_cost, total_received = 0.0, 0.0

    for e in txns:
        is_revenue = (e.credit or 0) if not e.vendor_id else 0
        cost = e.debit or 0
        balance += is_revenue - cost
        total_cost += cost
        total_received += is_revenue

        day_book.append({
            "date": str(e.date),
            "description": e.vendor_name or e.description or e.category or "Transaction",
            "ref": e.bill_no,
            "debit": round(cost, 2),
            "credit": round(is_revenue, 2),
            "balance": round(balance, 2),
            "mode": e.payment_mode,
            "status": e.status.value if e.status else None,
        })

        if e.vendor_id:
            vid = e.vendor_id
            if vid not in vendor_map:
                v = db.query(Vendor).filter(Vendor.id == vid).first()
                vendor_map[vid] = {"vendor_id": vid, "vendor_name": v.name if v else e.vendor_name or "Unknown", "billed": 0, "paid": 0}
            vendor_map[vid]["billed"] += e.debit or 0
            vendor_map[vid]["paid"] += e.credit or 0

        cat = e.category or "Other"
        if cat not in cat_map:
            cat_map[cat] = {"category": cat, "debit": 0, "credit": 0, "count": 0}
        cat_map[cat]["debit"] += cost
        cat_map[cat]["credit"] += is_revenue
        cat_map[cat]["count"] += 1

    vendor_breakdown = [
        {**v, "outstanding": round(v["billed"] - v["paid"], 2)}
        for v in vendor_map.values()
    ]
    vendor_breakdown.sort(key=lambda x: x["outstanding"], reverse=True)

    return {
        "site_id": site_id,
        "site_name": site.name,
        "client_name": site.client_name,
        "budget": site.budget or 0,
        "contract_value": site.contract_value or 0,
        "total_cost": round(total_cost, 2),
        "total_received": round(total_received, 2),
        "net_balance": round(balance, 2),
        "budget_used_pct": round((total_cost / site.budget * 100) if site.budget else 0, 1),
        "receivable_from_client": round((site.contract_value or 0) - total_received, 2),
        "day_book": day_book,
        "vendor_breakdown": vendor_breakdown,
        "category_breakdown": list(cat_map.values()),
    }
