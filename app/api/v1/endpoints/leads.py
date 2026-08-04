from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date
from app.db.session import get_db
from app.core.deps import get_current_user, require_perm
from app.models.models import (
    Lead, LeadActivity, LeadStatus, LeadSource, User, Site,
    AgreementTemplate, Agreement, AgreementStatus,
    CustomerReport, CustomerReview
)
from pydantic import BaseModel
import uuid

router = APIRouter(prefix="/leads", tags=["CRM - Leads"])
gen_id = lambda: str(uuid.uuid4())


class LeadIn(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    source: LeadSource = LeadSource.other
    interested_in: Optional[str] = None
    budget: float = 0
    location_pref: Optional[str] = None
    notes: Optional[str] = None
    next_follow_up: Optional[date] = None
    assigned_to: Optional[str] = None

class LeadUpdateIn(BaseModel):
    status: Optional[LeadStatus] = None
    next_follow_up: Optional[date] = None
    assigned_to: Optional[str] = None
    lost_reason: Optional[str] = None
    converted_site_id: Optional[str] = None

class ActivityIn(BaseModel):
    activity_type: str = "note"
    note: str


@router.get("")
def list_leads(
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tid = current_user["tenant_id"]
    q = db.query(Lead).filter(Lead.tenant_id == tid)
    if status: q = q.filter(Lead.status == status)
    if assigned_to: q = q.filter(Lead.assigned_to == assigned_to)
    leads = q.order_by(Lead.next_follow_up.asc().nullslast(), Lead.created_at.desc()).all()
    result = []
    for l in leads:
        u = db.query(User).filter(User.id == l.assigned_to).first() if l.assigned_to else None
        last_activity = db.query(LeadActivity).filter(LeadActivity.lead_id == l.id).order_by(LeadActivity.created_at.desc()).first()
        result.append({
            "id": l.id, "name": l.name, "phone": l.phone, "email": l.email,
            "source": l.source.value, "status": l.status.value,
            "interested_in": l.interested_in, "budget": l.budget,
            "next_follow_up": str(l.next_follow_up) if l.next_follow_up else None,
            "assigned_to_name": u.name if u else None,
            "last_activity": last_activity.note[:80] if last_activity else None,
            "created_at": str(l.created_at.date()) if l.created_at else None,
        })
    return result

@router.post("")
def create_lead(data: LeadIn, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    tid = current_user["tenant_id"]
    l = Lead(
        id=gen_id(), tenant_id=tid, name=data.name, phone=data.phone, email=data.email,
        source=data.source, interested_in=data.interested_in, budget=data.budget,
        location_pref=data.location_pref, notes=data.notes, next_follow_up=data.next_follow_up,
        assigned_to=data.assigned_to or current_user["id"], created_by=current_user["id"]
    )
    db.add(l); db.commit()
    return {"id": l.id, "message": "Lead added"}

@router.get("/{lid}")
def get_lead(lid: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    l = db.query(Lead).filter(Lead.id == lid, Lead.tenant_id == current_user["tenant_id"]).first()
    if not l: raise HTTPException(404)
    u = db.query(User).filter(User.id == l.assigned_to).first() if l.assigned_to else None
    site = db.query(Site).filter(Site.id == l.converted_site_id).first() if l.converted_site_id else None
    activities = db.query(LeadActivity).filter(LeadActivity.lead_id == lid).order_by(LeadActivity.created_at.desc()).all()
    return {
        "id": l.id, "name": l.name, "phone": l.phone, "email": l.email,
        "source": l.source.value, "status": l.status.value,
        "interested_in": l.interested_in, "budget": l.budget, "location_pref": l.location_pref,
        "notes": l.notes, "next_follow_up": str(l.next_follow_up) if l.next_follow_up else None,
        "assigned_to": l.assigned_to, "assigned_to_name": u.name if u else None,
        "lost_reason": l.lost_reason, "converted_site_name": site.name if site else None,
        "created_at": str(l.created_at.date()) if l.created_at else None,
        "activities": [{"id": a.id, "activity_type": a.activity_type, "note": a.note, "created_at": str(a.created_at)} for a in activities]
    }

@router.patch("/{lid}")
def update_lead(lid: str, data: LeadUpdateIn, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    l = db.query(Lead).filter(Lead.id == lid, Lead.tenant_id == current_user["tenant_id"]).first()
    if not l: raise HTTPException(404)
    if data.status is not None: l.status = data.status
    if data.next_follow_up is not None: l.next_follow_up = data.next_follow_up
    if data.assigned_to is not None: l.assigned_to = data.assigned_to
    if data.lost_reason is not None: l.lost_reason = data.lost_reason
    if data.converted_site_id is not None: l.converted_site_id = data.converted_site_id
    db.commit()
    return {"message": "Lead updated"}

@router.post("/{lid}/activity")
def add_activity(lid: str, data: ActivityIn, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    l = db.query(Lead).filter(Lead.id == lid, Lead.tenant_id == current_user["tenant_id"]).first()
    if not l: raise HTTPException(404)
    a = LeadActivity(id=gen_id(), lead_id=lid, activity_type=data.activity_type, note=data.note, done_by=current_user["id"])
    db.add(a); db.commit()
    return {"message": "Activity logged"}

@router.get("/stats/summary")
def leads_summary(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = current_user["tenant_id"]
    leads = db.query(Lead).filter(Lead.tenant_id == tid).all()
    by_status = {}
    for l in leads:
        by_status[l.status.value] = by_status.get(l.status.value, 0) + 1
    won = [l for l in leads if l.status == LeadStatus.won]
    return {
        "total": len(leads), "by_status": by_status,
        "won_count": len(won), "won_value": sum(l.budget or 0 for l in won),
        "open_count": len([l for l in leads if l.status not in (LeadStatus.won, LeadStatus.lost)]),
    }


# ─────────────────────────────────────────────
# AGREEMENT TEMPLATES + AGREEMENTS
# ─────────────────────────────────────────────
class TemplateIn(BaseModel):
    name: str
    description: Optional[str] = None
    content: str

@router.get("/templates/list")
def list_templates(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    ts = db.query(AgreementTemplate).filter(AgreementTemplate.tenant_id == current_user["tenant_id"]).order_by(AgreementTemplate.created_at.desc()).all()
    return [{"id": t.id, "name": t.name, "description": t.description, "content": t.content} for t in ts]

@router.post("/templates/list")
def create_template(data: TemplateIn, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    t = AgreementTemplate(id=gen_id(), tenant_id=current_user["tenant_id"], name=data.name, description=data.description, content=data.content, created_by=current_user["id"])
    db.add(t); db.commit()
    return {"id": t.id, "message": "Template saved"}

@router.delete("/templates/{tid}")
def delete_template(tid: str, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    t = db.query(AgreementTemplate).filter(AgreementTemplate.id == tid, AgreementTemplate.tenant_id == current_user["tenant_id"]).first()
    if not t: raise HTTPException(404)
    db.delete(t); db.commit()
    return {"message": "Template deleted"}

class AgreementIn(BaseModel):
    lead_id: Optional[str] = None
    site_id: Optional[str] = None
    template_id: Optional[str] = None
    client_name: str
    title: Optional[str] = "Work Agreement"
    generated_content: str
    notes: Optional[str] = None

@router.get("/agreements/list")
def list_agreements(lead_id: Optional[str] = None, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Agreement).filter(Agreement.tenant_id == current_user["tenant_id"])
    if lead_id: q = q.filter(Agreement.lead_id == lead_id)
    ags = q.order_by(Agreement.created_at.desc()).all()
    return [{"id": a.id, "client_name": a.client_name, "title": a.title, "status": a.status.value, "sent_date": str(a.sent_date) if a.sent_date else None, "signed_date": str(a.signed_date) if a.signed_date else None, "created_at": str(a.created_at.date()) if a.created_at else None} for a in ags]

@router.post("/agreements/list")
def create_agreement(data: AgreementIn, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    a = Agreement(id=gen_id(), tenant_id=current_user["tenant_id"], lead_id=data.lead_id, site_id=data.site_id, template_id=data.template_id, client_name=data.client_name, title=data.title, generated_content=data.generated_content, notes=data.notes, created_by=current_user["id"])
    db.add(a); db.commit()
    return {"id": a.id, "message": "Agreement created"}

@router.get("/agreements/{aid}")
def get_agreement(aid: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    a = db.query(Agreement).filter(Agreement.id == aid, Agreement.tenant_id == current_user["tenant_id"]).first()
    if not a: raise HTTPException(404)
    return {"id": a.id, "client_name": a.client_name, "title": a.title, "generated_content": a.generated_content, "status": a.status.value, "sent_date": str(a.sent_date) if a.sent_date else None, "signed_date": str(a.signed_date) if a.signed_date else None, "notes": a.notes}

@router.post("/agreements/{aid}/status")
def update_agreement_status(aid: str, status: AgreementStatus, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    a = db.query(Agreement).filter(Agreement.id == aid, Agreement.tenant_id == current_user["tenant_id"]).first()
    if not a: raise HTTPException(404)
    a.status = status
    if status == AgreementStatus.sent: a.sent_date = date.today()
    if status == AgreementStatus.signed: a.signed_date = date.today()
    db.commit()
    return {"message": "Status updated"}


# ─────────────────────────────────────────────
# CUSTOMER PROGRESS REPORTS
# ─────────────────────────────────────────────
class ReportIn(BaseModel):
    lead_id: Optional[str] = None
    site_id: Optional[str] = None
    client_name: Optional[str] = None
    report_date: date
    progress_pct: float = 0
    work_summary: str
    sent_via: Optional[str] = None
    sent_to: Optional[str] = None

@router.get("/reports/list")
def list_reports(lead_id: Optional[str] = None, site_id: Optional[str] = None, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(CustomerReport).filter(CustomerReport.tenant_id == current_user["tenant_id"])
    if lead_id: q = q.filter(CustomerReport.lead_id == lead_id)
    if site_id: q = q.filter(CustomerReport.site_id == site_id)
    reports = q.order_by(CustomerReport.report_date.desc()).all()
    return [{"id": r.id, "client_name": r.client_name, "report_date": str(r.report_date), "progress_pct": r.progress_pct, "work_summary": r.work_summary, "sent_via": r.sent_via, "sent_to": r.sent_to, "sent_at": str(r.sent_at) if r.sent_at else None} for r in reports]

@router.post("/reports/list")
def create_report(data: ReportIn, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    r = CustomerReport(
        id=gen_id(), tenant_id=current_user["tenant_id"], lead_id=data.lead_id, site_id=data.site_id,
        client_name=data.client_name, report_date=data.report_date, progress_pct=data.progress_pct,
        work_summary=data.work_summary, sent_via=data.sent_via, sent_to=data.sent_to,
        sent_at=func.now() if data.sent_via else None, created_by=current_user["id"]
    )
    db.add(r); db.commit()
    return {"id": r.id, "message": "Report saved" + (" aur bhej diya" if data.sent_via else "")}


# ─────────────────────────────────────────────
# CUSTOMER REVIEWS / FEEDBACK
# ─────────────────────────────────────────────
class ReviewIn(BaseModel):
    lead_id: Optional[str] = None
    site_id: Optional[str] = None
    customer_name: str
    rating: int
    review_text: Optional[str] = None
    would_recommend: bool = True

@router.get("/reviews/list")
def list_reviews(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    revs = db.query(CustomerReview).filter(CustomerReview.tenant_id == current_user["tenant_id"]).order_by(CustomerReview.created_at.desc()).all()
    return [{"id": r.id, "customer_name": r.customer_name, "rating": r.rating, "review_text": r.review_text, "would_recommend": r.would_recommend, "created_at": str(r.created_at.date()) if r.created_at else None} for r in revs]

@router.post("/reviews/list")
def create_review(data: ReviewIn, current_user: dict = Depends(require_perm("expenses")), db: Session = Depends(get_db)):
    if not (1 <= data.rating <= 5): raise HTTPException(400, "Rating 1 se 5 ke beech honi chahiye")
    r = CustomerReview(id=gen_id(), tenant_id=current_user["tenant_id"], lead_id=data.lead_id, site_id=data.site_id, customer_name=data.customer_name, rating=data.rating, review_text=data.review_text, would_recommend=data.would_recommend, recorded_by=current_user["id"])
    db.add(r); db.commit()
    return {"id": r.id, "message": "Review saved"}

@router.get("/reviews/stats/summary")
def reviews_summary(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    revs = db.query(CustomerReview).filter(CustomerReview.tenant_id == current_user["tenant_id"]).all()
    if not revs: return {"count": 0, "avg_rating": 0, "recommend_pct": 0}
    avg = sum(r.rating for r in revs) / len(revs)
    rec_pct = sum(1 for r in revs if r.would_recommend) / len(revs) * 100
    return {"count": len(revs), "avg_rating": round(avg, 1), "recommend_pct": round(rec_pct, 1)}
