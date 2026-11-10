from app import db


def test_full_booking_conversation(chat, client):
    r = chat("Bonjour, je voudrais un détartrage demain matin")
    assert r["intent"] == "booking" and len(r["slots"]) >= 1 and r["engine"] == "rules"
    r = chat("le premier")
    assert "nom" in r["reply"].lower()
    r = chat("Je m'appelle Marie Dupont, 06 12 34 56 78")
    assert "récapitule" in r["reply"] and "Marie Dupont" in r["reply"]
    r = chat("oui")
    assert r["intent"] == "booked"
    appt = r["appointment"]
    assert appt["patient_name"] == "Marie Dupont" and appt["appointment_type"] == "detartrage"
    # journalisé côté admin
    convs = client.get("/api/admin/conversations").json()
    assert convs[0]["n_messages"] == 8
    assert client.get("/api/admin/appointments").json()[0]["id"] == appt["id"]


def test_cancel_flow(chat):
    chat("Je voudrais un rendez-vous", session="a")
    chat("2", session="a")
    chat("Paul Martin 0611223344", session="a")
    assert chat("oui", session="a")["intent"] == "booked"
    r = chat("Je dois annuler mon rendez-vous", session="b")
    assert "numéro" in r["reply"]
    r = chat("06 11 22 33 44", session="b")
    assert "Souhaitez-vous l'annuler" in r["reply"]
    assert chat("oui", session="b")["intent"] == "cancelled"


def test_reschedule_flow(chat):
    chat("Je voudrais un rendez-vous", session="r", practice="generaliste")
    chat("le premier", session="r", practice="generaliste")
    chat("Je m'appelle Léa Petit, 07 88 77 66 55", session="r", practice="generaliste")
    first = chat("oui", session="r", practice="generaliste")["appointment"]
    r = chat("Je voudrais déplacer mon rendez-vous", session="r", practice="generaliste")
    assert "déplacer" in r["reply"]
    r = chat("oui", session="r", practice="generaliste")
    assert r["slots"]
    chat("le deuxième", session="r", practice="generaliste")
    r = chat("oui", session="r", practice="generaliste")
    assert r["intent"] == "booked" and "ancien rendez-vous a bien été annulé" in r["reply"]
    with db.get_conn() as conn:
        status = conn.execute("SELECT status FROM appointments WHERE id=?", (first["id"],)).fetchone()[0]
    assert status == "cancelled"


def test_dental_emergency_gets_priority_slot(chat, client):
    r = chat("J'ai la joue gonflée et très mal depuis hier soir", session="e")
    assert r["emergency"]["level"] == "urgent" and r["slots"]
    assert "froid" in r["reply"]
    chat("le premier", session="e")
    chat("Je m'appelle Hugo Blanc, 06 55 44 33 22", session="e")
    r = chat("oui", session="e")
    assert r["intent"] == "booked" and r["appointment"]["urgent"] is True
    assert client.get("/api/admin/emergencies").json()[0]["level"] == "urgent"


def test_psy_suicidal_message_gives_3114_and_15(chat):
    r = chat("Je pense à en finir", session="p", practice="psychologue")
    assert r["emergency"]["level"] == "vital"
    assert "3114" in r["reply"] and "15" in r["reply"]
    assert not r["slots"]


def test_gp_chest_pain_says_call_15(chat):
    r = chat("J'ai une douleur dans la poitrine", session="g", practice="generaliste")
    assert r["emergency"]["level"] == "vital" and "15" in r["reply"]


def test_kine_red_flag_redirects_without_booking(chat):
    r = chat("Mon mollet est gonflé et chaud depuis l'opération", session="k", practice="kinesitherapeute")
    assert r["emergency"]["action"] == "redirect" and r["handoff"] is True and not r["slots"]


def test_faq_per_specialty(chat):
    assert "Mon soutien psy" in chat("Les séances sont-elles remboursées ?", session="f1", practice="psychologue")["reply"]
    assert "ordonnance" in chat("Faut-il une ordonnance ?", session="f2", practice="kinesitherapeute")["reply"]
    assert "C2S" in chat("Vous prenez la CMU ?", session="f3", practice="dentiste")["reply"]
    assert "lundi" in chat("Quels sont vos horaires ?", session="f4", practice="ophtalmologue")["reply"]


def test_human_handoff(chat):
    r = chat("Je voudrais parler à une vraie personne", session="h")
    assert r["handoff"] is True


def test_prompt_contains_overlay(client):
    p = client.get("/api/prompt", params={"practice": "psychologue"}).json()["prompt"]
    assert "3114" in p and "jamais d'analyse" in p and "Les Tilleuls" in p
