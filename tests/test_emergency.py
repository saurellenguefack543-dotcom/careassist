import pytest

from app.emergency import detect

CASES = [
    # (spécialité, message, niveau attendu, action attendue, catégorie attendue)
    ("dentiste", "J'ai la joue gonflée et très mal", "urgent", "priority_slot", "gonflement"),
    ("dentiste", "Mon fils est tombé, il a une dent cassée", "urgent", "priority_slot", "traumatisme"),
    ("dentiste", "Le gonflement descend dans le cou et j'ai du mal à avaler", "vital", "samu", "cellulite"),
    ("dentiste", "J'ai une rage de dents insupportable", "urgent", "priority_slot", "douleur"),
    ("psychologue", "Je pense à en finir, je n'ai plus envie de vivre", "vital", "samu_psy", "suicide"),
    ("psychologue", "Je suis en pleine crise d'angoisse", "urgent", "soonest_slot", "crise"),
    ("psychologue", "Mon conjoint me frappe, je suis en danger", "vital", "samu_danger", "danger"),
    ("ophtalmologue", "J'ai reçu de la javel dans l'œil", "vital", "samu", "brulure_chimique"),
    ("ophtalmologue", "Perte brutale de la vue de l'œil droit", "vital", "samu", "perte_vision"),
    ("ophtalmologue", "Je vois comme un rideau noir sur le côté", "vital", "samu", "perte_vision"),
    ("ophtalmologue", "Je vois des éclairs et des mouches volantes", "urgent", "priority_slot", "decollement"),
    ("generaliste", "J'ai une douleur dans la poitrine qui serre", "vital", "samu", "douleur_thoracique"),
    ("generaliste", "Mon père a la bouche de travers et n'arrive plus à parler", "vital", "samu", "avc"),
    ("generaliste", "Mon bébé de 2 mois a 39 de fièvre", "vital", "samu", "fievre_nourrisson"),
    ("generaliste", "J'ai de la fièvre et mal à la gorge depuis hier", "urgent", "priority_slot", "soins_du_jour"),
    ("kinesitherapeute", "Mon mollet est gonflé et chaud depuis l'opération", "urgent", "redirect", "phlebite"),
    ("kinesitherapeute", "Ma cicatrice est rouge et coule", "urgent", "redirect", "cicatrice_infection"),
    ("kinesitherapeute", "Je suis essoufflé brutalement depuis ce matin", "vital", "samu", "embolie"),
]


@pytest.mark.parametrize("specialty,text,level,action,category", CASES)
def test_specialty_emergencies(specialty, text, level, action, category):
    r = detect(text, specialty)
    assert r.level == level, r
    assert r.action == action, r
    assert category in r.categories


@pytest.mark.parametrize("specialty", ["dentiste", "psychologue", "ophtalmologue", "generaliste", "kinesitherapeute"])
def test_common_vital_rules_apply_everywhere(specialty):
    assert detect("J'ai du mal à respirer", specialty).level == "vital"
    assert detect("je veux me suicider", specialty).action == "samu_psy"


@pytest.mark.parametrize("specialty,text", [
    ("dentiste", "Je voudrais un détartrage mardi"),
    ("psychologue", "Je voudrais un premier rendez-vous"),
    ("ophtalmologue", "Renouvellement de lunettes"),
    ("generaliste", "Un certificat médical pour le sport"),
    ("kinesitherapeute", "Rééducation après mon opération du genou"),
])
def test_no_false_positive(specialty, text):
    assert detect(text, specialty).level == "none"


def test_specialty_rules_are_scoped():
    # un mollet gonflé est une alerte en kiné, pas une règle dentaire
    assert detect("mon mollet est gonflé", "kinesitherapeute").action == "redirect"
    assert detect("des éclairs dans l'œil", "dentiste").level == "none"


def test_emergency_api(client):
    r = client.post("/api/emergency/check", json={"message": "J'ai reçu de l'acide dans les yeux", "practice": "ophtalmologue"}).json()
    assert r["level"] == "vital"
