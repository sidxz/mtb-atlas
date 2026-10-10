"""Resistance mutations from the WHO mutation catalogue.

*Catalogue of mutations in Mycobacterium tuberculosis complex and their
association with drug resistance*, 2nd edition (WHO, 2023) — the current
edition. Data licence: ODC-By 1.0, stated in the repository's
`Final Result Files/LICENSE.md`.

Scope matters more here than anywhere else in the pipeline. The catalogue
covers **65 genes** — those with matched phenotypic drug-susceptibility
testing — and is keyed on **gene symbol, not Rv tag**. Neither `dprE1` nor
`mmpL3` is in it. Every other gene in the atlas gets no resistance row, and
that absence is the honest answer rather than a gap to fill from elsewhere.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet

SOURCE = "who-catalogue"
EDITION = "WHO catalogue of mutations in MTBC, 2nd ed. (2023)"
REPO = "https://raw.githubusercontent.com/GTB-tbsequencing/mutation-catalogue-2023/main"
URL = f"{REPO}/Final%20Result%20Files/WHO-UCN-TB-2023.6-eng_catalogue_master_file.txt"

GRADING = "FINAL CONFIDENCE GRADING"
# Gradings 3-5 are "uncertain significance", "not associated - interim" and
# "not associated". Counting those as resistance would badly overstate it.
ASSOCIATED = ("1) Assoc w R", "2) Assoc w R - Interim")

AA3 = {
    "Ala": "A",
    "Arg": "R",
    "Asn": "N",
    "Asp": "D",
    "Cys": "C",
    "Gln": "Q",
    "Glu": "E",
    "Gly": "G",
    "His": "H",
    "Ile": "I",
    "Leu": "L",
    "Lys": "K",
    "Met": "M",
    "Phe": "F",
    "Pro": "P",
    "Ser": "S",
    "Thr": "T",
    "Trp": "W",
    "Tyr": "Y",
    "Val": "V",
    "Ter": "*",
}
MISSENSE = re.compile(r"^p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})$")


def residue(mutation: str) -> tuple[int | None, str | None]:
    """`p.Ser315Thr` -> (315, "S315T"), for mapping onto a structure.

    Returns (None, None) for everything else, which is most of the catalogue:
    promoter variants, frameshifts and stop codons cannot be drawn on a
    structure, and a viewer that silently dropped them would overstate how much
    of a gene's resistance is structural.
    """
    match = MISSENSE.match(mutation or "")
    if not match:
        return None, None
    wild, position, mutant = match.groups()
    return int(position), f"{AA3.get(wild, wild)}{position}{AA3.get(mutant, mutant)}"


def fetch_raw(*, force: bool = False) -> Fetched:
    return fetch(URL, "who-catalogue-v2-master.txt", source=SOURCE, min_interval=1.0, force=force)


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    """One row per (gene, mutation, drug). 48,152 rows over 65 genes."""
    csv.field_size_limit(10**9)
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            grading = row[GRADING]
            position, label = residue(row["mutation"])
            yield {
                "gene": row["gene"],
                "mutation": row["mutation"],
                "variant": row["variant"],
                "drug": row["drug"],
                "grading": grading,
                "associated": grading in ASSOCIATED,
                "tier": row["tier"],
                "effect": row["effect"],
                "genomic_position": row["genomic position"] or None,
                "residue_position": position,
                "residue_label": label,
            }


def build(*, force: bool = False) -> Path:
    raw = fetch_raw(force=force)
    return write_parquet(
        "resistance",
        normalize(raw.path),
        source=SOURCE,
        source_version=EDITION,
        retrieved_at=raw.retrieved_at,
    )
