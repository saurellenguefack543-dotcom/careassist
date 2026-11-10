"""Annuaire public : publication, validation, option de retrait, données publiques uniquement."""
from datetime import datetime, timedelta, timezone

from app import db, directory


PUBLIC_FORBIDDEN = (
    "password_hash", "patients", "voip_number", "transfer_number", "notify_patient_offsets",
    "trial_ends_at", "subscription_status", "logo_path", "plan",
)


def test_seeded_demos_are_published(client):
    j = client.get("/api/directory").json()
    rows = j["practices"]
    assert len(rows) >= 3
    slugs = {r["slug"] for r in rows}
    assert "dentiste" in slugs
    for r in rows:
        for k in PUBLIC_FORBIDDEN:
            assert k not in r
        assert "name" in r and "specialty" in r and "country" in r
        assert "phone" in r and "email" in r and "hours" in r
        assert "06 05 50 85 42" not in (r.get("phone") or "")


def test_directory_filters(client):
    only = client.get("/api/directory", params={"specialty": "dentiste"}).json()["practices"]
    assert only and all(r["specialty"] == "dentiste" for r in only)
    fr = client.get("/api/directory", params={"country": "FR"}).json()["practices"]
    assert fr and all(r["country"] == "FR" for r in fr)
    city = only[0].get("city") or ""
    if city:
        filtered = client.get("/api/directory", params={"city": city}).json()["practices"]
        assert all(city.lower() in (r.get("city") or "").lower() for r in filtered)


def test_signup_listing_is_pending_until_approved(client):
    r = client.post("/api/auth/signup", json={
        "practice_name": "Cabinet Annuaire Test", "specialty": "generaliste", "country": "FR",
        "name": "Dr Annuaire", "email": "annuaire@cabinet-test.fr", "password": "MotDePasse2026",
    })
    assert r.status_code == 201, r.text
    me = client.get("/api/auth/me").json()
    slug = me["practice"]["slug"]
    assert me["listing"]["listing_status"] == "pending"
    listed = {p["slug"] for p in client.get("/api/directory").json()["practices"]}
    assert slug not in listed
    assert client.get(f"/api/directory/{slug}").status_code == 404

    pid = me["practice"]["id"]
    ok = client.post(f"/api/admin/practices/{pid}/approve")
    assert ok.status_code == 200, ok.text
    assert ok.json()["listing_status"] == "published"
    one = client.get(f"/api/directory/{slug}")
    assert one.status_code == 200
    assert one.json()["name"] == "Cabinet Annuaire Test"
    for k in PUBLIC_FORBIDDEN:
        assert k not in one.json()


def test_admin_reject_hides_listing(client):
    r = client.post("/api/auth/signup", json={
        "practice_name": "Cabinet Refus", "specialty": "psychologue", "country": "FR",
        "name": "Dr Refus", "email": "refus@cabinet-test.fr", "password": "MotDePasse2026",
    })
    assert r.status_code == 201, r.text
    pid = client.get("/api/auth/me").json()["practice"]["id"]
    slug = client.get("/api/auth/me").json()["practice"]["slug"]
    assert client.post(f"/api/admin/practices/{pid}/reject").json()["listing_status"] == "rejected"
    assert client.get(f"/api/directory/{slug}").status_code == 404
    # une fiche refusée n'est pas auto-publiée
    past = (datetime.now(timezone.utc) - timedelta(hours=60)).isoformat()
    with db.get_conn() as conn:
        conn.execute("UPDATE practices SET created_at=? WHERE id=?", (past, pid))
    directory.process_listings(datetime.now(timezone.utc))
    assert db.get_practice(pid)["listing_status"] == "rejected"
    assert client.get(f"/api/directory/{slug}").status_code == 404


def test_auto_publish_after_48h(client):
    r = client.post("/api/auth/signup", json={
        "practice_name": "Cabinet Auto Pub", "specialty": "ophtalmologue", "country": "FR",
        "name": "Dr Auto", "email": "autopub@cabinet-test.fr", "password": "MotDePasse2026",
    })
    assert r.status_code == 201, r.text
    me = client.get("/api/auth/me").json()
    pid, slug = me["practice"]["id"], me["practice"]["slug"]
    past = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
    with db.get_conn() as conn:
        conn.execute("UPDATE practices SET created_at=?, listing_status=? WHERE id=?", (past, "pending", pid))
    stats = directory.process_listings(datetime.now(timezone.utc))
    assert stats["published"] >= 1
    assert client.get(f"/api/directory/{slug}").status_code == 200


def test_directory_opt_out(client, login):
    call = login()
    me = call("GET", "/api/auth/me").json()
    slug = me["practice"]["slug"]
    assert any(p["slug"] == slug for p in client.get("/api/directory").json()["practices"])
    r = call("PUT", "/api/espace/settings", json={"directory_visible": False})
    assert r.status_code == 200, r.text
    listed = {p["slug"] for p in client.get("/api/directory").json()["practices"]}
    assert slug not in listed
    call("PUT", "/api/espace/settings", json={"directory_visible": True})
    listed = {p["slug"] for p in client.get("/api/directory").json()["practices"]}
    assert slug in listed


def test_directory_contact_creates_lead(client):
    rows = client.get("/api/directory").json()["practices"]
    slug = rows[0]["slug"]
    r = client.post(f"/api/directory/{slug}/contact", json={
        "name": "Marie Test", "email": "marie@exemple.fr", "phone": "06 11 22 33 44",
        "message": "Bonjour, je souhaite un rendez-vous la semaine prochaine.",
    })
    assert r.status_code == 201, r.text
    with db.get_conn() as conn:
        lead = conn.execute("SELECT * FROM leads WHERE source=? ORDER BY id DESC LIMIT 1", ("directory",)).fetchone()
    assert lead is not None
    assert "Marie Test" in lead["message"]
