"""VoIP cloud — appels entrants multi-fournisseurs, journal d'appels, messagerie vocale, appels manqués, SMS entrants.

Routage : le cabinet est retrouvé par le NUMÉRO APPELÉ (champ `voip_number` du cabinet, E.164), sinon `?practice=`.

- Twilio          : /twilio/voice (voice.py), /twilio/status, /twilio/dial-status, /twilio/voicemail, /twilio/sms
- Vonage          : /vonage/answer (NCCO), /vonage/input (ASR), /vonage/event, /vonage/inbound-sms
- Africa's Talking: /africastalking/voice (XML Say/GetDigits/Dial/Record), /africastalking/sms
- SIP générique   : voir README (Asterisk/FreeSWITCH -> trunk SIP vers Twilio/Vonage/AT, ou AGI vers /api/chat).
"""
from __future__ import annotations

import json
import uuid
from xml.sax.saxutils import escape

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from . import config, db, messaging, notifications
from . import phone as phonelib
from .countries import get_country
from .engine import process_message, resolve_practice

async def webhook_guard(request: Request):
    """Authentifie les webhooks VoIP entrants.
    - Twilio : signature X-Twilio-Signature (HMAC-SHA1) si TWILIO_VALIDATE=true.
    - Vonage / Africa's Talking : jeton partagé `?wt=` si VOIP_WEBHOOK_TOKEN est défini (à ajouter aux URL de webhook
      configurées chez le fournisseur ; Vonage propose aussi des webhooks signés JWT, à brancher en production).
    + limitation de débit par IP."""
    from . import security
    security.check("inbound", security.client_ip(request))
    path = request.url.path
    if path.startswith("/twilio/"):
        if config.env("TWILIO_VALIDATE", "false").lower() in ("1", "true", "yes"):
            from .voice import twilio_signature_ok
            form = dict((await request.form()).items())
            base = config.env("PUBLIC_BASE_URL").rstrip("/")
            url = (base + path + (("?" + request.url.query) if request.url.query else "")) if base else str(request.url)
            if not twilio_signature_ok(url, form, request.headers.get("X-Twilio-Signature", "")):
                raise HTTPException(403, "Signature Twilio invalide")
        return
    token = config.env("VOIP_WEBHOOK_TOKEN")
    if token and not hmac.compare_digest(request.query_params.get("wt", ""), token):
        raise HTTPException(403, "Jeton de webhook invalide")


router = APIRouter(dependencies=[Depends(webhook_guard)])


# ---------------------------------------------------------------- journal d'appels

def route_practice(to_number: str | None, practice_key: str | None = None) -> dict:
    p = db.practice_by_number(to_number) if to_number else None
    return p or resolve_practice(practice_key)


def start_call(provider: str, call_id: str, practice: dict, from_number: str | None, to_number: str | None) -> dict:
    country = practice.get("country") or "FR"
    frm = phonelib.to_e164(from_number, country, strict=False) or from_number
    to = phonelib.to_e164(to_number, country, strict=False) or to_number
    from .patients import find_by_phone
    pat = find_by_phone(practice["id"], frm, country) if frm else None
    with db.get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO calls(practice_id, patient_id, provider, provider_call_id, direction, from_number, to_number, "
            "status, started_at) VALUES (?,?,?,?, 'inbound', ?,?, 'in-progress', ?)",
            (practice["id"], pat["id"] if pat else None, provider, call_id, frm, to, db.now_iso()))
        return dict(conn.execute("SELECT * FROM calls WHERE provider=? AND provider_call_id=?", (provider, call_id)).fetchone())


def get_call(provider: str, call_id: str) -> dict | None:
    with db.get_conn() as conn:
        r = conn.execute("SELECT * FROM calls WHERE provider=? AND provider_call_id=?", (provider, call_id)).fetchone()
    return dict(r) if r else None


def add_turn(provider: str, call_id: str, user_text: str, assistant_text: str) -> None:
    with db.get_conn() as conn:
        conn.execute("UPDATE calls SET transcript = transcript || ?, turns = turns + 1 WHERE provider=? AND provider_call_id=?",
                     (f"Patient : {user_text}\nAssistante : {assistant_text}\n", provider, call_id))


def set_call(provider: str, call_id: str, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with db.get_conn() as conn:
        conn.execute(f"UPDATE calls SET {sets} WHERE provider=? AND provider_call_id=?", (*fields.values(), provider, call_id))


def end_call(provider: str, call_id: str, provider_status: str, duration: int | None) -> dict | None:
    """Clôture l'appel. Appel sans aucun échange (raccroché, occupé, sans réponse) = manqué -> SMS de rappel."""
    call = get_call(provider, call_id)
    if not call:
        return None
    status = call["status"]
    if status in ("in-progress", "transferring"):
        if provider_status in ("busy", "no-answer", "failed", "canceled") or not call["turns"]:
            status = "missed"
        else:
            status = "transferred" if call["status"] == "transferring" else "completed"
    set_call(provider, call_id, status=status, duration_s=duration, ended_at=db.now_iso())
    if status == "missed" and not call["callback_sms_sent"]:
        practice = db.get_practice(call["practice_id"])
        notifications.missed_call_followup(practice, call["from_number"], "missed")
    return get_call(provider, call_id)


def voicemail_saved(provider: str, call_id: str, recording_url: str | None, text: str | None) -> None:
    call = get_call(provider, call_id)
    if not call:
        return
    fields = {"status": "voicemail"}
    if recording_url:
        fields["recording_url"] = recording_url
    if text:
        fields["voicemail_text"] = text
    set_call(provider, call_id, **fields)
    if not call["callback_sms_sent"]:
        notifications.missed_call_followup(db.get_practice(call["practice_id"]), call["from_number"], "voicemail")


def transfer_number(practice: dict) -> str | None:
    return practice.get("transfer_number") or config.env("HUMAN_TRANSFER_NUMBER") or None


def turn(provider: str, call_id: str, practice: dict, speech: str) -> dict:
    res = process_message(speech, session_id=f"{provider}-{call_id}" if provider != "twilio" else call_id,
                          practice=practice["id"], channel="phone")
    add_turn(provider, call_id, speech, res["reply"])
    return res


def cb_url(path: str, **params) -> str:
    """URL absolue de rappel (Vonage / Africa's Talking), avec le jeton de webhook s'il est configuré."""
    from urllib.parse import urlencode
    if config.env("VOIP_WEBHOOK_TOKEN"):
        params["wt"] = config.env("VOIP_WEBHOOK_TOKEN")
    return config.env("PUBLIC_BASE_URL", "").rstrip("/") + path + ("?" + urlencode(params) if params else "")


def samu_short(practice: dict) -> str:
    em = get_country(practice.get("country")).get("emergency") or {}
    return f"composez le {em['samu']}" if em.get("samu") else "contactez les services d'urgence"


# ---------------------------------------------------------------- Twilio : statut, transfert, messagerie, SMS

def _twiml(*parts: str) -> Response:
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(parts) + "</Response>", media_type="application/xml")


def _say_tw(text: str) -> str:
    return f'<Say language="fr-FR" voice="{escape(config.env("TWILIO_VOICE", "Polly.Lea"))}">{escape(text)}</Say>'


def twilio_record(practice_q: str) -> str:
    cb = escape(f"/twilio/voicemail{practice_q}")
    return (_say_tw("Le cabinet ne peut pas vous répondre pour le moment. Laissez votre nom, votre numéro et votre message "
                    "après le bip ; nous vous rappellerons.")
            + f'<Record maxLength="120" playBeep="true" transcribe="true" transcribeCallback="{cb}" action="{cb}" method="POST"/>')


@router.post("/twilio/status")
async def twilio_status(request: Request):
    """Status callback Twilio (CallStatus, CallDuration) : clôture le journal d'appel ; appel manqué -> SMS."""
    f = dict((await request.form()).items())
    call = end_call("twilio", f.get("CallSid", ""), f.get("CallStatus", "completed"),
                    int(f["CallDuration"]) if (f.get("CallDuration") or "").isdigit() else None)
    return {"ok": True, "status": call["status"] if call else None}


@router.post("/twilio/dial-status")
async def twilio_dial_status(request: Request):
    """Action du <Dial> de transfert : si personne ne décroche -> messagerie vocale."""
    f = dict((await request.form()).items())
    q = f"?practice={request.query_params['practice']}" if request.query_params.get("practice") else ""
    if f.get("DialCallStatus") in ("completed", "answered"):
        set_call("twilio", f.get("CallSid", ""), status="transferred")
        return _twiml("<Hangup/>")
    set_call("twilio", f.get("CallSid", ""), status="in-progress")
    return _twiml(twilio_record(q))


@router.post("/twilio/voicemail")
async def twilio_voicemail(request: Request):
    """Action de <Record> (RecordingUrl) et transcribeCallback (TranscriptionText)."""
    f = dict((await request.form()).items())
    voicemail_saved("twilio", f.get("CallSid", ""), f.get("RecordingUrl"), f.get("TranscriptionText"))
    return _twiml(_say_tw("Merci, votre message a bien été enregistré. Au revoir."), "<Hangup/>")


@router.post("/twilio/sms")
async def twilio_sms(request: Request):
    """Webhook « A message comes in » Twilio (SMS et WhatsApp : From/To préfixés « whatsapp: »). Réponse en TwiML."""
    f = dict((await request.form()).items())
    channel = "whatsapp" if (f.get("From") or "").startswith("whatsapp:") else "sms"
    to = (f.get("To") or "").replace("whatsapp:", "")
    practice = route_practice(to, request.query_params.get("practice"))
    res = notifications.handle_inbound(practice, f.get("From", ""), f.get("Body", ""), channel, "twilio")
    messaging.log_message(practice["id"], None, "outbound", channel, "twilio-twiml" if messaging.provider_configured("twilio") else "mock:twilio",
                          to, (f.get("From") or "").replace("whatsapp:", ""), res["reply"],
                          "sent" if messaging.provider_configured("twilio") else "mock_sent")
    return _twiml(f"<Message>{escape(res['reply'])}</Message>")


# ---------------------------------------------------------------- Vonage Voice API (NCCO)

def _ncco_talk_input(text: str, event_url: str, practice: dict) -> list:
    lang = "en-GB" if practice.get("language") == "en" else "fr-FR"
    return [{"action": "talk", "text": text, "language": lang, "bargeIn": True},
            {"action": "input", "type": ["speech"], "eventUrl": [event_url],
             "speech": {"language": lang, "endOnSilence": 1.5, "maxDuration": 20}}]


async def _params(request: Request) -> dict:
    out = dict(request.query_params)
    if request.method == "POST":
        try:
            out.update(await request.json())
        except Exception:
            out.update(dict((await request.form()).items()))
    return out


@router.api_route("/vonage/answer", methods=["GET", "POST"])
async def vonage_answer(request: Request):
    """answer_url Vonage : renvoie un NCCO (talk + input speech). Paramètres : to, from, uuid, conversation_uuid."""
    p = await _params(request)
    practice = route_practice(p.get("to"), p.get("practice"))
    call_id = p.get("uuid") or p.get("conversation_uuid") or uuid.uuid4().hex
    start_call("vonage", call_id, practice, p.get("from"), p.get("to"))
    greet = f"Bonjour, vous êtes bien au {practice['name']}. Je suis l'assistante virtuelle du cabinet. Comment puis-je vous aider ?"
    return JSONResponse(_ncco_talk_input(greet, cb_url("/vonage/input", practice=practice["id"]), practice))


@router.post("/vonage/input")
async def vonage_input(request: Request):
    """eventUrl de l'action input : {"uuid", "speech": {"results": [{"text", "confidence"}], "timeout_reason"}}."""
    p = await _params(request)
    practice = route_practice(p.get("to"), p.get("practice"))
    call_id = p.get("uuid") or uuid.uuid4().hex
    if not get_call("vonage", call_id):
        start_call("vonage", call_id, practice, p.get("from"), p.get("to"))
    results = ((p.get("speech") or {}).get("results") or [])
    speech = (results[0].get("text") if results else "") or ""
    event = cb_url("/vonage/input", practice=practice["id"])
    lang = "en-GB" if practice.get("language") == "en" else "fr-FR"
    if not speech:
        tries = int(p.get("tries", 0) or 0)
        if tries >= 1:
            return JSONResponse([
                {"action": "talk", "text": "Le cabinet ne peut pas vous répondre. Laissez votre message après le bip.", "language": lang},
                {"action": "record", "beepStart": True, "endOnSilence": 3, "timeOut": 120,
                 "eventUrl": [cb_url("/vonage/recording", practice=practice["id"])]}])
        return JSONResponse(_ncco_talk_input("Je ne vous ai pas entendu. Pouvez-vous répéter ?",
                                             cb_url("/vonage/input", practice=practice["id"], tries=1), practice))
    res = turn("vonage", call_id, practice, speech)
    num = transfer_number(practice)
    if res["emergency"]["level"] == "vital":
        ncco = [{"action": "talk", "text": res["reply"], "language": lang}]
        if num:
            ncco.append({"action": "connect", "endpoint": [{"type": "phone", "number": num.lstrip("+")}]})
        return JSONResponse(ncco)
    if res["handoff"] and num:
        set_call("vonage", call_id, status="transferring")
        return JSONResponse([{"action": "talk", "text": "Je vous mets en relation avec le cabinet.", "language": lang},
                             {"action": "connect", "timeout": 20, "endpoint": [{"type": "phone", "number": num.lstrip("+")}]}])
    return JSONResponse(_ncco_talk_input(res["reply"], event, practice))


@router.post("/vonage/recording")
async def vonage_recording(request: Request):
    p = await _params(request)
    voicemail_saved("vonage", p.get("uuid") or p.get("conversation_uuid") or "", p.get("recording_url"), None)
    return {"ok": True}


@router.api_route("/vonage/event", methods=["GET", "POST"])
async def vonage_event(request: Request):
    """event_url Vonage : status started|ringing|answered|completed|busy|timeout|failed|rejected|unanswered, duration."""
    p = await _params(request)
    status = p.get("status")
    mapping = {"busy": "busy", "timeout": "no-answer", "unanswered": "no-answer", "failed": "failed", "rejected": "failed",
               "cancelled": "canceled", "completed": "completed"}
    if status in mapping:
        dur = p.get("duration")
        end_call("vonage", p.get("uuid", ""), mapping[status], int(dur) if str(dur or "").isdigit() else None)
    return {"ok": True}


@router.api_route("/vonage/inbound-sms", methods=["GET", "POST"])
async def vonage_inbound_sms(request: Request):
    """Webhook SMS entrant Vonage (SMS API) : msisdn, to, text, messageId. Réponse envoyée via l'API SMS."""
    p = await _params(request)
    practice = route_practice("+" + str(p.get("to", "")).lstrip("+"), p.get("practice"))
    res = notifications.handle_inbound(practice, "+" + str(p.get("msisdn", "")).lstrip("+"), p.get("text", ""), "sms", "vonage")
    out = messaging.send(practice, "sms", "+" + str(p.get("msisdn", "")).lstrip("+"), res["reply"])
    return {"ok": True, "action": res["action"], "reply_status": out["status"]}


# ---------------------------------------------------------------- Africa's Talking Voice (XML) + SMS

def _at(xml: str) -> Response:
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response>' + xml + "</Response>", media_type="application/xml")


@router.post("/africastalking/voice")
async def at_voice(request: Request):
    """Callback voix Africa's Talking (isActive, sessionId, callerNumber, destinationNumber, dtmfDigits, recordingUrl,
    durationInSeconds, callSessionState). AT ne fait pas de reconnaissance vocale : menu DTMF (GetDigits).
      1 = prendre / gérer un rendez-vous (SMS avec l'assistante)  2 = urgence  0 = secrétariat (Dial, sinon messagerie)
    """
    f = dict((await request.form()).items())
    practice = route_practice(f.get("destinationNumber"), request.query_params.get("practice"))
    sid = f.get("sessionId") or uuid.uuid4().hex
    cb = escape(cb_url("/africastalking/voice", practice=practice["id"]))
    if str(f.get("isActive", "1")) == "0":  # notification de fin d'appel
        if not get_call("africastalking", sid):
            start_call("africastalking", sid, practice, f.get("callerNumber"), f.get("destinationNumber"))
        if f.get("recordingUrl"):
            voicemail_saved("africastalking", sid, f.get("recordingUrl"), None)
        dur = f.get("durationInSeconds")
        end_call("africastalking", sid, "completed" if f.get("status", "Success") == "Success" else "failed",
                 int(float(dur)) if dur else None)
        return _at("")
    if not get_call("africastalking", sid):
        start_call("africastalking", sid, practice, f.get("callerNumber"), f.get("destinationNumber"))
    digits = (f.get("dtmfDigits") or "").strip()
    if not digits:
        return _at(f'<GetDigits timeout="15" finishOnKey="#" numDigits="1" callbackUrl="{cb}"><Say voice="woman">'
                   + escape(f"Bonjour, vous êtes au {practice['name']}. Pour prendre, déplacer ou annuler un rendez-vous, tapez 1. "
                            "Pour une urgence, tapez 2. Pour parler au secrétariat, tapez 0.") + "</Say></GetDigits>"
                   + '<Say voice="woman">Nous n\'avons pas reçu votre choix. Un SMS va vous être envoyé. Au revoir.</Say>')
    if digits == "1":
        add_turn("africastalking", sid, "[touche 1] rendez-vous", "SMS envoyé pour poursuivre avec l'assistante")
        caller = f.get("callerNumber")
        e = phonelib.to_e164(caller, practice.get("country") or "FR", strict=False)
        if e:
            messaging.send(practice, "sms", e, f"{practice['name']} : bonjour, écrivez-nous ici votre demande de rendez-vous "
                           "(jour souhaité, matin ou après-midi) et l'assistante vous répond immédiatement.")
        return _at('<Say voice="woman">Un SMS vient de vous être envoyé pour choisir votre créneau. Merci et au revoir.</Say>')
    if digits == "2":
        add_turn("africastalking", sid, "[touche 2] urgence", "orientation vers les secours")
        return _at('<Say voice="woman">' + escape(f"En cas d'urgence vitale, raccrochez et {samu_short(practice)} immédiatement. "
                                                  "Pour une urgence non vitale, restez en ligne.") + "</Say>"
                   + (f'<Dial phoneNumbers="{escape(transfer_number(practice))}" ringbackTone="" />' if transfer_number(practice) else ""))
    if digits == "0":
        add_turn("africastalking", sid, "[touche 0] secrétariat", "transfert")
        num = transfer_number(practice)
        if num:
            set_call("africastalking", sid, status="transferring")
            return _at(f'<Say voice="woman">Je vous mets en relation.</Say><Dial phoneNumbers="{escape(num)}" maxDuration="600"/>')
    return _at('<Record finishOnKey="#" maxLength="120" trimSilence="true" playBeep="true"><Say voice="woman">'
               "Le secrétariat n'est pas disponible. Laissez votre message après le bip, puis appuyez sur dièse.</Say></Record>")


@router.post("/africastalking/sms")
async def at_sms(request: Request):
    """Callback SMS entrant Africa's Talking : from, to, text, date, id, linkId. Réponse via l'API SMS."""
    f = dict((await request.form()).items())
    practice = route_practice(f.get("to"), request.query_params.get("practice"))
    res = notifications.handle_inbound(practice, f.get("from", ""), f.get("text", ""), "sms", "africastalking")
    out = messaging.send(practice, "sms", phonelib.to_e164(f.get("from"), practice.get("country") or "FR", strict=False) or f.get("from", ""),
                         res["reply"])
    return {"ok": True, "action": res["action"], "reply_status": out["status"]}


status_router = APIRouter()


@status_router.get("/api/voip/status")
def voip_status():
    return {"providers": messaging.status_overview()}
