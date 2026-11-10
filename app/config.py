"""Configuration lue dynamiquement depuis les variables d'environnement (.env supporté)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

PRODUCT_NAME = "CareAssist"
SLOGAN = "Ne manquez plus jamais un rendez-vous. Votre réceptionniste IA 24/7 pour les professionnels de santé."
PRICE_EUR_MONTH = 299
SITE_URL = "https://getcareassist.com"
CONTACT_EMAIL = "contact@getcareassist.com"


def env(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def db_path() -> str:
    p = env("DB_PATH", str(BASE_DIR / "data" / "careassist.db"))
    if not os.path.isabs(p):
        p = str(BASE_DIR / p)
    return p


def timezone() -> str:
    return env("TIMEZONE", "Europe/Paris")


def default_practice() -> str:
    return env("DEFAULT_PRACTICE", "dentiste")
