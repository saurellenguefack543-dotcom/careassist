"""Paiements : abstraction de prestataires + endpoints checkout / webhooks.

Prestataires (formats d'API issus de leur documentation officielle) :
- Stripe Checkout   POST https://api.stripe.com/v1/checkout/sessions (form-encoded, mode=subscription)
                    webhook : en-tête Stripe-Signature (t=..., v1=HMAC-SHA256(secret, "t.payload"))
- Flutterwave v3    POST https://api.flutterwave.com/v3/payments (JSON, renvoie data.link)
                    webhook : en-tête verif-hash == FLW_SECRET_HASH ; vérification GET /v3/transactions/{id}/verify
- Paystack          POST https://api.paystack.co/transaction/initialize (JSON, montant en sous-unité)
                    webhook : en-tête x-paystack-signature == HMAC-SHA512(PAYSTACK_SECRET_KEY, corps brut)

Sans clé (ou PAYMENTS_MODE=mock) : MODE DÉMO. L'abonnement est enregistré « pending » dans SQLite et une
URL de checkout simulée (/checkout/mock/<ref>) est renvoyée. Aucune clé n'est codée en dur.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from html import escape

import httpx
from fastapi import Depends, APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from . import security
from . import config, db
from .pricing import DISCLAIMER_FR, get_region, public_pricing, region_for_country

log = logging.getLogger("careassist.payments")
router = APIRouter()

# Devises sans décimale chez Stripe (montant envoyé tel quel)
STRIPE_ZERO_DECIMAL = {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV",
                       "XAF", "XOF", "XPF"}


class ProviderError(Exception):
    pass


def payments_forced_mock() -> bool:
    return config.env("PAYMENTS_MODE", "auto").lower() == "mock"


def base_url(request: Request | None) -> str:
    b = config.env("PUBLIC_BASE_URL")
    if b:
        return b.rstrip("/")
    return str(request.base_url).rstrip("/") if request else "http://localhost:8000"


def _timeout() -> float:
    return float(config.env("PAYMENTS_TIMEOUT", "20"))


# ------------------------------------------------------------------ prestataires

class Provider:
    name = "abstract"
    key_env = ""

    def is_live(self) -> bool:
        return bool(config.env(self.key_env)) and not payments_forced_mock()

    def create_checkout(self, sub: dict, region: dict, base: str) -> tuple[str, str | None]:
        """Renvoie (checkout_url, provider_session_id)."""
        raise NotImplementedError


class StripeProvider(Provider):
    name = "stripe"
    key_env = "STRIPE_SECRET_KEY"

    @staticmethod
    def unit_amount(amount: float, currency: str) -> int:
        return int(round(amount)) if currency.upper() in STRIPE_ZERO_DECIMAL else int(round(amount * 100))

    def build_params(self, sub: dict, region: dict, base: str) -> list[tuple[str, str]]:
        ref = sub["reference"]
        params = [
            ("mode", "subscription"),
            ("success_url", f"{base}/checkout/success?ref={ref}&session_id={{CHECKOUT_SESSION_ID}}"),
            ("cancel_url", f"{base}/#tarif"),
            ("customer_email", sub["email"]),
            ("client_reference_id", ref),
            ("metadata[reference]", ref),
            ("metadata[region]", region["key"]),
            ("subscription_data[metadata][reference]", ref),
            ("line_items[0][quantity]", "1"),
            ("locale", "fr"),
        ]
        price_id = config.env(f"STRIPE_PRICE_{region['key'].upper()}")
        if price_id:  # prix récurrent créé dans le dashboard Stripe
            params.append(("line_items[0][price]", price_id))
        else:
            params += [
                ("line_items[0][price_data][currency]", region["currency"].lower()),
                ("line_items[0][price_data][unit_amount]", str(self.unit_amount(region["amount"], region["currency"]))),
                ("line_items[0][price_data][recurring][interval]", "month"),
                ("line_items[0][price_data][product_data][name]", f"CareAssist — {region['label']}"),
            ]
        for i, pm in enumerate(region.get("stripe_payment_method_types") or ["card"]):
            params.append((f"payment_method_types[{i}]", pm))
        return params

    def create_checkout(self, sub, region, base):
        r = httpx.post("https://api.stripe.com/v1/checkout/sessions", data=self.build_params(sub, region, base),
                       auth=(config.env(self.key_env), ""), timeout=_timeout())
        if r.status_code >= 400:
            raise ProviderError(f"Stripe {r.status_code}: {r.text[:300]}")
        j = r.json()
        return j["url"], j["id"]


class FlutterwaveProvider(Provider):
    name = "flutterwave"
    key_env = "FLW_SECRET_KEY"

    def build_payload(self, sub: dict, region: dict, base: str) -> dict:
        payload = {
            "tx_ref": sub["reference"],
            "amount": region["amount"],                      # unité principale de la devise
            "currency": region["currency"],
            "redirect_url": f"{base}/checkout/success?ref={sub['reference']}",
            "customer": {"email": sub["email"], "name": sub["practice_name"], "phonenumber": sub.get("phone") or ""},
            "customizations": {"title": "CareAssist", "description": "Abonnement mensuel — appels illimités",
                               "logo": f"{config.SITE_URL}/favicon.svg"},
            "payment_options": region.get("flutterwave_payment_options", "card"),
            "meta": {"reference": sub["reference"], "region": region["key"]},
        }
        plan = config.env(f"FLW_PLAN_{region['key'].upper()}")  # plan de paiement récurrent (dashboard Flutterwave)
        if plan:
            payload["payment_plan"] = plan
        return payload

    def create_checkout(self, sub, region, base):
        r = httpx.post("https://api.flutterwave.com/v3/payments", json=self.build_payload(sub, region, base),
                       headers={"Authorization": f"Bearer {config.env(self.key_env)}"}, timeout=_timeout())
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400 or j.get("status") != "success":
            raise ProviderError(f"Flutterwave {r.status_code}: {r.text[:300]}")
        return j["data"]["link"], None

    def verify_transaction(self, transaction_id) -> dict:
        r = httpx.get(f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify",
                      headers={"Authorization": f"Bearer {config.env(self.key_env)}"}, timeout=_timeout())
        r.raise_for_status()
        return r.json().get("data") or {}


class PaystackProvider(Provider):
    name = "paystack"
    key_env = "PAYSTACK_SECRET_KEY"

    @staticmethod
    def subunit(amount: float) -> int:
        return int(round(amount * 100))  # kobo, pesewas, cents

    def build_payload(self, sub: dict, region: dict, base: str) -> dict:
        payload = {
            "email": sub["email"],
            "amount": str(self.subunit(region["amount"])),
            "currency": region["currency"],
            "reference": sub["reference"],
            "callback_url": f"{base}/checkout/success?ref={sub['reference']}",
            "channels": region.get("paystack_channels", ["card"]),
            "metadata": json.dumps({"reference": sub["reference"], "region": region["key"],
                                    "practice_name": sub["practice_name"]}),
        }
        plan = config.env(f"PAYSTACK_PLAN_{region['key'].upper()}")  # plan récurrent (remplace amount)
        if plan:
            payload["plan"] = plan
        return payload

    def create_checkout(self, sub, region, base):
        r = httpx.post("https://api.paystack.co/transaction/initialize", json=self.build_payload(sub, region, base),
                       headers={"Authorization": f"Bearer {config.env(self.key_env)}"}, timeout=_timeout())
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400 or not j.get("status"):
            raise ProviderError(f"Paystack {r.status_code}: {r.text[:300]}")
        return j["data"]["authorization_url"], j["data"].get("access_code")


PROVIDERS: dict[str, Provider] = {"stripe": StripeProvider(), "flutterwave": FlutterwaveProvider(),
                                  "paystack": PaystackProvider()}


# ------------------------------------------------------------------ persistance

def get_sub(reference: str) -> dict | None:
    with db.get_conn() as conn:
        r = conn.execute("SELECT * FROM subscriptions WHERE reference=?", (reference,)).fetchone()
    return dict(r) if r else None


def update_sub(reference: str, **fields) -> None:
    fields["updated_at"] = db.now_iso()
    if fields.get("status") == "active":
        fields.setdefault("activated_at", db.now_iso())
    cols = ", ".join(f"{k}=?" for k in fields)
    with db.get_conn() as conn:
        conn.execute(f"UPDATE subscriptions SET {cols} WHERE reference=?", (*fields.values(), reference))


def activate(reference: str, event: str, **extra) -> bool:
    sub = get_sub(reference)
    if not sub:
        return False
    if sub["status"] != "active":
        update_sub(reference, status="active", last_event=event, **extra)
    else:
        update_sub(reference, last_event=event, **extra)
    return True


# ------------------------------------------------------------------ API

class CheckoutIn(BaseModel):
    region: str | None = Field(None, description="clé de région (voir /api/pricing)")
    country: str | None = Field(None, description="code pays ISO-2 ; utilisé si region est absent")
    practice_name: str = Field(..., min_length=2, max_length=160)
    email: EmailStr
    phone: str | None = Field(None, max_length=30)
    specialty: str | None = None


@router.get("/api/pricing")
def pricing(country: str | None = None):
    data = public_pricing()
    data["suggested_region"] = region_for_country(country) if country else data["reference_region"]
    data["providers"] = {k: ("live" if p.is_live() else "mock") for k, p in PROVIDERS.items()}
    return data


@router.post("/api/checkout", status_code=201, dependencies=[Depends(security.limiter("checkout"))])
def checkout(body: CheckoutIn, request: Request):
    key = body.region or region_for_country(body.country)
    region = get_region(key)
    if not region:
        raise HTTPException(422, f"Région inconnue : {key}")
    provider = PROVIDERS[region["provider"]]
    mode = "live" if provider.is_live() else "mock"
    ref = f"ca_{region['key'][:6]}_{uuid.uuid4().hex[:16]}"
    sub = {"reference": ref, "practice_name": body.practice_name.strip(), "email": body.email, "phone": body.phone}
    ts = db.now_iso()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO subscriptions(reference, region, currency, amount, provider, mode, status, practice_name, email, "
            "phone, specialty, created_at, updated_at) VALUES (?,?,?,?,?,?, 'pending', ?,?,?,?,?,?)",
            (ref, region["key"], region["currency"], region["amount"], provider.name, mode, sub["practice_name"],
             body.email, body.phone, body.specialty, ts, ts),
        )
    base = base_url(request)
    if mode == "mock":
        url, session_id = f"{base}/checkout/mock/{ref}", None
    else:
        try:
            url, session_id = provider.create_checkout(sub, region, base)
        except (ProviderError, httpx.HTTPError) as e:
            log.error("checkout %s : %s", provider.name, e)
            update_sub(ref, status="error", last_event=str(e)[:300])
            raise HTTPException(502, f"Le prestataire de paiement ({provider.name}) a refusé la demande.")
    update_sub(ref, checkout_url=url, provider_session_id=session_id)
    return {"reference": ref, "region": region["key"], "provider": provider.name, "mode": mode, "status": "pending",
            "amount": region["amount"], "currency": region["currency"], "interval": "month", "checkout_url": url,
            "indicative_price": bool(region.get("indicative")),
            "notice": ("MODE DÉMO : aucun paiement réel, aucune clé de prestataire configurée." if mode == "mock" else None),
            "disclaimer": DISCLAIMER_FR if region.get("indicative") else None}


@router.get("/api/checkout/{reference}")
def checkout_status(reference: str):
    sub = get_sub(reference)
    if not sub:
        raise HTTPException(404, "Référence inconnue")
    return {k: sub[k] for k in ("reference", "region", "currency", "amount", "provider", "mode", "status", "activated_at")}


@router.post("/api/checkout/mock/{reference}/complete")
def mock_complete(reference: str):
    sub = get_sub(reference)
    if not sub:
        raise HTTPException(404, "Référence inconnue")
    if sub["mode"] != "mock":
        raise HTTPException(403, "Réservé au mode démo")
    activate(reference, "mock.payment_succeeded")
    return {"reference": reference, "status": "active", "mode": "mock"}


def _page(title: str, inner: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} — CareAssist</title><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/styles.css?v=3">
<style>.box{{max-width:560px;margin:60px auto;background:#fff;border:1px solid var(--line);border-radius:20px;padding:32px;box-shadow:var(--shadow)}}
.demo{{background:#fff7ed;border:1px solid #fdba74;color:#9a3412;border-radius:12px;padding:12px 14px;font-weight:600;margin-bottom:18px}}
dl{{display:grid;grid-template-columns:auto 1fr;gap:6px 16px}}dt{{color:var(--muted)}}dd{{margin:0;font-weight:600}}</style></head>
<body><div class="box"><a href="/" class="logo"><span class="logo-mark"><svg class="i" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></span> CareAssist</a>{inner}</div></body></html>""")


def _fmt_amount(sub: dict) -> str:
    amt = int(sub["amount"]) if float(sub["amount"]).is_integer() else sub["amount"]
    return f"{amt:,}".replace(",", " ") + f" {sub['currency']} / mois"


@router.get("/checkout/mock/{reference}", include_in_schema=False)
def mock_checkout_page(reference: str):
    sub = get_sub(reference)
    if not sub:
        raise HTTPException(404, "Référence inconnue")
    if sub["status"] == "active":
        return RedirectResponse(f"/checkout/success?ref={reference}", status_code=303)
    return _page("Paiement (démo)", f"""
<h2 style="text-align:left;margin-top:20px">Paiement simulé</h2>
<div class="demo">MODE DÉMO — aucun paiement réel. Aucune clé {escape(sub['provider'].capitalize())} n'est configurée.</div>
<dl><dt>Cabinet</dt><dd>{escape(sub['practice_name'])}</dd><dt>Email</dt><dd>{escape(sub['email'])}</dd>
<dt>Formule</dt><dd>CareAssist — appels illimités</dd><dt>Montant</dt><dd>{escape(_fmt_amount(sub))}</dd>
<dt>Prestataire</dt><dd>{escape(sub['provider'])} (simulé)</dd><dt>Référence</dt><dd><small>{escape(reference)}</small></dd></dl>
<form method="post" action="/checkout/mock/{escape(reference)}/pay" style="margin-top:22px">
<button class="btn btn-primary btn-block" type="submit">Simuler un paiement réussi</button></form>
<p class="note"><a href="/#tarif">Annuler et revenir au site</a></p>""")


@router.post("/checkout/mock/{reference}/pay", include_in_schema=False)
def mock_checkout_pay(reference: str):
    mock_complete(reference)
    return RedirectResponse(f"/checkout/success?ref={reference}", status_code=303)


@router.get("/checkout/success", include_in_schema=False)
def checkout_success(ref: str = ""):
    sub = get_sub(ref) if ref else None
    if not sub:
        return _page("Paiement", "<h2>Merci !</h2><p>Votre paiement est en cours de traitement.</p>")
    state = ("Votre abonnement est actif." if sub["status"] == "active" else
             "Paiement reçu côté prestataire : l'activation sera confirmée dès réception de la notification (webhook).")
    demo = '<div class="demo">MODE DÉMO — aucun paiement réel n\'a été effectué.</div>' if sub["mode"] == "mock" else ""
    return _page("Merci", f"""<h2 style="text-align:left;margin-top:20px">Merci, {escape(sub['practice_name'])} !</h2>{demo}
<p>{state}</p><dl><dt>Montant</dt><dd>{escape(_fmt_amount(sub))}</dd><dt>Statut</dt><dd>{escape(sub['status'])}</dd>
<dt>Référence</dt><dd><small>{escape(ref)}</small></dd></dl>
<p>Nous vous contactons sous 24 h ouvrées pour configurer votre cabinet. Questions : <a href="mailto:{config.CONTACT_EMAIL}">{config.CONTACT_EMAIL}</a></p>
<a class="btn btn-outline" href="/">Retour au site</a>""")


# ------------------------------------------------------------------ webhooks

def verify_stripe_signature(payload: bytes, header: str, secret: str, tolerance: int = 300) -> bool:
    try:
        parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
        t = int(parts["t"])
    except (KeyError, ValueError):
        return False
    signatures = [p.split("=", 1)[1] for p in header.split(",") if p.startswith("v1=")]
    expected = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return abs(time.time() - t) <= tolerance and any(hmac.compare_digest(expected, s) for s in signatures)


def verify_paystack_signature(payload: bytes, header: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, header or "")


def _require_unsigned_ok(reference: str | None):
    """Sans secret configuré, on n'accepte que les événements visant un abonnement en mode démo."""
    sub = get_sub(reference) if reference else None
    if not sub or sub["mode"] != "mock":
        raise HTTPException(400, "Webhook non signé refusé (secret non configuré et abonnement non démo)")


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    raw = await request.body()
    secret = config.env("STRIPE_WEBHOOK_SECRET")
    try:
        event = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "JSON invalide")
    obj = (event.get("data") or {}).get("object") or {}
    ref = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("reference")
    if secret:
        if not verify_stripe_signature(raw, request.headers.get("Stripe-Signature", ""), secret):
            raise HTTPException(400, "Signature Stripe invalide")
    else:
        _require_unsigned_ok(ref)
    etype = event.get("type")
    if etype == "checkout.session.completed" and ref:
        activate(ref, etype, provider_subscription_id=obj.get("subscription"))
    elif etype == "customer.subscription.deleted" and ref:
        update_sub(ref, status="cancelled", last_event=etype)
    elif etype == "invoice.payment_failed":
        sub_ref = ((obj.get("subscription_details") or {}).get("metadata") or {}).get("reference")
        if sub_ref:
            update_sub(sub_ref, status="failed", last_event=etype)
    return {"received": True, "type": etype}


@router.post("/webhooks/flutterwave")
async def flutterwave_webhook(request: Request):
    raw = await request.body()
    secret_hash = config.env("FLW_SECRET_HASH")
    try:
        event = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "JSON invalide")
    data = event.get("data") or {}
    ref = data.get("tx_ref") or data.get("txRef")
    if secret_hash:
        if not hmac.compare_digest(request.headers.get("verif-hash", ""), secret_hash):
            raise HTTPException(401, "verif-hash invalide")
    else:
        _require_unsigned_ok(ref)
    etype = event.get("event") or event.get("event.type")
    status = data.get("status")
    if etype == "charge.completed" and ref:
        sub = get_sub(ref)
        if sub and status == "successful":
            prov = PROVIDERS["flutterwave"]
            if sub["mode"] == "live" and prov.is_live() and data.get("id"):
                v = prov.verify_transaction(data["id"])  # recommandé par Flutterwave
                if not (v.get("status") == "successful" and v.get("currency") == sub["currency"]
                        and float(v.get("amount", 0)) >= float(sub["amount"])):
                    update_sub(ref, status="failed", last_event="charge.completed (vérification échouée)")
                    return {"received": True, "verified": False}
            activate(ref, etype, provider_session_id=str(data.get("id") or ""))
        elif sub:
            update_sub(ref, status="failed", last_event=f"{etype}:{status}")
    return {"received": True}


@router.post("/webhooks/paystack")
async def paystack_webhook(request: Request):
    raw = await request.body()
    secret = config.env("PAYSTACK_SECRET_KEY")
    try:
        event = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "JSON invalide")
    data = event.get("data") or {}
    ref = data.get("reference")
    if secret:
        if not verify_paystack_signature(raw, request.headers.get("x-paystack-signature", ""), secret):
            raise HTTPException(401, "Signature Paystack invalide")
    else:
        _require_unsigned_ok(ref)
    etype = event.get("event")
    if etype == "charge.success" and ref and data.get("status") == "success":
        sub = get_sub(ref)
        if sub and data.get("currency") and data["currency"] != sub["currency"]:
            update_sub(ref, status="failed", last_event="charge.success (devise inattendue)")
        else:
            activate(ref, etype)
    elif etype in ("subscription.disable", "subscription.not_renew") and ref:
        update_sub(ref, status="cancelled", last_event=etype)
    return {"received": True}
