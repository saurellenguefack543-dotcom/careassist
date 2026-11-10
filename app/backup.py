"""Sauvegardes SQLite : copie à chaud cohérente (API backup de sqlite3) + rotation, et restauration."""
from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from . import config


def backup_dir() -> Path:
    p = Path(config.env("BACKUP_DIR", str(Path(config.db_path()).parent / "backups")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def keep_n() -> int:
    return max(1, int(config.env("BACKUP_KEEP", "7")))


def run_backup(keep: int | None = None) -> dict:
    src = config.db_path()
    dest = backup_dir() / f"careassist-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.db"
    with sqlite3.connect(src) as s, sqlite3.connect(dest) as d:
        s.backup(d)  # cohérent même pendant les écritures
    os.chmod(dest, 0o600)
    removed = rotate(keep or keep_n())
    return {"file": str(dest), "size": dest.stat().st_size, "removed": removed}


def list_backups() -> list[Path]:
    return sorted(backup_dir().glob("careassist-*.db"))


def rotate(keep: int) -> list[str]:
    files = list_backups()
    old = files[:-keep] if len(files) > keep else []
    for f in old:
        f.unlink(missing_ok=True)
    return [str(f) for f in old]


def restore(path: str) -> dict:
    """Restaure une sauvegarde (serveur ARRÊTÉ). La base actuelle est d'abord copiée en *.before-restore."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(path)
    with sqlite3.connect(src) as c:
        if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Sauvegarde corrompue (integrity_check)")
    target = Path(config.db_path())
    safety = None
    if target.exists():
        safety = target.with_suffix(f".before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db")
        shutil.copy2(target, safety)
    with sqlite3.connect(src) as s, sqlite3.connect(target) as d:
        s.backup(d)
    return {"restored": str(src), "into": str(target), "previous_copy": str(safety) if safety else None}
