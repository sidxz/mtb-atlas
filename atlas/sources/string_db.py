"""Functional interaction partners from STRING.

STRING v12.5, taxon 83332. Licence: CC BY 4.0 — "All data and download files
in STRING are freely available under a 'Creative Commons BY 4.0' license",
covering "network images, functional enrichment graphs, tables, data files,
individual scores and data points". STRING asks that bulk users take the flat
files rather than the API, which is what this does.

Why it earns a place in a target atlas: a gene's partners are how you tell a
lone enzyme from a committed step in a pathway, and they are where you look
when a target turns out to be undruggable and you need the next node along.

STRING's protein ids are literally `83332.Rv0001`, so this is the only source
in the pipeline that keys to an Rv tag with nothing but a prefix strip.
"""

from __future__ import annotations

import csv
import gzip
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet

SOURCE = "string-db"
VERSION = "12.5"
TAXON = "83332"
BASE = "https://stringdb-downloads.org/download"
LINKS_URL = (
    f"{BASE}/protein.links.detailed.v{VERSION}/{TAXON}.protein.links.detailed.v{VERSION}.txt.gz"
)
INFO_URL = f"{BASE}/protein.info.v{VERSION}/{TAXON}.protein.info.v{VERSION}.txt.gz"

# STRING scores are 0-1000. 700 is STRING's own "high confidence" cut; the full
# file is 1.39M edges, which is mostly low-confidence text mining and would
# swamp a target page. 57k edges survive, and they are the ones worth showing.
MIN_SCORE = 700

CHANNELS = (
    "neighborhood",
    "fusion",
    "cooccurence",
    "coexpression",
    "experimental",
    "database",
    "textmining",
)


def _strip(protein_id: str) -> str:
    """`83332.Rv0001` -> `Rv0001`."""
    return protein_id.split(".", 1)[1] if "." in protein_id else protein_id


def fetch_raw(*, force: bool = False) -> tuple[Fetched, Fetched]:
    links = fetch(
        LINKS_URL, f"links.v{VERSION}.txt.gz", source=SOURCE, min_interval=1.0, force=force
    )
    info = fetch(INFO_URL, f"info.v{VERSION}.txt.gz", source=SOURCE, min_interval=1.0, force=force)
    return links, info


def normalize(links_path: Path, info_path: Path) -> Iterator[dict[str, Any]]:
    """High-confidence edges, one row per unordered pair.

    The download lists every edge twice (A-B and B-A); emitting both would
    double every partner count downstream.
    """
    names: dict[str, str] = {}
    with gzip.open(info_path, "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            names[_strip(row["#string_protein_id"])] = row["preferred_name"]

    seen: set[tuple[str, str]] = set()
    with gzip.open(links_path, "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter=" "):
            score = int(row["combined_score"])
            if score < MIN_SCORE:
                continue
            left, right = _strip(row["protein1"]), _strip(row["protein2"])
            pair = (left, right) if left <= right else (right, left)
            if pair in seen:
                continue
            seen.add(pair)
            yield {
                "rv_id": pair[0],
                "partner_rv_id": pair[1],
                "partner_name": names.get(pair[1]),
                "rv_name": names.get(pair[0]),
                "combined_score": score,
                # Kept per channel: an edge supported only by text mining is a
                # much weaker claim than one with experimental support, and the
                # combined score alone hides which it is.
                **{channel: int(row[channel]) for channel in CHANNELS},
            }


def build(*, force: bool = False) -> Path:
    links, info = fetch_raw(force=force)
    return write_parquet(
        "interactions",
        normalize(links.path, info.path),
        source=SOURCE,
        source_version=f"STRING v{VERSION}, taxon {TAXON}, combined_score >= {MIN_SCORE}",
        retrieved_at=links.retrieved_at,
    )
