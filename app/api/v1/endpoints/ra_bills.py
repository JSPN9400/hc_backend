from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from typing import List, Optional
from datetime import date, datetime
from app.db.session import get_db
from app.core.deps import get_current_user, require_perm
from app.models.models import Site, User
from pydantic import BaseModel
from typing import Any
import uuid

router = APIRouter(prefix="/ra-bills", tags=["RA Bills"])
gen_id = lambda: str(uuid.uuid4())

# ══════════════════════════════════════════
# INLINE MODELS (no separate file needed)
# ══════════════════════════════════════════
from sqlalchemy import Column, String, Float, Boolean, Date, DateTime, ForeignKey, Text, Enum, Integer, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func as sqlfunc
from app.db.session import Base
import enum

class ContractType(str, enum.Enum):
    labour = "labour"
    labour_material = "labour_material"

class WorkStatus(str, enum.Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    done = "done"
    partially_done = "partially_done"

class BillStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    paid = "paid"

class Contract(Base):
    __tablename__ = "contracts"
    id              = Column(String, primary_key=True, default=gen_id)
    tenant_id       = Column(String, nullable=False, index=True)
    contract_no     = Column(String(30))
    site_id         = Column(String, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    party_name      = Column(String(300), nullable=False)
    party_phone     = Column(String(20))
    party_gstin     = Column(String(20))
    party_pan       = Column(String(15))
    contract_type   = Column(Enum(ContractType), default=ContractType.labour)
    total_value     = Column(Float, default=0)
    retention_pct   = Column(Float, default=5)
    tds_rate        = Column(Float, default=1)
    gst_rate        = Column(Float, default=18)
    advance_paid    = Column(Float, default=0)
    start_date      = Column(Date)
    end_date        = Column(Date)
    description     = Column(Text)
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime, server_default=sqlfunc.now())
    site            = relationship("Site", foreign_keys=[site_id])
    boq_items       = relationship("BOQItem", back_populates="contract", cascade="all, delete")
    ra_bills        = relationship("RABill", back_populates="contract", cascade="all, delete")

class BOQItem(Base):
    __tablename__ = "boq_items"
    id              = Column(String, primary_key=True, default=gen_id)
    contract_id     = Column(String, ForeignKey("contracts.id", ondelete="CASCADE"))
    si_no           = Column(String(10))       # 0.1, 1, 1.1, 2.1 etc
    description     = Column(String(500), nullable=False)
    unit            = Column(String(20))       # SQ.FT, CUM, RMT, NOS, LS (Lump Sum)
    quantity        = Column(Float, default=0)
    rate            = Column(Float, default=0)
    amount          = Column(Float, default=0) # quantity × rate
    payment_pct     = Column(Float, default=100)  # % of parent item (60%, 40%)
    payment_amount  = Column(Float, default=0)    # actual payment amount
    work_status     = Column(Enum(WorkStatus), default=WorkStatus.not_started)
    completion_pct  = Column(Float, default=0)    # 0-100
    is_parent       = Column(Boolean, default=False)  # 1, 2, 3 are parents
    parent_si       = Column(String(10))          # parent's si_no
    notes           = Column(String(300))
    updated_at      = Column(DateTime, server_default=sqlfunc.now(), onupdate=sqlfunc.now())
    contract        = relationship("Contract", back_populates="boq_items")

class RABill(Base):
    __tablename__ = "ra_bills"
    id              = Column(String, primary_key=True, default=gen_id)
    tenant_id       = Column(String, nullable=False, index=True)
    bill_no         = Column(String(30))
    ra_number       = Column(Integer, default=1)  # RA-1, RA-2...
    contract_id     = Column(String, ForeignKey("contracts.id", ondelete="CASCADE"))
    bill_date       = Column(Date, nullable=False)
    period_from     = Column(Date)
    period_to       = Column(Date)
    # Amounts
    gross_amount    = Column(Float, default=0)    # Total work done value
    prev_billed     = Column(Float, default=0)    # Previously billed
    this_bill_amt   = Column(Float, default=0)    # This RA bill amount
    retention_amt   = Column(Float, default=0)
    tds_amt         = Column(Float, default=0)
    gst_amt         = Column(Float, default=0)
    advance_recovery= Column(Float, default=0)
    net_payable     = Column(Float, default=0)
    paid_amount     = Column(Float, default=0)
    balance_due     = Column(Float, default=0)
    status          = Column(Enum(BillStatus), default=BillStatus.draft)
    notes           = Column(Text)
    created_by      = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime, server_default=sqlfunc.now())
    contract        = relationship("Contract", back_populates="ra_bills")
    bill_items      = relationship("RABillItem", back_populates="bill", cascade="all, delete")

class RABillItem(Base):
    __tablename__ = "ra_bill_items"
    id              = Column(String, primary_key=True, default=gen_id)
    bill_id         = Column(String, ForeignKey("ra_bills.id", ondelete="CASCADE"))
    boq_item_id     = Column(String, ForeignKey("boq_items.id", ondelete="CASCADE"))
    si_no           = Column(String(10))
    description     = Column(String(500))
    unit            = Column(String(20))
    quantity        = Column(Float, default=0)
    rate            = Column(Float, default=0)
    total_amount    = Column(Float, default=0)   # Contract amount
    prev_amount     = Column(Float, default=0)   # Previously billed
    this_amount     = Column(Float, default=0)   # This bill
    work_status     = Column(Enum(WorkStatus))
    completion_pct  = Column(Float, default=0)
    bill            = relationship("RABill", back_populates="bill_items")


# ══════════════════════════════════════════
# SCHEMAS
# ══════════════════════════════════════════
class BOQItemIn(BaseModel):
    si_no: str
    description: str
    unit: Optional[str] = "LS"
    quantity: float = 0
    rate: float = 0
    amount: float = 0
    payment_pct: float = 100
    payment_amount: float = 0
    work_status: WorkStatus = WorkStatus.not_started
    completion_pct: float = 0
    is_parent: bool = False
    parent_si: Optional[str] = None
    notes: Optional[str] = None

class ContractIn(BaseModel):
    site_id: Optional[str] = None
    party_name: str
    party_phone: Optional[str] = None
    party_gstin: Optional[str] = None
    party_pan: Optional[str] = None
    contract_type: ContractType = ContractType.labour
    total_value: float = 0
    retention_pct: float = 5
    tds_rate: float = 1
    gst_rate: float = 18
    advance_paid: float = 0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    description: Optional[str] = None
    boq_items: List[BOQItemIn] = []

class WorkStatusUpdate(BaseModel):
    boq_item_id: str
    work_status: WorkStatus
    completion_pct: float = 0
    notes: Optional[str] = None

class RABillIn(BaseModel):
    contract_id: str
    bill_date: date
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    advance_recovery: float = 0
    notes: Optional[str] = None


# ══════════════════════════════════════════
# CONTRACTS
# ══════════════════════════════════════════
@router.get("/contracts")
def list_contracts(
    site_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(Contract).filter(Contract.tenant_id == tid, Contract.is_active == True)
    if site_id: q = q.filter(Contract.site_id == site_id)
    contracts = q.order_by(Contract.created_at.desc()).all()
    result = []
    for c in contracts:
        s = db.query(Site).filter(Site.id == c.site_id).first() if c.site_id else None
        boq = db.query(BOQItem).filter(BOQItem.contract_id == c.id).all()
        done_amt = sum(
            (i.payment_amount or i.amount or 0) for i in boq
            if i.work_status == WorkStatus.done and not i.is_parent
        )
        partial_amt = sum(
            (i.payment_amount or i.amount or 0) * (i.completion_pct/100) for i in boq
            if i.work_status == WorkStatus.partially_done and not i.is_parent
        )
        billed = sum(b.this_bill_amt for b in db.query(RABill).filter(RABill.contract_id == c.id).all())
        result.append({
            "id": c.id, "contract_no": c.contract_no,
            "site_name": s.name if s else None,
            "party_name": c.party_name, "party_phone": c.party_phone,
            "contract_type": c.contract_type.value,
            "total_value": c.total_value,
            "work_done_value": round(done_amt + partial_amt, 2),
            "total_billed": round(billed, 2),
            "balance_to_bill": round(done_amt + partial_amt - billed, 2),
            "retention_pct": c.retention_pct, "tds_rate": c.tds_rate,
            "boq_count": len([b for b in boq if not b.is_parent]),
            "done_count": len([b for b in boq if b.work_status == WorkStatus.done and not b.is_parent]),
            "start_date": str(c.start_date) if c.start_date else None,
            "created_at": str(c.created_at)
        })
    return result


@router.post("/contracts")
def create_contract(
    data: ContractIn,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    count = db.query(func.count(Contract.id)).filter(Contract.tenant_id == tid).scalar()
    contract_no = f"VC-C-{date.today().year}-{str(count+1).zfill(3)}"

    c = Contract(
        id=gen_id(), tenant_id=tid, contract_no=contract_no,
        site_id=data.site_id, party_name=data.party_name,
        party_phone=data.party_phone, party_gstin=data.party_gstin,
        party_pan=data.party_pan, contract_type=data.contract_type,
        total_value=data.total_value, retention_pct=data.retention_pct,
        tds_rate=data.tds_rate, gst_rate=data.gst_rate,
        advance_paid=data.advance_paid,
        start_date=data.start_date, end_date=data.end_date,
        description=data.description
    )
    db.add(c); db.flush()

    for item in data.boq_items:
        amt = item.amount if item.amount else round(item.quantity * item.rate, 2)
        pay_amt = item.payment_amount if item.payment_amount else round(amt * item.payment_pct / 100, 2)
        db.add(BOQItem(
            id=gen_id(), contract_id=c.id,
            si_no=item.si_no, description=item.description,
            unit=item.unit, quantity=item.quantity, rate=item.rate,
            amount=amt, payment_pct=item.payment_pct,
            payment_amount=pay_amt,
            work_status=item.work_status,
            completion_pct=item.completion_pct,
            is_parent=item.is_parent, parent_si=item.parent_si,
            notes=item.notes
        ))

    db.commit()
    return {"id": c.id, "contract_no": contract_no, "message": "Contract created"}


@router.get("/contracts/{cid}")
def get_contract(
    cid: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    c = db.query(Contract).filter(Contract.id == cid, Contract.tenant_id == current_user["tenant_id"]).first()
    if not c: raise HTTPException(404)
    s = db.query(Site).filter(Site.id == c.site_id).first() if c.site_id else None
    boq = db.query(BOQItem).filter(BOQItem.contract_id == cid).order_by(BOQItem.si_no).all()
    ra_bills = db.query(RABill).filter(RABill.contract_id == cid).order_by(RABill.ra_number).all()
    total_billed = sum(b.this_bill_amt for b in ra_bills)
    return {
        "id": c.id, "contract_no": c.contract_no,
        "site_name": s.name if s else None, "site_id": c.site_id,
        "party_name": c.party_name, "party_phone": c.party_phone,
        "party_gstin": c.party_gstin, "party_pan": c.party_pan,
        "contract_type": c.contract_type.value,
        "total_value": c.total_value, "retention_pct": c.retention_pct,
        "tds_rate": c.tds_rate, "gst_rate": c.gst_rate,
        "advance_paid": c.advance_paid,
        "start_date": str(c.start_date) if c.start_date else None,
        "end_date": str(c.end_date) if c.end_date else None,
        "description": c.description,
        "total_billed": round(total_billed, 2),
        "boq_items": [
            {
                "id": i.id, "si_no": i.si_no, "description": i.description,
                "unit": i.unit, "quantity": i.quantity, "rate": i.rate,
                "amount": i.amount, "payment_pct": i.payment_pct,
                "payment_amount": i.payment_amount,
                "work_status": i.work_status.value,
                "completion_pct": i.completion_pct,
                "is_parent": i.is_parent, "parent_si": i.parent_si,
                "notes": i.notes
            } for i in boq
        ],
        "ra_bills": [
            {
                "id": b.id, "bill_no": b.bill_no, "ra_number": b.ra_number,
                "bill_date": str(b.bill_date), "this_bill_amt": b.this_bill_amt,
                "net_payable": b.net_payable, "status": b.status.value
            } for b in ra_bills
        ]
    }


@router.post("/contracts/{cid}/update-work-status")
def update_work_status(
    cid: str,
    updates: List[WorkStatusUpdate],
    current_user: dict = Depends(require_perm("attendance")),
    db: Session = Depends(get_db)
):
    """Supervisor updates work done status per BOQ item"""
    c = db.query(Contract).filter(Contract.id == cid, Contract.tenant_id == current_user["tenant_id"]).first()
    if not c: raise HTTPException(404)
    for upd in updates:
        item = db.query(BOQItem).filter(BOQItem.id == upd.boq_item_id, BOQItem.contract_id == cid).first()
        if item:
            item.work_status = upd.work_status
            item.completion_pct = upd.completion_pct
            if upd.notes: item.notes = upd.notes
    db.commit()
    return {"message": f"{len(updates)} items updated"}


# ══════════════════════════════════════════
# RA BILLS — Generate
# ══════════════════════════════════════════
@router.post("/generate")
def generate_ra_bill(
    data: RABillIn,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    """Auto-generate RA Bill from work done status"""
    c = db.query(Contract).filter(
        Contract.id == data.contract_id,
        Contract.tenant_id == current_user["tenant_id"]
    ).first()
    if not c: raise HTTPException(404, "Contract not found")

    boq_items = db.query(BOQItem).filter(
        BOQItem.contract_id == c.id, BOQItem.is_parent == False
    ).all()

    # Calculate work done
    bill_items_data = []
    gross = 0
    for item in boq_items:
        item_amt = item.payment_amount or item.amount or 0
        if item.work_status == WorkStatus.done:
            this_amt = item_amt
        elif item.work_status == WorkStatus.partially_done:
            this_amt = round(item_amt * item.completion_pct / 100, 2)
        else:
            this_amt = 0

        # Previous billed for this item
        prev_billed_items = db.query(RABillItem).join(RABill).filter(
            RABill.contract_id == c.id,
            RABillItem.boq_item_id == item.id,
            RABill.status != BillStatus.draft
        ).all()
        prev_amt = sum(p.this_amount for p in prev_billed_items)
        net_this = max(0, this_amt - prev_amt)
        gross += net_this
        bill_items_data.append({
            "boq_item_id": item.id, "si_no": item.si_no,
            "description": item.description, "unit": item.unit,
            "quantity": item.quantity, "rate": item.rate,
            "total_amount": item_amt, "prev_amount": prev_amt,
            "this_amount": net_this,
            "work_status": item.work_status, "completion_pct": item.completion_pct
        })

    # Previous total billed
    prev_bills = db.query(RABill).filter(
        RABill.contract_id == c.id, RABill.status != BillStatus.draft
    ).all()
    prev_total = sum(b.this_bill_amt for b in prev_bills)
    ra_num = len(prev_bills) + 1

    # Deductions
    retention = round(gross * c.retention_pct / 100, 2)
    tds = round(gross * c.tds_rate / 100, 2)
    gst = round(gross * c.gst_rate / 100, 2) if c.contract_type == ContractType.labour_material else 0
    adv_recovery = data.advance_recovery or 0
    net = round(gross + gst - retention - tds - adv_recovery, 2)

    bill_no = f"VC-RA-{c.contract_no}-{ra_num:02d}"
    b = RABill(
        id=gen_id(), tenant_id=current_user["tenant_id"],
        bill_no=bill_no, ra_number=ra_num,
        contract_id=c.id, bill_date=data.bill_date,
        period_from=data.period_from, period_to=data.period_to,
        gross_amount=round(prev_total + gross, 2),
        prev_billed=prev_total,
        this_bill_amt=gross,
        retention_amt=retention, tds_amt=tds, gst_amt=gst,
        advance_recovery=adv_recovery,
        net_payable=net, balance_due=net,
        notes=data.notes, created_by=current_user["id"]
    )
    db.add(b); db.flush()

    for bi in bill_items_data:
        db.add(RABillItem(
            id=gen_id(), bill_id=b.id,
            boq_item_id=bi["boq_item_id"], si_no=bi["si_no"],
            description=bi["description"], unit=bi["unit"],
            quantity=bi["quantity"], rate=bi["rate"],
            total_amount=bi["total_amount"], prev_amount=bi["prev_amount"],
            this_amount=bi["this_amount"],
            work_status=bi["work_status"], completion_pct=bi["completion_pct"]
        ))

    db.commit()
    return {
        "id": b.id, "bill_no": bill_no, "ra_number": ra_num,
        "gross_amount": gross, "prev_billed": prev_total,
        "this_bill_amt": gross, "retention": retention,
        "tds": tds, "gst": gst, "net_payable": net,
        "items_count": len([i for i in bill_items_data if i["this_amount"] > 0])
    }


@router.get("/{bill_id}")
def get_ra_bill(
    bill_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    b = db.query(RABill).filter(
        RABill.id == bill_id, RABill.tenant_id == current_user["tenant_id"]
    ).first()
    if not b: raise HTTPException(404)
    c = b.contract
    s = db.query(Site).filter(Site.id == c.site_id).first() if c and c.site_id else None
    items = db.query(RABillItem).filter(RABillItem.bill_id == bill_id, RABillItem.this_amount > 0).all()
    return {
        "id": b.id, "bill_no": b.bill_no, "ra_number": b.ra_number,
        "bill_date": str(b.bill_date),
        "period_from": str(b.period_from) if b.period_from else None,
        "period_to": str(b.period_to) if b.period_to else None,
        "contract": {
            "no": c.contract_no, "party": c.party_name,
            "phone": c.party_phone, "gstin": c.party_gstin,
            "total_value": c.total_value, "type": c.contract_type.value
        },
        "site_name": s.name if s else None,
        "amounts": {
            "gross_cumulative": b.gross_amount,
            "prev_billed": b.prev_billed,
            "this_bill": b.this_bill_amt,
            "retention": b.retention_amt,
            "tds": b.tds_amt, "gst": b.gst_amt,
            "advance_recovery": b.advance_recovery,
            "net_payable": b.net_payable,
            "paid": b.paid_amount,
            "balance": b.balance_due
        },
        "status": b.status.value,
        "items": [
            {
                "si_no": i.si_no, "description": i.description,
                "unit": i.unit, "quantity": i.quantity, "rate": i.rate,
                "total_amount": i.total_amount, "prev_amount": i.prev_amount,
                "this_amount": i.this_amount, "work_status": i.work_status.value
            } for i in items
        ],
        "notes": b.notes
    }


@router.post("/{bill_id}/submit")
def submit_bill(
    bill_id: str,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    b = db.query(RABill).filter(RABill.id == bill_id, RABill.tenant_id == current_user["tenant_id"]).first()
    if not b: raise HTTPException(404)
    b.status = BillStatus.submitted
    db.commit()
    return {"message": "Bill submitted"}


@router.post("/{bill_id}/approve")
def approve_bill(
    bill_id: str,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    if current_user["role"] not in ["admin", "accounts"]:
        raise HTTPException(403)
    b = db.query(RABill).filter(RABill.id == bill_id, RABill.tenant_id == current_user["tenant_id"]).first()
    if not b: raise HTTPException(404)
    b.status = BillStatus.approved
    db.commit()
    return {"message": "Bill approved"}


@router.post("/{bill_id}/payment")
def record_payment(
    bill_id: str,
    amount: float,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db)
):
    b = db.query(RABill).filter(RABill.id == bill_id, RABill.tenant_id == current_user["tenant_id"]).first()
    if not b: raise HTTPException(404)
    b.paid_amount = (b.paid_amount or 0) + amount
    b.balance_due = b.net_payable - b.paid_amount
    if b.balance_due <= 0: b.status = BillStatus.paid
    db.commit()
    return {"message": "Payment recorded", "balance_due": b.balance_due}
