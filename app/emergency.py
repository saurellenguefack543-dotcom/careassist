"""Détection d'urgence déterministe (toujours exécutée AVANT le LLM).

Règles communes (signes vitaux, idées suicidaires…) + règles propres à la spécialité.
Niveaux : none < urgent < vital. Actions :
  samu          -> appeler le 15 / 112, aucun RDV proposé
  samu_psy      -> 3114 + 15, ton empathique
  samu_danger   -> 17 / 112 (+ 3919), mise en sécurité
  priority_slot -> créneau d'urgence le jour même (ou au plus tôt)
  soonest_slot  -> premier créneau disponible + ressources (psy)
  redirect      -> orienter vers médecin/chirurgien le jour même (kiné)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .specialties import COMMON_EMERGENCY_RULES, get_specialty

ORDER = {"none": 0, "urgent": 1, "vital": 2}


def normalize(text: str) -> str:
    text = (text or "").lower().replace("’", "'").replace("`", "'").replace("œ", "oe")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class EmergencyResult:
    level: str = "none"
    action: str | None = None
    primary: str | None = None
    categories: list[str] = field(default_factory=list)

    @property
    def is_emergency(self) -> bool:
        return self.level != "none"

    def to_dict(self) -> dict:
        return {"level": self.level, "action": self.action, "primary": self.primary, "categories": self.categories}


def _match(rule: dict, text: str) -> bool:
    return any(re.search(p, text) for p in rule["patterns"])


def detect(text: str, specialty: str | None = "dentiste") -> EmergencyResult:
    t = normalize(text)
    spec = get_specialty(specialty)
    rules = COMMON_EMERGENCY_RULES + spec["emergency_rules"]
    matched = [r for r in rules if _match(r, t)]
    if not matched:
        return EmergencyResult()
    best = max(ORDER[r["level"]] for r in matched)
    top = [r for r in matched if ORDER[r["level"]] == best]
    primary = top[0]
    return EmergencyResult(level=primary["level"], action=primary["action"], primary=primary["id"],
                           categories=[r["id"] for r in matched])
