"""Human homology: the anti-target check, computed rather than looked up.

A target whose closest relative sits in the human proteome is a selectivity
problem before it is anything else, so this is among the first things a target
biologist asks. **No public resource publishes the answer for Mtb in a form
that can be downloaded**: UniProt exposes no orthology field, OrthoDB's bulk
files are 1.8 GB, eggNOG's are ~1 GB, and InParanoiDB's download is a
CSRF-protected form that returns HTML.

UniRef co-membership was tried first and abandoned, which is worth recording
because it looks like it should work: four bulk ID-mapping jobs, no local
tooling, and the answer came back **zero human homologs across all 3,978
accessions**. That is not a finding, it is the wrong instrument. UniRef50
clusters at 50% identity to the representative, and Mtb-human homology mostly
lives at 25-40% -- even GroEL2 (P9WPE7) and human HSPD1 (P10809), textbook
homologs, land in different UniRef50 clusters. A column that says "no" to every
gene is worse than no column, because it reads as reassurance.

So this searches properly, with phmmer via pyhmmer: each Mtb protein against
the reviewed human proteome, keeping the best hit with its E-value and percent
identity. Both proteomes are UniProt (CC BY 4.0). ~4,000 x 20,000 takes a few
minutes on one machine and needs no system package.
"""

from __future__ import annotations

import gzip
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet

SOURCE = "phmmer-human"
MTB_PROTEOME = "UP000001584"
HUMAN_PROTEOME = "UP000005640"
STREAM = "https://rest.uniprot.org/uniprotkb/stream"
MTB_FASTA = f"{STREAM}?query=proteome:{MTB_PROTEOME}&format=fasta&compressed=true"
# Reviewed only: the unreviewed human proteome is largely isoforms and fragments,
# which inflates hit counts without adding an anti-target the chemist cares about.
HUMAN_FASTA = (
    f"{STREAM}?query=proteome:{HUMAN_PROTEOME}+AND+reviewed:true&format=fasta&compressed=true"
)

# phmmer's own reporting threshold. Anything weaker is not a selectivity concern
# worth surfacing, and loosening it floods the table with coincidental hits.
E_VALUE = 1e-5
# Where a hit stops being "distant relative" and starts being a real liability.
# Not a hard line in biology; it is the line this atlas draws, and it is shown.
CLOSE_IDENTITY = 0.30


def fetch_raw(*, force: bool = False) -> tuple[Fetched, Fetched]:
    mtb = fetch(MTB_FASTA, "mtb.fasta.gz", source=SOURCE, min_interval=0.5, force=force)
    human = fetch(
        HUMAN_FASTA, "human-reviewed.fasta.gz", source=SOURCE, min_interval=0.5, force=force
    )
    return mtb, human


def _accession(name: str | bytes) -> str:
    """`sp|P9WJF1|DPRE1_MYCTU` -> `P9WJF1`. pyhmmer returns str or bytes by version."""
    text = name.decode() if isinstance(name, bytes) else name
    parts = text.split("|")
    return parts[1] if len(parts) > 2 else text


def alignment_stats(query_length: int, hit: Any) -> tuple[float, float]:
    """Percent identity and query coverage for a phmmer hit.

    phmmer reports an alignment, not an identity, so this computes it from the
    aligned columns -- the number a chemist expects when they ask "how similar".
    Shared with `paralogs.py` so the two columns mean the same thing.

    Coverage is clamped to 1.0. pyhmmer's alignment can report marginally more
    aligned columns than the query has residues, which left 45 human hits at up
    to 1.07; a protein cannot be more than fully covered, and the number now
    gates a flag rather than only being displayed.
    """
    alignment = hit.best_domain.alignment
    pairs = list(zip(alignment.target_sequence, alignment.hmm_sequence, strict=False))
    matched = sum(1 for t, q in pairs if t.upper() == q.upper() and t != "-")
    aligned = sum(1 for t, q in pairs if t != "-" and q != "-")
    identity = matched / aligned if aligned else 0.0
    coverage = min(aligned / query_length, 1.0) if query_length else 0.0
    return identity, coverage


def _descriptions(path: Path) -> dict[str, str]:
    """Accession -> the protein name in the FASTA header, for naming the hit."""
    out: dict[str, str] = {}
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith(">"):
                continue
            header = line[1:].strip()
            name, _, rest = header.partition(" ")
            description = rest.split(" OS=")[0]
            gene = ""
            if " GN=" in rest:
                gene = rest.split(" GN=")[1].split(" ")[0]
            out[_accession(name)] = gene or description
    return out


def normalize(mtb_path: Path, human_path: Path, *, cpus: int = 0) -> Iterator[dict[str, Any]]:
    """phmmer every Mtb protein against the human proteome; keep the best hit."""
    import pyhmmer

    alphabet = pyhmmer.easel.Alphabet.amino()
    human_names = _descriptions(human_path)

    def sequences(path: Path) -> list[pyhmmer.easel.DigitalSequence]:
        with gzip.open(path, "rb") as handle:
            raw = handle.read()
        with pyhmmer.easel.SequenceFile(io.BytesIO(raw), digital=True, alphabet=alphabet) as reader:
            return list(reader)

    queries = sequences(mtb_path)
    targets = sequences(human_path)

    best: dict[str, dict[str, Any]] = {}
    for hits in pyhmmer.hmmer.phmmer(queries, targets, cpus=cpus, E=E_VALUE):
        query = _accession(hits.query.name)
        for hit in hits:
            if hit.evalue > E_VALUE:
                continue
            identity, coverage = alignment_stats(len(hits.query), hit)
            current = best.get(query)
            if current is None or hit.evalue < current["evalue"]:
                accession = _accession(hit.name)
                best[query] = {
                    "evalue": hit.evalue,
                    "bitscore": hit.score,
                    "identity": identity,
                    "coverage": coverage,
                    "human_acc": accession,
                    "human_gene": human_names.get(accession),
                }
            break  # hits are ranked, so the first is the best

    for sequence in queries:
        accession = _accession(sequence.name)
        hit = best.get(accession)
        yield {
            "uniprot_acc": accession,
            "human_homolog": hit is not None,
            "human_acc": hit["human_acc"] if hit else None,
            "human_gene": hit["human_gene"] if hit else None,
            "evalue": hit["evalue"] if hit else None,
            "bitscore": hit["bitscore"] if hit else None,
            "identity": round(hit["identity"], 4) if hit else None,
            "coverage": round(hit["coverage"], 4) if hit else None,
            # The flag a target team actually filters on. The threshold is this
            # atlas's choice, not a fact, which is why the identity is shown too.
            "close_human_homolog": bool(hit and hit["identity"] >= CLOSE_IDENTITY),
        }


def build(*, retrieved_at: str | None = None, force: bool = False) -> Path:
    mtb, human = fetch_raw(force=force)
    return write_parquet(
        "homology",
        normalize(mtb.path, human.path),
        source=SOURCE,
        source_version=(
            f"phmmer (pyhmmer) {MTB_PROTEOME} vs reviewed {HUMAN_PROTEOME}, "
            f"E <= {E_VALUE:g}, close >= {CLOSE_IDENTITY:.0%} identity"
        ),
        retrieved_at=retrieved_at or mtb.retrieved_at,
    )
