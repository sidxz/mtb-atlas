"""/ask's allowance: the counting, the signing, and the routes that use them.

Turnstile and ORCID are never called: their two functions are replaced, so these
tests run offline like every other test here.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas import agent, api, store, summary
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
        lambda c: c + "é",  # a non-ASCII cookie is no cookie, not a TypeError
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


# --- hardening: every failure of Turnstile / ORCID is a refusal -----------------


class _Reply:
    def __init__(self, status: int = 200, body: object = None, bad_json: bool = False) -> None:
        self.status_code, self._body, self._bad = status, body, bad_json

    def json(self) -> object:
        if self._bad:
            raise ValueError("not json")
        return self._body


def _post(monkeypatch: pytest.MonkeyPatch, reply: _Reply | Exception) -> None:
    def fake(*args, **kwargs):
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(httpx, "post", fake)


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")
    monkeypatch.setenv("ORCID_CLIENT_ID", "id")
    monkeypatch.setenv("ORCID_CLIENT_SECRET", "s")
    monkeypatch.setenv("ATLAS_PUBLIC_URL", "https://x.example")


@pytest.mark.parametrize(
    "reply",
    [
        httpx.ConnectError("down"),
        httpx.InvalidURL("bad"),
        _Reply(500, {"success": True}),
        _Reply(200, {"success": False}),
        _Reply(200, ["success"]),
        _Reply(200, "yes"),
        _Reply(200, bad_json=True),
    ],
)
def test_turnstile_is_false_on_any_failure(keys: None, monkeypatch, reply) -> None:
    _post(monkeypatch, reply)
    assert access.verify_turnstile("tok", "1.2.3.4") is False


def test_turnstile_is_true_only_on_a_clear_yes(keys: None, monkeypatch) -> None:
    _post(monkeypatch, _Reply(200, {"success": True}))
    assert access.verify_turnstile("tok", "1.2.3.4") is True


@pytest.mark.parametrize(
    "reply",
    [
        httpx.ConnectError("down"),
        httpx.InvalidURL("bad"),
        _Reply(401, {"orcid": IRIS}),
        _Reply(200, [IRIS]),
        _Reply(200, {}),
        _Reply(200, {"orcid": "not-an-id"}),
        _Reply(200, {"orcid": 5}),
        _Reply(200, bad_json=True),
    ],
)
def test_orcid_exchange_is_none_on_any_failure(keys: None, monkeypatch, reply) -> None:
    _post(monkeypatch, reply)
    assert access.exchange_code("code") is None


def test_orcid_exchange_returns_the_id(keys: None, monkeypatch) -> None:
    _post(monkeypatch, _Reply(200, {"orcid": IRIS, "name": "x", "access_token": "t"}))
    assert access.exchange_code("code") == IRIS


def test_an_ip_digest_is_not_a_session_signature(secret: None) -> None:
    assert access.ip_key("x") != "ip:" + access._sign("session", "x")
    assert access.ip_key("x") != "ip:" + access._sign("state", "x")
