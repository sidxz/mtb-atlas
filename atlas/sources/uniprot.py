"""UniProt reference proteome UP000001584: accessions, cross-references, biology.

This is the source of truth for Rv tag -> UniProt accession, and for the PDB,
ChEMBL and AlphaFold cross-references hanging off each accession. The same
stream carries the curated biology a target page leads with -- function,
location, membrane topology, pathway, catalysis, cofactors, GO terms, the
disruption phenotype and the papers UniProt cites. Licence: CC BY 4.0.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet

SOURCE = "uniprot"
PROTEOME = "UP000001584"
# Domains come free in the same stream. The alternative is InterPro's
# protein2ipr.dat.gz, which is 13.3 GB for the same 3,997 answers. So does the
# curated biology a target page needs: function, location, membrane topology,
# pathway, catalysis, cofactors, GO term names and the papers UniProt cites.
FIELDS = (
    "accession,id,reviewed,gene_oln,gene_primary,gene_synonym,protein_name,"
    "length,xref_pdb,xref_chembl,xref_alphafolddb,xref_interpro,xref_pfam,"
    "go_id,ec,cc_function,cc_subcellular_location,ft_transmem,ft_signal,cc_pathway,"
    "cc_catalytic_activity,cc_cofactor,go_p,go_f,go_c,cc_disruption_phenotype,"
    "lit_pubmed_id,protein_existence,annotation_score"
)
URL = (
    f"https://rest.uniprot.org/uniprotkb/stream?query=proteome:{PROTEOME}"
    f"&format=tsv&fields={FIELDS}"
)

# Locus tags in `gene_oln` are not one-per-entry and not uniformly shaped. Real
# values in this proteome include "Rv3790", "Rv0206c", "Rv0236A", "Rv3423.1",
# "Rv1706c.1", "Rv2922.1c", "Rv1180/Rv1181" and a 16-tag semicolon list for the
# IS6110 transposase. Splitting on whitespace is not enough, so match the tags
# directly; this also skips the "RVBD_0846c" aliases, which are not Rv tags.
RV_TAG = re.compile(r"Rv\d{4}[A-Z]?c?(?:\.\d+c?)?")


def rv_tags(gene_oln: str) -> list[str]:
    """Every Rv locus tag mentioned in a UniProt `gene_oln` field, in order."""
    return list(dict.fromkeys(RV_TAG.findall(gene_oln)))


def _ids(field: str) -> list[str]:
    return [x.strip() for x in field.split(";") if x.strip()]


# UniProt prefixes every comment ("FUNCTION: ") and tags claims with evidence
# codes ("{ECO:0000269|PubMed:25906160}"). A page wants the prose; the citations
# written into it ("(PubMed:16291675)") stay.
_ECO = re.compile(r"\s*\{ECO:[^}]*\}")
_GO_ID = re.compile(r"\s*\[GO:\d+\]")


def _comments(field: str, prefix: str) -> list[str]:
    """`PATHWAY: a. {ECO:..}. PATHWAY: b.` -> ["a", "b"]. Empty field, empty list."""
    text = _ECO.sub("", field or "")
    return [part.strip().rstrip(".").strip() for part in text.split(f"{prefix}:") if part.strip()]


def _comment(field: str, prefix: str) -> str | None:
    # None, not "", so an entry UniProt says nothing about reads as an absence.
    parts = _comments(field, prefix)
    return ". ".join(parts) + "." if parts else None


def _locations(field: str) -> list[str]:
    """`Cell inner membrane; Multi-pass membrane protein. Cell tip. Note=...` -> terms."""
    text = (_comment(field, "SUBCELLULAR LOCATION") or "").split("Note=")[0]
    terms = (t.strip() for t in re.split(r"[.;]", text))
    return list(dict.fromkeys(t for t in terms if t))


def fetch_raw(*, force: bool = False) -> Fetched:
    return fetch(URL, f"{PROTEOME}.tsv", source=SOURCE, min_interval=0.5, force=force)


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            yield {
                "uniprot_acc": row["Entry"],
                "entry_name": row["Entry Name"],
                "reviewed": row["Reviewed"] == "reviewed",
                "rv_ids": rv_tags(row["Gene Names (ordered locus)"]),
                "gene_primary": row["Gene Names (primary)"] or None,
                "gene_synonyms": [g for g in row["Gene Names (synonym)"].split() if g],
                "protein_name": row["Protein names"],
                "length": int(row["Length"]),
                "pdb_ids": _ids(row["PDB"]),
                "chembl_target_ids": _ids(row["ChEMBL"]),
                "alphafold_ids": _ids(row["AlphaFoldDB"]),
                "interpro_ids": _ids(row["InterPro"]),
                "pfam_ids": _ids(row["Pfam"]),
                "go_ids": _ids(row["Gene Ontology IDs"]),
                "ec_numbers": [e.strip() for e in row["EC number"].split(";") if e.strip()],
                "function": _comment(row["Function [CC]"], "FUNCTION"),
                "subcellular_location": _comment(
                    row["Subcellular location [CC]"], "SUBCELLULAR LOCATION"
                ),
                "locations": _locations(row["Subcellular location [CC]"]),
                "n_transmembrane": row["Transmembrane"].count("TRANSMEM "),
                "signal_peptide": "SIGNAL " in row["Signal peptide"],
                "pathways": _comments(row["Pathway"], "PATHWAY"),
                "reactions": [
                    r.strip() for r in re.findall(r"Reaction=([^;]+);", row["Catalytic activity"])
                ],
                "rhea_ids": sorted(set(re.findall(r"Rhea:(RHEA:\d+)", row["Catalytic activity"]))),
                "cofactors": sorted(
                    {c.strip() for c in re.findall(r"Name=([^;]+);", row["Cofactor"])}
                ),
                "go_process": [
                    _GO_ID.sub("", g) for g in _ids(row["Gene Ontology (biological process)"])
                ],
                "go_function": [
                    _GO_ID.sub("", g) for g in _ids(row["Gene Ontology (molecular function)"])
                ],
                "go_component": [
                    _GO_ID.sub("", g) for g in _ids(row["Gene Ontology (cellular component)"])
                ],
                "disruption_phenotype": _comment(
                    row["Disruption phenotype"], "DISRUPTION PHENOTYPE"
                ),
                "pubmed_ids": _ids(row["PubMed ID"]),
                "n_references": len(_ids(row["PubMed ID"])),
                "protein_existence": row["Protein existence"] or None,
                "annotation_score": float(row["Annotation"]) if row["Annotation"] else None,
            }


def build(*, force: bool = False) -> Path:
    raw = fetch_raw(force=force)
    return write_parquet(
        "proteins",
        normalize(raw.path),
        source=SOURCE,
        source_version=raw.version("x-uniprot-release", "x-uniprot-release-date"),
        retrieved_at=raw.retrieved_at,
    )
