"""Moteur de conversation hybride.

- Urgences : détection déterministe systématique (emergency.py), jamais déléguée au LLM.
- Transactions (réservation, annulation, report) : machine à états déterministe -> aucune
  hallucination de créneau possible.
- Questions ouvertes (FAQ, small talk, hors périmètre) : LLM si configuré (Groq/OpenAI/Ollama),
  sinon moteur de règles. En cas d'erreur LLM, repli automatique sur les règles.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import timedelta

from . import booking, config, db
from .emergency import detect, normalize
from .llm import get_llm
from .prompts import build_system_prompt
from .specialties import get_specialty
from .countries import get_country, localize
from . import phone as phonelib

log = logging.getLogger("careassist.engine")

WEEKDAYS = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6}
YES = r"\b(oui|ok|okay|d'accord|daccord|parfait|confirme|confirmer|c'est bon|exact|exactement|volontiers|ouais|yes|vas-y|allez-y|tout a fait|absolument|c'est ca)\b"
NO = r"\b(non|pas (ca|celui)|aucun|autre|ne convient|change|attendez)\b"
PHONE_RE = re.compile(r"(?:\+33\s?|0033\s?|0)[1-9](?:[\s.\-]?\d{2}){4}")

INTENTS = [
    ("human", r"humain|une (vraie )?personne|quelqu'un (de reel|du cabinet)|conseill|secretari|standard|"
              r"parler (a|au|avec) (un |une |le |la )?(docteur|medecin|dentiste|praticien|secretariat|kine|psy)"),
    ("cancel", r"annul|desist|(ne|n') ?(pourrai|peux|pourrais) (pas|plus) venir"),
    ("reschedule", r"deplac|decal|report|changer (mon|le|de) (rendez|rdv|horaire|creneau|date)|modifier (mon|le) (rendez|rdv)"),
    ("booking", r"rendez-?vous|\brdv\b|reserv|prendre (un|une) (seance|consult)|je (voudrais|souhaite|veux|aimerais|souhaiterais) "
                r"(un|une|prendre|venir|consulter|voir|commencer|faire)|disponibilit|creneau|dois commencer|une place"),
    ("insurance", r"mutuelle|assurance|tiers payant|\bcmu|\bc2s\b|\bame\b|carte vitale|\bsecu|securite sociale|rembours|prise en charge|"
                  r"soutien psy|ordonnance pour|faut-il une ordonnance|besoin d'une ordonnance|sans ordonnance"),
    ("prices", r"\bprix\b|tarif|combien|\bcout|coute|devis|honoraire|depassement"),
    ("hours", r"horaire|heures? d'ouverture|ouvert|ferme|fermeture|a quelle heure"),
    ("address", r"adresse|ou (se trouve|etes-vous|est le cabinet|vous trouver)|acces|parking|metro|\btram|\bpmr\b"),
    ("privacy", r"rgpd|mes donnees|donnees personnelles|vie privee"),
    ("ai", r"robot|intelligence artificielle|\bune ia\b|etes-vous (humain|reel)"),
    ("thanks", r"merci|au revoir|bonne (journee|soiree)|c'est tout"),
    ("greeting", r"^(bonjour|bonsoir|salut|allo|hello|coucou)\b"),
]

VITAL_EXTRA = {
    "brulure_chimique": "Rincez immédiatement et abondamment l'œil à l'eau claire du robinet pendant au moins 15 minutes, paupières bien ouvertes, puis appelez [[SAMU_SHORT]].",
    "perte_vision": "Une perte brutale de la vision est une urgence absolue : chaque minute compte.",
    "cellulite": "Un gonflement qui s'étend au cou ou à l'œil, ou une gêne pour avaler ou respirer, peut être une infection grave.",
    "embolie": "Un essoufflement brutal, surtout après une opération ou une immobilisation, peut être une embolie pulmonaire.",
    "fievre_nourrisson": "Chez un nourrisson, la fièvre doit être évaluée sans attendre.",
    "douleur_thoracique": "Ne prenez pas la voiture vous-même ; restez au repos en attendant les secours.",
    "avc": "Notez l'heure de début des symptômes, c'est important pour les secours.",
}

ORDINALS = {"premier": 0, "premiere": 0, "1er": 0, "deuxieme": 1, "second": 1, "seconde": 1, "troisieme": 2, "dernier": -1}


# ---------------------------------------------------------------- helpers

def detect_intent(t: str) -> str | None:
    for name, pattern in INTENTS:
        if re.search(pattern, t):
            return name
    return None


def parse_prefs(t: str, tz: str | None = None) -> dict:
    prefs: dict = {}
    today = db.now(tz).date()
    if re.search(r"aujourd'?hui|ce jour|dans la journee|ce (matin|soir|midi)|cet apres-midi", t):
        prefs["day"] = today.isoformat()
    elif "apres-demain" in t or "apres demain" in t:
        prefs["day"] = (today + timedelta(days=2)).isoformat()
    elif "demain" in t:
        prefs["day"] = (today + timedelta(days=1)).isoformat()
    else:
        for name, wd in WEEKDAYS.items():
            if re.search(rf"\b{name}\b", t):
                prefs["weekday"] = wd
                break
    if "matin" in t:
        prefs["period"] = "matin"
    elif re.search(r"apres-?\s?midi|aprem", t):
        prefs["period"] = "apres-midi"
    elif re.search(r"\bsoir|fin de journee|apres le travail|tard", t):
        prefs["period"] = "soir"
    m = re.search(r"\b(\d{1,2}) ?h(?:eures?)?\b", t)
    if m and 7 <= int(m.group(1)) <= 20:
        prefs["hour"] = int(m.group(1))
    return prefs


def extract_phone(text: str, region: str = "FR") -> str | None:
    m = PHONE_RE.search(text) if region == "FR" else None
    if m:
        return re.sub(r"\s+", " ", m.group(0)).strip()
    found = phonelib.find_in_text(text, region)
    return re.sub(r"\s+", " ", found).strip() if found else None


def extract_name(text: str) -> str | None:
    raw = PHONE_RE.sub(" ", text)
    m = re.search(r"(?:je m'appelle|je m’appelle|je suis|mon nom est|mon nom c'est|c'est|nom\s*:)\s+([A-Za-zÀ-ÿ' \-]{2,60})", raw, re.I)
    if m:
        cand = m.group(1)
    else:
        cand = raw
    cand = re.split(r"[,.;!?]|\bet\b|\bmon\b|\bnum[eé]ro\b|\bt[eé]l", cand, maxsplit=1, flags=re.I)[0]
    cand = re.sub(r"\b(bonjour|oui|alors|euh|madame|monsieur|mme|m\.)\b", " ", cand, flags=re.I)
    cand = re.sub(r"\s+", " ", cand).strip(" -'")
    words = cand.split()
    if 1 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-zÀ-ÿ'\-]+", w) for w in words) and len(cand) >= 2:
        if normalize(cand) in {"oui", "non", "ok", "merci", "d'accord"}:
            return None
        return " ".join(w[:1].upper() + w[1:] for w in words)
    return None


def detect_type(t: str, spec: dict, urgent: bool = False) -> dict:
    types = spec["appointment_types"]
    if urgent:
        for ty in types:
            if ty["key"] == "urgence":
                return ty
    for ty in types:
        if ty["key"] == "urgence":
            continue
        if any(re.search(k, t) for k in ty["keywords"]):
            return ty
    return types[-1]


def slot_phrase(slots: list[dict]) -> str:
    names = ["le premier", "le deuxième", "le troisième"]
    return " ; ".join(f"{names[i]} : {s['label']} avec {s['practitioner']}" for i, s in enumerate(slots))


# ---------------------------------------------------------------- engine

class Engine:
    def __init__(self, practice: dict, conv_id: int, state: dict):
        self.practice = practice
        self.spec = get_specialty(practice["specialty"])
        self.conv_id = conv_id
        self.state = state
        self.country = get_country(practice.get("country"))
        self.region = self.country["code"]
        self.tz = practice.get("timezone") or self.country["timezone"]
        self.meta: dict = {"intent": None, "engine": "rules", "emergency": {"level": "none"}, "appointment": None,
                           "handoff": False, "slots": []}

    # ---- main entry
    def respond(self, text: str) -> str:
        t = normalize(text)
        em = detect(text, self.practice["specialty"])
        in_urgent_flow = self.state.get("flow") == "booking" and self.state.get("urgent")
        if em.level == "vital":
            self.meta.update(intent="emergency", emergency=em.to_dict())
            db.log_emergency(self.conv_id, self.practice["id"], em.level, em.categories, text)
            self.state = {}
            return self.vital_reply(em)
        if em.level == "urgent" and not in_urgent_flow:
            self.meta.update(intent="emergency", emergency=em.to_dict())
            db.log_emergency(self.conv_id, self.practice["id"], em.level, em.categories, text)
            return self.urgent_reply(em, t)

        intent = detect_intent(t)
        if intent == "human":
            self.meta.update(intent="human", handoff=True)
            self.state = {}
            return ("Bien sûr. Je transmets votre demande au secrétariat"
                    + (" et je vous mets en relation." if (self.practice.get("transfer_number") or config.env("HUMAN_TRANSFER_NUMBER")) else
                       f" ; vous serez rappelé(e) aux heures d'ouverture, {self.practice['hours']}.")
                    + " Pouvez-vous me laisser votre nom et votre numéro si ce n'est pas déjà fait ?")
        flow = self.state.get("flow")
        if intent in ("cancel", "reschedule") and flow != intent:
            return self.start_cancel(t, text, reschedule=(intent == "reschedule"))
        if flow == "booking":
            return self.booking_step(t, text)
        if flow in ("cancel", "reschedule"):
            return self.cancel_step(t, text)
        if intent == "booking":
            return self.start_booking(t, text)
        # FAQ spécifiques à la spécialité
        for item in self.spec.get("faq", []):
            if any(re.search(p, t) for p in item["patterns"]) and intent not in ("insurance", "prices"):
                self.meta["intent"] = "faq"
                return self.open_answer(text, item["answer"] + " Puis-je vous aider pour un rendez-vous ?")
        if intent in ("insurance", "prices", "hours", "address", "privacy", "ai", "thanks", "greeting"):
            self.meta["intent"] = intent
            return self.open_answer(text, self.faq(intent))
        # mot-clé d'un type de rendez-vous sans formule explicite ("un détartrage ?")
        if any(any(re.search(k, t) for k in ty["keywords"]) for ty in self.spec["appointment_types"] if ty["key"] != "urgence"):
            return self.start_booking(t, text)
        self.meta["intent"] = "other"
        return self.open_answer(text, (
            f"Je suis l'assistante du {self.practice['name']}. Je peux prendre, déplacer ou annuler un rendez-vous, "
            "et répondre à vos questions sur les horaires, l'accès ou les remboursements. Que puis-je faire pour vous ?"))

    # ---- open questions: LLM if available, else rules
    def open_answer(self, text: str, rules_answer: str) -> str:
        client = get_llm()
        if not client:
            return rules_answer
        try:
            msgs = [{"role": "system", "content": build_system_prompt(
                self.practice, "Pour une prise de rendez-vous, invite la personne à dire « je voudrais un rendez-vous » : "
                "le système de réservation prendra le relais. Réponse de référence validée par le cabinet : " + rules_answer)}]
            msgs += [{"role": m["role"], "content": m["content"]} for m in db.history(self.conv_id, 10)]
            if not msgs[-1:] or msgs[-1]["content"] != text:
                msgs.append({"role": "user", "content": text})
            out = client.chat(msgs)
            self.meta["engine"] = f"llm:{client.provider}"
            return out
        except Exception as exc:  # repli silencieux
            log.warning("LLM indisponible, repli règles : %s", exc)
            self.meta["engine"] = "rules (llm-fallback)"
            return rules_answer

    def faq(self, intent: str) -> str:
        p, s = self.practice, self.spec
        return {
            "insurance": (p.get("insurance_note") or s["insurance"]) + " Souhaitez-vous prendre rendez-vous ?",
            "prices": (p.get("prices_note") or s["prices"]) + " Voulez-vous que je vous propose un créneau ?",
            "hours": f"Le cabinet est ouvert {p['hours']}. Je réponds aussi 24h/24 pour prendre vos rendez-vous. Souhaitez-vous un créneau ?",
            "address": f"Le cabinet se trouve {p['address']}. {p.get('access') or ''}. Souhaitez-vous prendre rendez-vous ?",
            "privacy": ("Vos données (nom, téléphone, rendez-vous) sont utilisées uniquement pour la gestion de vos rendez-vous par le "
                        "cabinet, conformément au RGPD. Vous pouvez demander leur consultation ou leur suppression auprès du cabinet."),
            "ai": "Oui, je suis une assistante virtuelle (IA) du cabinet. Je peux vous transférer à une personne si vous le souhaitez.",
            "thanks": "Avec plaisir ! Bonne journée et à bientôt au cabinet.",
            "greeting": f"Bonjour, {p['name']}, je suis l'assistante virtuelle du cabinet. Comment puis-je vous aider ?",
        }[intent]

    # ---- emergencies
    def vital_reply(self, em) -> str:
        if em.action == "samu_psy":
            return ("Je suis vraiment désolée que vous traversiez cela, et merci de me l'avoir dit. Vous n'êtes pas seul(e). "
                    "Appelez dès maintenant [[SUICIDE]]. Si vous êtes en danger immédiat, appelez [[SAMU_SHORT]]"
                    + (" ou le 112. " if self.country["code"] == "FR" else ". ")
                    + "Si possible, ne restez pas seul(e) et prévenez une personne de confiance. Je signale votre appel au cabinet.")
        if em.action == "samu_danger":
            if self.country["code"] == "FR":
                return ("Votre sécurité passe avant tout. Si vous êtes en danger, appelez le 17 (police) ou le 112 ; si vous ne pouvez "
                        "pas parler, envoyez un SMS au 114. Le 3919 écoute gratuitement et anonymement les victimes de violences. "
                        "Je signale votre appel au cabinet.")
            return ("Votre sécurité passe avant tout. Si vous êtes en danger, appelez [[POLICE]] ou [[SAMU_SHORT]] en cas de "
                    "blessure. Je signale votre appel au cabinet.")
        extra = VITAL_EXTRA.get(em.primary, "")
        return (f"Ce que vous décrivez peut être une urgence vitale. Appelez immédiatement [[SAMU]]. {extra} "
                "Si quelqu'un est près de vous, demandez-lui de rester avec vous. Je ne prends pas de rendez-vous dans cette "
                "situation, mais je signale votre appel au cabinet.").replace("  ", " ")

    def urgent_reply(self, em, t: str) -> str:
        advice = self.spec.get("advice", {}).get(em.primary, "")
        if em.action == "redirect":
            self.meta["handoff"] = True
            self.state = {}
            return ("Merci de nous avoir prévenus. " + advice + " Ce n'est pas une situation à traiter en séance de "
                    "rééducation : je signale votre appel au cabinet pour qu'un praticien vous rappelle. En cas de douleur "
                    "dans la poitrine ou d'essoufflement, appelez [[SAMU_SHORT]].")
        emergency_slots = em.action == "priority_slot" and self.spec.get("has_emergency_slots")
        slots = booking.find_slots(emergency=True, practice_id=self.practice["id"], limit=2) if emergency_slots else []
        slots += booking.find_slots(practice_id=self.practice["id"], limit=3 - len(slots))
        ty = detect_type(t, self.spec, urgent=True)
        self.state = {"flow": "booking", "step": "choose_slot", "urgent": True, "type": ty["key"],
                      "type_label": ty["label"], "proposed": [s["id"] for s in slots],
                      "name": self.state.get("name"), "phone": self.state.get("phone")}
        self.meta["slots"] = [{"id": s["id"], "label": s["label"], "practitioner": s["practitioner"]} for s in slots]
        if self.spec["key"] == "psychologue":
            intro = "Je suis désolée que vous traversiez un moment si difficile, merci de nous avoir appelés. "
            end = " Le praticien ne fait pas de suivi par téléphone, mais il peut vous recevoir rapidement."
        else:
            intro = "Je comprends, c'est une situation à traiter en priorité. "
            end = " Si les symptômes s'aggravent fortement, appelez [[SAMU_SHORT]]."
        if not slots:
            self.state = {}
            self.meta["handoff"] = True
            return intro + advice + " Je n'ai plus de créneau disponible : je signale votre appel au cabinet pour un rappel rapide." + end
        return (intro + advice + f" Je peux vous recevoir au plus tôt : {slot_phrase(slots)}. Lequel vous convient ?" + end)

    # ---- booking flow
    def propose(self, prefs: dict, exclude: list[int] | None = None) -> tuple[list[dict], bool]:
        exclude = set(exclude or [])
        attempts = [prefs, {k: v for k, v in prefs.items() if k != "hour"},
                    {k: v for k, v in prefs.items() if k in ("day", "weekday")}, {}]
        for i, p in enumerate(attempts):
            kwargs = dict(p)
            if "day" in kwargs:
                from datetime import date
                kwargs["day"] = date.fromisoformat(kwargs["day"])
            slots = [s for s in booking.find_slots(practice_id=self.practice["id"], limit=3 + len(exclude), **kwargs)
                     if s["id"] not in exclude][:3]
            if slots:
                return slots, i > 0 and bool(prefs)
        return [], False

    def start_booking(self, t: str, text: str, keep: dict | None = None) -> str:
        self.meta["intent"] = "booking"
        ty = detect_type(t, self.spec)
        prefs = parse_prefs(t, self.tz)
        slots, relaxed = self.propose(prefs)
        base = keep or {}
        self.state = {"flow": "booking", "step": "choose_slot", "urgent": False, "type": ty["key"], "type_label": ty["label"],
                      "proposed": [s["id"] for s in slots], "prefs": prefs,
                      "name": base.get("name") or extract_name_if_explicit(text), "phone": base.get("phone") or extract_phone(text, self.region),
                      "old_appt_id": base.get("old_appt_id")}
        if not slots:
            self.state = {}
            return "Je n'ai malheureusement plus de créneau disponible dans les prochains jours. Je transmets votre demande au secrétariat qui vous rappellera."
        self.meta["slots"] = [{"id": s["id"], "label": s["label"], "practitioner": s["practitioner"]} for s in slots]
        pre = "Je n'ai pas de disponibilité exactement à ce moment-là. " if relaxed else ""
        return (f"Très bien, pour : {ty['label'].lower()}. {pre}Je vous propose {slot_phrase(slots)}. "
                "Lequel vous convient ?")

    def booking_step(self, t: str, text: str) -> str:
        st = self.state
        step = st.get("step")
        if step == "choose_slot":
            idx = self.parse_choice(t)
            if idx is None:
                prefs = parse_prefs(t, self.tz)
                if prefs or re.search(NO, t) or re.search(r"plus tard|plus tot|autre", t):
                    merged = {**st.get("prefs", {}), **prefs} if prefs else st.get("prefs", {})
                    slots, relaxed = self.propose(merged, exclude=st.get("proposed") if not prefs else None)
                    if not slots:
                        return "Je n'ai pas d'autre disponibilité correspondante. Souhaitez-vous que le secrétariat vous rappelle ?"
                    st["proposed"], st["prefs"] = [s["id"] for s in slots], merged
                    self.meta["slots"] = [{"id": s["id"], "label": s["label"], "practitioner": s["practitioner"]} for s in slots]
                    return f"{'Rien exactement à ce moment-là. ' if relaxed else ''}Voici d'autres possibilités : {slot_phrase(slots)}. Lequel préférez-vous ?"
                intent = detect_intent(t)
                if intent in ("insurance", "prices", "hours", "address", "privacy", "ai"):
                    return self.faq(intent).split(" Souhaitez")[0].split(" Voulez")[0] + " Pour revenir au rendez-vous : quel créneau vous convient, le premier, le deuxième ou le troisième ?"
                return "Pardon, je n'ai pas bien compris. Quel créneau vous convient : le premier, le deuxième ou le troisième ? Vous pouvez aussi me donner une autre préférence (jour, matin ou après-midi)."
            slot = booking.get_slot(st["proposed"][idx])
            if not slot or slot["booked"]:
                slots, _ = self.propose(st.get("prefs", {}))
                st["proposed"] = [s["id"] for s in slots]
                return f"Ce créneau vient d'être pris, désolée. Je vous propose : {slot_phrase(slots)}."
            st["slot_id"] = slot["id"]
            st["slot_label"] = f"{slot['label']} avec {slot['practitioner']}"
            st["name"] = st.get("name") or extract_name_if_explicit(text)
            st["phone"] = st.get("phone") or extract_phone(text, self.region)
            return self.next_identity_or_confirm()
        if step == "ask_identity":
            st["phone"] = st.get("phone") or extract_phone(text, self.region)
            st["name"] = st.get("name") or extract_name(text)
            return self.next_identity_or_confirm()
        if step == "confirm":
            if re.search(YES, t) and not re.search(r"\bnon\b", t):
                return self.finalize()
            if re.search(NO, t) or re.search(r"\bnon\b", t):
                slots, _ = self.propose(st.get("prefs", {}), exclude=[st.get("slot_id")])
                st.update(step="choose_slot", proposed=[s["id"] for s in slots])
                return f"D'accord, choisissons un autre créneau : {slot_phrase(slots)}. Lequel vous convient ? (Pour corriger vos coordonnées, dites-les simplement.)"
            phone, name = extract_phone(text, self.region), extract_name(text)
            if phone or name:
                st["phone"], st["name"] = phone or st["phone"], name or st["name"]
                return self.next_identity_or_confirm()
            return "Je confirme ce rendez-vous ? Répondez simplement par oui ou par non."
        self.state = {}
        return self.start_booking(t, text)

    def parse_choice(self, t: str) -> int | None:
        n = len(self.state.get("proposed", []))
        if not n:
            return None
        for word, i in ORDINALS.items():
            if re.search(rf"\b{word}\b", t):
                return (n - 1) if i == -1 else (i if i < n else None)
        m = re.search(r"(?:^|\ble |\bnumero |\bn ?°? ?|\bcreneau |\bchoix )([1-3])\b(?! ?h)", t) or re.fullmatch(r"\s*([1-3])\s*[.!]?", t)
        if m and int(m.group(1)) <= n:
            return int(m.group(1)) - 1
        mh = re.search(r"\b(\d{1,2}) ?h ?(\d{2})?\b", t)
        if mh:
            hh, mm = int(mh.group(1)), int(mh.group(2) or 0)
            for i, sid in enumerate(self.state["proposed"]):
                s = booking.get_slot(sid)
                if s and s["start"][11:16] == f"{hh:02d}:{mm:02d}":
                    return i
        if n == 1 and re.search(YES, t):
            return 0
        return None

    def next_identity_or_confirm(self) -> str:
        st = self.state
        if not st.get("name") and not st.get("phone"):
            st["step"] = "ask_identity"
            return f"Parfait, je vous réserve {st['slot_label']}. À quel nom, et à quel numéro de téléphone puis-je vous joindre ?"
        if not st.get("name"):
            st["step"] = "ask_identity"
            return "Merci. Pouvez-vous me donner votre nom et votre prénom ?"
        if not st.get("phone"):
            st["step"] = "ask_identity"
            return f"Merci {st['name']}. Quel est votre numéro de téléphone ?"
        st["step"] = "confirm"
        return (f"Je récapitule : {st['type_label'].lower()}, {st['slot_label']}, au nom de {st['name']}, "
                f"téléphone {st['phone']}. Je confirme ce rendez-vous ?")

    def finalize(self) -> str:
        st = self.state
        try:
            appt = booking.book(st["slot_id"], st["name"], st["phone"], reason=st.get("type_label", ""),
                                urgent=bool(st.get("urgent")), conversation_id=self.conv_id, appointment_type=st.get("type"))
        except booking.BookingError:
            slots, _ = self.propose(st.get("prefs", {}))
            st.update(step="choose_slot", proposed=[s["id"] for s in slots])
            return f"Désolée, ce créneau vient d'être pris. Je vous propose : {slot_phrase(slots)}."
        moved = ""
        if st.get("old_appt_id"):
            try:
                booking.cancel(st["old_appt_id"])
                moved = " Votre ancien rendez-vous a bien été annulé."
            except booking.BookingError:
                pass
        self.meta.update(intent="booked", appointment=appt)
        self.state = {"name": st["name"], "phone": st["phone"]}
        tip = " Pensez à apporter " + self.country.get("patient_docs", "vos documents de santé") + (" et votre ordonnance." if self.spec["key"] == "kinesitherapeute" else ".")
        return (f"C'est confirmé : {appt['label']} avec {appt['practitioner']}, au {self.practice['address']}.{moved}{tip} "
                "Si vous avez un empêchement, rappelez-nous pour annuler ou déplacer. Puis-je faire autre chose pour vous ?")

    # ---- cancel / reschedule flow
    def start_cancel(self, t: str, text: str, reschedule: bool) -> str:
        self.meta["intent"] = "reschedule" if reschedule else "cancel"
        self.state = {"flow": "reschedule" if reschedule else "cancel", "step": "ask_phone",
                      "name": self.state.get("name"), "phone": self.state.get("phone")}
        phone = extract_phone(text, self.region) or self.state.get("phone")
        if phone:
            return self.lookup(phone)
        return "Bien sûr. Quel numéro de téléphone avez-vous donné lors de la prise de rendez-vous ?"

    def lookup(self, phone: str) -> str:
        st = self.state
        appts = booking.upcoming_for_phone(phone, practice_id=self.practice["id"])
        if not appts:
            self.state = {}
            return ("Je ne trouve aucun rendez-vous à venir avec ce numéro. Vérifiez le numéro ou demandez à parler au "
                    "secrétariat. Souhaitez-vous plutôt prendre un nouveau rendez-vous ?")
        a = appts[0]
        st.update(step="confirm", appt_id=a["id"], phone=phone, name=a["patient_name"])
        more = f" (vous en avez {len(appts)} à venir, je commence par le plus proche)" if len(appts) > 1 else ""
        verb = "le déplacer" if st["flow"] == "reschedule" else "l'annuler"
        return f"J'ai trouvé votre rendez-vous {a['label']} avec {a['practitioner']}{more}. Souhaitez-vous {verb} ?"

    def cancel_step(self, t: str, text: str) -> str:
        st = self.state
        if st.get("step") == "ask_phone":
            phone = extract_phone(text, self.region)
            if not phone:
                return "Je n'ai pas reconnu le numéro. Pouvez-vous me le redonner, par exemple " + self.country["phone_example"] + " ?"
            return self.lookup(phone)
        if st.get("step") == "confirm":
            if re.search(YES, t) and not re.search(r"\bnon\b", t):
                if st["flow"] == "cancel":
                    booking.cancel(st["appt_id"])
                    self.meta["intent"] = "cancelled"
                    self.state = {"name": st.get("name"), "phone": st.get("phone")}
                    return "C'est fait, votre rendez-vous est annulé et le créneau libéré. Souhaitez-vous en reprendre un autre ?"
                keep = {"name": st.get("name"), "phone": st.get("phone"), "old_appt_id": st["appt_id"]}
                return self.start_booking(t, text, keep=keep)
            self.state = {}
            return "Très bien, je ne change rien : votre rendez-vous est maintenu. Puis-je vous aider autrement ?"
        self.state = {}
        return "Que puis-je faire pour vous ?"


def extract_name_if_explicit(text: str) -> str | None:
    if re.search(r"je m'appelle|je m’appelle|mon nom est|nom\s*:", text, re.I):
        return extract_name(text)
    return None


# ---------------------------------------------------------------- public API

def resolve_practice(practice_key=None, conv: dict | None = None) -> dict:
    p = None
    if practice_key:
        p = db.get_practice(practice_key)
    if not p and conv and conv.get("practice_id"):
        p = db.get_practice(conv["practice_id"])
    if not p:
        p = db.get_practice(config.default_practice()) or db.list_practices()[0]
    return p


def process_message(message: str, session_id: str | None = None, practice=None, channel: str = "web") -> dict:
    session_id = session_id or uuid.uuid4().hex
    existing = db.get_or_create_conversation(session_id, channel)
    p = resolve_practice(practice, existing)
    if existing.get("practice_id") != p["id"]:
        with db.get_conn() as conn:
            conn.execute("UPDATE conversations SET practice_id=? WHERE id=?", (p["id"], existing["id"]))
        # changement de cabinet en cours de route (démo) : on repart d'un état vierge
        if existing.get("practice_id"):
            existing["state"] = "{}"
    state = json.loads(existing.get("state") or "{}")
    db.log_message(existing["id"], "user", message)
    eng = Engine(p, existing["id"], state)
    reply = localize(eng.respond(message), eng.country)
    if not eng.meta["intent"]:
        eng.meta["intent"] = state.get("flow") or "other"
    db.save_state(existing["id"], eng.state, eng.meta["emergency"]["level"])
    db.log_message(existing["id"], "assistant", reply, intent=eng.meta["intent"], engine=eng.meta["engine"])
    return {"session_id": session_id, "practice": {"id": p["id"], "slug": p["slug"], "name": p["name"], "specialty": p["specialty"]},
            "reply": reply, "state": {k: v for k, v in eng.state.items() if k in ("flow", "step")}, **eng.meta}
