from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.session import engine, Base
from app.api.v1.endpoints import auth, tenants, sites, workers, attendance, expenses
from app.api.v1.endpoints.misc import (
    vendors_router, advances_router, leaves_router,
    users_router, dashboard_router, reports_router
)

try:
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables ready")
except Exception as e:
    print(f"⚠️  DB warning: {e}")

app = FastAPI(
    title="Happy Contractor API",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

origins = settings.cors_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False if origins == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
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

@app.get("/")
def root():
    return {"message": "Happy Contractor API v2.0", "docs": "/api/docs"}

@app.get("/health")
def health():
    return {"status": "ok"}
