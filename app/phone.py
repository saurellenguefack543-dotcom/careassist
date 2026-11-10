"""Numéros de téléphone : validation et normalisation E.164 avec la bibliothèque `phonenumbers`."""
from __future__ import annotations

import phonenumbers


class PhoneError(ValueError):
    pass


def to_e164(raw: str | None, region: str = "FR", strict: bool = True) -> str | None:
    """'06 12 34 56 78' (FR) -> '+33612345678'. Lève PhoneError si invalide (strict) sinon renvoie None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("whatsapp:"):
        raw = raw[len("whatsapp:"):]
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if raw.isdigit() and len(raw) > 10 and not raw.startswith("0"):
        raw = "+" + raw  # format msisdn (Vonage) : 221771234567
    try:
        num = phonenumbers.parse(raw, (region or "FR").upper())
    except phonenumbers.NumberParseException as e:
        if strict:
            raise PhoneError(f"Numéro de téléphone invalide : {raw}") from e
        return None
    if not phonenumbers.is_valid_number(num):
        if strict:
            raise PhoneError(f"Numéro de téléphone invalide pour le pays {region} : {raw}")
        return None
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def pretty(e164: str | None) -> str:
    if not e164:
        return ""
    try:
        return phonenumbers.format_number(phonenumbers.parse(e164, None), phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except phonenumbers.NumberParseException:
        return e164


def find_in_text(text: str, region: str = "FR") -> str | None:
    """Premier numéro valide trouvé dans un texte libre (dictée vocale, chat)."""
    for m in phonenumbers.PhoneNumberMatcher(text or "", (region or "FR").upper()):
        return m.raw_string
    return None


def same_number(a: str | None, b: str | None, region: str = "FR") -> bool:
    ea, eb = to_e164(a, region, strict=False), to_e164(b, region, strict=False)
    if ea and eb:
        return ea == eb
    da, dbb = "".join(c for c in (a or "") if c.isdigit()), "".join(c for c in (b or "") if c.isdigit())
    return bool(da) and da[-9:] == dbb[-9:]
