"""Forfaits CareAssist : Gratuit, essai Premium 14 jours, Premium.

Limites du plan Gratuit (à vie, sans carte) :
  - 30 conversations IA par mois (appels vocaux + discussions chat)
  - 1 utilisateur (le titulaire)
  - rappels par e-mail uniquement (pas de SMS ni WhatsApp)
  - agenda et fiches patients (fonctions de base)
  - pas de numéro VoIP dédié
  - pas de sauvegardes automatiques
  - badge « Propulsé par CareAssist »

Le plan Premium lève toutes ces limites (appels et messages illimités, SMS / WhatsApp,
plusieurs utilisateurs, numéro VoIP, sauvegardes, support prioritaire) au tarif régional
en vigueur (299 €/mois en Europe, devises locales en Afrique).

Tout nouveau cabinet démarre en essai Premium 14 jours, sans carte. À l'échéance,
il bascule automatiquement sur Gratuit tant qu'il ne s'abonne pas. Les cabinets de
démonstration restent en Premium.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import config, db

log = logging.getLogger("careassist.plans")

TRIAL_DAYS = 14
TRIAL_REMINDER_DAYS = 3
FREE_AI_CONVERSATIONS_PER_MONTH = 30
FREE_USERS = 1
FREE_CHANNELS = ("email",)

PLAN_FREE = "free"
PLAN_PREMIUM = "premium"

STATUS_TRIALING = "trialing"
STATUS_ACTIVE = "active"
STATUS_FREE = "free"
STATUS_CANCELLED = "cancelled"


def trial_end_iso(from_dt: datetime | None = None) -> str:
    start = from_dt or datetime.now(timezone.utc)
    return (start + timedelta(days=TRIAL_DAYS)).replace(microsecond=0).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        raw = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def is_demo(practice: dict) -> bool:
    return bool(practice.get("is_demo"))


def trial_active(practice: dict, now: datetime | None = None) -> bool:
    if is_demo(practice):
        return False
    status = practice.get("subscription_status") or ""
    if status == STATUS_ACTIVE or status == STATUS_FREE:
        return False
    ends = _parse_iso(practice.get("trial_ends_at"))
    if not ends:
        return False
    return ends > (now or datetime.now(timezone.utc))


def effective_plan(practice: dict, now: datetime | None = None) -> str:
    if is_demo(practice) or practice.get("subscription_status") == STATUS_ACTIVE:
        return PLAN_PREMIUM
    if trial_active(practice, now):
        return PLAN_PREMIUM
    return PLAN_FREE


def is_premium(practice: dict, now: datetime | None = None) -> bool:
    return effective_plan(practice, now) == PLAN_PREMIUM


def trial_days_left(practice: dict, now: datetime | None = None) -> int | None:
    if not trial_active(practice, now):
        return None
    ends = _parse_iso(practice["trial_ends_at"])
    delta = ends - (now or datetime.now(timezone.utc))
    return max(0, delta.days + (1 if delta.seconds or delta.microseconds else 0))


def month_start_iso(now: datetime | None = None) -> str:
    n = now or datetime.now(timezone.utc)
    return n.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def ai_usage_this_month(practice_id: int, now: datetime | None = None) -> int:
    start = month_start_iso(now)
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE practice_id=? AND created_at>=?",
            (practice_id, start),
        ).fetchone()[0]


def check_ai_quota(practice: dict, now: datetime | None = None) -> dict:
    if is_premium(practice, now):
        return {"allowed": True, "used": ai_usage_this_month(practice["id"], now), "limit": None, "plan": PLAN_PREMIUM}
    used = ai_usage_this_month(practice["id"], now)
    limit = FREE_AI_CONVERSATIONS_PER_MONTH
    return {"allowed": used < limit, "used": used, "limit": limit, "plan": PLAN_FREE}


def quota_reached_reply(practice: dict) -> str:
    name = practice.get("name") or "cabinet"
    return (
        f"Le {name} a atteint la limite du plan Gratuit ({FREE_AI_CONVERSATIONS_PER_MONTH} conversations IA ce mois-ci). "
        "Pour continuer à être joint 24h/24, le titulaire peut passer au plan Premium depuis son espace cabinet. "
        "En cas d'urgence, appelez les secours de votre pays (15 ou 112 en France)."
    )


def user_count(practice_id: int) -> int:
    with db.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users WHERE practice_id=? AND active=1", (practice_id,)).fetchone()[0]


def can_add_user(practice: dict) -> tuple[bool, str]:
    if is_premium(practice):
        return True, "ok"
    if user_count(practice["id"]) >= FREE_USERS:
        return False, "Le plan Gratuit est limité à un utilisateur (le titulaire). Passez au plan Premium pour ajouter des comptes."
    return True, "ok"


def allowed_channels(practice: dict) -> list[str]:
    if is_premium(practice):
        return ["sms", "whatsapp", "email"]
    return list(FREE_CHANNELS)


def channel_allowed(practice: dict, channel: str | None) -> bool:
    if not channel:
        return False
    return channel in allowed_channels(practice)


def can_use_voip(practice: dict) -> bool:
    return is_premium(practice)


def can_auto_backup(practice: dict) -> bool:
    return is_premium(practice)


def apply_premium(practice_id: int) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE practices SET plan=?, subscription_status=?, trial_ends_at=NULL WHERE id=?",
            (PLAN_PREMIUM, STATUS_ACTIVE, practice_id),
        )


def apply_free(practice_id: int) -> None:
    with db.get_conn() as conn:
        row = conn.execute("SELECT is_demo FROM practices WHERE id=?", (practice_id,)).fetchone()
        if row and row["is_demo"]:
            return
        conn.execute(
            "UPDATE practices SET plan=?, subscription_status=?, trial_ends_at=NULL WHERE id=?",
            (PLAN_FREE, STATUS_FREE, practice_id),
        )


def start_trial(practice_id: int, from_dt: datetime | None = None) -> str:
    ends = trial_end_iso(from_dt)
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE practices SET plan=?, subscription_status=?, trial_ends_at=?, trial_notice_3d=0, trial_notice_end=0 WHERE id=? AND is_demo=0",
            (PLAN_PREMIUM, STATUS_TRIALING, ends, practice_id),
        )
    return ends


def public_plans() -> dict:
    return {
        "trial_days": TRIAL_DAYS,
        "free": {
            "key": PLAN_FREE,
            "label": "Gratuit",
            "label_en": "Free",
            "price": 0,
            "ai_conversations_per_month": FREE_AI_CONVERSATIONS_PER_MONTH,
            "users": FREE_USERS,
            "channels": list(FREE_CHANNELS),
            "voip": False,
            "backups": False,
            "badge": "Propulsé par CareAssist",
            "features_fr": [
                f"{FREE_AI_CONVERSATIONS_PER_MONTH} conversations IA par mois (appels ou chat)",
                "1 utilisateur (le titulaire)",
                "Rappels par e-mail uniquement",
                "Agenda et fiches patients",
                "Badge « Propulsé par CareAssist »",
            ],
            "features_en": [
                f"{FREE_AI_CONVERSATIONS_PER_MONTH} AI conversations per month (calls or chat)",
                "1 user (the owner)",
                "Email reminders only",
                "Calendar and patient records",
                "“Powered by CareAssist” badge",
            ],
        },
        "premium": {
            "key": PLAN_PREMIUM,
            "label": "Premium",
            "label_en": "Premium",
            "features_fr": [
                "Appels et messages IA illimités",
                "SMS, WhatsApp et e-mail",
                "Plusieurs utilisateurs et rôles",
                "Numéro VoIP dédié",
                "Sauvegardes automatiques",
                "Support prioritaire",
            ],
            "features_en": [
                "Unlimited AI calls and messages",
                "SMS, WhatsApp and email",
                "Multiple users and roles",
                "Dedicated VoIP number",
                "Automatic backups",
                "Priority support",
            ],
        },
    }


def plan_payload(practice: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    plan = effective_plan(practice, now)
    days = trial_days_left(practice, now)
    usage = check_ai_quota(practice, now)
    return {
        "plan": plan,
        "subscription_status": practice.get("subscription_status") or STATUS_FREE,
        "trial_ends_at": practice.get("trial_ends_at"),
        "trial_days_left": days,
        "trialing": trial_active(practice, now),
        "is_demo": is_demo(practice),
        "limits": public_plans()["free"] if plan == PLAN_FREE else None,
        "usage": usage,
        "badge": plan == PLAN_FREE,
    }


def _owner_email(practice: dict) -> str | None:
    email = practice.get("email")
    if email:
        return email
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT email FROM users WHERE practice_id=? AND role='owner' AND active=1 ORDER BY id LIMIT 1",
            (practice["id"],),
        ).fetchone()
    return row["email"] if row else None


def _send_trial_email(practice: dict, kind: str) -> bool:
    from . import messaging
    to = _owner_email(practice)
    if not to:
        log.warning("essai %s : pas d'e-mail pour le cabinet %s", kind, practice.get("slug") or practice["id"])
        return False
    name = practice.get("name") or "votre cabinet"
    if kind == "3d":
        body = (
            f"Bonjour,\n\nL'essai Premium de {name} se termine dans {TRIAL_REMINDER_DAYS} jours. "
            f"Sans abonnement, le cabinet basculera automatiquement sur le plan Gratuit "
            f"({FREE_AI_CONVERSATIONS_PER_MONTH} conversations IA par mois, rappels par e-mail, 1 utilisateur).\n\n"
            f"Pour rester en Premium (appels illimités, SMS/WhatsApp, numéro VoIP, plusieurs utilisateurs), "
            f"rendez-vous dans votre espace cabinet : {config.SITE_URL}/espace\n\n"
            f"— CareAssist\n{config.CONTACT_EMAIL}"
        )
    else:
        body = (
            f"Bonjour,\n\nL'essai Premium de {name} est arrivé à son terme. "
            f"Le cabinet est désormais sur le plan Gratuit. Vous pouvez passer à Premium à tout moment "
            f"depuis votre espace : {config.SITE_URL}/espace\n\n— CareAssist\n{config.CONTACT_EMAIL}"
        )
    res = messaging.send(practice, "email", to, body)
    return res.get("status") in ("sent", "mock_sent")


def process_trials(now: datetime | None = None) -> dict:
    """Envoie les rappels d'essai et bascule les essais échus sur le plan Gratuit. Idempotent."""
    now = now or datetime.now(timezone.utc)
    stats = {"reminded": 0, "expired": 0, "emails": 0, "skipped_demo": 0}
    with db.get_conn() as conn:
        rows = db.rows(conn.execute(
            "SELECT * FROM practices WHERE is_demo=0 AND subscription_status=? AND trial_ends_at IS NOT NULL",
            (STATUS_TRIALING,),
        ))
    reminder_from = now + timedelta(days=TRIAL_REMINDER_DAYS)
    for p in rows:
        ends = _parse_iso(p.get("trial_ends_at"))
        if not ends:
            continue
        if ends <= now:
            apply_free(p["id"])
            sent = False
            if not p.get("trial_notice_end"):
                sent = _send_trial_email(p, "end")
                with db.get_conn() as conn:
                    conn.execute("UPDATE practices SET trial_notice_end=1 WHERE id=?", (p["id"],))
            stats["expired"] += 1
            if sent:
                stats["emails"] += 1
            continue
        # rappel J-3 : la date de fin tombe dans les 3 prochains jours (inclus)
        if ends <= reminder_from and not p.get("trial_notice_3d"):
            if _send_trial_email(p, "3d"):
                stats["emails"] += 1
            with db.get_conn() as conn:
                conn.execute("UPDATE practices SET trial_notice_3d=1 WHERE id=?", (p["id"],))
            stats["reminded"] += 1
    return stats


def activate_subscription_for_email(email: str, practice_id: int | None = None) -> int | None:
    """Passe un cabinet en Premium après un paiement réussi. Renvoie l'id du cabinet, ou None."""
    email = (email or "").lower().strip()
    with db.get_conn() as conn:
        row = None
        if practice_id:
            row = conn.execute("SELECT id FROM practices WHERE id=?", (practice_id,)).fetchone()
        if not row and email:
            row = conn.execute("SELECT id FROM practices WHERE lower(email)=?", (email,)).fetchone()
        if not row and email:
            row = conn.execute(
                "SELECT practice_id AS id FROM users WHERE lower(email)=? AND role='owner'", (email,)
            ).fetchone()
        if not row:
            return None
        pid = row["id"]
    apply_premium(pid)
    return pid


def backfill_existing(conn) -> None:
    """Appelé une seule fois, quand les colonnes de forfait viennent d'être créées."""
    ends = trial_end_iso()
    conn.execute(
        "UPDATE practices SET plan=?, subscription_status=?, trial_ends_at=NULL WHERE is_demo=1",
        (PLAN_PREMIUM, STATUS_ACTIVE),
    )
    conn.execute(
        "UPDATE practices SET plan=?, subscription_status=?, trial_ends_at=? WHERE is_demo=0",
        (PLAN_PREMIUM, STATUS_TRIALING, ends),
    )
