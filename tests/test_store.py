"""The store's read path, which every page, the API and the agent go through."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from atlas.store import provenance, stamp, write_parquet, write_stamped


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


def test_a_table_two_sources_feed_keeps_each_rows_own_provenance(tmp_path: Path) -> None:
    """`screens` holds PubChem campaigns and ChEMBL literature campaigns. Stamping the
    table as one source would label a ChEMBL paper `pubchem` and give it PubChem's
    version, in a store whose rule is that the UI shows where every value came from.
    The first row is the one `provenance()` answers for, so the order is meaningful."""
    first = stamp([{"id": "a"}], source="pubchem", source_version="v1", retrieved_at="2026-10-11")
    second = stamp([{"id": "b"}], source="chembl", source_version="v2", retrieved_at="2026-10-09")
    path = write_stamped("mixed", [*first, *second], store=tmp_path)
    rows = duckdb.sql(f"SELECT id, source, source_version, retrieved_at FROM '{path}'").fetchall()
    assert [(r[0], r[1], r[2], str(r[3])) for r in rows] == [
        ("a", "pubchem", "v1", "2026-10-11"),
        ("b", "chembl", "v2", "2026-10-09"),
    ]
    assert provenance("mixed", store=tmp_path)[0] == "v1"


def test_a_row_that_carries_no_provenance_is_refused_not_written_unlabelled(tmp_path: Path) -> None:
    rows = [
        *stamp([{"id": "a"}], source="pubchem", source_version="v1", retrieved_at="2026-10-11"),
        {"id": "b", "source": "chembl", "source_version": "v2"},  # no retrieved_at
    ]
    with pytest.raises(ValueError, match=r"mixed.*retrieved_at"):
        write_stamped("mixed", rows, store=tmp_path)
    assert not (tmp_path / "mixed.parquet").exists()


def test_stamping_a_row_that_already_has_provenance_is_an_error() -> None:
    with pytest.raises(ValueError, match="already carry"):
        list(stamp([{"id": "a", "source": "x"}], source="y", source_version="1", retrieved_at="d"))


def test_write_stamped_refuses_an_empty_table(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        write_stamped("mixed", [], store=tmp_path)


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
