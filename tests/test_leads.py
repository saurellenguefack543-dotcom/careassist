def test_lead_ok(client):
    r = client.post("/api/leads", json={"practice_name": "Cabinet Dr Martin", "email": "dr.martin@example.fr",
                                        "phone": "01 23 45 67 89", "specialty": "dentiste"})
    assert r.status_code == 201 and r.json()["ok"]
    leads = client.get("/api/admin/leads").json()
    assert leads[0]["email"] == "dr.martin@example.fr" and leads[0]["specialty"] == "dentiste"


def test_lead_validation(client):
    assert client.post("/api/leads", json={"practice_name": "X Cab", "email": "pas-un-email", "phone": "0123456789"}).status_code == 422
    assert client.post("/api/leads", json={"practice_name": "X Cab", "email": "a@b.fr", "phone": "12"}).status_code == 422
    assert client.post("/api/leads", json={"email": "a@b.fr", "phone": "0123456789"}).status_code == 422


def test_admin_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    assert client.get("/api/admin/leads").status_code == 401
    assert client.get("/api/admin/leads", headers={"X-Admin-Token": "secret"}).status_code == 200
