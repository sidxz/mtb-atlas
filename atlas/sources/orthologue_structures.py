"""Is there a structure to work from, even if not of this protein?

3,094 of 3,978 Mtb accessions have no experimental structure, and the atlas
reports that as the absence it is. But "no structure" and "nothing to work
from" are different claims, and MmpL3 is the standing example of the gap: one
Mtb entry at 3.0 A against four *M. smegmatis* MmpL3 structures, one of which
carries an inhibitor. The ChEMBL orthologue bridge already reaches that
protein (`orthologue.py`, via UniRef50_A0QP27) for its ligands; its structures
were invisible, because `structures` is keyed on the Mtb accession and nothing
mapped the neighbour back.

Two different findings come out of one search, and they must not be flattened:

* **`same_sequence`** -- the deposited sequence is *identical* to the Mtb one,
  filed under another accession. 36 genes the atlas calls structure-less have a
  100%-identical structure deposited against a CDC 1551, H37Ra or *M. bovis*
  accession. That is not a model of the target, it is the target, and the only
  reason it was missing is the key.
* **`orthologue`** -- a related mycobacterial protein, with the identity and
  coverage that produced the link on every row. A judgement about what can be
  done with a 34%-identical structure belongs to the person reading it, so the
  numbers travel with the row and no modelling claim is made here.

**This does not touch `n_pdb`, `has_structure` or `structural_gap`.** Those
count structures of the gene's own protein and must keep meaning that; a
borrowed structure sits in its own columns beside them.

Why phmmer rather than the UniRef bridge `orthologue.py` uses: UniRef gives
co-membership, not a number, and this atlas has already recorded what that is
worth -- MmpL3's UniRef50 cluster holds 611 members. UniRef membership is also
unreachable in bulk (the API truncates the member list at ten, and UniProtKB
publishes no cluster field), so the cheap route would have been ~1,800
per-accession requests. The homology machinery was already here: the target set
is only the 895 Mycobacteriaceae proteins that have a PDB entry, so one
download and 6 s of phmmer give identity *and* coverage for every pair.

Licence: UniProt CC BY 4.0 for the sequences, RCSB CC0 1.0 for the entries.
"""

from __future__ import annotations

import gzip
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet
from . import homology, pdb
from .homology import E_VALUE, MTB_PROTEOME, _accession, alignment_stats

SOURCE = "orthologue-pdb"

# Mycobacteriaceae, less H37Rv itself -- the same scoping as the ChEMBL
# orthologue bridge, so "orthologue" means the same thing in both columns.
# `database:pdb` does the filtering upstream: there is no point phmmering
# against a neighbour whose structure nobody has solved.
MYCOBACTERIACEAE = 1762
H37RV = 83332
HOSTS_FASTA = (
    f"{homology.STREAM}?query=(taxonomy_id:{MYCOBACTERIACEAE})+AND+(database:pdb)"
    f"+NOT+(taxonomy_id:{H37RV})&format=fasta&compressed=true"
)

# Where this stops listing. The pair matches the paralog floor, because the
# question has the same shape -- a structure is only worth borrowing if it is
# of the same protein, not of something that shares a domain -- and 30% is also
# the convention for a usable homology model. Both numbers are on every row, so
# a team that wants a stricter line can draw it.
MIN_IDENTITY = 0.30
MIN_COVERAGE = 0.70

# A perfect match can still be the wrong protein. `O07717` (398 aa) aligns at
# 100% identity over its whole length inside `Q8VJU4` (766 aa), which is a
# different protein that contains it; 3 of 165 perfect pairs look like this.
# When coverage is already 1.0 the query/target length ratio *is* the target's
# coverage, so this is the same measurement from the other end, not a new rule.
SAME_SEQUENCE_LENGTH_RATIO = 0.80


def fetch_raw(*, force: bool = False) -> Fetched:
    """The neighbours worth searching: Mycobacteriaceae proteins with a PDB entry."""
    return fetch(
        HOSTS_FASTA, "mycobacteriaceae-pdb.fasta.gz", source=SOURCE, min_interval=0.5, force=force
    )


def _hosts(path: Path) -> dict[str, dict[str, Any]]:
    """Accession -> organism, taxon and gene, read off the FASTA headers.

    The header carries everything the TSV stream would have, so this is one
    download rather than two: `OS=` to ` OX=` is the organism (strain names
    hold spaces, slashes and brackets, so it cannot be split on whitespace).
    """
    out: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith(">"):
                continue
            name, _, rest = line[1:].strip().partition(" ")
            organism, _, after = rest.partition("OS=")
            organism, _, taxon_part = after.partition(" OX=")
            taxon = taxon_part.split(" ")[0] if taxon_part else ""
            gene = rest.split(" GN=")[1].split(" ")[0] if " GN=" in rest else None
            out[_accession(name)] = {
                "via_gene": gene,
                "via_organism": organism.strip() or None,
                "via_taxon": taxon or None,
            }
    return out


def bridge(mtb_path: Path, hosts_path: Path, *, cpus: int = 0) -> list[dict[str, Any]]:
    """Every (Mtb protein, neighbour with a structure) pair above the floor."""
    import pyhmmer

    alphabet = pyhmmer.easel.Alphabet.amino()
    hosts = _hosts(hosts_path)

    def sequences(path: Path) -> list[Any]:
        with gzip.open(path, "rb") as handle:
            raw = handle.read()
        with pyhmmer.easel.SequenceFile(io.BytesIO(raw), digital=True, alphabet=alphabet) as reader:
            return list(reader)

    queries = sequences(mtb_path)
    targets = sequences(hosts_path)
    lengths = {_accession(s.name): len(s.sequence) for s in targets}

    pairs: list[dict[str, Any]] = []
    for hits in pyhmmer.hmmer.phmmer(queries, targets, cpus=cpus, E=E_VALUE):
        query = _accession(hits.query.name)
        query_length = len(hits.query)
        for hit in hits:
            if hit.evalue > E_VALUE:
                continue
            accession = _accession(hit.name)
            if accession not in hosts:
                continue
            identity, coverage = alignment_stats(query_length, hit)
            if identity < MIN_IDENTITY or coverage < MIN_COVERAGE:
                continue
            target_length = lengths.get(accession) or 0
            ratio = query_length / target_length if target_length else 0.0
            same = identity >= 1.0 and coverage >= 1.0 and ratio >= SAME_SEQUENCE_LENGTH_RATIO
            pairs.append(
                {
                    "uniprot_acc": query,
                    "via_acc": accession,
                    **hosts[accession],
                    "via_length": target_length or None,
                    # The claim this row makes, and the two claims are not the
                    # same strength: one is the protein, the other is a relative.
                    "relation": "same_sequence" if same else "orthologue",
                    "identity": round(identity, 4),
                    "coverage": round(coverage, 4),
                    "evalue": hit.evalue,
                    "bitscore": hit.score,
                }
            )
    return pairs


def normalize(
    pairs: list[dict[str, Any]], structures: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """One row per (Mtb accession, neighbour's PDB entry).

    The structure facts come from `pdb.normalize`, so a borrowed entry gets the
    same chain-level ligand attribution as an Mtb one: a ligand sitting on a
    neighbouring chain is not counted for this protein either.
    """
    by_accession: dict[str, list[dict[str, Any]]] = {}
    for structure in structures:
        by_accession.setdefault(structure["uniprot_acc"], []).append(structure)

    for pair in pairs:
        for structure in by_accession.get(pair["via_acc"], []):
            yield {
                **pair,
                "pdb_id": structure["pdb_id"],
                "title": structure["title"],
                "method": structure["method"],
                "resolution": structure["resolution"],
                "released": structure["released"],
                "entity_description": structure["entity_description"],
                "n_ligands": structure["n_ligands"],
                "ligand_ids": structure["ligand_ids"],
            }


def version_label(n_entries: int) -> str:
    """The stored `source_version`, so the freshness probe can reproduce it.

    `atlas check` has to compare against the same statement the table was
    stamped from, which here names both upstreams. The entry count is the
    moving part: RCSB releases weekly, and a neighbour's new structure is what
    this source exists to notice.
    """
    return (
        f"phmmer (pyhmmer) {MTB_PROTEOME} vs Mycobacteriaceae (taxon {MYCOBACTERIACEAE}, "
        f"not {H37RV}) with a PDB entry, E <= {E_VALUE:g}, "
        f">= {MIN_IDENTITY:.0%} identity over >= {MIN_COVERAGE:.0%} of the query; "
        f"structures from RCSB, {n_entries} entries"
    )


def build(*, retrieved_at: str | None = None, force: bool = False) -> Path:
    mtb, _ = homology.fetch_raw(force=force)
    hosts = fetch_raw(force=force)
    pairs = bridge(mtb.path, hosts.path)
    accessions = sorted({pair["via_acc"] for pair in pairs})
    entry_ids = sorted({str(eid).split("_")[0] for eid in pdb.entity_ids(accessions)})
    structures = list(pdb.normalize(pdb.entries(entry_ids), set(accessions)))
    return write_parquet(
        "orthologue_structures",
        normalize(pairs, structures),
        source=SOURCE,
        source_version=version_label(len(entry_ids)),
        retrieved_at=retrieved_at or hosts.retrieved_at,
    )
