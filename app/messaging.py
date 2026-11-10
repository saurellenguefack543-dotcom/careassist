"""VoIP cloud — envoi de messages (SMS, WhatsApp, e-mail) avec abstraction de fournisseur.

Fournisseurs (formes d'API d'après les documentations officielles) :
- Twilio      SMS + WhatsApp : POST https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Messages.json
                (form : To, From, Body ; WhatsApp = préfixe « whatsapp:+… »), auth Basic AccountSid:AuthToken.
- Vonage      SMS API : POST https://rest.nexmo.com/sms/json (api_key, api_secret, from, to, text) ;
                succès si messages[0].status == "0".
- Africa's Talking SMS : POST https://api.africastalking.com/version1/messaging (sandbox :
                https://api.sandbox.africastalking.com/version1/messaging), en-têtes apiKey + Accept: application/json,
                form : username, to, message, [from] ; succès si Recipients[0].statusCode == 101.
- SMTP        e-mail (smtplib, STARTTLS).

MODE DÉMO : si les clés d'un fournisseur sont absentes (ou MESSAGING_MODE=mock), aucun appel externe n'est fait :
le message est seulement enregistré en base (statut « mock_sent »).
"""
from __future__ import annotations

import logging
import smtplib
import uuid
from email.message import EmailMessage

import httpx

from . import config, db

log = logging.getLogger("careassist.messaging")

# Marchés historiques d'Africa's Talking (vérifier la couverture exacte auprès du fournisseur)
AT_DEFAULT_COUNTRIES = {"KE", "UG", "TZ", "RW", "MW", "ZM", "NG", "ET"}


def forced_mock() -> bool:
    return config.env("MESSAGING_MODE", "auto").lower() == "mock"


def provider_configured(name: str) -> bool:
    if forced_mock():
        return False
    if name == "twilio":
        return bool(config.env("TWILIO_ACCOUNT_SID") and config.env("TWILIO_AUTH_TOKEN"))
    if name == "vonage":
        return bool(config.env("VONAGE_API_KEY") and config.env("VONAGE_API_SECRET"))
    if name == "africastalking":
        return bool(config.env("AT_USERNAME") and config.env("AT_API_KEY"))
    if name == "smtp":
        return bool(config.env("SMTP_HOST"))
    return False


def voice_provider(practice: dict) -> str:
    p = (practice.get("voip_provider") or "auto").lower()
    if p in ("twilio", "vonage", "africastalking"):
        return p
    return "africastalking" if (practice.get("country") or "FR") in AT_DEFAULT_COUNTRIES else "twilio"


def provider_for(practice: dict, channel: str) -> str:
    if channel == "email":
        return "smtp"
    if channel == "whatsapp":
        return "twilio"  # WhatsApp Business via Twilio (Vonage Messages API possible en extension)
    return voice_provider(practice)


def status_overview() -> dict:
    return {n: ("live" if provider_configured(n) else "mock") for n in ("twilio", "vonage", "africastalking", "smtp")}


# ---------------------------------------------------------------- envois réels

def _twilio_send(to: str, body: str, sender: str | None, whatsapp: bool) -> tuple[str, str]:
    sid, token = config.env("TWILIO_ACCOUNT_SID"), config.env("TWILIO_AUTH_TOKEN")
    data = {"To": ("whatsapp:" + to) if whatsapp else to, "Body": body}
    msid = config.env("TWILIO_MESSAGING_SERVICE_SID")
    if whatsapp:
        data["From"] = "whatsapp:" + (config.env("TWILIO_WHATSAPP_FROM") or sender or "").replace("whatsapp:", "")
    elif msid:
        data["MessagingServiceSid"] = msid
    else:
        data["From"] = sender or config.env("TWILIO_FROM")
    r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data, auth=(sid, token), timeout=15)
    r.raise_for_status()
    j = r.json()
    return "sent", j.get("sid", "")


def _vonage_send(to: str, body: str, sender: str | None) -> tuple[str, str]:
    data = {"api_key": config.env("VONAGE_API_KEY"), "api_secret": config.env("VONAGE_API_SECRET"),
            "from": sender or config.env("VONAGE_FROM", "CareAssist"), "to": to.lstrip("+"), "text": body, "type": "unicode"}
    r = httpx.post("https://rest.nexmo.com/sms/json", data=data, timeout=15)
    r.raise_for_status()
    m = (r.json().get("messages") or [{}])[0]
    if m.get("status") != "0":
        raise RuntimeError(f"Vonage status {m.get('status')}: {m.get('error-text')}")
    return "sent", m.get("message-id", "")


def _at_send(to: str, body: str, sender: str | None) -> tuple[str, str]:
    username = config.env("AT_USERNAME")
    url = ("https://api.sandbox.africastalking.com/version1/messaging" if username == "sandbox"
           else "https://api.africastalking.com/version1/messaging")
    data = {"username": username, "to": to, "message": body}
    if sender or config.env("AT_SENDER_ID"):
        data["from"] = sender or config.env("AT_SENDER_ID")
    r = httpx.post(url, data=data, headers={"apiKey": config.env("AT_API_KEY"), "Accept": "application/json"}, timeout=15)
    r.raise_for_status()
    rec = ((r.json().get("SMSMessageData") or {}).get("Recipients") or [{}])[0]
    if rec.get("statusCode") not in (100, 101, 102):
        raise RuntimeError(f"Africa's Talking: {rec.get('status')}")
    return "sent", rec.get("messageId", "")


def _smtp_send(to: str, body: str, subject: str) -> tuple[str, str]:
    msg = EmailMessage()
    msg["From"] = config.env("SMTP_FROM", config.CONTACT_EMAIL)
    msg["To"] = to
    msg["Subject"] = subject
    mid = f"<{uuid.uuid4().hex}@getcareassist.com>"
    msg["Message-ID"] = mid
    msg.set_content(body)
    port = int(config.env("SMTP_PORT", "587"))
    with smtplib.SMTP(config.env("SMTP_HOST"), port, timeout=15) as s:
        if config.env("SMTP_STARTTLS", "true").lower() in ("1", "true", "yes"):
            s.starttls()
        if config.env("SMTP_USER"):
            s.login(config.env("SMTP_USER"), config.env("SMTP_PASSWORD"))
        s.send_message(msg)
    return "sent", mid


# ---------------------------------------------------------------- API publique

def send(practice: dict, channel: str, to: str, body: str, patient_id: int | None = None,
         subject: str | None = None) -> dict:
    """Envoie (ou simule) un message et l'enregistre dans channel_messages. Ne lève jamais d'exception."""
    provider = provider_for(practice, channel)
    sender = practice.get("voip_number")
    status, mid, error = "mock_sent", "mock-" + uuid.uuid4().hex[:12], None
    demo_guard = bool(practice.get("is_demo")) and config.env("DEMO_LIVE_MESSAGING", "0") != "1"
    if provider_configured(provider) and not demo_guard:
        try:
            if provider == "smtp":
                status, mid = _smtp_send(to, body, subject or f"{practice['name']} — CareAssist")
            elif provider == "twilio":
                status, mid = _twilio_send(to, body, sender, whatsapp=(channel == "whatsapp"))
            elif provider == "vonage":
                status, mid = _vonage_send(to, body, sender)
            elif provider == "africastalking":
                status, mid = _at_send(to, body, sender)
        except Exception as exc:  # journalisé, la notification passe en « failed »
            log.warning("envoi %s/%s échoué : %s", provider, channel, exc)
            status, mid, error = "failed", None, str(exc)[:300]
    log_message(practice["id"], patient_id, "outbound", channel, provider if status != "mock_sent" else f"mock:{provider}",
                sender if channel != "email" else config.env("SMTP_FROM", config.CONTACT_EMAIL), to, body, status, mid, error)
    return {"status": status, "provider": provider, "mode": "mock" if status == "mock_sent" else "live",
            "provider_message_id": mid, "error": error}


def log_message(practice_id, patient_id, direction, channel, provider, from_addr, to_addr, body, status,
                provider_message_id=None, error=None) -> int:
    with db.get_conn() as conn:
        return conn.execute(
            "INSERT INTO channel_messages(practice_id, patient_id, direction, channel, provider, from_addr, to_addr, body, status, "
            "provider_message_id, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (practice_id, patient_id, direction, channel, provider, from_addr, to_addr, body, status, provider_message_id,
             error, db.now_iso()),
        ).lastrowid
