"""Tarification régionale de CareAssist : un seul plan par région, appels illimités.

Référence : Europe, 299 EUR/mois HT.

!! PRIX INDICATIFS À VALIDER !!
Les prix hors zone euro ci-dessous sont des EXEMPLES PAR DÉFAUT, ajustés grossièrement au pouvoir
d'achat et au marché local. Ce ne sont ni des conversions de change exactes ni des prix
validés. Modifiez-les ici (ou dans PRICING_FILE, voir plus bas) avant toute commercialisation. Les
équivalents en euros (`approx_eur`) sont approximatifs (sauf XOF/XAF, à parité fixe 655,957 pour 1 EUR)
et doivent être recalculés au taux du jour.

Montants exprimés dans l'unité principale de la devise (ex. 299 = 299,00 EUR). La conversion vers
l'unité minimale propre à chaque prestataire est faite dans payments.py.

Surcharge possible sans toucher au code : définir PRICING_FILE=/chemin/pricing.json (même structure
que REGIONS : {"<clé>": {"amount": ..., ...}}), les clés fournies remplacent les valeurs par défaut.
"""
from __future__ import annotations

import copy
import json
import os

DISCLAIMER_FR = "Prix indicatifs à valider : exemples par défaut, à ajuster avant commercialisation."
REFERENCE_REGION = "europe"

REGIONS: dict[str, dict] = {
    "europe": {
        "label": "Europe (zone euro)", "label_en": "Europe (euro area)",
        "currency": "EUR", "amount": 299, "approx_eur": 299, "reference": True, "indicative": False,
        "provider": "stripe", "methods": ["Carte bancaire", "Prélèvement SEPA"],
        "stripe_payment_method_types": ["card", "sepa_debit"],
        "countries": ["FR", "BE", "LU", "DE", "ES", "IT", "PT", "NL", "IE", "AT", "FI", "GR", "MC"],
    },
    "international": {
        "label": "International (USD)", "label_en": "International (USD)",
        "currency": "USD", "amount": 329, "approx_eur": 299, "indicative": True,
        "provider": "stripe", "methods": ["Carte bancaire"], "stripe_payment_method_types": ["card"],
        "countries": ["US", "CA", "GB", "CH"],
    },
    "uemoa": {
        "label": "Afrique de l'Ouest — UEMOA (FCFA XOF)", "label_en": "West Africa — WAEMU (CFA franc XOF)",
        "currency": "XOF", "amount": 59000, "approx_eur": 90, "indicative": True,
        "provider": "flutterwave", "methods": ["Carte bancaire", "Orange Money", "MTN MoMo", "Moov Money", "Wave"],
        "flutterwave_payment_options": "card,mobilemoneyfranco",
        "methods_note": "Moyens mobiles proposés selon le pays et leur disponibilité chez le prestataire (Wave notamment).",
        "countries": ["SN", "CI", "ML", "BF", "BJ", "TG", "NE", "GW"],
    },
    "cemac": {
        "label": "Afrique centrale — CEMAC (FCFA XAF)", "label_en": "Central Africa — CEMAC (CFA franc XAF)",
        "currency": "XAF", "amount": 59000, "approx_eur": 90, "indicative": True,
        "provider": "flutterwave", "methods": ["Carte bancaire", "Orange Money", "MTN MoMo"],
        "flutterwave_payment_options": "card,mobilemoneyfranco",
        "methods_note": "Moyens mobiles proposés selon le pays et leur disponibilité chez le prestataire.",
        "countries": ["CM", "GA", "CG", "TD", "CF", "GQ"],
    },
    "nigeria": {
        "label": "Nigeria (NGN)", "label_en": "Nigeria (NGN)",
        "currency": "NGN", "amount": 95000, "approx_eur": 55, "indicative": True,
        "provider": "paystack", "methods": ["Carte bancaire", "Virement", "USSD"],
        "paystack_channels": ["card", "bank", "ussd", "bank_transfer"],
        "countries": ["NG"],
    },
    "ghana": {
        "label": "Ghana (GHS)", "label_en": "Ghana (GHS)",
        "currency": "GHS", "amount": 900, "approx_eur": 60, "indicative": True,
        "provider": "paystack", "methods": ["Carte bancaire", "MTN MoMo", "Telecel Cash", "AirtelTigo Money"],
        "paystack_channels": ["card", "mobile_money"],
        "countries": ["GH"],
    },
    "kenya": {
        "label": "Kenya (KES)", "label_en": "Kenya (KES)",
        "currency": "KES", "amount": 8500, "approx_eur": 60, "indicative": True,
        "provider": "paystack", "methods": ["Carte bancaire", "M-Pesa", "Airtel Money"],
        "paystack_channels": ["card", "mobile_money"],
        "countries": ["KE"],
    },
    "south_africa": {
        "label": "Afrique du Sud (ZAR)", "label_en": "South Africa (ZAR)",
        "currency": "ZAR", "amount": 1990, "approx_eur": 100, "indicative": True,
        "provider": "paystack", "methods": ["Carte bancaire", "EFT instantané"],
        "paystack_channels": ["card", "eft"],
        "countries": ["ZA"],
    },
    "morocco": {
        "label": "Maroc (MAD)", "label_en": "Morocco (MAD)",
        "currency": "MAD", "amount": 1290, "approx_eur": 120, "indicative": True,
        "provider": "stripe", "methods": ["Carte bancaire"], "stripe_payment_method_types": ["card"],
        "countries": ["MA"],
    },
    "maghreb": {
        "label": "Algérie, Tunisie, Mauritanie (EUR)", "label_en": "Algeria, Tunisia, Mauritania (EUR)",
        "currency": "EUR", "amount": 129, "approx_eur": 129, "indicative": True,
        "provider": "stripe", "methods": ["Carte bancaire internationale"], "stripe_payment_method_types": ["card"],
        "methods_note": "Facturation en euros : les devises locales (DZD, TND, MRU) ne sont pas proposées par défaut.",
        "countries": ["DZ", "TN", "MR"],
    },
    "africa_other": {
        "label": "Autres pays d'Afrique (USD)", "label_en": "Other African countries (USD)",
        "currency": "USD", "amount": 99, "approx_eur": 90, "indicative": True,
        "provider": "flutterwave", "methods": ["Carte bancaire"],
        "flutterwave_payment_options": "card",
        "methods_note": "Le mobile money exige la devise locale : ajoutez une région dédiée (ex. UGX, RWF, TZS) pour le proposer.",
        "countries": ["CD", "GN", "MG", "RW", "UG", "TZ", "ET", "EG", "ZM", "MZ", "AO", "BI", "DJ", "KM", "CV", "SL", "LR", "GM"],
    },
}

# Fuseaux horaires -> pays (pour la détection côté navigateur ; dupliqué de façon minimale dans app.js)
TIMEZONE_COUNTRY = {
    "Africa/Dakar": "SN", "Africa/Abidjan": "CI", "Africa/Bamako": "ML", "Africa/Ouagadougou": "BF",
    "Africa/Porto-Novo": "BJ", "Africa/Lome": "TG", "Africa/Niamey": "NE", "Africa/Bissau": "GW",
    "Africa/Douala": "CM", "Africa/Libreville": "GA", "Africa/Brazzaville": "CG", "Africa/Ndjamena": "TD",
    "Africa/Bangui": "CF", "Africa/Malabo": "GQ", "Africa/Lagos": "NG", "Africa/Accra": "GH",
    "Africa/Nairobi": "KE", "Africa/Johannesburg": "ZA", "Africa/Casablanca": "MA", "Africa/Algiers": "DZ",
    "Africa/Tunis": "TN", "Africa/Nouakchott": "MR", "Africa/Kinshasa": "CD", "Africa/Lubumbashi": "CD",
    "Africa/Conakry": "GN", "Africa/Kigali": "RW", "Africa/Kampala": "UG", "Africa/Dar_es_Salaam": "TZ",
    "Africa/Addis_Ababa": "ET", "Africa/Cairo": "EG", "Indian/Antananarivo": "MG",
}


def load_regions() -> dict[str, dict]:
    regions = copy.deepcopy(REGIONS)
    path = os.environ.get("PRICING_FILE")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            overrides = json.load(f)
        for key, val in overrides.items():
            regions.setdefault(key, {}).update(val)
    return regions


def get_region(key: str) -> dict | None:
    r = load_regions().get(key)
    return {"key": key, **r} if r else None


def region_for_country(country: str | None) -> str:
    c = (country or "").upper()
    for key, r in load_regions().items():
        if c in r.get("countries", []):
            return key
    return REFERENCE_REGION if not c else ("international" if c not in _AFRICA else "africa_other")


_AFRICA = {"SN", "CI", "ML", "BF", "BJ", "TG", "NE", "GW", "CM", "GA", "CG", "TD", "CF", "GQ", "NG", "GH", "KE",
           "ZA", "MA", "DZ", "TN", "MR", "CD", "GN", "MG", "RW", "UG", "TZ", "ET", "EG", "ZM", "MZ", "AO", "BI",
           "DJ", "KM", "CV", "SL", "LR", "GM", "LY", "SD", "SS", "SO", "ER", "NA", "BW", "ZW", "MW", "LS", "SZ",
           "MU", "SC", "ST"}


def public_pricing() -> dict:
    out = []
    for key, r in load_regions().items():
        out.append({
            "key": key, "label": r["label"], "label_en": r.get("label_en", r["label"]), "currency": r["currency"],
            "amount": r["amount"], "approx_eur": r.get("approx_eur"), "reference": bool(r.get("reference")),
            "indicative": bool(r.get("indicative", True)), "provider": r["provider"], "methods": r.get("methods", []),
            "methods_note": r.get("methods_note"), "countries": r.get("countries", []),
        })
    from .plans import public_plans, TRIAL_DAYS
    return {"plan": "CareAssist Premium — appels illimités, cabinet solo ou petit groupe", "interval": "month",
            "reference_region": REFERENCE_REGION, "disclaimer": DISCLAIMER_FR, "regions": out,
            "timezone_country": TIMEZONE_COUNTRY, "plans": public_plans(), "trial_days": TRIAL_DAYS}
