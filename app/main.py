from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

app = FastAPI(
    title="Happy Contractor API",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import routers AFTER app creation to avoid startup crash
from app.api.v1.endpoints import auth, tenants, sites, workers, attendance, expenses
from app.api.v1.endpoints.misc import (
    vendors_router, advances_router, leaves_router,
    users_router, dashboard_router, reports_router
)
from app.api.v1.endpoints.accounts import (
    bank_accounts_router, ledger_router, cashbook_router
)

PREFIX = "/api/v1"
app.include_router(auth.router,        prefix=PREFIX)
app.include_router(tenants.router,     prefix=PREFIX)
app.include_router(sites.router,       prefix=PREFIX)
app.include_router(workers.router,     prefix=PREFIX)
app.include_router(attendance.router,  prefix=PREFIX)
app.include_router(expenses.router,    prefix=PREFIX)
app.include_router(vendors_router,     prefix=PREFIX)
app.include_router(advances_router,    prefix=PREFIX)
app.include_router(leaves_router,      prefix=PREFIX)
app.include_router(users_router,       prefix=PREFIX)
app.include_router(dashboard_router,   prefix=PREFIX)
app.include_router(reports_router,     prefix=PREFIX)
app.include_router(bank_accounts_router, prefix=PREFIX)
app.include_router(ledger_router,      prefix=PREFIX)
app.include_router(cashbook_router,    prefix=PREFIX)

@app.on_event("startup")
async def startup():
    try:
        from app.db.session import engine, Base
        Base.metadata.create_all(bind=engine)
        print("✅ Database tables ready")
    except Exception as e:
        print(f"⚠️  DB warning (app still running): {e}")

@app.get("/")
def root():
    return {"message": "Happy Contractor API v2.0", "docs": "/api/docs"}

@app.get("/health")
def health():
    return {"status": "ok"}


# ── ONE-TIME SEED ENDPOINT ─────────────────────────────────
@app.get("/api/seed-now")
def run_seed():
    """One-time seed endpoint — delete after use"""
    try:
        import uuid
        from app.db.session import SessionLocal
        from app.models.models import (
            Tenant, User, Site, Worker, Vendor, Expense,
            PlanEnum, RoleEnum, WorkerTypeEnum, ExpenseStatus, AttendanceStatus
        )
        from app.core.security import get_password_hash
        from datetime import date, timedelta

        db = SessionLocal()
        gen_id = lambda: str(uuid.uuid4())

        # Tenant
        t = db.query(Tenant).filter(Tenant.name.ilike("%vishwanath%")).first()
        if not t:
            t = Tenant(
                id=gen_id(), name="Vishwanath Construction",
                address="Danapur, Patna, Bihar", phone="9876543210",
                plan=PlanEnum.pro, is_active=True, financial_year="2026-27"
            )
            db.add(t); db.flush()

        TENANT_ID = t.id

        # Users
        users = [
            ("Admin","admin","admin123",RoleEnum.admin,True,True,True,True,True,True,True,True),
            ("Anish Kumar","anish","anish123",RoleEnum.accounts,False,True,True,True,True,True,False,True),
            ("Supervisor","supervisor","sup123",RoleEnum.supervisor,False,True,True,True,False,True,False,False),
            ("HR Staff","hr","hr123",RoleEnum.hr,False,True,True,False,True,True,False,True),
        ]
        for name,uname,pw,role,s,w,a,e,sal,r,u,ed in users:
            if not db.query(User).filter(User.tenant_id==TENANT_ID,User.username==uname).first():
                db.add(User(
                    id=gen_id(),tenant_id=TENANT_ID,name=name,username=uname,
                    password_hash=get_password_hash(pw[:72]),role=role,is_active=True,
                    perm_sites=s,perm_workers=w,perm_attendance=a,perm_expenses=e,
                    perm_salary=sal,perm_reports=r,perm_users=u,perm_edit=ed
                ))

        # Sites
        sites_data = [
            ("XB112","Anand Kumar Residence - Danapur",2500000,"active"),
            ("XB113","Raj Complex - Boring Road",4500000,"active"),
            ("XB114","Sharma Villa - Bailey Road",3200000,"active"),
            ("XB115","Gupta Commercial - Patna City",8000000,"active"),
            ("XB116","Singh Residence - Kankarbagh",1800000,"active"),
        ]
        site_map = {}
        for code,name,budget,status in sites_data:
            s = db.query(Site).filter(Site.tenant_id==TENANT_ID,Site.project_code==code).first()
            if not s:
                s = Site(id=gen_id(),tenant_id=TENANT_ID,project_code=code,name=name,
                         location="Patna, Bihar",status=status,budget=float(budget))
                db.add(s); db.flush()
            site_map[code] = s.id

        # Workers
        workers_data = [
            ("Ramesh Kumar","Mason",600,"XB112"),
            ("Suresh Paswan","Labour",450,"XB112"),
            ("Dinesh Yadav","Labour",450,"XB113"),
            ("Santosh Gupta","Electrician",750,"XB115"),
            ("Sanjay Kumar","Mason",600,"XB116"),
        ]
        for name,role,rate,sc in workers_data:
            if not db.query(Worker).filter(Worker.tenant_id==TENANT_ID,Worker.name==name).first():
                db.add(Worker(id=gen_id(),tenant_id=TENANT_ID,name=name,role=role,
                             daily_rate=float(rate),worker_type=WorkerTypeEnum.labour,
                             default_site_id=site_map.get(sc),is_active=True))

        db.commit()
        db.close()
        return {
            "status": "✅ Seed complete!",
            "tenant": "Vishwanath Construction",
            "logins": {
                "super_admin": "jaisankar / jai@2024",
                "admin": "admin / admin123",
                "accounts": "anish / anish123"
            }
        }
    except Exception as e:
        return {"status": "❌ Error", "detail": str(e)}

# RA Bills router
from app.api.v1.endpoints.ra_bills import router as ra_bills_router
app.include_router(ra_bills_router, prefix=PREFIX)
