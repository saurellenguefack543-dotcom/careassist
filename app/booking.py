"""Logique de réservation : disponibilités, réservation, annulation."""
from __future__ import annotations

import logging
from datetime import date, datetime

from . import db
from .calendar_adapter import get_calendar
from . import phone as phonelib

log = logging.getLogger("careassist.booking")
ACTIVE_STATUSES = ("confirmed", "reminded")
ALL_STATUSES = ("confirmed", "reminded", "honored", "no_show", "cancelled")


def practice_tz(practice_id: int | None) -> str | None:
    if not practice_id:
        return None
    with db.get_conn() as conn:
        r = conn.execute("SELECT timezone FROM practices WHERE id=?", (practice_id,)).fetchone()
    return r[0] if r else None

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


class BookingError(Exception):
    pass


def format_slot(start_iso: str, tz: str | None = None) -> str:
    dt = datetime.fromisoformat(start_iso)
    today = db.now(tz).date()
    if dt.date() == today:
        day = "aujourd'hui"
    elif (dt.date() - today).days == 1:
        day = "demain"
    else:
        day = f"{JOURS[dt.weekday()]} {dt.day} {MOIS[dt.month - 1]}"
    return f"{day} à {dt.hour}h{dt.minute:02d}" if dt.minute else f"{day} à {dt.hour}h"


def find_slots(
    day: date | None = None,
    period: str | None = None,       # matin | apres-midi | soir
    hour: int | None = None,
    weekday: int | None = None,
    emergency: bool = False,
    limit: int = 3,
    practitioner_id: int | None = None,
    practice_id: int | None = None,
) -> list[dict]:
    """Créneaux libres futurs correspondant aux préférences.

    emergency=True : uniquement les créneaux réservés aux urgences (au plus tôt).
    Sinon : créneaux standards (les créneaux urgence restent protégés).
    """
    q = ("SELECT s.*, p.name AS practitioner, p.specialty FROM slots s "
         "JOIN practitioners p ON p.id = s.practitioner_id WHERE s.booked = 0 AND s.start > ?")
    tz = practice_tz(practice_id)
    params: list = [db.now(tz).strftime("%Y-%m-%dT%H:%M")]
    q += " AND s.is_emergency = ?"
    params.append(1 if emergency else 0)
    if day:
        q += " AND substr(s.start, 1, 10) = ?"
        params.append(day.isoformat())
    if practitioner_id:
        q += " AND s.practitioner_id = ?"
        params.append(practitioner_id)
    if practice_id:
        q += " AND p.practice_id = ?"
        params.append(practice_id)
    q += " ORDER BY s.start, s.practitioner_id"
    with db.get_conn() as conn:
        candidates = db.rows(conn.execute(q, params))
    out, seen_times = [], set()
    for s in candidates:
        dt = datetime.fromisoformat(s["start"])
        if weekday is not None and dt.weekday() != weekday:
            continue
        if period == "matin" and dt.hour >= 13:
            continue
        if period == "apres-midi" and not (13 <= dt.hour < 18):
            continue
        if period == "soir" and dt.hour < 17:
            continue
        if hour is not None and dt.hour != hour:
            continue
        if s["start"] in seen_times:  # varier les horaires proposés
            continue
        seen_times.add(s["start"])
        s["label"] = format_slot(s["start"], tz)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def get_slot(slot_id: int) -> dict | None:
    with db.get_conn() as conn:
        r = conn.execute(
            "SELECT s.*, p.name AS practitioner, p.practice_id, pr.timezone FROM slots s JOIN practitioners p ON p.id=s.practitioner_id "
            "JOIN practices pr ON pr.id=p.practice_id WHERE s.id=?",
            (slot_id,),
        ).fetchone()
    if not r:
        return None
    d = dict(r)
    d["label"] = format_slot(d["start"], d.get("timezone"))
    return d


def book(slot_id: int, patient_name: str, phone: str, reason: str = "", urgent: bool = False,
         conversation_id: int | None = None, appointment_type: str | None = None, *, practice_id: int | None = None,
         patient_id: int | None = None, source: str = "assistant", notes: str | None = None, notify: bool = True) -> dict:
    """Réserve un créneau. `practice_id` (espace cabinet) : le créneau DOIT appartenir à ce cabinet."""
    patient_name = (patient_name or "").strip()
    phone = (phone or "").strip()
    if not patient_name or not phone:
        raise BookingError("Nom et téléphone obligatoires")
    with db.get_conn() as conn:
        # réservation atomique : on ne prend le créneau que s'il est libre
        if practice_id is not None:
            owner = conn.execute("SELECT p.practice_id FROM slots s JOIN practitioners p ON p.id=s.practitioner_id WHERE s.id=?",
                                 (slot_id,)).fetchone()
            if not owner or owner[0] != practice_id:
                raise BookingError("Créneau introuvable")
        cur = conn.execute("UPDATE slots SET booked = 1 WHERE id = ? AND booked = 0", (slot_id,))
        if cur.rowcount != 1:
            raise BookingError("Ce créneau n'est plus disponible")
        slot = dict(conn.execute(
            "SELECT s.*, p.name AS practitioner, p.practice_id, pr.timezone, pr.country FROM slots s "
            "JOIN practitioners p ON p.id=s.practitioner_id JOIN practices pr ON pr.id=p.practice_id WHERE s.id=?",
            (slot_id,),
        ).fetchone())
        event_id = None
        try:
            event_id = get_calendar().create_event(
                summary=f"{'[URGENCE] ' if urgent else ''}{patient_name} — {reason or 'consultation'}",
                start_iso=slot["start"],
                duration_min=slot["duration_min"],
                description=f"Tél: {phone} — pris par CareAssist",
            )
        except Exception:  # l'agenda externe ne doit pas bloquer la réservation
            event_id = None
        c2 = conn.execute(
            "INSERT INTO appointments(slot_id, practice_id, patient_name, phone, reason, appointment_type, urgent, status, "
            "calendar_event_id, conversation_id, created_at, source, notes) VALUES (?,?,?,?,?,?,?, 'confirmed', ?,?,?,?,?)",
            (slot_id, slot["practice_id"], patient_name, phone, reason, appointment_type, int(urgent), event_id,
             conversation_id, db.now_iso(), source, notes),
        )
        appt_id = c2.lastrowid
    # fiche patient (base patients du cabinet) + notifications (confirmation, rappels J-1 / H-2)
    from . import notifications, patients
    try:
        pid = patient_id or patients.upsert_from_booking(slot["practice_id"], patient_name, phone, slot.get("country") or "FR")
        with db.get_conn() as conn:
            conn.execute("UPDATE appointments SET patient_id=? WHERE id=?", (pid, appt_id))
        patient_id = pid
    except Exception as exc:  # ne jamais bloquer une réservation
        log.warning("fiche patient non créée : %s", exc)
    scheduled = []
    if notify:
        try:
            scheduled = notifications.on_booked(appt_id)
        except Exception as exc:
            log.warning("notifications non planifiées : %s", exc)
    return {
        "id": appt_id, "slot_id": slot_id, "start": slot["start"], "label": format_slot(slot["start"], slot.get("timezone")),
        "patient_id": patient_id, "notifications": scheduled,
        "practitioner": slot["practitioner"], "patient_name": patient_name, "phone": phone,
        "reason": reason, "appointment_type": appointment_type, "practice_id": slot["practice_id"], "urgent": urgent, "status": "confirmed", "calendar_event_id": event_id,
    }


def normalize_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("33") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits


def upcoming_for_phone(phone: str, practice_id: int | None = None) -> list[dict]:
    with db.get_conn() as conn:
        appts = db.rows(conn.execute(
            "SELECT a.*, s.start, p.name AS practitioner, pr.country, pr.timezone FROM appointments a JOIN slots s ON s.id=a.slot_id "
            "JOIN practitioners p ON p.id=s.practitioner_id JOIN practices pr ON pr.id=p.practice_id "
            "WHERE a.status IN ('confirmed','reminded') " + ("AND a.practice_id=? " if practice_id else "") + "ORDER BY s.start",
            ((practice_id,) if practice_id else ()),
        ))
    out = []
    for a in appts:
        if a["start"] <= db.now(a.get("timezone")).strftime("%Y-%m-%dT%H:%M"):
            continue
        if phonelib.same_number(a["phone"], phone, a.get("country") or "FR"):
            a["label"] = format_slot(a["start"], a.get("timezone"))
            out.append(a)
    return out


def cancel(appointment_id: int, practice_id: int | None = None, source: str = "assistant", notify: bool = True) -> dict:
    """Annule un RDV. `practice_id` (espace cabinet) : refuse si le RDV appartient à un autre cabinet."""
    with db.get_conn() as conn:
        if practice_id is not None:
            r = conn.execute("SELECT * FROM appointments WHERE id=? AND practice_id=?", (appointment_id, practice_id)).fetchone()
        else:
            r = conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
        if not r:
            raise BookingError("Rendez-vous introuvable")
        a = dict(r)
        if a["status"] == "cancelled":
            raise BookingError("Rendez-vous déjà annulé")
        conn.execute("UPDATE appointments SET status='cancelled', cancelled_at=?, updated_at=? WHERE id=?",
                     (db.now_iso(), db.now_iso(), appointment_id))
        conn.execute("UPDATE slots SET booked=0 WHERE id=?", (a["slot_id"],))
    if a.get("calendar_event_id"):
        try:
            get_calendar().delete_event(a["calendar_event_id"])
        except Exception:
            pass
    a["status"] = "cancelled"
    from . import notifications
    try:
        notifications.on_cancelled(appointment_id, source=source, notify=notify)
    except Exception as exc:
        log.warning("notifications d'annulation : %s", exc)
    return a


def generate_slots(practice_id: int, days: int = 14) -> int:
    """Crée (idempotent) les créneaux des `days` prochains jours à partir des horaires d'ouverture du cabinet."""
    from datetime import timedelta
    from .specialties import get_specialty
    with db.get_conn() as conn:
        pr = conn.execute("SELECT specialty, timezone FROM practices WHERE id=?", (practice_id,)).fetchone()
        if not pr:
            return 0
        hours = db.rows(conn.execute("SELECT weekday, open_time, close_time FROM opening_hours WHERE practice_id=?", (practice_id,)))
        pracs = [r[0] for r in conn.execute("SELECT id FROM practitioners WHERE practice_id=? AND active=1", (practice_id,))]
        step = get_specialty(pr["specialty"])["slot_minutes"]
        today = db.now(pr["timezone"]).date()
        created = 0
        for off in range(days):
            d = today + timedelta(days=off)
            for h in (x for x in hours if x["weekday"] == d.weekday()):
                cur = datetime.fromisoformat(f"{d.isoformat()}T{h['open_time']}")
                end = datetime.fromisoformat(f"{d.isoformat()}T{h['close_time']}")
                while cur + timedelta(minutes=step) <= end:
                    for pid in pracs:
                        created += conn.execute(
                            "INSERT OR IGNORE INTO slots(practitioner_id, start, duration_min, is_emergency, booked) VALUES (?,?,?,0,0)",
                            (pid, cur.strftime("%Y-%m-%dT%H:%M"), step)).rowcount
                    cur += timedelta(minutes=step)
    return created
