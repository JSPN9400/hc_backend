from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from typing import List, Optional
from datetime import date, datetime
from app.db.session import get_db
from app.core.deps import get_current_user, require_perm, get_super_admin
from app.core.security import get_password_hash
from app.models.models import (
    Vendor, Advance, Worker, Site, Expense, Attendance, User,
    LeaveRequest, Holiday, LeaveStatus, AttendanceStatus, RoleEnum
)
from app.schemas.schemas import (
    VendorCreate, VendorUpdate, VendorOut,
    AdvanceCreate, AdvanceOut,
    LeaveCreate, LeaveApprove, LeaveOut,
    UserCreate, UserUpdate, UserOut,
    DashboardStats
)
import uuid

def gen_id(): return str(uuid.uuid4())


# ─────────────────────────────────────────────
# VENDORS
# ─────────────────────────────────────────────
vendors_router = APIRouter(prefix="/vendors", tags=["vendors"])

@vendors_router.get("/", response_model=List[VendorOut])
def list_vendors(
    vendor_type: Optional[str] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(Vendor).filter(Vendor.tenant_id == tid)
    if vendor_type:
        q = q.filter(Vendor.vendor_type == vendor_type)
    if search:
        q = q.filter(Vendor.name.ilike(f"%{search}%"))
    vendors = q.order_by(Vendor.name).all()

    result = []
    for v in vendors:
        out = VendorOut.model_validate(v)
        totals = db.query(
            func.sum(Expense.debit).label("paid"),
            func.count(Expense.id).label("cnt"),
            func.max(Expense.date).label("last")
        ).filter(Expense.vendor_id == v.id).first()
        out.total_paid = float(totals.paid or 0)
        out.transaction_count = totals.cnt or 0
        out.last_transaction_date = totals.last
        result.append(out)
    return result

@vendors_router.post("/", response_model=VendorOut)
def create_vendor(data: VendorCreate, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    v = Vendor(id=gen_id(), tenant_id=current_user["tenant_id"], **data.model_dump())
    db.add(v); db.commit(); db.refresh(v)
    return VendorOut.model_validate(v)

@vendors_router.patch("/{vid}", response_model=VendorOut)
def update_vendor(vid: str, data: VendorUpdate, current_user: dict = Depends(require_perm("edit")), db: Session = Depends(get_db)):
    v = db.query(Vendor).filter(Vendor.id == vid, Vendor.tenant_id == current_user["tenant_id"]).first()
    if not v: raise HTTPException(404)
    for k, val in data.model_dump(exclude_none=True).items():
        setattr(v, k, val)
    db.commit(); db.refresh(v)
    return VendorOut.model_validate(v)

@vendors_router.delete("/{vid}")
def delete_vendor(vid: str, current_user: dict = Depends(require_perm("edit")), db: Session = Depends(get_db)):
    v = db.query(Vendor).filter(Vendor.id == vid, Vendor.tenant_id == current_user["tenant_id"]).first()
    if not v: raise HTTPException(404)
    db.delete(v); db.commit()
    return {"message": "Deleted"}


# ─────────────────────────────────────────────
# ADVANCES
# ─────────────────────────────────────────────
advances_router = APIRouter(prefix="/advances", tags=["advances"])

@advances_router.get("/", response_model=List[AdvanceOut])
def list_advances(
    worker_id: Optional[str] = None,
    month: Optional[str] = None,
    current_user: dict = Depends(require_perm("salary")),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(Advance).filter(Advance.tenant_id == tid)
    if worker_id:
        q = q.filter(Advance.worker_id == worker_id)
    if month:
        yr, mn = month.split("-")
        q = q.filter(extract("year", Advance.date) == int(yr), extract("month", Advance.date) == int(mn))
    advs = q.order_by(Advance.date.desc()).all()
    result = []
    for a in advs:
        out = AdvanceOut.model_validate(a)
        w = db.query(Worker).filter(Worker.id == a.worker_id).first()
        out.worker_name = w.name if w else None
        result.append(out)
    return result

@advances_router.post("/", response_model=AdvanceOut)
def create_advance(data: AdvanceCreate, current_user: dict = Depends(require_perm("salary")), db: Session = Depends(get_db)):
    w = db.query(Worker).filter(Worker.id == data.worker_id, Worker.tenant_id == current_user["tenant_id"]).first()
    if not w: raise HTTPException(404, "Worker not found")
    a = Advance(id=gen_id(), tenant_id=current_user["tenant_id"], entered_by=current_user["id"], **data.model_dump())
    db.add(a); db.commit(); db.refresh(a)
    out = AdvanceOut.model_validate(a)
    out.worker_name = w.name
    return out

@advances_router.delete("/{aid}")
def delete_advance(aid: str, current_user: dict = Depends(require_perm("edit")), db: Session = Depends(get_db)):
    a = db.query(Advance).filter(Advance.id == aid, Advance.tenant_id == current_user["tenant_id"]).first()
    if not a: raise HTTPException(404)
    db.delete(a); db.commit()
    return {"message": "Deleted"}


# ─────────────────────────────────────────────
# LEAVE REQUESTS
# ─────────────────────────────────────────────
leaves_router = APIRouter(prefix="/leaves", tags=["leaves"])

@leaves_router.get("/", response_model=List[LeaveOut])
def list_leaves(
    status: Optional[str] = None,
    worker_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(LeaveRequest).filter(LeaveRequest.tenant_id == tid)
    if status: q = q.filter(LeaveRequest.status == status)
    if worker_id: q = q.filter(LeaveRequest.worker_id == worker_id)
    leaves = q.order_by(LeaveRequest.created_at.desc()).all()
    result = []
    for l in leaves:
        out = LeaveOut.model_validate(l)
        w = db.query(Worker).filter(Worker.id == l.worker_id).first()
        out.worker_name = w.name if w else None
        result.append(out)
    return result

@leaves_router.post("/", response_model=LeaveOut)
def apply_leave(data: LeaveCreate, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    from datetime import timedelta
    days = (data.to_date - data.from_date).days + 1
    l = LeaveRequest(
        id=gen_id(), tenant_id=current_user["tenant_id"],
        days=days, applied_by=current_user["id"],
        **data.model_dump()
    )
    db.add(l); db.commit(); db.refresh(l)
    out = LeaveOut.model_validate(l)
    w = db.query(Worker).filter(Worker.id == l.worker_id).first()
    out.worker_name = w.name if w else None
    return out

@leaves_router.post("/{lid}/approve")
def approve_leave(lid: str, data: LeaveApprove, current_user: dict = Depends(require_perm("workers")), db: Session = Depends(get_db)):
    l = db.query(LeaveRequest).filter(LeaveRequest.id == lid, LeaveRequest.tenant_id == current_user["tenant_id"]).first()
    if not l: raise HTTPException(404)
    l.status = data.status
    l.approved_by = current_user["id"]
    l.approved_at = datetime.utcnow()
    l.reject_reason = data.reject_reason
    if data.status == LeaveStatus.approved:
        # Mark attendance as Leave for those dates
        w = db.query(Worker).filter(Worker.id == l.worker_id).first()
        if w:
            current = l.from_date
            from datetime import timedelta
            while current <= l.to_date:
                existing = db.query(Attendance).filter(Attendance.worker_id == w.id, Attendance.date == current).first()
                if existing:
                    existing.status = AttendanceStatus.L
                else:
                    db.add(Attendance(id=gen_id(), tenant_id=l.tenant_id, worker_id=w.id, date=current, status=AttendanceStatus.L))
                current += timedelta(days=1)
    db.commit()
    return {"message": f"Leave {data.status.value}"}


# ─────────────────────────────────────────────
# USERS (per tenant)
# ─────────────────────────────────────────────
users_router = APIRouter(prefix="/users", tags=["users"])

ROLE_DEFAULT_PERMS = {
    RoleEnum.admin:      dict(perm_sites=True, perm_workers=True, perm_attendance=True, perm_expenses=True, perm_salary=True, perm_reports=True, perm_users=True, perm_edit=True),
    RoleEnum.accounts:   dict(perm_sites=False, perm_workers=True, perm_attendance=True, perm_expenses=True, perm_salary=True, perm_reports=True, perm_users=False, perm_edit=True),
    RoleEnum.supervisor: dict(perm_sites=False, perm_workers=True, perm_attendance=True, perm_expenses=True, perm_salary=False, perm_reports=True, perm_users=False, perm_edit=False),
    RoleEnum.hr:         dict(perm_sites=False, perm_workers=True, perm_attendance=True, perm_expenses=False, perm_salary=True, perm_reports=True, perm_users=False, perm_edit=True),
    RoleEnum.viewer:     dict(perm_sites=False, perm_workers=False, perm_attendance=False, perm_expenses=False, perm_salary=False, perm_reports=True, perm_users=False, perm_edit=False),
}

@users_router.get("/", response_model=List[UserOut])
def list_users(current_user: dict = Depends(require_perm("users")), db: Session = Depends(get_db)):
    return db.query(User).filter(User.tenant_id == current_user["tenant_id"]).order_by(User.name).all()

@users_router.post("/", response_model=UserOut)
def create_user(data: UserCreate, current_user: dict = Depends(require_perm("users")), db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.tenant_id == current_user["tenant_id"], User.username == data.username.lower()).first()
    if existing: raise HTTPException(400, "Username already exists")
    perms = ROLE_DEFAULT_PERMS.get(data.role, {})
    u = User(
        id=gen_id(), tenant_id=current_user["tenant_id"],
        username=data.username.lower().strip(),
        password_hash=get_password_hash(data.password),
        name=data.name, email=data.email, phone=data.phone, role=data.role,
        **{k: data.model_dump().get(k.replace("perm_","perm_"), perms.get(k, False)) for k in perms}
    )
    # Override with explicitly provided perms
    for k in ["perm_sites","perm_workers","perm_attendance","perm_expenses","perm_salary","perm_reports","perm_users","perm_edit"]:
        val = getattr(data, k, None)
        if val is not None: setattr(u, k, val)
    db.add(u); db.commit(); db.refresh(u)
    return u

@users_router.patch("/{uid}", response_model=UserOut)
def update_user(uid: str, data: UserUpdate, current_user: dict = Depends(require_perm("users")), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == uid, User.tenant_id == current_user["tenant_id"]).first()
    if not u: raise HTTPException(404)
    if data.password:
        u.password_hash = get_password_hash(data.password)
    for k, v in data.model_dump(exclude_none=True, exclude={"password"}).items():
        setattr(u, k, v)
    db.commit(); db.refresh(u)
    return u

@users_router.delete("/{uid}")
def delete_user(uid: str, current_user: dict = Depends(require_perm("users")), db: Session = Depends(get_db)):
    if uid == current_user["id"]: raise HTTPException(400, "Apne aap ko delete nahi kar sakte")
    u = db.query(User).filter(User.id == uid, User.tenant_id == current_user["tenant_id"]).first()
    if not u: raise HTTPException(404)
    db.delete(u); db.commit()
    return {"message": "User deleted"}


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────
dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@dashboard_router.get("/stats")
def dashboard_stats(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = current_user["tenant_id"]
    today = date.today()
    yr = today.year

    total_sites = db.query(func.count(Site.id)).filter(Site.tenant_id == tid).scalar()
    active_sites = db.query(func.count(Site.id)).filter(Site.tenant_id == tid, Site.status == "active").scalar()
    total_workers = db.query(func.count(Worker.id)).filter(Worker.tenant_id == tid).scalar()
    active_workers = db.query(func.count(Worker.id)).filter(Worker.tenant_id == tid, Worker.is_active == True).scalar()

    today_att = db.query(Attendance).filter(Attendance.tenant_id == tid, Attendance.date == today).all()
    present = sum(1 for a in today_att if a.status == AttendanceStatus.P)
    half = sum(1 for a in today_att if a.status == AttendanceStatus.H)
    absent = sum(1 for a in today_att if a.status == AttendanceStatus.A)

    # Today payroll
    today_pay = 0
    for a in today_att:
        w = db.query(Worker).filter(Worker.id == a.worker_id).first()
        if w:
            if a.status == AttendanceStatus.P: today_pay += w.daily_rate or 0
            elif a.status == AttendanceStatus.H: today_pay += (w.daily_rate or 0) / 2

    fy_exps = db.query(Expense).filter(Expense.tenant_id == tid, extract("year", Expense.date) == yr).all()
    fy_expense = sum(e.debit or 0 for e in fy_exps)
    fy_receipt = sum(e.credit or 0 for e in fy_exps)

    pending_exp = db.query(func.count(Expense.id)).filter(Expense.tenant_id == tid, Expense.status == "pending").scalar()
    pending_leaves = db.query(func.count(LeaveRequest.id)).filter(LeaveRequest.tenant_id == tid, LeaveRequest.status == "pending").scalar()

    # Site PL
    sites = db.query(Site).filter(Site.tenant_id == tid).all()
    site_pl = []
    for s in sites:
        exps = db.query(Expense).filter(Expense.site_id == s.id).all()
        te = sum(e.debit or 0 for e in exps)
        tr = sum(e.credit or 0 for e in exps)
        wc = db.query(func.count(Worker.id)).filter(Worker.default_site_id == s.id, Worker.is_active == True).scalar()
        site_pl.append({"site_id": s.id, "site_name": s.name, "status": s.status.value, "total_expense": round(te, 2), "total_receipt": round(tr, 2), "balance": round(tr - te, 2), "worker_count": wc})

    # Today attendance by site
    site_att = {}
    for a in today_att:
        w = db.query(Worker).filter(Worker.id == a.worker_id).first()
        if w and w.default_site_id:
            sid = w.default_site_id
            if sid not in site_att: site_att[sid] = {"P": 0, "H": 0, "A": 0}
            site_att[sid][a.status.value] = site_att[sid].get(a.status.value, 0) + 1

    # Recent transactions
    recent_exp = db.query(Expense).filter(Expense.tenant_id == tid).order_by(Expense.date.desc(), Expense.created_at.desc()).limit(10).all()

    return {
        "stats": {
            "total_sites": total_sites, "active_sites": active_sites,
            "total_workers": total_workers, "active_workers": active_workers,
            "present_today": present, "half_day_today": half, "absent_today": absent,
            "today_payroll": round(today_pay, 2),
            "fy_total_expense": round(fy_expense, 2),
            "fy_total_receipt": round(fy_receipt, 2),
            "pending_expenses": pending_exp,
            "pending_leaves": pending_leaves,
        },
        "site_pl": site_pl,
        "today_site_attendance": site_att,
        "recent_expenses": [
            {"id": e.id, "date": str(e.date), "vendor": e.vendor_name, "site_id": e.site_id,
             "category": e.category, "debit": e.debit, "credit": e.credit, "mode": e.payment_mode, "status": e.status.value}
            for e in recent_exp
        ]
    }


# ─────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────
reports_router = APIRouter(prefix="/reports", tags=["reports"])

@reports_router.get("/manpower-cost")
def manpower_cost_report(
    month: str = Query(...),
    site_id: Optional[str] = None,
    current_user: dict = Depends(require_perm("reports")),
    db: Session = Depends(get_db)
):
    """Manpower cost by site for a month"""
    tid = current_user["tenant_id"]
    yr, mn = month.split("-")
    q = db.query(Attendance).filter(
        Attendance.tenant_id == tid,
        extract("year", Attendance.date) == int(yr),
        extract("month", Attendance.date) == int(mn)
    )
    if site_id: q = q.filter(Attendance.site_id == site_id)
    records = q.all()

    site_cost = {}
    for a in records:
        w = db.query(Worker).filter(Worker.id == a.worker_id).first()
        if not w: continue
        sid = a.site_id or "general"
        if sid not in site_cost:
            s = db.query(Site).filter(Site.id == sid).first()
            site_cost[sid] = {"site_name": s.name if s else "General", "workers": {}, "total": 0}
        cost = (w.daily_rate or 0) if a.status == AttendanceStatus.P else ((w.daily_rate or 0) / 2 if a.status == AttendanceStatus.H else 0)
        if w.id not in site_cost[sid]["workers"]:
            site_cost[sid]["workers"][w.id] = {"name": w.name, "role": w.role, "days": 0, "half": 0, "cost": 0}
        if a.status == AttendanceStatus.P: site_cost[sid]["workers"][w.id]["days"] += 1
        elif a.status == AttendanceStatus.H: site_cost[sid]["workers"][w.id]["half"] += 1
        site_cost[sid]["workers"][w.id]["cost"] += cost
        site_cost[sid]["total"] += cost

    return {"month": month, "report": site_cost, "total_cost": round(sum(v["total"] for v in site_cost.values()), 2)}

@reports_router.get("/vendor-payments")
def vendor_payment_report(
    month: Optional[str] = None,
    vendor_type: Optional[str] = None,
    current_user: dict = Depends(require_perm("reports")),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(Expense).filter(Expense.tenant_id == tid, Expense.debit > 0)
    if month:
        yr, mn = month.split("-")
        q = q.filter(extract("year", Expense.date) == int(yr), extract("month", Expense.date) == int(mn))
    exps = q.order_by(Expense.date.desc()).all()

    vendor_map = {}
    for e in exps:
        key = e.vendor_name or "Unknown"
        if key not in vendor_map:
            vendor_map[key] = {"total": 0, "count": 0, "last_date": None, "modes": {}}
        vendor_map[key]["total"] += e.debit or 0
        vendor_map[key]["count"] += 1
        if not vendor_map[key]["last_date"] or e.date > vendor_map[key]["last_date"]:
            vendor_map[key]["last_date"] = e.date
        mode = e.payment_mode or "Other"
        vendor_map[key]["modes"][mode] = vendor_map[key]["modes"].get(mode, 0) + (e.debit or 0)

    sorted_vendors = sorted(vendor_map.items(), key=lambda x: x[1]["total"], reverse=True)
    return {
        "month": month,
        "vendors": [{"vendor": k, **v, "last_date": str(v["last_date"]) if v["last_date"] else None} for k, v in sorted_vendors],
        "total_paid": round(sum(v["total"] for v in vendor_map.values()), 2)
    }

@reports_router.get("/export/excel")
def export_to_excel(
    report_type: str = Query(..., description="expenses|attendance|salary|workers|vendors"),
    month: Optional[str] = None,
    site_id: Optional[str] = None,
    current_user: dict = Depends(require_perm("reports")),
    db: Session = Depends(get_db)
):
    """Export any report to Excel"""
    import pandas as pd
    from fastapi.responses import StreamingResponse
    import io

    tid = current_user["tenant_id"]
    rows = []

    if report_type == "expenses":
        q = db.query(Expense).filter(Expense.tenant_id == tid)
        if month:
            yr, mn = month.split("-")
            q = q.filter(extract("year", Expense.date) == int(yr), extract("month", Expense.date) == int(mn))
        if site_id: q = q.filter(Expense.site_id == site_id)
        for e in q.order_by(Expense.date).all():
            s = db.query(Site).filter(Site.id == e.site_id).first() if e.site_id else None
            rows.append({"Date": str(e.date), "Site": s.name if s else "", "Vendor": e.vendor_name or "", "Payer": e.payer_name or "", "Category": e.category or "", "SubCategory": e.sub_category or "", "Description": e.description or "", "Debit": e.debit or 0, "Credit": e.credit or 0, "Mode": e.payment_mode or "", "Status": e.status.value, "Bill No": e.bill_no or ""})

    elif report_type == "workers":
        for w in db.query(Worker).filter(Worker.tenant_id == tid).order_by(Worker.name).all():
            s = db.query(Site).filter(Site.id == w.default_site_id).first() if w.default_site_id else None
            rows.append({"Name": w.name, "Phone": w.phone or "", "Role": w.role or "", "Type": w.worker_type.value, "Daily Rate": w.daily_rate or 0, "Site": s.name if s else "", "Aadhar": w.aadhar_no or "", "Bank": w.bank_account or "", "IFSC": w.ifsc_code or "", "Address": w.address or "", "Active": "Yes" if w.is_active else "No"})

    elif report_type == "salary":
        if not month: raise HTTPException(400, "month required")
        yr, mn = month.split("-")
        for w in db.query(Worker).filter(Worker.tenant_id == tid, Worker.is_active == True).all():
            att = db.query(Attendance).filter(Attendance.worker_id == w.id, extract("year", Attendance.date) == int(yr), extract("month", Attendance.date) == int(mn)).all()
            days_p = sum(1 for a in att if a.status == AttendanceStatus.P)
            days_h = sum(1 for a in att if a.status == AttendanceStatus.H)
            gross = round((days_p + days_h * 0.5) * (w.daily_rate or 0), 2)
            adv = db.query(func.sum(Advance.amount)).filter(Advance.worker_id == w.id, extract("year", Advance.date) == int(yr), extract("month", Advance.date) == int(mn)).scalar() or 0
            s = db.query(Site).filter(Site.id == w.default_site_id).first() if w.default_site_id else None
            rows.append({"Name": w.name, "Role": w.role or "", "Site": s.name if s else "", "Daily Rate": w.daily_rate or 0, "Days Present": days_p, "Half Days": days_h, "Gross Earning": gross, "Advance": adv, "Previous Due": w.previous_due or 0, "Net Payable": round(gross - adv + (w.previous_due or 0), 2)})

    if not rows:
        raise HTTPException(404, "No data found")

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=report_type.capitalize())
    buf.seek(0)

    filename = f"{report_type}_{month or 'all'}_{date.today()}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
