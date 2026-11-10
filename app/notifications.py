"""Notifications automatiques : confirmation à la prise de RDV, rappels (J-1 et H-2 par défaut) au patient ET au
praticien, annulations, proposition de rappel après appel manqué, réponses patient (OUI / NON / ANNULER / STOP).

Garanties :
- Idempotence : chaque notification a une `dedupe_key` UNIQUE (INSERT OR IGNORE) et l'envoi « réclame » la ligne
  (UPDATE … WHERE status='scheduled') avant d'envoyer : relancer le job, ou deux workers en parallèle, n'envoie
  jamais deux fois le même rappel.
- Fuseaux : l'heure du RDV est interprétée dans le fuseau du cabinet ; `scheduled_for` est stocké en UTC.
- Heures calmes (quiet hours, 21:00-08:00 par défaut, réglables) : un rappel tombant dans la plage est avancé à la
  veille au soir ou décalé au matin s'il reste avant le RDV ; vérifié à nouveau au moment de l'envoi.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db, messaging
from . import phone as phonelib
from .countries import get_country

log = logging.getLogger("careassist.notifications")

PATIENT_INITIATED = ("assistant", "web", "phone", "sms", "whatsapp", "vapi")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


# ---------------------------------------------------------------- helpers temps

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _hm(s: str | None, default: str) -> time:
    h, m = (s or default).split(":")
    return time(int(h), int(m))


def in_quiet(local: datetime, qs: time, qe: time) -> bool:
    t = local.time()
    if qs == qe:
        return False
    return (qs <= t < qe) if qs < qe else (t >= qs or t < qe)


def adjust_for_quiet(when: datetime, appt: datetime, now: datetime, qs: time, qe: time) -> datetime | None:
    """`when`, `appt`, `now` : datetimes locales (aware) du cabinet. None = à ne pas envoyer."""
    if not in_quiet(when, qs, qe):
        return when
    after = when.replace(hour=qe.hour, minute=qe.minute, second=0)
    if after <= when:
        after += timedelta(days=1)
    if after <= appt - timedelta(minutes=30):
        return after
    before = when.replace(hour=qs.hour, minute=qs.minute, second=0)
    if before > when:
        before -= timedelta(days=1)
    before -= timedelta(minutes=5)
    if before > now:
        return before
    return after if after < appt else None


def offsets(raw, default) -> list[int]:
    try:
        vals = json.loads(raw) if isinstance(raw, str) else (raw or default)
        return sorted({int(v) for v in vals if int(v) > 0}, reverse=True)
    except (ValueError, TypeError):
        return default


def offset_label(minutes: int) -> str:
    if minutes % 1440 == 0:
        return f"J-{minutes // 1440}"
    if minutes % 60 == 0:
        return f"H-{minutes // 60}"
    return f"{minutes} min avant"


# ---------------------------------------------------------------- contexte

def _context(appt_id: int) -> dict | None:
    with db.get_conn() as conn:
        a = conn.execute(
            "SELECT a.*, s.start, s.duration_min, s.practitioner_id, p.name AS practitioner, p.email AS practitioner_email, "
            "p.phone_e164 AS practitioner_phone, p.notify_channel AS practitioner_notify_channel "
            "FROM appointments a JOIN slots s ON s.id=a.slot_id JOIN practitioners p ON p.id=s.practitioner_id WHERE a.id=?",
            (appt_id,)).fetchone()
        if not a:
            return None
        a = dict(a)
        pr = dict(conn.execute("SELECT * FROM practices WHERE id=?", (a["practice_id"],)).fetchone())
        pat = conn.execute("SELECT * FROM patients WHERE id=? AND practice_id=?", (a.get("patient_id"), pr["id"])).fetchone()
    return {"appt": a, "practice": pr, "patient": dict(pat) if pat else None}


def _tz(practice: dict) -> ZoneInfo:
    return ZoneInfo(practice.get("timezone") or get_country(practice.get("country"))["timezone"])


def appt_local(ctx: dict) -> datetime:
    return datetime.fromisoformat(ctx["appt"]["start"]).replace(tzinfo=_tz(ctx["practice"]))


def fmt_when(ctx: dict) -> str:
    dt = appt_local(ctx)
    prof = get_country(ctx["practice"].get("country"))
    return f"{JOURS[dt.weekday()]} {dt.strftime(prof['date_format'])} à {dt.strftime(prof['time_format'])}"


def choose_patient_channel(practice: dict, patient: dict | None) -> tuple[str | None, str | None, str]:
    """Renvoie (canal, adresse, raison). Respecte consentement, préférence patient puis défauts pays/cabinet."""
    if not patient:
        return None, None, "aucune fiche patient"
    if not patient.get("notify_consent"):
        return None, None, "pas de consentement aux notifications"
    pref = patient.get("preferred_channel") or "auto"
    if pref == "none":
        return None, None, "le patient a refusé les notifications"
    try:
        defaults = json.loads(practice.get("patient_channels") or "null") or get_country(practice.get("country"))["preferred_channels"]
    except ValueError:
        defaults = get_country(practice.get("country"))["preferred_channels"]
    from . import plans
    allowed = set(plans.allowed_channels(practice))
    order = ([pref] if pref != "auto" else []) + [c for c in defaults if c != pref] + ["sms", "email"]
    for ch in order:
        if ch not in allowed:
            continue
        if ch in ("sms", "whatsapp") and patient.get("phone_e164"):
            return ch, patient["phone_e164"], "ok"
        if ch == "email" and patient.get("email"):
            return ch, patient["email"], "ok"
    if allowed == {"email"}:
        return None, None, "plan gratuit : rappels par e-mail uniquement, aucune adresse"
    return None, None, "aucune coordonnée utilisable"


def choose_practitioner_channel(practice: dict, appt: dict) -> tuple[str | None, str | None, str]:
    from . import plans
    pref = appt.get("practitioner_notify_channel") or practice.get("practitioner_channel") or "email"
    email = appt.get("practitioner_email") or practice.get("email")
    phone = appt.get("practitioner_phone") or practice.get("phone_e164")
    allowed = set(plans.allowed_channels(practice))
    for ch in [pref, "email", "sms"]:
        if ch not in allowed:
            continue
        if ch == "email" and email:
            return "email", email, "ok"
        if ch in ("sms", "whatsapp") and phone:
            return ch, phone, "ok"
    return None, None, "aucune coordonnée praticien"


# ---------------------------------------------------------------- textes

def render(kind: str, recipient: str, ctx: dict) -> str:
    a, pr, pat = ctx["appt"], ctx["practice"], ctx["patient"]
    when = fmt_when(ctx)
    who = a["patient_name"]
    reply = " Répondez OUI pour confirmer ou ANNULER pour annuler."
    if recipient == "patient":
        if kind == "confirmation":
            return (f"{pr['name']} : votre rendez-vous ({a.get('reason') or 'consultation'}) est confirmé le {when} avec "
                    f"{a['practitioner']}, {pr['address']}.{reply}")
        if kind.startswith("reminder_"):
            return f"Rappel {pr['name']} : rendez-vous le {when} avec {a['practitioner']}, {pr['address']}.{reply}"
        if kind == "cancellation":
            return (f"{pr['name']} : votre rendez-vous du {when} est annulé. Pour en reprendre un, répondez RDV ou appelez le "
                    f"{phonelib.pretty(pr.get('voip_number')) or pr['phone']}.")
    else:
        if kind == "confirmation":
            return f"[CareAssist] Nouveau RDV : {who} le {when} ({a.get('reason') or 'consultation'}){' — URGENT' if a.get('urgent') else ''}."
        if kind.startswith("reminder_"):
            return f"[CareAssist] Rappel : {who} le {when} ({a.get('reason') or 'consultation'}) avec {a['practitioner']}."
        if kind == "cancellation":
            return f"[CareAssist] RDV annulé : {who} le {when}. Le créneau est de nouveau libre."
    return f"{pr['name']} : {when}"


# ---------------------------------------------------------------- planification

def _insert(conn, **f) -> bool:
    cur = conn.execute(
        "INSERT OR IGNORE INTO notifications(practice_id, appointment_id, patient_id, practitioner_id, recipient_type, kind, channel, "
        "to_addr, body, status, scheduled_for, error, dedupe_key, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f["practice_id"], f.get("appointment_id"), f.get("patient_id"), f.get("practitioner_id"), f["recipient_type"], f["kind"],
         f.get("channel"), f.get("to_addr"), f.get("body"), f.get("status", "scheduled"), f["scheduled_for"], f.get("error"),
         f["dedupe_key"], db.now_iso()))
    return cur.rowcount == 1


def schedule_for_appointment(appt_id: int, now: datetime | None = None) -> list[dict]:
    """Crée (idempotent) les notifications d'un RDV. Renvoie la liste des notifications du RDV."""
    ctx = _context(appt_id)
    if not ctx or ctx["appt"]["status"] == "cancelled":
        return []
    a, pr, pat = ctx["appt"], ctx["practice"], ctx["patient"]
    tz = _tz(pr)
    now_utc = now or utcnow()
    now_l = now_utc.astimezone(tz)
    start_l = appt_local(ctx)
    qs, qe = _hm(pr.get("quiet_start"), "21:00"), _hm(pr.get("quiet_end"), "08:00")
    base = f"a{appt_id}:{a['start']}"
    plan = []  # (recipient, kind, local_time, exempt_quiet)
    if pr.get("notify_on_booking", 1):
        plan.append(("patient", "confirmation", now_l, (a.get("source") or "assistant") in PATIENT_INITIATED))
        if pr.get("notify_practitioner", 1):
            plan.append(("practitioner", "confirmation", now_l, False))
    for m in offsets(pr.get("notify_patient_offsets"), [1440, 120]):
        plan.append(("patient", f"reminder_{m}", start_l - timedelta(minutes=m), False))
    if pr.get("notify_practitioner", 1):
        for m in offsets(pr.get("notify_practitioner_offsets"), [120]):
            plan.append(("practitioner", f"reminder_{m}", start_l - timedelta(minutes=m), False))
    with db.get_conn() as conn:
        for recipient, kind, when, exempt in plan:
            status, error = "scheduled", None
            if kind.startswith("reminder_") and when <= now_l:
                status, error = "skipped", "RDV trop proche : rappel non pertinent"
            elif not exempt:
                adj = adjust_for_quiet(when, start_l, now_l, qs, qe)
                if adj is None:
                    status, error = "skipped", "heures calmes : aucun créneau d'envoi avant le RDV"
                else:
                    when = adj
            if recipient == "patient":
                ch, addr, why = choose_patient_channel(pr, pat)
            else:
                ch, addr, why = choose_practitioner_channel(pr, a)
            _insert(conn, practice_id=pr["id"], appointment_id=appt_id, patient_id=a.get("patient_id"),
                    practitioner_id=a.get("practitioner_id"), recipient_type=recipient, kind=kind, channel=ch, to_addr=addr,
                    body=render(kind, recipient, ctx), status=status, error=error,
                    scheduled_for=when.astimezone(timezone.utc).isoformat(), dedupe_key=f"{base}:{recipient}:{kind}")
        return db.rows(conn.execute("SELECT id, recipient_type, kind, channel, status, scheduled_for FROM notifications "
                                    "WHERE appointment_id=? ORDER BY scheduled_for", (appt_id,)))


def on_booked(appt_id: int) -> list[dict]:
    schedule_for_appointment(appt_id)
    dispatch_due(appointment_id=appt_id)
    with db.get_conn() as conn:
        return db.rows(conn.execute("SELECT id, recipient_type, kind, channel, status, scheduled_for FROM notifications "
                                    "WHERE appointment_id=? ORDER BY scheduled_for", (appt_id,)))


def on_cancelled(appt_id: int, source: str = "assistant", notify: bool = True) -> None:
    with db.get_conn() as conn:
        conn.execute("UPDATE notifications SET status='cancelled', error='RDV annulé' WHERE appointment_id=? AND status='scheduled'",
                     (appt_id,))
    if not notify:
        return
    ctx = _context(appt_id)
    if not ctx:
        return
    a, pr = ctx["appt"], ctx["practice"]
    now_l = utcnow().astimezone(_tz(pr))
    qs, qe = _hm(pr.get("quiet_start"), "21:00"), _hm(pr.get("quiet_end"), "08:00")
    recipients = []
    if pr.get("notify_practitioner", 1):
        recipients.append("practitioner")
    if source not in ("patient",):  # annulation par le cabinet / l'assistante -> on prévient le patient
        recipients.append("patient")
    with db.get_conn() as conn:
        for r in recipients:
            when = now_l
            if in_quiet(now_l, qs, qe) and not (r == "patient" and source in PATIENT_INITIATED):
                when = now_l.replace(hour=qe.hour, minute=qe.minute, second=0)
                if when <= now_l:
                    when += timedelta(days=1)
            ch, addr, _ = choose_patient_channel(pr, ctx["patient"]) if r == "patient" else choose_practitioner_channel(pr, a)
            _insert(conn, practice_id=pr["id"], appointment_id=appt_id, patient_id=a.get("patient_id"),
                    practitioner_id=a.get("practitioner_id"), recipient_type=r, kind="cancellation", channel=ch, to_addr=addr,
                    body=render("cancellation", r, ctx), scheduled_for=when.astimezone(timezone.utc).isoformat(),
                    dedupe_key=f"a{appt_id}:{a['start']}:{r}:cancellation")
    dispatch_due(appointment_id=appt_id)


# ---------------------------------------------------------------- envoi

def dispatch_due(now: datetime | None = None, appointment_id: int | None = None, limit: int = 500,
                 practice_id: int | None = None) -> dict:
    """Envoie les notifications échues. Idempotent et sûr en concurrence (réclamation atomique de chaque ligne)."""
    now_utc = now or utcnow()
    q = "SELECT id FROM notifications WHERE status='scheduled' AND scheduled_for <= ?"
    params: list = [now_utc.isoformat()]
    if appointment_id:
        q += " AND appointment_id=?"
        params.append(appointment_id)
    if practice_id:
        q += " AND practice_id=?"
        params.append(practice_id)
    q += " ORDER BY scheduled_for LIMIT ?"
    params.append(limit)
    with db.get_conn() as conn:
        ids = [r[0] for r in conn.execute(q, params).fetchall()]
    stats = {"due": len(ids), "sent": 0, "mock_sent": 0, "failed": 0, "skipped": 0, "deferred": 0, "cancelled": 0}
    for nid in ids:
        with db.get_conn() as conn:
            if conn.execute("UPDATE notifications SET status='sending' WHERE id=? AND status='scheduled'", (nid,)).rowcount != 1:
                continue  # déjà pris par un autre worker
            n = dict(conn.execute("SELECT * FROM notifications WHERE id=?", (nid,)).fetchone())
        result = _send_one(n, now_utc)
        stats[result] = stats.get(result, 0) + 1
    return stats


def _finish(nid: int, status: str, **f) -> None:
    sets = ", ".join(f"{k}=?" for k in f)
    with db.get_conn() as conn:
        conn.execute(f"UPDATE notifications SET status=?{', ' + sets if sets else ''} WHERE id=?", (status, *f.values(), nid))


def _send_one(n: dict, now_utc: datetime) -> str:
    with db.get_conn() as conn:
        pr = dict(conn.execute("SELECT * FROM practices WHERE id=?", (n["practice_id"],)).fetchone())
    ctx = _context(n["appointment_id"]) if n.get("appointment_id") else None
    tz = _tz(pr)
    now_l = now_utc.astimezone(tz)
    qs, qe = _hm(pr.get("quiet_start"), "21:00"), _hm(pr.get("quiet_end"), "08:00")
    if ctx:
        a = ctx["appt"]
        if a["status"] == "cancelled" and n["kind"] != "cancellation":
            _finish(n["id"], "cancelled", error="RDV annulé")
            return "cancelled"
        start_l = appt_local(ctx)
        if n["kind"].startswith("reminder_") and start_l <= now_l:
            _finish(n["id"], "skipped", error="RDV déjà passé")
            return "skipped"
        exempt = n["kind"] in ("confirmation", "cancellation") and n["recipient_type"] == "patient" and \
            (a.get("source") or "assistant") in PATIENT_INITIATED
        if not exempt and in_quiet(now_l, qs, qe):
            adj = adjust_for_quiet(now_l, start_l, now_l, qs, qe)
            if adj is None or adj <= now_l:
                _finish(n["id"], "skipped", error="heures calmes")
                return "skipped"
            _finish(n["id"], "scheduled", scheduled_for=adj.astimezone(timezone.utc).isoformat())
            return "deferred"
        if n["recipient_type"] == "patient":
            ch, addr, why = choose_patient_channel(pr, ctx["patient"])
        else:
            ch, addr, why = choose_practitioner_channel(pr, a)
        body = render(n["kind"], n["recipient_type"], ctx)
    else:  # notification hors RDV (ex. proposition de rappel après appel manqué)
        if in_quiet(now_l, qs, qe):
            nxt = now_l.replace(hour=qe.hour, minute=qe.minute, second=0)
            if nxt <= now_l:
                nxt += timedelta(days=1)
            _finish(n["id"], "scheduled", scheduled_for=nxt.astimezone(timezone.utc).isoformat())
            return "deferred"
        ch, addr, why, body = n.get("channel"), n.get("to_addr"), "ok", n.get("body") or ""
    if not ch or not addr:
        _finish(n["id"], "skipped", error=why)
        return "skipped"
    res = messaging.send(pr, ch, addr, body, patient_id=n.get("patient_id"),
                         subject=f"{pr['name']} — rendez-vous" if ch == "email" else None)
    _finish(n["id"], res["status"], channel=ch, to_addr=addr, body=body, provider=res["provider"],
            provider_message_id=res["provider_message_id"], error=res["error"], sent_at=db.utcnow_iso())
    if res["status"] in ("sent", "mock_sent") and ctx and n["recipient_type"] == "patient" and n["kind"].startswith("reminder_"):
        with db.get_conn() as conn:
            conn.execute("UPDATE appointments SET status='reminded', updated_at=? WHERE id=? AND status='confirmed'",
                         (db.now_iso(), n["appointment_id"]))
    return res["status"] if res["status"] in ("sent", "mock_sent", "failed") else "sent"


# ---------------------------------------------------------------- appels manqués

def missed_call_followup(practice: dict, caller: str | None, reason: str = "missed") -> int | None:
    """SMS automatique proposant un rappel / un RDV après appel manqué ou message vocal (1 par numéro et par jour)."""
    if not practice.get("missed_call_sms", 1):
        return None
    e = phonelib.to_e164(caller, practice.get("country") or "FR", strict=False)
    if not e:
        return None
    from .patients import find_by_phone
    pat = find_by_phone(practice["id"], e, practice.get("country") or "FR")
    if pat and not pat.get("notify_consent"):
        return None
    now_utc = utcnow()
    day = now_utc.astimezone(_tz(practice)).date().isoformat()
    lead = ("Merci pour votre message vocal" if reason == "voicemail" else "Nous n'avons pas pu prendre votre appel")
    body = (f"{practice['name']} : {lead}. Répondez RDV pour être rappelé(e) par le cabinet, ou écrivez-nous ici pour "
            f"prendre rendez-vous. En cas d'urgence vitale, appelez les secours.")
    prof = get_country(practice.get("country"))
    em = prof.get("emergency") or {}
    if em.get("samu"):
        body = body.replace("appelez les secours", f"appelez le {em['samu']}")
    channel = "whatsapp" if prof["preferred_channels"][0] == "whatsapp" and messaging.provider_configured("twilio") else "sms"
    with db.get_conn() as conn:
        ok = _insert(conn, practice_id=practice["id"], patient_id=pat["id"] if pat else None, recipient_type="patient",
                     kind="callback_offer", channel=channel, to_addr=e, body=body,
                     scheduled_for=now_utc.isoformat(), dedupe_key=f"missed:{practice['id']}:{e}:{day}")
        nid = conn.execute("SELECT id FROM notifications WHERE dedupe_key=?", (f"missed:{practice['id']}:{e}:{day}",)).fetchone()[0]
    if ok:
        dispatch_due()
        with db.get_conn() as conn:
            conn.execute("UPDATE calls SET callback_sms_sent=1 WHERE practice_id=? AND from_number=? AND callback_sms_sent=0",
                         (practice["id"], e))
    return nid


# ---------------------------------------------------------------- réponses patient (SMS / WhatsApp entrants)

def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper().strip()
    return re.sub(r"[^A-Z0-9' ]+", " ", t).strip()


def parse_reply(text: str) -> str | None:
    t = _norm(text)
    if re.match(r"^(STOP|STOPSMS|DESABONNER|UNSUBSCRIBE)\b", t):
        return "stop"
    if re.match(r"^(OUI|O|YES|Y|OK|CONFIRME|CONFIRMER|CONFIRMATION|JE CONFIRME|D'ACCORD|DACCORD)\b", t):
        return "confirm"
    if re.match(r"^(NON|NO|N|ANNULER|ANNULE|ANNULATION|ANNULEZ|CANCEL|JE ANNULE|J'ANNULE)\b", t):
        return "cancel"
    if re.match(r"^(RDV|RAPPEL|RAPPELEZ|RAPPELER|CALLBACK|RENDEZ VOUS)\b", t):
        return "callback"
    return None


def handle_inbound(practice: dict, from_raw: str, text: str, channel: str = "sms", provider: str = "mock") -> dict:
    """Traite un SMS/WhatsApp entrant. Renvoie {"action", "reply", "appointment_id"}. Le message entrant est journalisé ;
    la réponse est journalisée par l'appelant (TwiML) ou envoyée via messaging.send."""
    from . import booking
    from .patients import find_by_phone
    country = practice.get("country") or "FR"
    e = phonelib.to_e164(from_raw, country, strict=False) or (from_raw or "").replace("whatsapp:", "")
    pat = find_by_phone(practice["id"], e, country)
    messaging.log_message(practice["id"], pat["id"] if pat else None, "inbound", channel, provider, e,
                          practice.get("voip_number"), text, "received")
    action = parse_reply(text)
    upcoming = booking.upcoming_for_phone(e, practice_id=practice["id"])
    appt = upcoming[0] if upcoming else None
    phone_disp = phonelib.pretty(practice.get("voip_number")) or practice["phone"]
    if action == "stop":
        if pat:
            with db.get_conn() as conn:
                conn.execute("UPDATE patients SET notify_consent=0, updated_at=? WHERE id=? AND practice_id=?",
                             (db.now_iso(), pat["id"], practice["id"]))
        return {"action": "stop", "appointment_id": None,
                "reply": f"{practice['name']} : vous ne recevrez plus de messages automatiques. Votre rendez-vous éventuel est maintenu."}
    if action == "confirm" and appt:
        with db.get_conn() as conn:
            conn.execute("UPDATE appointments SET status='confirmed', patient_confirmed_at=?, updated_at=? WHERE id=? AND practice_id=?",
                         (db.now_iso(), db.now_iso(), appt["id"], practice["id"]))
        return {"action": "confirmed", "appointment_id": appt["id"],
                "reply": f"{practice['name']} : merci, votre rendez-vous {appt['label']} est bien confirmé. À bientôt."}
    if action == "cancel" and appt:
        booking.cancel(appt["id"], practice_id=practice["id"], source="patient")
        return {"action": "cancelled", "appointment_id": appt["id"],
                "reply": (f"{practice['name']} : votre rendez-vous {appt['label']} est annulé. Pour en reprendre un, répondez RDV "
                          f"ou appelez le {phone_disp}.")}
    if action in ("confirm", "cancel") and not appt:
        return {"action": "no_appointment", "appointment_id": None,
                "reply": f"{practice['name']} : nous ne trouvons aucun rendez-vous à venir pour ce numéro. Répondez RDV pour être rappelé(e)."}
    if action == "callback":
        with db.get_conn() as conn:
            _insert(conn, practice_id=practice["id"], patient_id=pat["id"] if pat else None, recipient_type="practitioner",
                    kind="callback_request", channel=None, to_addr=None, status="skipped",
                    body=f"Demande de rappel de {e}", error="à traiter par le secrétariat (tableau de bord)",
                    scheduled_for=utcnow().isoformat(), dedupe_key=f"cbreq:{practice['id']}:{e}:{utcnow().date().isoformat()}")
        return {"action": "callback_request", "appointment_id": None,
                "reply": f"{practice['name']} : c'est noté, le cabinet vous rappelle dès que possible aux heures d'ouverture."}
    # texte libre : l'assistante IA répond par SMS/WhatsApp (même moteur que le téléphone et le chat)
    from .engine import process_message
    res = process_message(text, session_id=f"{channel}-{practice['id']}-{e}", practice=practice["id"], channel=channel)
    return {"action": "assistant", "appointment_id": (res.get("appointment") or {}).get("id"), "reply": res["reply"]}
