"""
Happy Contractor — Seed Script v2
Vishwanath Construction ka data Supabase mein load karta hai.

Run: cd backend && python seed.py
"""
import sys, os, uuid
from datetime import date, timedelta
from dotenv import load_dotenv

# .env load
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

db_url = os.getenv("DATABASE_URL", "")
if not db_url or "user:password" in db_url or db_url == "":
    print("❌ .env mein DATABASE_URL set nahi hai!")
    sys.exit(1)

print(f"🔗 DB: {db_url.split('@')[1] if '@' in db_url else db_url[:40]}...")

from app.db.session import SessionLocal, engine, Base
from app.models.models import (
    Tenant, User, Site, Worker, Vendor, Expense, Attendance,
    PlanEnum, RoleEnum, SiteStatusEnum, WorkerTypeEnum, ExpenseStatus, AttendanceStatus
)
from app.core.security import get_password_hash

try:
    Base.metadata.create_all(bind=engine)
    print("✅ Tables ready")
except Exception as e:
    print(f"❌ DB Error: {e}")
    sys.exit(1)

db = SessionLocal()
gen_id = lambda: str(uuid.uuid4())

# ── TENANT ──────────────────────────────────────────────────
t = db.query(Tenant).filter(Tenant.name.ilike("%vishwanath%")).first()
if t:
    TENANT_ID = t.id
    print(f"ℹ️  Tenant exists: {t.name}")
else:
    t = Tenant(
        id=gen_id(), name="Vishwanath Construction",
        gstin="10EUFPK3451L1ZQ",
        address="Danapur, Patna, Bihar - 801503",
        phone="9876543210", email="info@vishwanath.in",
        plan=PlanEnum.pro, is_active=True, financial_year="2026-27"
    )
    db.add(t); db.flush()
    TENANT_ID = t.id
    print(f"✅ Tenant created: {t.name}")

# ── USERS ────────────────────────────────────────────────────
USERS = [
    ("Admin",       "admin",      "admin123",  RoleEnum.admin,
     True,True,True,True,True,True,True,True),
    ("Anish Kumar", "anish",      "anish123",  RoleEnum.accounts,
     False,True,True,True,True,True,False,True),
    ("Supervisor",  "supervisor", "sup123",    RoleEnum.supervisor,
     False,True,True,True,False,True,False,False),
    ("HR Staff",    "hr",         "hr123",     RoleEnum.hr,
     False,True,True,False,True,True,False,True),
]
for name, uname, pw, role, s,w,a,e,sal,r,u,ed in USERS:
    if not db.query(User).filter(User.tenant_id==TENANT_ID, User.username==uname).first():
        db.add(User(
            id=gen_id(), tenant_id=TENANT_ID, name=name, username=uname,
            password_hash=get_password_hash(pw), role=role, is_active=True,
            perm_sites=s, perm_workers=w, perm_attendance=a, perm_expenses=e,
            perm_salary=sal, perm_reports=r, perm_users=u, perm_edit=ed
        ))
        print(f"  ✅ User: {uname} / {pw}")
db.flush()

# ── SITES ────────────────────────────────────────────────────
SITES = [
    ("XB112","Anand Kumar Residence - Danapur",   2500000,"active"),
    ("XB113","Raj Complex - Boring Road",          4500000,"active"),
    ("XB114","Sharma Villa - Bailey Road",         3200000,"active"),
    ("XB115","Gupta Commercial - Patna City",      8000000,"active"),
    ("XB116","Singh Residence - Kankarbagh",       1800000,"active"),
    ("XB117","Mishra Building - Rajendra Nagar",   3500000,"paused"),
    ("XB118","Yadav House - Phulwarisharif",       2100000,"active"),
    ("XB119","Commercial Plot - Danapur Cantt",    5500000,"planning"),
    ("XB120","Renovation Project - Khagaul",        800000,"completed"),
]
site_map = {}
for code, name, budget, status in SITES:
    s = db.query(Site).filter(Site.tenant_id==TENANT_ID, Site.project_code==code).first()
    if s:
        site_map[code] = s.id
    else:
        s = Site(id=gen_id(), tenant_id=TENANT_ID, project_code=code, name=name,
                 location="Patna/Danapur, Bihar", status=status,
                 budget=float(budget), start_date=date(2026,1,1))
        db.add(s); db.flush()
        site_map[code] = s.id
        print(f"  ✅ Site: [{code}] {name}")

# ── WORKERS ──────────────────────────────────────────────────
WORKERS = [
    ("Ramesh Kumar",    "Mason",         600, "XB112"),
    ("Suresh Paswan",   "Labour",        450, "XB112"),
    ("Dinesh Yadav",    "Labour",        450, "XB113"),
    ("Mahesh Singh",    "Mason",         600, "XB113"),
    ("Aakash Kumar",    "Plumber",       700, "XB114"),
    ("Vijay Sharma",    "Labour",        450, "XB114"),
    ("Santosh Gupta",   "Electrician",   750, "XB115"),
    ("Rakesh Bind",     "Labour",        450, "XB115"),
    ("Sanjay Kumar",    "Mason",         600, "XB116"),
    ("Mohan Lal",       "Labour",        450, "XB116"),
    ("Pappu Mistri",    "Mason",         600, "XB117"),
    ("Deepak Kumar",    "Painter",       550, "XB117"),
    ("Anupam Singh",    "Labour",        450, "XB118"),
    ("Raju Chamar",     "Labour",        450, "XB119"),
    ("Birendra Prasad", "Sub-Contractor",800, "XB120"),
]
worker_map = {}
for name, role, rate, sc in WORKERS:
    w = db.query(Worker).filter(Worker.tenant_id==TENANT_ID, Worker.name==name).first()
    if w:
        worker_map[name] = w.id
    else:
        w = Worker(id=gen_id(), tenant_id=TENANT_ID, name=name, role=role,
                   daily_rate=float(rate), worker_type=WorkerTypeEnum.labour,
                   default_site_id=site_map.get(sc), is_active=True)
        db.add(w); db.flush()
        worker_map[name] = w.id
        print(f"  ✅ Worker: {name} ({role}, Rs.{rate}/day)")

# ── VENDORS ──────────────────────────────────────────────────
VENDORS = [
    ("Sharma Steel & Cement",    "Material Supplier"),
    ("Patna Sand Traders",       "Material Supplier"),
    ("Bihar Brick Works",        "Material Supplier"),
    ("RK Transport Co.",         "Transport"),
    ("Mishra Labour Contractor", "Labour Contractor"),
    ("National Hardware",        "Material Supplier"),
    ("Danapur Plumbing Works",   "Sub-Contractor"),
    ("Kumar Electricals",        "Sub-Contractor"),
    ("Bihari Tiles & Marbles",   "Material Supplier"),
    ("Patna Crane Services",     "Equipment"),
]
vendor_map = {}
for vn, vt in VENDORS:
    v = db.query(Vendor).filter(Vendor.tenant_id==TENANT_ID, Vendor.name==vn).first()
    if v:
        vendor_map[vn] = v.id
    else:
        v = Vendor(id=gen_id(), tenant_id=TENANT_ID, name=vn, vendor_type=vt, is_active=True)
        db.add(v); db.flush()
        vendor_map[vn] = v.id
        print(f"  ✅ Vendor: {vn}")

# ── EXPENSES ─────────────────────────────────────────────────
EXPENSES = [
    ("Sharma Steel & Cement",    "XB112","Material Purchase",       "Steel TMT 8mm 2 ton",          125000,0,"HDFC CURRENT 9734"),
    ("Patna Sand Traders",       "XB112","Material Purchase",       "River Sand 50 CFT",              18500,0,"PhonePe"),
    ("Bihar Brick Works",        "XB113","Material Purchase",       "Bricks 5000 pcs",                22000,0,"Cash"),
    ("Mishra Labour Contractor", "XB112","Labour Charges",          "Weekly Labour Bill W1",          45000,0,"HDFC SAVING"),
    ("Mishra Labour Contractor", "XB113","Labour Charges",          "Weekly Labour Bill W1",          38000,0,"HDFC SAVING"),
    ("RK Transport Co.",         "XB114","Transport",               "Material delivery",               8500,0,"Cash"),
    ("National Hardware",        "XB114","Material Purchase",       "Cement 50 bags OPC",             26000,0,"PhonePe"),
    ("Kumar Electricals",        "XB115","Sub-Contractor Payments", "Electrical wiring Phase 1",      55000,0,"NEFT"),
    ("Danapur Plumbing Works",   "XB116","Sub-Contractor Payments", "Plumbing rough work",            42000,0,"HDFC CURRENT 9734"),
    ("Sharma Steel & Cement",    "XB116","Material Purchase",       "Steel TMT 10mm 1.5 ton",         98000,0,"HDFC CURRENT 9734"),
    ("Anand Kumar",              "XB112","Received",                "Client 1st installment",             0,300000,"HDFC SAVING"),
    ("Raj Constructions",        "XB113","Received",                "Client advance",                     0,250000,"NEFT"),
    ("Mishra Labour Contractor", "XB114","Labour Charges",          "Weekly Labour Bill W2",          52000,0,"HDFC SAVING"),
    ("National Hardware",        "XB115","Material Purchase",       "PVC pipes 4 inch 50 pcs",        14500,0,"Cash"),
    ("Bihar Brick Works",        "XB117","Material Purchase",       "AAC Blocks 600 pcs",             67000,0,"KOTAK SAVING"),
    ("Patna Crane Services",     "XB112","Equipment",               "Tower crane 3 days rent",        36000,0,"Cash"),
    ("Sharma Steel & Cement",    "XB118","Material Purchase",       "Steel TMT 12mm 3 ton",          145000,0,"HDFC CURRENT 9734"),
    ("Patna Sand Traders",       "XB119","Material Purchase",       "Sand gravel mix 80 CFT",         22000,0,"Cash"),
    ("Mishra Labour Contractor", "XB120","Labour Charges",          "Demolition site clearance",      28000,0,"Cash"),
    ("Bihari Tiles & Marbles",   "XB117","Material Purchase",       "Floor tiles 200 sqft",           38000,0,"PhonePe"),
    ("Kumar Electricals",        "XB118","Sub-Contractor Payments", "External wiring complete",       32000,0,"NEFT"),
    ("Sharma Villa",             "XB114","Received",                "Client 2nd installment",             0,180000,"HDFC SAVING"),
    ("Gupta Commercial",         "XB115","Received",                "Client advance 2nd payment",         0,450000,"NEFT"),
    ("Bihar Brick Works",        "XB112","Material Purchase",       "Bricks 8000 pcs extra",          35000,0,"Cash"),
    ("Danapur Plumbing Works",   "XB119","Sub-Contractor Payments", "Plumbing rough work",            25000,0,"Cash"),
    ("Mishra Labour Contractor", "XB116","Labour Charges",          "Weekly Labour Bill W2",          41000,0,"HDFC SAVING"),
    ("RK Transport Co.",         "XB120","Transport",               "Site clearing transport",         6500,0,"Cash"),
    ("National Hardware",        "XB113","Material Purchase",       "Sanitary fittings set",          18500,0,"PhonePe"),
    ("Singh Residence",          "XB116","Received",                "Client advance payment",             0,200000,"KOTAK SAVING"),
    ("Sharma Steel & Cement",    "XB119","Material Purchase",       "Steel rods assorted",            78000,0,"HDFC CURRENT 9734"),
]

base = date(2026,4,1)
exp_n = 0
for i,(vn,sc,cat,desc,db_,cr,mode) in enumerate(EXPENSES):
    e = Expense(
        id=gen_id(), tenant_id=TENANT_ID,
        date=base+timedelta(days=i*2),
        site_id=site_map.get(sc),
        vendor_id=vendor_map.get(vn), vendor_name=vn,
        payer_name="Anish Kumar", category=cat, description=desc,
        debit=float(db_), credit=float(cr),
        payment_mode=mode, status=ExpenseStatus.approved
    )
    db.add(e); exp_n+=1
print(f"  ✅ Expenses: {exp_n} entries")

# ── ATTENDANCE ───────────────────────────────────────────────
today = date.today()
first = date(today.year, today.month, 1)
statuses = [AttendanceStatus.P,AttendanceStatus.P,AttendanceStatus.P,
            AttendanceStatus.H,AttendanceStatus.A]
att_n = 0
for wname, wid in list(worker_map.items())[:12]:
    wo = db.query(Worker).filter(Worker.id==wid).first()
    for off in range(min(today.day-1, 22)):
        d = first+timedelta(days=off)
        if d.weekday()==6: continue
        if not db.query(Attendance).filter(
            Attendance.worker_id==wid, Attendance.date==d
        ).first():
            db.add(Attendance(
                id=gen_id(), tenant_id=TENANT_ID, worker_id=wid,
                site_id=wo.default_site_id if wo else None,
                date=d, status=statuses[off%len(statuses)]
            ))
            att_n+=1
print(f"  ✅ Attendance: {att_n} records")

db.commit()
db.close()

print(f"""
╔══════════════════════════════════════════╗
║         SEED COMPLETE! ✅                ║
╠══════════════════════════════════════════╣
║  Tenant  : Vishwanath Construction       ║
║  ID      : {TENANT_ID[:24]}...  ║
╠══════════════════════════════════════════╣
║  LOGIN CREDENTIALS                       ║
║  ─────────────────────────────────────  ║
║  Super Admin : jaisankar / jai@2024      ║
║  Admin       : admin / admin123          ║
║  Accounts    : anish / anish123          ║
║  Supervisor  : supervisor / sup123       ║
║  HR          : hr / hr123                ║
╠══════════════════════════════════════════╣
║  Ab server chalao:                       ║
║  uvicorn app.main:app --reload           ║
╚══════════════════════════════════════════╝
""")
