from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.db.session import get_db
from app.core.deps import get_super_admin
from app.core.security import get_password_hash
from app.models.models import Tenant, User, Site, Worker, Expense, RoleEnum
from app.schemas.schemas import TenantCreate, TenantUpdate, TenantOut, TenantStats
import uuid

router = APIRouter(prefix="/tenants", tags=["tenants"])
gen_id = lambda: str(uuid.uuid4())

@router.get("/", response_model=List[TenantStats])
def list_tenants(db: Session = Depends(get_db), _=Depends(get_super_admin)):
    tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    result = []
    for t in tenants:
        ts = TenantStats.model_validate(t)
        ts.site_count    = db.query(func.count(Site.id)).filter(Site.tenant_id == t.id).scalar()
        ts.worker_count  = db.query(func.count(Worker.id)).filter(Worker.tenant_id == t.id).scalar()
        ts.expense_count = db.query(func.count(Expense.id)).filter(Expense.tenant_id == t.id).scalar()
        ts.user_count    = db.query(func.count(User.id)).filter(User.tenant_id == t.id).scalar()
        result.append(ts)
    return result

@router.post("/", response_model=TenantOut)
def create_tenant(data: TenantCreate, db: Session = Depends(get_db), _=Depends(get_super_admin)):
    tenant = Tenant(
        id=gen_id(), name=data.name, address=data.address,
        phone=data.phone, email=data.email, plan=data.plan,
        financial_year=data.financial_year, license_note=data.license_note, is_active=True
    )
    db.add(tenant); db.flush()
    perms = dict(perm_sites=True,perm_workers=True,perm_attendance=True,perm_expenses=True,
                 perm_salary=True,perm_reports=True,perm_users=True,perm_edit=True)
    admin_user = User(
        id=gen_id(), tenant_id=tenant.id, name=data.admin_name,
        username=data.admin_username.lower().strip(),
        password_hash=get_password_hash(data.admin_password),
        role=RoleEnum.admin, is_active=True, **perms
    )
    db.add(admin_user); db.commit(); db.refresh(tenant)
    return tenant

@router.get("/{tenant_id}", response_model=TenantStats)
def get_tenant(tenant_id: str, db: Session = Depends(get_db), _=Depends(get_super_admin)):
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t: raise HTTPException(404)
    ts = TenantStats.model_validate(t)
    ts.site_count    = db.query(func.count(Site.id)).filter(Site.tenant_id == t.id).scalar()
    ts.worker_count  = db.query(func.count(Worker.id)).filter(Worker.tenant_id == t.id).scalar()
    ts.expense_count = db.query(func.count(Expense.id)).filter(Expense.tenant_id == t.id).scalar()
    ts.user_count    = db.query(func.count(User.id)).filter(User.tenant_id == t.id).scalar()
    return ts

@router.patch("/{tenant_id}", response_model=TenantOut)
def update_tenant(tenant_id: str, data: TenantUpdate, db: Session = Depends(get_db), _=Depends(get_super_admin)):
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t: raise HTTPException(404)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(t, k, v)
    db.commit(); db.refresh(t)
    return t

@router.patch("/{tenant_id}/deactivate")
def deactivate_tenant(tenant_id: str, db: Session = Depends(get_db), _=Depends(get_super_admin)):
    """Soft delete — company inactive, login blocked, data preserved"""
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t: raise HTTPException(404)
    t.is_active = False
    db.commit()
    return {"message": f"Company '{t.name}' deactivated. Data preserved."}

@router.patch("/{tenant_id}/activate")
def activate_tenant(tenant_id: str, db: Session = Depends(get_db), _=Depends(get_super_admin)):
    """Reactivate company"""
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t: raise HTTPException(404)
    t.is_active = True
    db.commit()
    return {"message": f"Company '{t.name}' activated."}

@router.delete("/{tenant_id}")
def delete_tenant(tenant_id: str, db: Session = Depends(get_db), _=Depends(get_super_admin)):
    """Hard delete — ALL data permanently removed"""
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t: raise HTTPException(404)
    name = t.name
    db.delete(t); db.commit()
    return {"message": f"Company '{name}' permanently deleted"}

@router.post("/{tenant_id}/reset-admin")
def reset_admin(tenant_id: str, username: str, password: str, db: Session = Depends(get_db), _=Depends(get_super_admin)):
    admin = db.query(User).filter(User.tenant_id == tenant_id, User.role == RoleEnum.admin).first()
    if not admin: raise HTTPException(404)
    admin.username = username.lower().strip()
    admin.password_hash = get_password_hash(password)
    db.commit()
    return {"message": "Admin credentials updated"}
