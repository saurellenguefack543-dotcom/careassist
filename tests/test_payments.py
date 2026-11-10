"""Tarification régionale et paiements (mode démo + formats prestataires + webhooks signés).

Les « clés » utilisées ici sont des valeurs factices de test, jamais de vraies clés.
"""
import hashlib
import hmac
import json
import time

import httpx
import pytest

from app import payments, pricing

FAKE = "test_only_not_a_real_key"


@pytest.fixture(autouse=True)
def no_payment_keys(monkeypatch):
    for k in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "FLW_SECRET_KEY", "FLW_SECRET_HASH", "PAYSTACK_SECRET_KEY",
              "PUBLIC_BASE_URL", "PAYMENTS_MODE", "PRICING_FILE"):
        monkeypatch.delenv(k, raising=False)


def new_checkout(client, **kw):
    body = {"practice_name": "Cabinet Test", "email": "test@example.com", "phone": "0102030405", **kw}
    r = client.post("/api/checkout", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_pricing_reference_and_regions(client):
    d = client.get("/api/pricing").json()
    regions = {r["key"]: r for r in d["regions"]}
    assert regions["europe"]["amount"] == 299 and regions["europe"]["currency"] == "EUR" and regions["europe"]["reference"]
    for key in ("uemoa", "cemac", "nigeria", "ghana", "kenya", "south_africa", "morocco"):
        assert regions[key]["indicative"] is True
    assert {regions[k]["currency"] for k in ("uemoa", "cemac", "nigeria", "ghana", "kenya", "south_africa", "morocco")} == \
        {"XOF", "XAF", "NGN", "GHS", "KES", "ZAR", "MAD"}
    assert all(r["provider"] in payments.PROVIDERS for r in d["regions"])
    assert "indicatifs" in d["disclaimer"]
    assert set(d["providers"].values()) == {"mock"}


@pytest.mark.parametrize("country,region", [("FR", "europe"), ("SN", "uemoa"), ("CI", "uemoa"), ("CM", "cemac"),
                                            ("NG", "nigeria"), ("GH", "ghana"), ("KE", "kenya"), ("ZA", "south_africa"),
                                            ("MA", "morocco"), ("TN", "maghreb"), ("CD", "africa_other"),
                                            ("LY", "africa_other"), ("US", "international"), ("JP", "international")])
def test_region_for_country(country, region):
    assert pricing.region_for_country(country) == region


def test_mock_checkout_eur_full_flow(client):
    c = new_checkout(client, region="europe")
    assert c["mode"] == "mock" and c["provider"] == "stripe" and c["currency"] == "EUR" and c["amount"] == 299
    assert "/checkout/mock/" in c["checkout_url"] and "MODE DÉMO" in c["notice"]
    assert client.get(f"/api/checkout/{c['reference']}").json()["status"] == "pending"
    page = client.get(f"/checkout/mock/{c['reference']}")
    assert page.status_code == 200 and "MODE DÉMO" in page.text and "299 EUR" in page.text
    r = client.post(f"/checkout/mock/{c['reference']}/pay", follow_redirects=False)
    assert r.status_code == 303
    assert client.get(f"/api/checkout/{c['reference']}").json()["status"] == "active"
    assert "Votre abonnement est actif" in client.get(f"/checkout/success?ref={c['reference']}").text


def test_mock_checkout_xof_by_country(client):
    c = new_checkout(client, country="SN")
    assert c["region"] == "uemoa" and c["provider"] == "flutterwave" and c["currency"] == "XOF" and c["amount"] == 59000
    assert c["indicative_price"] is True and c["disclaimer"]


def test_checkout_validation(client):
    assert client.post("/api/checkout", json={"region": "mars", "practice_name": "Cab X", "email": "a@b.fr"}).status_code == 422
    assert client.post("/api/checkout", json={"region": "europe", "practice_name": "Cab X", "email": "nope"}).status_code == 422


def test_stripe_params_shape():
    p = payments.StripeProvider()
    sub = {"reference": "ref1", "email": "a@b.fr", "practice_name": "Cab"}
    eu = dict(p.build_params(sub, pricing.get_region("europe"), "https://getcareassist.com"))
    assert eu["mode"] == "subscription" and eu["line_items[0][price_data][unit_amount]"] == "29900"
    assert eu["line_items[0][price_data][recurring][interval]"] == "month" and eu["client_reference_id"] == "ref1"
    assert eu["payment_method_types[1]"] == "sepa_debit"
    assert eu["success_url"].startswith("https://getcareassist.com/checkout/success")
    # MAD : devise à 2 décimales -> centimes
    assert dict(p.build_params(sub, pricing.get_region("morocco"), "x"))["line_items[0][price_data][unit_amount]"] == "129000"
    assert p.unit_amount(59000, "XOF") == 59000  # zéro décimale


def test_flutterwave_and_paystack_payload_shape():
    sub = {"reference": "ref2", "email": "a@b.fr", "practice_name": "Cab", "phone": "+221770000000"}
    fw = payments.FlutterwaveProvider().build_payload(sub, pricing.get_region("uemoa"), "https://getcareassist.com")
    assert fw["tx_ref"] == "ref2" and fw["amount"] == 59000 and fw["currency"] == "XOF"
    assert "mobilemoneyfranco" in fw["payment_options"] and fw["customer"]["email"] == "a@b.fr"
    ps = payments.PaystackProvider().build_payload(sub, pricing.get_region("kenya"), "https://getcareassist.com")
    assert ps["amount"] == "850000" and ps["currency"] == "KES" and "mobile_money" in ps["channels"]
    assert ps["reference"] == "ref2" and json.loads(ps["metadata"])["region"] == "kenya"


class FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, json.dumps(data)
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._d


def test_live_mode_uses_provider_url(client, monkeypatch):
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", FAKE)
    calls = {}

    def fake_post(url, **kw):
        calls["url"], calls["json"] = url, kw.get("json")
        return FakeResp({"status": True, "data": {"authorization_url": "https://checkout.paystack.com/abc", "access_code": "abc", "reference": kw["json"]["reference"]}})

    monkeypatch.setattr(httpx, "post", fake_post)
    c = new_checkout(client, region="nigeria")
    assert c["mode"] == "live" and c["checkout_url"] == "https://checkout.paystack.com/abc"
    assert calls["url"] == "https://api.paystack.co/transaction/initialize" and calls["json"]["amount"] == "9500000"


def test_live_provider_error_returns_502(client, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE)
    monkeypatch.setattr(httpx, "post", lambda url, **kw: FakeResp({"error": {"message": "bad"}}, 400))
    assert client.post("/api/checkout", json={"region": "europe", "practice_name": "Cab", "email": "a@b.fr"}).status_code == 502


def test_forced_mock_mode(client, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE)
    monkeypatch.setenv("PAYMENTS_MODE", "mock")
    assert new_checkout(client, region="europe")["mode"] == "mock"


def _stripe_sig(payload: bytes, secret: str, t=None) -> str:
    t = t or int(time.time())
    return f"t={t},v1=" + hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()


def test_stripe_webhook_signature(client, monkeypatch):
    ref = new_checkout(client, region="europe")["reference"]
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_" + FAKE)
    body = json.dumps({"type": "checkout.session.completed", "data": {"object": {"client_reference_id": ref, "subscription": "sub_123"}}}).encode()
    bad = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": "t=1,v1=deadbeef"})
    assert bad.status_code == 400
    old = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": _stripe_sig(body, "whsec_" + FAKE, t=int(time.time()) - 3600)})
    assert old.status_code == 400  # hors tolérance
    ok = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": _stripe_sig(body, "whsec_" + FAKE)})
    assert ok.status_code == 200
    assert client.get(f"/api/checkout/{ref}").json()["status"] == "active"


def test_paystack_webhook_signature(client, monkeypatch):
    ref = new_checkout(client, region="ghana")["reference"]
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", FAKE)
    body = json.dumps({"event": "charge.success", "data": {"reference": ref, "status": "success", "currency": "GHS"}}).encode()
    assert client.post("/webhooks/paystack", content=body, headers={"x-paystack-signature": "00"}).status_code == 401
    sig = hmac.new(FAKE.encode(), body, hashlib.sha512).hexdigest()
    assert client.post("/webhooks/paystack", content=body, headers={"x-paystack-signature": sig}).status_code == 200
    assert client.get(f"/api/checkout/{ref}").json()["status"] == "active"


def test_flutterwave_webhook_verif_hash(client, monkeypatch):
    ref = new_checkout(client, region="cemac")["reference"]
    monkeypatch.setenv("FLW_SECRET_HASH", "hash_" + FAKE)
    body = {"event": "charge.completed", "data": {"id": 1, "tx_ref": ref, "status": "successful", "amount": 59000, "currency": "XAF"}}
    assert client.post("/webhooks/flutterwave", json=body, headers={"verif-hash": "wrong"}).status_code == 401
    assert client.post("/webhooks/flutterwave", json=body, headers={"verif-hash": "hash_" + FAKE}).status_code == 200
    assert client.get(f"/api/checkout/{ref}").json()["status"] == "active"


def test_unsigned_webhook_only_for_mock_subscriptions(client, monkeypatch):
    mock_ref = new_checkout(client, region="europe")["reference"]
    body = {"type": "checkout.session.completed", "data": {"object": {"client_reference_id": mock_ref}}}
    assert client.post("/webhooks/stripe", json=body).status_code == 200
    # abonnement réel (live) : un webhook non signé est refusé
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE)
    monkeypatch.setattr(httpx, "post", lambda url, **kw: FakeResp({"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"}))
    live_ref = new_checkout(client, region="europe")["reference"]
    body["data"]["object"]["client_reference_id"] = live_ref
    assert client.post("/webhooks/stripe", json=body).status_code == 400
    assert client.post("/webhooks/stripe", json={"type": "x", "data": {"object": {}}}).status_code == 400


def test_admin_lists_subscriptions(client):
    new_checkout(client, region="europe")
    new_checkout(client, country="SN")
    subs = client.get("/api/admin/subscriptions").json()
    assert {s["currency"] for s in subs} == {"EUR", "XOF"} and all(s["mode"] == "mock" for s in subs)
    assert client.get("/api/admin/stats").json()["subscriptions"] == 2


def test_pricing_file_override(client, tmp_path, monkeypatch):
    f = tmp_path / "pricing.json"
    f.write_text(json.dumps({"uemoa": {"amount": 49000}}))
    monkeypatch.setenv("PRICING_FILE", str(f))
    assert pricing.get_region("uemoa")["amount"] == 49000
    assert new_checkout(client, region="uemoa")["amount"] == 49000
