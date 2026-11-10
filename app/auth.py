"""Authentification du personnel des cabinets : bcrypt, session serveur (cookie HttpOnly), CSRF double-submit, rôles."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request, Response

from . import config, db

COOKIE = "ca_session"
CSRF_COOKIE = "ca_csrf"
ROLES = ("owner", "practitioner", "secretary")
SESSION_HOURS = 12


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt(rounds=int(config.env("BCRYPT_ROUNDS", "12")))).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


_DUMMY = None


def _dummy_hash() -> str:
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(secrets.token_hex(8))
    return _DUMMY


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _secure(request: Request) -> bool:
    mode = config.env("COOKIE_SECURE", "auto").lower()
    if mode in ("1", "true", "yes"):
        return True
    if mode in ("0", "false", "no"):
        return False
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def create_session(user_id: int, request: Request, response: Response) -> str:
    token = secrets.token_urlsafe(32)
    exp = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    with db.get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now(timezone.utc).isoformat(),))
        conn.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                     (_th(token), user_id, db.utcnow_iso(), exp.isoformat()))
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (db.now_iso(), user_id))
    secure = _secure(request)
    response.set_cookie(COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True, samesite="lax", secure=secure, path="/")
    csrf = secrets.token_urlsafe(24)
    response.set_cookie(CSRF_COOKIE, csrf, max_age=SESSION_HOURS * 3600, httponly=False, samesite="strict", secure=secure, path="/")
    return csrf


def destroy_session(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        with db.get_conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Connexion requise")
    with db.get_conn() as conn:
        r = conn.execute(
            "SELECT u.id, u.practice_id, u.email, u.name, u.role, u.practitioner_id, s.expires_at FROM sessions s "
            "JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND u.active=1", (_th(token),)).fetchone()
    if not r or r["expires_at"] < datetime.now(timezone.utc).isoformat():
        raise HTTPException(401, "Session expirée")
    # CSRF : toute requête modifiante doit renvoyer le jeton du cookie ca_csrf dans l'en-tête X-CSRF-Token
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent, cookie = request.headers.get("x-csrf-token", ""), request.cookies.get(CSRF_COOKIE, "")
        if not cookie or not hmac.compare_digest(sent, cookie):
            raise HTTPException(403, "Jeton CSRF manquant ou invalide")
    u = dict(r)
    u.pop("expires_at", None)
    return u


def require_roles(*roles: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "Action réservée à : " + ", ".join(roles))
        return user
    return dep


def authenticate(email: str, password: str) -> dict | None:
    with db.get_conn() as conn:
        r = conn.execute("SELECT * FROM users WHERE email=? AND active=1", (email.strip().lower(),)).fetchone()
    if not r:
        verify_password(password, _dummy_hash())  # temps constant : pas d'énumération des comptes
        return None
    return dict(r) if verify_password(password, r["password_hash"]) else None


def create_user(practice_id: int, email: str, password: str, name: str, role: str = "owner",
                practitioner_id: int | None = None, conn=None) -> int:
    if role not in ROLES:
        raise ValueError("rôle invalide")
    sql = ("INSERT INTO users(practice_id, email, password_hash, name, role, practitioner_id, created_at) VALUES (?,?,?,?,?,?,?)")
    args = (practice_id, email.strip().lower(), hash_password(password), name.strip(), role, practitioner_id, db.now_iso())
    if conn is not None:
        return conn.execute(sql, args).lastrowid
    with db.get_conn() as c:
        return c.execute(sql, args).lastrowid
