# Public Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the atlas safe to host publicly: an allowance on `/ask`, one universal Docker image with no site baked in, and the privacy, cookie, licence and terms pages a public site owes its visitors.

**Architecture:** `atlas/ask_access.py` holds the limiter (SQLite, stdlib), the Turnstile check, the HMAC-signed session and the ORCID exchange; `atlas/api.py` wires them into `/ask` and four `/auth/*` routes. `atlas/serve.py` mounts the existing API at `/api` and the built page at `/` so one uvicorn process serves both. The frontend gains an allowance strip in the Ask bar, a footer, a one-line notice and three `/about/*` pages. A GitHub Actions workflow publishes `ghcr.io/sidxz/mtb-atlas`; ned's stack lives in the infra repo.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, sqlite3, httpx, DuckDB; React 18 + React Router 7 + Vite 5; Docker, GitHub Actions, Docker Swarm + Traefik 3.

**Spec:** `docs/superpowers/specs/2026-10-12-public-release-design.md`

## Global Constraints

- Limits: anonymous **5 per IP per rolling 1 h**; ORCID **20 per iD per rolling 24 h** (replaces, not stacks); **500 per rolling 24 h across everyone**.
- Effort is fixed at `"high"`; `Question.effort` is removed.
- Counted when admitted; a model error does not refund; a refusal never counts.
- Refusals: **429** with `Retry-After` and `detail = {"limit": "ip"|"orcid"|"global", "retry_after": <int seconds>}`; failed CAPTCHA **403**; incomplete configuration **503**.
- An IP is never stored in clear: key is `ip:<hex HMAC-SHA256(ATLAS_SECRET, ip)>`; rows older than 24 h are deleted.
- Session cookie `atlas_session` = `<orcid>|<expiry>|<hmac>`, `HttpOnly; Secure; SameSite=Lax; Path=/`, 30 days. Only the ORCID iD is kept.
- Missing configuration **fails closed**. `ATLAS_ASK_LIMITS=off` disables the whole layer.
- No host name in any image or bundle. Everything site-specific is an env var (table in the spec, Part 2).
- The store is **never** in the image; mounted read-only at `ATLAS_STORE`.
- One uvicorn process per container.
- No consent banner; a dismissible information notice only.
- No new Python dependency. One new npm dependency: `@fontsource/inter`.
- Python: ruff, line length 100. Commits: conventional, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, **never** a `Claude-Session:` trailer.
- Tests run on fixtures, never the network.

## Review Focus

1. **Visitor IP behind Traefik.** If `FORWARDED_ALLOW_IPS` does not cover the proxy, every visitor shares one bucket of 5. Expected: two visitors on different networks have separate allowances. Pinned by the post-deploy check in Task 11, Step 5, and documented in Task 10.
2. **Turnstile blocked by a privacy extension.** An anonymous visitor whose browser blocks `challenges.cloudflare.com` must be told why they cannot ask and offered ORCID, not left with a silent failure. Pinned in Task 6 (`captchaUnavailableMessage` test).
3. **Sign-in from a deep link.** Starting at `/targets/Rv1484?filter=x` must come back to exactly that path; a crafted `next` (`//evil.example`, `https://…`, `/\evil`) must come back to `/`. Pinned in Task 3 (`safe_next` tests) and Task 5 (login round trip).
4. **The rolling-window edge.** An ask exactly one window after the oldest counted one is admitted, and `retry_after` names that moment. Pinned in Task 2.
5. **A 429 body is no longer a string.** The Ask bar used to print `body.detail` as text; an object must become a sentence, not `[object Object]`. Pinned in Task 6 (`refusalMessage` tests).

---

## File structure

| File | Responsibility |
|---|---|
| `atlas/fetch.py` (modify) | `STORE` honours `ATLAS_STORE` |
| `atlas/ask_access.py` (create) | limiter, signing, session, state, Turnstile, ORCID exchange — no FastAPI |
| `atlas/api.py` (modify) | `/ask` gate, `/auth/me`, `/auth/orcid/login`, `/auth/orcid/callback`, `/auth/logout`, `site` on `/meta` |
| `atlas/serve.py` (create) | the one-container ASGI app |
| `tests/test_ask_access.py` (create) | limiter, signing, routes |
| `tests/test_serve.py` (create) | static serving, SPA fallback, `ATLAS_STORE` |
| `web/src/askAccess.ts` (create) | pure helpers: allowance label, refusal sentences |
| `web/tests/ask-access.test.mjs` (create) | tests for the above |
| `web/src/api.ts` (modify) | `Me`, `Site` types, `api.me()` |
| `web/src/Ask.tsx` (modify) | Turnstile, sign-in, allowance, refusals |
| `web/src/About.tsx` (create) | `/about/sources`, `/about/privacy`, `/about/terms`, footer, notice |
| `web/src/App.tsx` (modify) | `about` view, footer, notice |
| `web/src/styles.css` (modify) | footer row, notice, allowance strip, about pages |
| `web/index.html`, `web/src/main.tsx` (modify) | self-hosted Inter |
| `Dockerfile`, `.dockerignore`, `docker-compose.prod.yml`, `.env.example` (create) | the image and a generic way to run it |
| `.github/workflows/publish-image.yml` (create) | build, smoke-test, push |
| `LICENSE` (create), `.gitignore`, `pyproject.toml`, `README.md`, `CLAUDE.md` (modify) | housekeeping and docs |
| `../snet2-infrastructure/docker-swarm-core/149-atlas/*` (create) | ned's stack, deploy script |

---

### Task 1: `ATLAS_STORE`

**Files:**
- Modify: `atlas/fetch.py:29-31`
- Test: `tests/test_serve.py` (created here, extended in Task 7)

**Interfaces:**
- Produces: `atlas.fetch.STORE: Path` = `$ATLAS_STORE` if set, else `ROOT / "data" / "store"`. Every module that imports `STORE` already imports it from here (via `atlas.store`), so nothing else changes.

- [ ] **Step 1: Write the failing test**

Create `tests/test_serve.py`:

```python
"""The one-container entry point, and the paths it takes from the environment."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _store_seen_with(env: dict[str, str]) -> str:
    # A fresh interpreter, because STORE is read once at import.
    result = subprocess.run(
        [sys.executable, "-c", "from atlas.fetch import STORE; print(STORE)"],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_atlas_store_moves_where_the_store_is_read(tmp_path: Path) -> None:
    assert _store_seen_with({"ATLAS_STORE": str(tmp_path)}) == str(tmp_path)


def test_without_atlas_store_the_store_is_where_it_always_was() -> None:
    env = {k: v for k, v in os.environ.items() if k != "ATLAS_STORE"}
    seen = subprocess.run(
        [sys.executable, "-c", "from atlas.fetch import STORE; print(STORE)"],
        env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert seen.endswith(os.path.join("data", "store"))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_serve.py -v`
Expected: `test_atlas_store_moves_where_the_store_is_read` FAILS (prints `.../data/store`).

- [ ] **Step 3: Implement**

In `atlas/fetch.py`, add `import os` to the imports if absent, and replace line 31:

```python
# The pipeline writes here; a deployed API reads a store mounted elsewhere.
STORE = Path(os.environ.get("ATLAS_STORE") or ROOT / "data" / "store")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_serve.py -v && uv run pytest -q`
Expected: both new tests PASS; full suite PASS (650+).

- [ ] **Step 5: Commit**

```bash
git add atlas/fetch.py tests/test_serve.py
git commit -m "feat: ATLAS_STORE says where a deployed API finds the store

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The limiter

**Files:**
- Create: `atlas/ask_access.py`
- Create: `tests/test_ask_access.py`
- Modify: `.gitignore` (add `data/ask_usage.sqlite`)

**Interfaces:**
- Produces:
  - constants `HOUR = 3600.0`, `DAY = 86400.0`, `ANONYMOUS = (5, HOUR)`, `SIGNED_IN = (20, DAY)`, `GLOBAL_LIMIT = 500`
  - `limits_on() -> bool`, `usage_db() -> Path`
  - `@dataclass(frozen=True) class Verdict: admitted: bool; limit: str | None; retry_after: float; remaining: int; global_remaining: int`
  - `admit(key: str, limit: int, window: float, *, now: float | None = None, record: bool = True, path: Path | None = None) -> Verdict` — `record=False` peeks without counting. Refused `limit` is `"global"` or the key's prefix (`"ip"`, `"orcid"`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ask_access.py`:

```python
"""/ask's allowance: the counting, the signing, and the routes that use them.

Turnstile and ORCID are never called: their two functions are replaced, so these
tests run offline like every other test here.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from atlas import ask_access as access

T0 = 1_800_000_000.0  # a fixed clock; nothing here sleeps


def test_five_an_hour_then_refused_with_the_moment_it_reopens(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    for i in range(5):
        assert access.admit("ip:a", 5, access.HOUR, now=T0 + i, path=db).admitted
    refused = access.admit("ip:a", 5, access.HOUR, now=T0 + 10, path=db)
    assert not refused.admitted
    assert refused.limit == "ip"
    # The oldest counted ask (T0) leaves the window at T0 + 3600.
    assert refused.retry_after == pytest.approx(3600 - 10)


def test_the_window_rolls_at_exactly_one_window(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    for i in range(5):
        access.admit("ip:a", 5, access.HOUR, now=T0 + i, path=db)
    assert not access.admit("ip:a", 5, access.HOUR, now=T0 + 3599, path=db).admitted
    assert access.admit("ip:a", 5, access.HOUR, now=T0 + 3600, path=db).admitted


def test_a_refusal_is_not_counted(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    for i in range(7):
        access.admit("ip:a", 5, access.HOUR, now=T0 + i, path=db)
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT count(*) FROM asks").fetchone()[0] == 5


def test_keys_do_not_share_an_allowance(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    for i in range(5):
        access.admit("ip:a", 5, access.HOUR, now=T0 + i, path=db)
    assert access.admit("ip:b", 5, access.HOUR, now=T0 + 6, path=db).admitted


def test_the_global_ceiling_refuses_everyone(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    access.admit("ip:seed", 5, access.HOUR, now=T0, path=db)  # creates the table
    with sqlite3.connect(db) as connection:
        connection.executemany(
            "INSERT INTO asks VALUES (?, ?)",
            [(f"orcid:{i}", T0 + 1 + i) for i in range(access.GLOBAL_LIMIT - 1)],
        )
    refused = access.admit("orcid:fresh", 20, access.DAY, now=T0 + 600, path=db)
    assert not refused.admitted
    assert refused.limit == "global"
    assert refused.retry_after == pytest.approx(access.DAY - 600)


def test_peeking_does_not_count(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    peek = access.admit("ip:a", 5, access.HOUR, now=T0, path=db, record=False)
    assert peek.admitted and peek.remaining == 5
    assert access.admit("ip:a", 5, access.HOUR, now=T0, path=db).remaining == 4


def test_two_racers_for_the_last_slot_get_exactly_one(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    for i in range(4):
        access.admit("ip:a", 5, access.HOUR, now=T0 + i, path=db)
    barrier = threading.Barrier(2)
    results: list[bool] = []

    def race() -> None:
        barrier.wait()
        results.append(access.admit("ip:a", 5, access.HOUR, now=T0 + 10, path=db).admitted)

    threads = [threading.Thread(target=race) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False, True]


def test_rows_older_than_a_day_are_deleted(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    access.admit("ip:a", 5, access.HOUR, now=T0, path=db)
    access.admit("ip:b", 5, access.HOUR, now=T0 + access.DAY + 1, path=db)
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT key FROM asks").fetchall() == [("ip:b",)]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_ask_access.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atlas.ask_access'`.

- [ ] **Step 3: Implement**

Create `atlas/ask_access.py`:

```python
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
        mine = [r[0] for r in connection.execute(
            "SELECT at FROM asks WHERE key = ? AND at > ? ORDER BY at", (key, now - window)
        )]
        everyone = [r[0] for r in connection.execute(
            "SELECT at FROM asks WHERE at > ? ORDER BY at", (now - DAY,)
        )]
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
```

Append to `.gitignore`, under the `data/store.prev/` line:

```
# /ask's allowance counts: per-deployment state, never committed
data/ask_usage.sqlite
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ask_access.py -v && make lint`
Expected: 8 PASS; lint clean (run `make fmt` first if formatting differs).

- [ ] **Step 5: Commit**

```bash
git add atlas/ask_access.py tests/test_ask_access.py .gitignore
git commit -m "feat: an allowance counter for /ask

Rolling windows in SQLite, one write-locked transaction per ask, a global
ceiling over every key, and rows gone after a day.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Signing, session, Turnstile and ORCID helpers

**Files:**
- Modify: `atlas/ask_access.py`
- Test: `tests/test_ask_access.py`

**Interfaces:**
- Consumes: `_env` from Task 2.
- Produces:
  - constants `SESSION_COOKIE = "atlas_session"`, `STATE_COOKIE = "atlas_oauth_state"`, `SESSION_SECONDS = 30 * DAY`, `STATE_SECONDS = 600.0`
  - `secret_configured() -> bool`, `turnstile_configured() -> bool`, `turnstile_site_key() -> str | None`, `signin_available() -> bool`
  - `ip_key(ip: str) -> str` (`"ip:<hex hmac>"`), `orcid_key(orcid: str) -> str` (`"orcid:<iD>"`)
  - `make_session(orcid: str, now: float | None = None) -> str`, `read_session(cookie: str | None, now: float | None = None) -> str | None`
  - `safe_next(path: str | None) -> str`
  - `make_state(nonce: str, next_path: str, now: float | None = None) -> str`, `read_state(cookie: str | None, now: float | None = None) -> tuple[str, str] | None` (nonce, next)
  - `verify_turnstile(token: str | None, ip: str) -> bool`
  - `public_url() -> str`, `authorize_url(nonce: str) -> str`, `exchange_code(code: str) -> str | None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ask_access.py`:

```python
IRIS = "0000-0002-1825-0097"  # ORCID's own documentation iD


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_SECRET", "test-secret")


def test_a_session_round_trips(secret: None) -> None:
    assert access.read_session(access.make_session(IRIS, now=T0), now=T0 + 60) == IRIS


@pytest.mark.parametrize(
    "mangle",
    [
        lambda c: c.replace(IRIS, "0000-0001-5109-3700"),  # someone else's iD
        lambda c: c[:-1] + ("0" if c[-1] != "0" else "1"),  # a forged signature
        lambda c: c + "|extra",
        lambda c: "",
        lambda c: "not a cookie",
    ],
)
def test_a_tampered_session_is_no_session(secret: None, mangle) -> None:
    assert access.read_session(mangle(access.make_session(IRIS, now=T0)), now=T0) is None


def test_a_session_expires(secret: None) -> None:
    cookie = access.make_session(IRIS, now=T0)
    assert access.read_session(cookie, now=T0 + access.SESSION_SECONDS + 1) is None


def test_a_session_signed_under_another_secret_is_no_session(
    secret: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    cookie = access.make_session(IRIS, now=T0)
    monkeypatch.setenv("ATLAS_SECRET", "a-different-secret")
    assert access.read_session(cookie, now=T0) is None


def test_an_ip_is_never_its_own_key(secret: None) -> None:
    key = access.ip_key("203.0.113.9")
    assert key.startswith("ip:") and "203.0.113.9" not in key
    assert key == access.ip_key("203.0.113.9")


@pytest.mark.parametrize(
    ("asked", "returned"),
    [
        ("/targets/Rv1484?filter=x", "/targets/Rv1484?filter=x"),
        ("/", "/"),
        ("//evil.example", "/"),
        ("https://evil.example/", "/"),
        ("/\\evil.example", "/"),
        ("/ok|forged", "/"),
        ("/tab\there", "/"),
        ("", "/"),
        (None, "/"),
    ],
)
def test_sign_in_only_returns_to_a_path_on_this_site(asked, returned) -> None:
    assert access.safe_next(asked) == returned


def test_oauth_state_round_trips_and_expires(secret: None) -> None:
    cookie = access.make_state("nonce123", "/map/Rv0206c", now=T0)
    assert access.read_state(cookie, now=T0 + 10) == ("nonce123", "/map/Rv0206c")
    assert access.read_state(cookie, now=T0 + access.STATE_SECONDS + 1) is None


def test_turnstile_without_a_secret_or_token_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    assert access.verify_turnstile("token", "203.0.113.9") is False
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")
    assert access.verify_turnstile(None, "203.0.113.9") is False


def test_signin_needs_every_piece(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ATLAS_SECRET", "ORCID_CLIENT_ID", "ORCID_CLIENT_SECRET", "ATLAS_PUBLIC_URL"):
        monkeypatch.setenv(name, "x")
    monkeypatch.delenv("ATLAS_ASK_LIMITS", raising=False)
    assert access.signin_available()
    monkeypatch.delenv("ORCID_CLIENT_SECRET")
    assert not access.signin_available()


def test_the_authorize_url_names_this_site_and_only_authenticate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORCID_CLIENT_ID", "APP-TEST")
    monkeypatch.setenv("ATLAS_PUBLIC_URL", "https://atlas.example.org/")
    monkeypatch.delenv("ORCID_BASE", raising=False)
    url = access.authorize_url("n1")
    assert url.startswith("https://orcid.org/oauth/authorize?")
    assert "client_id=APP-TEST" in url and "state=n1" in url
    assert "scope=%2Fauthenticate" in url
    assert "redirect_uri=https%3A%2F%2Fatlas.example.org%2Fapi%2Fauth%2Forcid%2Fcallback" in url
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_ask_access.py -v`
Expected: new tests FAIL with `AttributeError: module 'atlas.ask_access' has no attribute 'make_session'` (and similar).

- [ ] **Step 3: Implement**

In `atlas/ask_access.py`, extend the imports:

```python
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
```

Add after `GLOBAL_LIMIT = 500`:

```python
SESSION_COOKIE = "atlas_session"
STATE_COOKIE = "atlas_oauth_state"
SESSION_SECONDS = 30 * DAY
STATE_SECONDS = 600.0
TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
ORCID_ID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
```

Add after `usage_db()`:

```python
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
    if not hmac.compare_digest(_sign("|".join(parts[:-1])), parts[-1]):
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
    if not ORCID_ID.match(orcid) or not expiry.isdigit() or int(expiry) <= now:
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
    return orcid if isinstance(orcid, str) and ORCID_ID.match(orcid) else None
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ask_access.py -v && make lint`
Expected: all PASS; lint clean.

- [ ] **Step 5: Commit**

```bash
git add atlas/ask_access.py tests/test_ask_access.py
git commit -m "feat: signed sessions, Turnstile and ORCID for /ask's allowance

The session holds the ORCID iD and nothing else; a tampered, expired or
foreign cookie is no cookie. Sign-in only returns to a path on this site.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Gate `/ask`; add `/auth/me`

**Files:**
- Modify: `atlas/api.py` (imports near line 8-27; `Question` at ~2230; `/ask` at ~2340)
- Test: `tests/test_ask_access.py`

**Interfaces:**
- Consumes: everything from Tasks 2–3 via `from . import ask_access as access`.
- Produces:
  - `POST /ask` (gated). Refusal bodies: `{"detail": {"limit": str, "retry_after": int}}` (429), `{"detail": str}` (403/503).
  - `GET /auth/me` → `AuthMe` = `{orcid: str|null, limits: bool, remaining: int|null, limit: int, window: "1h"|"24h", global_remaining: int|null, turnstile_site_key: str|null, signin_available: bool}`.
  - helper `_client_ip(request: Request) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ask_access.py`:

```python
from fastapi.testclient import TestClient

from atlas import agent, api, store, summary


@pytest.fixture
def asking(
    evidence_store: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> TestClient:
    """The API with limits on, Turnstile faked (token "good" passes) and the model faked."""
    for module in (api, store, summary):
        monkeypatch.setattr(module, "STORE", evidence_store)
    monkeypatch.setenv("ATLAS_SECRET", "test-secret")
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret-key")
    monkeypatch.setenv("ATLAS_USAGE_DB", str(tmp_path / "usage.sqlite"))
    for name in ("ATLAS_ASK_LIMITS", "ORCID_CLIENT_ID", "ORCID_CLIENT_SECRET", "ATLAS_PUBLIC_URL"):
        monkeypatch.delenv(name, raising=False)
    efforts: list[str] = []

    def fake_ask(question: str, *, model: str = agent.MODEL, effort: str = "high"):
        efforts.append(effort)
        return agent.Answer(text="dprE1 is Rv3790.")

    monkeypatch.setattr(agent, "ask", fake_ask)
    monkeypatch.setattr(access, "verify_turnstile", lambda token, ip: token == "good")
    client = TestClient(api.app, base_url="https://testserver")
    client.efforts = efforts  # type: ignore[attr-defined]
    return client


def _ask(client: TestClient, token: str | None = "good", **body):
    headers = {"X-Turnstile-Token": token} if token else {}
    return client.post("/ask", json={"question": "What is dprE1?", **body}, headers=headers)


def test_anonymous_gets_five_then_a_429_that_says_when(asking: TestClient) -> None:
    for _ in range(5):
        assert _ask(asking).status_code == 200
    refused = _ask(asking)
    assert refused.status_code == 429
    assert refused.json()["detail"]["limit"] == "ip"
    assert int(refused.headers["Retry-After"]) == refused.json()["detail"]["retry_after"] > 0


def test_a_failed_captcha_is_403_and_costs_nothing(asking: TestClient) -> None:
    assert _ask(asking, token="bad").status_code == 403
    assert _ask(asking, token=None).status_code == 403
    for _ in range(5):
        assert _ask(asking).status_code == 200


def test_missing_turnstile_config_refuses_rather_than_running_open(
    asking: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TURNSTILE_SECRET_KEY")
    assert _ask(asking).status_code == 503


def test_missing_secret_refuses_every_ask(
    asking: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ATLAS_SECRET")
    assert _ask(asking).status_code == 503


def test_effort_is_fixed_at_high_whatever_the_body_says(asking: TestClient) -> None:
    assert _ask(asking, effort="xhigh").status_code == 200
    assert asking.efforts == ["high"]  # type: ignore[attr-defined]


def test_the_usage_file_holds_no_ip_in_clear(asking: TestClient, tmp_path: Path) -> None:
    _ask(asking)
    with sqlite3.connect(tmp_path / "usage.sqlite") as connection:
        keys = [k for (k,) in connection.execute("SELECT key FROM asks")]
    assert keys and all("testclient" not in k for k in keys)


def test_limits_off_admits_without_touching_the_usage_file(
    asking: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ATLAS_ASK_LIMITS", "off")
    monkeypatch.delenv("ATLAS_SECRET")
    for _ in range(7):
        assert _ask(asking, token=None).status_code == 200
    assert not (tmp_path / "usage.sqlite").exists()


def test_signed_in_gets_twenty_a_day_and_no_captcha(asking: TestClient) -> None:
    asking.cookies.set(access.SESSION_COOKIE, access.make_session(IRIS))
    for _ in range(20):
        assert _ask(asking, token=None).status_code == 200
    refused = _ask(asking, token=None)
    assert refused.status_code == 429
    assert refused.json()["detail"]["limit"] == "orcid"


def test_a_tampered_session_is_anonymous(asking: TestClient) -> None:
    forged = access.make_session(IRIS).replace(IRIS, "0000-0001-5109-3700")
    asking.cookies.set(access.SESSION_COOKIE, forged)
    assert _ask(asking, token=None).status_code == 403


def test_the_global_ceiling_refuses_a_signed_in_user_too(
    asking: TestClient, tmp_path: Path
) -> None:
    _ask(asking)  # creates the usage file
    now = __import__("time").time()
    with sqlite3.connect(tmp_path / "usage.sqlite") as connection:
        connection.executemany(
            "INSERT INTO asks VALUES (?, ?)",
            [(f"orcid:{i}", now - 60) for i in range(access.GLOBAL_LIMIT)],
        )
    asking.cookies.set(access.SESSION_COOKIE, access.make_session(IRIS))
    refused = _ask(asking, token=None)
    assert refused.status_code == 429
    assert refused.json()["detail"]["limit"] == "global"


def test_me_reports_the_allowance_without_spending_it(asking: TestClient) -> None:
    me = asking.get("/auth/me").json()
    assert me == {
        "orcid": None,
        "limits": True,
        "remaining": 5,
        "limit": 5,
        "window": "1h",
        "global_remaining": access.GLOBAL_LIMIT,
        "turnstile_site_key": "site-key",
        "signin_available": False,
    }
    _ask(asking)
    assert asking.get("/auth/me").json()["remaining"] == 4


def test_me_signed_in(asking: TestClient) -> None:
    asking.cookies.set(access.SESSION_COOKIE, access.make_session(IRIS))
    me = asking.get("/auth/me").json()
    assert (me["orcid"], me["limit"], me["window"], me["remaining"]) == (IRIS, 20, "24h", 20)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_ask_access.py -v -k "anonymous or captcha or missing or effort or usage_file or limits_off or signed_in or tampered_session_is or global_ceiling_refuses_a or me_"`
Expected: FAIL — 6th anonymous ask returns 200, `/auth/me` is 404.

- [ ] **Step 3: Implement**

In `atlas/api.py`, change the imports:

```python
import atexit
import math
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

import duckdb
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import ask_access as access
from .clinical import TARGET_LINK_SQL, TARGET_LINKS
```

Replace the `Question` model:

```python
class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    # No `effort`: it is fixed at "high" on the server, so a caller cannot buy a
    # dearer answer. An `effort` in the body is ignored, not refused.
```

Add, just above `@app.post("/ask", ...)`:

```python
class AuthMe(BaseModel):
    orcid: str | None
    limits: bool
    remaining: int | None
    limit: int
    window: Literal["1h", "24h"]
    global_remaining: int | None
    turnstile_site_key: str | None
    signin_available: bool


def _client_ip(request: Request) -> str:
    # The visitor only if uvicorn trusts the proxy in front (FORWARDED_ALLOW_IPS);
    # otherwise every visitor is the proxy and shares one allowance.
    return request.client.host if request.client else ""


def _allowance(request: Request) -> tuple[str, str | None, tuple[int, float]]:
    """(usage key, signed-in iD or None, (limit, window)) for this caller."""
    orcid = access.read_session(request.cookies.get(access.SESSION_COOKIE))
    if orcid:
        return access.orcid_key(orcid), orcid, access.SIGNED_IN
    return access.ip_key(_client_ip(request)), None, access.ANONYMOUS


def _admit(request: Request) -> None:
    """Spend one of this caller's asks, or refuse with the reason. Fails closed."""
    if not access.limits_on():
        return
    if not access.secret_configured():
        raise HTTPException(503, "Questions are switched off: this site has no ATLAS_SECRET.")
    key, orcid, (limit, window) = _allowance(request)
    if orcid is None:
        if not access.turnstile_configured():
            raise HTTPException(
                503, "Anonymous questions are switched off: this site has no Turnstile keys."
            )
        token = request.headers.get("X-Turnstile-Token")
        if not access.verify_turnstile(token, _client_ip(request)):
            raise HTTPException(403, "The human check did not pass. Try again.")
    verdict = access.admit(key, limit, window)
    if not verdict.admitted:
        wait = max(1, math.ceil(verdict.retry_after))
        raise HTTPException(
            429,
            detail={"limit": verdict.limit, "retry_after": wait},
            headers={"Retry-After": str(wait)},
        )


@app.get("/auth/me", response_model=AuthMe)
def auth_me(request: Request) -> AuthMe:
    """What this caller may still ask, and what the page needs to let them."""
    limits = access.limits_on()
    orcid = access.read_session(request.cookies.get(access.SESSION_COOKIE))
    limit, window = access.SIGNED_IN if orcid else access.ANONYMOUS
    remaining = global_remaining = None
    if limits and access.secret_configured():
        key, _, _ = _allowance(request)
        peek = access.admit(key, limit, window, record=False)
        remaining, global_remaining = peek.remaining, peek.global_remaining
    return AuthMe(
        orcid=orcid,
        limits=limits,
        remaining=remaining,
        limit=limit,
        window="24h" if orcid else "1h",
        global_remaining=global_remaining,
        turnstile_site_key=(access.turnstile_site_key() if limits else None),
        signin_available=access.signin_available(),
    )
```

Replace the `/ask` route:

```python
@app.post("/ask", response_model=AgentAnswer)
def ask(body: Question, request: Request) -> AgentAnswer:
    from . import agent

    _admit(request)
    try:
        result = agent.ask(body.question, effort="high")
    except RuntimeError as error:
        # No credentials configured: a 503 rather than a 500, because the rest of
        # the API is fine and this one route simply is not available.
        raise HTTPException(503, str(error)) from error
    return AgentAnswer(
        answer=result.text,
        queries=[
            {"tool": c.name, "sql": c.input.get("sql"), "rows": c.rows, "error": c.error}
            for c in result.calls
        ],
        sources=result.sources,
        references=references(result.text),
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ask_access.py -v && uv run pytest -q && make lint`
Expected: all PASS. If an existing test posted `effort` to `/ask` and asserted on it, it now passes the body through unchanged (the field is ignored); update only an assertion that expected the old `Literal` validation error, and say so in the commit.

- [ ] **Step 5: Commit**

```bash
git add atlas/api.py tests/test_ask_access.py
git commit -m "feat: /ask spends an allowance; effort fixed at high

Anonymous: Turnstile, then 5 an hour per IP. Signed in: 20 a day per
ORCID iD. 500 a day across everyone. Missing configuration refuses
rather than running open; /auth/me reports what is left.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: ORCID sign-in routes

**Files:**
- Modify: `atlas/api.py` (after `auth_me`)
- Test: `tests/test_ask_access.py`

**Interfaces:**
- Consumes: `access.signin_available`, `make_state`, `read_state`, `authorize_url`, `exchange_code`, `make_session`, `public_url`, `safe_next`, cookie names and lifetimes.
- Produces: `GET /auth/orcid/login?next=`, `GET /auth/orcid/callback?code=&state=`, `POST /auth/logout`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ask_access.py`:

```python
@pytest.fixture
def signing_in(asking: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ORCID_CLIENT_ID", "APP-TEST")
    monkeypatch.setenv("ORCID_CLIENT_SECRET", "orcid-secret")
    monkeypatch.setenv("ATLAS_PUBLIC_URL", "https://atlas.example.org")
    monkeypatch.setattr(access, "exchange_code", lambda code: IRIS if code == "ok" else None)
    return asking


def _login(client: TestClient, next_path: str) -> str:
    """Start a sign-in and return the state ORCID would send back."""
    started = client.get("/auth/orcid/login", params={"next": next_path}, follow_redirects=False)
    assert started.status_code == 302
    assert started.headers["location"].startswith("https://orcid.org/oauth/authorize?")
    return started.headers["location"].split("state=")[1].split("&")[0]


def test_sign_in_round_trip_returns_to_the_page_it_left(signing_in: TestClient) -> None:
    state = _login(signing_in, "/targets/Rv1484?filter=x")
    back = signing_in.get(
        "/auth/orcid/callback", params={"code": "ok", "state": state}, follow_redirects=False
    )
    assert back.status_code == 302
    assert back.headers["location"] == "https://atlas.example.org/targets/Rv1484?filter=x"
    assert signing_in.get("/auth/me").json()["orcid"] == IRIS


def test_a_crafted_next_comes_back_home(signing_in: TestClient) -> None:
    state = _login(signing_in, "//evil.example/steal")
    back = signing_in.get(
        "/auth/orcid/callback", params={"code": "ok", "state": state}, follow_redirects=False
    )
    assert back.headers["location"] == "https://atlas.example.org/"


def test_a_state_that_does_not_match_its_cookie_signs_nobody_in(signing_in: TestClient) -> None:
    _login(signing_in, "/map")
    back = signing_in.get(
        "/auth/orcid/callback", params={"code": "ok", "state": "forged"}, follow_redirects=False
    )
    assert back.headers["location"] == "https://atlas.example.org/?signin=failed"
    assert signing_in.get("/auth/me").json()["orcid"] is None


def test_a_failed_exchange_says_so_and_signs_nobody_in(signing_in: TestClient) -> None:
    state = _login(signing_in, "/genome?x=1")
    back = signing_in.get(
        "/auth/orcid/callback", params={"code": "bad", "state": state}, follow_redirects=False
    )
    assert back.headers["location"] == "https://atlas.example.org/genome?x=1&signin=failed"
    assert signing_in.get("/auth/me").json()["orcid"] is None


def test_logout_forgets_the_session(signing_in: TestClient) -> None:
    signing_in.cookies.set(access.SESSION_COOKIE, access.make_session(IRIS))
    assert signing_in.post("/auth/logout").status_code == 204
    assert signing_in.get("/auth/me").json()["orcid"] is None


def test_sign_in_is_404_when_not_configured(asking: TestClient) -> None:
    assert asking.get("/auth/orcid/login", follow_redirects=False).status_code == 404
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_ask_access.py -v -k "sign_in or crafted or state_that or failed_exchange or logout"`
Expected: FAIL — 404 on `/auth/orcid/login`.

- [ ] **Step 3: Implement**

In `atlas/api.py`, add to imports: `import secrets` and `from fastapi.responses import PlainTextResponse, RedirectResponse, Response`. Then after `auth_me`:

```python
def _set_cookie(response: Response, name: str, value: str, max_age: float) -> None:
    response.set_cookie(
        name, value, max_age=int(max_age), httponly=True, secure=True, samesite="lax", path="/"
    )


@app.get("/auth/orcid/login")
def orcid_login(next: str = "/") -> RedirectResponse:
    if not access.signin_available():
        raise HTTPException(404, "Sign-in is not configured on this site.")
    nonce = secrets.token_urlsafe(16)
    response = RedirectResponse(access.authorize_url(nonce), status_code=302)
    _set_cookie(
        response, access.STATE_COOKIE, access.make_state(nonce, next), access.STATE_SECONDS
    )
    return response


@app.get("/auth/orcid/callback")
def orcid_callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    saved = access.read_state(request.cookies.get(access.STATE_COOKIE))
    target = saved[1] if saved else "/"
    orcid = None
    if saved and secrets.compare_digest(saved[0], state) and code:
        orcid = access.exchange_code(code)
    if orcid is None:
        target += ("&" if "?" in target else "?") + "signin=failed"
    response = RedirectResponse(f"{access.public_url()}{target}", status_code=302)
    response.delete_cookie(access.STATE_COOKIE, path="/")
    if orcid:
        _set_cookie(
            response, access.SESSION_COOKIE, access.make_session(orcid), access.SESSION_SECONDS
        )
    return response


@app.post("/auth/logout", status_code=204)
def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(access.SESSION_COOKIE, path="/")
    return response
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ask_access.py -v && uv run pytest -q && make lint`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add atlas/api.py tests/test_ask_access.py
git commit -m "feat: sign in with ORCID for 20 questions a day

/authenticate scope only; the iD is kept and the token and name are
discarded. CSRF state in a signed 10-minute cookie, and sign-in returns
only to a path on this site.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The Ask bar — CAPTCHA, sign-in, allowance, refusals

**Files:**
- Create: `web/src/askAccess.ts`, `web/tests/ask-access.test.mjs`
- Modify: `web/src/api.ts` (types near `Meta` at ~735; `api` object at ~979), `web/src/Ask.tsx`, `web/src/styles.css`

**Interfaces:**
- Consumes: `GET /auth/me` (`AuthMe` shape from Task 4), 429 `detail` shape, `/auth/orcid/login?next=`, `POST /auth/logout`.
- Produces:
  - `web/src/api.ts`: `export interface Me {...}` mirroring `AuthMe`; `api.me(): Promise<Me>`.
  - `web/src/askAccess.ts`: `allowanceLabel(me: Me): string | null`, `refusalMessage(detail: unknown, now: Date): string`, `captchaUnavailableMessage(signinAvailable: boolean): string`.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/ask-access.test.mjs`:

```js
import assert from 'node:assert/strict';
import test from 'node:test';
import { allowanceLabel, refusalMessage, captchaUnavailableMessage } from '../src/askAccess.ts';

const anon = { orcid: null, limits: true, remaining: 3, limit: 5, window: '1h', global_remaining: 400, turnstile_site_key: 'k', signin_available: true };
const at = new Date('2026-10-12T10:00:00');

test('the allowance reads as a count of what is left', () => {
  assert.equal(allowanceLabel(anon), '3 of 5 left this hour');
  assert.equal(allowanceLabel({ ...anon, orcid: '0000-0002-1825-0097', limit: 20, remaining: 20, window: '24h' }), '20 of 20 left today');
  assert.equal(allowanceLabel({ ...anon, limits: false }), null);
  assert.equal(allowanceLabel({ ...anon, remaining: null }), null);
});

test('a refusal is a sentence that names whose limit it is, never [object Object]', () => {
  const ip = refusalMessage({ limit: 'ip', retry_after: 600 }, at);
  assert.match(ip, /5 questions an hour/);
  assert.match(ip, /ORCID/);
  assert.match(refusalMessage({ limit: 'orcid', retry_after: 60 }, at), /20 questions for today/);
  const global = refusalMessage({ limit: 'global', retry_after: 60 }, at);
  assert.match(global, /across everyone/);
  assert.doesNotMatch(global, /your/i);
  for (const odd of [undefined, null, 'Service unavailable', { nonsense: true }]) {
    const message = refusalMessage(odd, at);
    assert.equal(typeof message, 'string');
    assert.doesNotMatch(message, /object Object/);
  }
});

test('a blocked CAPTCHA explains itself and offers ORCID when there is one', () => {
  assert.match(captchaUnavailableMessage(true), /ORCID/);
  assert.doesNotMatch(captchaUnavailableMessage(false), /ORCID/);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && npm test`
Expected: FAIL — cannot find module `../src/askAccess.ts`.

- [ ] **Step 3: Implement the helpers and types**

In `web/src/api.ts`, after the `Meta` interface:

```ts
/** What this visitor may still ask (`/auth/me`). `remaining` is null when limits are off. */
export interface Me {
  orcid: string | null;
  limits: boolean;
  remaining: number | null;
  limit: number;
  window: "1h" | "24h";
  global_remaining: number | null;
  turnstile_site_key: string | null;
  signin_available: boolean;
}
```

and in the `api` object, after `meta`:

```ts
  me: () => get<Me>("/auth/me"),
```

Create `web/src/askAccess.ts`:

```ts
/**
 * The words around /ask's allowance. Pure, so the sentences are tested rather
 * than eyeballed; Ask.tsx only places them.
 */
import type { Me } from "./api";

export function allowanceLabel(me: Me): string | null {
  if (!me.limits || me.remaining === null) return null;
  return `${me.remaining} of ${me.limit} left ${me.window === "1h" ? "this hour" : "today"}`;
}

const clock = (at: Date) => at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** A 429's `detail` as a sentence. Anything unexpected still reads as text. */
export function refusalMessage(detail: unknown, now: Date): string {
  if (typeof detail === "string") return detail;
  const d = (detail ?? {}) as { limit?: unknown; retry_after?: unknown };
  const seconds = typeof d.retry_after === "number" ? d.retry_after : 0;
  const when = clock(new Date(now.getTime() + seconds * 1000));
  switch (d.limit) {
    case "global":
      return `The atlas has answered its 500 questions for today, across everyone. The next is admitted at ${when}.`;
    case "orcid":
      return `You have used your 20 questions for today. The next is admitted at ${when}.`;
    case "ip":
      return `You have used the 5 questions an hour allowed without signing in. The next is admitted at ${when}, or sign in with ORCID for 20 a day.`;
    default:
      return "The question was not admitted. Try again shortly.";
  }
}

export function captchaUnavailableMessage(signinAvailable: boolean): string {
  const base =
    "The human check could not load, so questions cannot be asked anonymously from this browser. A privacy extension blocking challenges.cloudflare.com is the usual cause.";
  return signinAvailable ? `${base} Signing in with ORCID skips the check.` : base;
}
```

- [ ] **Step 4: Run the helper tests**

Run: `cd web && npm test`
Expected: all PASS (existing table-formatting tests too).

- [ ] **Step 5: Wire the Ask bar**

In `web/src/Ask.tsx`:

Change imports:

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link, useLocation } from "react-router";
import { InterfaceIcon } from "./InterfaceIcon";
import { api, type Hit, type Me, type SearchResults } from "./api";
import { allowanceLabel, captchaUnavailableMessage, refusalMessage } from "./askAccess";
```

Add above `export function Ask`:

```ts
declare global {
  interface Window {
    turnstile?: {
      render(element: HTMLElement, options: Record<string, unknown>): string;
      reset(widget?: string): void;
      remove(widget?: string): void;
    };
  }
}

// Loaded on the first focus of the Ask input, never in index.html: nobody who
// does not ask sends anything to Cloudflare. A failed load can be retried.
let turnstileScript: Promise<void> | null = null;
function loadTurnstile(): Promise<void> {
  turnstileScript ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      turnstileScript = null;
      reject(new Error("turnstile"));
    };
    document.head.appendChild(script);
  });
  return turnstileScript;
}
```

Inside `Ask`, after the existing `useState` hooks:

```ts
  const location = useLocation();
  const [me, setMe] = useState<Me | null>(null);
  const [captchaFailed, setCaptchaFailed] = useState(false);
  const widgetHost = useRef<HTMLDivElement | null>(null);
  const widget = useRef<string | null>(null);
  const token = useRef<string | null>(null);

  const refreshMe = useCallback(() => api.me().then(setMe).catch(() => setMe(null)), []);
  useEffect(() => { void refreshMe(); }, [refreshMe]);

  const needsCaptcha = Boolean(me?.limits && !me.orcid && me.turnstile_site_key);

  const startCaptcha = useCallback(() => {
    if (!needsCaptcha || widget.current || !widgetHost.current) return;
    loadTurnstile()
      .then(() => {
        if (!window.turnstile || !widgetHost.current || widget.current) return;
        widget.current = window.turnstile.render(widgetHost.current, {
          sitekey: me!.turnstile_site_key,
          // Shown only when Cloudflare needs the visitor to do something.
          appearance: "interaction-only",
          callback: (value: string) => { token.current = value; },
          "expired-callback": () => { token.current = null; },
          "error-callback": () => { token.current = null; },
        });
      })
      .catch(() => setCaptchaFailed(true));
  }, [needsCaptcha, me]);

  const signInHref = `/api/auth/orcid/login?next=${encodeURIComponent(location.pathname + location.search)}`;
  const signOut = async () => {
    await fetch(`${base}/auth/logout`, { method: "POST" });
    void refreshMe();
  };
```

Replace the body of `submit` from `try {` through the end of `catch`:

```ts
    try {
      if (needsCaptcha && !token.current) {
        throw new Error(captchaFailed ? captchaUnavailableMessage(Boolean(me?.signin_available)) : "One moment: the human check is still running. Ask again in a few seconds.");
      }
      const response = await fetch(`${base}/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token.current ? { "X-Turnstile-Token": token.current } : {}),
        },
        body: JSON.stringify({ question: text }),
        signal: controller.signal,
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(response.status === 429 ? refusalMessage(body.detail, new Date()) : (typeof body.detail === "string" ? body.detail : `${response.status}`));
      }
      setResult(body as Result);
      setState("idle");
    } catch (caught: unknown) {
      if (controller.signal.aborted) return;
      setError(String(caught instanceof Error ? caught.message : caught));
      setState("error");
    } finally {
      // A token is single-use: whatever happened, the next ask needs a fresh one.
      token.current = null;
      if (widget.current) window.turnstile?.reset(widget.current);
      void refreshMe();
    }
```

On the input, extend `onFocus`:

```tsx
          onFocus={() => { setFocused(true); startCaptcha(); }}
```

After the closing `</form>`, add the allowance strip:

```tsx
      <div className="askaccess">
        <div ref={widgetHost} className="askaccess-captcha" />
        {me && allowanceLabel(me) && <span className="faint">{allowanceLabel(me)}</span>}
        {me?.orcid ? (
          <>
            <a href={`https://orcid.org/${me.orcid}`} target="_blank" rel="noreferrer">{me.orcid}</a>
            <button type="button" className="linkbtn" onClick={() => void signOut()}>Sign out</button>
          </>
        ) : me?.signin_available ? (
          <a href={signInHref}>Sign in with ORCID for 20 a day</a>
        ) : null}
        {new URLSearchParams(location.search).get("signin") === "failed" && (
          <span className="caveat-inline">ORCID sign-in did not complete.</span>
        )}
      </div>
```

In `web/src/styles.css`, after the `.askbar` rules:

```css
.askaccess { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 0 20px 4px; font-size: 12px; }
.askaccess:empty { display: none; }
.askaccess-captcha:empty { display: none; }
.linkbtn { background: none; border: 0; padding: 0; color: var(--link, inherit); text-decoration: underline; cursor: pointer; font: inherit; }
.caveat-inline { color: var(--warn, inherit); }
```

(Use the variable names already defined in `styles.css` for link and warning colours; check with `grep -n -- "--" web/src/styles.css | head -40` and substitute.)

- [ ] **Step 6: Typecheck, build and look**

Run: `cd web && npm run typecheck && npm test && npm run build`
Expected: no type errors; tests PASS; build succeeds.

Then run it with Cloudflare's always-pass test keys:

```bash
ATLAS_SECRET=dev TURNSTILE_SITE_KEY=1x00000000000000000000AA \
TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA make api   # terminal 1
make web                                                              # terminal 2
```

Open `http://localhost:5173`: the strip reads "5 of 5 left this hour"; ask once → "4 of 5"; ask five more → the 6th shows the 5-an-hour sentence with a time. No ORCID link (not configured locally). Then restart the API with `ATLAS_ASK_LIMITS=off`: the strip is empty and asks work without a token.

- [ ] **Step 7: Commit**

```bash
git add web/src/askAccess.ts web/tests/ask-access.test.mjs web/src/api.ts web/src/Ask.tsx web/src/styles.css
git commit -m "feat: the Ask bar shows its allowance, runs the human check, signs in

Turnstile loads on the first focus of the input, never before. A 429
becomes a sentence naming whose limit it was; a blocked CAPTCHA says so
and offers ORCID.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: One process serves the API and the page

**Files:**
- Create: `atlas/serve.py`
- Modify: `tests/test_serve.py`, `pyproject.toml` (uvicorn floor)

**Interfaces:**
- Consumes: `atlas.api.app`, `atlas.fetch.ROOT`.
- Produces: `atlas.serve.create_app(dist: Path) -> FastAPI`; `atlas.serve.app` (uses `$ATLAS_WEB_DIST` or `ROOT / "web" / "dist"`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_serve.py`:

```python
import pytest
from fastapi.testclient import TestClient

from atlas import api, serve, store, summary


@pytest.fixture
def site(evidence_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for module in (api, store, summary):
        monkeypatch.setattr(module, "STORE", evidence_store)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><div id="root"></div>')
    (dist / "assets" / "index-3f9a1c.js").write_text("console.log('atlas')")
    return TestClient(serve.create_app(dist))


def test_the_api_is_under_api(site: TestClient) -> None:
    assert site.get("/api/meta").status_code == 200


def test_a_router_path_is_the_page(site: TestClient) -> None:
    for path in ("/", "/genome/Rv3790", "/clinical/drug/CHEMBL64", "/about/privacy"):
        page = site.get(path)
        assert page.status_code == 200, path
        assert 'id="root"' in page.text
        assert page.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_cached_for_a_year(site: TestClient) -> None:
    asset = site.get("/assets/index-3f9a1c.js")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_a_missing_asset_is_404_not_the_page(site: TestClient) -> None:
    assert site.get("/assets/gone-000000.js").status_code == 404


def test_an_unknown_api_route_is_404_not_the_page(site: TestClient) -> None:
    assert site.get("/api/no-such-route").status_code == 404
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_serve.py -v`
Expected: FAIL — `ImportError: cannot import name 'serve'`.

- [ ] **Step 3: Implement**

Create `atlas/serve.py`:

```python
"""The public site as one process: the API at /api, the built page everywhere else.

Development does not use this (`make api` + `make web`, with Vite's proxy). The
image does. The page calls the relative `/api`, so nothing here or in the bundle
names a host: the same image runs on anyone's server.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from .api import app as api
from .fetch import ROOT

IMMUTABLE = "public, max-age=31536000, immutable"


class Page(StaticFiles):
    """web/dist, where a path that is not a file is the app: React Router owns it."""

    async def get_response(self, path: str, scope: Scope):
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            # A missing hashed asset is a real 404; only an app path falls back.
            if error.status_code != 404 or path.startswith("assets/"):
                raise
            response = await super().get_response("index.html", scope)
            path = "index.html"
        # Vite hashes every file under assets/, so they never change in place.
        response.headers["Cache-Control"] = (
            IMMUTABLE if path.startswith("assets/") else "no-cache"
        )
        return response


def create_app(dist: Path) -> FastAPI:
    site = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    site.add_middleware(GZipMiddleware, minimum_size=1024)
    site.mount("/api", api)
    site.mount("/", Page(directory=dist, html=True, check_dir=False), name="page")
    return site


app = create_app(Path(os.environ.get("ATLAS_WEB_DIST") or ROOT / "web" / "dist"))
```

In `pyproject.toml`, raise the uvicorn floor so `FORWARDED_ALLOW_IPS` accepts CIDR ranges:

```toml
    "uvicorn[standard]>=0.34",
```

Then confirm the installed uvicorn understands a CIDR (a one-off check, not a test — it touches uvicorn internals):

Run: `uv run python -c "from uvicorn.middleware.proxy_headers import _TrustedHosts as T; t = T('172.16.50.0/24'); print('172.16.50.7' in t, '10.0.0.1' in t)"`
Expected: `True False`. If `_TrustedHosts` does not exist in the installed version, read `uvicorn/middleware/proxy_headers.py` and confirm CIDR support by its source before continuing; report what you found.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_serve.py -v && uv run pytest -q && make lint`
Expected: all PASS. If `/api/no-such-route` returns the page, the `/api` mount is not matching first — mounts are matched in order, so `site.mount("/api", api)` must stay before the `/` mount.

- [ ] **Step 5: Commit**

```bash
git add atlas/serve.py tests/test_serve.py pyproject.toml
git commit -m "feat: one process serves the API at /api and the page at /

Router paths fall back to index.html, hashed assets are cached for a year,
a missing asset is still a 404. Nothing names a host.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The image, a generic way to run it, and CI

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `docker-compose.prod.yml`, `.env.example`, `.github/workflows/publish-image.yml`

**Interfaces:**
- Consumes: `atlas.serve:app` (Task 7), `ATLAS_STORE`/`ATLAS_USAGE_DB`/`ATLAS_WEB_DIST` (Tasks 1, 2, 7), `/api/auth/me` (Task 4).
- Produces: image `ghcr.io/sidxz/mtb-atlas:{latest,sha-<sha>,X.Y.Z,X.Y,X}` listening on 8099, store expected at `/store`.

- [ ] **Step 1: Write the Dockerfile and .dockerignore**

`Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
# The atlas as one image: the API and the built page, and no data.
# The store is mounted read-only at /store; see docker-compose.prod.yml.

FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY atlas ./atlas
RUN uv pip install --system --no-cache .
COPY --from=web /web/dist ./web/dist
RUN useradd --system --uid 1001 atlas && mkdir -p /var/lib/atlas && chown atlas /var/lib/atlas
USER atlas
ENV ATLAS_STORE=/store \
    ATLAS_WEB_DIST=/app/web/dist \
    ATLAS_USAGE_DB=/var/lib/atlas/ask_usage.sqlite \
    PYTHONUNBUFFERED=1
EXPOSE 8099
# /api/meta reads the store, so a missing or broken mount reads as unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/api/meta', timeout=4)"
# One process: the API's DuckDB instance and hit-profile cache are per process by design.
CMD ["uvicorn", "atlas.serve:app", "--host", "0.0.0.0", "--port", "8099"]
```

(`LICENSE` is created in Task 10; if Task 8 runs first, create it now from Task 10, Step 1.)

`.dockerignore`:

```
.git
.github
.venv
.claude
.superpowers
**/__pycache__
**/.pytest_cache
.ruff_cache
data
poc
tests
docs
web/node_modules
web/dist
.env
.env.*
```

- [ ] **Step 2: Build it and smoke-test it locally**

```bash
docker build --platform linux/amd64 -t mtb-atlas:local .
docker run -d --rm --name atlas-smoke -p 8099:8099 -v "$PWD/data/store:/store:ro" mtb-atlas:local
sleep 8
curl -fsS localhost:8099/ | grep -q 'id="root"' && echo page-ok
curl -fsS localhost:8099/genome/Rv3790 | grep -q 'id="root"' && echo route-ok
curl -fsS localhost:8099/api/meta | head -c 200; echo
curl -fsS localhost:8099/api/auth/me; echo
docker inspect --format '{{.State.Health.Status}}' atlas-smoke   # after ~40 s: healthy
docker stop atlas-smoke
```

Expected: `page-ok`, `route-ok`, JSON from `/api/meta` with sources, `/api/auth/me` answering with `"limits":true` and `"remaining":null` (no secret set), health `healthy`.

- [ ] **Step 3: Write the generic compose file and env example**

`docker-compose.prod.yml`:

```yaml
# The atlas as one container. Nothing here names a host.
#
#   make build                                  # the store, into ./data/store
#   cp .env.example .env                        # optional: only /ask needs anything
#   docker compose -f docker-compose.prod.yml up -d
#
# Then http://localhost:8099. Behind a reverse proxy, set FORWARDED_ALLOW_IPS to
# the proxy's address or subnet, or every visitor shares one /ask allowance.
services:
  atlas:
    image: ghcr.io/sidxz/mtb-atlas:${VERSION:-latest}
    env_file:
      - path: .env
        required: false
    ports:
      - "8099:8099"
    volumes:
      - ./data/store:/store:ro
    restart: unless-stopped
```

`.env.example`:

```sh
# Everything is optional except for /ask. Without the /ask settings the atlas
# serves every view and /ask answers 503.

# --- /ask ------------------------------------------------------------------
ANTHROPIC_API_KEY=
# Any long random string: signs the session cookie and hashes IPs for counting.
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
ATLAS_SECRET=
# Cloudflare Turnstile (free): https://dash.cloudflare.com/?to=/:account/turnstile
# Test keys that always pass: 1x00000000000000000000AA / 1x0000000000000000000000000000000AA
TURNSTILE_SITE_KEY=
TURNSTILE_SECRET_KEY=
# ORCID sign-in (optional; raises the allowance from 5/hour to 20/day).
# Register a public API client at https://orcid.org/developer-tools with the
# redirect URI <ATLAS_PUBLIC_URL>/api/auth/orcid/callback
ORCID_CLIENT_ID=
ORCID_CLIENT_SECRET=
# ORCID_BASE=https://sandbox.orcid.org
# The address visitors use, with no trailing slash, e.g. https://atlas.example.org
ATLAS_PUBLIC_URL=
# Set to off to disable every /ask limit (local development only).
# ATLAS_ASK_LIMITS=off

# --- who runs this instance (shown on the privacy page) ---------------------
ATLAS_OPERATOR=
ATLAS_CONTACT=
# Extra footer links an institution requires, as JSON:
# ATLAS_FOOTER_LINKS=[{"label": "Site policies", "url": "https://example.org/policies"}]

# --- behind a reverse proxy --------------------------------------------------
# The proxy's address or subnet, so the visitor's IP is the one counted.
# FORWARDED_ALLOW_IPS=172.16.50.0/24
```

Check the local `.env` is still ignored and `.env.example` is not: `git check-ignore -v .env .env.example` → only `.env` listed (the existing `!.env.example` rule).

- [ ] **Step 4: Write the CI workflow**

`.github/workflows/publish-image.yml`:

```yaml
name: Publish image

# main -> :latest and :sha-<sha>; a vX.Y.Z tag -> :X.Y.Z, :X.Y, :X and a GitHub Release.
on:
  push:
    branches: [main]
    tags: ['v*.*.*']

jobs:
  image:
    runs-on: ubuntu-latest
    permissions:
      contents: write   # the release on a tag
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
      - run: uv pip install --system -e '.[dev]'
      - run: ruff check . && ruff format --check .
      - run: pytest -q
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci && npm run typecheck && npm test
        working-directory: web
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ghcr.io/sidxz/mtb-atlas
          flavor: latest=false
          tags: |
            type=raw,value=latest,enable={{is_default_branch}}
            type=sha,prefix=sha-
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=semver,pattern={{major}}
      - name: Build for the smoke test
        uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64
          load: true
          tags: mtb-atlas:smoke
          cache-from: type=gha
          cache-to: type=gha,mode=max
      - name: Smoke test, with no store
        run: |
          mkdir -p empty-store
          docker run -d --name smoke -p 8099:8099 -v "$PWD/empty-store:/store:ro" mtb-atlas:smoke
          for i in $(seq 1 30); do curl -fsS localhost:8099/api/auth/me && break; sleep 1; done
          curl -fsS localhost:8099/ | grep -q 'id="root"'
          curl -fsS localhost:8099/genome/Rv3790 | grep -q 'id="root"'
          docker logs smoke
          docker rm -f smoke
      - name: Push
        uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
      - if: github.ref_type == 'tag'
        uses: softprops/action-gh-release@v2
        with:
          generate_release_notes: true
```

Validate syntax locally: `uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/publish-image.yml'))" 2>/dev/null || python3 -c "import yaml; yaml.safe_load(open('.github/workflows/publish-image.yml'))"` — if PyYAML is absent, skip; GitHub reports syntax errors on push.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.prod.yml .env.example .github/workflows/publish-image.yml
git commit -m "feat: one universal image, published by CI

Code and the built page only; the store is mounted read-only and every
site-specific value is an environment variable. CI tests, smoke-tests the
image with no store, then pushes to ghcr.io/sidxz/mtb-atlas.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Not done by this task (Sid):** the first push to GitHub creates the GHCR package as **private**. Set it public once, at github.com/users/sidxz/packages/container/mtb-atlas/settings, or ned cannot pull it.

---

### Task 9: What the site tells its visitors

**Files:**
- Modify: `atlas/api.py` (`Meta` at ~231, `meta()` at ~482)
- Create: `web/src/About.tsx`
- Modify: `web/src/api.ts` (`Meta`), `web/src/App.tsx` (`View`, `VIEWS`, render), `web/src/styles.css`
- Test: `tests/test_ask_access.py` (site block), `web/tests/ask-access.test.mjs` (footer link filtering)

**Interfaces:**
- Produces:
  - `Meta.site: Site` = `{operator: str|null, contact: str|null, footer_links: [{label: str, url: str}]}`; `footer_links` keeps only well-formed `http(s)` entries from `ATLAS_FOOTER_LINKS`.
  - `web/src/About.tsx`: `export function AboutPage({ page, meta }: { page: string | null; meta: Meta | null })`, `export function SiteFooter({ meta }: { meta: Meta | null })`, `export function SiteNotice()`.
  - Paths `/about/sources`, `/about/privacy`, `/about/terms` (`about` added to `VIEWS`).

- [ ] **Step 1: Write the failing API test**

Append to `tests/test_ask_access.py`:

```python
def test_meta_says_who_runs_the_site_and_keeps_only_real_links(
    asking: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_OPERATOR", "Example Lab")
    monkeypatch.setenv("ATLAS_CONTACT", "atlas@example.org")
    monkeypatch.setenv(
        "ATLAS_FOOTER_LINKS",
        '[{"label": "Site policies", "url": "https://example.org/p"},'
        ' {"label": "Bad", "url": "javascript:alert(1)"}, {"url": "https://no-label"}]',
    )
    site = asking.get("/meta").json()["site"]
    assert site == {
        "operator": "Example Lab",
        "contact": "atlas@example.org",
        "footer_links": [{"label": "Site policies", "url": "https://example.org/p"}],
    }


def test_malformed_footer_links_are_none_not_an_error(
    asking: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_FOOTER_LINKS", "not json")
    assert asking.get("/meta").json()["site"]["footer_links"] == []
```

Run: `uv run pytest tests/test_ask_access.py -v -k "meta_says or malformed"`
Expected: FAIL — `KeyError: 'site'`.

- [ ] **Step 2: Implement `site` on `/meta`**

In `atlas/api.py`, add `import json` and `import os` to the imports. Before `class Meta`:

```python
class FooterLink(BaseModel):
    label: str
    url: str


class Site(BaseModel):
    """Who runs this instance: set per deployment, so the image names nobody."""

    operator: str | None
    contact: str | None
    footer_links: list[FooterLink]


def _site() -> Site:
    try:
        raw = json.loads(os.environ.get("ATLAS_FOOTER_LINKS") or "[]")
    except ValueError:
        raw = []
    links = [
        FooterLink(label=item["label"], url=item["url"])
        for item in (raw if isinstance(raw, list) else [])
        if isinstance(item, dict)
        and isinstance(item.get("label"), str)
        and isinstance(item.get("url"), str)
        and item["url"].startswith(("https://", "http://"))
    ]
    return Site(
        operator=os.environ.get("ATLAS_OPERATOR") or None,
        contact=os.environ.get("ATLAS_CONTACT") or None,
        footer_links=links,
    )
```

Add `site: Site` to `Meta`, and pass `site=_site()` where `meta()` constructs `Meta(...)` (read the end of `meta()` to find the constructor call).

Run: `uv run pytest -q && make lint` → all PASS.

In `web/src/api.ts`, extend `Meta`:

```ts
export interface Meta {
  counts: Record<string, number>;
  sources: { name: string; version: string; licence: string; retrieved: string }[];
  caveats: string[];
  site: { operator: string | null; contact: string | null; footer_links: { label: string; url: string }[] };
}
```

- [ ] **Step 3: Write the pages, footer and notice**

Create `web/src/About.tsx`:

```tsx
/**
 * What a public site owes its visitors: whose data this is, what is stored and
 * sent where, and what the atlas does not promise. Written so any operator can
 * run it unchanged; who runs this instance comes from /meta.
 */
import { useState } from "react";
import { Link } from "react-router";
import type { Meta } from "./api";

const REPO = "https://github.com/sidxz/mtb-atlas";
const NOTICE_KEY = "atlas.notice.v1";

/** The citations the sources ask for, verbatim from docs/data-sources.md. */
const CITATIONS: { source: string; cite: string; doi: string }[] = [
  { source: "Mycobrowser", cite: "Kapopoulou A, Lew JM, Cole ST. The MycoBrowser portal: a comprehensive and manually annotated resource for mycobacterial genomes. Tuberculosis (Edinb) 2011;91(1):8–13.", doi: "10.1016/j.tube.2010.09.006" },
  { source: "Essentiality", cite: "DeJesus MA, Gerrick ER, Xu W, et al. Comprehensive essentiality analysis of the Mycobacterium tuberculosis genome via saturating transposon mutagenesis. mBio 2017;8(1):e02133-16.", doi: "10.1128/mBio.02133-16" },
  { source: "CRISPRi vulnerability", cite: "Bosch B, DeJesus MA, Poulton NC, et al. Genome-wide gene expression tuning reveals diverse vulnerabilities of M. tuberculosis. Cell 2021;184(17):4579–4592.e24.", doi: "10.1016/j.cell.2021.06.033" },
  { source: "Conditional fitness", cite: "Griffin JE, Gawronski JD, DeJesus MA, Ioerger TR, Akerley BJ, Sassetti CM. High-resolution phenotypic profiling defines genes essential for mycobacterial growth and cholesterol catabolism. PLoS Pathog 2011;7(9):e1002251.", doi: "10.1371/journal.ppat.1002251" },
  { source: "MtbTnDB", cite: "Jinich A, Zaveri A, DeJesus MA, et al. The Mycobacterium tuberculosis Transposon Sequencing Database (MtbTnDB): a large-scale guide to genetic conditional essentiality. Mol Microbiol 2025;124(1):91–101.", doi: "10.1111/mmi.15370" },
];

function Sources({ meta }: { meta: Meta | null }) {
  return (
    <>
      <h2>Sources &amp; licences</h2>
      <p>Every value in the atlas comes from a public source, and each keeps its own licence. The table is this instance's store: the release each source was built from and when it was retrieved.</p>
      <ul>
        <li><strong>ChEMBL</strong> and everything derived from it (bioactivity, drugs and mechanisms, drug precedent, hit profiling, the ChEMBL–PubChem bridge) is <strong>CC BY-SA 3.0</strong>, and that content is shared here under the same licence.</li>
        <li><strong>ClinicalTrials.gov</strong> data is shown as retrieved on the date below. Its display here does not imply endorsement by the U.S. National Library of Medicine.</li>
        <li><strong>PubChem</strong> screening results belong to their depositors; every campaign names its depositor, and no blanket licence is claimed.</li>
        <li><strong>Mycobrowser</strong> states no licence. The atlas uses its locus list, coordinates, names, products, functional categories and promoters, and cites it below.</li>
      </ul>
      {meta ? (
        <table className="about-table">
          <thead><tr><th>Source</th><th>Version</th><th>Licence</th><th>Retrieved</th></tr></thead>
          <tbody>
            {meta.sources.map((s) => (
              <tr key={s.name + s.version}><td>{s.name}</td><td>{s.version}</td><td>{s.licence}</td><td>{s.retrieved}</td></tr>
            ))}
          </tbody>
        </table>
      ) : <p className="faint">Loading the store's sources…</p>}
      <h3>Please cite</h3>
      <ul>
        {CITATIONS.map((c) => (
          <li key={c.doi}><span className="faint">{c.source}:</span> {c.cite} <a href={`https://doi.org/${c.doi}`} target="_blank" rel="noreferrer">doi:{c.doi}</a></li>
        ))}
        <li>The databases (UniProt, ChEMBL, PubChem, RCSB PDB, AlphaFold DB, STRING, the WHO catalogue, ClinicalTrials.gov, NCBI RefSeq) each ask to be cited as described on their own sites.</li>
      </ul>
      <p>The atlas's own code is MIT-licensed: <a href={REPO} target="_blank" rel="noreferrer">{REPO.replace("https://", "")}</a>.</p>
    </>
  );
}

function Privacy({ meta }: { meta: Meta | null }) {
  const operator = meta?.site.operator ?? "the operator of this site";
  const contact = meta?.site.contact;
  return (
    <>
      <h2>Privacy &amp; cookies</h2>
      <p>This instance is run by {operator}.{contact && <> Questions about it: <a href={`mailto:${contact}`}>{contact}</a>.</>}</p>
      <h3>Cookies and browser storage</h3>
      <table className="about-table">
        <thead><tr><th>What</th><th>Set when</th><th>Why</th></tr></thead>
        <tbody>
          <tr><td><code>atlas_session</code> cookie</td><td>you sign in with ORCID</td><td>keeps you signed in for 30 days; holds your ORCID iD and nothing else</td></tr>
          <tr><td><code>atlas_oauth_state</code> cookie</td><td>during sign-in, for 10 minutes</td><td>protects the sign-in from forgery</td></tr>
          <tr><td>browser storage: table preferences</td><td>you change a table's columns</td><td>remembers your columns</td></tr>
          <tr><td>browser storage: notice</td><td>you dismiss the notice</td><td>does not show it again</td></tr>
        </tbody>
      </table>
      <p>There are no analytics, advertising or tracking cookies. The cookies above are strictly necessary for something you asked for, so the site does not ask for consent.</p>
      <h3>What is sent where</h3>
      <ul>
        <li><strong>Questions</strong> typed into “Ask the atlas” are sent to Anthropic to be answered. The atlas does not log them.</li>
        <li><strong>Cloudflare Turnstile</strong> checks that an anonymous asker is human. It loads only when you first click into the Ask box, and receives signals from your browser.</li>
        <li><strong>ORCID</strong> handles sign-in. The atlas receives and keeps only your ORCID iD: not your name, email or record, and it can never write to your record.</li>
        <li><strong>RCSB PDB</strong>: the structure viewer loads coordinate files from models.rcsb.org directly in your browser.</li>
        <li><strong>The web server</strong> records each request (address, path, time) in the operator's server logs.</li>
      </ul>
      <h3>Counting questions</h3>
      <p>To enforce the question allowance the atlas stores, per question, the time and either your ORCID iD or a keyed hash of your IP address. The IP address itself is never stored, and every row is deleted after 24 hours.</p>
    </>
  );
}

function Terms() {
  return (
    <>
      <h2>Terms &amp; disclaimer</h2>
      <ul>
        <li>The atlas is for research use. It is not medical or clinical advice.</li>
        <li>It is provided as is, without warranty of any kind, and its sources are summarised as published; errors in a source are errors here.</li>
        <li><strong>An absent record is a statement about the public record, not about the biology.</strong> “No ligands” means no public deposit reaches this gene, not that none exists.</li>
        <li>Answers from “Ask the atlas” are generated by a language model from queries over the store. They can be wrong: check them against the rows they cite.</li>
        <li>Each source's licence applies to its data; see <Link to="/about/sources">Sources &amp; licences</Link>.</li>
      </ul>
    </>
  );
}

export function AboutPage({ page, meta }: { page: string | null; meta: Meta | null }) {
  return (
    <article className="about">
      {page === "privacy" ? <Privacy meta={meta} /> : page === "terms" ? <Terms /> : <Sources meta={meta} />}
    </article>
  );
}

export function SiteFooter({ meta }: { meta: Meta | null }) {
  return (
    <footer className="sitefooter">
      <Link to="/about/sources">Sources &amp; licences</Link>
      <Link to="/about/privacy">Privacy &amp; cookies</Link>
      <Link to="/about/terms">Terms &amp; disclaimer</Link>
      {meta?.site.footer_links.map((l) => <a key={l.url} href={l.url} target="_blank" rel="noreferrer">{l.label}</a>)}
      <span className="faint">Code MIT · <a href={REPO} target="_blank" rel="noreferrer">source</a></span>
    </footer>
  );
}

function dismissed(): boolean {
  try { return localStorage.getItem(NOTICE_KEY) === "1"; } catch { return false; }
}

/** Information, not a consent gate: the site behaves the same either way. */
export function SiteNotice() {
  const [hidden, setHidden] = useState(dismissed);
  if (hidden) return null;
  return (
    <div className="sitenotice" role="note">
      <span>This site sets no cookies unless you sign in with ORCID, and has no analytics. Asking a question sends it to Anthropic, and anonymous questions are checked by Cloudflare.</span>
      <Link to="/about/privacy">Privacy &amp; cookies</Link>
      <button type="button" className="iconbtn" onClick={() => { try { localStorage.setItem(NOTICE_KEY, "1"); } catch { /* blocked: it just comes back */ } setHidden(true); }}>OK</button>
    </div>
  );
}
```

- [ ] **Step 4: Route and place them**

In `web/src/App.tsx`:

```ts
import { AboutPage, SiteFooter, SiteNotice } from "./About";
```

```ts
type View = "genome" | "targets" | "screens" | "hits" | "clinical" | "map" | "about";
const VIEWS: View[] = ["genome", "targets", "screens", "hits", "clinical", "map", "about"];
```

Update the `parseRoute` doc comment to list `/about/privacy`. In the render, change the branch that starts `{view === "clinical" ? (` to begin with the about page:

```tsx
      {view === "about" ? (
        <div className="workspace-view"><AboutPage page={id} meta={meta} /></div>
      ) : view === "clinical" ? (
```

(`id` is the route id `parseRoute` returns — find the variable the component destructures from it near `const { view, ... } = parseRoute(...)` and use that name.) Just before the closing `</div>` of `.app` (after the `{zoomed && …}` block):

```tsx
      <SiteFooter meta={meta} />
      <SiteNotice />
```

If the view switch in the top bar renders one link per entry of `VIEWS`, exclude `about` there (it is reached from the footer, not the switch).

In `web/src/styles.css`, change the `.app` grid to add a footer row and add the new rules:

```css
.app { --rail-width: 232px; display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; height: 100%; min-height: 0; }
.app > .sitefooter { grid-row: 4; grid-column: 1; }

.sitefooter { display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: center; padding: 6px 20px; border-top: 1px solid var(--line); background: var(--surface); font-size: 12px; }
.sitenotice { position: fixed; left: 16px; right: 16px; bottom: 40px; z-index: 20; display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; max-width: 78ch; margin: 0 auto; padding: 10px 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); box-shadow: 0 4px 16px rgb(0 0 0 / 0.12); font-size: 13px; }
.about { max-width: 78ch; padding: 24px 20px 48px; overflow: auto; }
.about h2 { margin-top: 0; }
.about-table { border-collapse: collapse; margin: 12px 0; font-size: 13px; }
.about-table th, .about-table td { text-align: left; padding: 4px 12px 4px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
```

(The 78ch cap follows CLAUDE.md's "a wider panel must not mean a wider line of text".)

- [ ] **Step 5: Typecheck, build, look**

Run: `cd web && npm run typecheck && npm test && npm run build`, then `make api` + `make web` and check in the browser:
- the footer sits under every view and does not overlap the genome canvas or the detail panel;
- `/about/sources` lists this store's sources with versions; `/about/privacy`; `/about/terms`; reload on each keeps the page;
- the notice shows once, OK hides it, reload keeps it hidden; with site data cleared it returns;
- at 390 px wide the footer wraps and nothing scrolls sideways.

- [ ] **Step 6: Commit**

```bash
git add atlas/api.py tests/test_ask_access.py web/src/About.tsx web/src/api.ts web/src/App.tsx web/src/styles.css
git commit -m "feat: sources, privacy and terms pages, a footer, and a plain notice

The notice informs rather than asks: the only cookies are strictly
necessary. Who runs the instance and any institution's required links
come from the environment, through /meta.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Self-hosted font, LICENSE, docs

**Files:**
- Create: `LICENSE`
- Modify: `web/index.html`, `web/src/main.tsx`, `web/package.json` (+ lock), `README.md`, `CLAUDE.md`

- [ ] **Step 1: LICENSE**

Create `LICENSE`:

```
MIT License

Copyright (c) 2026 Siddhant Rath

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

(The licence covers the code only; the README's existing "Each data source keeps its own licence" stays.)

- [ ] **Step 2: Self-host Inter**

```bash
cd web && npm install --save-exact @fontsource/inter
```

In `web/index.html`, delete the `<link rel="preconnect" …>` and the Google Fonts `<link rel="stylesheet" …>`. At the top of `web/src/main.tsx`, before other imports of CSS:

```ts
// Self-hosted: loading Inter from Google sent every visitor's IP to Google.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/inter/400-italic.css";
```

Run: `npm run build && grep -rc "fonts.googleapis\|fonts.gstatic" dist/ | grep -v ":0" ; echo exit=$?`
Expected: no matches (`exit=1`). Open the app: text is still Inter (DevTools → Computed → font-family renders "Inter"), and numeric columns still align (`tabular-nums`).

- [ ] **Step 3: Docs**

In `README.md`, add a section before `## Licence`:

```markdown
## Running it publicly

One image, `ghcr.io/sidxz/mtb-atlas`, serves the API at `/api` and the page at
`/`. It holds no data and names no host: build the store (`make build`), mount
it read-only, and configure everything else with environment variables — see
`.env.example` and `docker-compose.prod.yml`.

- **Behind a reverse proxy, set `FORWARDED_ALLOW_IPS`** to the proxy's address or
  subnet. Without it every visitor is the proxy, and they all share one `/ask`
  allowance of 5 an hour.
- `/ask` is the only route that costs money. Anonymous askers pass Cloudflare
  Turnstile and get 5 an hour per IP; ORCID sign-in gives 20 a day; 500 a day
  across everyone. Missing keys switch `/ask` off rather than leaving it open.
- A data refresh never needs a new image: `atlas refresh`, read `atlas diff`,
  copy the store to where the container mounts it, restart.
```

In `CLAUDE.md`, add a section after "## The agent":

```markdown
## Hosting it

One image, no data, no host name. `atlas/serve.py` mounts the API at `/api` and
`web/dist` at `/`; development still runs `make api` + `make web`. Everything
site-specific is an environment variable (`.env.example`), and the store is
mounted read-only at `ATLAS_STORE`, **never baked into the image**: a public
image with the store inside would publish the whole store, and a store built in
CI is one nobody read the diff of.

`/ask` spends an allowance (`atlas/ask_access.py`): Turnstile and 5/hour per IP
anonymously, 20/day per ORCID iD signed in, 500/day across everyone; effort is
fixed at `high`. **Missing configuration fails closed** — no Turnstile keys
means no anonymous asks, not unprotected ones. An IP is only ever stored as an
HMAC, for 24 h. The usage file is container-local on purpose (SQLite on NFS
cannot trust its locks), so a redeploy resets the counts.

The site owes its visitors three pages (`/about/sources`, `/about/privacy`,
`/about/terms`) and a notice, **not a consent banner**: the only cookies are
strictly necessary. Adding analytics or any non-essential cookie changes that,
and the privacy page with it.
```

Also update CLAUDE.md's Commands block with:

```bash
docker compose -f docker-compose.prod.yml up -d   # the public image against ./data/store
```

- [ ] **Step 4: Verify and commit**

Run: `uv run pytest -q && make lint && cd web && npm run typecheck && npm test && npm run build`
Expected: all green.

```bash
git add LICENSE web/index.html web/src/main.tsx web/package.json web/package-lock.json README.md CLAUDE.md
git commit -m "chore: self-host Inter, add LICENSE, document public hosting

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: ned's stack (`snet2-infrastructure`)

**Files (in `/Users/sidx/workspace/snet2-infrastructure/docker-swarm-core/`):**
- Create: `149-atlas/atlas.yml`, `149-atlas/atlas_deploy.sh`, `149-atlas/README.md`
- Sid creates: `149-atlas/.env` → `.env.enc` (SOPS); the plan supplies the variable list.

**Interfaces:**
- Consumes: image `ghcr.io/sidxz/mtb-atlas:${VERSION}` (Task 8), port 8099, `/store` mount, `/api/meta` healthcheck, the env vars of Task 8's `.env.example`.

- [ ] **Step 1: The stack file**

`149-atlas/atlas.yml`:

```yaml
version: "3.8"

# Mtb Target Atlas (ned swarm) — public, read-only target evidence for M. tuberculosis.
#   ./atlas_deploy.sh deploy
# One public GHCR image, no data inside: the store is mounted read-only from NFS
# and replaced with `./atlas_deploy.sh store <dir>`. ${VERSION} interpolates
# because the deploy script sources .env first (stack deploy ignores .env).

services:
  atlas:
    image: ghcr.io/sidxz/mtb-atlas:${VERSION:-latest}
    env_file: [.env]
    environment:
      # Traefik binds 80/443 in host mode, so it sees the visitor; trust its
      # X-Forwarded-For only from the traefik-public subnet.
      FORWARDED_ALLOW_IPS: "172.16.50.0/24"
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.labels.snet.userns == false
          - node.role == worker
          - node.labels.snet.on-premises == true
      resources:
        limits:
          memory: 3072M
        reservations:
          memory: 768M
      update_config:
        parallelism: 1
        order: stop-first
        failure_action: rollback
      labels:
        - traefik.enable=true
        - traefik.swarm.network=traefik-public
        - traefik.constraint-label=traefik-public
        - traefik.http.routers.atlas-http.rule=Host(`atlas.snet.biobio.tamu.edu`)
        - traefik.http.routers.atlas-http.entrypoints=http
        - traefik.http.routers.atlas-http.middlewares=https-redirect
        - traefik.http.routers.atlas-https.rule=Host(`atlas.snet.biobio.tamu.edu`)
        - traefik.http.routers.atlas-https.entrypoints=https
        - traefik.http.routers.atlas-https.tls=true
        - traefik.http.services.atlas.loadbalancer.server.port=8099
    volumes:
      - /net-fs-ins/docker-vols/atlas/store:/store:ro
      - /etc/localtime:/etc/localtime:ro
    networks: [traefik-public]
    # uses the image's HEALTHCHECK (GET /api/meta, which reads the store)

networks:
  traefik-public:
    external: true
```

(`stop-first` because the usage counter is container-local and the API holds one DuckDB instance; two replicas overlapping would split the counts.)

- [ ] **Step 2: The deploy script**

`149-atlas/atlas_deploy.sh` (then `chmod +x`):

```bash
#!/usr/bin/env bash
set -euo pipefail

# Mtb Target Atlas — ned deploy
#   ./atlas_deploy.sh deploy             — decrypt .env.enc, stack deploy, wait for healthy
#   ./atlas_deploy.sh store <store dir>  — copy a locally built, diffed store to NFS
#                                          (previous kept as store.prev), restart
#   ./atlas_deploy.sh remove             — stack rm (the store on NFS is kept)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$SCRIPT_DIR"
DOCKER="docker --context ned"
STACK="atlas"
VOL="/net-fs-ins/docker-vols/atlas"
TIMEOUT_SECS="${TIMEOUT_SECS:-180}"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

do_deploy() {
    log "Decrypting .env.enc..."
    sops decrypt --input-type dotenv --output-type dotenv .env.enc > .env
    set -a; source .env; set +a
    $DOCKER run --rm -v "$VOL":/d alpine sh -c 'mkdir -p /d/store'
    log "=== Deploying $STACK (VERSION=$VERSION) ==="
    $DOCKER stack deploy -c atlas.yml "$STACK"
    local elapsed=0
    while [ $elapsed -lt "$TIMEOUT_SECS" ]; do
        if $DOCKER stack services "$STACK" --format '{{.Replicas}}' | grep -q '^1/1$'; then
            log "$STACK converged"; $DOCKER stack services "$STACK"; return 0
        fi
        sleep 5; elapsed=$((elapsed+5))
    done
    log "WARNING: $STACK did not converge in ${TIMEOUT_SECS}s"; $DOCKER stack services "$STACK"; return 1
}

do_store() {
    local src="${1:?usage: $0 store <local store dir>}"
    [ -f "$src/target_summary.parquet" ] || { log "$src does not look like an atlas store"; exit 1; }
    log "Copying $src ($(du -sh "$src" | cut -f1)) to $VOL/store; the current one becomes store.prev"
    tar -C "$src" -cf - . | $DOCKER run --rm -i -v "$VOL":/d alpine sh -c '
        set -e
        rm -rf /d/store.next && mkdir -p /d/store.next && tar -C /d/store.next -xf -
        rm -rf /d/store.prev
        if [ -d /d/store ]; then mv /d/store /d/store.prev; fi
        mv /d/store.next /d/store'
    # The running container still holds the old directory; a restart reopens the new one.
    $DOCKER service update --force "${STACK}_atlas" >/dev/null
    log "atlas restarted on the new store"
}

case "${1:-}" in
    deploy) do_deploy ;;
    store) shift; do_store "$@" ;;
    remove) $DOCKER stack rm "$STACK" ;;
    *) echo "Usage: $0 {deploy|store <dir>|remove}"; exit 1 ;;
esac
```

Check: `bash -n 149-atlas/atlas_deploy.sh` (syntax) and, if installed, `shellcheck 149-atlas/atlas_deploy.sh`.

- [ ] **Step 3: README and the secrets Sid adds**

`149-atlas/README.md`:

```markdown
# 149-atlas — Mtb Target Atlas on ned

Public, read-only target evidence for every *M. tuberculosis* H37Rv gene.
https://atlas.snet.biobio.tamu.edu · code: github.com/sidxz/mtb-atlas

## Image
`ghcr.io/sidxz/mtb-atlas`, public, built by the repo's `publish-image.yml`. Tag
pinned by `VERSION` in `.env`. The image holds no data and no host name.

## Store
`/net-fs-ins/docker-vols/atlas/store`, mounted read-only. Built and diffed on a
workstation (`atlas refresh <source>`, `atlas diff`), then
`./atlas_deploy.sh store ~/atlas/data/store`. The previous store is kept as
`store.prev`; to roll back, swap the two directories and
`docker --context ned service update --force atlas_atlas`.

## Secrets (`.env.enc`, SOPS)
VERSION, ANTHROPIC_API_KEY, ATLAS_SECRET, TURNSTILE_SITE_KEY,
TURNSTILE_SECRET_KEY, ORCID_CLIENT_ID, ORCID_CLIENT_SECRET,
ATLAS_PUBLIC_URL=https://atlas.snet.biobio.tamu.edu, ATLAS_OPERATOR,
ATLAS_CONTACT, ATLAS_FOOTER_LINKS (TAMU's required links, JSON).

## Notes
- `FORWARDED_ALLOW_IPS=172.16.50.0/24` (traefik-public) is in `atlas.yml`. If
  every visitor shows the same `/ask` allowance, it is wrong.
- One replica, `stop-first`: the `/ask` counter lives in the container, so a
  redeploy resets it (harmless: 24 h windows).
- ORCID production client: redirect URI
  `https://atlas.snet.biobio.tamu.edu/api/auth/orcid/callback`.
```

Sid then creates `.env` with real values (`ATLAS_SECRET` from `python -c "import secrets; print(secrets.token_urlsafe(48))"`) and encrypts: `sops encrypt --input-type dotenv --output-type dotenv .env > .env.enc`. **Do not write secrets into this plan, the chat, or any committed file.**

- [ ] **Step 4: Commit in the infra repo**

```bash
cd /Users/sidx/workspace/snet2-infrastructure/docker-swarm-core
git add 149-atlas/atlas.yml 149-atlas/atlas_deploy.sh 149-atlas/README.md
git commit -m "feat(149-atlas): Mtb Target Atlas stack

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(`.env.enc` is committed by Sid once it exists; `.env` stays ignored by the repo's `.gitignore` — confirm with `git check-ignore -v 149-atlas/.env`.)

- [ ] **Step 5: Deploy and check (with Sid, after the image is public)**

```bash
./atlas_deploy.sh store ~/atlas/data/store
./atlas_deploy.sh deploy
curl -fsS https://atlas.snet.biobio.tamu.edu/api/meta | head -c 200; echo
curl -fsS https://atlas.snet.biobio.tamu.edu/api/auth/me; echo
```

Expected: `/api/meta` JSON; `/auth/me` with `"remaining":5`, the Turnstile site key and `"signin_available":true`. Then from **two different networks** (e.g. campus Wi-Fi and a phone hotspot) ask once each: each sees its own "4 of 5". If both see 4 then 3, `FORWARDED_ALLOW_IPS` is not matching Traefik — fix before announcing the site. Finally sign in with ORCID and confirm the strip shows the iD and "20 of 20 left today".

---

## Self-review notes (resolved while writing)

- Spec coverage: Part 1 → Tasks 2–6; Part 2 → Tasks 1, 7, 8, 11; Part 3 → Tasks 9, 10. Out-of-scope items (accessibility audit, PubChem terms, Mycobrowser email, Trivy, `/version`) have no task by design.
- `/api/meta` needs a store, so CI's smoke test uses `/` and `/api/auth/me`; the image healthcheck uses `/api/meta` deliberately.
- `turnstile_site_key()` is defined in Task 3 so `api.py` never reaches into `ask_access._env`.
