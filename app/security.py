"""Sécurité transverse : limitation de débit, en-têtes HTTP (CSP…), journal d'audit sans PII."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from . import config, db

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)

# (requêtes, fenêtre en secondes)
LIMITS = {
    "login": (10, 300), "signup": (5, 3600), "chat": (40, 60), "leads": (5, 300), "checkout": (10, 300),
    "inbound": (120, 60), "espace": (300, 60),
}


def enabled() -> bool:
    return config.env("RATE_LIMIT_ENABLED", "1").lower() not in ("0", "false", "no")


def client_ip(request: Request) -> str:
    if config.env("TRUST_PROXY", "1") == "1":
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check(bucket: str, key: str) -> None:
    if not enabled():
        return
    limit, window = LIMITS[bucket]
    now = time.monotonic()
    k = f"{bucket}:{key}"
    with _lock:
        q = _hits[k]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "Trop de requêtes, réessayez dans quelques minutes.",
                                headers={"Retry-After": str(int(window - (now - q[0])) + 1)})
        q.append(now)


def reset() -> None:
    with _lock:
        _hits.clear()


def limiter(bucket: str):
    def dep(request: Request):
        check(bucket, client_ip(request))
    return dep


CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self' "
       "https://checkout.stripe.com https://checkout.flutterwave.com https://checkout.paystack.com")


async def headers_middleware(request: Request, call_next):
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
        h.setdefault("Content-Security-Policy", CSP)
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith(("/api/espace", "/api/auth", "/api/admin")):
        h["Cache-Control"] = "no-store"
    return resp


def audit(practice_id: int | None, user_id: int | None, action: str, entity: str | None = None,
          entity_id: int | None = None, request: Request | None = None) -> None:
    """Journal d'audit (qui a fait quoi, quand) — identifiants uniquement, jamais de données de santé."""
    with db.get_conn() as conn:
        conn.execute("INSERT INTO audit_log(practice_id, user_id, action, entity, entity_id, ip, created_at) VALUES (?,?,?,?,?,?,?)",
                     (practice_id, user_id, action, entity, entity_id, client_ip(request) if request else None, db.now_iso()))
