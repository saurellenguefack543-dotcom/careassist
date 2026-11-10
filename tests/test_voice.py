def test_twilio_greeting_and_gather(client):
    r = client.post("/twilio/voice", data={"CallSid": "CA123"})
    assert r.status_code == 200 and "xml" in r.headers["content-type"]
    assert '<Gather input="speech" language="fr-FR"' in r.text and "Bonjour" in r.text


def test_twilio_speech_turn_books(client):
    r = client.post("/twilio/voice?practice=ophtalmologue", data={"CallSid": "CA9", "SpeechResult": "Je voudrais un rendez-vous pour mes lunettes"})
    assert "Je vous propose" in r.text and "<Gather" in r.text


def test_twilio_vital_emergency_hangs_up(client):
    r = client.post("/twilio/voice?practice=generaliste", data={"CallSid": "CA7", "SpeechResult": "j'ai une douleur dans la poitrine"})
    assert "15" in r.text and "<Hangup/>" in r.text


def test_vapi_custom_llm(client):
    body = {"model": "x", "call": {"id": "call-1"}, "messages": [{"role": "user", "content": "Quels sont vos horaires ?"}]}
    r = client.post("/vapi/chat/completions?practice=dentiste", json=body).json()
    assert "lundi" in r["choices"][0]["message"]["content"]
    r = client.post("/vapi/chat/completions", json={**body, "stream": True})
    assert r.text.startswith("data: ") and "[DONE]" in r.text


def test_vapi_tool_calls(client):
    msg = {"message": {"type": "tool-calls", "toolCallList": [
        {"id": "t1", "function": {"name": "check_availability", "arguments": {"limit": 1}}}]}}
    res = client.post("/vapi/webhook?practice=kinesitherapeute", json=msg).json()["results"][0]
    assert res["toolCallId"] == "t1" and "slot_id" in res["result"]
