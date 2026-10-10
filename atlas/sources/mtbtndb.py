"""Conditional TnSeq across 136 published screens (MtbTnDB).

Jinich A, Zaveri A, DeJesus MA, Spencer A, Almada-Monter R, Flores-Bautista E,
Smith CM, Sassetti CM, Rock JM, Ehrt S, Schnappinger D, Ioerger TR, Rhee KY.
*The Mycobacterium tuberculosis Transposon Sequencing Database (MtbTnDB): a
large-scale guide to genetic conditional essentiality.* Mol Microbiol
2025;124(1):91-101, doi 10.1111/mmi.15370. Data: Zenodo
`10.5281/zenodo.15284946`, **CC BY 4.0**.

Griffin 2011 gave the atlas one condition. This gives it thirteen studies'
worth: hypoxia, acid, nitrosative stress, iron and amino-acid starvation,
clinical isolates, mouse infection, and drug exposure.

This reads the **raw TRANSIT resampling output**, not the processed table in the
authors' GitHub repository, for two reasons. The repository has no LICENSE file
(its README claims MIT and links to a 404). And -- the reason that would stand
even if it did -- the processed table keeps only `log2FC` and `q-val`, which
cannot tell "measured, no effect" from "no insertions, nothing to measure". In
the Griffin comparison 534 of 3,990 genes have zero insertions in both
conditions, and every one reads exactly `log2FC 0.00, q 1.00000`. TRANSIT's
output carries `Sum Ctrl` and `Sum Exp`, so `measured` here is a fact rather
than a guess.

**The trap this source cannot fix, and every surface must state.** TRANSIT
counts TA sites across the whole ORF. Griffin counted them in 5-80% of the ORF,
excluding the termini, where an insertion is least likely to disrupt function:
over the 3,917 genes both cover, the median ratio of TRANSIT sites to Griffin
sites is 1.333, exactly 1/0.75. So a gene can take insertions only at its ends,
be unmeasurable in the sense that matters, and still carry a fold change here.
`dprE1` (+0.37) and `mmpL3` (-1.67) on cholesterol are both that case, against
`n/a` in Griffin's own table. Fixing it needs insertion positions and the
deposit ships no `.wig` files, so a value is carried with `measured` and the
gene's essentiality call beside it, never alone.

**Why 136 screens and not 1,969.** 1,833 of the archive's comparisons set one
mouse strain against another, from Smith 2020's Collaborative Cross and BXD
panels. That is a host-genetics question, not "is this gene required under
condition X", so they are skipped -- stated here because an absence in this
atlas is supposed to be a decision somebody can read. The in-vivo screens that
remain are the 61 comparing a mouse strain to the shared in-vitro reference
library. Screen counts are still not evidence weight: group by `study`.

Each row keeps both sides' source study, because 76 of the 136 take their
control library from a different study than their experimental data, and the
paper's own Fig S1 is about batch effects between screens.
"""

from __future__ import annotations

import math
import re
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet

SOURCE = "mtbtndb"
CITATION = "Jinich et al. 2025 Mol Microbiol 124(1):91-101"
DATA_DOI = "10.5281/zenodo.15284946"
# The concept record, which always points at the newest deposit. `atlas check`
# reads this; the ingester deliberately does not, so a download stays
# reproducible instead of silently following a new release.
CONCEPT_ID = "13937393"
# The versioned DOI, not the concept DOI: the concept DOI always resolves to the
# newest deposit, which would make this stamp drift under a file that has not
# changed.
SOURCE_VERSION = f"Zenodo {DATA_DOI} (2025-04-20), via {CITATION}"
URL = "https://zenodo.org/records/15284946/files/transit_outputs_mtbtndb.tar.gz?download=1"

# The screen annotation -- condition, medium, stress, mouse strain, source paper
# -- is not in the Zenodo deposit. It lives in the authors' repository, which
# carries no LICENSE file, so the basis for using it is the paper's own CC BY
# 4.0 plus the fact that it is a compilation of facts about published
# experiments. The URL is pinned to **the commit the paper's Methods cites**,
# not `master`, which is both reproducible and the revision the article refers
# to -- the two differ. Nothing from it is redistributed: `data/raw/` is
# gitignored, exactly as for Mycobrowser.
PAPER_COMMIT = "a2f223042a40d01f3188e1f7465b7b1eccaffb43"
ANNOTATION_URL = (
    f"https://raw.githubusercontent.com/ajinich/mtb_tn_db/{PAPER_COMMIT}/data/col_desc_dash.tsv"
)
ANNOTATION_VERSION = f"mtb_tn_db@{PAPER_COMMIT[:12]}/data/col_desc_dash.tsv, via {CITATION}"

# col_desc_dash.tsv spelling -> the column this atlas writes. The rest of its 18
# columns are either already derived from the wig lists (replicate counts) or
# constant for everything here (`Microarray or TnSeq` is TnSeq for all 64, since
# a microarray screen has no TRANSIT output to begin with).
ANNOTATION_COLUMNS = {
    "meaning": "description",
    "paper_title": "paper_title",
    "paper_URL": "paper_url",
    "in vitro/cell/in vivo": "condition_class",
    "in vitro media": "medium",
    "carbon source": "carbon_source",
    "stress": "stress",
    "mouse strain": "mouse_strain",
    "Mtb strain": "mtb_strain",
    "GI_RvID": "interaction_gene",
    "GI_name": "interaction_gene_name",
}

MEMBER = re.compile(r"^Results/result_resampling_(?P<screen>.+)\.txt$")
# TRANSIT writes the input file list through Python's bytes repr, so the b'...'
# is in the file itself, not an artefact of reading it.
WIG_LINE = re.compile(r"^#(?P<side>Control|Experimental) Data: b'(?P<files>.*)'\s*$")

# The host-genetics panel. A comparison with this study on *both* sides is one
# mouse strain against another; the same study against the reference library is
# "is this gene required in this mouse", which the atlas does want.
HOST_PANEL = "2020_Smith"


def fetch_raw(*, force: bool = False) -> Fetched:
    # ponytail: fetch() buffers the whole body, so this peaks at ~267 MB of RAM.
    # Cached after the first run; stream it if a larger deposit ever shows up.
    return fetch(
        URL,
        "transit_outputs_mtbtndb.tar.gz",
        source=SOURCE,
        min_interval=1.0,
        timeout=900.0,
        force=force,
    )


def fetch_annotation(*, force: bool = False) -> Fetched:
    return fetch(ANNOTATION_URL, "col_desc_dash.tsv", source=SOURCE, min_interval=1.0, force=force)


def _blank(value: str | None) -> str | None:
    """The table writes a missing cell as empty or as `-`."""
    text = (value or "").strip()
    return text or None if text != "-" else None


def annotation(path: Path) -> dict[str, dict[str, str | None]]:
    """Screen id -> the authors' own description of what that screen was.

    Keyed on `column_ID_std`, which is the same slug the archive names its
    files with -- for 64 of the 136 screens. The authors' table calls the
    host-panel screens `<strain>_vs_in_vitro` while the archive calls them
    `<strain>_vs_mbio_H37Rv`, and no file in the archive uses the former. They
    are very likely the same comparison, but "very likely" is an inference, so
    those screens are left unannotated rather than matched by guesswork.
    """
    import csv

    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return {
        row["column_ID_std"]: {out: _blank(row.get(src)) for src, out in ANNOTATION_COLUMNS.items()}
        for row in rows
        if (row.get("column_ID_std") or "").strip()
    }


def _locus(tag: str) -> str | None:
    """The archive ships two annotations, and only one of them says `Rv`.

    Most screens were resampled against `H37Rv.prot_table` and key genes as
    `Rv0206c`. Eight -- Xu's drug-exposure series and Nambi 2015 -- used
    `H37RvBD.prot_table` and key them as `RVBD_0206c`. The `c` suffix survives,
    so this is a prefix swap, the same one Bosch 2021 needs without the
    underscore. Returns None for anything else, which drops the RNA features the
    larger annotation carries.
    """
    if tag.startswith("RVBD_"):
        return f"Rv{tag[5:]}"
    return tag if tag.startswith("Rv") else None


def _number(value: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _studies(header: list[str]) -> tuple[str | None, str | None, int, int]:
    """Which study each side's reads came from, and how many replicates.

    The study is the directory the `.wig` files sit in -- the authors' own
    naming (`2011_Griffin`, `2020_Smith`), so it is attribution rather than a
    label this atlas invented.
    """
    found: dict[str, tuple[str | None, int]] = {}
    for line in header:
        match = WIG_LINE.match(line)
        if not match:
            continue
        files = [f for f in match["files"].split(",") if f]
        study = files[0].split("/")[0] if files and "/" in files[0] else None
        found[match["side"]] = (study, len(files))
    experimental, n_experimental = found.get("Experimental", (None, 0))
    control, n_control = found.get("Control", (None, 0))
    return experimental, control, n_experimental, n_control


def _meta(header: list[str], screen: str) -> dict[str, Any] | None:
    """One screen's identity, or None if it is one the atlas deliberately skips."""
    study, control_study, n_replicates, n_control = _studies(header)
    if study == HOST_PANEL and control_study == HOST_PANEL:
        return None
    experimental, _, control = screen.partition("_vs_")
    return {
        "screen_id": screen,
        "experimental": experimental,
        "control": control or None,
        "study": study,
        "control_study": control_study,
        # The control library comes from another study in 76 of the 136.
        "cross_study": study is not None and control_study is not None and study != control_study,
        "n_replicates": n_replicates,
        "n_replicates_control": n_control,
    }


def _screen(raw: bytes, screen: str) -> list[dict[str, Any]] | None:
    """Gene rows for one screen, or None if it is one the atlas skips.

    None and `[]` mean different things on purpose: `normalize` raises on the
    empty list, because a screen that parses to nothing is a format change, not
    a result. That is how the `RVBD_` annotation was found -- eight screens had
    been dropping silently.
    """
    text = raw.decode("utf-8", errors="replace").splitlines()
    header = [line for line in text if line.startswith("#")]
    if _meta(header, screen) is None:
        return None

    rows = []
    for line in text:
        if line.startswith("#") or not line.strip():
            continue
        field = line.split("\t")
        if len(field) < 12:
            continue
        rv_id = _locus(field[0])
        if rv_id is None:
            continue
        sum_control = _number(field[7])
        sum_experimental = _number(field[8])
        rows.append(
            {
                "rv_id": rv_id,
                "gene_name": field[1] if field[1] not in ("", "-") else None,
                "screen_id": screen,
                "n_ta_sites": _number(field[3]),
                "mean_control": _number(field[4]),
                "mean_experimental": _number(field[5]),
                "sum_control": sum_control,
                "sum_experimental": sum_experimental,
                "log2fc": _number(field[6]),
                "delta_mean": _number(field[9]),
                "p_value": _number(field[10]),
                "q_value": _number(field[11]),
                # The whole reason this source is read raw. A gene with no
                # insertions in either condition has nothing to compare, and
                # TRANSIT still reports log2FC 0.00 / q 1.00 for it.
                "measured": bool((sum_control or 0) > 0 or (sum_experimental or 0) > 0),
                "citation": CITATION,
            }
        )
    return rows


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    """One row per gene per screen, skipping the strain-against-strain panel."""
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            match = MEMBER.match(member.name)
            if not match or not member.isfile():
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            rows = _screen(handle.read(), match["screen"])
            if rows is None:
                continue
            if not rows:
                raise ValueError(f"{match['screen']}: parsed no genes -- the format changed")
            yield from rows


def screens(path: Path, described: dict[str, dict[str, str | None]]) -> Iterator[dict[str, Any]]:
    """One row per screen: what was compared to what, and what that was.

    A second pass over the archive rather than threading two row shapes through
    one. Decompressing it twice costs seconds and keeps both passes readable.
    """
    blank = dict.fromkeys(ANNOTATION_COLUMNS.values())
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            match = MEMBER.match(member.name)
            if not match or not member.isfile():
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            header = [
                line
                for line in handle.read().decode("utf-8", errors="replace").splitlines()
                if line.startswith("#")
            ]
            meta = _meta(header, match["screen"])
            if meta is None:
                continue
            found = described.get(match["screen"])
            yield {
                **meta,
                **(found or blank),
                # False means the authors' table does not name this screen, so
                # nothing here describes its condition. It is not "in vitro".
                "annotated": found is not None,
                "citation": CITATION,
            }


def build(*, force: bool = False) -> list[Path]:
    raw = fetch_raw(force=force)
    described = annotation(fetch_annotation(force=force).path)
    genes = write_parquet(
        "conditional_tnseq",
        normalize(raw.path),
        source=SOURCE,
        source_version=SOURCE_VERSION,
        retrieved_at=raw.retrieved_at,
    )
    described_version = f"{SOURCE_VERSION}; annotation {ANNOTATION_VERSION}"
    return [
        genes,
        write_parquet(
            "tnseq_screens",
            screens(raw.path, described),
            source=SOURCE,
            source_version=described_version,
            retrieved_at=raw.retrieved_at,
        ),
    ]
