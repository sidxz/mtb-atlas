"""ChEMBL target list, keyed on UniProt accession.

M0 ingests only the accession -> target mapping, which is what the ID crosswalk
needs. Bioactivity lands in M1. Licence: CC BY-SA 3.0, attribution requested;
ChEMBL asks that ChEMBL IDs be preserved and the release number displayed, which
is why `source_version` is parsed from the file rather than hardcoded.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet

SOURCE = "chembl"
URL = "https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/latest/chembl_uniprot_mapping.txt"

# First line is e.g. "# chembl_37 target list, 01/05/2026".
_VERSION = re.compile(r"#\s*(chembl_\S+)\s+target list,\s*(\S+)")


def fetch_raw(*, force: bool = False) -> Fetched:
    return fetch(URL, "chembl_uniprot_mapping.txt", source=SOURCE, min_interval=0.5, force=force)


def release(path: Path) -> str:
    with path.open(encoding="utf-8") as handle:
        match = _VERSION.match(handle.readline())
    return f"{match.group(1)} ({match.group(2)})" if match else "unknown"


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    """The whole table, not just Mycobacterium.

    Keeping every row (~17k) lets the crosswalk resolve both the direct Mtb
    targets and the mycobacterial orthologue targets without this ingester
    needing to know anything about the gene universe.
    """
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 4:
                continue
            accession, target_id, pref_name, target_type = parts
            yield {
                "uniprot_acc": accession,
                "chembl_target_id": target_id,
                "pref_name": pref_name,
                "target_type": target_type,
            }


def build(*, force: bool = False) -> Path:
    raw = fetch_raw(force=force)
    return write_parquet(
        "chembl_targets",
        normalize(raw.path),
        source=SOURCE,
        source_version=release(raw.path),
        retrieved_at=raw.retrieved_at,
    )
