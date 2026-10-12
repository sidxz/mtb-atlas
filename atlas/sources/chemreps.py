"""ChEMBL's structure file: one SMILES per compound, for the whole release.

`compounds` is the ChEMBL potency set, 5,178 molecules, and the screening layer
references 479,023. A page draws a compound from a SMILES, so without this about
99% of the screens could not be drawn. ChEMBL publishes every compound's structure
as one flat file (`chembl_37_chemreps.txt.gz`, 292,540,141 bytes), which replaces
about 9,500 requests to the molecule endpoint and covers the whole screened set
rather than an affordable subset. The same reasoning as `unichem.py`: when the
question is "map my whole key set", a bulk file beats a request per id.

The file is read for the ids the store references and nothing else, so 2.9M rows
are streamed past and never held. Each wanted id gets exactly one row, in one of
two states, and the third state is having no row:

- `has_structure` true: the file has a SMILES for it.
- `has_structure` false: looked up, and this release's structure file has no line
  for it (a molecule without a structure, or an id outside the release).
- no row: never looked up. A PubChem-only CID has no ChEMBL id and is one of these.

A separate table rather than a wider `compounds`, because that table's provenance
is stamped for the potency set; widening it would re-scope its claim to a
population it was never measured over.

Licence: CC BY-SA 3.0, ChEMBL's.
"""

from __future__ import annotations

import gzip
from collections.abc import Collection, Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet
from . import chembl

SOURCE = "chembl"
HEADER = "chembl_id\tcanonical_smiles\tstandard_inchi\tstandard_inchi_key"


def url(release: str) -> str:
    base = "https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/releases"
    return f"{base}/{release}/{release}_chemreps.txt.gz"


def release_name(mapping: Path) -> str:
    """`chembl_37`, from the first line of the mapping file the identity stage fetched.

    The URL is built from it, so a new release is a new URL, and `fetch` re-downloads
    when the URL changes. A file that names no release is refused rather than guessed.
    """
    stated = chembl.release(mapping)
    if stated == "unknown":
        raise ValueError(f"{mapping} names no ChEMBL release; cannot say which file to fetch")
    return stated.split(" ")[0]


def fetch_raw(release: str, *, force: bool = False) -> Fetched:
    return fetch(
        url(release),
        f"chemreps/{release}_chemreps.txt.gz",
        source=SOURCE,
        min_interval=0.5,
        timeout=900.0,
        force=force,
    )


def _lines(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        # The first line is skipped as a header, so a file without one would lose a
        # compound silently.
        header = next(handle, "").rstrip("\n")
        if header != HEADER:
            raise ValueError(
                f"chemreps header is {header!r}, not {HEADER!r}. Refusing to read a file "
                "whose first line is not the header, since that line would be dropped."
            )
        yield from handle


def normalize(path: Path, wanted: Collection[str]) -> Iterator[dict[str, Any]]:
    """One row per wanted id: those the file has, then those it lacks.

    A line that is not four fields is skipped, and a blank SMILES is no structure:
    true beside a NULL SMILES would promise a drawing the page cannot make. An id
    the file lists twice raises, because keeping either line would be a choice the
    source did not make.
    """
    wanted = set(wanted)
    found: set[str] = set()
    for line in _lines(path):
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 4:
            continue
        chembl_id, smiles, _inchi, key = parts
        if chembl_id not in wanted or not smiles:
            continue
        if chembl_id in found:
            raise ValueError(f"{chembl_id} is listed twice in {path.name}")
        found.add(chembl_id)
        yield {
            "molecule_chembl_id": chembl_id,
            "has_structure": True,
            "canonical_smiles": smiles,
            "standard_inchi_key": key or None,
        }
    for chembl_id in sorted(wanted - found):
        yield {
            "molecule_chembl_id": chembl_id,
            "has_structure": False,
            "canonical_smiles": None,
            "standard_inchi_key": None,
        }


def build(wanted: Collection[str], *, force: bool = False, store: Path | None = None) -> Path:
    release = release_name(chembl.fetch_raw().path)
    raw = fetch_raw(release, force=force)
    return write_parquet(
        "compound_structures",
        normalize(raw.path, wanted),
        source=SOURCE,
        source_version=release,
        retrieved_at=raw.retrieved_at,
        store=store,
    )
