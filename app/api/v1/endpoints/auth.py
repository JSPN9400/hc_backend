from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.config import settings
from app.core.deps import get_current_user
from app.models.models import User, Tenant
from app.schemas.schemas import LoginRequest, Token
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/companies")
def list_companies(db: Session = Depends(get_db)):
    """Public endpoint — returns active companies for login screen"""
    tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
    return [
        {"id": t.id, "name": t.name, "address": t.address, "plan": t.plan.value}
        for t in tenants
    ]


@router.post("/login", response_model=Token)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    username = req.username.strip().lower()

    # Super admin check
    if username == settings.SUPER_ADMIN_USERNAME.lower() and req.password == settings.SUPER_ADMIN_PASSWORD:
        token = create_access_token({"sub": "super_admin", "is_super_admin": True})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": "super_admin",
                "name": "Jaisankar",
                "role": "super_admin",
                "is_super_admin": True,
                "tenant_id": None,
                "perms": {k: True for k in ["sites","workers","attendance","expenses","salary","reports","users","edit"]}
            }
        }

    # Company user
    if not req.tenant_id:
        raise HTTPException(400, "Company ID required for company login")

    tenant = db.query(Tenant).filter(Tenant.id == req.tenant_id, Tenant.is_active == True).first()
    if not tenant:
        raise HTTPException(403, "Company not found or inactive")

    user = db.query(User).filter(
        User.tenant_id == req.tenant_id,
        User.username == username,
        User.is_active == True
    ).first()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Galat username ya password")

    token = create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "is_super_admin": False})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "role": user.role.value,
            "is_super_admin": False,
            "tenant_id": user.tenant_id,
            "tenant_name": tenant.name,
            "perms": {
                "sites": user.perm_sites, "workers": user.perm_workers,
                "attendance": user.perm_attendance, "expenses": user.perm_expenses,
                "salary": user.perm_salary, "reports": user.perm_reports,
                "users": user.perm_users, "edit": user.perm_edit,
            }
        }
    }


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    return current_user


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.get("is_super_admin"):
        if req.old_password != settings.SUPER_ADMIN_PASSWORD:
            raise HTTPException(400, "Current password galat hai")
        # Note: super admin password is in env, so just return success hint
        return {"message": "Update .env file to change super admin password"}

    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user or not verify_password(req.old_password, user.password_hash):
        raise HTTPException(400, "Current password galat hai")
    if len(req.new_password) < 4:
        raise HTTPException(400, "Password 4+ characters hona chahiye")

    user.password_hash = get_password_hash(req.new_password)
    db.commit()
    return {"message": "Password updated"}
