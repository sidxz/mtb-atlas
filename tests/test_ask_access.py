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
