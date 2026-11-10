"""Intégrations voix : Twilio (TwiML <Gather speech>) et Vapi (custom LLM + tool calls)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import booking, config, db
from .engine import process_message, resolve_practice

router = APIRouter()


async def _guard(request: Request):
    from .telephony import webhook_guard
    await webhook_guard(request)


# ------------------------------------------------------------------ Twilio

def _say(text: str) -> str:
    voice = config.env("TWILIO_VOICE", "Polly.Lea")
    return f'<Say language="fr-FR" voice="{escape(voice)}">{escape(text)}</Say>'


def _gather(action: str, prompt: str) -> str:
    return (f'<Gather input="speech" language="fr-FR" speechTimeout="auto" action="{escape(action)}" method="POST" '
            f'actionOnEmptyResult="true">'
            f"{_say(prompt)}</Gather>")


def twilio_signature_ok(request_url: str, params: dict, signature: str) -> bool:
    token = config.env("TWILIO_AUTH_TOKEN")
    data = request_url + "".join(k + params[k] for k in sorted(params))
    digest = base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(digest, signature or "")


@router.post("/twilio/voice", dependencies=[Depends(_guard)])
async def twilio_voice(request: Request):
    """Webhook « A call comes in » de Twilio. Boucle : Gather(speech) -> moteur -> Say -> Gather…

    Routage : cabinet retrouvé par le numéro appelé (`To` = numéro VoIP du cabinet), sinon `?practice=<slug|id>`.
    Journal d'appel (durée, statut, transcription) dans la table `calls` ; deux silences -> messagerie vocale ;
    transfert humain via <Dial> (sans réponse -> messagerie) ; appel manqué -> SMS de rappel automatique.
    Configurez aussi le « status callback » du numéro sur /twilio/status.
    """
    from . import telephony
    form = dict((await request.form()).items())
    practice_key = request.query_params.get("practice")
    call_sid = form.get("CallSid") or "twilio-" + uuid.uuid4().hex
    speech = (form.get("SpeechResult") or "").strip()
    practice = telephony.route_practice(form.get("To"), practice_key)
    q = f"?practice={practice_key}" if practice_key else ""
    action = "/twilio/voice" + q
    is_new = not telephony.get_call("twilio", call_sid)
    if is_new:
        telephony.start_call("twilio", call_sid, practice, form.get("From"), form.get("To"))
    transfer = telephony.transfer_number(practice)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<Response>"]
    if not speech:
        db.get_or_create_conversation(call_sid, "phone", practice["id"])
        retry = int(request.query_params.get("retry") or 0)
        if is_new:
            greet = (f"Bonjour, vous êtes bien au {practice['name']}. Je suis l'assistante virtuelle du cabinet. "
                     "Comment puis-je vous aider ?")
            parts.append(_gather(action, greet))
            parts.append(_say("Je n'ai rien entendu. N'hésitez pas à rappeler. Au revoir."))
        elif retry < 2:
            parts.append(_gather(action + ("&" if q else "?") + f"retry={retry + 1}", "Je ne vous ai pas entendu. Pouvez-vous répéter ?"))
            parts.append(_say("Je n'ai rien entendu. N'hésitez pas à rappeler. Au revoir."))
        else:
            parts.append(telephony.twilio_record(q))
    else:
        res = telephony.turn("twilio", call_sid, practice, speech)
        reply = res["reply"]
        if res["emergency"]["level"] == "vital":
            parts.append(_say(reply))
            if transfer:
                parts.append(f"<Dial>{escape(transfer)}</Dial>")
            parts.append(_say(f"Raccrochez et {telephony.samu_short(practice)} maintenant si vous êtes en danger. Au revoir."))
            parts.append("<Hangup/>")
        elif res["handoff"] and transfer:
            telephony.set_call("twilio", call_sid, status="transferring")
            parts.append(_say(reply.split(" Pouvez-vous")[0]))
            parts.append(f'<Dial timeout="20" action="{escape("/twilio/dial-status" + q)}" method="POST">{escape(transfer)}</Dial>')
        elif res["intent"] == "thanks":
            parts.append(_say(reply))
            parts.append("<Hangup/>")
        else:
            parts.append(_gather(action, reply))
            parts.append(_say("Je n'ai rien entendu. Au revoir et à bientôt."))
    parts.append("</Response>")
    return Response("".join(parts), media_type="application/xml")


# ------------------------------------------------------------------ Vapi

def _vapi_auth(request: Request):
    secret = config.env("VAPI_SECRET")
    if secret and not hmac.compare_digest(request.headers.get("x-vapi-secret", ""), secret):
        raise HTTPException(401, "x-vapi-secret invalide")


@router.post("/vapi/chat/completions")
async def vapi_custom_llm(request: Request):
    """Endpoint « Custom LLM » de Vapi (format OpenAI chat completions, streaming SSE ou non).

    Dans Vapi : Model -> Custom LLM -> URL = https://<votre-domaine>/vapi  (Vapi ajoute /chat/completions).
    Le dernier message utilisateur est passé au moteur CareAssist (urgences + réservations déterministes).
    """
    _vapi_auth(request)
    body = await request.json()
    msgs = body.get("messages") or []
    user_msgs = [m for m in msgs if m.get("role") == "user" and m.get("content")]
    text = user_msgs[-1]["content"] if user_msgs else ""
    if isinstance(text, list):
        text = " ".join(p.get("text", "") for p in text if isinstance(p, dict))
    call = body.get("call") or {}
    meta = body.get("metadata") or {}
    session = "vapi-" + str(call.get("id") or meta.get("session_id") or body.get("user") or uuid.uuid4().hex)
    practice_key = request.query_params.get("practice") or meta.get("practice")
    if text:
        reply = process_message(text, session_id=session, practice=practice_key, channel="vapi")["reply"]
    else:
        p = resolve_practice(practice_key)
        reply = f"Bonjour, vous êtes bien au {p['name']}. Comment puis-je vous aider ?"
    cid, created, model = "chatcmpl-" + uuid.uuid4().hex[:24], int(time.time()), "careassist-engine"
    if body.get("stream"):
        def gen():
            chunk = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply}, "finish_reason": None}]}
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            end = {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            yield f"data: {json.dumps(end)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return {"id": cid, "object": "chat.completion", "created": created, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


def _run_tool(name: str, args: dict, practice_key) -> dict:
    p = resolve_practice(practice_key or args.get("practice"))
    if name == "check_availability":
        from datetime import date
        day = date.fromisoformat(args["date"]) if args.get("date") else None
        slots = booking.find_slots(day=day, period=args.get("period"), practice_id=p["id"],
                                   limit=int(args.get("limit", 3)))
        return {"slots": [{"slot_id": s["id"], "start": s["start"], "label": s["label"], "practitioner": s["practitioner"]} for s in slots]}
    if name == "book_appointment":
        try:
            a = booking.book(int(args["slot_id"]), args.get("patient_name", ""), args.get("phone", ""),
                             reason=args.get("reason", ""), urgent=bool(args.get("urgent")))
            return {"ok": True, "appointment": a}
        except (booking.BookingError, KeyError, ValueError) as e:
            return {"ok": False, "error": str(e)}
    if name == "cancel_appointment":
        appts = booking.upcoming_for_phone(args.get("phone", ""), practice_id=p["id"])
        if not appts:
            return {"ok": False, "error": "Aucun rendez-vous à venir pour ce numéro"}
        a = booking.cancel(appts[0]["id"])
        return {"ok": True, "cancelled_appointment_id": a["id"]}
    if name == "detect_emergency":
        from .emergency import detect
        return detect(args.get("text", ""), p["specialty"]).to_dict()
    return {"error": f"outil inconnu : {name}"}


@router.post("/vapi/webhook")
async def vapi_webhook(request: Request):
    """Server URL Vapi : gère les messages `tool-calls` (et l'ancien `function-call`).

    Outils exposés : check_availability(date?, period?), book_appointment(slot_id, patient_name, phone, reason?),
    cancel_appointment(phone), detect_emergency(text). Les autres types (status-update, end-of-call-report…) sont
    simplement journalisés et acquittés.
    """
    _vapi_auth(request)
    body = await request.json()
    msg = body.get("message") or body
    mtype = msg.get("type")
    practice_key = request.query_params.get("practice")
    if mtype == "tool-calls":
        results = []
        for tc in msg.get("toolCallList") or msg.get("toolCalls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments") or tc.get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            name = fn.get("name") or tc.get("name")
            results.append({"toolCallId": tc.get("id"), "result": json.dumps(_run_tool(name, args, practice_key), ensure_ascii=False)})
        return {"results": results}
    if mtype == "function-call":
        fc = msg.get("functionCall") or {}
        return {"result": json.dumps(_run_tool(fc.get("name"), fc.get("parameters") or {}, practice_key), ensure_ascii=False)}
    if mtype == "end-of-call-report":
        call_id = (msg.get("call") or {}).get("id") or uuid.uuid4().hex
        conv = db.get_or_create_conversation("vapi-" + str(call_id), "vapi", resolve_practice(practice_key)["id"])
        if msg.get("summary"):
            db.log_message(conv["id"], "assistant", "[Résumé Vapi] " + msg["summary"], intent="summary", engine="vapi")
    return JSONResponse({"ok": True, "received": mtype})
