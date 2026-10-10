"""The clinical layer's joins: drugs to genes, and trials to drugs.

Like the crosswalk, these are store tables of their own rather than queries
each page re-derives, because every link records *how* it was made, and a gene
page, a drug page and the agent have to agree on that.

**Drug -> gene** (`drug_genes.link`), four ways that are not interchangeable:

* `mechanism` -- ChEMBL's mechanism names this gene's protein as the
  single-protein target (isoniazid -> InhA, macozinone -> DprE1).
* `mechanism_complex` -- ChEMBL names a complex the protein belongs to.
  Bedaquiline is filed against all eight ATP synthase subunits, sutezolid
  against the 70S ribosome. That says the drug acts on the assembly, not that
  it binds this subunit, so it is shown and never counted as a drug on the gene.
* `bosch_2021` -- Bosch 2021's own `antibacterial` annotation, matched exactly
  to a ChEMBL synonym (SQ109 -> mmpL3, PBTZ169 -> dprE1). Drug classes
  ("fluoroquinolones", "rifamycins") match no molecule and stay text.
* `who_resistance` -- the WHO catalogue grades variants in this gene as
  associated with resistance to the drug. **Resistance is not engagement**:
  katG activates isoniazid, Rv0678 is a regulator of an efflux pump.

A mechanism target from another organism links no Mtb gene. Rifampicin's
ChEMBL target is a generic bacterial RNA polymerase built from *E. coli*
proteins; reaching rpoB from it would need a homology bridge that ChEMBL does
not state. rpoB still meets rifampicin, through the WHO catalogue, labelled as
resistance.

**Trial -> drug** (`trial_drugs`), two ways: ChEMBL's own curated trial
references (`via_chembl_ref`), and an exact match of an intervention name to a
ChEMBL synonym (`via_intervention_name`). An intervention's other names are
consulted only when its own name matches nothing, because sponsors list class
names there -- NCT02651259 gives rifapentine the other name "Rifamycin".
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .store import provenance, records, write_parquet

# Links that say the drug acts on the gene itself. The others are shown, not counted.
TARGET_LINKS = ("mechanism", "bosch_2021")

_PAREN = re.compile(r"\(([^)]*)\)")
_SPLIT = re.compile(r"\s*(?:\+|/|,|;|&|\band\b|\bplus\b|\bwith\b)\s*", re.IGNORECASE)
_DOSE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|g|mcg|µg|ug|iu|ml)\b.*$", re.IGNORECASE)


def key(name: str) -> str:
    """Case and punctuation do not distinguish drug names: PA-824 is pa 824."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def name_candidates(text: str) -> list[str]:
    """The drug names one intervention string could stand for.

    "Isoniazid (INH)" -> Isoniazid, INH; "Bedaquiline, Pretomanid and
    Linezolid" -> all three; "PBTZ169 - 40 mg" -> PBTZ169.
    """
    text = text or ""
    names = []
    for chunk in (_PAREN.sub(" ", text), *_PAREN.findall(text)):
        for part in _SPLIT.split(chunk):
            part = _DOSE.sub("", part).strip(" -–:;.,")
            if part:
                names.append(part)
    return names


def synonym_index(drugs: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Every name ChEMBL gives a TB drug, normalised, mapped to its molecule.

    A name two molecules share (Decadron is dexamethasone and its phosphate) is
    dropped rather than guessed, and a key under three characters never
    matches: "E", "Z" and "H" are regimen shorthand, not names.
    """
    owners: dict[str, set[str]] = defaultdict(set)
    for drug in drugs:
        for name in (drug["pref_name"], *(drug["synonyms"] or [])):
            if len(k := key(name)) >= 3:
                owners[k].add(drug["molecule_chembl_id"])
    return {k: next(iter(v)) for k, v in owners.items() if len(v) == 1}


def matches(text: str, index: Mapping[str, str]) -> set[str]:
    return {index[k] for k in map(key, name_candidates(text)) if k in index}


def drug_gene_links(
    mechanisms: Iterable[Mapping[str, Any]],
    walk: Iterable[Mapping[str, Any]],
    vulnerability: Iterable[Mapping[str, Any]],
    resistance: Iterable[Mapping[str, Any]],
    index: Mapping[str, str],
) -> list[dict[str, Any]]:
    walk = list(walk)
    genes_of_acc: dict[str, list[str]] = defaultdict(list)
    for gene in walk:
        if gene["uniprot_acc"]:
            genes_of_acc[gene["uniprot_acc"]].append(gene["rv_id"])
    # The WHO catalogue is keyed on gene symbol, or the Rv tag where there is none.
    gene_of_symbol = {gene["gene_name"] or gene["rv_id"]: gene["rv_id"] for gene in walk}
    universe = {gene["rv_id"] for gene in walk}

    links: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add(molecule: str, rv_id: str, link: str, **detail: Any) -> None:
        links.setdefault(
            (molecule, rv_id, link),
            {
                "molecule_chembl_id": molecule,
                "rv_id": rv_id,
                "link": link,
                "target_chembl_id": None,
                "target_name": None,
                "n_target_components": None,
                "shared_accession": False,
                "source_text": None,
                "n_variants": None,
                **detail,
            },
        )

    for mechanism in mechanisms:
        components = mechanism["component_accessions"] or []
        single = mechanism["target_type"] == "SINGLE PROTEIN"
        for accession in components:
            # More than one locus behind an accession (the IS6110 copies) means
            # siblings would claim each other's drug; flag it, as the crosswalk does.
            rv_ids = genes_of_acc.get(accession, [])
            for rv_id in rv_ids:
                add(
                    mechanism["molecule_chembl_id"],
                    rv_id,
                    "mechanism" if single else "mechanism_complex",
                    target_chembl_id=mechanism["target_chembl_id"],
                    target_name=mechanism["target_name"],
                    n_target_components=len(components),
                    shared_accession=len(rv_ids) > 1,
                    source_text=mechanism["mechanism_of_action"],
                )

    for row in vulnerability:
        if row["antibacterial"] and row["rv_id"] in universe:
            for molecule in matches(row["antibacterial"], index):
                add(molecule, row["rv_id"], "bosch_2021", source_text=row["antibacterial"])

    graded: Counter[tuple[str, str, str]] = Counter()
    for row in resistance:
        molecule = index.get(key(row["drug"]))
        rv_id = gene_of_symbol.get(row["gene"])
        if row["associated"] and molecule and rv_id:
            graded[(molecule, rv_id, row["drug"])] += 1
    for (molecule, rv_id, drug), n in graded.items():
        add(molecule, rv_id, "who_resistance", source_text=drug, n_variants=n)

    return list(links.values())


def trial_drug_links(
    drugs: Iterable[Mapping[str, Any]],
    trials: Iterable[Mapping[str, Any]],
    index: Mapping[str, str],
) -> list[dict[str, Any]]:
    trials = list(trials)
    in_store = {trial["nct_id"] for trial in trials}
    links: dict[tuple[str, str], dict[str, Any]] = {}

    def link(nct_id: str, molecule: str) -> dict[str, Any]:
        return links.setdefault(
            (nct_id, molecule),
            {
                "nct_id": nct_id,
                "molecule_chembl_id": molecule,
                "via_chembl_ref": False,
                "via_intervention_name": False,
                "matched_names": [],
            },
        )

    for drug in drugs:
        # ChEMBL cites trials outside this condition search; a link to a trial
        # the store does not hold would dangle, so only held trials are linked.
        for nct_id in drug["nct_ids"] or []:
            if nct_id in in_store:
                link(nct_id, drug["molecule_chembl_id"])["via_chembl_ref"] = True

    for trial in trials:
        for intervention in trial["interventions"] or []:
            found = matches(intervention["name"], index)
            if not found:
                for other in intervention["other_names"] or []:
                    found |= matches(other, index)
            for molecule in found:
                row = link(trial["nct_id"], molecule)
                row["via_intervention_name"] = True
                row["matched_names"] = sorted({*row["matched_names"], intervention["name"]})

    return list(links.values())


def build(*, store: Path | None = None) -> list[Path]:
    drugs = records("drugs", store=store)
    index = synonym_index(drugs)
    gene_links = drug_gene_links(
        records("drug_mechanisms", store=store),
        records("crosswalk", store=store),
        records("vulnerability", store=store),
        records("resistance", store=store),
        index,
    )
    trial_links = trial_drug_links(drugs, records("trials", store=store), index)

    inputs = {
        name: provenance(name, store=store)
        for name in ("drugs", "trials", "crosswalk", "vulnerability", "resistance")
    }
    stamp = {
        "source": "atlas-clinical",
        "source_version": "; ".join(f"{name}={version}" for name, (version, _) in inputs.items()),
        "retrieved_at": max(str(retrieved) for _, retrieved in inputs.values()),
        "store": store,
    }
    return [
        write_parquet("drug_genes", gene_links, **stamp),
        write_parquet("trial_drugs", trial_links, **stamp),
    ]
