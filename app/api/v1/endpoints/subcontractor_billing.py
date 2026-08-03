from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import date
from app.db.session import get_db
from app.core.deps import get_current_user, require_perm
from app.models.models import (
    Site, Vendor,
    SubContract, SubContractType, SubContractStatus,
    SubMilestone, MilestoneStatus,
    SubRABill, SubRABillItem, SubRABillStatus,
    SubPayment,
)
from pydantic import BaseModel
import uuid

router = APIRouter(prefix="/subcontractor", tags=["Sub-Contractor Billing"])
gen_id = lambda: str(uuid.uuid4())


# ── CONTRACT ────────────────────────────────────
class SubMilestoneIn(BaseModel):
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

class SubContractIn(BaseModel):
    site_id: Optional[str] = None
    vendor_id: Optional[str] = None
    subcontractor_name: str
    subcontractor_phone: Optional[str] = None
    subcontractor_gstin: Optional[str] = None
    contract_type: SubContractType = SubContractType.labour_material
    contract_value: float = 0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    scope_of_work: Optional[str] = None
    advance_pct: float = 10
    advance_paid: float = 0
    retention_pct: float = 5
    tds_rate: float = 1
    gst_rate: float = 0
    notes: Optional[str] = None
    milestones: List[SubMilestoneIn] = []

@router.get("/contracts")
def list_sub_contracts(
    site_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(SubContract).filter(SubContract.tenant_id == tid)
    if site_id: q = q.filter(SubContract.site_id == site_id)
    if status: q = q.filter(SubContract.status == status)
    contracts = q.order_by(SubContract.created_at.desc()).all()
    result = []
    for c in contracts:
        s = db.query(Site).filter(Site.id == c.site_id).first() if c.site_id else None
        bills = db.query(SubRABill).filter(SubRABill.contract_id == c.id).all()
        payments = db.query(SubPayment).filter(SubPayment.contract_id == c.id).all()
        total_billed = sum(b.this_bill for b in bills if b.status != SubRABillStatus.draft)
        total_paid = sum(p.net_paid for p in payments)
        milestones = db.query(SubMilestone).filter(
            SubMilestone.contract_id == c.id, SubMilestone.is_parent == False
        ).all()
        done_count = sum(1 for m in milestones if m.status in [MilestoneStatus.completed, MilestoneStatus.billed, MilestoneStatus.paid])
        result.append({
            "id": c.id, "contract_no": c.contract_no,
            "subcontractor_name": c.subcontractor_name, "subcontractor_phone": c.subcontractor_phone,
            "site_name": s.name if s else None, "site_id": c.site_id,
            "contract_type": c.contract_type.value, "status": c.status.value,
            "contract_value": c.contract_value,
            "advance_paid": c.advance_paid,
            "total_billed": total_billed, "total_paid": total_paid,
            "balance_due": total_billed - total_paid,
            "retention_pct": c.retention_pct,
            "milestone_count": len(milestones), "done_count": done_count,
            "start_date": str(c.start_date) if c.start_date else None,
        })
    return result

@router.post("/contracts")
def create_sub_contract(
    data: SubContractIn,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    count = db.query(func.count(SubContract.id)).filter(SubContract.tenant_id == tid).scalar()
    contract_no = f"SC-{date.today().year}-{str(count+1).zfill(3)}"
    c = SubContract(
        id=gen_id(), tenant_id=tid, contract_no=contract_no,
        site_id=data.site_id, vendor_id=data.vendor_id,
        subcontractor_name=data.subcontractor_name, subcontractor_phone=data.subcontractor_phone,
        subcontractor_gstin=data.subcontractor_gstin, contract_type=data.contract_type,
        contract_value=data.contract_value, start_date=data.start_date,
        end_date=data.end_date, scope_of_work=data.scope_of_work,
        advance_pct=data.advance_pct, advance_paid=data.advance_paid,
        retention_pct=data.retention_pct, tds_rate=data.tds_rate,
        gst_rate=data.gst_rate, notes=data.notes, created_by=current_user["id"]
    )
    db.add(c); db.flush()
    for m in data.milestones:
        amt = m.amount if m.amount else round(m.quantity * m.rate, 2)
        db.add(SubMilestone(
            id=gen_id(), contract_id=c.id,
            si_no=m.si_no, description=m.description, unit=m.unit,
            quantity=m.quantity, rate=m.rate, amount=amt,
            payment_pct=m.payment_pct, is_parent=m.is_parent,
            parent_si=m.parent_si, notes=m.notes
        ))
    db.commit()
    return {"id": c.id, "contract_no": contract_no}

@router.get("/contracts/{cid}")
def get_sub_contract(cid: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(SubContract).filter(SubContract.id == cid, SubContract.tenant_id == current_user["tenant_id"]).first()
    if not c: raise HTTPException(404)
    s = db.query(Site).filter(Site.id == c.site_id).first() if c.site_id else None
    milestones = db.query(SubMilestone).filter(SubMilestone.contract_id == cid).order_by(SubMilestone.si_no).all()
    bills = db.query(SubRABill).filter(SubRABill.contract_id == cid).order_by(SubRABill.ra_number).all()
    payments = db.query(SubPayment).filter(SubPayment.contract_id == cid).order_by(SubPayment.date).all()
    return {
        "id": c.id, "contract_no": c.contract_no,
        "subcontractor_name": c.subcontractor_name, "subcontractor_phone": c.subcontractor_phone,
        "subcontractor_gstin": c.subcontractor_gstin,
        "site_name": s.name if s else None, "site_id": c.site_id,
        "contract_type": c.contract_type.value, "status": c.status.value,
        "contract_value": c.contract_value,
        "advance_pct": c.advance_pct, "advance_paid": c.advance_paid,
        "retention_pct": c.retention_pct, "gst_rate": c.gst_rate, "tds_rate": c.tds_rate,
        "start_date": str(c.start_date) if c.start_date else None,
        "end_date": str(c.end_date) if c.end_date else None,
        "scope_of_work": c.scope_of_work,
        "total_billed": sum(b.this_bill for b in bills if b.status != SubRABillStatus.draft),
        "total_paid": sum(p.net_paid for p in payments),
        "milestones": [{"id": m.id, "si_no": m.si_no, "description": m.description, "unit": m.unit, "quantity": m.quantity, "rate": m.rate, "amount": m.amount, "payment_pct": m.payment_pct, "status": m.status.value, "completion_pct": m.completion_pct, "is_parent": m.is_parent, "parent_si": m.parent_si, "completed_date": str(m.completed_date) if m.completed_date else None, "notes": m.notes} for m in milestones],
        "bills": [{"id": b.id, "bill_no": b.bill_no, "ra_number": b.ra_number, "bill_date": str(b.bill_date), "this_bill": b.this_bill, "net_payable": b.net_payable, "paid_amount": b.paid_amount, "balance_due": b.balance_due, "status": b.status.value} for b in bills],
        "payments": [{"id": p.id, "date": str(p.date), "amount": p.amount, "tds_deducted": p.tds_deducted, "net_paid": p.net_paid, "payment_mode": p.payment_mode, "ref_no": p.ref_no, "is_advance": p.is_advance} for p in payments]
    }

class SubMilestoneUpdateIn(BaseModel):
    milestone_id: str
    status: MilestoneStatus
    completion_pct: float = 0
    completed_date: Optional[date] = None
    notes: Optional[str] = None

@router.post("/contracts/{cid}/update-milestones")
def update_sub_milestones(cid: str, updates: List[SubMilestoneUpdateIn], current_user: dict = Depends(require_perm("attendance")), db: Session = Depends(get_db)):
    c = db.query(SubContract).filter(SubContract.id == cid, SubContract.tenant_id == current_user["tenant_id"]).first()
    if not c: raise HTTPException(404)
    for upd in updates:
        m = db.query(SubMilestone).filter(SubMilestone.id == upd.milestone_id).first()
        if m:
            m.status = upd.status
            m.completion_pct = upd.completion_pct
            if upd.completed_date: m.completed_date = upd.completed_date
            if upd.notes: m.notes = upd.notes
    db.commit()
    return {"message": f"{len(updates)} milestones updated"}


# ── SUB-CONTRACTOR RA BILL ─────────────────────
class SubRABillIn(BaseModel):
    contract_id: str
    bill_date: date
    due_date: Optional[date] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    advance_recovery: float = 0
    notes: Optional[str] = None

@router.post("/ra-bills/generate")
def generate_sub_ra_bill(
    data: SubRABillIn,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    c = db.query(SubContract).filter(SubContract.id == data.contract_id, SubContract.tenant_id == tid).first()
    if not c: raise HTTPException(404)
    milestones = db.query(SubMilestone).filter(SubMilestone.contract_id == c.id, SubMilestone.is_parent == False).all()
    prev_bills = db.query(SubRABill).filter(SubRABill.contract_id == c.id, SubRABill.status != SubRABillStatus.draft).all()
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
        prev_items = db.query(SubRABillItem).join(SubRABill).filter(SubRABill.contract_id == c.id, SubRABillItem.milestone_id == m.id, SubRABill.status != SubRABillStatus.draft).all()
        prev_amt = sum(i.this_amount for i in prev_items)
        net_this = max(0, this_amt - prev_amt)
        this_bill_total += net_this
        bill_items.append({"milestone_id": m.id, "si_no": m.si_no, "description": m.description, "unit": m.unit, "quantity": m.quantity, "rate": m.rate, "contract_amount": m.amount, "prev_amount": prev_amt, "this_amount": net_this, "completion_pct": m.completion_pct, "status": m.status})
    retention = round(this_bill_total * c.retention_pct / 100, 2)
    tds = round(this_bill_total * c.tds_rate / 100, 2)
    gst = round(this_bill_total * c.gst_rate / 100, 2)
    net_payable = round(this_bill_total + gst - retention - tds - data.advance_recovery, 2)
    bill_no = f"SUB-{date.today().year}-{ra_num:03d}"
    b = SubRABill(
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
            db.add(SubRABillItem(id=gen_id(), bill_id=b.id, milestone_id=bi["milestone_id"], si_no=bi["si_no"], description=bi["description"], unit=bi["unit"], quantity=bi["quantity"], rate=bi["rate"], contract_amount=bi["contract_amount"], prev_amount=bi["prev_amount"], this_amount=bi["this_amount"], completion_pct=bi["completion_pct"], status=bi["status"]))
    db.commit()
    return {"id": b.id, "bill_no": bill_no, "ra_number": ra_num, "this_bill": this_bill_total, "net_payable": net_payable}

@router.get("/ra-bills")
def list_sub_ra_bills(
    contract_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(SubRABill).filter(SubRABill.tenant_id == tid)
    if contract_id: q = q.filter(SubRABill.contract_id == contract_id)
    if status: q = q.filter(SubRABill.status == status)
    bills = q.order_by(SubRABill.bill_date.desc()).all()
    result = []
    for b in bills:
        c = b.contract
        result.append({"id": b.id, "bill_no": b.bill_no, "ra_number": b.ra_number, "bill_date": str(b.bill_date), "subcontractor_name": c.subcontractor_name if c else None, "this_bill": b.this_bill, "gst_amt": b.gst_amt, "net_payable": b.net_payable, "paid_amount": b.paid_amount, "balance_due": b.balance_due, "due_date": str(b.due_date) if b.due_date else None, "status": b.status.value})
    return result

@router.get("/ra-bills/{bid}")
def get_sub_ra_bill(bid: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.query(SubRABill).filter(SubRABill.id == bid, SubRABill.tenant_id == current_user["tenant_id"]).first()
    if not b: raise HTTPException(404)
    c = b.contract
    s = db.query(Site).filter(Site.id == c.site_id).first() if c and c.site_id else None
    items = db.query(SubRABillItem).filter(SubRABillItem.bill_id == bid, SubRABillItem.this_amount > 0).all()
    return {
        "id": b.id, "bill_no": b.bill_no, "ra_number": b.ra_number,
        "bill_date": str(b.bill_date), "due_date": str(b.due_date) if b.due_date else None,
        "period_from": str(b.period_from) if b.period_from else None, "period_to": str(b.period_to) if b.period_to else None,
        "contract": {"no": c.contract_no, "type": c.contract_type.value, "subcontractor": c.subcontractor_name, "phone": c.subcontractor_phone, "gstin": c.subcontractor_gstin, "retention_pct": c.retention_pct, "tds_rate": c.tds_rate, "gst_rate": c.gst_rate, "value": c.contract_value},
        "site_name": s.name if s else None,
        "amounts": {"gross_cumulative": b.gross_amount, "prev_billed": b.prev_billed, "this_bill": b.this_bill, "retention": b.retention_amt, "tds": b.tds_amt, "gst": b.gst_amt, "advance_recovery": b.advance_recovery, "net_payable": b.net_payable, "paid": b.paid_amount, "balance": b.balance_due},
        "status": b.status.value, "notes": b.notes,
        "items": [{"si_no": i.si_no, "description": i.description, "unit": i.unit, "quantity": i.quantity, "rate": i.rate, "contract_amount": i.contract_amount, "prev_amount": i.prev_amount, "this_amount": i.this_amount, "status": i.status.value if i.status else None} for i in items]
    }

@router.post("/ra-bills/{bid}/submit")
def submit_sub_bill(bid: str, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    b = db.query(SubRABill).filter(SubRABill.id == bid, SubRABill.tenant_id == current_user["tenant_id"]).first()
    if not b: raise HTTPException(404)
    b.status = SubRABillStatus.submitted; db.commit()
    return {"message": "Bill certified"}

@router.post("/ra-bills/{bid}/payment")
def record_sub_payment(bid: str, amount: float, tds_deducted: float = 0, payment_mode: str = "NEFT", ref_no: Optional[str] = None, is_advance: bool = False, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    tid = current_user["tenant_id"]
    b = db.query(SubRABill).filter(SubRABill.id == bid, SubRABill.tenant_id == tid).first()
    if not b: raise HTTPException(404)
    net = amount - tds_deducted
    db.add(SubPayment(id=gen_id(), tenant_id=tid, bill_id=bid, contract_id=b.contract_id, date=date.today(), amount=amount, tds_deducted=tds_deducted, net_paid=net, payment_mode=payment_mode, ref_no=ref_no, is_advance=is_advance))
    b.paid_amount = (b.paid_amount or 0) + net
    b.balance_due = b.net_payable - b.paid_amount
    b.status = SubRABillStatus.paid if b.balance_due <= 0 else SubRABillStatus.partial
    db.commit()
    return {"message": "Payment recorded", "net_paid": net, "balance_due": b.balance_due}
