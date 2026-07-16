from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import date, timedelta
import uuid

from app.db.session import get_db
from app.core.deps import get_current_user, require_perm
from app.models.models import BankAccount, Expense, Vendor, AccountTypeEnum
from app.schemas.schemas import (
    BankAccountCreate, BankAccountUpdate, BankAccountOut,
    PartyLedgerOut, LedgerRow, BankStatementOut,
    CashBookOut, CashBookDay,
)

def gen_id(): return str(uuid.uuid4())


# ─────────────────────────────────────────────
# BANK ACCOUNTS (Bank / Cash / UPI)
# ─────────────────────────────────────────────
bank_accounts_router = APIRouter(prefix="/bank-accounts", tags=["bank-accounts"])


def _account_totals(db: Session, tenant_id: str, account_id: str):
    """
    Sum of cash out / cash in posted against this account.
    Vendor-linked rows have swapped polarity: a vendor "payment" is recorded as a
    credit on the vendor ledger (reduces what we owe) but is cash OUT of this account.
    """
    rows = db.query(Expense.debit, Expense.credit, Expense.vendor_id).filter(
        Expense.tenant_id == tenant_id, Expense.account_id == account_id
    ).all()
    cash_out = sum((r.credit if r.vendor_id else r.debit) or 0 for r in rows)
    cash_in = sum((r.debit if r.vendor_id else r.credit) or 0 for r in rows)
    return float(cash_out), float(cash_in)


def _enrich_account(a: BankAccount, db: Session) -> BankAccountOut:
    out = BankAccountOut.model_validate(a)
    total_out, total_in = _account_totals(db, a.tenant_id, a.id)
    out.total_in = round(total_in, 2)
    out.total_out = round(total_out, 2)
    out.current_balance = round((a.opening_balance or 0) + total_in - total_out, 2)
    return out


@bank_accounts_router.get("/", response_model=List[BankAccountOut])
def list_bank_accounts(
    include_inactive: bool = False,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tid = current_user["tenant_id"]
    q = db.query(BankAccount).filter(BankAccount.tenant_id == tid)
    if not include_inactive:
        q = q.filter(BankAccount.is_active == True)
    accounts = q.order_by(BankAccount.account_type, BankAccount.account_name).all()
    return [_enrich_account(a, db) for a in accounts]


@bank_accounts_router.post("/", response_model=BankAccountOut)
def create_bank_account(
    data: BankAccountCreate,
    current_user: dict = Depends(require_perm("expenses")),
    db: Session = Depends(get_db),
):
    tid = current_user["tenant_id"]
    a = BankAccount(id=gen_id(), tenant_id=tid, **data.model_dump())
    # First cash account becomes the default cash account automatically
    if a.account_type == AccountTypeEnum.cash:
        existing_cash = db.query(BankAccount).filter(
            BankAccount.tenant_id == tid, BankAccount.account_type == AccountTypeEnum.cash
        ).first()
        if not existing_cash:
            a.is_default_cash = True
    db.add(a)
    db.commit()
    db.refresh(a)
    return _enrich_account(a, db)


@bank_accounts_router.patch("/{account_id}", response_model=BankAccountOut)
def update_bank_account(
    account_id: str,
    data: BankAccountUpdate,
    current_user: dict = Depends(require_perm("edit")),
    db: Session = Depends(get_db),
):
    a = db.query(BankAccount).filter(BankAccount.id == account_id, BankAccount.tenant_id == current_user["tenant_id"]).first()
    if not a:
        raise HTTPException(404, "Account not found")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(a, k, v)
    db.commit()
    db.refresh(a)
    return _enrich_account(a, db)


@bank_accounts_router.delete("/{account_id}")
def delete_bank_account(
    account_id: str,
    current_user: dict = Depends(require_perm("edit")),
    db: Session = Depends(get_db),
):
    a = db.query(BankAccount).filter(BankAccount.id == account_id, BankAccount.tenant_id == current_user["tenant_id"]).first()
    if not a:
        raise HTTPException(404, "Account not found")
    linked = db.query(func.count(Expense.id)).filter(Expense.account_id == account_id).scalar()
    if linked:
        raise HTTPException(400, f"Cannot delete — {linked} transaction(s) linked to this account. Deactivate instead.")
    db.delete(a)
    db.commit()
    return {"message": "Deleted"}


@bank_accounts_router.get("/{account_id}/statement", response_model=BankStatementOut)
def account_statement(
    account_id: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bank/Cash account statement with running balance — printable."""
    tid = current_user["tenant_id"]
    a = db.query(BankAccount).filter(BankAccount.id == account_id, BankAccount.tenant_id == tid).first()
    if not a:
        raise HTTPException(404, "Account not found")

    q = db.query(Expense).filter(Expense.tenant_id == tid, Expense.account_id == account_id)
    if date_from:
        q = q.filter(Expense.date >= date_from)
    if date_to:
        q = q.filter(Expense.date <= date_to)
    txns = q.order_by(Expense.date, Expense.created_at).all()

    # Opening balance = account opening balance + everything posted before date_from
    balance = a.opening_balance or 0
    if date_from:
        pre_rows = db.query(Expense.debit, Expense.credit, Expense.vendor_id).filter(
            Expense.tenant_id == tid, Expense.account_id == account_id, Expense.date < date_from
        ).all()
        pre_out = sum((r.credit if r.vendor_id else r.debit) or 0 for r in pre_rows)
        pre_in = sum((r.debit if r.vendor_id else r.credit) or 0 for r in pre_rows)
        balance += pre_in - pre_out

    rows = []
    total_in, total_out = 0.0, 0.0
    for e in txns:
        # Cash-impact polarity: for vendor-linked rows, a "payment made" is entered
        # as a credit on the vendor ledger (reduces what we owe) but is money
        # LEAVING this bank/cash account — so the polarity is swapped here.
        # Non-vendor rows (general expense / receipt) use debit=out, credit=in directly.
        if e.vendor_id:
            cash_out, cash_in = e.credit or 0, e.debit or 0
        else:
            cash_out, cash_in = e.debit or 0, e.credit or 0

        balance += cash_in - cash_out
        total_in += cash_in
        total_out += cash_out
        rows.append(LedgerRow(
            date=e.date,
            description=e.vendor_name or e.description or e.category or "Transaction",
            ref=e.bill_no,
            debit=round(cash_out, 2),
            credit=round(cash_in, 2),
            balance=round(balance, 2),
            mode=e.payment_mode,
            status=e.status.value if e.status else None,
        ))

    return BankStatementOut(
        account=_enrich_account(a, db),
        rows=rows,
        total_in=round(total_in, 2),
        total_out=round(total_out, 2),
        closing_balance=round(balance, 2),
    )


# ─────────────────────────────────────────────
# PARTY LEDGER (Vendor — extendable to Client later)
# ─────────────────────────────────────────────
ledger_router = APIRouter(prefix="/ledger", tags=["ledger"])


@ledger_router.get("/vendor/{vendor_id}", response_model=PartyLedgerOut)
def vendor_ledger(
    vendor_id: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Vendor party ledger with running balance.
    Convention: debit = vendor supplied goods/services (we owe them),
                credit = we paid the vendor (reduces what we owe).
    Positive closing balance = amount WE OWE the vendor (payable/outstanding).
    """
    tid = current_user["tenant_id"]
    v = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.tenant_id == tid).first()
    if not v:
        raise HTTPException(404, "Vendor not found")

    q = db.query(Expense).filter(Expense.tenant_id == tid, Expense.vendor_id == vendor_id)
    if date_from:
        q = q.filter(Expense.date >= date_from)
    if date_to:
        q = q.filter(Expense.date <= date_to)
    txns = q.order_by(Expense.date, Expense.created_at).all()

    opening = 0.0
    if date_from:
        pre = db.query(
            func.coalesce(func.sum(Expense.debit), 0.0).label("d"),
            func.coalesce(func.sum(Expense.credit), 0.0).label("c"),
        ).filter(Expense.tenant_id == tid, Expense.vendor_id == vendor_id, Expense.date < date_from).first()
        opening = float(pre.d or 0) - float(pre.c or 0)

    balance = opening
    rows = []
    total_debit, total_credit = 0.0, 0.0
    for e in txns:
        balance += (e.debit or 0) - (e.credit or 0)
        total_debit += e.debit or 0
        total_credit += e.credit or 0
        rows.append(LedgerRow(
            date=e.date,
            description=e.description or e.category or "Transaction",
            ref=e.bill_no,
            debit=e.debit or 0,
            credit=e.credit or 0,
            balance=round(balance, 2),
            mode=e.payment_mode,
            status=e.status.value if e.status else None,
        ))

    return PartyLedgerOut(
        party_name=v.name,
        opening_balance=round(opening, 2),
        rows=rows,
        total_debit=round(total_debit, 2),
        total_credit=round(total_credit, 2),
        closing_balance=round(balance, 2),
    )


@ledger_router.get("/payables")
def outstanding_payables(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kise kitna dena hai — outstanding balance per vendor, sorted highest-due first."""
    tid = current_user["tenant_id"]
    vendors = db.query(Vendor).filter(Vendor.tenant_id == tid, Vendor.is_active == True).all()
    result = []
    for v in vendors:
        totals = db.query(
            func.coalesce(func.sum(Expense.debit), 0.0).label("d"),
            func.coalesce(func.sum(Expense.credit), 0.0).label("c"),
            func.max(Expense.date).label("last"),
        ).filter(Expense.tenant_id == tid, Expense.vendor_id == v.id).first()
        due = float(totals.d or 0) - float(totals.c or 0)
        if abs(due) > 0.01:
            result.append({
                "vendor_id": v.id,
                "vendor_name": v.name,
                "vendor_type": v.vendor_type,
                "phone": v.phone,
                "outstanding": round(due, 2),
                "last_transaction_date": str(totals.last) if totals.last else None,
            })
    result.sort(key=lambda x: x["outstanding"], reverse=True)
    return {
        "total_payable": round(sum(r["outstanding"] for r in result if r["outstanding"] > 0), 2),
        "vendors": result,
    }


# ─────────────────────────────────────────────
# CASH BOOK
# ─────────────────────────────────────────────
cashbook_router = APIRouter(prefix="/cashbook", tags=["cashbook"])


@cashbook_router.get("/", response_model=CashBookOut)
def cash_book(
    date_from: date = Query(...),
    date_to: date = Query(...),
    account_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Daily cash in/out. If account_id not given, uses the tenant's default cash account(s)."""
    tid = current_user["tenant_id"]

    if account_id:
        cash_account_ids = [account_id]
        opening_total = db.query(BankAccount).filter(BankAccount.id == account_id, BankAccount.tenant_id == tid).first()
        opening_total = opening_total.opening_balance if opening_total else 0
    else:
        cash_accounts = db.query(BankAccount).filter(
            BankAccount.tenant_id == tid, BankAccount.account_type == AccountTypeEnum.cash
        ).all()
        cash_account_ids = [a.id for a in cash_accounts]
        opening_total = sum(a.opening_balance or 0 for a in cash_accounts)

    if not cash_account_ids:
        return CashBookOut(date_from=date_from, date_to=date_to, opening_balance=0, total_in=0, total_out=0, closing_balance=0, days=[])

    # Opening balance as of date_from = account opening + all txns before date_from
    pre_rows = db.query(Expense.debit, Expense.credit, Expense.vendor_id).filter(
        Expense.tenant_id == tid, Expense.account_id.in_(cash_account_ids), Expense.date < date_from
    ).all()
    pre_out = sum((r.credit if r.vendor_id else r.debit) or 0 for r in pre_rows)
    pre_in = sum((r.debit if r.vendor_id else r.credit) or 0 for r in pre_rows)
    running_balance = opening_total + pre_in - pre_out
    opening_for_range = running_balance

    txns = db.query(Expense).filter(
        Expense.tenant_id == tid,
        Expense.account_id.in_(cash_account_ids),
        Expense.date >= date_from, Expense.date <= date_to,
    ).order_by(Expense.date, Expense.created_at).all()

    by_day = {}
    d = date_from
    while d <= date_to:
        by_day[d] = {"in": 0.0, "out": 0.0, "rows": []}
        d += timedelta(days=1)

    for e in txns:
        cash_out, cash_in = (e.credit or 0, e.debit or 0) if e.vendor_id else (e.debit or 0, e.credit or 0)
        by_day[e.date]["in"] += cash_in
        by_day[e.date]["out"] += cash_out
        by_day[e.date]["rows"].append(LedgerRow(
            date=e.date,
            description=e.vendor_name or e.description or e.category or "Transaction",
            ref=e.bill_no,
            debit=round(cash_out, 2),
            credit=round(cash_in, 2),
            balance=0,  # set below
            mode=e.payment_mode,
            status=e.status.value if e.status else None,
        ))

    days = []
    total_in, total_out = 0.0, 0.0
    for d in sorted(by_day.keys()):
        info = by_day[d]
        day_open = running_balance
        running_balance += info["in"] - info["out"]
        bal = day_open
        for r in info["rows"]:
            bal += r.credit - r.debit
            r.balance = round(bal, 2)
        total_in += info["in"]
        total_out += info["out"]
        days.append(CashBookDay(
            date=d, opening_balance=round(day_open, 2),
            cash_in=round(info["in"], 2), cash_out=round(info["out"], 2),
            closing_balance=round(running_balance, 2), rows=info["rows"],
        ))

    return CashBookOut(
        date_from=date_from, date_to=date_to,
        opening_balance=round(opening_for_range, 2),
        total_in=round(total_in, 2), total_out=round(total_out, 2),
        closing_balance=round(running_balance, 2),
        days=days,
    )
