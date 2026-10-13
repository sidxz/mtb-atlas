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

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .fetch import ROOT

HOUR = 3600.0
DAY = 86400.0
ANONYMOUS = (5, HOUR)
SIGNED_IN = (20, DAY)
GLOBAL_LIMIT = 500


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
