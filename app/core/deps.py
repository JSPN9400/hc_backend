from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import decode_token
from app.core.config import settings
from app.models.models import User, Tenant

bearer_scheme = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
):
    token = credentials.credentials
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    is_super = payload.get("is_super_admin", False)

    if is_super:
        # Virtual super admin user
        return {
            "id": "super_admin",
            "name": settings.SUPER_ADMIN_USERNAME,
            "role": "super_admin",
            "is_super_admin": True,
            "tenant_id": None,
            "perms": {
                "sites": True, "workers": True, "attendance": True,
                "expenses": True, "salary": True, "reports": True,
                "users": True, "edit": True
            }
        }

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Check tenant is active
    if user.tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
        if not tenant or not tenant.is_active:
            raise HTTPException(status_code=403, detail="Company account is inactive. Contact administrator.")

    return {
        "id": user.id,
        "name": user.name,
        "role": user.role.value,
        "is_super_admin": False,
        "tenant_id": user.tenant_id,
        "perms": {
            "sites": user.perm_sites,
            "workers": user.perm_workers,
            "attendance": user.perm_attendance,
            "expenses": user.perm_expenses,
            "salary": user.perm_salary,
            "reports": user.perm_reports,
            "users": user.perm_users,
            "edit": user.perm_edit,
        }
    }


def get_super_admin(current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_super_admin"):
        raise HTTPException(status_code=403, detail="Super Admin access required")
    return current_user


def get_tenant_user(current_user: dict = Depends(get_current_user)):
    if current_user.get("is_super_admin"):
        raise HTTPException(status_code=403, detail="Use a company account for this action")
    return current_user


def require_perm(perm: str):
    def checker(current_user: dict = Depends(get_current_user)):
        if current_user.get("is_super_admin"):
            return current_user
        if not current_user["perms"].get(perm):
            raise HTTPException(status_code=403, detail=f"Permission denied: {perm}")
        return current_user
    return checker


def get_tenant_id(current_user: dict = Depends(get_current_user)) -> str:
    tid = current_user.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=400, detail="No tenant context")
    return tid
