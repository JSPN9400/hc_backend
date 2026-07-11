from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import extract, func
from typing import List, Optional
from datetime import date
from app.db.session import get_db
from app.core.deps import get_current_user, require_perm
from app.models.models import Expense, Site, Vendor, User, ExpenseStatus
from app.schemas.schemas import ExpenseCreate, ExpenseUpdate, ExpenseOut, ExpenseApprove, ImportResult
import uuid

router = APIRouter(prefix="/expenses", tags=["expenses"])


def gen_id(): return str(uuid.uuid4())


def enrich(e: Expense, db: Session) -> ExpenseOut:
    out = ExpenseOut.model_validate(e)
    if e.site_id:
        s = db.query(Site).filter(Site.id == e.site_id).first()
        out.site_name = s.name if s else None
    if e.entered_by:
        u = db.query(User).filter(User.id == e.entered_by).first()
        out.entered_by = u.name if u else None
    if e.approved_by:
        u = db.query(User).filter(User.id == e.approved_by).first()
        out.approved_by = u.name if u else None
    return out


@router.get("/", response_model=List[ExpenseOut])
def list_expenses(
    site_id: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(Expense).filter(Expense.tenant_id == tid)

    if site_id:
        q = q.filter(Expense.site_id == site_id)
    if category:
        q = q.filter(Expense.category == category)
    if status:
        q = q.filter(Expense.status == status)
    if month:
        yr, mn = month.split("-")
        q = q.filter(extract("year", Expense.date) == int(yr), extract("month", Expense.date) == int(mn))
    if date_from:
        q = q.filter(Expense.date >= date_from)
    if date_to:
        q = q.filter(Expense.date <= date_to)
    if search:
        q = q.filter(
            (Expense.vendor_name.ilike(f"%{search}%")) |
            (Expense.description.ilike(f"%{search}%"))
        )

    # Supervisors only see their site's expenses
    if current_user["role"] == "supervisor":
        import json
        assigned = json.loads(current_user.get("assigned_site_ids") or "[]")
        if assigned:
            q = q.filter(Expense.site_id.in_(assigned))

    total = q.count()
    expenses = q.order_by(Expense.date.desc(), Expense.created_at.desc()) \
                .offset((page - 1) * page_size).limit(page_size).all()

    return [enrich(e, db) for e in expenses]


@router.get("/summary")
def expense_summary(
    month: Optional[str] = None,
    site_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Category-wise and site-wise summary"""
    tid = current_user["tenant_id"]
    q = db.query(Expense).filter(Expense.tenant_id == tid)
    if month:
        yr, mn = month.split("-")
        q = q.filter(extract("year", Expense.date) == int(yr), extract("month", Expense.date) == int(mn))
    if site_id:
        q = q.filter(Expense.site_id == site_id)
    exps = q.all()

    cat_map, site_map, mode_map = {}, {}, {}
    for e in exps:
        cat = e.category or "Other"
        if cat not in cat_map:
            cat_map[cat] = {"debit": 0, "credit": 0, "count": 0}
        cat_map[cat]["debit"] += e.debit or 0
        cat_map[cat]["credit"] += e.credit or 0
        cat_map[cat]["count"] += 1

        sid = e.site_id or "no_site"
        if sid not in site_map:
            s = db.query(Site).filter(Site.id == sid).first()
            site_map[sid] = {"name": s.name if s else "General", "debit": 0, "credit": 0}
        site_map[sid]["debit"] += e.debit or 0
        site_map[sid]["credit"] += e.credit or 0

        mode = e.payment_mode or "Other"
        mode_map[mode] = mode_map.get(mode, 0) + (e.debit or 0)

    total_d = sum(e.debit or 0 for e in exps)
    total_c = sum(e.credit or 0 for e in exps)
    return {
        "total_debit": round(total_d, 2),
        "total_credit": round(total_c, 2),
        "balance": round(total_c - total_d, 2),
        "count": len(exps),
        "by_category": cat_map,
        "by_site": site_map,
        "by_mode": mode_map
    }


@router.post("/", response_model=ExpenseOut)
def create_expense(
    data: ExpenseCreate,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    # Auto-link vendor if vendor_name matches
    vendor_id = data.vendor_id
    if not vendor_id and data.vendor_name:
        v = db.query(Vendor).filter(
            Vendor.tenant_id == current_user["tenant_id"],
            Vendor.name.ilike(data.vendor_name)
        ).first()
        if v:
            vendor_id = v.id

    # Supervisor entries start as pending; accounts entries can be approved directly
    status = ExpenseStatus.pending
    if current_user["role"] in ["admin", "accounts"]:
        status = ExpenseStatus.approved

    e = Expense(
        id=gen_id(),
        tenant_id=current_user["tenant_id"],
        vendor_id=vendor_id,
        status=status,
        entered_by=current_user["id"],
        **{k: v for k, v in data.model_dump().items() if k != "vendor_id"}
    )
    e.vendor_id = vendor_id
    db.add(e)
    db.commit()
    db.refresh(e)
    return enrich(e, db)


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(
    expense_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    e = db.query(Expense).filter(Expense.id == expense_id, Expense.tenant_id == current_user["tenant_id"]).first()
    if not e:
        raise HTTPException(404)
    return enrich(e, db)


@router.patch("/{expense_id}", response_model=ExpenseOut)
def update_expense(
    expense_id: str,
    data: ExpenseUpdate,
    current_user: dict = Depends(require_perm("edit")),
    db: Session = Depends(get_db)
):
    e = db.query(Expense).filter(Expense.id == expense_id, Expense.tenant_id == current_user["tenant_id"]).first()
    if not e:
        raise HTTPException(404)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(e, k, v)
    db.commit()
    db.refresh(e)
    return enrich(e, db)


@router.post("/{expense_id}/approve")
def approve_expense(
    expense_id: str,
    data: ExpenseApprove,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    """Accounts reviews and approves/rejects supervisor expense"""
    if current_user["role"] not in ["admin", "accounts"]:
        raise HTTPException(403, "Only Accounts/Admin can approve expenses")
    e = db.query(Expense).filter(Expense.id == expense_id, Expense.tenant_id == current_user["tenant_id"]).first()
    if not e:
        raise HTTPException(404)
    from datetime import datetime
    e.status = data.status
    e.approved_by = current_user["id"]
    e.approved_at = datetime.utcnow()
    db.commit()
    return {"message": f"Expense {data.status.value}", "id": expense_id}


@router.delete("/{expense_id}")
def delete_expense(
    expense_id: str,
    current_user: dict = Depends(require_perm("edit")),
    db: Session = Depends(get_db)
):
    e = db.query(Expense).filter(Expense.id == expense_id, Expense.tenant_id == current_user["tenant_id"]).first()
    if not e:
        raise HTTPException(404)
    db.delete(e)
    db.commit()
    return {"message": "Deleted"}


@router.post("/import/excel", response_model=ImportResult)
async def import_expenses_excel(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    """Import expenses from Excel. Columns: Date, Site Code, Vendor, Category, Debit, Credit, Mode, Description"""
    import pandas as pd, io
    content = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(content))
    except Exception as ex:
        raise HTTPException(400, f"Invalid file: {ex}")

    tid = current_user["tenant_id"]
    # Build site code map
    sites = db.query(Site).filter(Site.tenant_id == tid).all()
    site_map = {s.project_code: s.id for s in sites if s.project_code}
    site_map.update({s.name: s.id for s in sites})

    success, failed, errors = 0, 0, []
    for i, row in df.iterrows():
        try:
            from datetime import datetime as dt
            raw_date = row.get("Date", "")
            if hasattr(raw_date, "date"):
                entry_date = raw_date.date()
            else:
                entry_date = dt.strptime(str(raw_date).strip(), "%Y-%m-%d").date()

            site_key = str(row.get("Site Code", "") or "").strip()
            site_id = site_map.get(site_key)
            debit = float(row.get("Debit", 0) or 0)
            credit = float(row.get("Credit", 0) or 0)
            if not debit and not credit:
                continue

            e = Expense(
                id=gen_id(), tenant_id=tid,
                date=entry_date,
                site_id=site_id,
                vendor_name=str(row.get("Vendor", "") or ""),
                payer_name=str(row.get("Payer", "") or ""),
                category=str(row.get("Category", "Miscellaneous") or "Miscellaneous"),
                sub_category=str(row.get("Sub Category", "") or ""),
                description=str(row.get("Description", "") or ""),
                debit=debit, credit=credit,
                payment_mode=str(row.get("Mode", "Cash") or "Cash"),
                status=ExpenseStatus.approved,
                entered_by=current_user["id"]
            )
            db.add(e)
            success += 1
        except Exception as ex:
            failed += 1
            errors.append(f"Row {i+2}: {str(ex)}")

    db.commit()
    return ImportResult(success=success, failed=failed, errors=errors[:10])
