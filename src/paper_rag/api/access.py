"""Access requests and sessions for public (tunnelled) mode.

Flow: a visitor files a request (gets request_id + claim_secret) → the admin approves it in the
localhost-only console → the visitor's next status poll, carrying the claim secret, receives a
session token (set as an HttpOnly cookie). Only sha256 hashes of secrets/tokens are stored.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUEST_TTL_S = 30 * 60
MAX_PENDING_PER_IP = 3
MAX_PENDING_TOTAL = 50
MAX_NAME = 80
MAX_REASON = 500
ONE_TIME_CODE_TTL_S = 60

# USD per million tokens: (input, output, cache read, cache write). Used for the admin cost estimate.
PRICING = {
    "claude-opus-5": (5.0, 25.0, 0.5, 6.25),
    "claude-opus-5-5": (4.0, 20.0, 0.4, 5.0),
    "claude-sonnet-5": (2.0, 10.0, 0.2, 2.5),
    "claude-haiku-4-5": (1.0, 5.0, 0.1, 1.25),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY, claim_hash TEXT NOT NULL, name TEXT NOT NULL, reason TEXT NOT NULL,
    ip TEXT, user_agent TEXT, created_at REAL NOT NULL, status TEXT NOT NULL,
    decided_at REAL, hours REAL, quota INTEGER, session_id TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL, ip TEXT,
    created_at REAL NOT NULL, expires_at REAL NOT NULL, quota INTEGER, questions_used INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0, revoked INTEGER NOT NULL DEFAULT 0, is_admin INTEGER NOT NULL DEFAULT 0,
    last_used_at REAL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class AccessError(Exception):
    """Raised with a machine-readable code and the HTTP status the API should return."""

    def __init__(self, code: str, status: int, message: str):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Session:
    id: str
    name: str
    expires_at: float
    quota: int | None
    questions_used: int
    is_admin: bool

    @property
    def questions_left(self) -> int | None:
        return None if self.quota is None else max(0, self.quota - self.questions_used)


class AccessManager:
    def __init__(self, db_path: Path, default_hours: float = 24, default_quota: int = 30):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_hours = default_hours
        self.default_quota = default_quota
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._lock = threading.Lock()
        self._one_time_codes: dict[str, tuple[str, float]] = {}  # code hash → (session token, expiry)
        self.version = 0  # bumped on every change; the admin SSE feed watches it

    def _changed(self) -> None:
        self.version += 1

    # ------------------------------------------------------------ global pause
    @property
    def paused(self) -> bool:
        row = self._db.execute("SELECT value FROM kv WHERE key='paused'").fetchone()
        return bool(row and row["value"] == "1")

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO kv(key, value) VALUES('paused', ?)", ("1" if paused else "0",))
            self._changed()

    # ------------------------------------------------------------ visitor side
    def _expire_stale(self, now: float) -> None:
        cur = self._db.execute("UPDATE requests SET status='expired' WHERE status IN ('pending','approved') "
                               "AND created_at < ?", (now - REQUEST_TTL_S,))
        if cur.rowcount:
            self._changed()

    def create_request(self, name: str, reason: str, ip: str | None, user_agent: str | None) -> tuple[str, str]:
        name, reason = (name or "").strip(), (reason or "").strip()
        if not name:
            raise AccessError("invalid", 400, "Please enter your name.")
        if len(name) > MAX_NAME or len(reason) > MAX_REASON:
            raise AccessError("invalid", 400, "Name or reason is too long.")
        if self.paused:
            raise AccessError("paused", 503, "Access requests are paused right now.")
        now = time.time()
        with self._lock:
            self._expire_stale(now)
            pending = self._db.execute("SELECT COUNT(*) AS n FROM requests WHERE status='pending'").fetchone()["n"]
            if pending >= MAX_PENDING_TOTAL:
                raise AccessError("busy", 429, "Too many pending requests. Try again later.")
            if ip:
                mine = self._db.execute("SELECT COUNT(*) AS n FROM requests WHERE status='pending' AND ip=?",
                                        (ip,)).fetchone()["n"]
                if mine >= MAX_PENDING_PER_IP:
                    raise AccessError("busy", 429, "You already have pending requests. Please wait for a decision.")
            request_id = secrets.token_urlsafe(12)
            claim_secret = secrets.token_urlsafe(24)
            self._db.execute(
                "INSERT INTO requests(id, claim_hash, name, reason, ip, user_agent, created_at, status) "
                "VALUES(?,?,?,?,?,?,?, 'pending')",
                (request_id, _hash(claim_secret), name, reason, ip, (user_agent or "")[:300], now),
            )
            self._changed()
        return request_id, claim_secret

    def check_request(self, request_id: str, claim_secret: str) -> tuple[str, str | None]:
        """Returns (status, session_token). The token is issued exactly once, on the first poll after approval."""
        with self._lock:
            self._expire_stale(time.time())
            row = self._db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if row is None or not secrets.compare_digest(row["claim_hash"], _hash(claim_secret or "")):
                raise AccessError("not_found", 404, "Unknown request.")
            if row["status"] != "approved":
                return row["status"], None
            token, session_id = self._new_session(row["name"], row["ip"], row["hours"], row["quota"], is_admin=False)
            self._db.execute("UPDATE requests SET status='claimed', session_id=? WHERE id=?", (session_id, request_id))
            self._changed()
            return "approved", token

    def _new_session(self, name: str, ip: str | None, hours: float, quota: int | None, is_admin: bool) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        session_id = secrets.token_urlsafe(9)
        now = time.time()
        self._db.execute(
            "INSERT INTO sessions(id, token_hash, name, ip, created_at, expires_at, quota, is_admin) VALUES(?,?,?,?,?,?,?,?)",
            (session_id, _hash(token), name, ip, now, now + hours * 3600, quota, int(is_admin)),
        )
        return token, session_id

    def validate(self, token: str | None) -> Session:
        if not token:
            raise AccessError("no_session", 401, "Access required.")
        row = self._db.execute("SELECT * FROM sessions WHERE token_hash=?", (_hash(token),)).fetchone()
        if row is None:
            raise AccessError("no_session", 401, "Access required.")
        if row["revoked"]:
            raise AccessError("revoked", 401, "Your access was revoked.")
        if row["expires_at"] < time.time():
            raise AccessError("expired", 401, "Your access has expired.")
        if self.paused and not row["is_admin"]:
            raise AccessError("paused", 503, "Public access is paused right now.")
        return Session(row["id"], row["name"], row["expires_at"], row["quota"], row["questions_used"], bool(row["is_admin"]))

    def begin_question(self, session: Session) -> None:
        with self._lock:
            cur = self._db.execute(
                "UPDATE sessions SET questions_used = questions_used + 1, last_used_at=? "
                "WHERE id=? AND (quota IS NULL OR questions_used < quota)", (time.time(), session.id))
            if cur.rowcount == 0:
                raise AccessError("quota", 429, "You have used all the questions for this session.")
            self._changed()

    def record_usage(self, session_id: str, usage: dict[str, int], model: str) -> None:
        inp, out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        cr, cw = usage.get("cache_read_input_tokens", 0), usage.get("cache_creation_input_tokens", 0)
        price = next((p for m, p in PRICING.items() if model.startswith(m)), None)
        cost = sum(t * p for t, p in zip((inp, out, cr, cw), price)) / 1e6 if price else 0.0
        with self._lock:
            self._db.execute(
                "UPDATE sessions SET input_tokens=input_tokens+?, output_tokens=output_tokens+?, "
                "cache_read_tokens=cache_read_tokens+?, cache_write_tokens=cache_write_tokens+?, cost_usd=cost_usd+? "
                "WHERE id=?", (inp, out, cr, cw, cost, session_id))
            self._changed()

    def questions_left(self, session_id: str) -> int | None:
        row = self._db.execute("SELECT quota, questions_used FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None or row["quota"] is None:
            return None
        return max(0, row["quota"] - row["questions_used"])

    # ------------------------------------------------------------ admin side
    def approve(self, request_id: str, hours: float | None = None, quota: int | None = None,
                unlimited: bool = False) -> None:
        hours = hours if hours and hours > 0 else self.default_hours
        quota = None if unlimited else (quota if quota and quota > 0 else self.default_quota)
        with self._lock:
            cur = self._db.execute("UPDATE requests SET status='approved', decided_at=?, hours=?, quota=? "
                                   "WHERE id=? AND status='pending'", (time.time(), hours, quota, request_id))
            if cur.rowcount == 0:
                raise AccessError("not_found", 404, "No pending request with that id.")
            self._changed()

    def deny(self, request_id: str) -> None:
        with self._lock:
            cur = self._db.execute("UPDATE requests SET status='denied', decided_at=? WHERE id=? AND status='pending'",
                                   (time.time(), request_id))
            if cur.rowcount == 0:
                raise AccessError("not_found", 404, "No pending request with that id.")
            self._changed()

    def revoke(self, session_id: str) -> None:
        with self._lock:
            cur = self._db.execute("UPDATE sessions SET revoked=1 WHERE id=?", (session_id,))
            if cur.rowcount == 0:
                raise AccessError("not_found", 404, "No such session.")
            self._changed()

    def create_admin_login_code(self) -> str:
        """One-time code the admin console exchanges (on the app port) for an unlimited admin session."""
        with self._lock:
            token, _ = self._new_session("admin", "127.0.0.1", 24 * 7, None, is_admin=True)
            code = secrets.token_urlsafe(24)
            now = time.time()
            self._one_time_codes = {k: v for k, v in self._one_time_codes.items() if v[1] > now}
            self._one_time_codes[_hash(code)] = (token, now + ONE_TIME_CODE_TTL_S)
            self._changed()
            return code

    def redeem_login_code(self, code: str) -> str:
        with self._lock:
            entry = self._one_time_codes.pop(_hash(code or ""), None)
        if entry is None or entry[1] < time.time():
            raise AccessError("invalid", 400, "This login link is invalid or has expired.")
        return entry[0]

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            self._expire_stale(now)
            pending = [dict(r) for r in self._db.execute(
                "SELECT id, name, reason, ip, user_agent, created_at FROM requests WHERE status='pending' "
                "ORDER BY created_at")]
            recent = [dict(r) for r in self._db.execute(
                "SELECT id, name, status, decided_at FROM requests WHERE status IN ('denied','claimed','expired') "
                "ORDER BY COALESCE(decided_at, created_at) DESC LIMIT 20")]
            sessions = [dict(r) for r in self._db.execute(
                "SELECT id, name, ip, created_at, expires_at, quota, questions_used, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, cost_usd, revoked, is_admin, last_used_at FROM sessions "
                "WHERE expires_at > ? - 86400 ORDER BY created_at DESC LIMIT 200", (now,))]
        for s in sessions:
            s["active"] = not s["revoked"] and s["expires_at"] > now
        return {"paused": self.paused, "pending": pending, "recent": recent, "sessions": sessions, "now": now}
