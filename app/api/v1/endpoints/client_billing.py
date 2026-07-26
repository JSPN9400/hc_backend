from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from typing import List, Optional
from datetime import date, datetime
from app.db.session import get_db
from app.core.deps import get_current_user, require_perm
from app.models.models import (
    Site, User, Worker,
    ClientContract, ClientContractType, ClientContractStatus,
    ContractMilestone, MilestoneStatus,
    ClientRABill, ClientRABillItem, ClientRABillStatus,
    ClientPayment,
    WorkerSiteAssignment, SupervisorSiteAssignment,
    DailySiteReport, MaterialTransaction
)
from pydantic import BaseModel
import uuid

router = APIRouter(prefix="/client", tags=["Client Billing"])
gen_id = lambda: str(uuid.uuid4())


# ── WORKER MULTI-SITE ──────────────────────────
class WorkerAssignIn(BaseModel):
    worker_id: str
    site_id: str
    date_from: date
    date_to: Optional[date] = None
    reason: Optional[str] = None

@router.get("/worker-assignments")
def list_worker_assignments(
    site_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    as_of_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(WorkerSiteAssignment).filter(WorkerSiteAssignment.tenant_id == tid)
    if site_id: q = q.filter(WorkerSiteAssignment.site_id == site_id)
    if worker_id: q = q.filter(WorkerSiteAssignment.worker_id == worker_id)
    assignments = q.order_by(WorkerSiteAssignment.date_from.desc()).all()
    result = []
    for a in assignments:
        w = db.query(Worker).filter(Worker.id == a.worker_id).first()
        s = db.query(Site).filter(Site.id == a.site_id).first()
        result.append({
            "id": a.id,
            "worker_id": a.worker_id,
            "worker_name": w.name if w else None,
            "worker_role": w.role if w else None,
            "site_id": a.site_id,
            "site_name": s.name if s else None,
            "date_from": str(a.date_from),
            "date_to": str(a.date_to) if a.date_to else None,
            "reason": a.reason,
            "is_active": not a.date_to or a.date_to >= date.today()
        })
    return result

@router.post("/worker-assignments")
def assign_worker_to_site(
    data: WorkerAssignIn,
    current_user: dict = Depends(require_perm("workers")),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    existing = db.query(WorkerSiteAssignment).filter(
        WorkerSiteAssignment.tenant_id == tid,
        WorkerSiteAssignment.worker_id == data.worker_id,
        WorkerSiteAssignment.date_to == None
    ).first()
    if existing:
        existing.date_to = data.date_from
    a = WorkerSiteAssignment(
        id=gen_id(), tenant_id=tid,
        worker_id=data.worker_id, site_id=data.site_id,
        date_from=data.date_from, date_to=data.date_to,
        reason=data.reason, assigned_by=current_user["id"]
    )
    w = db.query(Worker).filter(Worker.id == data.worker_id, Worker.tenant_id == tid).first()
    if w: w.default_site_id = data.site_id
    db.add(a); db.commit()
    return {"id": a.id, "message": "Worker assigned"}

@router.get("/workers-by-site/{site_id}")
def workers_on_site(
    site_id: str,
    as_of_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    check_date = as_of_date or date.today()
    assigned = db.query(WorkerSiteAssignment).filter(
        WorkerSiteAssignment.tenant_id == tid,
        WorkerSiteAssignment.site_id == site_id,
        WorkerSiteAssignment.date_from <= check_date,
        (WorkerSiteAssignment.date_to == None) | (WorkerSiteAssignment.date_to >= check_date)
    ).all()
    assigned_ids = {a.worker_id for a in assigned}
    default_workers = db.query(Worker).filter(
        Worker.tenant_id == tid, Worker.default_site_id == site_id, Worker.is_active == True
    ).all()
    default_ids = {w.id for w in default_workers}
    all_ids = assigned_ids | default_ids
    workers = db.query(Worker).filter(Worker.id.in_(all_ids), Worker.is_active == True).all()
    return [
        {
            "id": w.id, "name": w.name, "role": w.role, "daily_rate": w.daily_rate,
            "assignment_type": "transferred" if w.id in assigned_ids and w.id not in default_ids else "default"
        } for w in workers
    ]


# ── SUPERVISOR MULTI-SITE ──────────────────────
class SupervisorAssignIn(BaseModel):
    supervisor_id: str
    site_ids: List[str]
    primary_site_id: Optional[str] = None

@router.get("/supervisor-assignments/{supervisor_id}")
def get_supervisor_sites(
    supervisor_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    assignments = db.query(SupervisorSiteAssignment).filter(
        SupervisorSiteAssignment.tenant_id == current_user["tenant_id"],
        SupervisorSiteAssignment.supervisor_id == supervisor_id
    ).all()
    return [
        {"site_id": a.site_id, "site_name": db.query(Site).filter(Site.id == a.site_id).first().name if db.query(Site).filter(Site.id == a.site_id).first() else None, "is_primary": a.is_primary}
        for a in assignments
    ]

@router.post("/supervisor-assignments")
def assign_supervisor_sites(
    data: SupervisorAssignIn,
    current_user: dict = Depends(require_perm("users")),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    db.query(SupervisorSiteAssignment).filter(
        SupervisorSiteAssignment.tenant_id == tid,
        SupervisorSiteAssignment.supervisor_id == data.supervisor_id
    ).delete()
    for site_id in data.site_ids:
        db.add(SupervisorSiteAssignment(
            id=gen_id(), tenant_id=tid,
            supervisor_id=data.supervisor_id, site_id=site_id,
            is_primary=(site_id == data.primary_site_id)
        ))
    db.commit()
    return {"message": f"{len(data.site_ids)} sites assigned"}


# ── CLIENT CONTRACTS ───────────────────────────
class MilestoneIn(BaseModel):
    si_no: str
    description: str
    unit: str = "LS"
    quantity: float = 0
    rate: float = 0
    amount: float = 0
    payment_pct: float = 100
    is_parent: bool = False
    parent_si: Optional[str] = None
    notes: Optional[str] = None

class ClientContractIn(BaseModel):
    site_id: Optional[str] = None
    client_name: str
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    client_address: Optional[str] = None
    client_gstin: Optional[str] = None
    client_pan: Optional[str] = None
    contract_type: ClientContractType = ClientContractType.labour_material
    contract_value: float = 0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    scope_of_work: Optional[str] = None
    advance_pct: float = 10
    advance_received: float = 0
    retention_pct: float = 5
    gst_rate: float = 12
    tds_rate: float = 10
    notes: Optional[str] = None
    milestones: List[MilestoneIn] = []

@router.get("/contracts")
def list_client_contracts(
    site_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(ClientContract).filter(ClientContract.tenant_id == tid)
    if site_id: q = q.filter(ClientContract.site_id == site_id)
    if status: q = q.filter(ClientContract.status == status)
    contracts = q.order_by(ClientContract.created_at.desc()).all()
    result = []
    for c in contracts:
        s = db.query(Site).filter(Site.id == c.site_id).first() if c.site_id else None
        bills = db.query(ClientRABill).filter(ClientRABill.contract_id == c.id).all()
        payments = db.query(ClientPayment).filter(ClientPayment.contract_id == c.id).all()
        total_billed = sum(b.this_bill for b in bills if b.status != ClientRABillStatus.draft)
        total_received = sum(p.net_received for p in payments)
        milestones = db.query(ContractMilestone).filter(
            ContractMilestone.contract_id == c.id, ContractMilestone.is_parent == False
        ).all()
        done_count = sum(1 for m in milestones if m.status in [MilestoneStatus.completed, MilestoneStatus.billed, MilestoneStatus.paid])
        result.append({
            "id": c.id, "contract_no": c.contract_no,
            "client_name": c.client_name, "client_phone": c.client_phone,
            "site_name": s.name if s else None, "site_id": c.site_id,
            "contract_type": c.contract_type.value, "status": c.status.value,
            "contract_value": c.contract_value,
            "advance_received": c.advance_received,
            "total_billed": total_billed, "total_received": total_received,
            "balance_due": total_billed - total_received,
            "retention_pct": c.retention_pct,
            "milestone_count": len(milestones), "done_count": done_count,
            "start_date": str(c.start_date) if c.start_date else None,
        })
    return result

@router.post("/contracts")
def create_client_contract(
    data: ClientContractIn,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    count = db.query(func.count(ClientContract.id)).filter(ClientContract.tenant_id == tid).scalar()
    contract_no = f"CC-{date.today().year}-{str(count+1).zfill(3)}"
    c = ClientContract(
        id=gen_id(), tenant_id=tid, contract_no=contract_no,
        site_id=data.site_id, client_name=data.client_name,
        client_phone=data.client_phone, client_email=data.client_email,
        client_address=data.client_address, client_gstin=data.client_gstin,
        client_pan=data.client_pan, contract_type=data.contract_type,
        contract_value=data.contract_value, start_date=data.start_date,
        end_date=data.end_date, scope_of_work=data.scope_of_work,
        advance_pct=data.advance_pct, advance_received=data.advance_received,
        retention_pct=data.retention_pct, gst_rate=data.gst_rate,
        tds_rate=data.tds_rate, notes=data.notes, created_by=current_user["id"]
    )
    db.add(c); db.flush()
    for m in data.milestones:
        amt = m.amount if m.amount else round(m.quantity * m.rate, 2)
        db.add(ContractMilestone(
            id=gen_id(), contract_id=c.id,
            si_no=m.si_no, description=m.description, unit=m.unit,
            quantity=m.quantity, rate=m.rate, amount=amt,
            payment_pct=m.payment_pct, is_parent=m.is_parent,
            parent_si=m.parent_si, notes=m.notes
        ))
    db.commit()
    return {"id": c.id, "contract_no": contract_no}

@router.get("/contracts/{cid}")
def get_client_contract(cid: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(ClientContract).filter(ClientContract.id == cid, ClientContract.tenant_id == current_user["tenant_id"]).first()
    if not c: raise HTTPException(404)
    s = db.query(Site).filter(Site.id == c.site_id).first() if c.site_id else None
    milestones = db.query(ContractMilestone).filter(ContractMilestone.contract_id == cid).order_by(ContractMilestone.si_no).all()
    bills = db.query(ClientRABill).filter(ClientRABill.contract_id == cid).order_by(ClientRABill.ra_number).all()
    payments = db.query(ClientPayment).filter(ClientPayment.contract_id == cid).order_by(ClientPayment.date).all()
    return {
        "id": c.id, "contract_no": c.contract_no,
        "client_name": c.client_name, "client_phone": c.client_phone,
        "client_gstin": c.client_gstin, "client_pan": c.client_pan,
        "client_address": c.client_address,
        "site_name": s.name if s else None, "site_id": c.site_id,
        "contract_type": c.contract_type.value, "status": c.status.value,
        "contract_value": c.contract_value,
        "advance_pct": c.advance_pct, "advance_received": c.advance_received,
        "retention_pct": c.retention_pct, "gst_rate": c.gst_rate, "tds_rate": c.tds_rate,
        "start_date": str(c.start_date) if c.start_date else None,
        "end_date": str(c.end_date) if c.end_date else None,
        "scope_of_work": c.scope_of_work,
        "total_billed": sum(b.this_bill for b in bills if b.status != ClientRABillStatus.draft),
        "total_received": sum(p.net_received for p in payments),
        "milestones": [{"id": m.id, "si_no": m.si_no, "description": m.description, "unit": m.unit, "quantity": m.quantity, "rate": m.rate, "amount": m.amount, "payment_pct": m.payment_pct, "status": m.status.value, "completion_pct": m.completion_pct, "is_parent": m.is_parent, "parent_si": m.parent_si, "completed_date": str(m.completed_date) if m.completed_date else None, "notes": m.notes} for m in milestones],
        "bills": [{"id": b.id, "bill_no": b.bill_no, "ra_number": b.ra_number, "bill_date": str(b.bill_date), "this_bill": b.this_bill, "net_payable": b.net_payable, "paid_amount": b.paid_amount, "balance_due": b.balance_due, "status": b.status.value} for b in bills],
        "payments": [{"id": p.id, "date": str(p.date), "amount": p.amount, "tds_deducted": p.tds_deducted, "net_received": p.net_received, "payment_mode": p.payment_mode, "ref_no": p.ref_no, "is_advance": p.is_advance} for p in payments]
    }

class MilestoneUpdateIn(BaseModel):
    milestone_id: str
    status: MilestoneStatus
    completion_pct: float = 0
    completed_date: Optional[date] = None
    notes: Optional[str] = None

@router.post("/contracts/{cid}/update-milestones")
def update_milestones(cid: str, updates: List[MilestoneUpdateIn], current_user: dict = Depends(require_perm("attendance")), db: Session = Depends(get_db)):
    c = db.query(ClientContract).filter(ClientContract.id == cid, ClientContract.tenant_id == current_user["tenant_id"]).first()
    if not c: raise HTTPException(404)
    for upd in updates:
        m = db.query(ContractMilestone).filter(ContractMilestone.id == upd.milestone_id).first()
        if m:
            m.status = upd.status
            m.completion_pct = upd.completion_pct
            if upd.completed_date: m.completed_date = upd.completed_date
            if upd.notes: m.notes = upd.notes
    db.commit()
    return {"message": f"{len(updates)} milestones updated"}


# ── CLIENT RA BILL ─────────────────────────────
class ClientRABillIn(BaseModel):
    contract_id: str
    bill_date: date
    due_date: Optional[date] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    advance_recovery: float = 0
    notes: Optional[str] = None

@router.post("/ra-bills/generate")
def generate_client_ra_bill(
    data: ClientRABillIn,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    c = db.query(ClientContract).filter(ClientContract.id == data.contract_id, ClientContract.tenant_id == tid).first()
    if not c: raise HTTPException(404)
    milestones = db.query(ContractMilestone).filter(ContractMilestone.contract_id == c.id, ContractMilestone.is_parent == False).all()
    prev_bills = db.query(ClientRABill).filter(ClientRABill.contract_id == c.id, ClientRABill.status != ClientRABillStatus.draft).all()
    prev_total = sum(b.this_bill for b in prev_bills)
    ra_num = len(prev_bills) + 1
    bill_items = []
    this_bill_total = 0
    for m in milestones:
        if m.status in [MilestoneStatus.completed, MilestoneStatus.billed, MilestoneStatus.paid]:
            this_amt = m.amount
        elif m.status == MilestoneStatus.in_progress:
            this_amt = round(m.amount * m.completion_pct / 100, 2)
        else:
            this_amt = 0
        prev_items = db.query(ClientRABillItem).join(ClientRABill).filter(ClientRABill.contract_id == c.id, ClientRABillItem.milestone_id == m.id, ClientRABill.status != ClientRABillStatus.draft).all()
        prev_amt = sum(i.this_amount for i in prev_items)
        net_this = max(0, this_amt - prev_amt)
        this_bill_total += net_this
        bill_items.append({"milestone_id": m.id, "si_no": m.si_no, "description": m.description, "unit": m.unit, "quantity": m.quantity, "rate": m.rate, "contract_amount": m.amount, "prev_amount": prev_amt, "this_amount": net_this, "completion_pct": m.completion_pct, "status": m.status})
    retention = round(this_bill_total * c.retention_pct / 100, 2)
    tds = round(this_bill_total * c.tds_rate / 100, 2)
    gst = round(this_bill_total * c.gst_rate / 100, 2)
    net_payable = round(this_bill_total + gst - retention - tds - data.advance_recovery, 2)
    bill_no = f"INV-{date.today().year}-{ra_num:03d}"
    b = ClientRABill(
        id=gen_id(), tenant_id=tid, bill_no=bill_no, ra_number=ra_num,
        contract_id=c.id, bill_date=data.bill_date, due_date=data.due_date,
        period_from=data.period_from, period_to=data.period_to,
        gross_amount=prev_total+this_bill_total, prev_billed=prev_total,
        this_bill=this_bill_total, advance_recovery=data.advance_recovery,
        retention_amt=retention, tds_amt=tds, gst_amt=gst,
        net_payable=net_payable, balance_due=net_payable,
        notes=data.notes, created_by=current_user["id"]
    )
    db.add(b); db.flush()
    for bi in bill_items:
        if bi["this_amount"] > 0:
            db.add(ClientRABillItem(id=gen_id(), bill_id=b.id, milestone_id=bi["milestone_id"], si_no=bi["si_no"], description=bi["description"], unit=bi["unit"], quantity=bi["quantity"], rate=bi["rate"], contract_amount=bi["contract_amount"], prev_amount=bi["prev_amount"], this_amount=bi["this_amount"], completion_pct=bi["completion_pct"], status=bi["status"]))
    db.commit()
    return {"id": b.id, "bill_no": bill_no, "ra_number": ra_num, "this_bill": this_bill_total, "net_payable": net_payable}

@router.get("/ra-bills")
def list_client_ra_bills(
    contract_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(ClientRABill).filter(ClientRABill.tenant_id == tid)
    if contract_id: q = q.filter(ClientRABill.contract_id == contract_id)
    if status: q = q.filter(ClientRABill.status == status)
    bills = q.order_by(ClientRABill.bill_date.desc()).all()
    result = []
    for b in bills:
        c = b.contract
        result.append({"id": b.id, "bill_no": b.bill_no, "ra_number": b.ra_number, "bill_date": str(b.bill_date), "client_name": c.client_name if c else None, "this_bill": b.this_bill, "gst_amt": b.gst_amt, "net_payable": b.net_payable, "paid_amount": b.paid_amount, "balance_due": b.balance_due, "due_date": str(b.due_date) if b.due_date else None, "status": b.status.value})
    return result

@router.get("/ra-bills/{bid}")
def get_client_ra_bill(bid: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.query(ClientRABill).filter(ClientRABill.id == bid, ClientRABill.tenant_id == current_user["tenant_id"]).first()
    if not b: raise HTTPException(404)
    c = b.contract
    s = db.query(Site).filter(Site.id == c.site_id).first() if c and c.site_id else None
    items = db.query(ClientRABillItem).filter(ClientRABillItem.bill_id == bid, ClientRABillItem.this_amount > 0).all()
    return {
        "id": b.id, "bill_no": b.bill_no, "ra_number": b.ra_number,
        "bill_date": str(b.bill_date), "due_date": str(b.due_date) if b.due_date else None,
        "period_from": str(b.period_from) if b.period_from else None, "period_to": str(b.period_to) if b.period_to else None,
        "contract": {"no": c.contract_no, "type": c.contract_type.value, "client": c.client_name, "phone": c.client_phone, "gstin": c.client_gstin, "pan": c.client_pan, "address": c.client_address, "retention_pct": c.retention_pct, "tds_rate": c.tds_rate, "gst_rate": c.gst_rate, "value": c.contract_value},
        "site_name": s.name if s else None,
        "amounts": {"gross_cumulative": b.gross_amount, "prev_billed": b.prev_billed, "this_bill": b.this_bill, "retention": b.retention_amt, "tds": b.tds_amt, "gst": b.gst_amt, "advance_recovery": b.advance_recovery, "net_payable": b.net_payable, "paid": b.paid_amount, "balance": b.balance_due},
        "status": b.status.value, "notes": b.notes,
        "items": [{"si_no": i.si_no, "description": i.description, "unit": i.unit, "quantity": i.quantity, "rate": i.rate, "contract_amount": i.contract_amount, "prev_amount": i.prev_amount, "this_amount": i.this_amount, "status": i.status.value if i.status else None} for i in items]
    }

@router.post("/ra-bills/{bid}/submit")
def submit_bill(bid: str, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    b = db.query(ClientRABill).filter(ClientRABill.id == bid, ClientRABill.tenant_id == current_user["tenant_id"]).first()
    if not b: raise HTTPException(404)
    b.status = ClientRABillStatus.submitted; db.commit()
    return {"message": "Bill submitted to client"}

@router.post("/ra-bills/{bid}/payment")
def record_client_payment(bid: str, amount: float, tds_deducted: float = 0, payment_mode: str = "NEFT", ref_no: Optional[str] = None, is_advance: bool = False, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    tid = current_user["tenant_id"]
    b = db.query(ClientRABill).filter(ClientRABill.id == bid, ClientRABill.tenant_id == tid).first()
    if not b: raise HTTPException(404)
    net = amount - tds_deducted
    db.add(ClientPayment(id=gen_id(), tenant_id=tid, bill_id=bid, contract_id=b.contract_id, date=date.today(), amount=amount, tds_deducted=tds_deducted, net_received=net, payment_mode=payment_mode, ref_no=ref_no, is_advance=is_advance))
    b.paid_amount = (b.paid_amount or 0) + net
    b.balance_due = b.net_payable - b.paid_amount
    b.status = ClientRABillStatus.paid if b.balance_due <= 0 else ClientRABillStatus.partial
    db.commit()
    return {"message": "Payment recorded", "net_received": net, "balance_due": b.balance_due}


# ── DAILY SITE REPORT ──────────────────────────
class DailySiteReportIn(BaseModel):
    site_id: str
    date: date
    workers_present: int = 0
    work_done: Optional[str] = None
    material_used: Optional[str] = None
    issues: Optional[str] = None
    weather: str = "Clear"

@router.get("/daily-reports")
def list_daily_reports(site_id: Optional[str] = None, month: Optional[str] = None, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = current_user["tenant_id"]
    q = db.query(DailySiteReport).filter(DailySiteReport.tenant_id == tid)
    if site_id: q = q.filter(DailySiteReport.site_id == site_id)
    if month:
        yr, mn = month.split("-")
        q = q.filter(extract("year", DailySiteReport.date) == int(yr), extract("month", DailySiteReport.date) == int(mn))
    reports = q.order_by(DailySiteReport.date.desc()).limit(100).all()
    return [{"id": r.id, "site_name": db.query(Site).filter(Site.id == r.site_id).first().name if db.query(Site).filter(Site.id == r.site_id).first() else None, "date": str(r.date), "workers_present": r.workers_present, "work_done": r.work_done, "issues": r.issues, "weather": r.weather} for r in reports]

@router.post("/daily-reports")
def submit_daily_report(data: DailySiteReportIn, current_user: dict = Depends(require_perm("attendance")), db: Session = Depends(get_db)):
    tid = current_user["tenant_id"]
    existing = db.query(DailySiteReport).filter(DailySiteReport.tenant_id == tid, DailySiteReport.site_id == data.site_id, DailySiteReport.date == data.date).first()
    if existing:
        for k, v in data.model_dump().items(): setattr(existing, k, v)
        existing.submitted_by = current_user["id"]
        db.commit()
        return {"id": existing.id, "message": "Report updated"}
    r = DailySiteReport(id=gen_id(), tenant_id=tid, submitted_by=current_user["id"], **data.model_dump())
    db.add(r); db.commit()
    return {"id": r.id, "message": "Report submitted"}


# ── MATERIAL TRACKING ──────────────────────────
class MaterialTxnIn(BaseModel):
    site_id: str
    date: date
    item_name: str
    category: Optional[str] = None
    unit: str
    txn_type: str
    quantity: float
    rate: float = 0
    from_site_id: Optional[str] = None
    to_site_id: Optional[str] = None
    vendor_name: Optional[str] = None
    bill_no: Optional[str] = None
    notes: Optional[str] = None

@router.get("/materials/stock/{site_id}")
def site_stock(site_id: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    txns = db.query(MaterialTransaction).filter(MaterialTransaction.tenant_id == current_user["tenant_id"], MaterialTransaction.site_id == site_id).all()
    stock = {}
    for t in txns:
        key = f"{t.item_name}|{t.unit}"
        if key not in stock: stock[key] = {"item": t.item_name, "unit": t.unit, "qty_in": 0, "qty_out": 0, "category": t.category}
        if t.txn_type == "in": stock[key]["qty_in"] += t.quantity
        elif t.txn_type == "out": stock[key]["qty_out"] += t.quantity
    for v in stock.values(): v["current_stock"] = v["qty_in"] - v["qty_out"]
    return sorted(stock.values(), key=lambda x: x["item"])

@router.post("/materials")
def add_material(data: MaterialTxnIn, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    tid = current_user["tenant_id"]
    t = MaterialTransaction(id=gen_id(), tenant_id=tid, amount=round(data.quantity * data.rate, 2), entered_by=current_user["id"], **data.model_dump())
    db.add(t)
    if data.txn_type == "transfer" and data.to_site_id:
        db.add(MaterialTransaction(id=gen_id(), tenant_id=tid, site_id=data.to_site_id, date=data.date, item_name=data.item_name, unit=data.unit, txn_type="in", quantity=data.quantity, rate=data.rate, amount=round(data.quantity * data.rate, 2), from_site_id=data.site_id, category=data.category, notes=f"Transfer: {data.notes or ''}", entered_by=current_user["id"]))
    db.commit()
    return {"message": "Material entry added"}
