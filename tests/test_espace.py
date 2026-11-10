"""Authentification, rôles, CSRF et ISOLATION STRICTE entre cabinets."""
from app import db

DAKAR = "dr.diop@demo.getcareassist.com"


def test_login_ok_and_bad_password(client, login):
    assert client.post("/api/auth/login", json={"email": "dr.martin@demo.getcareassist.com", "password": "mauvais-mdp-123"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "inconnu@demo.getcareassist.com", "password": "x"}).status_code == 401
    call = login()
    me = call("GET", "/api/auth/me").json()
    assert me["user"]["role"] == "owner" and me["practice"]["country"] == "FR"
    r = client.post("/api/auth/login", json={"email": "dr.martin@demo.getcareassist.com", "password": "CareAssist-Demo-2026"})
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("Lax", "lax")


def test_passwords_are_bcrypt_hashed(client):
    with db.get_conn() as conn:
        h = conn.execute("SELECT password_hash FROM users LIMIT 1").fetchone()[0]
    assert h.startswith("$2") and "CareAssist" not in h


def test_unauthenticated_and_csrf(client, login):
    client.cookies.clear()
    assert client.get("/api/espace/patients").status_code == 401
    login()
    # requête modifiante sans en-tête CSRF -> 403
    r = client.post("/api/espace/patients", json={"last_name": "Sans", "phone": "06 12 34 56 78"})
    assert r.status_code == 403


def test_logout_invalidates_session(client, login):
    call = login()
    assert call("POST", "/api/auth/logout").status_code == 200
    assert client.get("/api/espace/patients").status_code == 401


def test_signup_creates_isolated_practice(client):
    r = client.post("/api/auth/signup", json={"practice_name": "Cabinet Test Abidjan", "specialty": "generaliste", "country": "CI",
                                               "name": "Dr Test", "email": "test@cabinet-ci.com", "password": "MotDePasse2026"})
    assert r.status_code == 201, r.text
    csrf = r.json()["csrf"]
    me = client.get("/api/auth/me").json()
    assert me["practice"]["timezone"] == "Africa/Abidjan" and me["practice"]["currency"] == "XOF"
    assert client.get("/api/espace/patients").json() == []
    assert len(client.get("/api/espace/slots").json()) > 0
    weak = client.post("/api/auth/signup", json={"practice_name": "X Y", "specialty": "dentiste", "country": "FR", "name": "Dr X",
                                                  "email": "x@cabinet.fr", "password": "court"})
    assert weak.status_code == 422
    assert client.post("/api/espace/patients", json={"last_name": "Kouassi", "phone": "07 07 12 34 56"},
                       headers={"X-CSRF-Token": csrf}).json()["phone_e164"] == "+2250707123456"


def test_tenant_isolation(client, login):
    # Cabinet A (Paris) : ses patients et RDV
    a = login()
    pats_a = a("GET", "/api/espace/patients").json()
    appts_a = a("GET", "/api/espace/appointments").json()
    assert pats_a and appts_a
    pa, ra = pats_a[0]["id"], appts_a[0]["id"]
    # Cabinet B (Dakar) ne voit QUE ses données et ne peut rien lire / modifier / annuler chez A
    b = login(DAKAR)
    pats_b = b("GET", "/api/espace/patients").json()
    assert pats_b and not ({p["id"] for p in pats_b} & {p["id"] for p in pats_a})
    assert all(p["practice_id"] != pats_a[0]["practice_id"] for p in pats_b)
    assert b("GET", f"/api/espace/patients/{pa}").status_code == 404
    assert b("GET", f"/api/espace/patients/{pa}/export").status_code == 404
    assert b("PUT", f"/api/espace/patients/{pa}", json={"last_name": "Pirate"}).status_code == 404
    assert b("DELETE", f"/api/espace/patients/{pa}").status_code == 404
    assert b("POST", f"/api/espace/appointments/{ra}/cancel").status_code == 404
    assert b("PUT", f"/api/espace/appointments/{ra}", json={"status": "no_show"}).status_code == 404
    assert ra not in {x["id"] for x in b("GET", "/api/espace/appointments").json()}
    # B ne peut pas réserver un créneau de A, ni y rattacher son patient
    slot_a = db.get_practice("dentiste")
    from app import booking
    free_a = booking.find_slots(practice_id=slot_a["id"], limit=1)[0]["id"]
    assert b("POST", "/api/espace/appointments", json={"patient_id": pats_b[0]["id"], "slot_id": free_a}).status_code == 409
    assert b("POST", "/api/espace/appointments", json={"patient_id": pa, "slot_id": free_a}).status_code == 404
    # notifications / appels / messages / export : uniquement le cabinet B
    pid_b = pats_b[0]["practice_id"]
    for path in ("/api/espace/notifications", "/api/espace/calls", "/api/espace/messages"):
        assert all(r["practice_id"] == pid_b for r in b("GET", path).json() if "practice_id" in r)
    exp = b("GET", "/api/espace/export?format=json").json()
    assert exp["practice"]["id"] == pid_b and all(p["practice_id"] == pid_b for p in exp["patients"])
    assert all(x["practice_id"] == pid_b for x in exp["appointments"])
    # A n'a pas été modifié
    a = login()
    assert a("GET", f"/api/espace/patients/{pa}").json()["last_name"] == pats_a[0]["last_name"]


def test_roles(client, login):
    sec = login("accueil.parc@demo.getcareassist.com")
    assert sec("GET", "/api/espace/patients").status_code == 200
    assert sec("PUT", "/api/espace/settings", json={"quiet_start": "22:00"}).status_code == 403
    assert sec("GET", "/api/espace/users").status_code == 403
    assert sec("GET", "/api/espace/export").status_code == 200
    prac = login("dr.benali@demo.getcareassist.com")
    assert prac("GET", "/api/espace/export").status_code == 403
    owner = login()
    pid = owner("GET", "/api/espace/patients").json()[0]["id"]
    assert sec is not None
    sec = login("accueil.parc@demo.getcareassist.com")
    assert sec("DELETE", f"/api/espace/patients/{pid}").status_code == 403


def test_patient_crud_phone_validation_and_gdpr(client, login):
    call = login()
    bad = call("POST", "/api/espace/patients", json={"last_name": "Bad", "phone": "12"})
    assert bad.status_code == 422
    p = call("POST", "/api/espace/patients", json={"first_name": "Léa", "last_name": "Test", "phone": "06 12 34 56 78",
                                                    "preferred_channel": "sms"}).json()
    assert p["phone_e164"] == "+33612345678"
    assert call("POST", "/api/espace/patients", json={"last_name": "Doublon", "phone": "+33 6 12 34 56 78"}).status_code == 409
    assert any(x["id"] == p["id"] for x in call("GET", "/api/espace/patients?q=lea").json())
    assert any(x["id"] == p["id"] for x in call("GET", "/api/espace/patients?q=0612").json())
    up = call("PUT", f"/api/espace/patients/{p['id']}", json={"last_name": "Test", "first_name": "Léa", "phone": "0612345678",
                                                            "notify_consent": False}).json()
    assert up["notify_consent"] == 0
    exp = call("GET", f"/api/espace/patients/{p['id']}/export")
    assert exp.status_code == 200 and "attachment" in exp.headers["content-disposition"]
    assert call("DELETE", f"/api/espace/patients/{p['id']}").json()["ok"]
    assert call("GET", f"/api/espace/patients/{p['id']}").status_code == 404
    actions = [r["action"] for r in call("GET", "/api/espace/audit").json()]
    assert "patient.delete" in actions and "patient.export" in actions


def test_settings_validation(client, login):
    call = login()
    assert call("PUT", "/api/espace/settings", json={"timezone": "Mars/Olympus"}).status_code == 422
    assert call("PUT", "/api/espace/settings", json={"quiet_start": "25:00"}).status_code == 422
    assert call("PUT", "/api/espace/settings", json={"voip_number": "+221338000001"}).status_code == 409  # déjà pris (Dakar)
    s = call("PUT", "/api/espace/settings", json={"notify_patient_offsets": [2880, 120], "quiet_end": "07:30"}).json()
    assert s["notify_patient_offsets"] == [2880, 120] and s["quiet_end"] == "07:30"


def test_gdpr_delete_cancels_future_appointments(client, login):
    call = login()
    p = call("POST", "/api/espace/patients", json={"first_name": "Effa", "last_name": "Cement", "phone": "06 12 34 56 11"}).json()
    slot = call("GET", "/api/espace/slots?limit=5").json()
    slot = slot if isinstance(slot, list) else slot["slots"]
    appt = call("POST", "/api/espace/appointments", json={"slot_id": slot[-1]["id"], "patient_id": p["id"]}).json()
    r = call("DELETE", f"/api/espace/patients/{p['id']}").json()
    assert appt["id"] in r["cancelled_appointments"]
    with db.get_conn() as conn:
        a = conn.execute("SELECT status, patient_name FROM appointments WHERE id=?", (appt["id"],)).fetchone()
        booked = conn.execute("SELECT booked FROM slots WHERE id=?", (slot[-1]["id"],)).fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM notifications WHERE appointment_id=? AND status='scheduled'", (appt["id"],)).fetchone()[0]
    assert a["status"] == "cancelled" and a["patient_name"] == "[effacé]" and booked == 0 and pending == 0
