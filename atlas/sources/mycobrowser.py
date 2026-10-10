"""Mycobrowser H37Rv gene annotation: the backbone of the gene universe.

Release 5 (2024-07-11). Every ingester in this package exposes the same three
functions -- `fetch_raw`, `normalize`, `build` -- so the pipeline can treat them
uniformly without an abstract base class standing in for one implementation.

Licence note: Mycobrowser publishes no data licence, only a citation request
(see docs/data-sources.md). The pipeline downloads at build time and the raw
files are gitignored, so this repository redistributes none of it.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet

SOURCE = "mycobrowser"
RELEASE = "5"
RELEASE_DATE = "2024-07-11"
URL = (
    f"https://mycobrowser.epfl.ch/releases/{RELEASE}/get_file"
    "?dir=txt&file=Mycobacterium_tuberculosis_H37Rv.txt"
)

# The gene universe is Mycobrowser's CDS rows (4031 loci). The file also carries
# ncRNA/tRNA/rRNA genes and, on separate rows re-using a gene's locus tag,
# regulatory features (promoter, -10_signal, -35_signal) -- those are not genes
# and would otherwise duplicate a locus.
GENE_FEATURE = "CDS"


def fetch_raw(*, force: bool = False) -> Fetched:
    return fetch(URL, "H37Rv_v5.txt", source=SOURCE, min_interval=1.0, force=force)


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    """Rows -> one record per CDS locus.

    Reads by column index rather than `csv.DictReader` because the release file
    has a duplicated header name (`Orthologues M. tuberculosis` appears twice),
    which a dict reader silently collapses.
    """
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader)
        col = {name: i for i, name in enumerate(header)}
        for row in reader:
            if row[col["Feature"]] != GENE_FEATURE:
                continue
            yield {
                "rv_id": row[col["Locus"]].strip(),
                "gene_name": row[col["Name"]].strip() or None,
                "product": row[col["Product"]].strip() or None,
                "function": row[col["Function"]].strip() or None,
                "functional_category": row[col["Functional_Category"]].strip() or None,
                "start": int(row[col["Start"]]),
                "stop": int(row[col["Stop"]]),
                "strand": row[col["Strand"]].strip(),
                "is_pseudogene": row[col["Is_Pseudogene"]].strip() == "Yes",
                # Mycobrowser's own UniProt claim. The crosswalk compares it against
                # the reference proteome rather than trusting either side blindly.
                "mycobrowser_uniprot_ac": row[col["UniProt_AC"]].strip() or None,
                # Drug abbreviations (e.g. "ETH,INH"), not mutations -- a coarse
                # "this gene is implicated in resistance to" flag.
                "resistance_drugs": [
                    d.strip() for d in row[col["Drug Resistance Mutations"]].split(",") if d.strip()
                ],
            }


def build(*, force: bool = False) -> Path:
    raw = fetch_raw(force=force)
    return write_parquet(
        "genes",
        normalize(raw.path),
        source=SOURCE,
        source_version=f"release {RELEASE} ({RELEASE_DATE})",
        retrieved_at=raw.retrieved_at,
    )
