"""Annuaire public des cabinets : validation, publication automatique, données publiques uniquement."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from . import config, db

log = logging.getLogger("careassist.directory")

STATUS_PENDING = "pending"
STATUS_PUBLISHED = "published"
STATUS_REJECTED = "rejected"
AUTO_PUBLISH_HOURS = 48

PUBLIC_FIELDS = (
    "id", "slug", "name", "specialty", "address", "city", "country", "phone", "email",
    "hours", "access", "listing_status", "published_at", "directory_visible", "logo_path",
    "timezone", "language",
)


def infer_city(address: str | None, fallback: str = "") -> str:
    if not address:
        return fallback
    part = address.split(",")[-1].strip()
    part = re.sub(r"^\d{4,5}\s+", "", part)
    return part or fallback


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def auto_publish_at(practice: dict) -> datetime | None:
    created = _parse_iso(practice.get("created_at"))
    if not created:
        return None
    return created + timedelta(hours=AUTO_PUBLISH_HOURS)


def public_view(practice: dict, *, include_pending: bool = False) -> dict:
    """Champs publics uniquement (jamais de patients, ni de données internes)."""
    from .specialties import get_specialty
    from .countries import get_country
    spec = get_specialty(practice.get("specialty"))
    country = get_country(practice.get("country"))
    return {
        "slug": practice.get("slug"),
        "name": practice.get("name"),
        "specialty": practice.get("specialty"),
        "specialty_label": spec["label"],
        "address": practice.get("address"),
        "city": practice.get("city") or infer_city(practice.get("address")),
        "country": practice.get("country"),
        "country_name": country["name"],
        "phone": practice.get("phone"),
        "email": practice.get("email"),
        "hours": practice.get("hours"),
        "access": practice.get("access") or "",
        "has_logo": bool(practice.get("logo_path")),
        "is_demo": bool(practice.get("is_demo")),
        "published_at": practice.get("published_at"),
    }


def listing_payload(practice: dict) -> dict:
    """État de l'annonce vu depuis l'espace cabinet."""
    due = auto_publish_at(practice)
    return {
        "directory_visible": bool(practice.get("directory_visible", 1)),
        "listing_status": practice.get("listing_status") or STATUS_PENDING,
        "published_at": practice.get("published_at"),
        "created_at": practice.get("created_at"),
        "auto_publish_at": due.isoformat() if due else None,
        "city": practice.get("city") or infer_city(practice.get("address")),
    }


def publish(practice_id: int, *, reason: str = "approved") -> None:
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE practices SET listing_status=?, published_at=COALESCE(published_at, ?) WHERE id=?",
            (STATUS_PUBLISHED, db.now_iso(), practice_id),
        )
    log.info("annuaire : cabinet %s publié (%s)", practice_id, reason)


def reject(practice_id: int) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE practices SET listing_status=?, published_at=NULL WHERE id=?",
            (STATUS_REJECTED, practice_id),
        )


def mark_pending(practice_id: int) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE practices SET listing_status=?, published_at=NULL WHERE id=?",
            (STATUS_PENDING, practice_id),
        )


def list_published(specialty: str | None = None, country: str | None = None, city: str | None = None) -> list[dict]:
    sql = "SELECT * FROM practices WHERE listing_status=? AND directory_visible=1"
    args: list = [STATUS_PUBLISHED]
    if specialty:
        sql += " AND specialty=?"
        args.append(specialty)
    if country:
        sql += " AND country=?"
        args.append(country.upper())
    with db.get_conn() as conn:
        rows = db.rows(conn.execute(sql + " ORDER BY lower(name)", args))
    out = [public_view(r) for r in rows]
    if city:
        needle = city.strip().lower()
        out = [r for r in out if needle in (r.get("city") or "").lower()]
    return out


def get_published(slug: str) -> dict | None:
    p = db.get_practice(slug)
    if not p or p.get("listing_status") != STATUS_PUBLISHED or not p.get("directory_visible"):
        return None
    return public_view(p)


def process_listings(now: datetime | None = None) -> dict:
    """Publie automatiquement les annonces en attente depuis AUTO_PUBLISH_HOURS heures."""
    now = now or datetime.now(timezone.utc)
    stats = {"published": 0}
    with db.get_conn() as conn:
        rows = db.rows(conn.execute(
            "SELECT id, slug, created_at, listing_status FROM practices WHERE listing_status=?",
            (STATUS_PENDING,),
        ))
    for p in rows:
        due = auto_publish_at(p)
        if due and due <= now:
            publish(p["id"], reason="auto-48h")
            stats["published"] += 1
    return stats


def notify_admin_new_listing(practice: dict) -> dict:
    """Préviens l'équipe qu'une annuaire est à valider. Mode démo (mock) si SMTP absent."""
    from . import messaging
    name = practice.get("name") or "Nouveau cabinet"
    due = auto_publish_at(practice)
    when = due.strftime("%d/%m/%Y à %Hh%M") if due else f"sous {AUTO_PUBLISH_HOURS} h"
    body = (
        f"Nouvelle fiche annuaire à valider : {name} ({practice.get('specialty')}, {practice.get('city') or practice.get('country')}).\n\n"
        f"Sans action de votre part, elle sera publiée automatiquement le {when}.\n"
        f"Valider ou refuser : {config.SITE_URL}/admin\n\n"
        f"— CareAssist"
    )
    # messaging.send attend un cabinet ; on passe le cabinet concerné, destinataire = e-mail de la plateforme
    return messaging.send(practice, "email", config.CONTACT_EMAIL, body)
