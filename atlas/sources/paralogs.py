"""Functional redundancy: does Mtb carry a second copy of this target?

An essential, vulnerable, structurally tractable gene with a close paralog is a
different proposition from the same gene standing alone. Inhibit one copy and
the other may cover for it -- and the compound then looks inactive for a reason
that has nothing to do with the chemistry. It is the first thing to check after
essentiality, and nothing in the store answered it.

The crosswalk already carries the degenerate case: 55 loci whose *accession* is
shared with a sibling, which is identity collapse rather than paralogy
(`shared_accession`). This is the general case, and it is a different question
-- `Rv1180`/`Rv1181` share one accession, while a gene and its 70%-identical
duplicate have two.

No download: this is the same phmmer machinery `homology.py` uses against the
human proteome, pointed at Mtb instead, so it reuses that module's cached
proteome FASTA and adds no source. The only new decision is what counts as a
paralog, and the threshold is recorded on every row rather than baked in.

**A protein's best hit against its own proteome is itself**, at 100% identity,
so self-hits are dropped. Where two loci share an accession they are literally
the same sequence, so each would be the other's perfect "paralog"; those pairs
are dropped too, because reporting them would turn an annotation artefact into
a redundancy claim.
"""

from __future__ import annotations

import gzip
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..store import write_parquet
from .homology import (
    E_VALUE,
    MTB_PROTEOME,
    _accession,
    _descriptions,
    alignment_stats,
    fetch_raw,
)

SOURCE = "phmmer-paralog"

# Where a hit stops being "same superfamily" and starts being a second copy
# that could cover for the first. 30% matches the human-homology convention so
# the two columns mean the same thing, and the identity is shown beside the
# flag for the same reason it is there.
CLOSE_IDENTITY = 0.30

# **Redundancy additionally requires coverage, and this is where the paralog
# question parts company with the anti-target one.** For a human off-target,
# a shared site over part of the protein is already a selectivity worry, so
# `homology.py` flags on identity alone. For "can another copy do this job",
# a partial match is not enough: the second copy has to be the same protein,
# not share a domain with it.
#
# Identity alone calls 2,009 genes redundant, including dprE1 (30.8% over 37%
# of the protein) and mmpL3 (31.7% over 21%) -- both have family members, and
# neither has a backup. Requiring coverage too gives 985, keeps groEL2/groEL1
# (62% over 98%), and drops exactly the family-level links that the UniRef50
# lesson says not to trust. The median coverage among 30%-identity best hits
# is 0.68, so this threshold discriminates rather than rubber-stamps.
CLOSE_COVERAGE = 0.70


def normalize(mtb_path: Path, *, cpus: int = 0) -> Iterator[dict[str, Any]]:
    """phmmer the Mtb proteome against itself; keep the best non-self hit."""
    import pyhmmer

    alphabet = pyhmmer.easel.Alphabet.amino()
    names = _descriptions(mtb_path)

    with gzip.open(mtb_path, "rb") as handle:
        raw = handle.read()
    with pyhmmer.easel.SequenceFile(io.BytesIO(raw), digital=True, alphabet=alphabet) as reader:
        sequences = list(reader)

    # Identical sequences under two accessions are an annotation artefact, not
    # redundancy: dropping them needs the sequence, so index it once here.
    by_accession = {_accession(s.name): bytes(s.sequence) for s in sequences}

    best: dict[str, list[dict[str, Any]]] = {}
    for hits in pyhmmer.hmmer.phmmer(sequences, sequences, cpus=cpus, E=E_VALUE):
        query = _accession(hits.query.name)
        kept: list[dict[str, Any]] = []
        for hit in hits:
            if hit.evalue > E_VALUE:
                continue
            accession = _accession(hit.name)
            if accession == query:
                continue  # itself
            if by_accession.get(accession) == by_accession.get(query):
                continue  # the same sequence filed twice
            identity, coverage = alignment_stats(len(hits.query), hit)
            kept.append(
                {
                    "acc": accession,
                    "gene": names.get(accession),
                    "evalue": hit.evalue,
                    "bitscore": hit.score,
                    "identity": identity,
                    "coverage": coverage,
                }
            )
        if kept:
            best[query] = kept

    for sequence in sequences:
        accession = _accession(sequence.name)
        hits = best.get(accession, [])
        # Ranked by identity, not E-value: for "could another copy cover for
        # this one" the degree of similarity is the question, and a long weak
        # match can outscore a short strong one on E-value alone.
        # Two rankings, because the two questions want different winners.
        # The nearest *relative* goes by bitscore, phmmer's own measure, which
        # balances how similar against how much: ranking it by identity would
        # crown a 20-residue exact fragment over a full-length good match.
        hits.sort(key=lambda h: h["bitscore"], reverse=True)
        top = hits[0] if hits else None
        # The nearest *backup* must clear both floors first; among those,
        # identity is the right tiebreak, since they all span the protein.
        close = sorted(
            (
                h
                for h in hits
                if h["identity"] >= CLOSE_IDENTITY and h["coverage"] >= CLOSE_COVERAGE
            ),
            key=lambda h: h["identity"],
            reverse=True,
        )
        yield {
            "uniprot_acc": accession,
            "has_paralog": bool(hits),
            "n_paralogs": len(hits),
            # The count that matters for redundancy, as against family
            # membership. A gene with 40 distant relatives and no close one is
            # not covered for.
            "n_close_paralogs": len(close),
            "close_paralog": bool(close),
            # The closest *redundant* copy, which is not always the closest
            # relative: mmpL3's best hit is mmpL1 at 31.7% over a fifth of the
            # protein, and it has no redundant copy at all.
            "closest_close_gene": close[0]["gene"] if close else None,
            "closest_close_identity": round(close[0]["identity"], 4) if close else None,
            "closest_acc": top["acc"] if top else None,
            "closest_gene": top["gene"] if top else None,
            "closest_identity": round(top["identity"], 4) if top else None,
            "closest_coverage": round(top["coverage"], 4) if top else None,
            "closest_evalue": top["evalue"] if top else None,
            "closest_bitscore": top["bitscore"] if top else None,
            "paralog_accs": [h["acc"] for h in hits],
        }


def build(*, retrieved_at: str | None = None, force: bool = False) -> Path:
    mtb, _ = fetch_raw(force=force)
    return write_parquet(
        "paralogs",
        normalize(mtb.path),
        source=SOURCE,
        source_version=(
            f"phmmer (pyhmmer) {MTB_PROTEOME} vs itself, "
            f"E <= {E_VALUE:g}, close >= {CLOSE_IDENTITY:.0%} identity "
            f"over >= {CLOSE_COVERAGE:.0%} of the query"
        ),
        retrieved_at=retrieved_at or mtb.retrieved_at,
    )
