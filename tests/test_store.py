"""The store's read path, which every page, the API and the agent go through."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from atlas.store import provenance, write_parquet


def test_a_missing_table_does_not_poison_later_reads(store: Path) -> None:
    """A half-read result plus one failed read used to abort every read after it.

    `provenance` fetches a single row, which left that result -- and its
    transaction -- open on DuckDB's shared default connection; the next failed
    read aborted the transaction for the whole process. `/meta` skips sources
    that are not built yet, so the first unbuilt one turned it into a 500.
    """
    provenance("genes", store=store)
    with pytest.raises(duckdb.IOException):
        provenance("not_built_yet", store=store)
    assert provenance("genes", store=store)[0]


def _types(path: Path) -> dict[str, str]:
    return dict(duckdb.sql(f"SELECT column_name, column_type FROM (DESCRIBE '{path}')").fetchall())


def test_a_column_is_typed_from_every_row_not_from_the_first_20480(tmp_path: Path) -> None:
    """DuckDB infers a JSON column's type from a sample, and 20,480 rows is the default.

    A column that is NULL for all of them types as JSON, and every later value is then
    stored as JSON text: a string keeps its quotation marks (`'"active"'`), so an
    `outcome = 'active'` filter finds nothing and no error says why. The screens tables
    are the case that matters: one source's rows come first, and they carry no outcome.
    """
    leading = [{"outcome": None, "cid": None, "score": None} for _ in range(25_000)]
    later = [{"outcome": "active", "cid": "911287", "score": 80}]
    path = write_parquet(
        "sampled",
        leading + later,
        source="x",
        source_version="1",
        retrieved_at="2026-10-11",
        store=tmp_path,
    )
    assert _types(path) == {
        "outcome": "VARCHAR",
        "cid": "VARCHAR",
        "score": "BIGINT",
        "source": "VARCHAR",
        "source_version": "VARCHAR",
        "retrieved_at": "DATE",
    }
    found = duckdb.sql(f"SELECT outcome, cid, score FROM '{path}' WHERE score IS NOT NULL")
    assert found.fetchall() == [("active", "911287", 80)]
