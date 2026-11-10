"""Paramètres cabinet : contact d'urgence, FAQ, logo, isolation."""
import io

from app import db


def _signup(client, email, name):
    r = client.post("/api/auth/signup", json={
        "practice_name": name, "specialty": "dentiste", "country": "FR",
        "name": "Dr Settings", "email": email, "password": "MotDePasse2026",
    })
    assert r.status_code == 201, r.text
    return r.json()["csrf"], client.get("/api/auth/me").json()


def test_settings_emergency_access_and_city(client):
    csrf, me = _signup(client, "settings@cabinet-test.fr", "Cabinet Paramètres")
    r = client.put("/api/espace/settings", json={
        "access": "Métro ligne 1, interphone 12",
        "prices_note": "Consultation 50 euros",
        "city": "Lille",
        "emergency_contact_name": "Dr Garde",
        "emergency_contact_phone": "03 20 00 00 00",
        "hours": "Lundi-vendredi 9h-18h",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["access"] == "Métro ligne 1, interphone 12"
    assert s["prices_note"] == "Consultation 50 euros"
    assert s["city"] == "Lille"
    assert s["emergency_contact_name"] == "Dr Garde"
    assert s["emergency_contact_phone"].startswith("+33")


def test_faq_crud_and_tenant_isolation(client):
    csrf_a, me_a = _signup(client, "faqa@cabinet-test.fr", "Cabinet FAQ A")
    created = client.post("/api/espace/faq", json={
        "question": "Faut-il apporter un panoramique ?",
        "answer": "Oui, si vous en avez un de moins de six mois.",
        "keywords": "panoramique, radio",
    }, headers={"X-CSRF-Token": csrf_a})
    assert created.status_code == 201, created.text
    fid = created.json()["id"]
    rows = client.get("/api/espace/faq").json()
    assert any(r["id"] == fid for r in rows)

    # un autre cabinet ne voit pas et ne peut pas modifier cette FAQ
    csrf_b, _ = _signup(client, "faqb@cabinet-test.fr", "Cabinet FAQ B")
    assert client.get("/api/espace/faq").json() == []
    assert client.put(f"/api/espace/faq/{fid}", json={"question": "Pirate ?", "answer": "Non merci"},
                      headers={"X-CSRF-Token": csrf_b}).status_code == 404
    assert client.delete(f"/api/espace/faq/{fid}", headers={"X-CSRF-Token": csrf_b}).status_code == 404

    # le cabinet A peut supprimer la sienne (nouvelle session A)
    client.cookies.clear()
    login = client.post("/api/auth/login", json={"email": "faqa@cabinet-test.fr", "password": "MotDePasse2026"})
    csrf_a2 = login.json()["csrf"]
    assert client.delete(f"/api/espace/faq/{fid}", headers={"X-CSRF-Token": csrf_a2}).status_code == 200
    assert client.get("/api/espace/faq").json() == []


def test_logo_upload_and_delete(client):
    csrf, me = _signup(client, "logo@cabinet-test.fr", "Cabinet Logo")
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (14, 124, 134)).save(buf, format="JPEG")
    buf.seek(0)
    r = client.post("/api/espace/logo", files={"file": ("logo.jpg", buf, "image/jpeg")},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    assert r.json()["has_logo"] is True
    got = client.get("/api/espace/logo")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("image/")
    assert client.delete("/api/espace/logo", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/api/espace/logo").status_code == 404


def test_custom_faq_is_used_in_chat(client):
    csrf, me = _signup(client, "faqchat@cabinet-test.fr", "Cabinet FAQ Chat")
    slug = me["practice"]["slug"]
    client.post("/api/espace/faq", json={
        "question": "Acceptez-vous les paiements en chèque ?",
        "answer": "Oui, le cabinet accepte les chèques et les cartes, mention unique FAQTEST42.",
        "keywords": "chèque, cheque, paiement",
    }, headers={"X-CSRF-Token": csrf})
    r = client.post("/api/chat", json={"message": "Est-ce que vous prenez les chèques ?", "session_id": "faq-1", "practice": slug})
    assert r.status_code == 200, r.text
    assert "FAQTEST42" in r.json()["reply"]
