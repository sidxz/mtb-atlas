"""Has a drug ever been filed against this fold?

`docs/data-sources.md` records an open question: nothing public supplies a
druggability score, and the atlas refuses to invent one. This is not that
number. It is the one sourced thing in its neighbourhood -- a count of the
drugs ChEMBL has on record against *some other* protein carrying the same Pfam
domain as this gene. "Four approved drugs are filed against proteins with this
domain" is a fact about a database. Whether that makes the gene druggable is
the reader's call, which is why every row names the drug, its phase, the
protein it actually acts on and that protein's organism.

**Pfam, not ChEMBL's own protein classification.** ChEMBL classifies its own
target components, and only 199 of the 4,031 CDS genes are one -- the genes
that already have chemistry, which need a precedent signal least. Pfam is on
3,531 of them, from the UniProt stream the atlas already downloads, and ChEMBL
publishes a Pfam cross-reference on its components, so both ends of the bridge
are a domain accession rather than a name match.

**A shared domain is not a shared binding site**, the same caveat UniRef50
carries in `CLAUDE.md`. Two defences, both visible rather than built into the
number: the domain is named, and the summary carries how many Mtb genes share
it -- PF00005 (ABC transporter) covers 37 of them, PF03176 (MmpL) 14, and the
median precedented domain covers one. A precedent on a domain 37 genes share
is a statement about a superfamily.

**A gene's own protein is not precedent for itself.** The roll-up excludes
rows whose component accession is the gene's own: a drug against this very
protein is already counted in `n_drugs` and `n_ligands`, and dprE1 reading
"two clinical compounds against this fold" when those compounds are
macozinone and TBA-7371 against dprE1 would be circular.

The source is ChEMBL, same release as the drug layer, so `atlas check`'s
existing chembl probe covers it and no new probe is registered. It is a
separate module from `chembl.py` because it takes the Mtb proteome's domains
as its key set, and that module's normalizer deliberately knows nothing about
the gene universe.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..store import write_parquet
from .chembl import SOURCE, batches, pages, release_from_api

# Every mechanism in ChEMBL, not just the TB ones: the point is precedent from
# anywhere, and `clinical.py` already holds the TB-only question.
MECHANISM_FIELDS = (
    "mec_id,molecule_chembl_id,parent_molecule_chembl_id,target_chembl_id,max_phase,"
    "action_type,mechanism_of_action"
)
TARGET_FIELDS = "target_chembl_id,pref_name,target_type,organism,tax_id,target_components"
COMPONENT_FIELDS = "accession,target_component_xrefs"
MOLECULE_FIELDS = "molecule_chembl_id,pref_name"

PFAM = "Pfam"


def fetch_raw(*, force: bool = False) -> dict[str, list[dict[str, Any]]]:
    """Mechanisms, the targets they point at, and those targets' components.

    Sequential, because each step's key set is the previous step's answer. Eight
    pages of mechanisms, then ~1,500 targets and ~2,300 components in batches of
    fifty, every page cached like the rest of the drug layer.
    """
    mechanisms = pages(
        "mechanism", f"only={MECHANISM_FIELDS}", "mechanisms", "precedent/mechanisms", force=force
    )
    target_ids = sorted({m["target_chembl_id"] for m in mechanisms if m.get("target_chembl_id")})
    targets: list[dict[str, Any]] = []
    for n, batch in enumerate(batches(target_ids)):
        targets += pages(
            "target",
            f"target_chembl_id__in={batch}&only={TARGET_FIELDS}",
            "targets",
            f"precedent/targets-{n}",
            force=force,
        )
    accessions = sorted(
        {
            component["accession"]
            for target in targets
            for component in target.get("target_components") or []
            if component.get("accession")
        }
    )
    components: list[dict[str, Any]] = []
    for n, batch in enumerate(batches(accessions)):
        components += pages(
            "target_component",
            f"accession__in={batch}&only={COMPONENT_FIELDS}",
            "target_components",
            f"precedent/components-{n}",
            force=force,
        )
    return {"mechanisms": mechanisms, "targets": targets, "components": components}


def molecule_names(molecule_ids: Sequence[str], *, force: bool = False) -> dict[str, str]:
    """`CHEMBL19` is not a drug name a reader can act on; fetched last, so only
    the molecules that survived the domain filter are asked for."""
    names: dict[str, str] = {}
    for n, batch in enumerate(batches(molecule_ids)):
        for molecule in pages(
            "molecule",
            f"molecule_chembl_id__in={batch}&only={MOLECULE_FIELDS}",
            "molecules",
            f"precedent/molecules-{n}",
            force=force,
        ):
            if molecule.get("pref_name"):
                names[molecule["molecule_chembl_id"]] = molecule["pref_name"]
    return names


def pfam_domains(components: Iterable[dict[str, Any]]) -> dict[str, list[tuple[str, str | None]]]:
    """accession -> [(Pfam accession, Pfam name)], from ChEMBL's own cross-references."""
    return {
        component["accession"]: [
            (xref["xref_id"], xref.get("xref_name"))
            for xref in component.get("target_component_xrefs") or []
            if xref.get("xref_src_db") == PFAM and xref.get("xref_id")
        ]
        for component in components
        if component.get("accession")
    }


def normalize(
    payloads: Mapping[str, list[dict[str, Any]]],
    domains: Iterable[str],
    names: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """One row per distinct claim, restricted to the domains Mtb proteins carry.

    A claim is (domain, protein, drug, target, mechanism) and `mec_id` is the
    earliest ChEMBL record that states it. Not one row per `mec_id`: ChEMBL
    files a mechanism per salt, and folding salts into their parent the way
    `normalize_drugs` does turns daunorubicin, its hydrochloride and its
    citrate into three identical rows about human topoisomerase II. The counts
    are DISTINCT on the molecule and so were right either way, but the table
    behind them should not repeat itself.

    Dropping the domains no Mtb protein carries takes the table from 34,561
    rows over 1,403 domains to 9,603 over 325, and leaves nothing behind that
    could reach a gene.
    """
    wanted = set(domains)
    names = names or {}
    pfam_of = pfam_domains(payloads["components"])
    by_id = {t["target_chembl_id"]: t for t in payloads["targets"]}

    rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    for mechanism in payloads["mechanisms"]:
        target = by_id.get(mechanism.get("target_chembl_id"))
        if target is None:
            continue
        molecule = mechanism.get("parent_molecule_chembl_id") or mechanism["molecule_chembl_id"]
        phase = mechanism.get("max_phase")
        for component in target.get("target_components") or []:
            accession = component.get("accession")
            for pfam_id, pfam_name in pfam_of.get(accession, []):
                if pfam_id not in wanted:
                    continue
                key = (
                    pfam_id,
                    accession,
                    molecule,
                    target["target_chembl_id"],
                    mechanism.get("mechanism_of_action"),
                )
                seen = rows.get(key)
                if seen is not None and seen["mec_id"] <= mechanism["mec_id"]:
                    continue
                rows[key] = {
                    "pfam_id": pfam_id,
                    "pfam_name": pfam_name,
                    # The protein that carries the domain and that the drug was
                    # actually filed against. The roll-up excludes a gene's own
                    # accession with it.
                    "accession": accession,
                    "mec_id": mechanism["mec_id"],
                    "molecule_chembl_id": molecule,
                    "molecule_name": names.get(molecule),
                    # ChEMBL's phase for the molecule in any indication. 4 is
                    # approved; -1 is ChEMBL saying it does not know, which is
                    # neither approved nor clinical and is counted as neither.
                    "max_phase": float(phase) if phase is not None else None,
                    "target_chembl_id": target["target_chembl_id"],
                    "target_name": target.get("pref_name"),
                    "target_type": target.get("target_type"),
                    "organism": target.get("organism"),
                    "tax_id": target.get("tax_id"),
                    "action_type": mechanism.get("action_type"),
                    "mechanism_of_action": mechanism.get("mechanism_of_action"),
                }
    return sorted(rows.values(), key=lambda row: (row["pfam_id"], -(row["max_phase"] or 0)))


def build(domains: Iterable[str], *, retrieved_at: str, force: bool = False) -> Path:
    payloads = fetch_raw(force=force)
    rows = normalize(payloads, domains)
    names = molecule_names(
        sorted({row["molecule_chembl_id"] for row in rows}),
        force=force,
    )
    rows = [row | {"molecule_name": names.get(row["molecule_chembl_id"])} for row in rows]
    return write_parquet(
        "drug_precedent",
        rows,
        source=SOURCE,
        source_version=release_from_api(),
        retrieved_at=retrieved_at,
    )
