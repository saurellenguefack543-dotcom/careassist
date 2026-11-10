"""VoIP cloud en mode démo : routage par numéro appelé, journal d'appels, appels manqués, messagerie, fournisseurs."""
import json

from app import db, messaging


def _call(provider, cid):
    with db.get_conn() as conn:
        r = conn.execute("SELECT * FROM calls WHERE provider=? AND provider_call_id=?", (provider, cid)).fetchone()
    return dict(r) if r else None


def test_twilio_routes_by_called_number_and_logs_transcript(client):
    r = client.post("/twilio/voice", data={"CallSid": "CA-route", "From": "+33612121212", "To": "+33199000003"})
    assert "Centre Ophtalmologique Vision Plus" in r.text  # numéro du cabinet d'ophtalmologie
    client.post("/twilio/voice", data={"CallSid": "CA-route", "From": "+33612121212", "To": "+33199000003",
                                       "SpeechResult": "Quels sont vos horaires ?"})
    client.post("/twilio/status", data={"CallSid": "CA-route", "CallStatus": "completed", "CallDuration": "42"})
    c = _call("twilio", "CA-route")
    assert c["practice_id"] == db.get_practice("ophtalmologue")["id"]
    assert c["status"] == "completed" and c["duration_s"] == 42 and "horaires" in c["transcript"]


def test_missed_call_sends_callback_sms_once(client):
    for sid in ("CA-miss1", "CA-miss2"):
        client.post("/twilio/voice", data={"CallSid": sid, "From": "+33613131313", "To": "+33199000001"})
        client.post("/twilio/status", data={"CallSid": sid, "CallStatus": "completed", "CallDuration": "3"})
    assert _call("twilio", "CA-miss1")["status"] == "missed"
    with db.get_conn() as conn:
        rows = db.rows(conn.execute("SELECT * FROM notifications WHERE kind='callback_offer' AND to_addr='+33613131313'"))
    assert len(rows) == 1  # un seul SMS par numéro et par jour
    assert rows[0]["status"] in ("mock_sent", "scheduled")  # « scheduled » si on est dans les heures calmes


def test_twilio_silence_goes_to_voicemail_then_sms(client):
    q = {"CallSid": "CA-vm", "From": "+33614141414", "To": "+33199000001"}
    client.post("/twilio/voice", data=q)
    client.post("/twilio/voice?retry=1", data=q)
    r = client.post("/twilio/voice?retry=2", data=q)
    assert "<Record" in r.text
    r = client.post("/twilio/voicemail", data={**q, "RecordingUrl": "https://api.twilio.com/rec/RE1", "TranscriptionText": "Rappelez-moi"})
    assert "<Hangup/>" in r.text
    c = _call("twilio", "CA-vm")
    assert c["status"] == "voicemail" and c["voicemail_text"] == "Rappelez-moi"


def test_human_transfer_uses_practice_number(client):
    with db.get_conn() as conn:
        conn.execute("UPDATE practices SET transfer_number='+33199009999' WHERE slug='dentiste'")
    r = client.post("/twilio/voice", data={"CallSid": "CA-h", "To": "+33199000001", "SpeechResult": "Je voudrais parler à une personne du secrétariat"})
    assert "<Dial" in r.text and "+33199009999" in r.text and "/twilio/dial-status" in r.text
    r = client.post("/twilio/dial-status", data={"CallSid": "CA-h", "DialCallStatus": "no-answer"})
    assert "<Record" in r.text


def test_vonage_ncco_flow(client):
    r = client.get("/vonage/answer", params={"to": "237233000001", "from": "237670000199", "uuid": "V-1"})
    ncco = r.json()
    assert ncco[0]["action"] == "talk" and "Bonapriso" in ncco[0]["text"] and ncco[1]["action"] == "input"
    r = client.post("/vonage/input?practice=douala-bonapriso", json={"uuid": "V-1", "to": "237233000001", "from": "237670000199",
                                                                   "speech": {"results": [{"text": "j'ai une douleur dans la poitrine", "confidence": 0.9}]}})
    assert "119" in r.json()[0]["text"]  # numéro du SAMU au Cameroun
    client.post("/vonage/event", json={"uuid": "V-1", "status": "completed", "duration": "31"})
    c = _call("vonage", "V-1")
    assert c["practice_id"] == db.get_practice("douala-bonapriso")["id"] and c["status"] == "completed" and c["duration_s"] == 31


def test_africastalking_menu_and_end(client):
    base = {"sessionId": "AT-1", "isActive": "1", "callerNumber": "+221770000199", "destinationNumber": "+221338000001"}
    r = client.post("/africastalking/voice", data=base)
    assert "<GetDigits" in r.text and "Almadies" in r.text
    r = client.post("/africastalking/voice", data={**base, "dtmfDigits": "2"})
    assert "1515" in r.text  # SAMU Sénégal
    r = client.post("/africastalking/voice", data={**base, "dtmfDigits": "1"})
    assert "SMS" in r.text
    client.post("/africastalking/voice", data={**base, "isActive": "0", "durationInSeconds": "25", "status": "Success"})
    c = _call("africastalking", "AT-1")
    assert c["status"] == "completed" and c["duration_s"] == 25
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM channel_messages WHERE to_addr='+221770000199' AND status='mock_sent'").fetchone()[0] >= 1


def test_inbound_sms_vonage_and_at(client):
    r = client.post("/vonage/inbound-sms", json={"msisdn": "237670000101", "to": "237233000001", "text": "OUI", "messageId": "x"})
    assert r.json()["reply_status"] == "mock_sent"
    r = client.post("/africastalking/sms", data={"from": "+221770000101", "to": "+221338000001", "text": "RDV", "id": "1"})
    assert r.json()["action"] == "callback_request"


def test_mock_mode_never_calls_network(client, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("appel réseau interdit")))
    p = db.get_practice("dentiste")
    for ch in ("sms", "whatsapp", "email"):
        assert messaging.send(p, ch, "+33612345678" if ch != "email" else "a@b.fr", "test")["status"] == "mock_sent"


def test_demo_practice_never_sends_live_even_with_keys(client, monkeypatch):
    import httpx
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("appel réseau interdit")))
    assert messaging.send(db.get_practice("dentiste"), "sms", "+33612345678", "x")["status"] == "mock_sent"


def test_provider_payload_shapes(client, monkeypatch):
    calls = []

    class R:
        def __init__(self, j): self._j = j
        def raise_for_status(self): pass
        def json(self): return self._j

    def fake_post(url, data=None, headers=None, auth=None, timeout=None):
        calls.append({"url": url, "data": data, "headers": headers, "auth": auth})
        if "twilio" in url:
            return R({"sid": "SM123", "status": "queued"})
        if "nexmo" in url:
            return R({"message-count": "1", "messages": [{"status": "0", "message-id": "V123"}]})
        return R({"SMSMessageData": {"Recipients": [{"statusCode": 101, "status": "Success", "messageId": "ATX1"}]}})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    for k, v in {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t", "TWILIO_FROM": "+15005550006", "VONAGE_API_KEY": "k",
                 "VONAGE_API_SECRET": "s", "AT_USERNAME": "sandbox", "AT_API_KEY": "atk", "TWILIO_WHATSAPP_FROM": "+14155238886"}.items():
        monkeypatch.setenv(k, v)
    live = {**db.get_practice("dentiste"), "is_demo": 0}
    assert messaging.send({**live, "voip_provider": "twilio"}, "sms", "+33612345678", "a")["provider_message_id"] == "SM123"
    assert calls[-1]["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json" and calls[-1]["auth"] == ("AC1", "t")
    messaging.send({**live, "voip_provider": "twilio"}, "whatsapp", "+33612345678", "a")
    assert calls[-1]["data"]["To"] == "whatsapp:+33612345678" and calls[-1]["data"]["From"] == "whatsapp:+14155238886"
    assert messaging.send({**live, "voip_provider": "vonage"}, "sms", "+237670000101", "b")["provider_message_id"] == "V123"
    assert calls[-1]["url"] == "https://rest.nexmo.com/sms/json" and calls[-1]["data"]["to"] == "237670000101"
    assert messaging.send({**live, "voip_provider": "africastalking"}, "sms", "+254712345678", "c")["provider_message_id"] == "ATX1"
    assert calls[-1]["url"] == "https://api.sandbox.africastalking.com/version1/messaging" and calls[-1]["headers"]["apiKey"] == "atk"
