"""Optional single-user password login for cloud hosting.

OFF unless ATLAS_AUTH_PASSWORD is set, so the local (Windows) setup is unchanged. When on, every /api and /ws request except login/status/health needs a signed,
expiring session cookie; state-changing requests from another website are refused (CSRF). The session key is derived from the password, so sessions survive
restarts and changing the password logs everyone out. The password lives only in the server's environment.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

MIN_PASSWORD = 12
COOKIE = "atlas_session"
MAX_AGE = 7 * 86400
MAX_FAILS, FAIL_WINDOW = 5, 300
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
PUBLIC_API = {"/api/auth/login", "/api/auth/logout", "/api/auth/status", "/api/health"}


def refuse_open_server(host: str, password: str | None) -> str | None:
    """A non-local bind without a password would expose ATLAS to the internet. Return the reason to refuse, or None."""
    if host not in LOCAL_HOSTS and not password:
        return (f"Refusing to listen on {host} without a login. Set ATLAS_AUTH_PASSWORD (at least {MIN_PASSWORD} characters), "
                "or keep ATLAS_HOST=127.0.0.1 for local use.")
    return None


class Auth:
    def __init__(self, password: str | None):
        self.enabled = bool(password)
        if self.enabled and len(password) < MIN_PASSWORD:
            raise ValueError(f"ATLAS_AUTH_PASSWORD must be at least {MIN_PASSWORD} characters")
        self._pw = hashlib.sha256((password or "").encode()).digest()
        self._key = hashlib.sha256(b"atlas-session-v1:" + (password or "").encode()).digest()
        self._fails: dict[str, list[float]] = {}

    def check_password(self, given: str) -> bool:
        return hmac.compare_digest(hashlib.sha256(given.encode()).digest(), self._pw)

    def make_token(self, now: float | None = None) -> str:
        exp = str(int((now if now is not None else time.time()) + MAX_AGE))
        return f"{exp}.{hmac.new(self._key, exp.encode(), hashlib.sha256).hexdigest()}"

    def valid_token(self, token: str | None, now: float | None = None) -> bool:
        if not self.enabled or not token or "." not in token:
            return False
        exp, sig = token.split(".", 1)
        good = hmac.new(self._key, exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, good) and exp.isdigit() and int(exp) > (now if now is not None else time.time())

    def retry_after(self, ip: str, now: float | None = None) -> int:
        """Seconds to wait if this address has failed too often recently, else 0."""
        now = now if now is not None else time.time()
        recent = [t for t in self._fails.get(ip, []) if now - t < FAIL_WINDOW]
        self._fails[ip] = recent
        return int(FAIL_WINDOW - (now - recent[0])) + 1 if len(recent) >= MAX_FAILS else 0

    def record_failure(self, ip: str, now: float | None = None) -> None:
        self._fails.setdefault(ip, []).append(now if now is not None else time.time())
        if len(self._fails) > 1000:                                         # bound memory
            self._fails = {k: v for k, v in self._fails.items() if v and (now or time.time()) - v[-1] < FAIL_WINDOW}

    def clear_failures(self, ip: str) -> None:
        self._fails.pop(ip, None)


def _cookie(headers: list[tuple[bytes, bytes]]) -> str | None:
    for k, v in headers:
        if k == b"cookie":
            for part in v.decode("latin-1").split(";"):
                name, _, val = part.strip().partition("=")
                if name == COOKIE:
                    return val
    return None


def _header(headers, name: bytes) -> str | None:
    return next((v.decode("latin-1") for k, v in headers if k == name), None)


class AuthMiddleware:
    """Pure ASGI (covers HTTP and WebSocket). Static web files stay public: they hold no data, and they contain the login screen."""

    def __init__(self, app, auth: Auth, allowed_origins: set[str]):
        self.app, self.auth, self.origins = app, auth, allowed_origins

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not self.auth.enabled:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        guarded = path.startswith("/api/") or path.startswith("/ws/") or path in ("/api", "/ws")
        if not guarded:
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        if scope["type"] == "http":
            method = scope.get("method", "GET")
            origin, site = _header(headers, b"origin"), _header(headers, b"sec-fetch-site")
            if method not in ("GET", "HEAD", "OPTIONS") and ((origin is not None and origin not in self.origins) or site == "cross-site"):
                return await self._deny(send, 403, "FORBIDDEN_ORIGIN", "Requests from other websites are refused.")
            if method == "OPTIONS" or path in PUBLIC_API:
                return await self.app(scope, receive, send)
            if not self.auth.valid_token(_cookie(headers)):
                return await self._deny(send, 401, "AUTH_REQUIRED", "Please log in.")
        elif not self.auth.valid_token(_cookie(headers)):
            await send({"type": "websocket.close", "code": 1008})
            return
        return await self.app(scope, receive, send)

    @staticmethod
    async def _deny(send, status: int, code: str, message: str):
        body = json.dumps({"ok": False, "error": {"code": code, "message": message}}).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
