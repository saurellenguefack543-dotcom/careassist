"""CareAssist — API FastAPI.

Ne manquez plus jamais un rendez-vous. Votre réceptionniste IA 24/7 pour les professionnels de santé.
"""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from datetime import date

import hmac

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator

from . import booking, config, db, scheduler, security, seed
from .emergency import detect
from .engine import process_message, resolve_practice
from .llm import provider_name
from .prompts import build_system_prompt
from .specialties import public_specialties
from .payments import router as payments_router
from .voice import router as voice_router
from .espace import router as espace_router
from .telephony import router as telephony_router, status_router as voip_status_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if config.env("SEED_DEMO", "1") != "0" and db.is_empty():
        seed.seed()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(
    title=f"{config.PRODUCT_NAME} API",
    description=config.SLOGAN + " — Prise de rendez-vous, FAQ, triage des urgences, webhooks Twilio & Vapi.",
    version="2.0.0",
    docs_url=None if config.env("DISABLE_DOCS") == "1" else "/docs",
    contact={"name": config.PRODUCT_NAME, "url": config.SITE_URL, "email": config.CONTACT_EMAIL},
    lifespan=lifespan,
)
# CORS : seul le widget public (chat, créneaux) peut être appelé depuis d'autres origines ; jamais avec cookies.
app.add_middleware(CORSMiddleware, allow_origins=[o for o in config.env("CORS_ORIGINS", "").split(",") if o] or ["*"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"], allow_credentials=False)
app.middleware("http")(security.headers_middleware)
app.include_router(voice_router)
app.include_router(telephony_router)
app.include_router(voip_status_router)
app.include_router(payments_router)
app.include_router(espace_router)


# ------------------------------------------------------------------ modèles

class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None
    practice: str | None = Field(None, description="slug, id ou spécialité du cabinet (ex. dentiste, psychologue)")
    channel: str = "web"


class BookIn(BaseModel):
    slot_id: int
    patient_name: str = Field(..., min_length=2, max_length=120)
    phone: str = Field(..., min_length=6, max_length=30)
    reason: str | None = None
    urgent: bool = False


PHONE_OK = re.compile(r"^\+?[0-9 .\-()]{9,20}$")


class LeadIn(BaseModel):
    practice_name: str = Field(..., min_length=2, max_length=160)
    email: EmailStr
    phone: str
    specialty: str | None = None
    message: str | None = Field(None, max_length=2000)
    source: str = "landing"

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        v = v.strip()
        if not PHONE_OK.match(v) or sum(c.isdigit() for c in v) < 9:
            raise ValueError("Numéro de téléphone invalide")
        return v


def admin_guard(request: Request):
    """Super-admin : protégé PAR DÉFAUT. Sans ADMIN_TOKEN, l'accès n'est ouvert que si ADMIN_OPEN=1 (développement local)."""
    token = config.env("ADMIN_TOKEN")
    if not token:
        if config.env("ADMIN_OPEN", "0") == "1":
            return
        raise HTTPException(401, "ADMIN_TOKEN non configuré : accès super-admin désactivé")
    sent = request.headers.get("X-Admin-Token") or request.query_params.get("token") or ""
    if not hmac.compare_digest(sent.encode(), token.encode()):
        raise HTTPException(401, "Token admin requis")


def demo_practice_only(practice_id: int | None) -> None:
    """L'API publique de réservation/annulation sans authentification est réservée aux cabinets de DÉMO.
    Les cabinets réels passent par l'assistante (chat/téléphone) ou l'espace cabinet authentifié."""
    p = db.get_practice(practice_id) if practice_id else None
    if not p or not p.get("is_demo"):
        raise HTTPException(403, "Réservé aux cabinets de démonstration")


# ------------------------------------------------------------------ API publique

@app.get("/health")
def health():
    return {"status": "ok", "product": config.PRODUCT_NAME, "slogan": config.SLOGAN, "llm": provider_name()}


@app.get("/api/specialties")
def specialties():
    return {"specialties": public_specialties(), "practices": db.list_practices(), "price_eur_month": config.PRICE_EUR_MONTH}


@app.post("/api/chat", dependencies=[Depends(security.limiter("chat"))])
def chat(body: ChatIn):
    return process_message(body.message, session_id=body.session_id, practice=body.practice, channel=body.channel)


@app.get("/api/slots")
def slots(practice: str | None = None, day: date | None = None, period: str | None = None, urgent: bool = False, limit: int = 10):
    p = resolve_practice(practice)
    return {"practice": p["slug"], "slots": booking.find_slots(day=day, period=period, emergency=urgent, practice_id=p["id"], limit=limit)}


@app.post("/api/appointments", status_code=201, dependencies=[Depends(security.limiter("chat"))])
def create_appointment(body: BookIn):
    slot = booking.get_slot(body.slot_id)
    demo_practice_only(slot["practice_id"] if slot else None)
    try:
        return booking.book(body.slot_id, body.patient_name, body.phone, body.reason or "", body.urgent)
    except booking.BookingError as e:
        raise HTTPException(409, str(e))


@app.delete("/api/appointments/{appointment_id}")
def cancel_appointment(appointment_id: int):
    with db.get_conn() as conn:
        r = conn.execute("SELECT practice_id FROM appointments WHERE id=?", (appointment_id,)).fetchone()
    demo_practice_only(r[0] if r else None)
    try:
        return booking.cancel(appointment_id)
    except booking.BookingError as e:
        raise HTTPException(404, str(e))


@app.post("/api/emergency/check")
def emergency_check(body: ChatIn):
    p = resolve_practice(body.practice)
    return {"practice": p["slug"], **detect(body.message, p["specialty"]).to_dict()}


@app.post("/api/leads", status_code=201, dependencies=[Depends(security.limiter("leads"))])
def create_lead(body: LeadIn):
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO leads(practice_name, email, phone, specialty, message, source, created_at) VALUES (?,?,?,?,?,?,?)",
            (body.practice_name.strip(), body.email, body.phone, body.specialty, body.message, body.source, db.now_iso()),
        )
    return {"ok": True, "id": cur.lastrowid, "message": "Merci ! Nous vous recontactons sous 24 h ouvrées pour activer votre essai."}


@app.get("/api/prompt")
def system_prompt(practice: str | None = None):
    """Prompt système complet (base + surcouche spécialité) — utile pour Vapi/Retell/autre."""
    p = resolve_practice(practice)
    return {"practice": p["slug"], "prompt": build_system_prompt(p)}


# ------------------------------------------------------------------ API admin

@app.get("/api/admin/stats", dependencies=[Depends(admin_guard)])
def admin_stats():
    with db.get_conn() as conn:
        q = lambda sql: conn.execute(sql).fetchone()[0]
        return {
            "conversations": q("SELECT COUNT(*) FROM conversations"),
            "messages": q("SELECT COUNT(*) FROM messages"),
            "appointments": q("SELECT COUNT(*) FROM appointments WHERE status IN ('confirmed','reminded','honored')"),
            "cancelled": q("SELECT COUNT(*) FROM appointments WHERE status='cancelled'"),
            "emergencies": q("SELECT COUNT(*) FROM emergencies"),
            "vital": q("SELECT COUNT(*) FROM emergencies WHERE level='vital'"),
            "leads": q("SELECT COUNT(*) FROM leads"),
            "subscriptions": q("SELECT COUNT(*) FROM subscriptions"),
            "subscriptions_active": q("SELECT COUNT(*) FROM subscriptions WHERE status='active'"),
            "llm": provider_name(),
        }


@app.get("/api/admin/conversations", dependencies=[Depends(admin_guard)])
def admin_conversations(limit: int = 100):
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            "SELECT c.id, c.session_id, c.channel, c.emergency_level, c.created_at, c.updated_at, pr.name AS practice, "
            "pr.specialty, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS n_messages, "
            "(SELECT content FROM messages m WHERE m.conversation_id=c.id AND role='user' ORDER BY id LIMIT 1) AS first_message "
            "FROM conversations c LEFT JOIN practices pr ON pr.id=c.practice_id ORDER BY c.updated_at DESC LIMIT ?", (limit,)))


@app.get("/api/admin/conversations/{conv_id}", dependencies=[Depends(admin_guard)])
def admin_conversation(conv_id: int):
    with db.get_conn() as conn:
        c = conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
        if not c:
            raise HTTPException(404, "Conversation introuvable")
        msgs = db.rows(conn.execute("SELECT role, content, intent, engine, created_at FROM messages WHERE conversation_id=? ORDER BY id", (conv_id,)))
    return {**dict(c), "messages": msgs}


@app.get("/api/admin/appointments", dependencies=[Depends(admin_guard)])
def admin_appointments(limit: int = 200):
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            "SELECT a.*, s.start, p.name AS practitioner, pr.name AS practice, pr.specialty FROM appointments a "
            "JOIN slots s ON s.id=a.slot_id JOIN practitioners p ON p.id=s.practitioner_id "
            "LEFT JOIN practices pr ON pr.id=p.practice_id ORDER BY a.id DESC LIMIT ?", (limit,)))


@app.get("/api/admin/leads", dependencies=[Depends(admin_guard)])
def admin_leads():
    with db.get_conn() as conn:
        return db.rows(conn.execute("SELECT * FROM leads ORDER BY id DESC"))


@app.get("/api/admin/subscriptions", dependencies=[Depends(admin_guard)])
def admin_subscriptions():
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            "SELECT id, reference, region, currency, amount, provider, mode, status, practice_name, email, phone, specialty, "
            "last_event, created_at, activated_at FROM subscriptions ORDER BY id DESC"))


@app.get("/api/admin/emergencies", dependencies=[Depends(admin_guard)])
def admin_emergencies():
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            "SELECT e.*, pr.name AS practice, pr.specialty FROM emergencies e LEFT JOIN practices pr ON pr.id=e.practice_id "
            "ORDER BY e.id DESC"))


# ------------------------------------------------------------------ pages statiques

@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(config.STATIC_DIR / "admin.html")


@app.get("/espace", include_in_schema=False)
def espace_page():
    return FileResponse(config.STATIC_DIR / "espace.html")


@app.get("/api/admin/practices", dependencies=[Depends(admin_guard)])
def admin_practices():
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            "SELECT p.id, p.slug, p.name, p.specialty, p.city, p.country, p.timezone, p.currency, p.voip_provider, p.voip_number, p.is_demo, p.listing_status, p.directory_visible, p.published_at, p.created_at, p.plan, p.subscription_status, p.trial_ends_at, "
            "(SELECT COUNT(*) FROM users u WHERE u.practice_id=p.id) AS users, "
            "(SELECT COUNT(*) FROM patients x WHERE x.practice_id=p.id) AS patients, "
            "(SELECT COUNT(*) FROM appointments a WHERE a.practice_id=p.id AND a.status!='cancelled') AS appointments, "
            "(SELECT COUNT(*) FROM calls c WHERE c.practice_id=p.id) AS calls, "
            "(SELECT COUNT(*) FROM notifications n WHERE n.practice_id=p.id AND n.status IN ('sent','mock_sent')) AS notifications_sent "
            "FROM practices p ORDER BY p.id"))



# ------------------------------------------------------------------ annuaire public

@app.get("/api/directory")
def directory_list(specialty: str | None = None, country: str | None = None, city: str | None = None):
    from .directory import list_published
    return {"practices": list_published(specialty=specialty, country=country, city=city)}


@app.get("/api/directory/{slug}")
def directory_one(slug: str):
    from .directory import get_published
    item = get_published(slug)
    if not item:
        raise HTTPException(404, "Cabinet introuvable ou non publié")
    return item


@app.get("/api/directory/{slug}/logo")
def directory_logo(slug: str):
    from .directory import get_published
    from .espace import _logo_file
    item = get_published(slug)
    if not item:
        raise HTTPException(404, "Cabinet introuvable ou non publié")
    p = db.get_practice(slug)
    path = _logo_file(p["id"])
    if not path.is_file():
        raise HTTPException(404, "Pas de logo")
    return FileResponse(path, media_type="image/webp")


class DirectoryContactIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(None, max_length=30)
    message: str = Field(..., min_length=5, max_length=2000)


@app.post("/api/directory/{slug}/contact", status_code=201, dependencies=[Depends(security.limiter("leads"))])
def directory_contact(slug: str, body: DirectoryContactIn):
    from .directory import get_published
    item = get_published(slug)
    if not item:
        raise HTTPException(404, "Cabinet introuvable ou non publié")
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO leads(practice_name, email, phone, specialty, message, source, created_at) VALUES (?,?,?,?,?,?,?)",
            (item["name"], body.email, body.phone or "", item.get("specialty"),
             f"Contact annuaire — {body.name} : {body.message}", "directory", db.now_iso()),
        )
    return {"ok": True, "id": cur.lastrowid, "message": "Votre message a bien été transmis au cabinet."}


@app.post("/api/admin/practices/{pid}/approve", dependencies=[Depends(admin_guard)])
def admin_approve_listing(pid: int):
    from . import directory
    p = db.get_practice(pid)
    if not p:
        raise HTTPException(404, "Cabinet introuvable")
    directory.publish(pid, reason="admin")
    return {"ok": True, "listing_status": "published"}


@app.post("/api/admin/practices/{pid}/reject", dependencies=[Depends(admin_guard)])
def admin_reject_listing(pid: int):
    from . import directory
    p = db.get_practice(pid)
    if not p:
        raise HTTPException(404, "Cabinet introuvable")
    directory.reject(pid)
    return {"ok": True, "listing_status": "rejected"}


def _public_page(name: str):
    path = config.STATIC_DIR / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/fonctionnalites", include_in_schema=False)
def page_features():
    return _public_page("fonctionnalites.html")


@app.get("/specialites", include_in_schema=False)
def page_specs():
    return _public_page("specialites.html")


@app.get("/tarifs", include_in_schema=False)
def page_pricing():
    return _public_page("tarifs.html")


@app.get("/demo", include_in_schema=False)
def page_demo():
    return _public_page("demo.html")


@app.get("/faq", include_in_schema=False)
def page_faq():
    return _public_page("faq.html")


@app.get("/contact", include_in_schema=False)
def page_contact():
    return _public_page("contact.html")


@app.get("/cabinets", include_in_schema=False)
def page_directory():
    return _public_page("cabinets.html")


app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")
