"""The store's read path, which every page, the API and the agent go through."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from atlas.store import provenance


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
