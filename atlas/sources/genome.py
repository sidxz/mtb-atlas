"""The H37Rv chromosome, NC_000962.3, from NCBI RefSeq: the sequence under every locus.

Mycobrowser's coordinates are on this record -- its release file states
`NC_000962.3` in `Refseq_ID` on every row -- so a gene's DNA is a slice of it,
taken at read time rather than stored a second time per gene. A versioned RefSeq
accession names one sequence for ever; a re-annotation is a new version, not an
edit to this one.

Licence: NCBI places no restriction on its own records (US-government work); see
docs/data-sources.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet

SOURCE = "ncbi-refseq"
ACCESSION = "NC_000962.3"
URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    f"?db=nuccore&id={ACCESSION}&rettype=fasta&retmode=text"
)
_COMPLEMENT = str.maketrans("ACGTNacgtn", "TGCANtgcan")


def fetch_raw(*, force: bool = False) -> Fetched:
    return fetch(URL, f"{ACCESSION}.fasta", source=SOURCE, min_interval=0.4, force=force)


def normalize(path: Path) -> dict[str, Any]:
    """One FASTA record -> one row. Refuses anything but the accession it asked for."""
    header, *lines = path.read_text().splitlines()
    accession = header[1:].split()[0]
    if accession != ACCESSION:
        raise ValueError(f"expected {ACCESSION}, NCBI returned {accession}")
    sequence = "".join(line.strip() for line in lines).upper()
    return {
        "accession": accession,
        "description": header[1:].split(" ", 1)[1],
        "length": len(sequence),
        "sequence": sequence,
    }


def dna(sequence: str, start: int, stop: int, strand: str) -> str:
    """A feature's DNA, 5' to 3' on its own strand. Coordinates are 1-based, inclusive."""
    piece = sequence[start - 1 : stop]
    return piece.translate(_COMPLEMENT)[::-1] if strand == "-" else piece


def build(*, force: bool = False) -> Path:
    raw = fetch_raw(force=force)
    return write_parquet(
        "genome",
        [normalize(raw.path)],
        source=SOURCE,
        source_version=ACCESSION,
        retrieved_at=raw.retrieved_at,
    )
