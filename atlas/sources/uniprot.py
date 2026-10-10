"""UniProt reference proteome UP000001584: accessions and cross-references.

This is the source of truth for Rv tag -> UniProt accession, and for the PDB,
ChEMBL and AlphaFold cross-references hanging off each accession. Licence:
CC BY 4.0.
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
# protein2ipr.dat.gz, which is 13.3 GB for the same 3,997 answers.
FIELDS = (
    "accession,id,reviewed,gene_oln,gene_primary,gene_synonym,protein_name,"
    "length,xref_pdb,xref_chembl,xref_alphafolddb,xref_interpro,xref_pfam,"
    "go_id,ec"
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
