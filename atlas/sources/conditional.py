"""Conditional fitness: which genes matter on cholesterol, not just in broth.

Griffin JE, Gawronski JD, DeJesus MA, Ioerger TR, Akerley BJ, Sassetti CM.
*High-resolution phenotypic profiling defines genes essential for mycobacterial
growth and cholesterol catabolism.* PLoS Pathog 2011;7(9):e1002251.
PMC3182942, doi 10.1371/journal.ppat.1002251. **CC BY** (confirmed through
Europe PMC's `license` field).

This is the first answer in the atlas to "essential *under which conditions*".
DeJesus 2017 is one condition -- 7H9 broth -- and the caveat has been on every
essentiality number since. Cholesterol is the carbon source M. tuberculosis
lives on inside a macrophage, so a gene required on cholesterol and not on
glycerol is a gene the broth screen cannot see.

**What this does not measure, and it matters.** A transposon screen compares
insertion counts between conditions, and a gene that tolerates no insertions at
all has nothing to compare. Every in-vitro-essential gene is such a gene:
dprE1, inhA, mmpL3 and katG all come back `n/a` here. That is recorded as
`measured = false`, never as "no effect" -- the same structural blind spot
docs/data-sources.md records for MtbTnDB.

**The flag is the authors' own.** Table S4 is their list of 96 genes
specifically required for growth on cholesterol. The atlas carries that rather
than drawing its own line through the ratio, for the same reason it carries
Bosch's `certain` flag.
"""

from __future__ import annotations

import io
import math
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet

SOURCE = "griffin-2011"
CITATION = "Griffin et al. 2011 PLoS Pathog 7(9):e1002251, Table S3"
CONDITION = "cholesterol vs glycerol, in vitro"
# The `Required in vivo` column is not this paper's own measurement; it is
# carried from an earlier mouse screen, and is attributed as such.
IN_VIVO_CITATION = "Sassetti & Rubin 2003 PNAS 100:12989-12994, via Griffin 2011 Table S3"

# PMC's own supplementary path returns an HTML interstitial to scripted
# requests; Europe PMC serves the files as one zip. Same route as DeJesus 2017.
URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3182942/supplementaryFiles"

DIFFERENTIAL = "ppat.1002251.s003.xlsx"  # Table S3: every gene, both carbon sources
CALLED = "ppat.1002251.s004.xlsx"  # Table S4: the 96 the authors call
# Both tables open with a title and a legend; the column names are the last
# header row before the data, and Table S3 spreads its names over two rows.
DIFFERENTIAL_HEADER = 9
CALLED_HEADER = 7


def fetch_raw(*, force: bool = False) -> Fetched:
    return fetch(URL, "griffin-2011-supplement.zip", source=SOURCE, min_interval=1.0, force=force)


def _number(value: Any) -> float | None:
    """`n/a` is how this table says "no insertions to compare", so it is None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sheet(archive: zipfile.ZipFile, member: str, header: int) -> list[tuple]:
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(archive.read(member)), read_only=True, data_only=True)
    rows = list(book[book.sheetnames[0]].iter_rows(values_only=True))
    return [row for row in rows[header:] if row and str(row[0] or "").startswith("Rv")]


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    """One row per gene, with the ratio where there was one to compute."""
    with zipfile.ZipFile(path) as archive:
        called = {str(row[0]) for row in _sheet(archive, CALLED, CALLED_HEADER)}
        for row in _sheet(archive, DIFFERENTIAL, DIFFERENTIAL_HEADER):
            ratio = _number(row[16])
            yield {
                "rv_id": str(row[0]),
                "gene_name": row[1] if row[1] not in (None, "-") else None,
                "condition": CONDITION,
                "reference": "glycerol",
                "ratio": ratio,
                # Log2 so it reads like every other fitness scale: negative is
                # depleted on cholesterol.
                "log2_ratio": math.log2(ratio) if ratio else None,
                "p_value": _number(row[17]),
                # False where the gene took no insertions in either condition.
                "measured": ratio is not None,
                "n_ta_sites": _number(row[2]),
                "n_sites_hit": _number(row[3]),
                "cholesterol_required": str(row[0]) in called,
                "required_in_vivo": str(row[18] or "").strip().lower() == "yes",
                "in_vivo_citation": IN_VIVO_CITATION,
                "citation": CITATION,
            }


def build(*, force: bool = False) -> Path:
    raw = fetch_raw(force=force)
    return write_parquet(
        "conditional_fitness",
        normalize(raw.path),
        source=SOURCE,
        source_version=CITATION,
        retrieved_at=raw.retrieved_at,
    )
