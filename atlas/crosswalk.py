"""The ID crosswalk: Rv locus tag -> everything else.

The Rv tag is the canonical key, and the gene universe is Mycobrowser's 4031
CDS loci. Every other source is reached through this table, so its failure modes
matter more than its happy path:

* Mycobrowser and UniProt disagree on the accession for 13 loci, and Mycobrowser
  names 5 accessions that are not in the reference proteome at all.
* Rv tag -> accession is many-to-one. Rv1180 and Rv1181 share A0A089QRB9;
  Rv2561 and Rv2562 share P9WL99; the IS6110 transposase P9WKH9 covers 16 loci.
  Left unflagged, each of those loci would silently claim the same structures
  and ligands as its siblings.

None of that is resolved silently. Each row records how its accession was
decided (`acc_status`), whether that decision was a conflict, and which sibling
loci share the accession -- so a target page can show the ambiguity instead of
inventing certainty.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from . import orthologue
from .sources import chembl, mycobrowser, uniprot
from .store import provenance, write_parquet
from .store import rows as rows_of

# Accession decided by: both sources agreeing, or one of them alone.
AGREE = "agree"
UNIPROT_ONLY = "uniprot_only"
MYCOBROWSER_ONLY = "mycobrowser_only"
DISAGREEMENT = "disagreement"
ACC_NOT_IN_PROTEOME = "mycobrowser_acc_not_in_proteome"
NO_ACCESSION = "no_accession"

# Statuses where the sources actively contradict each other or leave the gene
# unmapped -- as opposed to one source simply having nothing to say.
CONFLICTS = frozenset({DISAGREEMENT, ACC_NOT_IN_PROTEOME, NO_ACCESSION})


def _resolve_accession(
    mb_acc: str | None, up_accs: list[str], in_proteome: set[str]
) -> tuple[str | None, str]:
    """Pick the accession for one locus and say how the choice was made."""
    up_acc = up_accs[0] if up_accs else None
    if up_acc and mb_acc == up_acc:
        return up_acc, AGREE
    if up_acc and mb_acc:
        # UniProt wins: it is the live reference proteome, and Mycobrowser's
        # value is kept in its own column for the UI to show side by side.
        return up_acc, DISAGREEMENT
    if up_acc:
        return up_acc, UNIPROT_ONLY
    if mb_acc and mb_acc in in_proteome:
        # The accession is real but carries no Rv tag in UniProt (e.g. Rv2307D).
        return mb_acc, MYCOBROWSER_ONLY
    if mb_acc:
        return None, ACC_NOT_IN_PROTEOME
    return None, NO_ACCESSION


def build(*, store: Path | None = None, with_orthologues: bool = True) -> Path:
    """Join the store's source tables into crosswalk.parquet."""
    genes, gene_cols = rows_of("genes", store=store)
    proteins, protein_cols = rows_of("proteins", store=store)
    targets, target_cols = rows_of("chembl_targets", store=store)

    by_acc = {p[protein_cols["uniprot_acc"]]: p for p in proteins}
    in_proteome = set(by_acc)
    up_by_rv: dict[str, list[str]] = defaultdict(list)
    for protein in proteins:
        for rv_id in protein[protein_cols["rv_ids"]] or []:
            up_by_rv[rv_id].append(protein[protein_cols["uniprot_acc"]])

    # ChEMBL targets reachable directly from an Mtb accession. The UniProt xrefs
    # and this mapping file very nearly agree; the union covers the handful of
    # targets that only one of them knows about.
    direct_by_acc: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for target in targets:
        acc = target[target_cols["uniprot_acc"]]
        if acc not in in_proteome:
            continue
        direct_by_acc[acc][target[target_cols["chembl_target_id"]]] = {
            "target_id": target[target_cols["chembl_target_id"]],
            "target_type": target[target_cols["target_type"]],
            "pref_name": target[target_cols["pref_name"]],
            "evidence": "direct",
            "via_accession": None,
            "via_organism": None,
            "via_gene": None,
            "uniref_cluster": None,
            "identity_level": None,
            "cluster_size": None,
        }
    for acc, protein in by_acc.items():
        for target_id in protein[protein_cols["chembl_target_ids"]] or []:
            direct_by_acc[acc].setdefault(
                target_id,
                {
                    "target_id": target_id,
                    "target_type": None,
                    "pref_name": None,
                    "evidence": "direct",
                    "via_accession": None,
                    "via_organism": None,
                    "via_gene": None,
                    "uniref_cluster": None,
                    "identity_level": None,
                    "cluster_size": None,
                },
            )

    # Name and type for a target live against the accession that *owns* it, which
    # for an orthologue link is the non-Mtb one. Without this lookup the UI would
    # show a bare CHEMBL id for exactly the targets that most need explaining.
    target_meta = {
        (t[target_cols["uniprot_acc"]], t[target_cols["chembl_target_id"]]): (
            t[target_cols["pref_name"]],
            t[target_cols["target_type"]],
        )
        for t in targets
    }

    ortho_by_acc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if with_orthologues:
        for link in orthologue.build_links(in_proteome):
            pref_name, target_type = target_meta.get(
                (link.via_accession, link.chembl_target_id), (None, None)
            )
            ortho_by_acc[link.mtb_acc].append(
                {
                    "target_id": link.chembl_target_id,
                    "target_type": target_type,
                    "pref_name": pref_name,
                    "evidence": "orthologue",
                    "via_accession": link.via_accession,
                    "via_organism": link.via_organism,
                    "via_gene": link.via_gene,
                    "uniref_cluster": link.uniref_cluster,
                    "identity_level": link.identity_level,
                    "cluster_size": link.cluster_size,
                }
            )

    # First pass: resolve accessions, so sharing can be detected before writing.
    resolved: list[tuple[Any, str | None, str]] = []
    rv_by_acc: dict[str, list[str]] = defaultdict(list)
    for gene in genes:
        rv_id = gene[gene_cols["rv_id"]]
        acc, status = _resolve_accession(
            gene[gene_cols["mycobrowser_uniprot_ac"]], up_by_rv.get(rv_id, []), in_proteome
        )
        resolved.append((gene, acc, status))
        if acc:
            rv_by_acc[acc].append(rv_id)

    out = []
    for gene, acc, status in resolved:
        rv_id = gene[gene_cols["rv_id"]]
        protein = by_acc.get(acc) if acc else None
        siblings = [r for r in rv_by_acc.get(acc, []) if r != rv_id] if acc else []
        chembl_targets = list(direct_by_acc.get(acc, {}).values()) if acc else []
        # An orthologue target is only worth showing where there is no direct one.
        if acc and not chembl_targets:
            chembl_targets = ortho_by_acc.get(acc, [])
        pdb_ids = (protein[protein_cols["pdb_ids"]] or []) if protein else []
        alphafold = (protein[protein_cols["alphafold_ids"]] or []) if protein else []

        out.append(
            {
                "rv_id": rv_id,
                "gene_name": gene[gene_cols["gene_name"]],
                "product": gene[gene_cols["product"]],
                "functional_category": gene[gene_cols["functional_category"]],
                "start": gene[gene_cols["start"]],
                "stop": gene[gene_cols["stop"]],
                "strand": gene[gene_cols["strand"]],
                "is_pseudogene": gene[gene_cols["is_pseudogene"]],
                "uniprot_acc": acc,
                "acc_status": status,
                "conflict": status in CONFLICTS,
                "mycobrowser_uniprot_ac": gene[gene_cols["mycobrowser_uniprot_ac"]],
                "shared_accession": bool(siblings),
                "shares_accession_with": siblings,
                "protein_name": protein[protein_cols["protein_name"]] if protein else None,
                "length": protein[protein_cols["length"]] if protein else None,
                "reviewed": protein[protein_cols["reviewed"]] if protein else None,
                "pdb_ids": list(pdb_ids),
                "n_pdb": len(pdb_ids),
                "alphafold_id": alphafold[0] if alphafold else None,
                "chembl_targets": chembl_targets,
                "n_chembl_targets": len(chembl_targets),
                "chembl_evidence": chembl_targets[0]["evidence"] if chembl_targets else None,
                "resistance_drugs": list(gene[gene_cols["resistance_drugs"]] or []),
            }
        )

    inputs = {
        name: provenance(name, store=store) for name in ("genes", "proteins", "chembl_targets")
    }
    return write_parquet(
        "crosswalk",
        out,
        source="atlas-crosswalk",
        source_version="; ".join(f"{name}={version}" for name, (version, _) in inputs.items()),
        retrieved_at=max(retrieved for _, retrieved in inputs.values()),
        store=store,
    )


def build_all(*, force: bool = False) -> list[Path]:
    """The whole M0 pipeline: three ingesters, then the crosswalk."""
    paths = [source.build(force=force) for source in (mycobrowser, uniprot, chembl)]
    return [*paths, build()]
