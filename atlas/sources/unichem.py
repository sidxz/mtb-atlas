"""UniChem: the ChEMBL <-> PubChem compound bridge, as one file.

PubChem keys a screening result on CID and ChEMBL keys a compound on
`molecule_chembl_id`. Without a bridge, a 215,397-compound screen cannot be
reached from a compound page. The alternatives were a request per compound
against PubChem's synonym endpoint, or PubChem's CID-Synonym dump (about 1 GB
compressed); UniChem publishes the whole src1 <-> src22 mapping as a single
gzipped file from the same provider as ChEMBL.

Licence: CC BY-SA 3.0, as ChEMBL's distribution states. UniChem's own README
names no licence, so this is inherited from the ChEMBL FTP tree, not stated by
UniChem.

Unlike the other sources here, this module has no `build`: nothing is written
to the store from it. It is a lookup that the PubChem ingester consumes.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch

SOURCE = "unichem"
URL = (
    "https://ftp.ebi.ac.uk/pub/databases/chembl/UniChem/data/wholeSourceMapping/"
    "src_id1/src1src22.txt.gz"
)


def fetch_raw(*, force: bool = False) -> Fetched:
    return fetch(URL, "src1src22.txt.gz", source=SOURCE, min_interval=0.5, force=force)


def _lines(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        next(handle, None)  # the "From src:'1'  To src:'22'" header
        yield from handle


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    """One row per mapped pair. A half-row is not a mapping and is skipped."""
    for line in _lines(path):
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 2:
            continue
        chembl_id, cid = (part.strip() for part in parts)
        if not chembl_id or not cid:
            continue
        yield {"molecule_chembl_id": chembl_id, "pubchem_cid": cid}


def chembl_by_cid(path: Path) -> dict[str, str]:
    """CID -> ChEMBL id, for stamping a ChEMBL identity onto a PubChem result.

    Keyed on the CID side because that is the unique side of the relation. In
    the full file 25,938 ChEMBL ids (0.9%) map to more than one CID, up to 32,
    so the other way round would keep one CID per compound. No CID appears twice
    across the 2,832,793 pairs, which is what makes this dict lossless. A dict
    comprehension keeps the last of any colliding pair without complaint, so
    that claim rests on the data, and the test pins the multi-CID case.
    """
    return {row["pubchem_cid"]: row["molecule_chembl_id"] for row in normalize(path)}
