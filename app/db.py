"""Accès SQLite (stdlib) : schéma, connexions, helpers."""
import json
import os
import re
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

CREATE TABLE IF NOT EXISTS practice_faq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id INTEGER NOT NULL REFERENCES practices(id),
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    keywords TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_faq_practice ON practice_faq(practice_id);
"""


def now(tz: str | None = None) -> datetime:
    """Heure locale (du cabinet si `tz` est fourni), sans tzinfo (stockage ISO simple)."""
    return datetime.now(ZoneInfo(tz or config.timezone())).replace(tzinfo=None, second=0, microsecond=0)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def now_iso() -> str:
    return datetime.now(ZoneInfo(config.timezone())).replace(microsecond=0).isoformat()


def database_url() -> str:
    """URL PostgreSQL (Render : DATABASE_URL). Vide = SQLite local."""
    url = config.env("DATABASE_URL")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def is_postgres() -> bool:
    return bool(database_url())


def _qmark_to_percent(sql: str) -> str:
    """Remplace les placeholders ? hors chaîtes par %s (psycopg)."""
    out, i, n, in_s, quote = [], 0, len(sql), False, ""
    while i < n:
        c = sql[i]
        if in_s:
            out.append(c)
            if c == quote:
                in_s = False
            elif c == "\\" and i + 1 < n:
                out.append(sql[i + 1]); i += 1
            i += 1
            continue
        if c in ("'", '"'):
            in_s, quote = True, c
            out.append(c)
        elif c == "?":
            out.append("%s")
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _adapt_sql(sql: str) -> str:
    rewritten = re.sub(r"(?i)INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql)
    ignored = rewritten != sql
    sql = rewritten
    if ignored:
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    m = re.match(r"\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", sql, re.I)
    if m and m.group(1).lower() != "sessions" and "RETURNING" not in sql.upper():
        sql = sql.rstrip().rstrip(";") + " RETURNING id"
    return _qmark_to_percent(sql)


class _PgRow:
    def __init__(self, cols, values):
        self._cols = cols
        self._values = list(values)
        self._map = {c: v for c, v in zip(cols, values)}

    def __getitem__(self, key):
        return self._values[key] if isinstance(key, int) else self._map[key]

    def __iter__(self):
        return iter(self._values)

    def keys(self):
        return self._map.keys()

    def __contains__(self, key):
        return key in self._map


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = None
        self.description = None
        self.rowcount = -1

    def execute(self, sql, params=None):
        adapted = _adapt_sql(sql)
        self._cur.execute(adapted, tuple(params) if params is not None else None)
        self.description = self._cur.description
        self.rowcount = self._cur.rowcount
        self.lastrowid = None
        if self._cur.description and len(self._cur.description) == 1 and self._cur.description[0].name == "id":
            # INSERT ... RETURNING id : consomme la ligne pour lastrowid
            if re.match(r"\s*INSERT\s", sql, re.I):
                row = self._cur.fetchone()
                if row:
                    self.lastrowid = row[0]
        return self

    def executemany(self, sql, seq):
        adapted = _adapt_sql(sql)
        # pas de lastrowid utile ici
        self._cur.executemany(adapted, list(seq))
        self.description = self._cur.description
        self.rowcount = self._cur.rowcount
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        cols = [d.name for d in self._cur.description]
        if hasattr(row, "keys"):
            return _PgRow(cols, [row[c] for c in cols])
        return _PgRow(cols, row)

    def fetchall(self):
        rows = self._cur.fetchall()
        if not rows:
            return []
        cols = [d.name for d in self._cur.description]
        out = []
        for row in rows:
            if hasattr(row, "keys"):
                out.append(_PgRow(cols, [row[c] for c in cols]))
            else:
                out.append(_PgRow(cols, row))
        return out

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row

    def close(self):
        self._cur.close()


class _PgConn:
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=None):
        cur = _PgCursor(self._raw.cursor())
        return cur.execute(sql, params)

    def executemany(self, sql, seq):
        cur = _PgCursor(self._raw.cursor())
        return cur.executemany(sql, seq)

    def executescript(self, script: str):
        # découpe naïve : le schéma n'a pas de point-virgule dans des chaînes utiles
        for stmt in script.split(";"):
            stmt = stmt.strip()
            if stmt:
                self.execute(stmt)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self._raw.rollback()
            else:
                self._raw.commit()
        finally:
            self._raw.close()
        return False


def _sqlite_conn():
    path = config.db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _pg_conn():
    import psycopg
    raw = psycopg.connect(database_url(), autocommit=False)
    return _PgConn(raw)


def get_conn():
    return _pg_conn() if is_postgres() else _sqlite_conn()


def schema_sql() -> str:
    sql = SCHEMA
    if is_postgres():
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
    return sql


def table_columns(conn, table: str) -> set[str]:
    if is_postgres():
        rows_ = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=?",
            (table,),
        ).fetchall()
        return {r[0] for r in rows_}
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def is_empty() -> bool:
    """Vrai si aucun cabinet n'est encore enregistré (première initialisation)."""
    with get_conn() as conn:
        try:
            n = conn.execute("SELECT COUNT(*) FROM practices").fetchone()[0]
        except Exception:
            return True
    return n == 0


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
        "plan": "TEXT NOT NULL DEFAULT 'free'",
        "trial_ends_at": "TEXT",
        "subscription_status": "TEXT NOT NULL DEFAULT 'free'",
        "trial_notice_3d": "INTEGER NOT NULL DEFAULT 0",
        "trial_notice_end": "INTEGER NOT NULL DEFAULT 0",
        "logo_path": "TEXT",
        "emergency_contact_name": "TEXT",
        "emergency_contact_phone": "TEXT",
        "city": "TEXT",
        "listing_status": "TEXT NOT NULL DEFAULT 'pending'",
        "directory_visible": "INTEGER NOT NULL DEFAULT 1",
        "published_at": "TEXT",
    },
    "practitioners": {"phone_e164": "TEXT", "email": "TEXT", "notify_channel": "TEXT", "active": "INTEGER NOT NULL DEFAULT 1"},
    "appointments": {"patient_id": "INTEGER", "notes": "TEXT", "patient_confirmed_at": "TEXT", "updated_at": "TEXT",
                     "source": "TEXT DEFAULT 'assistant'"},
    "subscriptions": {"practice_id": "INTEGER"},
}


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(schema_sql())
        added_plan = False
        for table, cols in MIGRATIONS.items():
            existing = table_columns(conn, table)
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                    if table == "practices" and col == "plan":
                        added_plan = True
        if added_plan:
            from .plans import backfill_existing
            backfill_existing(conn)
            # démo : fiches déjà publiées ; les autres restent en attente
            conn.execute(
                "UPDATE practices SET listing_status='published', published_at=COALESCE(published_at, created_at, ?) "
                "WHERE is_demo=1",
                (now_iso(),),
            )
        from .directory import infer_city
        for row in conn.execute("SELECT id, address, city FROM practices").fetchall():
            if not (row["city"] or "").strip():
                city = infer_city(row["address"])
                if city:
                    conn.execute("UPDATE practices SET city=? WHERE id=?", (city, row["id"]))
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


def get_conversation(session_id: str) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM conversations WHERE session_id=?", (session_id,)).fetchone()
        return dict(r) if r else None


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
