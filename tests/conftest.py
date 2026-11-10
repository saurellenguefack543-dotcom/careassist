import os

import pytest

# Aucun LLM pendant les tests : on valide le moteur de règles déterministe.
for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
    os.environ.pop(k, None)
os.environ["LLM_DISABLED"] = "1"
os.environ["ADMIN_TOKEN"] = ""
os.environ["TWILIO_VALIDATE"] = "false"
os.environ["ADMIN_OPEN"] = "1"          # super-admin ouvert en test uniquement (protégé par défaut)
os.environ["SCHEDULER_ENABLED"] = "0"   # pas de thread APScheduler pendant les tests
os.environ["RATE_LIMIT_ENABLED"] = "0"
os.environ["BCRYPT_ROUNDS"] = "4"       # hachage rapide en test
for k in ("TWILIO_ACCOUNT_SID", "VONAGE_API_KEY", "AT_API_KEY", "SMTP_HOST", "STRIPE_SECRET_KEY", "FLW_SECRET_KEY", "PAYSTACK_SECRET_KEY"):
    os.environ.pop(k, None)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CALENDAR_BACKEND", "mock_google")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def chat(client):
    def _chat(message, session="s1", practice="dentiste"):
        r = client.post("/api/chat", json={"message": message, "session_id": session, "practice": practice})
        assert r.status_code == 200, r.text
        return r.json()
    return _chat


PW = "CareAssist-Demo-2026"


@pytest.fixture()
def login(client):
    """Connecte un compte de démo et renvoie une fonction d'appel API avec le jeton CSRF."""
    def _login(email="dr.martin@demo.getcareassist.com", password=PW):
        client.cookies.clear()
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        csrf = r.json()["csrf"]

        def call(method, path, **kw):
            headers = kw.pop("headers", {})
            if method.upper() != "GET":
                headers["X-CSRF-Token"] = csrf
            return client.request(method, path, headers=headers, **kw)
        return call
    return _login
