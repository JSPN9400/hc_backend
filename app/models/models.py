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
