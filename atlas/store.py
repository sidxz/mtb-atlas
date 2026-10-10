"""The normalized store: one Parquet file per source, written by DuckDB.

Normalization happens in Python (it is branchy, and branchy logic belongs
somewhere testable); DuckDB only does the typing and the Parquet write, which
keeps the dependency list at httpx + duckdb.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import duckdb

from .fetch import STORE

# Every record in the store carries these three, per the provenance rule: the UI
# must be able to show where any single value came from and how old it is.
PROVENANCE = ("source", "source_version", "retrieved_at")


def write_parquet(
    name: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    source: str,
    source_version: str,
    retrieved_at: str,
    store: Path | None = None,
) -> Path:
    """Write `rows` to `<store>/<name>.parquet`, stamping provenance on each one."""
    rows = list(rows)
    if not rows:
        raise ValueError(f"refusing to write an empty {name}.parquet")

    clash = set(rows[0]) & set(PROVENANCE)
    if clash:
        raise ValueError(f"{name}: rows already carry provenance columns {sorted(clash)}")

    out_dir = store or STORE
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.parquet"

    stamp = {"source": source, "source_version": source_version, "retrieved_at": retrieved_at}
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as tmp:
        for row in rows:
            # default=str so dates round-trip: DuckDB types `retrieved_at` as DATE
            # on the way in, and a rebuild feeds that value straight back here.
            tmp.write(json.dumps({**row, **stamp}, default=str) + "\n")
        tmp_path = Path(tmp.name)

    try:
        duckdb.connect().execute(
            f"COPY (SELECT * FROM read_json_auto('{tmp_path}', format='newline_delimited')) "
            f"TO '{out}' (FORMAT PARQUET)"
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    return out


def read(name: str, *, store: Path | None = None) -> duckdb.DuckDBPyRelation:
    """Read a store file back. The API layer uses only this, never an ingester.

    Each read gets its own connection. On DuckDB's shared default connection a
    partly fetched result keeps a transaction open, and one failed read -- a
    source not built yet -- then aborted every read after it in the process.
    """
    return duckdb.connect().sql(f"SELECT * FROM '{(store or STORE) / f'{name}.parquet'}'")


def rows(name: str, *, store: Path | None = None) -> tuple[list[tuple], dict[str, int]]:
    """A store file as (rows, column index), for joins that are clearer in Python."""
    relation = read(name, store=store)
    return relation.fetchall(), {c: i for i, c in enumerate(relation.columns)}


def built(name: str, *, store: Path | None = None) -> bool:
    """Whether a stage has written this table yet. A store can stop part-way."""
    return ((store or STORE) / f"{name}.parquet").exists()


def records(name: str, *, store: Path | None = None) -> list[dict[str, Any]]:
    """A store file as one dict per row, for joins written in Python."""
    relation = read(name, store=store)
    return [dict(zip(relation.columns, row, strict=True)) for row in relation.fetchall()]


def provenance(name: str, *, store: Path | None = None) -> tuple[str, str]:
    """The (source_version, retrieved_at) stamped on a store file."""
    return read(name, store=store).project("source_version, retrieved_at").fetchone()
