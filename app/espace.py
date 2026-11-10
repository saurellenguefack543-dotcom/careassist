"""Espace cabinet (multi-tenant) : authentification + API privée /api/espace/*.

ISOLATION : chaque requête est filtrée par `user["practice_id"]` issu de la session serveur ; aucun identifiant de
cabinet n'est jamais lu depuis la requête. Un objet d'un autre cabinet renvoie 404 (pas de fuite d'existence).
"""
from __future__ import annotations

import csv
import io
import json
import re
import secrets
import unicodedata
import zipfile
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from . import auth, booking, config, db, messaging, notifications, security
from . import phone as phonelib
from .countries import COUNTRIES, get_country, public_countries
from . import plans, directory
from .specialties import SPECIALTIES

router = APIRouter()
ANY = auth.require_roles("owner", "practitioner", "secretary")
OWNER = auth.require_roles("owner")
STAFF_ADMIN = auth.require_roles("owner", "secretary")
APPT_STATUSES = booking.ALL_STATUSES


def _practice(user: dict) -> dict:
    return db.get_practice(user["practice_id"])


def _slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return (re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "cabinet") + "-" + secrets.token_hex(3)


# ================================================================ auth

class SignupIn(BaseModel):
    practice_name: str = Field(..., min_length=2, max_length=160)
    specialty: str
    country: str = "FR"
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=10, max_length=128)
    address: str = Field("", max_length=300)
    phone: str = Field("", max_length=30)

    @field_validator("specialty")
    @classmethod
    def v_spec(cls, v):
        if v not in SPECIALTIES:
            raise ValueError("spécialité inconnue")
        return v

    @field_validator("country")
    @classmethod
    def v_country(cls, v):
        v = v.upper()
        if v not in COUNTRIES:
            raise ValueError("pays non pris en charge")
        return v

    @field_validator("password")
    @classmethod
    def v_pw(cls, v):
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("le mot de passe doit contenir des lettres et des chiffres (10 caractères minimum)")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


DEFAULT_HOURS = [(wd, "09:00", "12:30") for wd in range(5)] + [(wd, "14:00", "18:30") for wd in range(5)]


def create_practice(conn, *, name, specialty, country, address="", phone="", email=None, slug=None, is_demo=0,
                    hours=None, timezone=None, language="fr", voip_provider="auto", voip_number=None,
                    insurance_note=None, prices_note=None, hours_text=None, access=None) -> int:
    prof = get_country(country)
    pid = conn.execute(
        "INSERT INTO practices(slug, name, specialty, address, phone, hours, access, country, timezone, currency, language, "
        "email, phone_e164, voip_provider, voip_number, insurance_note, prices_note, is_demo, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (slug or _slugify(name), name, specialty, address or "adresse à compléter", phone or "", hours_text or
         "du lundi au vendredi de 9h à 12h30 et de 14h à 18h30", access, prof["code"], timezone or prof["timezone"],
         prof["currency"], language, email, phonelib.to_e164(phone, prof["code"], strict=False), voip_provider,
         voip_number, insurance_note, prices_note, is_demo, db.now_iso())).lastrowid
    conn.executemany("INSERT INTO opening_hours(practice_id, weekday, open_time, close_time) VALUES (?,?,?,?)",
                     [(pid, wd, o, c) for wd, o, c in (hours or DEFAULT_HOURS)])
    return pid


@router.post("/api/auth/signup", status_code=201, dependencies=[Depends(security.limiter("signup"))])
def signup(body: SignupIn, request: Request, response: Response):
    with db.get_conn() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (body.email.lower(),)).fetchone():
            raise HTTPException(409, "Un compte existe déjà avec cet e-mail")
        city = directory.infer_city(body.address)
        pid = create_practice(conn, name=body.practice_name.strip(), specialty=body.specialty, country=body.country,
                              address=body.address, phone=body.phone, email=body.email.lower())
        if city:
            conn.execute("UPDATE practices SET city=? WHERE id=?", (city, pid))
        prac = conn.execute("INSERT INTO practitioners(practice_id, name, specialty, email) VALUES (?,?,?,?)",
                            (pid, body.name.strip(), SPECIALTIES[body.specialty]["label"], body.email.lower())).lastrowid
        uid = auth.create_user(pid, body.email, body.password, body.name, "owner", prac, conn=conn)
    plans.start_trial(pid)
    booking.generate_slots(pid)
    csrf = auth.create_session(uid, request, response)
    security.audit(pid, uid, "signup", "practice", pid, request)
    try:
        directory.notify_admin_new_listing(db.get_practice(pid))
    except Exception:
        pass
    return {"ok": True, "practice_id": pid, "csrf": csrf, "trial_days": plans.TRIAL_DAYS}


@router.post("/api/auth/login", dependencies=[Depends(security.limiter("login"))])
def login(body: LoginIn, request: Request, response: Response):
    security.check("login", "email:" + body.email.lower())
    u = auth.authenticate(body.email, body.password)
    if not u:
        security.audit(None, None, "login.failed", request=request)
        raise HTTPException(401, "E-mail ou mot de passe incorrect")
    csrf = auth.create_session(u["id"], request, response)
    security.audit(u["practice_id"], u["id"], "login", request=request)
    return {"ok": True, "csrf": csrf, "user": {"name": u["name"], "role": u["role"]}}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    auth.destroy_session(request, response)
    return {"ok": True}


class PasswordIn(BaseModel):
    current_password: str = Field(..., max_length=128)
    new_password: str = Field(..., min_length=10, max_length=128)


@router.post("/api/auth/password")
def change_password(body: PasswordIn, request: Request, response: Response, user: dict = Depends(ANY)):
    security.check("login", "pw:" + str(user["id"]))
    full = auth.authenticate(user["email"], body.current_password)
    if not full:
        raise HTTPException(403, "Mot de passe actuel incorrect")
    if not (re.search(r"[A-Za-z]", body.new_password) and re.search(r"\d", body.new_password)):
        raise HTTPException(422, "Le mot de passe doit contenir des lettres et des chiffres")
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (auth.hash_password(body.new_password), user["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))  # déconnecte toutes les sessions
    csrf = auth.create_session(user["id"], request, response)
    security.audit(user["practice_id"], user["id"], "password.change", request=request)
    return {"ok": True, "csrf": csrf}


@router.get("/api/auth/me")
def me(user: dict = Depends(ANY)):
    p = _practice(user)
    out = {"user": user,
           "practice": {k: p[k] for k in ("id", "name", "specialty", "country", "timezone", "currency", "language", "slug")},
           "country": get_country(p["country"]),
           "plan": plans.plan_payload(p),
           "listing": directory.listing_payload(p),
           "logo": bool(p.get("logo_path"))}
    return out


@router.get("/api/countries")
def countries():
    return {"countries": public_countries()}


# ================================================================ tableau de bord

@router.get("/api/espace/dashboard")
def dashboard(user: dict = Depends(ANY)):
    pid = user["practice_id"]
    p = _practice(user)
    today = db.now(p["timezone"]).date().isoformat()
    with db.get_conn() as conn:
        q = lambda sql, *a: conn.execute(sql, (pid, *a)).fetchone()[0]
        stats = {
            "today": q("SELECT COUNT(*) FROM appointments a JOIN slots s ON s.id=a.slot_id WHERE a.practice_id=? AND "
                       "substr(s.start,1,10)=? AND a.status!='cancelled'", today),
            "upcoming": q("SELECT COUNT(*) FROM appointments a JOIN slots s ON s.id=a.slot_id WHERE a.practice_id=? AND "
                          "s.start>=? AND a.status IN ('confirmed','reminded')", today),
            "patients": q("SELECT COUNT(*) FROM patients WHERE practice_id=?"),
            "calls_7d": q("SELECT COUNT(*) FROM calls WHERE practice_id=? AND started_at>=?", (date.fromisoformat(today) - timedelta(days=7)).isoformat()),
            "missed_7d": q("SELECT COUNT(*) FROM calls WHERE practice_id=? AND status IN ('missed','voicemail') AND started_at>=?",
                           (date.fromisoformat(today) - timedelta(days=7)).isoformat()),
            "notif_scheduled": q("SELECT COUNT(*) FROM notifications WHERE practice_id=? AND status='scheduled'"),
            "notif_sent": q("SELECT COUNT(*) FROM notifications WHERE practice_id=? AND status IN ('sent','mock_sent')"),
            "callback_requests": q("SELECT COUNT(*) FROM notifications WHERE practice_id=? AND kind='callback_request'"),
        }
    return {"stats": stats, "today": today, "voip": messaging.status_overview(),
            "appointments": list_appointments(user, start=today, end=(date.fromisoformat(today) + timedelta(days=7)).isoformat())}


# ================================================================ patients

class PatientIn(BaseModel):
    first_name: str = Field("", max_length=80)
    last_name: str = Field(..., min_length=1, max_length=80)
    phone: str | None = Field(None, max_length=30)
    email: EmailStr | None = None
    birth_date: date | None = None
    preferred_channel: str = "auto"
    notify_consent: bool = True
    language: str = Field("fr", max_length=5)
    notes: str | None = Field(None, max_length=2000)

    @field_validator("preferred_channel")
    @classmethod
    def v_ch(cls, v):
        if v not in ("auto", "sms", "whatsapp", "email", "none"):
            raise ValueError("canal invalide")
        return v


def _patient_values(body: PatientIn, country: str) -> dict:
    try:
        e164 = phonelib.to_e164(body.phone, country) if body.phone else None
    except phonelib.PhoneError as e:
        raise HTTPException(422, str(e))
    return {"first_name": body.first_name.strip(), "last_name": body.last_name.strip(), "phone_e164": e164,
            "email": body.email, "birth_date": body.birth_date.isoformat() if body.birth_date else None,
            "preferred_channel": body.preferred_channel, "notify_consent": int(body.notify_consent),
            "language": body.language, "notes": body.notes}


def _get_patient(pid: int, patient_id: int) -> dict:
    with db.get_conn() as conn:
        r = conn.execute("SELECT * FROM patients WHERE id=? AND practice_id=?", (patient_id, pid)).fetchone()
    if not r:
        raise HTTPException(404, "Patient introuvable")
    return dict(r)


@router.get("/api/espace/patients")
def list_patients(q: str = "", limit: int = 200, user: dict = Depends(ANY)):
    """Recherche insensible aux accents et à la casse (nom, prénom, e-mail, téléphone)."""
    with db.get_conn() as conn:
        rows = db.rows(conn.execute("SELECT * FROM patients WHERE practice_id=? ORDER BY last_name, first_name",
                                    (user["practice_id"],)))
    q = _fold(q.strip())
    if q:
        digits = "".join(c for c in q if c.isdigit())
        tail = digits.lstrip("0")
        rows = [r for r in rows if q in _fold(" ".join(filter(None, (r["first_name"], r["last_name"], r["email"]))))
                or (len(tail) >= 3 and tail in (r["phone_e164"] or ""))]
    return rows[: min(limit, 1000)]


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


@router.post("/api/espace/patients", status_code=201)
def create_patient(body: PatientIn, request: Request, user: dict = Depends(ANY)):
    p = _practice(user)
    v = _patient_values(body, p["country"])
    with db.get_conn() as conn:
        if v["phone_e164"] and conn.execute("SELECT 1 FROM patients WHERE practice_id=? AND phone_e164=?",
                                            (p["id"], v["phone_e164"])).fetchone():
            raise HTTPException(409, "Un patient existe déjà avec ce numéro")
        new_id = conn.execute(
            "INSERT INTO patients(practice_id, first_name, last_name, phone_e164, email, birth_date, preferred_channel, "
            "notify_consent, language, notes, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?, 'manual', ?, ?)",
            (p["id"], *v.values(), db.now_iso(), db.now_iso())).lastrowid
    security.audit(p["id"], user["id"], "patient.create", "patient", new_id, request)
    return _get_patient(p["id"], new_id)


@router.get("/api/espace/patients/{patient_id}")
def get_patient(patient_id: int, request: Request, user: dict = Depends(ANY)):
    pid = user["practice_id"]
    pat = _get_patient(pid, patient_id)
    with db.get_conn() as conn:
        pat["appointments"] = db.rows(conn.execute(
            "SELECT a.id, a.status, a.reason, s.start, pr.name AS practitioner FROM appointments a JOIN slots s ON s.id=a.slot_id "
            "JOIN practitioners pr ON pr.id=s.practitioner_id WHERE a.practice_id=? AND a.patient_id=? ORDER BY s.start DESC",
            (pid, patient_id)))
        pat["calls"] = db.rows(conn.execute("SELECT id, provider, status, duration_s, started_at, transcript, voicemail_text "
                                            "FROM calls WHERE practice_id=? AND (patient_id=? OR from_number=?) ORDER BY id DESC",
                                            (pid, patient_id, pat["phone_e164"] or "-")))
        pat["messages"] = db.rows(conn.execute("SELECT id, direction, channel, provider, body, status, created_at FROM channel_messages "
                                               "WHERE practice_id=? AND (patient_id=? OR from_addr=? OR to_addr=?) ORDER BY id DESC LIMIT 200",
                                               (pid, patient_id, pat["phone_e164"] or "-", pat["phone_e164"] or "-")))
        pat["notifications"] = db.rows(conn.execute("SELECT id, recipient_type, kind, channel, status, scheduled_for, sent_at "
                                                    "FROM notifications WHERE practice_id=? AND patient_id=? ORDER BY scheduled_for DESC",
                                                    (pid, patient_id)))
    security.audit(pid, user["id"], "patient.read", "patient", patient_id, request)
    return pat


@router.put("/api/espace/patients/{patient_id}")
def update_patient(patient_id: int, body: PatientIn, request: Request, user: dict = Depends(ANY)):
    p = _practice(user)
    _get_patient(p["id"], patient_id)
    v = _patient_values(body, p["country"])
    with db.get_conn() as conn:
        conn.execute("UPDATE patients SET " + ", ".join(f"{k}=?" for k in v) + ", updated_at=? WHERE id=? AND practice_id=?",
                     (*v.values(), db.now_iso(), patient_id, p["id"]))
    security.audit(p["id"], user["id"], "patient.update", "patient", patient_id, request)
    return _get_patient(p["id"], patient_id)


@router.delete("/api/espace/patients/{patient_id}")
def delete_patient(patient_id: int, request: Request, user: dict = Depends(OWNER)):
    """Droit à l'effacement (RGPD art. 17) : supprime la fiche et anonymise l'historique lié (RDV, appels, messages).
    Attention : le dossier médical relève d'obligations de conservation propres (hors périmètre de CareAssist)."""
    pid = user["practice_id"]
    pat = _get_patient(pid, patient_id)
    e = pat["phone_e164"] or "-"
    # RDV à venir : annulés (créneau libéré, rappels annulés) sans message au patient effacé
    with db.get_conn() as conn:
        upcoming = [r[0] for r in conn.execute(
            "SELECT a.id FROM appointments a JOIN slots s ON s.id=a.slot_id WHERE a.practice_id=? AND a.patient_id=? "
            "AND a.status IN ('confirmed','reminded') AND s.start >= ?", (pid, patient_id, db.now(booking.practice_tz(pid)).isoformat(timespec="minutes")))]
    for appt_id in upcoming:
        booking.cancel(appt_id, practice_id=pid, source="rgpd", notify=False)
    with db.get_conn() as conn:
        conn.execute("UPDATE appointments SET patient_name='[effacé]', phone='', notes=NULL, patient_id=NULL "
                     "WHERE practice_id=? AND patient_id=?", (pid, patient_id))
        conn.execute("UPDATE calls SET from_number='[effacé]', transcript='', voicemail_text=NULL, recording_url=NULL, patient_id=NULL "
                     "WHERE practice_id=? AND (patient_id=? OR from_number=?)", (pid, patient_id, e))
        conn.execute("DELETE FROM channel_messages WHERE practice_id=? AND (patient_id=? OR from_addr=? OR to_addr=?)",
                     (pid, patient_id, e, e))
        conn.execute("UPDATE notifications SET to_addr=NULL, body='[effacé]', status=CASE WHEN status='scheduled' THEN 'cancelled' "
                     "ELSE status END WHERE practice_id=? AND patient_id=?", (pid, patient_id))
        conn.execute("DELETE FROM patients WHERE id=? AND practice_id=?", (patient_id, pid))
    security.audit(pid, user["id"], "patient.delete", "patient", patient_id, request)
    return {"ok": True, "deleted": patient_id, "cancelled_appointments": upcoming}


@router.get("/api/espace/patients/{patient_id}/export")
def export_patient(patient_id: int, request: Request, user: dict = Depends(ANY)):
    """Droit d'accès / portabilité (RGPD art. 15 et 20) : toutes les données d'un patient en JSON."""
    data = get_patient(patient_id, request, user)
    security.audit(user["practice_id"], user["id"], "patient.export", "patient", patient_id, request)
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="patient-{patient_id}.json"'})


# ================================================================ rendez-vous

@router.get("/api/espace/appointments")
def list_appointments(user: dict = Depends(ANY), start: str | None = None, end: str | None = None, status: str | None = None,
                      patient_id: int | None = None):
    sql = ("SELECT a.id, a.status, a.reason, a.appointment_type, a.urgent, a.patient_id, a.patient_name, a.phone, a.notes, a.source, "
           "a.patient_confirmed_at, s.start, s.duration_min, s.practitioner_id, pr.name AS practitioner FROM appointments a "
           "JOIN slots s ON s.id=a.slot_id JOIN practitioners pr ON pr.id=s.practitioner_id WHERE a.practice_id=?")
    args: list = [user["practice_id"]]
    if start:
        sql += " AND s.start >= ?"
        args.append(start)
    if end:
        sql += " AND s.start < ?"
        args.append(end)
    if status:
        sql += " AND a.status = ?"
        args.append(status)
    if patient_id:
        sql += " AND a.patient_id = ?"
        args.append(patient_id)
    sql += " ORDER BY s.start LIMIT 1000"
    with db.get_conn() as conn:
        return db.rows(conn.execute(sql, args))


@router.get("/api/espace/slots")
def free_slots(day: date | None = None, practitioner_id: int | None = None, limit: int = 40, user: dict = Depends(ANY)):
    return booking.find_slots(day=day, practice_id=user["practice_id"], practitioner_id=practitioner_id, limit=limit)


class ApptIn(BaseModel):
    patient_id: int
    slot_id: int
    reason: str = Field("Consultation", max_length=200)
    appointment_type: str | None = Field(None, max_length=40)
    notes: str | None = Field(None, max_length=2000)
    urgent: bool = False


class ApptUpdate(BaseModel):
    status: str | None = None
    notes: str | None = Field(None, max_length=2000)
    slot_id: int | None = None
    reason: str | None = Field(None, max_length=200)


@router.post("/api/espace/appointments", status_code=201)
def create_appt(body: ApptIn, request: Request, user: dict = Depends(ANY)):
    pid = user["practice_id"]
    pat = _get_patient(pid, body.patient_id)
    name = " ".join(x for x in (pat["first_name"], pat["last_name"]) if x)
    try:
        a = booking.book(body.slot_id, name, pat["phone_e164"] or pat["email"] or "-", body.reason, body.urgent,
                         appointment_type=body.appointment_type, practice_id=pid, patient_id=pat["id"], source="cabinet",
                         notes=body.notes)
    except booking.BookingError as e:
        raise HTTPException(409, str(e))
    security.audit(pid, user["id"], "appointment.create", "appointment", a["id"], request)
    return a


def _get_appt(pid: int, appt_id: int) -> dict:
    with db.get_conn() as conn:
        r = conn.execute("SELECT * FROM appointments WHERE id=? AND practice_id=?", (appt_id, pid)).fetchone()
    if not r:
        raise HTTPException(404, "Rendez-vous introuvable")
    return dict(r)


@router.put("/api/espace/appointments/{appt_id}")
def update_appt(appt_id: int, body: ApptUpdate, request: Request, user: dict = Depends(ANY)):
    pid = user["practice_id"]
    a = _get_appt(pid, appt_id)
    if body.status == "cancelled":
        return cancel_appt(appt_id, request, user)
    with db.get_conn() as conn:
        if body.status:
            if body.status not in APPT_STATUSES:
                raise HTTPException(422, "Statut invalide")
            conn.execute("UPDATE appointments SET status=?, updated_at=? WHERE id=? AND practice_id=?",
                         (body.status, db.now_iso(), appt_id, pid))
        if body.notes is not None:
            conn.execute("UPDATE appointments SET notes=? WHERE id=? AND practice_id=?", (body.notes, appt_id, pid))
        if body.reason:
            conn.execute("UPDATE appointments SET reason=? WHERE id=? AND practice_id=?", (body.reason, appt_id, pid))
    if body.slot_id and body.slot_id != a["slot_id"]:  # déplacement : nouveau créneau du MÊME cabinet
        with db.get_conn() as conn:
            owner = conn.execute("SELECT p.practice_id FROM slots s JOIN practitioners p ON p.id=s.practitioner_id WHERE s.id=?",
                                 (body.slot_id,)).fetchone()
            if not owner or owner[0] != pid:
                raise HTTPException(404, "Créneau introuvable")
            if conn.execute("UPDATE slots SET booked=1 WHERE id=? AND booked=0", (body.slot_id,)).rowcount != 1:
                raise HTTPException(409, "Ce créneau n'est plus disponible")
            conn.execute("UPDATE slots SET booked=0 WHERE id=?", (a["slot_id"],))
            conn.execute("UPDATE appointments SET slot_id=?, status='confirmed', updated_at=? WHERE id=? AND practice_id=?",
                         (body.slot_id, db.now_iso(), appt_id, pid))
            conn.execute("UPDATE notifications SET status='cancelled', error='RDV déplacé' WHERE appointment_id=? AND status='scheduled'",
                         (appt_id,))
        notifications.on_booked(appt_id)
    security.audit(pid, user["id"], "appointment.update", "appointment", appt_id, request)
    return _get_appt(pid, appt_id)


@router.post("/api/espace/appointments/{appt_id}/cancel")
def cancel_appt(appt_id: int, request: Request, user: dict = Depends(ANY)):
    pid = user["practice_id"]
    _get_appt(pid, appt_id)
    try:
        booking.cancel(appt_id, practice_id=pid, source="cabinet")
    except booking.BookingError as e:
        raise HTTPException(409, str(e))
    security.audit(pid, user["id"], "appointment.cancel", "appointment", appt_id, request)
    return _get_appt(pid, appt_id)


# ================================================================ appels, messages, notifications

@router.get("/api/espace/calls")
def calls(user: dict = Depends(ANY), limit: int = 200):
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            "SELECT c.*, p.first_name, p.last_name FROM calls c LEFT JOIN patients p ON p.id=c.patient_id AND p.practice_id=c.practice_id "
            "WHERE c.practice_id=? ORDER BY c.id DESC LIMIT ?", (user["practice_id"], min(limit, 1000))))


@router.get("/api/espace/messages")
def messages(user: dict = Depends(ANY), limit: int = 200):
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            "SELECT m.*, p.first_name, p.last_name FROM channel_messages m LEFT JOIN patients p ON p.id=m.patient_id "
            "AND p.practice_id=m.practice_id WHERE m.practice_id=? ORDER BY m.id DESC LIMIT ?", (user["practice_id"], min(limit, 1000))))


@router.get("/api/espace/notifications")
def notifs(user: dict = Depends(ANY), status: str | None = None, limit: int = 300):
    sql = ("SELECT n.id, n.appointment_id, n.patient_id, n.recipient_type, n.kind, n.channel, n.to_addr, n.status, n.scheduled_for, "
           "n.sent_at, n.provider, n.error, n.body FROM notifications n WHERE n.practice_id=?")
    args: list = [user["practice_id"]]
    if status:
        sql += " AND n.status=?"
        args.append(status)
    sql += " ORDER BY n.scheduled_for DESC LIMIT ?"
    args.append(min(limit, 2000))
    with db.get_conn() as conn:
        return db.rows(conn.execute(sql, args))


# ================================================================ équipe & horaires

class PractitionerIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    specialty: str = Field("", max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=30)
    notify_channel: str | None = None
    active: bool = True


@router.get("/api/espace/practitioners")
def practitioners(user: dict = Depends(ANY)):
    with db.get_conn() as conn:
        return db.rows(conn.execute("SELECT id, name, specialty, email, phone_e164, notify_channel, active FROM practitioners "
                                    "WHERE practice_id=? ORDER BY id", (user["practice_id"],)))


def _prac_values(body: PractitionerIn, country: str) -> tuple:
    try:
        e = phonelib.to_e164(body.phone, country) if body.phone else None
    except phonelib.PhoneError as ex:
        raise HTTPException(422, str(ex))
    if body.notify_channel not in (None, "", "email", "sms", "whatsapp"):
        raise HTTPException(422, "Canal invalide")
    return (body.name.strip(), body.specialty, body.email, e, body.notify_channel or None, int(body.active))


@router.post("/api/espace/practitioners", status_code=201)
def add_practitioner(body: PractitionerIn, request: Request, user: dict = Depends(OWNER)):
    p = _practice(user)
    with db.get_conn() as conn:
        new = conn.execute("INSERT INTO practitioners(name, specialty, email, phone_e164, notify_channel, active, practice_id) "
                           "VALUES (?,?,?,?,?,?,?)", (*_prac_values(body, p["country"]), p["id"])).lastrowid
    booking.generate_slots(p["id"])
    security.audit(p["id"], user["id"], "practitioner.create", "practitioner", new, request)
    return {"id": new}


@router.put("/api/espace/practitioners/{prac_id}")
def edit_practitioner(prac_id: int, body: PractitionerIn, request: Request, user: dict = Depends(OWNER)):
    p = _practice(user)
    with db.get_conn() as conn:
        cur = conn.execute("UPDATE practitioners SET name=?, specialty=?, email=?, phone_e164=?, notify_channel=?, active=? "
                           "WHERE id=? AND practice_id=?", (*_prac_values(body, p["country"]), prac_id, p["id"]))
    if cur.rowcount != 1:
        raise HTTPException(404, "Praticien introuvable")
    security.audit(p["id"], user["id"], "practitioner.update", "practitioner", prac_id, request)
    return {"ok": True}


class HoursIn(BaseModel):
    hours: list[dict]


@router.get("/api/espace/hours")
def get_hours(user: dict = Depends(ANY)):
    with db.get_conn() as conn:
        return db.rows(conn.execute("SELECT weekday, open_time, close_time FROM opening_hours WHERE practice_id=? "
                                    "ORDER BY weekday, open_time", (user["practice_id"],)))


@router.put("/api/espace/hours")
def put_hours(body: HoursIn, request: Request, user: dict = Depends(OWNER)):
    rows = []
    for h in body.hours:
        try:
            wd, o, c = int(h["weekday"]), str(h["open_time"]), str(h["close_time"])
        except (KeyError, ValueError, TypeError):
            raise HTTPException(422, "Plage horaire invalide")
        if not (0 <= wd <= 6 and re.fullmatch(r"\d{2}:\d{2}", o) and re.fullmatch(r"\d{2}:\d{2}", c) and o < c):
            raise HTTPException(422, f"Plage horaire invalide : {h}")
        rows.append((user["practice_id"], wd, o, c))
    with db.get_conn() as conn:
        conn.execute("DELETE FROM opening_hours WHERE practice_id=?", (user["practice_id"],))
        conn.executemany("INSERT INTO opening_hours(practice_id, weekday, open_time, close_time) VALUES (?,?,?,?)", rows)
    created = booking.generate_slots(user["practice_id"])
    security.audit(user["practice_id"], user["id"], "hours.update", request=request)
    return {"ok": True, "slots_created": created}


class UserIn(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=2, max_length=120)
    role: str
    password: str = Field(..., min_length=10, max_length=128)


@router.get("/api/espace/users")
def users(user: dict = Depends(OWNER)):
    with db.get_conn() as conn:
        return db.rows(conn.execute("SELECT id, email, name, role, active, last_login_at FROM users WHERE practice_id=? ORDER BY id",
                                    (user["practice_id"],)))


@router.post("/api/espace/users", status_code=201)
def add_user(body: UserIn, request: Request, user: dict = Depends(OWNER)):
    if body.role not in auth.ROLES:
        raise HTTPException(422, "Rôle invalide")
    ok, msg = plans.can_add_user(_practice(user))
    if not ok:
        raise HTTPException(403, msg)
    with db.get_conn() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (body.email.lower(),)).fetchone():
            raise HTTPException(409, "E-mail déjà utilisé")
    uid = auth.create_user(user["practice_id"], body.email, body.password, body.name, body.role)
    security.audit(user["practice_id"], user["id"], "user.create", "user", uid, request)
    return {"id": uid}


# ================================================================ paramètres

class SettingsIn(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=160)
    address: str | None = Field(None, max_length=300)
    phone: str | None = Field(None, max_length=30)
    email: EmailStr | None = None
    hours: str | None = Field(None, max_length=300)
    access: str | None = Field(None, max_length=300)
    specialty: str | None = None
    country: str | None = None
    timezone: str | None = None
    currency: str | None = Field(None, max_length=3)
    language: str | None = None
    notify_on_booking: bool | None = None
    notify_practitioner: bool | None = None
    notify_patient_offsets: list[int] | None = None
    notify_practitioner_offsets: list[int] | None = None
    patient_channels: list[str] | None = None
    practitioner_channel: str | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    missed_call_sms: bool | None = None
    voip_provider: str | None = None
    voip_number: str | None = None
    transfer_number: str | None = None
    insurance_note: str | None = Field(None, max_length=1000)
    prices_note: str | None = Field(None, max_length=1000)
    city: str | None = Field(None, max_length=120)
    emergency_contact_name: str | None = Field(None, max_length=160)
    emergency_contact_phone: str | None = Field(None, max_length=30)
    directory_visible: bool | None = None


SETTINGS_FIELDS = ("id", "name", "specialty", "address", "phone", "email", "hours", "access", "country", "timezone", "currency",
                   "language", "notify_on_booking", "notify_practitioner", "notify_patient_offsets", "notify_practitioner_offsets",
                   "patient_channels", "practitioner_channel", "quiet_start", "quiet_end", "missed_call_sms", "voip_provider",
                   "voip_number", "transfer_number", "insurance_note", "prices_note", "city", "emergency_contact_name",
                   "emergency_contact_phone", "directory_visible", "listing_status", "published_at", "created_at", "logo_path")


@router.get("/api/espace/settings")
def get_settings(user: dict = Depends(ANY)):
    p = _practice(user)
    out = {k: p.get(k) for k in SETTINGS_FIELDS}
    for k in ("notify_patient_offsets", "notify_practitioner_offsets", "patient_channels"):
        out[k] = json.loads(out[k]) if out[k] else None
    out["country_profile"] = get_country(p["country"])
    out["voip_status"] = messaging.status_overview()
    out["specialties"] = {k: v["label"] for k, v in SPECIALTIES.items()}
    out["countries"] = {k: v["name"] for k, v in COUNTRIES.items()}
    out["has_logo"] = bool(p.get("logo_path"))
    out["listing"] = directory.listing_payload(p)
    out["plan"] = plans.plan_payload(p)
    out["directory_visible"] = bool(p.get("directory_visible", 1))
    if not out.get("city"):
        out["city"] = directory.infer_city(p.get("address"))
    return out


@router.put("/api/espace/settings")
def put_settings(body: SettingsIn, request: Request, user: dict = Depends(OWNER)):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    p = _practice(user)
    v = body.model_dump(exclude_unset=True)
    country = (v.get("country") or p["country"]).upper()
    if "country" in v:
        if country not in COUNTRIES:
            raise HTTPException(422, "Pays non pris en charge")
        v["country"] = country
        if "timezone" not in v:
            v["timezone"] = COUNTRIES[country]["timezone"]
        if "currency" not in v:
            v["currency"] = get_country(country)["currency"]
    if "timezone" in v:
        try:
            ZoneInfo(v["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(422, "Fuseau horaire invalide")
    if "specialty" in v and v["specialty"] not in SPECIALTIES:
        raise HTTPException(422, "Spécialité inconnue")
    if "language" in v and v["language"] not in ("fr", "en"):
        raise HTTPException(422, "Langue non prise en charge (fr, en)")
    for k in ("quiet_start", "quiet_end"):
        if k in v and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v[k] or ""):
            raise HTTPException(422, f"{k} : format HH:MM attendu")
    for k in ("notify_patient_offsets", "notify_practitioner_offsets"):
        if k in v:
            if any(m <= 0 or m > 60 * 24 * 14 for m in v[k]):
                raise HTTPException(422, "Délai de rappel invalide (minutes, max 14 jours)")
            v[k] = json.dumps(sorted(set(v[k]), reverse=True))
    if "patient_channels" in v:
        if any(c not in ("sms", "whatsapp", "email") for c in v["patient_channels"]):
            raise HTTPException(422, "Canal invalide")
        v["patient_channels"] = json.dumps(v["patient_channels"])
    if "practitioner_channel" in v and v["practitioner_channel"] not in ("email", "sms", "whatsapp"):
        raise HTTPException(422, "Canal praticien invalide")
    if "voip_provider" in v and v["voip_provider"] not in ("auto", "twilio", "vonage", "africastalking"):
        raise HTTPException(422, "Fournisseur VoIP invalide")
    if (v.get("voip_number") or (v.get("voip_provider") and v.get("voip_provider") != "auto" and v.get("voip_provider") != p.get("voip_provider"))) and not plans.can_use_voip(p):
        if v.get("voip_number"):
            raise HTTPException(403, "Le numéro VoIP dédié est réservé au plan Premium.")
    for k in ("voip_number", "transfer_number", "phone", "emergency_contact_phone"):
        if v.get(k):
            try:
                e = phonelib.to_e164(v[k], country)
            except phonelib.PhoneError as ex:
                raise HTTPException(422, str(ex))
            if k == "phone":
                v["phone_e164"] = e
            else:
                v[k] = e
    if v.get("voip_number"):
        with db.get_conn() as conn:
            if conn.execute("SELECT 1 FROM practices WHERE voip_number=? AND id!=?", (v["voip_number"], p["id"])).fetchone():
                raise HTTPException(409, "Ce numéro VoIP est déjà attribué à un autre cabinet")
    for k in ("notify_on_booking", "notify_practitioner", "missed_call_sms", "directory_visible"):
        if k in v:
            v[k] = int(v[k])
    if "city" in v and v["city"] is not None:
        v["city"] = v["city"].strip()
    if v:
        with db.get_conn() as conn:
            conn.execute("UPDATE practices SET " + ", ".join(f"{k}=?" for k in v) + " WHERE id=?", (*v.values(), p["id"]))
    security.audit(p["id"], user["id"], "settings.update", request=request)
    return get_settings(user)


# ================================================================ export & sauvegarde

def practice_export(pid: int) -> dict:
    with db.get_conn() as conn:
        pr = dict(conn.execute("SELECT * FROM practices WHERE id=?", (pid,)).fetchone())
        return {
            "exported_at": db.now_iso(), "format": "careassist-export-v1", "practice": pr,
            "practitioners": db.rows(conn.execute("SELECT * FROM practitioners WHERE practice_id=?", (pid,))),
            "opening_hours": db.rows(conn.execute("SELECT weekday, open_time, close_time FROM opening_hours WHERE practice_id=?", (pid,))),
            "patients": db.rows(conn.execute("SELECT * FROM patients WHERE practice_id=? ORDER BY id", (pid,))),
            "appointments": db.rows(conn.execute(
                "SELECT a.*, s.start, s.duration_min, pr.name AS practitioner FROM appointments a JOIN slots s ON s.id=a.slot_id "
                "JOIN practitioners pr ON pr.id=s.practitioner_id WHERE a.practice_id=? ORDER BY s.start", (pid,))),
            "calls": db.rows(conn.execute("SELECT * FROM calls WHERE practice_id=? ORDER BY id", (pid,))),
            "messages": db.rows(conn.execute("SELECT * FROM channel_messages WHERE practice_id=? ORDER BY id", (pid,))),
            "notifications": db.rows(conn.execute("SELECT * FROM notifications WHERE practice_id=? ORDER BY id", (pid,))),
        }


def _csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        for r in rows:  # neutralise l'injection de formules (CSV injection)
            w.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v) for k, v in r.items()})
    return "\ufeff" + buf.getvalue()


@router.get("/api/espace/export")
def export(request: Request, format: str = "json", user: dict = Depends(STAFF_ADMIN)):
    pid = user["practice_id"]
    data = practice_export(pid)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    security.audit(pid, user["id"], f"export.{format}", request=request)
    if format == "csv":
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("patients.csv", _csv(data["patients"]))
            z.writestr("rendez-vous.csv", _csv(data["appointments"]))
            z.writestr("appels.csv", _csv(data["calls"]))
            z.writestr("notifications.csv", _csv(data["notifications"]))
        mem.seek(0)
        return StreamingResponse(mem, media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="careassist-export-{stamp}.zip"'})
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="careassist-export-{stamp}.json"'})


@router.get("/api/espace/audit")
def audit_log(user: dict = Depends(OWNER), limit: int = 200):
    with db.get_conn() as conn:
        return db.rows(conn.execute("SELECT a.id, a.action, a.entity, a.entity_id, a.created_at, u.name AS user FROM audit_log a "
                                    "LEFT JOIN users u ON u.id=a.user_id WHERE a.practice_id=? ORDER BY a.id DESC LIMIT ?",
                                    (user["practice_id"], min(limit, 1000))))


@router.post("/api/espace/notifications/run")
def run_notifications(user: dict = Depends(STAFF_ADMIN)):
    """Déclenche l'envoi des notifications échues (toutes les notifications sont de toute façon traitées par le
    planificateur) — utile en démo."""
    return notifications.dispatch_due(practice_id=user["practice_id"])


# ================================================================ logo & FAQ

LOGO_DIR = config.BASE_DIR / "data" / "logos"
LOGO_MAX_BYTES = 1_000_000


def _logo_file(pid: int) -> Path:
    return LOGO_DIR / f"{pid}.webp"


@router.get("/api/espace/logo")
def get_logo(user: dict = Depends(ANY)):
    path = _logo_file(user["practice_id"])
    if not path.is_file():
        raise HTTPException(404, "Aucun logo")
    return FileResponse(path, media_type="image/webp")


@router.post("/api/espace/logo")
async def upload_logo(request: Request, user: dict = Depends(OWNER), file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > LOGO_MAX_BYTES:
        raise HTTPException(422, "Logo trop volumineux (1 Mo maximum)")
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im = im.convert("RGB")
        im.thumbnail((800, 800))
    except Exception:
        raise HTTPException(422, "Fichier image invalide (JPEG, PNG ou WebP)")
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    dest = _logo_file(user["practice_id"])
    im.save(dest, "WEBP", quality=82, method=6)
    rel = str(dest)
    with db.get_conn() as conn:
        conn.execute("UPDATE practices SET logo_path=? WHERE id=?", (rel, user["practice_id"]))
    security.audit(user["practice_id"], user["id"], "logo.update", request=request)
    return {"ok": True, "has_logo": True}


@router.delete("/api/espace/logo")
def delete_logo(request: Request, user: dict = Depends(OWNER)):
    path = _logo_file(user["practice_id"])
    if path.exists():
        path.unlink()
    with db.get_conn() as conn:
        conn.execute("UPDATE practices SET logo_path=NULL WHERE id=?", (user["practice_id"],))
    security.audit(user["practice_id"], user["id"], "logo.delete", request=request)
    return {"ok": True}


class FaqIn(BaseModel):
    question: str = Field(..., min_length=3, max_length=300)
    answer: str = Field(..., min_length=3, max_length=2000)
    keywords: str | None = Field(None, max_length=300)
    sort_order: int = 0


def _faq_row(conn, faq_id: int, pid: int):
    r = conn.execute("SELECT * FROM practice_faq WHERE id=? AND practice_id=?", (faq_id, pid)).fetchone()
    if not r:
        raise HTTPException(404, "Question introuvable")
    return dict(r)


@router.get("/api/espace/faq")
def list_faq(user: dict = Depends(ANY)):
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            "SELECT id, question, answer, keywords, sort_order FROM practice_faq WHERE practice_id=? ORDER BY sort_order, id",
            (user["practice_id"],)))


@router.post("/api/espace/faq", status_code=201)
def add_faq(body: FaqIn, request: Request, user: dict = Depends(OWNER)):
    with db.get_conn() as conn:
        fid = conn.execute(
            "INSERT INTO practice_faq(practice_id, question, answer, keywords, sort_order) VALUES (?,?,?,?,?)",
            (user["practice_id"], body.question.strip(), body.answer.strip(), (body.keywords or "").strip(), body.sort_order),
        ).lastrowid
        row = _faq_row(conn, fid, user["practice_id"])
    security.audit(user["practice_id"], user["id"], "faq.create", "faq", fid, request)
    return row


@router.put("/api/espace/faq/{faq_id}")
def update_faq(faq_id: int, body: FaqIn, request: Request, user: dict = Depends(OWNER)):
    with db.get_conn() as conn:
        _faq_row(conn, faq_id, user["practice_id"])
        conn.execute(
            "UPDATE practice_faq SET question=?, answer=?, keywords=?, sort_order=? WHERE id=? AND practice_id=?",
            (body.question.strip(), body.answer.strip(), (body.keywords or "").strip(), body.sort_order, faq_id, user["practice_id"]),
        )
        row = _faq_row(conn, faq_id, user["practice_id"])
    security.audit(user["practice_id"], user["id"], "faq.update", "faq", faq_id, request)
    return row


@router.delete("/api/espace/faq/{faq_id}")
def delete_faq(faq_id: int, request: Request, user: dict = Depends(OWNER)):
    with db.get_conn() as conn:
        _faq_row(conn, faq_id, user["practice_id"])
        conn.execute("DELETE FROM practice_faq WHERE id=? AND practice_id=?", (faq_id, user["practice_id"]))
    security.audit(user["practice_id"], user["id"], "faq.delete", "faq", faq_id, request)
    return {"ok": True}
