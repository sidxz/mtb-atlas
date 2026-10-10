"""The clinical layer: TB drugs, their mechanisms, trials, and the links between them.

Every case here is a real record. The traps are the ones the live data sets:
a phase that means TB in one column and any indication in the next, a drug
filed against a whole complex, a sponsor who lists the class name "Rifamycin"
as an alias for rifapentine, and a resistance gene that is not a target.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas import clinical
from atlas.sources import chembl, clinicaltrials
from atlas.store import records

from .conftest import FIXTURES

ISONIAZID = "CHEMBL64"
ETHIONAMIDE = "CHEMBL1441"
BEDAQUILINE = "CHEMBL376488"
MACOZINONE = "CHEMBL3330226"  # PBTZ169
SQ109 = "CHEMBL561057"
RIFAMPICIN = "CHEMBL374478"
RIFAPENTINE = "CHEMBL1660"
RIFAMYCIN = "CHEMBL437765"  # rifamycin SV, the molecule -- not the class
DELAMANID = "CHEMBL218650"
PRETOMANID = "CHEMBL227875"
LINEZOLID = "CHEMBL126"
DEXAMETHASONE = "CHEMBL384467"
LACTOSE = "CHEMBL5314358"


@pytest.fixture(scope="session")
def payloads() -> dict:
    return json.loads((FIXTURES / "chembl_drugs.json").read_text())


@pytest.fixture(scope="session")
def drugs(payloads: dict) -> dict[str, dict]:
    rows, _ = chembl.normalize_drugs(payloads)
    return {r["molecule_chembl_id"]: r for r in rows}


@pytest.fixture(scope="session")
def mechanisms(payloads: dict) -> list[dict]:
    return chembl.normalize_drugs(payloads)[1]


@pytest.fixture(scope="session")
def studies() -> dict:
    return json.loads((FIXTURES / "clinicaltrials_studies.json").read_text())


@pytest.fixture(scope="session")
def trials(studies: dict) -> dict[str, dict]:
    return {t["nct_id"]: t for t in clinicaltrials.normalize(studies["studies"])}


# --- ChEMBL drugs --------------------------------------------------------------


def test_one_row_per_parent_molecule(drugs: dict, payloads: dict) -> None:
    """A salt is its parent: bedaquiline fumarate is bedaquiline."""
    assert set(drugs) == {i["parent_molecule_chembl_id"] for i in payloads["indications"]}
    assert "CHEMBL2105700" not in drugs
    assert "CHEMBL2105700" in drugs[BEDAQUILINE]["salt_chembl_ids"]


def test_tb_phase_is_not_overall_phase(drugs: dict) -> None:
    """Linezolid is approved, but not for TB."""
    assert drugs[LINEZOLID]["max_phase"] == 4
    assert drugs[LINEZOLID]["max_phase_tb"] == 3


def test_trial_references_are_split(drugs: dict) -> None:
    """ChEMBL packs every trial behind an indication into one comma-separated ref."""
    ncts = drugs[BEDAQUILINE]["nct_ids"]
    assert "NCT02333799" in ncts
    assert all(n.startswith("NCT") and "," not in n for n in ncts)


def test_mechanism_flags(drugs: dict) -> None:
    assert drugs[ISONIAZID]["acts_on_mtb"] is True  # InhA
    assert drugs[DELAMANID]["acts_on_mtb"] is True  # filed against the organism itself
    assert drugs[RIFAMPICIN]["acts_on_mtb"] is False  # a generic *bacterial* RNA polymerase
    assert drugs[DEXAMETHASONE]["host_targeted"] is True  # human glucocorticoid receptor
    # A placebo excipient carries a TB indication and no mechanism at all.
    assert drugs[LACTOSE]["acts_on_mtb"] is False
    assert drugs[LACTOSE]["host_targeted"] is False


def test_a_complex_target_keeps_its_components(mechanisms: list[dict]) -> None:
    (bedaquiline,) = [m for m in mechanisms if m["molecule_chembl_id"] == BEDAQUILINE]
    assert bedaquiline["target_type"] == "PROTEIN COMPLEX"
    assert len(bedaquiline["component_accessions"]) == 8
    assert "P9WPS1" in bedaquiline["component_accessions"]  # atpE, subunit c


def test_prodrug_activation_survives(mechanisms: list[dict]) -> None:
    ethionamide = next(m for m in mechanisms if m["molecule_chembl_id"] == ETHIONAMIDE)
    assert "EthA" in ethionamide["mechanism_comment"]


def test_a_drug_without_a_mechanism_still_has_a_row(drugs: dict, mechanisms: list[dict]) -> None:
    assert SQ109 in drugs
    assert not [m for m in mechanisms if m["molecule_chembl_id"] == SQ109]


# --- ClinicalTrials.gov --------------------------------------------------------


def test_phase_is_a_number_for_sorting(trials: dict) -> None:
    assert trials["NCT02333799"]["phase_max"] == 3
    assert trials["NCT02333799"]["phases"] == ["PHASE3"]
    assert trials["NCT03036163"]["phase_max"] == 1


def test_interventions_keep_their_other_names(trials: dict) -> None:
    assert {"type": "DRUG", "name": "PA-824", "other_names": ["Pa", "pretomanid"]} in trials[
        "NCT02333799"
    ]["interventions"]


def test_countries_are_distinct(trials: dict) -> None:
    for trial in trials.values():
        assert trial["countries"] == sorted(set(trial["countries"]))


def test_version_names_the_processing_date(studies: dict) -> None:
    assert "2026-10-09T09:00:05" in clinicaltrials.version(studies["version"])


# --- name matching -------------------------------------------------------------


def test_key_ignores_case_and_punctuation() -> None:
    assert clinical.key("PA-824") == clinical.key("pa 824") == "pa824"


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("Isoniazid (INH)", {"Isoniazid", "INH"}),
        ("Bedaquiline, Pretomanid and Linezolid", {"Bedaquiline", "Pretomanid", "Linezolid"}),
        ("PBTZ169 - 40 mg", {"PBTZ169"}),
        ("Clofazimine 100mg", {"Clofazimine"}),
        ("Rifapentine/Isoniazid", {"Rifapentine", "Isoniazid"}),
        ("Bedaquiline Oral Tablet", {"Bedaquiline"}),
    ],
)
def test_name_candidates(text: str, names: set[str]) -> None:
    assert set(clinical.name_candidates(text)) == names


def test_a_name_naming_two_molecules_links_neither(drugs: dict) -> None:
    index = clinical.synonym_index(drugs.values())
    assert clinical.key("Decadron") not in index  # dexamethasone, and its phosphate
    assert index[clinical.key("TMC207")] == BEDAQUILINE
    assert index[clinical.key("PBTZ169")] == MACOZINONE


def test_short_names_never_index(drugs: dict) -> None:
    assert all(len(k) >= 3 for k in clinical.synonym_index(drugs.values()))


# --- drug -> gene --------------------------------------------------------------


@pytest.fixture(scope="session")
def links(evidence_store: Path) -> list[dict]:
    return records("drug_genes", store=evidence_store)


def kinds(links: list[dict]) -> set[tuple[str, str, str]]:
    return {(r["molecule_chembl_id"], r["rv_id"], r["link"]) for r in links}


def test_single_protein_mechanism_links_the_gene(links: list[dict]) -> None:
    assert (ISONIAZID, "Rv1484", "mechanism") in kinds(links)  # InhA
    assert (MACOZINONE, "Rv3790", "mechanism") in kinds(links)  # DprE1


def test_complex_membership_is_labelled_not_promoted(links: list[dict]) -> None:
    """ChEMBL files bedaquiline against all of ATP synthase, not against atpE."""
    pair = (BEDAQUILINE, "Rv1305")
    atpe = {r["link"]: r for r in links if (r["molecule_chembl_id"], r["rv_id"]) == pair}
    assert atpe["mechanism_complex"]["n_target_components"] == 8
    assert "mechanism" not in atpe


def test_bosch_annotation_links_by_exact_name(links: list[dict]) -> None:
    assert (SQ109, "Rv0206c", "bosch_2021") in kinds(links)
    assert (MACOZINONE, "Rv3790", "bosch_2021") in kinds(links)  # written PBTZ169
    assert (BEDAQUILINE, "Rv1305", "bosch_2021") in kinds(links)


def test_a_drug_class_matches_no_molecule(links: list[dict]) -> None:
    """Bosch annotates rpoB with 'rifamycins', a class; it must not become rifamycin SV."""
    assert not [r for r in links if r["rv_id"] == "Rv0667" and r["link"] == "bosch_2021"]


def test_non_mtb_mechanism_targets_reach_no_gene(links: list[dict]) -> None:
    """Rifampicin's ChEMBL target is built from E. coli proteins, not Mtb RpoB."""
    assert not [
        r for r in links if r["molecule_chembl_id"] == RIFAMPICIN and r["link"].startswith("mech")
    ]
    assert not [r for r in links if r["molecule_chembl_id"] == DELAMANID]  # organism-level


def test_resistance_is_its_own_link_and_not_a_target(links: list[dict]) -> None:
    assert (RIFAMPICIN, "Rv0667", "who_resistance") in kinds(links)
    assert (ISONIAZID, "Rv1908c", "who_resistance") in kinds(links)  # katG activates it
    assert (ISONIAZID, "Rv1908c", "mechanism") not in kinds(links)
    katg = next(r for r in links if (r["molecule_chembl_id"], r["rv_id"]) == (ISONIAZID, "Rv1908c"))
    assert katg["n_variants"] > 0


# --- trial -> drug -------------------------------------------------------------


@pytest.fixture(scope="session")
def trial_links(evidence_store: Path) -> dict[tuple[str, str], dict]:
    rows = records("trial_drugs", store=evidence_store)
    return {(r["nct_id"], r["molecule_chembl_id"]): r for r in rows}


def test_a_combination_regimen_links_each_drug(trial_links: dict) -> None:
    for molecule in (BEDAQUILINE, PRETOMANID, LINEZOLID):  # Nix-TB: B-Pa-L
        assert trial_links[("NCT02333799", molecule)]["via_intervention_name"] is True


def test_other_names_are_only_a_fallback(trial_links: dict) -> None:
    """NCT02651259 gives rifapentine the other name 'Rifamycin', meaning the class."""
    assert ("NCT02651259", RIFAPENTINE) in trial_links
    assert ("NCT02651259", RIFAMYCIN) not in trial_links


def test_a_chembl_reference_links_what_no_name_matches(trial_links: dict) -> None:
    """'PBTZ169 Formulation' names nothing exactly; ChEMBL's own reference still links it."""
    link = trial_links[("NCT03423030", MACOZINONE)]
    assert link["via_chembl_ref"] is True
    assert link["via_intervention_name"] is False


def test_doses_do_not_hide_a_name(trial_links: dict) -> None:
    assert trial_links[("NCT03036163", MACOZINONE)]["via_intervention_name"] is True


def test_parenthetical_abbreviations_still_match(trial_links: dict) -> None:
    assert ("NCT05556746", DELAMANID) in trial_links  # "Delamanid (DLM)"
    assert ("NCT05556746", ISONIAZID) in trial_links  # "Isoniazid (INH)"


def test_vaccine_trials_link_to_no_drug(trial_links: dict) -> None:
    assert not [k for k in trial_links if k[0] == "NCT01829490"]


def test_references_outside_the_trial_set_are_dropped(
    trial_links: dict, evidence_store: Path
) -> None:
    """ChEMBL cites dozens of bedaquiline trials; only the ones in the store may link."""
    in_store = {t["nct_id"] for t in records("trials", store=evidence_store)}
    assert {nct for nct, _ in trial_links} <= in_store
