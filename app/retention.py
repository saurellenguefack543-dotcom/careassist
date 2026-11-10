"""Rétention des données (RGPD, minimisation) : purge des journaux techniques anciens.
Par défaut 3 ans (RETENTION_DAYS). Ne touche ni aux fiches patients ni aux rendez-vous."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import config, db


def purge(days: int | None = None) -> dict:
    days = days or int(config.env("RETENTION_DAYS", "1095"))
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    out = {}
    with db.get_conn() as conn:
        out["calls"] = conn.execute("DELETE FROM calls WHERE started_at < ?", (cutoff,)).rowcount
        out["channel_messages"] = conn.execute("DELETE FROM channel_messages WHERE created_at < ?", (cutoff,)).rowcount
        out["notifications"] = conn.execute("DELETE FROM notifications WHERE created_at < ? AND status!='scheduled'", (cutoff,)).rowcount
        old = [r[0] for r in conn.execute("SELECT id FROM conversations WHERE updated_at < ?", (cutoff,))]
        for cid in old:
            conn.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        out["conversations"] = conn.execute("DELETE FROM conversations WHERE updated_at < ?", (cutoff,)).rowcount
        out["sessions"] = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (db.utcnow_iso(),)).rowcount
    return out
