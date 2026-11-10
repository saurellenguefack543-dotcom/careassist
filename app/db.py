"""Accès SQLite (stdlib) : schéma, connexions, helpers."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS practices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    specialty TEXT NOT NULL,       -- clé de app/specialties.py
    address TEXT NOT NULL,
    phone TEXT NOT NULL,
    hours TEXT NOT NULL,
    access TEXT
);
CREATE TABLE IF NOT EXISTS practitioners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id INTEGER NOT NULL REFERENCES practices(id),
    name TEXT NOT NULL,
    specialty TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practitioner_id INTEGER NOT NULL REFERENCES practitioners(id),
    start TEXT NOT NULL,              -- ISO local 'YYYY-MM-DDTHH:MM'
    duration_min INTEGER NOT NULL DEFAULT 30,
    is_emergency INTEGER NOT NULL DEFAULT 0,
    booked INTEGER NOT NULL DEFAULT 0,
    UNIQUE(practitioner_id, start)
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id INTEGER NOT NULL REFERENCES slots(id),
    patient_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    reason TEXT,
    appointment_type TEXT,
    practice_id INTEGER,
    urgent INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'confirmed',  -- confirmed | reminded | honored | no_show | cancelled
    calendar_event_id TEXT,
    conversation_id INTEGER,
    created_at TEXT NOT NULL,
    cancelled_at TEXT
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    practice_id INTEGER,
    channel TEXT NOT NULL DEFAULT 'web',
    state TEXT NOT NULL DEFAULT '{}',
    emergency_level TEXT NOT NULL DEFAULT 'none',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,            -- user | assistant
    content TEXT NOT NULL,
    intent TEXT,
    engine TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    message TEXT,
    specialty TEXT,
    source TEXT DEFAULT 'landing',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference TEXT UNIQUE NOT NULL,
    region TEXT NOT NULL,
    currency TEXT NOT NULL,
    amount REAL NOT NULL,             -- unité principale de la devise (ex. 299 EUR, 59000 XOF)
    provider TEXT NOT NULL,           -- stripe | flutterwave | paystack
    mode TEXT NOT NULL,               -- mock | live
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | active | failed | cancelled | error
    practice_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    specialty TEXT,
    checkout_url TEXT,
    provider_session_id TEXT,
    provider_subscription_id TEXT,
    last_event TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id INTEGER NOT NULL REFERENCES practices(id),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,        -- bcrypt
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner', -- owner | practitioner | secretary
    practitioner_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,        -- sha256 du jeton du cookie (le jeton brut n'est jamais stocké)
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL            -- UTC ISO
);
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id INTEGER NOT NULL REFERENCES practices(id),
    first_name TEXT,
    last_name TEXT NOT NULL,
    phone_e164 TEXT,
    email TEXT,
    birth_date TEXT,
    preferred_channel TEXT NOT NULL DEFAULT 'auto',  -- auto | sms | whatsapp | email | none
    notify_consent INTEGER NOT NULL DEFAULT 1,
    language TEXT DEFAULT 'fr',
    notes TEXT,
    source TEXT DEFAULT 'manual',       -- manual | booking | import
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_patients_practice ON patients(practice_id);
CREATE INDEX IF NOT EXISTS idx_patients_phone ON patients(practice_id, phone_e164);
CREATE TABLE IF NOT EXISTS opening_hours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id INTEGER NOT NULL REFERENCES practices(id),
    weekday INTEGER NOT NULL,           -- 0 = lundi
    open_time TEXT NOT NULL,            -- HH:MM
    close_time TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id INTEGER REFERENCES practices(id),
    patient_id INTEGER,
    provider TEXT NOT NULL,             -- twilio | vonage | africastalking | mock
    provider_call_id TEXT,
    direction TEXT NOT NULL DEFAULT 'inbound',
    from_number TEXT,
    to_number TEXT,
    status TEXT NOT NULL DEFAULT 'in-progress',  -- in-progress | completed | missed | voicemail | transferred | failed
    duration_s INTEGER,
    transcript TEXT NOT NULL DEFAULT '',
    recording_url TEXT,
    voicemail_text TEXT,
    callback_sms_sent INTEGER NOT NULL DEFAULT 0,
    turns INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    UNIQUE(provider, provider_call_id)
);
CREATE INDEX IF NOT EXISTS idx_calls_practice ON calls(practice_id);
CREATE TABLE IF NOT EXISTS channel_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id INTEGER REFERENCES practices(id),
    patient_id INTEGER,
    direction TEXT NOT NULL,            -- inbound | outbound
    channel TEXT NOT NULL,              -- sms | whatsapp | email
    provider TEXT NOT NULL,             -- twilio | vonage | africastalking | smtp | mock
    from_addr TEXT,
    to_addr TEXT,
    body TEXT NOT NULL,
    status TEXT,                        -- sent | mock_sent | failed | received
    provider_message_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msgs_practice ON channel_messages(practice_id);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id INTEGER NOT NULL REFERENCES practices(id),
    appointment_id INTEGER,
    patient_id INTEGER,
    practitioner_id INTEGER,
    recipient_type TEXT NOT NULL,       -- patient | practitioner
    kind TEXT NOT NULL,                 -- confirmation | reminder_<minutes> | cancellation | callback_offer
    channel TEXT,
    to_addr TEXT,
    body TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled | sending | sent | mock_sent | failed | skipped | cancelled
    scheduled_for TEXT NOT NULL,        -- UTC ISO
    sent_at TEXT,
    provider TEXT,
    provider_message_id TEXT,
    error TEXT,
    dedupe_key TEXT UNIQUE NOT NULL,    -- garantit l'idempotence (pas de doublon)
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notif_due ON notifications(status, scheduled_for);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id INTEGER,
    user_id INTEGER,
    action TEXT NOT NULL,               -- login | patient.update | export | …  (aucune donnée de santé)
    entity TEXT,
    entity_id INTEGER,
    ip TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emergencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER,
    practice_id INTEGER,
    level TEXT NOT NULL,           -- urgent | vital
    categories TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now(tz: str | None = None) -> datetime:
    """Heure locale (du cabinet si `tz` est fourni), sans tzinfo (stockage ISO simple)."""
    return datetime.now(ZoneInfo(tz or config.timezone())).replace(tzinfo=None, second=0, microsecond=0)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def now_iso() -> str:
    return datetime.now(ZoneInfo(config.timezone())).replace(microsecond=0).isoformat()


def get_conn() -> sqlite3.Connection:
    path = config.db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Colonnes ajoutées après coup (migration légère, idempotente, pour les bases existantes)
MIGRATIONS = {
    "practices": {
        "country": "TEXT NOT NULL DEFAULT 'FR'", "timezone": "TEXT NOT NULL DEFAULT 'Europe/Paris'",
        "currency": "TEXT NOT NULL DEFAULT 'EUR'", "language": "TEXT NOT NULL DEFAULT 'fr'",
        "email": "TEXT", "phone_e164": "TEXT",
        "voip_provider": "TEXT NOT NULL DEFAULT 'auto'",   # auto | twilio | vonage | africastalking
        "voip_number": "TEXT",                              # numéro E.164 appelé par les patients (routage entrant)
        "transfer_number": "TEXT",                          # transfert vers un humain
        "insurance_note": "TEXT", "prices_note": "TEXT",
        "notify_patient_offsets": "TEXT NOT NULL DEFAULT '[1440, 120]'",      # minutes avant le RDV
        "notify_practitioner_offsets": "TEXT NOT NULL DEFAULT '[120]'",
        "notify_on_booking": "INTEGER NOT NULL DEFAULT 1",
        "notify_practitioner": "INTEGER NOT NULL DEFAULT 1",
        "patient_channels": "TEXT",                         # JSON ; vide = défaut du pays
        "practitioner_channel": "TEXT NOT NULL DEFAULT 'email'",
        "quiet_start": "TEXT NOT NULL DEFAULT '21:00'", "quiet_end": "TEXT NOT NULL DEFAULT '08:00'",
        "missed_call_sms": "INTEGER NOT NULL DEFAULT 1",
        "created_at": "TEXT", "is_demo": "INTEGER NOT NULL DEFAULT 0",
    },
    "practitioners": {"phone_e164": "TEXT", "email": "TEXT", "notify_channel": "TEXT", "active": "INTEGER NOT NULL DEFAULT 1"},
    "appointments": {"patient_id": "INTEGER", "notes": "TEXT", "patient_confirmed_at": "TEXT", "updated_at": "TEXT",
                     "source": "TEXT DEFAULT 'assistant'"},
}


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_appt_practice ON appointments(practice_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_practices_voip ON practices(voip_number)")


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ---------- conversations & logs ----------

def practice_by_number(number: str | None) -> dict | None:
    """Routage entrant : cabinet dont le numéro VoIP (E.164) est le numéro appelé."""
    from .phone import to_e164
    e = to_e164(number, "FR", strict=False) if number else None
    if not e:
        return None
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM practices WHERE voip_number=?", (e,)).fetchone()
    return dict(r) if r else None


def get_practice(key) -> dict | None:
    """Récupère un cabinet par id ou slug."""
    with get_conn() as conn:
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            r = conn.execute("SELECT * FROM practices WHERE id=?", (int(key),)).fetchone()
        else:
            r = conn.execute("SELECT * FROM practices WHERE slug=? OR specialty=? ORDER BY id LIMIT 1", (key, key)).fetchone()
    return dict(r) if r else None


def list_practices() -> list[dict]:
    with get_conn() as conn:
        return rows(conn.execute("SELECT * FROM practices ORDER BY id"))


def get_or_create_conversation(session_id: str, channel: str = "web", practice_id: int | None = None) -> dict:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM conversations WHERE session_id=?", (session_id,)).fetchone()
        if r:
            return dict(r)
        ts = now_iso()
        conn.execute(
            "INSERT INTO conversations(session_id, practice_id, channel, state, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (session_id, practice_id, channel, "{}", ts, ts),
        )
        r = conn.execute("SELECT * FROM conversations WHERE session_id=?", (session_id,)).fetchone()
        return dict(r)


def save_state(conv_id: int, state: dict, emergency_level: str | None = None) -> None:
    with get_conn() as conn:
        if emergency_level and emergency_level != "none":
            cur = conn.execute("SELECT emergency_level FROM conversations WHERE id=?", (conv_id,)).fetchone()
            order = {"none": 0, "urgent": 1, "vital": 2}
            if order.get(emergency_level, 0) > order.get(cur["emergency_level"], 0):
                conn.execute("UPDATE conversations SET emergency_level=? WHERE id=?", (emergency_level, conv_id))
        conn.execute(
            "UPDATE conversations SET state=?, updated_at=? WHERE id=?",
            (json.dumps(state, ensure_ascii=False), now_iso(), conv_id),
        )


def log_message(conv_id: int, role: str, content: str, intent: str | None = None, engine: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages(conversation_id, role, content, intent, engine, created_at) VALUES (?,?,?,?,?,?)",
            (conv_id, role, content, intent, engine, now_iso()),
        )


def history(conv_id: int, limit: int = 12) -> list[dict]:
    with get_conn() as conn:
        r = rows(conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?", (conv_id, limit)
        ))
    return list(reversed(r))


def log_emergency(conv_id: int | None, practice_id: int | None, level: str, categories: list[str], message: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO emergencies(conversation_id, practice_id, level, categories, message, created_at) VALUES (?,?,?,?,?,?)",
            (conv_id, practice_id, level, ",".join(categories), message, now_iso()),
        )
