"""Export par cabinet, sauvegarde/rotation/restauration, sécurité (admin, en-têtes, limitation de débit, pays)."""
import io
import sqlite3
import zipfile

from app import backup, config, countries, db, security


def test_export_json_and_csv(client, login):
    call = login()
    j = call("GET", "/api/espace/export?format=json")
    assert j.status_code == 200 and j.json()["format"] == "careassist-export-v1" and j.json()["patients"]
    z = call("GET", "/api/espace/export?format=csv")
    assert z.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert {"patients.csv", "rendez-vous.csv"} <= set(names)
    csv_text = zipfile.ZipFile(io.BytesIO(z.content)).read("patients.csv").decode("utf-8-sig")
    assert "last_name" in csv_text and "Durand" in csv_text


def test_backup_rotation_and_restore(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))
    files = [backup.run_backup(keep=2)["file"] for _ in range(3)]
    assert len(backup.list_backups()) == 2 and str(backup.list_backups()[-1]) == files[-1]
    with sqlite3.connect(files[-1]) as c:
        n = c.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    with db.get_conn() as conn:
        conn.execute("DELETE FROM channel_messages")
        conn.execute("DELETE FROM patients")
    res = backup.restore(files[-1])
    assert res["previous_copy"]
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == n > 0


def test_admin_closed_by_default(client, monkeypatch):
    monkeypatch.setenv("ADMIN_OPEN", "0")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    assert client.get("/api/admin/stats").status_code == 401
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret-token")
    assert client.get("/api/admin/stats").status_code == 401
    assert client.get("/api/admin/stats", headers={"X-Admin-Token": "s3cret-token"}).status_code == 200
    assert client.get("/api/admin/practices", headers={"X-Admin-Token": "s3cret-token"}).json()


def test_security_headers(client):
    h = client.get("/").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert "default-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]


def test_rate_limit_login(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    security.reset()
    codes = [client.post("/api/auth/login", json={"email": "x@demo.getcareassist.com", "password": "nope"}).status_code for _ in range(12)]
    assert codes[0] == 401 and 429 in codes
    security.reset()


def test_public_booking_api_demo_only(client):
    with db.get_conn() as conn:
        conn.execute("UPDATE practices SET is_demo=0 WHERE slug='ophtalmologue'")
    slots = client.get("/api/slots", params={"practice": "ophtalmologue", "limit": 1}).json()["slots"]
    r = client.post("/api/appointments", json={"slot_id": slots[0]["id"], "patient_name": "Ana Lopes", "phone": "0611223344"})
    assert r.status_code == 403


def test_country_profiles_verified_or_todo():
    for code, p in countries.COUNTRIES.items():
        if p["emergency_verified"]:
            assert p["emergency"] and p["sources"], code
        else:
            assert not p["emergency"] and "TODO" in p["todo"], code
    assert countries.get_country("SN")["emergency"]["samu"] == "1515"
    assert countries.get_country("CM")["emergency"]["samu"] == "119"
    assert countries.get_country("CI")["emergency"]["samu"] == "185"
    assert countries.get_country("FR")["emergency"]["suicide"] == "3114"


def test_emergency_localized_per_country(client):
    r = client.post("/api/chat", json={"message": "je veux mourir", "practice": "dakar-almadies"}).json()
    assert r["emergency"]["level"] == "vital" and "1515" in r["reply"] and "3114" not in r["reply"] and "[[" not in r["reply"]
    r = client.post("/api/chat", json={"message": "je veux mourir", "practice": "psychologue"}).json()
    assert "3114" in r["reply"]
    prompt = client.get("/api/prompt", params={"practice": "douala-bonapriso"}).json()["prompt"]
    assert "119" in prompt and "[[" not in prompt and "Cameroun" in prompt
    for slug in ("dentiste", "psychologue", "ophtalmologue", "generaliste", "kinesitherapeute", "dakar-almadies"):
        assert "[[" not in client.get("/api/prompt", params={"practice": slug}).json()["prompt"]


def test_config_has_no_hardcoded_secrets():
    assert config.env("STRIPE_SECRET_KEY") == ""


def test_voip_webhook_token_and_twilio_signature(client, monkeypatch):
    monkeypatch.setenv("VOIP_WEBHOOK_TOKEN", "wh-secret")
    assert client.post("/africastalking/sms", data={"from": "+221770000101", "to": "+221338000001", "text": "OUI"}).status_code == 403
    assert client.post("/africastalking/sms?wt=wh-secret", data={"from": "+221770000101", "to": "+221338000001", "text": "OUI"}).status_code == 200
    monkeypatch.setenv("TWILIO_VALIDATE", "true")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    assert client.post("/twilio/sms", data={"From": "+33611111111", "To": "+33199000001", "Body": "OUI"}).status_code == 403
    from app.voice import twilio_signature_ok
    import base64, hashlib, hmac as h
    params = {"From": "+33611111111", "To": "+33199000001", "Body": "OUI"}
    url = "http://testserver/twilio/sms"
    sig = base64.b64encode(h.new(b"tok", (url + "".join(k + params[k] for k in sorted(params))).encode(), hashlib.sha1).digest()).decode()
    assert twilio_signature_ok(url, params, sig)
    assert client.post("/twilio/sms", data=params, headers={"X-Twilio-Signature": sig}).status_code == 200


def test_change_password(client, login):
    call = login("dr.ngono@demo.getcareassist.com")
    assert call("POST", "/api/auth/password", json={"current_password": "faux", "new_password": "NouveauMdp2026"}).status_code == 403
    assert call("POST", "/api/auth/password", json={"current_password": "CareAssist-Demo-2026", "new_password": "NouveauMdp2026"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "dr.ngono@demo.getcareassist.com", "password": "NouveauMdp2026"}).status_code == 200
