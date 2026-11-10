"""Forfaits Gratuit / Premium, essai 14 jours, quotas et rappels d\'échéance."""
from datetime import datetime, timedelta, timezone

from app import db, plans


def _signup(client, email="nouveau@cabinet-test.fr", name="Cabinet Essai Lille"):
    r = client.post("/api/auth/signup", json={
        "practice_name": name, "specialty": "dentiste", "country": "FR",
        "name": "Dr Essai", "email": email, "password": "MotDePasse2026",
    })
    assert r.status_code == 201, r.text
    return r.json(), client.get("/api/auth/me").json()


def test_pricing_exposes_plans_and_trial(client):
    j = client.get("/api/pricing").json()
    assert j["trial_days"] == 14
    assert j["plans"]["free"]["ai_conversations_per_month"] == 30
    assert j["plans"]["free"]["users"] == 1
    assert j["plans"]["free"]["channels"] == ["email"]
    assert j["plans"]["free"]["voip"] is False
    assert "Propulsé par CareAssist" in j["plans"]["free"]["badge"]


def test_demo_practices_stay_premium(client, login):
    me = login()("GET", "/api/auth/me").json()
    assert me["plan"]["plan"] == "premium"
    assert me["plan"]["is_demo"] is True
    assert me["plan"]["subscription_status"] == "active"
    p = db.get_practice(me["practice"]["id"])
    plans.apply_free(p["id"])
    p = db.get_practice(p["id"])
    assert plans.effective_plan(p) == "premium"


def test_signup_starts_premium_trial(client):
    raw, me = _signup(client)
    assert "trial_days" in raw or me["plan"]["trialing"] is True
    assert me["plan"]["plan"] == "premium"
    assert me["plan"]["trialing"] is True
    assert me["plan"]["trial_days_left"] in (13, 14)
    assert me["listing"]["listing_status"] == "pending"


def test_trial_expiry_downgrade_and_end_email(client):
    _signup(client, email="fin-essai@cabinet-test.fr", name="Cabinet Fin Essai")
    me = client.get("/api/auth/me").json()
    pid = me["practice"]["id"]
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with db.get_conn() as conn:
        conn.execute("UPDATE practices SET trial_ends_at=?, trial_notice_end=0 WHERE id=?", (past, pid))
    stats = plans.process_trials(datetime.now(timezone.utc))
    assert stats["expired"] >= 1
    p = db.get_practice(pid)
    assert plans.effective_plan(p) == "free"
    assert p["subscription_status"] == "free"
    assert p["trial_notice_end"] in (1, True)


def test_trial_reminder_three_days_before(client):
    _signup(client, email="j3@cabinet-test.fr", name="Cabinet Rappel J3")
    me = client.get("/api/auth/me").json()
    pid = me["practice"]["id"]
    soon = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    with db.get_conn() as conn:
        conn.execute("UPDATE practices SET trial_ends_at=?, trial_notice_3d=0, subscription_status=? WHERE id=?",
                     (soon, "trialing", pid))
    stats = plans.process_trials(datetime.now(timezone.utc))
    assert stats["reminded"] >= 1
    p = db.get_practice(pid)
    assert p["trial_notice_3d"] in (1, True)
    assert plans.effective_plan(p) == "premium"  # toujours en essai


def test_free_ai_quota_blocks_new_conversations(client):
    _signup(client, email="quota@cabinet-test.fr", name="Cabinet Quota")
    me = client.get("/api/auth/me").json()
    slug = me["practice"]["slug"]
    plans.apply_free(me["practice"]["id"])
    for i in range(30):
        r = client.post("/api/chat", json={"message": "Bonjour, quels sont vos horaires ?", "session_id": f"quota-{i}", "practice": slug})
        assert r.status_code == 200, r.text
        assert r.json()["intent"] != "quota"
    blocked = client.post("/api/chat", json={"message": "Bonjour encore", "session_id": "quota-new", "practice": slug})
    assert blocked.status_code == 200
    assert blocked.json()["intent"] == "quota"
    # une conversation déjà ouverte peut continuer
    cont = client.post("/api/chat", json={"message": "Et samedi ?", "session_id": "quota-0", "practice": slug})
    assert cont.status_code == 200
    assert cont.json()["intent"] != "quota"


def test_free_plan_blocks_extra_user_and_voip(client):
    raw, me = _signup(client, email="limites@cabinet-test.fr", name="Cabinet Limites")
    csrf = raw["csrf"]
    plans.apply_free(me["practice"]["id"])
    r = client.post("/api/espace/users", json={
        "name": "Secrétaire", "email": "sec@cabinet-test.fr", "role": "secretary", "password": "MotDePasse2026",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code in (403, 409, 422)
    r = client.put("/api/espace/settings", json={"voip_number": "01 23 45 67 89"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403


def test_upgrade_activates_premium(client):
    _signup(client, email="upgrade@cabinet-test.fr", name="Cabinet Upgrade")
    me = client.get("/api/auth/me").json()
    plans.apply_free(me["practice"]["id"])
    assert plans.effective_plan(db.get_practice(me["practice"]["id"])) == "free"
    pid = plans.activate_subscription_for_email("upgrade@cabinet-test.fr", me["practice"]["id"])
    assert pid == me["practice"]["id"]
    p = db.get_practice(pid)
    assert plans.effective_plan(p) == "premium"
    assert p["subscription_status"] == "active"
