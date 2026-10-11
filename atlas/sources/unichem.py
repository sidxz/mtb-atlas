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


HEADER = "From src:'1'\tTo src:'22'"


def _lines(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        # The first line is skipped as a header, so a file that lacks one would
        # lose its first pair silently. Both columns are checked, so a swapped
        # src order is refused here rather than caught later as a collision.
        header = next(handle, "").rstrip("\n")
        if header != HEADER:
            raise ValueError(
                f"UniChem header is {header!r}, not {HEADER!r}. Refusing to read a file "
                "whose first line is not the header, since that line would be dropped."
            )
        yield from handle


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    """One row per mapped pair. A line that is not a mapping is skipped.

    Two checks for two shapes. The length check catches a line that is not two
    fields: without it the unpack below raises and aborts the build. The emptiness
    check catches two fields with one side blank: without it that line would map
    an empty string to a compound, a silent corruption rather than a crash.
    """
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
    across the 2,832,793 pairs, which is what makes this dict lossless. A CID
    that does map to two ChEMBL ids raises, rather than keeping one of them: that
    uniqueness is asserted here, not assumed.
    """
    out: dict[str, str] = {}
    for row in normalize(path):
        cid, chembl_id = row["pubchem_cid"], row["molecule_chembl_id"]
        seen = out.get(cid)
        if seen is not None and seen != chembl_id:
            raise ValueError(
                f"CID {cid} maps to both {seen} and {chembl_id} in UniChem. The bridge "
                "is keyed on CID, so keeping either would attribute one compound's "
                "screens to the other."
            )
        out[cid] = chembl_id
    return out
