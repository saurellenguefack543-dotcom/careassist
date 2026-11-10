"""Base patients d'un cabinet. Toutes les fonctions prennent `practice_id` : aucune requête hors cabinet."""
from __future__ import annotations

from . import db
from . import phone as phonelib

CHANNELS = ("auto", "sms", "whatsapp", "email", "none")


def split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if len(parts) <= 1:
        return "", (parts[0] if parts else "Patient")
    return " ".join(parts[:-1]), parts[-1]


def find_by_phone(practice_id: int, raw_phone: str, country: str = "FR") -> dict | None:
    e = phonelib.to_e164(raw_phone, country, strict=False)
    if not e:
        return None
    with db.get_conn() as conn:
        r = conn.execute("SELECT * FROM patients WHERE practice_id=? AND phone_e164=? ORDER BY id LIMIT 1",
                         (practice_id, e)).fetchone()
    return dict(r) if r else None


def upsert_from_booking(practice_id: int, full_name: str, raw_phone: str, country: str = "FR") -> int:
    """Rattache une réservation (assistant, téléphone, chat) à une fiche patient, créée au besoin.

    Consentement aux rappels : 1 par défaut pour les rappels liés au rendez-vous demandé (le patient a donné son
    numéro pour ce rendez-vous) ; il peut répondre STOP à tout moment. Adapter selon votre politique RGPD.
    """
    existing = find_by_phone(practice_id, raw_phone, country)
    if existing:
        return existing["id"]
    first, last = split_name(full_name)
    e = phonelib.to_e164(raw_phone, country, strict=False)
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO patients(practice_id, first_name, last_name, phone_e164, preferred_channel, notify_consent, source, "
            "created_at, updated_at) VALUES (?,?,?,?, 'auto', 1, 'booking', ?, ?)",
            (practice_id, first, last, e, db.now_iso(), db.now_iso()),
        )
        return cur.lastrowid


def get(practice_id: int, patient_id: int) -> dict | None:
    with db.get_conn() as conn:
        r = conn.execute("SELECT * FROM patients WHERE id=? AND practice_id=?", (patient_id, practice_id)).fetchone()
    return dict(r) if r else None


def display_name(p: dict | None) -> str:
    if not p:
        return ""
    return " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
