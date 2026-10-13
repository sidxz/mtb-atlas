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


# --- the gate on /ask and /auth/me ------------------------------------------------


@pytest.fixture
def asking(evidence_store: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
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
    now = time.time()
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


def test_a_non_ascii_state_signs_nobody_in(signing_in: TestClient) -> None:
    _login(signing_in, "/map")
    back = signing_in.get(
        "/auth/orcid/callback", params={"code": "ok", "state": "café"}, follow_redirects=False
    )
    assert back.status_code == 302
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
    # Sign in for real, so the cookie logout deletes is the one the server set.
    state = _login(signing_in, "/")
    signing_in.get("/auth/orcid/callback", params={"code": "ok", "state": state})
    assert signing_in.get("/auth/me").json()["orcid"] == IRIS
    assert signing_in.post("/auth/logout").status_code == 204
    assert signing_in.get("/auth/me").json()["orcid"] is None


def test_sign_in_is_404_when_not_configured(asking: TestClient) -> None:
    assert asking.get("/auth/orcid/login", follow_redirects=False).status_code == 404


def _cookie_attributes(response: httpx.Response, name: str) -> dict[str, str]:
    """One Set-Cookie header's attributes, names lower-cased; flags map to ''."""
    for header in response.headers.get_list("set-cookie"):
        first, *rest = (part.strip() for part in header.split(";"))
        if first.split("=", 1)[0] == name:
            attrs = {}
            for part in rest:
                key, _, value = part.partition("=")
                attrs[key.lower()] = value
            return attrs
    raise AssertionError(f"no Set-Cookie for {name}")


def test_a_denied_sign_in_returns_to_its_page_without_a_session(signing_in: TestClient) -> None:
    state = _login(signing_in, "/genome?x=1")
    back = signing_in.get(
        "/auth/orcid/callback",
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )
    assert back.headers["location"] == "https://atlas.example.org/genome?x=1&signin=failed"
    assert signing_in.get("/auth/me").json()["orcid"] is None


def test_the_state_cookie_is_httponly_secure_lax_and_ten_minutes(signing_in: TestClient) -> None:
    started = signing_in.get("/auth/orcid/login", follow_redirects=False)
    attrs = _cookie_attributes(started, access.STATE_COOKIE)
    assert "httponly" in attrs
    assert "secure" in attrs
    assert attrs["samesite"].lower() == "lax"
    assert attrs["path"] == "/"
    assert attrs["max-age"] == "600"


def test_the_session_cookie_is_httponly_secure_lax_and_thirty_days(signing_in: TestClient) -> None:
    state = _login(signing_in, "/")
    back = signing_in.get(
        "/auth/orcid/callback", params={"code": "ok", "state": state}, follow_redirects=False
    )
    attrs = _cookie_attributes(back, access.SESSION_COOKIE)
    assert "httponly" in attrs
    assert "secure" in attrs
    assert attrs["samesite"].lower() == "lax"
    assert attrs["path"] == "/"
    assert attrs["max-age"] == str(int(access.SESSION_SECONDS))


def test_the_state_cookie_is_cleared_on_return(signing_in: TestClient) -> None:
    state = _login(signing_in, "/")
    back = signing_in.get(
        "/auth/orcid/callback", params={"code": "ok", "state": state}, follow_redirects=False
    )
    attrs = _cookie_attributes(back, access.STATE_COOKIE)
    assert attrs["max-age"] == "0"


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
