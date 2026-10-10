"""Gene essentiality from published transposon mutagenesis.

DeJesus MA, Gerrick ER, Xu W, et al. mBio 2017;8(1):e02133-16 (PMC5241402),
CC BY 4.0. Table S3 carries the ORF-level calls from a motif-dependent HMM,
keyed on Rv locus tag.

Keyed on `(rv_id, source)`, not `rv_id`: these are calls from one condition
(7H9 broth), and "essential, and under which conditions?" needs room for more.

The supplementary file cannot be fetched from PMC — `pmc.ncbi.nlm.nih.gov`
returns an HTML "Preparing to download" interstitial to scripted requests — so
this goes through Europe PMC, which serves a zip of the whole supplement.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet

SOURCE = "dejesus-2017"
PMCID = "PMC5241402"
URL = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{PMCID}/supplementaryFiles"
MEMBER = "mbo002173137st3.xlsx"
SHEET = "ORF Essentiality Calls"
CITATION = "DeJesus et al. 2017 mBio 8(1):e02133-16, Table S3"
CONDITION = "in vitro, 7H9 broth"

# The published key, spelled out so the UI never has to guess at an acronym.
CALLS = {
    "ES": "Essential",
    "ESD": "Essential domain",
    "GD": "Growth defect",
    "NE": "Non-essential",
    "GA": "Growth advantage",
    "Uncertain": "Uncertain (too short, or no insertions either way)",
}
# Essential proper. ESD counts: part of the protein is essential even though the
# whole ORF tolerates insertions, which is exactly the case for MmpL3.
ESSENTIAL = frozenset({"ES", "ESD"})
# Any measurable fitness cost. Kept separate, because calling a growth-defect
# gene "essential" would overstate 135 genes.
FITNESS_COST = frozenset({"ES", "ESD", "GD"})


def fetch_raw(*, force: bool = False) -> Fetched:
    # Slow (~90 s for 4.7 MB) but cached, so only the first build pays.
    return fetch(URL, f"{PMCID}-supplement.zip", source=SOURCE, min_interval=1.0, force=force)


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    """Table S3 -> one row per ORF. Row 1 is a caption; the header is row 2."""
    from openpyxl import load_workbook

    with zipfile.ZipFile(path) as archive:
        raw = archive.read(MEMBER)
    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    rows = workbook[SHEET].iter_rows(values_only=True)
    next(rows)
    header = [str(h) if h is not None else "" for h in next(rows)]
    index = {name: i for i, name in enumerate(header)}

    for row in rows:
        rv_id = row[index["ORF ID"]]
        if not rv_id or not str(rv_id).startswith("Rv"):
            continue
        call = row[index["Final Call"]]
        yield {
            "rv_id": str(rv_id),
            "call": call,
            "call_label": CALLS.get(call, call),
            "essential": call in ESSENTIAL,
            "fitness_cost": call in FITNESS_COST,
            "condition": CONDITION,
            "ta_sites": row[index["Number of TA Sites"]],
            "permissive_sites": row[index["Number of Permissive (P) Sites"]],
            "non_permissive_sites": row[index["Number of Non-Permissive (NP) Sites"]],
            "insertion_fraction": row[index["Fraction of Sites with Insertions"]],
            "mean_read_count": row[index["Mean Normalized Read-Count At Non-Zero Sites"]],
            "citation": CITATION,
        }


def build(*, force: bool = False) -> Path:
    raw = fetch_raw(force=force)
    return write_parquet(
        "essentiality",
        normalize(raw.path),
        source=SOURCE,
        source_version=CITATION,
        retrieved_at=raw.retrieved_at,
    )
