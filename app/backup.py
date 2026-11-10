"""Sauvegardes : SQLite (copie à chaud) ou PostgreSQL (pg_dump), rotation et restauration."""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from . import config, db


def backup_dir() -> Path:
    p = Path(config.env("BACKUP_DIR", str(Path(config.db_path()).parent / "backups")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def keep_n() -> int:
    return max(1, int(config.env("BACKUP_KEEP", "7")))


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def run_backup(keep: int | None = None) -> dict:
    dest_dir = backup_dir()
    if db.is_postgres():
        dest = dest_dir / f"careassist-{_stamp()}.sql"
        url = db.database_url()
        env = os.environ.copy()
        r = subprocess.run(["pg_dump", "--no-owner", "--no-acl", url], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "pg_dump a échoué")
        dest.write_text(r.stdout)
        os.chmod(dest, 0o600)
        removed = rotate(keep or keep_n())
        return {"file": str(dest), "size": dest.stat().st_size, "removed": removed, "engine": "postgres"}
    src = config.db_path()
    dest = dest_dir / f"careassist-{_stamp()}.db"
    with sqlite3.connect(src) as s, sqlite3.connect(dest) as d:
        s.backup(d)
    os.chmod(dest, 0o600)
    removed = rotate(keep or keep_n())
    return {"file": str(dest), "size": dest.stat().st_size, "removed": removed, "engine": "sqlite"}


def list_backups() -> list[Path]:
    files = list(backup_dir().glob("careassist-*.db")) + list(backup_dir().glob("careassist-*.sql"))
    return sorted(files)


def rotate(keep: int) -> list[str]:
    files = list_backups()
    old = files[:-keep] if len(files) > keep else []
    for f in old:
        f.unlink(missing_ok=True)
    return [str(f) for f in old]


def restore(path: str) -> dict:
    """Restaure une sauvegarde (serveur ARRÊTÉ)."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(path)
    if src.suffix == ".sql" or db.is_postgres():
        url = db.database_url()
        if not url:
            raise RuntimeError("DATABASE_URL requis pour restaurer un dump PostgreSQL")
        # sécurité : on n\'écrase pas à l\'aveugle sans dump lisible
        if src.stat().st_size < 20:
            raise ValueError("Sauvegarde vide ou illisible")
        r = subprocess.run(["psql", url, "-v", "ON_ERROR_STOP=1", "-f", str(src)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "psql restore a échoué")
        return {"restored": str(src), "into": url.split("@")[-1], "engine": "postgres"}
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
    return {"restored": str(src), "into": str(target), "previous_copy": str(safety) if safety else None, "engine": "sqlite"}
