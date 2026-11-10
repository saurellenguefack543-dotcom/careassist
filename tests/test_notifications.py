"""Rappels : planification (J-1, H-2), fuseaux, heures calmes, idempotence, réponses patient."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import booking, db, notifications


def _book(practice_slug, days=3, hour=None, phone="06 12 34 56 78", name="Marie Test", source="assistant"):
    p = db.get_practice(practice_slug)
    for extra in range(7):  # premier jour ouvré à partir de J+days ayant un créneau libre à l'heure voulue
        day = db.now(p["timezone"]).date() + timedelta(days=days + extra)
        slots = [s for s in booking.find_slots(day=day, practice_id=p["id"], limit=80) if hour is None or s["start"][11:13] == f"{hour:02d}"]
        if slots:
            return p, booking.book(slots[0]["id"], name, phone, "Contrôle", source=source)
    raise AssertionError("aucun créneau")


def _utc_start(p, a):
    return datetime.fromisoformat(a["start"]).replace(tzinfo=ZoneInfo(p["timezone"])).astimezone(timezone.utc)


def _notifs(appt_id):
    with db.get_conn() as conn:
        return db.rows(conn.execute("SELECT * FROM notifications WHERE appointment_id=? ORDER BY id", (appt_id,)))


def test_booking_schedules_patient_and_practitioner_reminders(client):
    p, a = _book("dentiste", days=3, hour=10)
    ns = _notifs(a["id"])
    kinds = {(n["recipient_type"], n["kind"]) for n in ns}
    assert {("patient", "confirmation"), ("patient", "reminder_1440"), ("patient", "reminder_120"),
            ("practitioner", "confirmation"), ("practitioner", "reminder_120")} <= kinds
    conf = next(n for n in ns if n["kind"] == "confirmation" and n["recipient_type"] == "patient")
    assert conf["status"] == "mock_sent" and conf["channel"] == "sms" and conf["to_addr"] == "+33612345678"
    # H-2 en UTC = heure locale Paris - 2 h
    start = datetime.fromisoformat(a["start"]).replace(tzinfo=ZoneInfo("Europe/Paris"))
    h2 = next(n for n in ns if n["kind"] == "reminder_120" and n["recipient_type"] == "patient")
    assert datetime.fromisoformat(h2["scheduled_for"]) == (start - timedelta(hours=2)).astimezone(timezone.utc)
    # fiche patient créée automatiquement
    assert a["patient_id"]


def test_timezone_dakar(client):
    p, a = _book("dakar-almadies", days=3, hour=10, phone="77 123 45 67", name="Awa Diallo")
    h2 = next(n for n in _notifs(a["id"]) if n["kind"] == "reminder_120" and n["recipient_type"] == "patient")
    start = datetime.fromisoformat(a["start"]).replace(tzinfo=ZoneInfo("Africa/Dakar"))
    assert datetime.fromisoformat(h2["scheduled_for"]) == (start - timedelta(hours=2)).astimezone(timezone.utc)
    assert h2["to_addr"] == "+221771234567" and h2["channel"] == "whatsapp"  # canal préféré au Sénégal


def test_quiet_hours_shift():
    tz = ZoneInfo("Europe/Paris")
    q = (notifications.time(21, 0), notifications.time(8, 0))
    appt = datetime(2030, 1, 10, 9, 0, tzinfo=tz)
    now = datetime(2030, 1, 8, 12, 0, tzinfo=tz)
    # H-2 à 07:00 -> décalé à 08:00 (encore 1 h avant le RDV)
    assert notifications.adjust_for_quiet(appt - timedelta(hours=2), appt, now, *q).hour == 8
    # J-1 à 09:00 -> hors heures calmes, inchangé
    assert notifications.adjust_for_quiet(appt - timedelta(days=1), appt, now, *q) == appt - timedelta(days=1)
    # RDV à 08:15, H-2 à 06:15 -> 08:00 trop tard (<30 min) -> avancé la veille à 20:55
    appt2 = datetime(2030, 1, 10, 8, 15, tzinfo=tz)
    adj = notifications.adjust_for_quiet(appt2 - timedelta(hours=2), appt2, now, *q)
    assert (adj.day, adj.hour, adj.minute) == (9, 20, 55)


def test_dispatch_is_idempotent(client):
    p, a = _book("dentiste", days=4, hour=11)
    before = len(_notifs(a["id"]))
    assert notifications.schedule_for_appointment(a["id"]) and len(_notifs(a["id"])) == before  # pas de doublon
    future = _utc_start(p, a) - timedelta(minutes=30)
    s1 = notifications.dispatch_due(now=future)
    sent_ids = {n["id"] for n in _notifs(a["id"]) if n["status"] in ("sent", "mock_sent")}
    s2 = notifications.dispatch_due(now=future)
    assert s2["due"] == 0 and {n["id"] for n in _notifs(a["id"]) if n["status"] in ("sent", "mock_sent")} == sent_ids
    with db.get_conn() as conn:
        n_msgs = conn.execute("SELECT COUNT(*) FROM channel_messages WHERE to_addr='+33612345678'").fetchone()[0]
    notifications.dispatch_due(now=future)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM channel_messages WHERE to_addr='+33612345678'").fetchone()[0] == n_msgs
    assert s1["due"] >= 1
    with db.get_conn() as conn:
        assert conn.execute("SELECT status FROM appointments WHERE id=?", (a["id"],)).fetchone()[0] == "reminded"


def test_cancel_cancels_pending_reminders(client):
    p, a = _book("dentiste", days=5, hour=10)
    booking.cancel(a["id"])
    ns = _notifs(a["id"])
    assert not [n for n in ns if n["status"] == "scheduled" and n["kind"].startswith("reminder_")]
    assert any(n["kind"] == "cancellation" for n in ns)


def test_no_consent_no_patient_message(client):
    p, a = _book("dentiste", days=3, hour=15, phone="06 98 76 54 32")
    with db.get_conn() as conn:
        conn.execute("UPDATE patients SET notify_consent=0 WHERE id=?", (a["patient_id"],))
    notifications.dispatch_due(now=_utc_start(p, a) - timedelta(hours=23))
    j1 = next(n for n in _notifs(a["id"]) if n["kind"] == "reminder_1440" and n["recipient_type"] == "patient")
    assert j1["status"] == "skipped" and "consentement" in j1["error"]


@pytest.mark.parametrize("text,expected", [
    ("OUI", "confirm"), ("oui merci", "confirm"), ("Yes", "confirm"), ("NON", "cancel"), ("Annuler svp", "cancel"),
    ("annulé", "cancel"), ("STOP", "stop"), ("RDV", "callback"), ("Bonjour, à quelle heure ouvrez-vous ?", None),
])
def test_parse_reply(text, expected):
    assert notifications.parse_reply(text) == expected


def test_inbound_sms_confirm_then_cancel(client):
    p, a = _book("dentiste", days=2, hour=10, phone="06 11 22 33 44")
    r = client.post("/twilio/sms", data={"From": "+33611223344", "To": "+33199000001", "Body": "OUI", "MessageSid": "SM1"})
    assert r.status_code == 200 and "<Message>" in r.text and "confirmé" in r.text
    with db.get_conn() as conn:
        assert conn.execute("SELECT patient_confirmed_at FROM appointments WHERE id=?", (a["id"],)).fetchone()[0]
    r = client.post("/twilio/sms", data={"From": "whatsapp:+33611223344", "To": "whatsapp:+33199000001", "Body": "ANNULER"})
    assert "annulé" in r.text
    with db.get_conn() as conn:
        assert conn.execute("SELECT status FROM appointments WHERE id=?", (a["id"],)).fetchone()[0] == "cancelled"
        inbound = conn.execute("SELECT COUNT(*) FROM channel_messages WHERE direction='inbound' AND from_addr='+33611223344'").fetchone()[0]
    assert inbound == 2


def test_inbound_free_text_goes_to_assistant(client):
    r = client.post("/twilio/sms", data={"From": "+33655555555", "To": "+33199000001", "Body": "Quels sont vos horaires ?"})
    assert "lundi" in r.text


def test_inbound_stop_revokes_consent(client):
    p, a = _book("dentiste", days=2, hour=11, phone="06 44 44 44 44")
    client.post("/twilio/sms", data={"From": "+33644444444", "To": "+33199000001", "Body": "STOP"})
    with db.get_conn() as conn:
        assert conn.execute("SELECT notify_consent FROM patients WHERE id=?", (a["patient_id"],)).fetchone()[0] == 0
