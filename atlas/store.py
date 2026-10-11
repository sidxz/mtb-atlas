"""The normalized store: one Parquet file per source, written by DuckDB.

Normalization happens in Python (it is branchy, and branchy logic belongs
somewhere testable); DuckDB only does the typing and the Parquet write, which
keeps the dependency list at httpx + duckdb.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable, Iterator, Mapping
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

    stamped = stamp(rows, source=source, source_version=source_version, retrieved_at=retrieved_at)
    return _write(name, stamped, store)


def stamp(
    rows: Iterable[Mapping[str, Any]], *, source: str, source_version: str, retrieved_at: str
) -> Iterator[dict[str, Any]]:
    """`rows` with their provenance attached, for `write_stamped`.

    A generator, so a table of millions of rows is never held twice.
    """
    labels = {"source": source, "source_version": source_version, "retrieved_at": retrieved_at}
    for row in rows:
        if clash := set(row) & set(PROVENANCE):
            raise ValueError(f"rows already carry provenance columns {sorted(clash)}")
        yield {**row, **labels}


def write_stamped(
    name: str, rows: Iterable[Mapping[str, Any]], *, store: Path | None = None
) -> Path:
    """Write rows that each carry their own provenance, for a table two sources feed.

    `screens` holds PubChem's campaigns and ChEMBL's literature campaigns. One stamp
    for the table would label a ChEMBL paper `pubchem`, and the UI shows provenance
    for every value. A row without all three columns is refused, never written
    unlabelled. `provenance()` reads the first row, so that is the source whose
    version the table answers for.
    """
    return _write(name, rows, store, require_provenance=True)


def _write(
    name: str,
    rows: Iterable[Mapping[str, Any]],
    store: Path | None,
    *,
    require_provenance: bool = False,
) -> Path:
    out_dir = store or STORE
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.parquet"

    count = 0
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as tmp:
        tmp_path = Path(tmp.name)
        try:
            for row in rows:
                if require_provenance and (missing := [k for k in PROVENANCE if not row.get(k)]):
                    raise ValueError(f"{name}: a row carries no {', '.join(missing)}: {dict(row)}")
                # default=str so dates round-trip: DuckDB types `retrieved_at` as DATE
                # on the way in, and a rebuild feeds that value straight back here.
                tmp.write(json.dumps(row, default=str) + "\n")
                count += 1
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
    if not count:
        tmp_path.unlink(missing_ok=True)
        raise ValueError(f"refusing to write an empty {name}.parquet")

    try:
        # sample_size=-1 reads every row to settle a column's type. The default samples
        # 20,480, and a column that is NULL throughout the sample types as JSON, which
        # stores every later string with its quotation marks and no error to say so.
        duckdb.connect().execute(
            f"COPY (SELECT * FROM read_json_auto('{tmp_path}', format='newline_delimited', "
            f"sample_size=-1)) TO '{out}' (FORMAT PARQUET)"
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
