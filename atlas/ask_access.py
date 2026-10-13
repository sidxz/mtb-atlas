"""Who may ask, and how often: the one route that spends money gets an allowance.

Anonymous askers pass a Cloudflare Turnstile check and get 5 an hour per IP; an
ORCID sign-in gets 20 a day per iD; everyone together gets 500 a day. The counts
live in a small SQLite file, not the Parquet store, and the pipeline never
touches it. An IP is never written down: only its HMAC under ATLAS_SECRET, and
every row is gone after 24 h.

Turnstile and ORCID are called at request time, unlike everything behind
`atlas/fetch.py`: they check a visitor rather than supply data, and nothing they
return is kept but the ORCID iD.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .fetch import ROOT

HOUR = 3600.0
DAY = 86400.0
ANONYMOUS = (5, HOUR)
SIGNED_IN = (20, DAY)
GLOBAL_LIMIT = 500
SESSION_COOKIE = "atlas_session"
STATE_COOKIE = "atlas_oauth_state"
SESSION_SECONDS = 30 * DAY
STATE_SECONDS = 600.0
TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
ORCID_ID = re.compile(r"[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]")


def _env(name: str) -> str | None:
    return os.environ.get(name) or None


def limits_on() -> bool:
    return (_env("ATLAS_ASK_LIMITS") or "on").lower() != "off"


def usage_db() -> Path:
    # ponytail: in the container this file is container-local, so a redeploy resets
    # every count, the global 500 included. Harmless for 24 h windows, and it keeps
    # SQLite off NFS, whose locking it cannot trust. Shared storage if that changes.
    return Path(_env("ATLAS_USAGE_DB") or ROOT / "data" / "ask_usage.sqlite")


@dataclass(frozen=True)
class Verdict:
    admitted: bool
    # Which limit refused: "ip", "orcid" or "global". None when admitted.
    limit: str | None
    # Seconds until the next ask would be admitted; 0 when admitted.
    retry_after: float
    remaining: int
    global_remaining: int


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: transactions are begun by hand, so BEGIN IMMEDIATE means it.
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.execute("CREATE TABLE IF NOT EXISTS asks (key TEXT NOT NULL, at REAL NOT NULL)")
    connection.execute("CREATE INDEX IF NOT EXISTS asks_key_at ON asks (key, at)")
    return connection


def admit(
    key: str,
    limit: int,
    window: float,
    *,
    now: float | None = None,
    record: bool = True,
    path: Path | None = None,
) -> Verdict:
    """Count one ask against `key` if both its own limit and the global one allow it.

    One BEGIN IMMEDIATE transaction takes the write lock before counting, so two
    requests racing for the last slot cannot both be admitted. `record=False` asks
    the same question without spending anything (for `/auth/me`).
    """
    now = time.time() if now is None else now
    connection = _connect(path or usage_db())
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM asks WHERE at <= ?", (now - DAY,))
        mine = [
            r[0]
            for r in connection.execute(
                "SELECT at FROM asks WHERE key = ? AND at > ? ORDER BY at", (key, now - window)
            )
        ]
        everyone = [
            r[0]
            for r in connection.execute(
                "SELECT at FROM asks WHERE at > ? ORDER BY at", (now - DAY,)
            )
        ]
        if len(everyone) >= GLOBAL_LIMIT:
            # The next slot opens when the oldest of the last GLOBAL_LIMIT leaves the day.
            opens = everyone[len(everyone) - GLOBAL_LIMIT] + DAY
            verdict = Verdict(False, "global", opens - now, max(limit - len(mine), 0), 0)
        elif len(mine) >= limit:
            opens = mine[len(mine) - limit] + window
            verdict = Verdict(
                False, key.split(":", 1)[0], opens - now, 0, GLOBAL_LIMIT - len(everyone)
            )
        else:
            spent = 1 if record else 0
            if record:
                connection.execute("INSERT INTO asks VALUES (?, ?)", (key, now))
            verdict = Verdict(
                True, None, 0.0, limit - len(mine) - spent, GLOBAL_LIMIT - len(everyone) - spent
            )
        connection.execute("COMMIT")
        return verdict
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def secret_configured() -> bool:
    return _env("ATLAS_SECRET") is not None


def turnstile_configured() -> bool:
    return bool(_env("TURNSTILE_SITE_KEY") and _env("TURNSTILE_SECRET_KEY"))


def turnstile_site_key() -> str | None:
    return _env("TURNSTILE_SITE_KEY")


def signin_available() -> bool:
    names = ("ATLAS_SECRET", "ORCID_CLIENT_ID", "ORCID_CLIENT_SECRET", "ATLAS_PUBLIC_URL")
    return limits_on() and all(_env(name) for name in names)


# --- signing -------------------------------------------------------------------


def _sign(payload: str) -> str:
    secret = _env("ATLAS_SECRET")
    if secret is None:
        raise RuntimeError("ATLAS_SECRET is not set")
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _signed(*fields: str) -> str:
    payload = "|".join(fields)
    return f"{payload}|{_sign(payload)}"


def _unsigned(value: str | None, n: int) -> list[str] | None:
    """The n fields of a value signed here, or None for anything tampered or foreign."""
    if not value or not secret_configured():
        return None
    parts = value.split("|")
    if len(parts) != n + 1:
        return None
    # compare_digest raises on non-ASCII str, so compare the bytes.
    expected = _sign("|".join(parts[:-1])).encode()
    if not hmac.compare_digest(expected, parts[-1].encode()):
        return None
    return parts[:-1]


def ip_key(ip: str) -> str:
    return f"ip:{_sign(ip)}"


def orcid_key(orcid: str) -> str:
    return f"orcid:{orcid}"


def make_session(orcid: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    return _signed(orcid, str(int(now + SESSION_SECONDS)))


def read_session(cookie: str | None, now: float | None = None) -> str | None:
    """The signed-in ORCID iD, or None: a bad cookie is no cookie, never an error."""
    fields = _unsigned(cookie, 2)
    if fields is None:
        return None
    orcid, expiry = fields
    now = time.time() if now is None else now
    if not ORCID_ID.fullmatch(orcid) or not expiry.isdigit() or int(expiry) <= now:
        return None
    return orcid


def safe_next(path: str | None) -> str:
    """A path on this site to come back to after sign-in, or `/`: never an open redirect."""
    if (
        not path
        or not path.startswith("/")
        or path.startswith("//")
        or len(path) > 500
        or any(c in path for c in "\\|")
        or any(c.isspace() or not c.isprintable() for c in path)
    ):
        return "/"
    return path


def make_state(nonce: str, next_path: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    return _signed(nonce, safe_next(next_path), str(int(now + STATE_SECONDS)))


def read_state(cookie: str | None, now: float | None = None) -> tuple[str, str] | None:
    fields = _unsigned(cookie, 3)
    if fields is None:
        return None
    nonce, next_path, expiry = fields
    now = time.time() if now is None else now
    if not expiry.isdigit() or int(expiry) <= now:
        return None
    return nonce, next_path


# --- Turnstile and ORCID ---------------------------------------------------------


def verify_turnstile(token: str | None, ip: str) -> bool:
    """Cloudflare's verdict on one single-use token. Anything but a clear yes is no."""
    secret = _env("TURNSTILE_SECRET_KEY")
    if not token or secret is None:
        return False
    try:
        response = httpx.post(
            TURNSTILE_VERIFY,
            data={"secret": secret, "response": token, "remoteip": ip},
            timeout=5.0,
        )
        return response.status_code == 200 and response.json().get("success") is True
    except (httpx.HTTPError, ValueError):
        return False


def public_url() -> str:
    return (_env("ATLAS_PUBLIC_URL") or "").rstrip("/")


def _orcid_base() -> str:
    return (_env("ORCID_BASE") or "https://orcid.org").rstrip("/")


def _redirect_uri() -> str:
    return f"{public_url()}/api/auth/orcid/callback"


def authorize_url(nonce: str) -> str:
    query = urlencode(
        {
            "client_id": _env("ORCID_CLIENT_ID") or "",
            "response_type": "code",
            # /authenticate reads the iD and nothing else, and can never write to a record.
            "scope": "/authenticate",
            "redirect_uri": _redirect_uri(),
            "state": nonce,
        }
    )
    return f"{_orcid_base()}/oauth/authorize?{query}"


def exchange_code(code: str) -> str | None:
    """The iD ORCID vouches for, or None. The access token and the name are discarded."""
    try:
        response = httpx.post(
            f"{_orcid_base()}/oauth/token",
            data={
                "client_id": _env("ORCID_CLIENT_ID") or "",
                "client_secret": _env("ORCID_CLIENT_SECRET") or "",
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(),
            },
            headers={"Accept": "application/json"},
            timeout=10.0,
        )
        orcid = response.json().get("orcid") if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None
    return orcid if isinstance(orcid, str) and ORCID_ID.fullmatch(orcid) else None
