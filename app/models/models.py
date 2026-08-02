from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Date, DateTime,
    ForeignKey, Text, Enum, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
import uuid
from app.db.session import Base


def gen_uuid():
    return str(uuid.uuid4())


# ─────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────
class PlanEnum(str, enum.Enum):
    starter = "starter"       # 1 site, 10 workers
    pro = "pro"               # 10 sites, 100 workers
    enterprise = "enterprise" # unlimited

class RoleEnum(str, enum.Enum):
    super_admin = "super_admin"
    admin = "admin"
    accounts = "accounts"
    supervisor = "supervisor"
    hr = "hr"
    viewer = "viewer"

class SiteStatusEnum(str, enum.Enum):
    active = "active"
    completed = "completed"
    paused = "paused"
    planning = "planning"

class WorkerTypeEnum(str, enum.Enum):
    labour = "labour"       # daily wage site worker
    employee = "employee"   # office/fixed salary staff

class AttendanceStatus(str, enum.Enum):
    P = "P"   # Present
    H = "H"   # Half Day
    A = "A"   # Absent
    L = "L"   # Leave
    HD = "HD" # Holiday

class ExpenseStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    paid = "paid"
    rejected = "rejected"

class LeaveStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class LeaveType(str, enum.Enum):
    CL = "CL"  # Casual Leave
    SL = "SL"  # Sick Leave
    EL = "EL"  # Earned Leave
    LWP = "LWP" # Leave Without Pay

class AccountTypeEnum(str, enum.Enum):
    bank = "bank"
    cash = "cash"
    upi = "upi"


# ─────────────────────────────────────────────
# TENANT (Company)
# ─────────────────────────────────────────────
class Tenant(Base):
    __tablename__ = "tenants"

    id            = Column(String, primary_key=True, default=gen_uuid)
    name          = Column(String(200), nullable=False)
    gstin         = Column(String(20))
    address       = Column(String(500))
    phone         = Column(String(20))
    email         = Column(String(200))
    logo_url      = Column(String(500))
    plan          = Column(Enum(PlanEnum), default=PlanEnum.starter)
    is_active     = Column(Boolean, default=True)
    financial_year = Column(String(10), default="2026-27")
    license_note  = Column(String(500))
    created_at    = Column(DateTime, server_default=func.now())
    expires_at    = Column(DateTime)

    # Relationships
    users         = relationship("User", back_populates="tenant", cascade="all, delete")
    sites         = relationship("Site", back_populates="tenant", cascade="all, delete")
    workers       = relationship("Worker", back_populates="tenant", cascade="all, delete")
    vendors       = relationship("Vendor", back_populates="tenant", cascade="all, delete")
    expenses      = relationship("Expense", back_populates="tenant", cascade="all, delete")
    bank_accounts = relationship("BankAccount", back_populates="tenant", cascade="all, delete")


# ─────────────────────────────────────────────
# BANK ACCOUNT (Bank / Cash / UPI ledger)
# ─────────────────────────────────────────────
class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id              = Column(String, primary_key=True, default=gen_uuid)
    tenant_id       = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    account_name    = Column(String(200), nullable=False)   # e.g. "HDFC Current a/c", "Site Cash"
    account_type    = Column(Enum(AccountTypeEnum), default=AccountTypeEnum.bank)
    bank_name       = Column(String(150))
    account_number  = Column(String(50))
    ifsc_code       = Column(String(15))
    branch          = Column(String(150))
    opening_balance = Column(Float, default=0)
    opening_date    = Column(Date)
    is_active       = Column(Boolean, default=True)
    is_default_cash = Column(Boolean, default=False)  # the default "Cash" account for the tenant
    note            = Column(String(500))
    created_at      = Column(DateTime, server_default=func.now())

    tenant          = relationship("Tenant", back_populates="bank_accounts")
    expenses        = relationship("Expense", back_populates="account")

    __table_args__ = (
        Index("ix_bank_accounts_tenant", "tenant_id"),
    )


# ─────────────────────────────────────────────
# USER
# ─────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    name          = Column(String(200), nullable=False)
    username      = Column(String(100), nullable=False)
    email         = Column(String(200))
    password_hash = Column(String(500), nullable=False)
    role          = Column(Enum(RoleEnum), default=RoleEnum.viewer)
    is_active     = Column(Boolean, default=True)
    phone         = Column(String(20))

    # Permissions (fine-grained)
    perm_sites      = Column(Boolean, default=False)
    perm_workers    = Column(Boolean, default=False)
    perm_attendance = Column(Boolean, default=False)
    perm_expenses   = Column(Boolean, default=False)
    perm_salary     = Column(Boolean, default=False)
    perm_reports    = Column(Boolean, default=False)
    perm_users      = Column(Boolean, default=False)
    perm_edit       = Column(Boolean, default=False)

    # Supervisor -> assigned sites (many-to-many via string list for simplicity)
    assigned_site_ids = Column(Text, default="[]")  # JSON array of site IDs

    created_at    = Column(DateTime, server_default=func.now())

    tenant        = relationship("Tenant", back_populates="users")

    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_user_tenant_username"),
    )


# ─────────────────────────────────────────────
# SITE (Project)
# ─────────────────────────────────────────────
class Site(Base):
    __tablename__ = "sites"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    project_code  = Column(String(20))  # XB112 etc
    name          = Column(String(300), nullable=False)
    client_name   = Column(String(200))
    client_phone  = Column(String(20))
    location      = Column(String(500))
    address       = Column(Text)
    supervisor_id = Column(String, ForeignKey("users.id"), nullable=True)
    status        = Column(Enum(SiteStatusEnum), default=SiteStatusEnum.active)
    budget        = Column(Float, default=0)
    start_date    = Column(Date)
    end_date      = Column(Date)
    description   = Column(Text)
    is_deleted    = Column(Boolean, default=False)  # soft-delete: keep history for audit
    created_at    = Column(DateTime, server_default=func.now())
    updated_at    = Column(DateTime, server_default=func.now(), onupdate=func.now())

    tenant        = relationship("Tenant", back_populates="sites")
    supervisor    = relationship("User", foreign_keys=[supervisor_id])
    attendance    = relationship("Attendance", back_populates="site", cascade="all, delete")
    expenses      = relationship("Expense", back_populates="site", cascade="all, delete")

    __table_args__ = (
        Index("ix_sites_tenant", "tenant_id"),
    )


# ─────────────────────────────────────────────
# WORKER (Labour + Employee)
# ─────────────────────────────────────────────
class Worker(Base):
    __tablename__ = "workers"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    employee_code = Column(String(30))
    name          = Column(String(200), nullable=False)
    phone         = Column(String(20))
    aadhar_no     = Column(String(20))
    bank_account  = Column(String(30))
    bank_name     = Column(String(100))
    ifsc_code     = Column(String(15))
    address       = Column(Text)
    photo_url     = Column(String(500))

    worker_type   = Column(Enum(WorkerTypeEnum), default=WorkerTypeEnum.labour)
    role          = Column(String(100))  # Mason, Labour, Plumber, etc.

    # Labour fields
    daily_rate    = Column(Float, default=0)
    # Default site (can be overridden daily in attendance)
    default_site_id = Column(String, ForeignKey("sites.id"), nullable=True)

    # Employee fields (fixed salary staff)
    monthly_salary = Column(Float, default=0)
    designation   = Column(String(100))
    department    = Column(String(100))
    join_date     = Column(Date)
    cl_balance    = Column(Float, default=12)   # Casual Leave
    sl_balance    = Column(Float, default=12)   # Sick Leave
    el_balance    = Column(Float, default=15)   # Earned Leave

    previous_due  = Column(Float, default=0)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, server_default=func.now())
    updated_at    = Column(DateTime, server_default=func.now(), onupdate=func.now())

    tenant        = relationship("Tenant", back_populates="workers")
    default_site  = relationship("Site", foreign_keys=[default_site_id])
    attendance    = relationship("Attendance", back_populates="worker", cascade="all, delete")
    advances      = relationship("Advance", back_populates="worker", cascade="all, delete")
    leave_requests = relationship("LeaveRequest", back_populates="worker", cascade="all, delete")

    __table_args__ = (
        Index("ix_workers_tenant", "tenant_id"),
    )


# ─────────────────────────────────────────────
# ATTENDANCE
# ─────────────────────────────────────────────
class Attendance(Base):
    __tablename__ = "attendance"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, nullable=False)
    worker_id     = Column(String, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False)
    site_id       = Column(String, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    date          = Column(Date, nullable=False)
    status        = Column(Enum(AttendanceStatus), default=AttendanceStatus.A)
    overtime_hours = Column(Float, default=0)
    note          = Column(String(300))
    entered_by    = Column(String, ForeignKey("users.id"), nullable=True)
    reviewed_by   = Column(String, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime, server_default=func.now())
    updated_at    = Column(DateTime, server_default=func.now(), onupdate=func.now())

    worker        = relationship("Worker", back_populates="attendance")
    site          = relationship("Site", back_populates="attendance")
    entered_user  = relationship("User", foreign_keys=[entered_by])
    reviewed_user = relationship("User", foreign_keys=[reviewed_by])

    __table_args__ = (
        UniqueConstraint("worker_id", "date", name="uq_attendance_worker_date"),
        Index("ix_attendance_tenant_date", "tenant_id", "date"),
    )


# ─────────────────────────────────────────────
# VENDOR
# ─────────────────────────────────────────────
class Vendor(Base):
    __tablename__ = "vendors"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name          = Column(String(300), nullable=False)
    vendor_type   = Column(String(50))  # Labour Contractor, Material Supplier, etc.
    phone         = Column(String(20))
    email         = Column(String(200))
    gstin         = Column(String(20))
    address       = Column(Text)
    bank_account  = Column(String(30))
    bank_name     = Column(String(100))
    ifsc_code     = Column(String(15))
    upi_id        = Column(String(100))
    note          = Column(Text)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, server_default=func.now())

    tenant        = relationship("Tenant", back_populates="vendors")
    expenses      = relationship("Expense", back_populates="vendor")

    __table_args__ = (
        Index("ix_vendors_tenant", "tenant_id"),
    )


# ─────────────────────────────────────────────
# EXPENSE
# ─────────────────────────────────────────────
class Expense(Base):
    __tablename__ = "expenses"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    site_id       = Column(String, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    vendor_id     = Column(String, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True)
    account_id    = Column(String, ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True)

    date          = Column(Date, nullable=False)
    vendor_name   = Column(String(300))  # denormalized for quick display
    payer_name    = Column(String(200))
    category      = Column(String(100))
    sub_category  = Column(String(100))
    description   = Column(Text)

    debit         = Column(Float, default=0)   # Money going out
    credit        = Column(Float, default=0)   # Money coming in
    payment_mode  = Column(String(50))         # PhonePe, Cash, NEFT etc.

    status        = Column(Enum(ExpenseStatus), default=ExpenseStatus.pending)
    entered_by    = Column(String, ForeignKey("users.id"), nullable=True)
    approved_by   = Column(String, ForeignKey("users.id"), nullable=True)
    approved_at   = Column(DateTime)
    bill_no       = Column(String(100))
    bill_image_url = Column(String(500))
    is_deleted    = Column(Boolean, default=False)  # soft-delete: keep history for audit

    created_at    = Column(DateTime, server_default=func.now())
    updated_at    = Column(DateTime, server_default=func.now(), onupdate=func.now())

    tenant        = relationship("Tenant", back_populates="expenses")
    site          = relationship("Site", back_populates="expenses")
    vendor        = relationship("Vendor", back_populates="expenses")
    account       = relationship("BankAccount", back_populates="expenses")
    entered_user  = relationship("User", foreign_keys=[entered_by])
    approved_user = relationship("User", foreign_keys=[approved_by])

    __table_args__ = (
        Index("ix_expenses_tenant_date", "tenant_id", "date"),
        Index("ix_expenses_site", "site_id"),
        Index("ix_expenses_account", "account_id"),
    )


# ─────────────────────────────────────────────
# ADVANCE / SALARY PAYMENT
# ─────────────────────────────────────────────
class Advance(Base):
    __tablename__ = "advances"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, nullable=False)
    worker_id     = Column(String, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False)
    site_id       = Column(String, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    date          = Column(Date, nullable=False)
    advance_type  = Column(String(30))  # advance, salary, bonus, deduction
    amount        = Column(Float, nullable=False)
    payment_mode  = Column(String(50))
    note          = Column(String(500))
    entered_by    = Column(String, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime, server_default=func.now())

    worker        = relationship("Worker", back_populates="advances")
    site          = relationship("Site", foreign_keys=[site_id])
    entered_user  = relationship("User", foreign_keys=[entered_by])

    __table_args__ = (
        Index("ix_advances_worker", "worker_id"),
        Index("ix_advances_tenant", "tenant_id"),
    )


# ─────────────────────────────────────────────
# LEAVE REQUEST (Employee)
# ─────────────────────────────────────────────
class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, nullable=False)
    worker_id     = Column(String, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False)
    leave_type    = Column(Enum(LeaveType), nullable=False)
    from_date     = Column(Date, nullable=False)
    to_date       = Column(Date, nullable=False)
    days          = Column(Float, nullable=False)
    reason        = Column(Text)
    status        = Column(Enum(LeaveStatus), default=LeaveStatus.pending)
    applied_by    = Column(String, ForeignKey("users.id"), nullable=True)
    approved_by   = Column(String, ForeignKey("users.id"), nullable=True)
    approved_at   = Column(DateTime)
    reject_reason = Column(String(500))
    created_at    = Column(DateTime, server_default=func.now())

    worker        = relationship("Worker", back_populates="leave_requests")
    applied_user  = relationship("User", foreign_keys=[applied_by])
    approved_user = relationship("User", foreign_keys=[approved_by])


# ─────────────────────────────────────────────
# HOLIDAY CALENDAR
# ─────────────────────────────────────────────
class Holiday(Base):
    __tablename__ = "holidays"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, nullable=False)
    date          = Column(Date, nullable=False)
    name          = Column(String(200), nullable=False)
    is_optional   = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "date", name="uq_holiday_tenant_date"),
    )


# ─────────────────────────────────────────────
# WORKER SITE ASSIGNMENT (Multi-site support)
# ─────────────────────────────────────────────
class WorkerSiteAssignment(Base):
    __tablename__ = "worker_site_assignments"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id   = Column(String, nullable=False)
    worker_id   = Column(String, ForeignKey("workers.id", ondelete="CASCADE"))
    site_id     = Column(String, ForeignKey("sites.id", ondelete="CASCADE"))
    date_from   = Column(Date, nullable=False)
    date_to     = Column(Date, nullable=True)
    reason      = Column(String(300))
    assigned_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime, server_default=func.now())
    worker      = relationship("Worker", foreign_keys=[worker_id])
    site        = relationship("Site", foreign_keys=[site_id])
    __table_args__ = (Index("ix_wsa_tenant", "tenant_id"),)

class SupervisorSiteAssignment(Base):
    __tablename__ = "supervisor_site_assignments"
    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id     = Column(String, nullable=False)
    supervisor_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"))
    site_id       = Column(String, ForeignKey("sites.id", ondelete="CASCADE"))
    is_primary    = Column(Boolean, default=False)
    assigned_at   = Column(DateTime, server_default=func.now())
    supervisor    = relationship("User", foreign_keys=[supervisor_id])
    site          = relationship("Site", foreign_keys=[site_id])
    __table_args__ = (UniqueConstraint("supervisor_id", "site_id", name="uq_sup_site"),)

class ClientContractStatus(str, enum.Enum):
    draft="draft"; active="active"; on_hold="on_hold"; completed="completed"; terminated="terminated"

class ClientContractType(str, enum.Enum):
    labour_only="labour_only"; labour_material="labour_material"; item_rate="item_rate"; lump_sum="lump_sum"

class ClientContract(Base):
    __tablename__ = "client_contracts"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id       = Column(String, nullable=False)
    contract_no     = Column(String(30))
    site_id         = Column(String, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    client_name     = Column(String(300), nullable=False)
    client_phone    = Column(String(20))
    client_email    = Column(String(200))
    client_address  = Column(Text)
    client_gstin    = Column(String(20))
    client_pan      = Column(String(15))
    contract_type   = Column(Enum(ClientContractType), default=ClientContractType.labour_material)
    status          = Column(Enum(ClientContractStatus), default=ClientContractStatus.active)
    contract_value  = Column(Float, default=0)
    start_date      = Column(Date)
    end_date        = Column(Date)
    scope_of_work   = Column(Text)
    advance_pct     = Column(Float, default=10)
    advance_received= Column(Float, default=0)
    retention_pct   = Column(Float, default=5)
    retention_released = Column(Float, default=0)
    gst_rate        = Column(Float, default=12)
    tds_rate        = Column(Float, default=10)
    total_billed    = Column(Float, default=0)
    total_received  = Column(Float, default=0)
    balance_due     = Column(Float, default=0)
    notes           = Column(Text)
    created_by      = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime, server_default=func.now())
    updated_at      = Column(DateTime, server_default=func.now(), onupdate=func.now())
    site            = relationship("Site", foreign_keys=[site_id])
    milestones      = relationship("ContractMilestone", back_populates="contract", cascade="all, delete")
    client_ra_bills = relationship("ClientRABill", back_populates="contract", cascade="all, delete")
    __table_args__ = (Index("ix_client_contracts_tenant", "tenant_id"),)

class MilestoneStatus(str, enum.Enum):
    pending="pending"; in_progress="in_progress"; completed="completed"; billed="billed"; paid="paid"

class ContractMilestone(Base):
    __tablename__ = "contract_milestones"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id     = Column(String, ForeignKey("client_contracts.id", ondelete="CASCADE"))
    si_no           = Column(String(10))
    description     = Column(String(500), nullable=False)
    unit            = Column(String(20), default="LS")
    quantity        = Column(Float, default=0)
    rate            = Column(Float, default=0)
    amount          = Column(Float, default=0)
    payment_pct     = Column(Float, default=100)
    status          = Column(Enum(MilestoneStatus), default=MilestoneStatus.pending)
    completion_pct  = Column(Float, default=0)
    completed_date  = Column(Date)
    is_parent       = Column(Boolean, default=False)
    parent_si       = Column(String(10))
    photo_url       = Column(String(500))
    notes           = Column(String(500))
    updated_at      = Column(DateTime, server_default=func.now(), onupdate=func.now())
    contract        = relationship("ClientContract", back_populates="milestones")

class ClientRABillStatus(str, enum.Enum):
    draft="draft"; submitted="submitted"; approved="approved"; partial="partial"; paid="paid"; disputed="disputed"

class ClientRABill(Base):
    __tablename__ = "client_ra_bills"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id       = Column(String, nullable=False)
    bill_no         = Column(String(50), nullable=False)
    ra_number       = Column(Integer, default=1)
    contract_id     = Column(String, ForeignKey("client_contracts.id", ondelete="CASCADE"))
    bill_date       = Column(Date, nullable=False)
    due_date        = Column(Date)
    period_from     = Column(Date)
    period_to       = Column(Date)
    gross_amount    = Column(Float, default=0)
    prev_billed     = Column(Float, default=0)
    this_bill       = Column(Float, default=0)
    advance_recovery= Column(Float, default=0)
    retention_amt   = Column(Float, default=0)
    tds_amt         = Column(Float, default=0)
    gst_amt         = Column(Float, default=0)
    net_payable     = Column(Float, default=0)
    paid_amount     = Column(Float, default=0)
    balance_due     = Column(Float, default=0)
    status          = Column(Enum(ClientRABillStatus), default=ClientRABillStatus.draft)
    notes           = Column(Text)
    created_by      = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime, server_default=func.now())
    contract        = relationship("ClientContract", back_populates="client_ra_bills")
    bill_items      = relationship("ClientRABillItem", back_populates="bill", cascade="all, delete")
    payments        = relationship("ClientPayment", back_populates="bill", cascade="all, delete")
    __table_args__ = (Index("ix_client_ra_bills_tenant", "tenant_id"),)

class ClientRABillItem(Base):
    __tablename__ = "client_ra_bill_items"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    bill_id         = Column(String, ForeignKey("client_ra_bills.id", ondelete="CASCADE"))
    milestone_id    = Column(String, ForeignKey("contract_milestones.id", ondelete="SET NULL"), nullable=True)
    si_no           = Column(String(10))
    description     = Column(String(500))
    unit            = Column(String(20))
    quantity        = Column(Float, default=0)
    rate            = Column(Float, default=0)
    contract_amount = Column(Float, default=0)
    prev_amount     = Column(Float, default=0)
    this_amount     = Column(Float, default=0)
    completion_pct  = Column(Float, default=0)
    status          = Column(Enum(MilestoneStatus))
    bill            = relationship("ClientRABill", back_populates="bill_items")

class ClientPayment(Base):
    __tablename__ = "client_payments"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id       = Column(String, nullable=False)
    bill_id         = Column(String, ForeignKey("client_ra_bills.id", ondelete="CASCADE"))
    contract_id     = Column(String, ForeignKey("client_contracts.id", ondelete="SET NULL"), nullable=True)
    date            = Column(Date, nullable=False)
    amount          = Column(Float, nullable=False)
    tds_deducted    = Column(Float, default=0)
    net_received    = Column(Float, default=0)
    payment_mode    = Column(String(50))
    ref_no          = Column(String(100))
    is_advance      = Column(Boolean, default=False)
    notes           = Column(Text)
    created_at      = Column(DateTime, server_default=func.now())
    bill            = relationship("ClientRABill", back_populates="payments")
    __table_args__ = (Index("ix_client_payments_tenant", "tenant_id"),)

class DailySiteReport(Base):
    __tablename__ = "daily_site_reports"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id       = Column(String, nullable=False)
    site_id         = Column(String, ForeignKey("sites.id", ondelete="CASCADE"))
    date            = Column(Date, nullable=False)
    workers_present = Column(Integer, default=0)
    work_done       = Column(Text)
    material_used   = Column(Text)
    issues          = Column(Text)
    weather         = Column(String(50))
    photo_urls      = Column(Text, default="[]")
    submitted_by    = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime, server_default=func.now())
    site            = relationship("Site", foreign_keys=[site_id])
    __table_args__ = (
        UniqueConstraint("site_id", "date", name="uq_daily_report_site_date"),
        Index("ix_dsr_tenant", "tenant_id"),
    )

class MaterialTransaction(Base):
    __tablename__ = "material_transactions"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id       = Column(String, nullable=False)
    site_id         = Column(String, ForeignKey("sites.id", ondelete="CASCADE"))
    date            = Column(Date, nullable=False)
    item_name       = Column(String(200), nullable=False)
    category        = Column(String(100))
    unit            = Column(String(20))
    txn_type        = Column(String(10))
    quantity        = Column(Float, default=0)
    rate            = Column(Float, default=0)
    amount          = Column(Float, default=0)
    from_site_id    = Column(String, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    to_site_id      = Column(String, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    vendor_name     = Column(String(300))
    bill_no         = Column(String(100))
    notes           = Column(String(500))
    entered_by      = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime, server_default=func.now())
    site            = relationship("Site", foreign_keys=[site_id])
    __table_args__ = (Index("ix_material_tenant", "tenant_id"),)
