from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from app.models.models import (
    PlanEnum, RoleEnum, SiteStatusEnum, WorkerTypeEnum,
    AttendanceStatus, ExpenseStatus, LeaveStatus, LeaveType
)


# ─── BASE ───
class TimestampMixin(BaseModel):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ─── TOKEN ───
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]

class LoginRequest(BaseModel):
    username: str
    password: str
    tenant_id: Optional[str] = None  # None = super admin login


# ─── TENANT ───
class TenantCreate(BaseModel):
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    plan: PlanEnum = PlanEnum.starter
    financial_year: str = "2026-27"
    license_note: Optional[str] = None
    admin_username: str = "admin"
    admin_password: str = "admin123"
    admin_name: str = "Admin"

class TenantUpdate(BaseModel):
    name: Optional[str] = None
    gstin: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    plan: Optional[PlanEnum] = None
    is_active: Optional[bool] = None
    financial_year: Optional[str] = None
    license_note: Optional[str] = None

class TenantOut(BaseModel):
    id: str
    name: str
    gstin: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    plan: PlanEnum
    is_active: bool
    financial_year: Optional[str] = None
    license_note: Optional[str] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class TenantStats(TenantOut):
    site_count: int = 0
    worker_count: int = 0
    expense_count: int = 0
    user_count: int = 0


# ─── USER ───
class UserCreate(BaseModel):
    name: str
    username: str
    password: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: RoleEnum = RoleEnum.viewer
    perm_sites: bool = False
    perm_workers: bool = False
    perm_attendance: bool = False
    perm_expenses: bool = False
    perm_salary: bool = False
    perm_reports: bool = True
    perm_users: bool = False
    perm_edit: bool = False

class UserUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[RoleEnum] = None
    is_active: Optional[bool] = None
    perm_sites: Optional[bool] = None
    perm_workers: Optional[bool] = None
    perm_attendance: Optional[bool] = None
    perm_expenses: Optional[bool] = None
    perm_salary: Optional[bool] = None
    perm_reports: Optional[bool] = None
    perm_users: Optional[bool] = None
    perm_edit: Optional[bool] = None

class UserOut(BaseModel):
    id: str
    name: str
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: RoleEnum
    is_active: bool
    perm_sites: bool = False
    perm_workers: bool = False
    perm_attendance: bool = False
    perm_expenses: bool = False
    perm_salary: bool = False
    perm_reports: bool = True
    perm_users: bool = False
    perm_edit: bool = False
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ─── SITE ───
class SiteCreate(BaseModel):
    project_code: Optional[str] = None
    name: str
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    location: Optional[str] = None
    address: Optional[str] = None
    supervisor_id: Optional[str] = None
    status: SiteStatusEnum = SiteStatusEnum.active
    budget: float = 0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    description: Optional[str] = None

class SiteUpdate(SiteCreate):
    name: Optional[str] = None

class SiteOut(BaseModel):
    id: str
    project_code: Optional[str] = None
    name: str
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    location: Optional[str] = None
    status: SiteStatusEnum
    budget: float = 0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    supervisor_id: Optional[str] = None
    supervisor_name: Optional[str] = None
    created_at: Optional[datetime] = None
    # Computed
    total_expense: float = 0
    total_receipt: float = 0
    worker_count: int = 0
    class Config:
        from_attributes = True


# ─── WORKER ───
class WorkerCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    aadhar_no: Optional[str] = None
    bank_account: Optional[str] = None
    bank_name: Optional[str] = None
    ifsc_code: Optional[str] = None
    address: Optional[str] = None
    worker_type: WorkerTypeEnum = WorkerTypeEnum.labour
    role: Optional[str] = None
    daily_rate: float = 0
    monthly_salary: float = 0
    designation: Optional[str] = None
    department: Optional[str] = None
    join_date: Optional[date] = None
    default_site_id: Optional[str] = None
    previous_due: float = 0
    employee_code: Optional[str] = None

class WorkerUpdate(WorkerCreate):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class WorkerOut(BaseModel):
    id: str
    employee_code: Optional[str] = None
    name: str
    phone: Optional[str] = None
    aadhar_no: Optional[str] = None
    worker_type: WorkerTypeEnum
    role: Optional[str] = None
    daily_rate: float = 0
    monthly_salary: float = 0
    designation: Optional[str] = None
    department: Optional[str] = None
    join_date: Optional[date] = None
    default_site_id: Optional[str] = None
    default_site_name: Optional[str] = None
    previous_due: float = 0
    is_active: bool
    cl_balance: float = 12
    sl_balance: float = 12
    el_balance: float = 15
    created_at: Optional[datetime] = None
    # computed
    this_month_days: int = 0
    this_month_gross: float = 0
    total_advance: float = 0
    class Config:
        from_attributes = True


# ─── ATTENDANCE ───
class AttendanceCreate(BaseModel):
    worker_id: str
    site_id: Optional[str] = None
    date: date
    status: AttendanceStatus
    overtime_hours: float = 0
    note: Optional[str] = None

class AttendanceBulk(BaseModel):
    date: date
    site_id: Optional[str] = None
    records: List[Dict[str, Any]]  # [{worker_id, status, overtime_hours}]

class AttendanceOut(BaseModel):
    id: str
    worker_id: str
    worker_name: str
    site_id: Optional[str] = None
    site_name: Optional[str] = None
    date: date
    status: AttendanceStatus
    overtime_hours: float = 0
    note: Optional[str] = None
    entered_by: Optional[str] = None
    class Config:
        from_attributes = True

class MonthlySummaryItem(BaseModel):
    worker_id: str
    worker_name: str
    worker_type: str
    role: Optional[str] = None
    daily_rate: float
    days_present: int
    half_days: int
    absent_days: int
    overtime_hours: float
    gross_earning: float
    advance_paid: float
    deductions: float
    net_payable: float
    previous_due: float


# ─── VENDOR ───
class VendorCreate(BaseModel):
    name: str
    vendor_type: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gstin: Optional[str] = None
    address: Optional[str] = None
    bank_account: Optional[str] = None
    bank_name: Optional[str] = None
    ifsc_code: Optional[str] = None
    upi_id: Optional[str] = None
    note: Optional[str] = None

class VendorUpdate(VendorCreate):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class VendorOut(BaseModel):
    id: str
    name: str
    vendor_type: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gstin: Optional[str] = None
    upi_id: Optional[str] = None
    is_active: bool
    total_paid: float = 0
    transaction_count: int = 0
    last_transaction_date: Optional[date] = None
    class Config:
        from_attributes = True


# ─── EXPENSE ───
class ExpenseCreate(BaseModel):
    site_id: Optional[str] = None
    vendor_id: Optional[str] = None
    date: date
    vendor_name: Optional[str] = None
    payer_name: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    description: Optional[str] = None
    debit: float = 0
    credit: float = 0
    payment_mode: Optional[str] = None
    bill_no: Optional[str] = None

class ExpenseUpdate(ExpenseCreate):
    status: Optional[ExpenseStatus] = None

class ExpenseOut(BaseModel):
    id: str
    site_id: Optional[str] = None
    site_name: Optional[str] = None
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    payer_name: Optional[str] = None
    date: date
    category: Optional[str] = None
    sub_category: Optional[str] = None
    description: Optional[str] = None
    debit: float = 0
    credit: float = 0
    payment_mode: Optional[str] = None
    status: ExpenseStatus
    bill_no: Optional[str] = None
    entered_by: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class ExpenseApprove(BaseModel):
    status: ExpenseStatus
    note: Optional[str] = None


# ─── ADVANCE ───
class AdvanceCreate(BaseModel):
    worker_id: str
    site_id: Optional[str] = None
    date: date
    advance_type: str  # advance, salary, bonus, deduction
    amount: float
    payment_mode: Optional[str] = None
    note: Optional[str] = None

class AdvanceOut(BaseModel):
    id: str
    worker_id: str
    worker_name: Optional[str] = None
    site_id: Optional[str] = None
    date: date
    advance_type: str
    amount: float
    payment_mode: Optional[str] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ─── LEAVE ───
class LeaveCreate(BaseModel):
    worker_id: str
    leave_type: LeaveType
    from_date: date
    to_date: date
    reason: Optional[str] = None

class LeaveApprove(BaseModel):
    status: LeaveStatus
    reject_reason: Optional[str] = None

class LeaveOut(BaseModel):
    id: str
    worker_id: str
    worker_name: Optional[str] = None
    leave_type: LeaveType
    from_date: date
    to_date: date
    days: float
    reason: Optional[str] = None
    status: LeaveStatus
    approved_by: Optional[str] = None
    reject_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ─── DASHBOARD ───
class DashboardStats(BaseModel):
    total_sites: int
    active_sites: int
    total_workers: int
    active_workers: int
    present_today: int
    half_day_today: int
    absent_today: int
    today_payroll: float
    fy_total_expense: float
    fy_total_receipt: float
    pending_expenses: int
    pending_leaves: int

class SitePL(BaseModel):
    site_id: str
    site_name: str
    total_expense: float
    total_receipt: float
    balance: float
    worker_count: int


# ─── IMPORT/EXPORT ───
class ImportResult(BaseModel):
    success: int
    failed: int
    errors: List[str] = []
