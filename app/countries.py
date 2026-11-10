"""Profils pays : fuseau, indicatif, devise, canaux préférés, langues, formats, numéros d'urgence.

RÈGLE : un numéro d'urgence n'est renseigné que s'il a été vérifié sur une source officielle ou fiable
(liste `sources`). Sinon le profil porte `emergency_verified: False` + un TODO, et l'assistante oriente
vers « les services d'urgence locaux » sans inventer de numéro.

Les autres langues (wolof, arabe, swahili, haoussa, portugais…) sont extensibles : ajouter le code dans
`languages` et les traductions côté UI / prompt.
"""
from __future__ import annotations

from .pricing import region_for_country, get_region

COUNTRIES: dict[str, dict] = {
    "FR": {
        "name": "France", "timezone": "Europe/Paris", "dial_code": "+33", "phone_example": "06 12 34 56 78",
        "languages": ["fr", "en"], "preferred_channels": ["sms", "email"],
        "date_format": "%d/%m/%Y", "time_format": "%Hh%M",
        "emergency_verified": True,
        "emergency": {"samu": "15", "general": "112", "police": "17", "pompiers": "18", "suicide": "3114",
                      "sourds": "114", "violences": "3919", "permanence_soins": "116 117"},
        "sources": [
            "https://www.service-public.gouv.fr/particuliers/vosdroits/F33954",
            "https://www.masecurite.interieur.gouv.fr/fr/practical-sheets/les-numeros-nationaux",
            "https://solidarites.gouv.fr/tous-les-contacts-utiles",
        ],
        "patient_docs": "votre carte Vitale",
    },
    "SN": {
        "name": "Sénégal", "timezone": "Africa/Dakar", "dial_code": "+221", "phone_example": "77 123 45 67",
        "languages": ["fr", "en"], "preferred_channels": ["whatsapp", "sms"],
        "date_format": "%d/%m/%Y", "time_format": "%Hh%M",
        "emergency_verified": True,
        "emergency": {"samu": "1515", "police": "17", "pompiers": "18"},
        "todo": "Aucune ligne nationale de prévention du suicide vérifiée : à compléter.",
        "sources": [
            "https://www.sante.gouv.sn/Pr%C3%A9sentation/la-d%C3%A9couverte-du-samu-national",
            "https://samu.sn/",
            "https://www.policenationale.gouv.sn/contact/",
            "https://sapeurspompiers.gouv.sn/contact",
        ],
        "patient_docs": "votre carnet de santé et votre carte d'assurance ou d'IPM si vous en avez une",
    },
    "CI": {
        "name": "Côte d'Ivoire", "timezone": "Africa/Abidjan", "dial_code": "+225", "phone_example": "07 07 12 34 56",
        "languages": ["fr", "en"], "preferred_channels": ["whatsapp", "sms"],
        "date_format": "%d/%m/%Y", "time_format": "%Hh%M",
        "emergency_verified": True,
        "emergency": {"samu": "185", "pompiers": "180", "police": "110 / 111 / 170"},
        "todo": "Aucune ligne nationale de prévention du suicide vérifiée : à compléter.",
        "sources": [
            "https://www.orange.ci/fr/fixe-numeros-utiles.html",
            "https://ci.diplomatie.gouv.fr/en-cas-durgence",
        ],
        "patient_docs": "votre carnet de santé et votre carte d'assurance si vous en avez une",
    },
    "CM": {
        "name": "Cameroun", "timezone": "Africa/Douala", "dial_code": "+237", "phone_example": "6 77 12 34 56",
        "languages": ["fr", "en"], "preferred_channels": ["whatsapp", "sms"],
        "date_format": "%d/%m/%Y", "time_format": "%Hh%M",
        "emergency_verified": True,
        "emergency": {"samu": "119", "police": "117", "pompiers": "118"},
        "todo": "Aucune ligne nationale de prévention du suicide vérifiée : à compléter.",
        "sources": [
            "https://minat.gov.cm/ (encart « Numéros d'urgence » : 119 assistance médicale, 117 police)",
            "https://yaounde.consulfrance.org/Numeros-d-urgence-400 (pompiers 118 depuis un portable)",
        ],
        "patient_docs": "votre carnet de santé et votre carte d'assurance si vous en avez une",
    },
    # ---- profils sans numéros vérifiés (TODO) : l'assistante n'invente aucun numéro
    "MA": {"name": "Maroc", "timezone": "Africa/Casablanca", "dial_code": "+212", "phone_example": "06 12 34 56 78",
           "languages": ["fr", "en"], "preferred_channels": ["whatsapp", "sms"],
           "date_format": "%d/%m/%Y", "time_format": "%Hh%M", "emergency_verified": False, "emergency": {},
           "todo": "TODO : vérifier les numéros d'urgence sur une source officielle avant activation.", "sources": []},
    "NG": {"name": "Nigeria", "timezone": "Africa/Lagos", "dial_code": "+234", "phone_example": "0803 123 4567",
           "languages": ["en", "fr"], "preferred_channels": ["whatsapp", "sms"],
           "date_format": "%d/%m/%Y", "time_format": "%H:%M", "emergency_verified": False, "emergency": {},
           "todo": "TODO : vérifier les numéros d'urgence sur une source officielle avant activation.", "sources": []},
    "KE": {"name": "Kenya", "timezone": "Africa/Nairobi", "dial_code": "+254", "phone_example": "0712 345678",
           "languages": ["en", "fr"], "preferred_channels": ["whatsapp", "sms"],
           "date_format": "%d/%m/%Y", "time_format": "%H:%M", "emergency_verified": False, "emergency": {},
           "todo": "TODO : vérifier les numéros d'urgence sur une source officielle avant activation.", "sources": []},
    "GH": {"name": "Ghana", "timezone": "Africa/Accra", "dial_code": "+233", "phone_example": "024 123 4567",
           "languages": ["en", "fr"], "preferred_channels": ["whatsapp", "sms"],
           "date_format": "%d/%m/%Y", "time_format": "%H:%M", "emergency_verified": False, "emergency": {},
           "todo": "TODO : vérifier les numéros d'urgence sur une source officielle avant activation.", "sources": []},
    "BE": {"name": "Belgique", "timezone": "Europe/Brussels", "dial_code": "+32", "phone_example": "0470 12 34 56",
           "languages": ["fr", "en"], "preferred_channels": ["sms", "email"],
           "date_format": "%d/%m/%Y", "time_format": "%Hh%M", "emergency_verified": False, "emergency": {},
           "todo": "TODO : vérifier les numéros d'urgence (112 européen) sur une source officielle belge.", "sources": []},
}

DEFAULT_COUNTRY = "FR"


def get_country(code: str | None) -> dict:
    code = (code or DEFAULT_COUNTRY).upper()
    prof = dict(COUNTRIES.get(code) or COUNTRIES[DEFAULT_COUNTRY])
    prof["code"] = code if code in COUNTRIES else DEFAULT_COUNTRY
    region = get_region(region_for_country(prof["code"]))
    prof["currency"] = region["currency"] if region else "EUR"
    prof["pricing_region"] = region["key"] if region else None
    return prof


def public_countries() -> list[dict]:
    out = []
    for code in COUNTRIES:
        p = get_country(code)
        out.append({k: p.get(k) for k in ("code", "name", "timezone", "dial_code", "currency", "languages",
                                          "preferred_channels", "emergency", "emergency_verified", "sources", "todo")})
    return out


# ---------------------------------------------------------------- localisation des messages d'urgence

def emergency_phrases(prof: dict) -> dict[str, str]:
    e = prof.get("emergency") or {}
    code = prof.get("code")
    if code == "FR":
        return {
            "SAMU": "le 15 (SAMU) ou le 112",
            "SAMU_SHORT": "le 15",
            "SAMU_NUM": "15",
            "SAMU_OR_112": "le 15 (ou 112)",
            "POLICE": "le 17 (police) ou le 112",
            "AFTER_HOURS": "En dehors des heures d'ouverture, appelez le 116 117 (permanence des soins) pour un avis médical, ou le 15 en cas d'urgence vitale.",
        }
    if e.get("samu"):
        samu = f"le {e['samu']} (SAMU)"
        police = f"le {e['police']} (police)" if e.get("police") else "la police"
        return {"SAMU": samu, "SAMU_SHORT": f"le {e['samu']}", "SAMU_NUM": e["samu"], "SAMU_OR_112": samu,
                "POLICE": police,
                "AFTER_HOURS": f"En dehors des heures d'ouverture, rendez-vous au service d'urgences le plus proche ou appelez {samu} en cas d'urgence vitale."}
    gen = "les services d'urgence de votre pays"
    return {"SAMU": gen, "SAMU_SHORT": gen, "SAMU_NUM": "les urgences", "SAMU_OR_112": gen, "POLICE": "la police",
            "AFTER_HOURS": "En dehors des heures d'ouverture, rendez-vous au service d'urgences le plus proche."}


def suicide_phrase(prof: dict) -> str:
    e = prof.get("emergency") or {}
    if e.get("suicide"):
        return f"le {e['suicide']}, le numéro national de prévention du suicide : c'est gratuit, 24h/24, et des professionnels peuvent vous écouter"
    ph = emergency_phrases(prof)
    return f"{ph['SAMU']} ou rendez-vous aux urgences les plus proches : des professionnels peuvent vous aider tout de suite"


def localize(text: str, prof: dict) -> str:
    """Remplace les jetons [[SAMU]], [[SAMU_SHORT]], [[POLICE]]… par les numéros du pays du cabinet."""
    if not text or "[[" not in text:
        return text
    for k, v in emergency_phrases(prof).items():
        text = text.replace(f"[[{k}]]", v)
    text = text.replace("[[SUICIDE]]", suicide_phrase(prof))
    return text


def prompt_block(prof: dict) -> str:
    e = prof.get("emergency") or {}
    nums = ", ".join(f"{k} : {v}" for k, v in e.items()) or "AUCUN NUMÉRO VÉRIFIÉ (TODO) : oriente vers les urgences locales, n'invente aucun numéro"
    return (f"- Pays : {prof['name']} ({prof['code']}) — fuseau {prof['timezone']}, indicatif {prof['dial_code']}, devise {prof['currency']}\n"
            f"- Numéros d'urgence à utiliser (uniquement ceux-ci) : {nums}\n"
            f"- Canaux de contact privilégiés : {', '.join(prof['preferred_channels'])}\n"
            f"- Format des numéros : international E.164 (ex. {prof['dial_code']} …), exemple local {prof['phone_example']}")
