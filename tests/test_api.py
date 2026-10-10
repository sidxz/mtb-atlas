"""The read API over the fixture store: drugs and trials both ways round.

The API reads only the normalized store, so pointing it at the fixture store
exercises every route without a network or a full build.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas import api, store, summary


@pytest.fixture
def client(evidence_store: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for module in (api, store, summary):
        monkeypatch.setattr(module, "STORE", evidence_store)
    return TestClient(api.app)


def test_target_page_carries_drugs_and_trials(client: TestClient) -> None:
    page = client.get("/targets/Rv3790").json()
    assert {(d["molecule_chembl_id"], d["link"]) for d in page["drugs"]} >= {
        ("CHEMBL3330226", "mechanism"),
        ("CHEMBL3330226", "bosch_2021"),
    }
    assert {t["nct_id"] for t in page["trials"]} == {"NCT03036163", "NCT03423030"}


def test_a_gene_without_drugs_says_so(client: TestClient) -> None:
    page = client.get("/targets/Rv0667").json()  # rpoB: resistance, but no target claim
    assert not [d for d in page["drugs"] if d["link"] in ("mechanism", "bosch_2021")]
    assert any("No drug" in text for text in page["absences"])


def test_drug_page_goes_back_to_genes_and_trials(client: TestClient) -> None:
    drug = client.get("/drugs/CHEMBL3330226").json()
    assert drug["pref_name"] == "MACOZINONE"
    assert ("Rv3790", "mechanism") in {(g["rv_id"], g["link"]) for g in drug["genes"]}
    assert {t["nct_id"] for t in drug["trials"]} == {"NCT03036163", "NCT03423030"}
    assert drug["mechanisms"][0]["target_chembl_id"] == "CHEMBL3804751"


def test_drug_list_filters_by_phase(client: TestClient) -> None:
    items = client.get("/drugs", params={"min_phase": 4}).json()["items"]
    assert items and all(d["max_phase_tb"] >= 4 for d in items)
    assert "TMC207" in next(d for d in items if d["pref_name"] == "BEDAQUILINE")["synonyms"]
    assert "CHEMBL3330226" not in {d["molecule_chembl_id"] for d in items}


def test_trials_filter_by_drug(client: TestClient) -> None:
    page = client.get("/trials", params={"molecule": "CHEMBL376488"}).json()
    assert "NCT02333799" in {t["nct_id"] for t in page["items"]}
    assert all(
        "CHEMBL376488" in {d["molecule_chembl_id"] for d in t["drugs"]} for t in page["items"]
    )


def test_trial_page_names_how_each_drug_was_linked(client: TestClient) -> None:
    trial = client.get("/trials/NCT03423030").json()
    (link,) = trial["drugs"]
    assert link["molecule_chembl_id"] == "CHEMBL3330226"
    assert link["via_chembl_ref"] is True
    assert link["via_intervention_name"] is False


def test_unknown_ids_are_404(client: TestClient) -> None:
    assert client.get("/drugs/CHEMBL0").status_code == 404
    assert client.get("/trials/NCT00000000").status_code == 404


def test_targets_filter_on_clinical_drugs(client: TestClient) -> None:
    hits = client.get("/targets", params={"has_clinical_drug": True}).json()["items"]
    assert {"Rv3790", "Rv0206c", "Rv1484", "Rv1305"} <= {g["rv_id"] for g in hits}
    assert "Rv0667" not in {g["rv_id"] for g in hits}


def test_meta_lists_the_clinical_sources(client: TestClient) -> None:
    meta = client.get("/meta").json()
    assert "ClinicalTrials.gov" in {s["name"] for s in meta["sources"]}
    assert meta["counts"]["trials"] > 0


def test_target_page_leads_with_the_protein(client: TestClient) -> None:
    page = client.get("/targets/Rv3790").json()
    assert page["function"].startswith("Component of the DprE1-DprE2 complex")
    assert page["reviewed"] is True
    assert page["locations"] == ["Periplasm"]
    assert "essential" in page["disruption_phenotype"]
    assert page["n_references"] == len(page["pubmed_ids"])


def test_targets_carry_membrane_topology(client: TestClient) -> None:
    hits = client.get("/targets", params={"q": "mmpL3"}).json()["items"]
    assert hits[0]["n_transmembrane"] == 12


def test_structures_separate_a_neighbours_ligand(client: TestClient) -> None:
    """rpoB's rifampicin structure must not read as a ligand of rpoC."""
    rpoc = client.get("/targets/Rv0668").json()
    entry = next(s for s in rpoc["structures"] if s["pdb_id"] == "5UHB")
    assert entry["ligand_ids"] == []
    assert entry["ligand_ids_elsewhere"] == ["RFP"]
    rpob = client.get("/targets/Rv0667").json()
    assert next(s for s in rpob["structures"] if s["pdb_id"] == "5UHB")["ligand_ids"] == ["RFP"]


def test_a_bound_ligand_is_named_and_tied_to_its_drug(client: TestClient) -> None:
    """5UHB holds rifampicin on rpoB's chain, and rifampicin is an approved TB drug."""
    (ligand,) = client.get("/targets/Rv0667").json()["bound_ligands"]
    assert ligand["comp_id"] == "RFP"
    assert ligand["molecule_chembl_id"] == "CHEMBL374478"
    assert ligand["drug_name"] == "RIFAMPIN"
    assert ligand["max_phase_tb"] == 4


def test_a_bound_ligand_that_is_no_known_drug_is_still_named(client: TestClient) -> None:
    (ligand,) = client.get("/targets/Rv1484").json()["bound_ligands"]  # InhA, 1ZID
    assert ligand["comp_id"] == "ZID"
    assert "NICOTINAMIDE" in ligand["name"]
    assert ligand["drug_name"] is None


# --- one box over everything -------------------------------------------------


def hits(client: TestClient, q: str) -> dict[str, list[str]]:
    found = client.get("/search", params={"q": q}).json()
    return {kind: [item["id"] for item in items] for kind, items in found.items()}


def test_an_identifier_finds_its_own_object(client: TestClient) -> None:
    assert hits(client, "Rv3790")["genes"][0] == "Rv3790"
    assert hits(client, "CHEMBL376488")["drugs"][0] == "CHEMBL376488"
    assert hits(client, "NCT02333799")["trials"][0] == "NCT02333799"
    assert hits(client, "P9WJF1")["genes"][0] == "Rv3790"  # the accession, not the tag


def test_a_drug_name_finds_the_drug_and_its_trials(client: TestClient) -> None:
    found = hits(client, "bedaquiline")
    assert "CHEMBL376488" in found["drugs"]
    assert "NCT02333799" in found["trials"]


def test_a_synonym_finds_the_drug(client: TestClient) -> None:
    assert "CHEMBL376488" in hits(client, "TMC207")["drugs"]


def test_a_gene_name_beats_a_product_mention(client: TestClient) -> None:
    """Typing a gene name should not bury it under everything that mentions it."""
    assert hits(client, "dprE1")["genes"][0] == "Rv3790"


def test_every_hit_says_what_it_is(client: TestClient) -> None:
    for items in client.get("/search", params={"q": "rif"}).json().values():
        for item in items:
            assert item["id"] and item["label"]


def test_a_search_that_matches_nothing_is_empty_not_an_error(client: TestClient) -> None:
    found = client.get("/search", params={"q": "zzzznotathing"})
    assert found.status_code == 200
    assert all(items == [] for items in found.json().values())


# --- a compound, the other way round -----------------------------------------


def test_a_compound_names_the_genes_it_hits(client: TestClient) -> None:
    """Hit triage runs compound-first: what does this molecule touch, and how hard?"""
    page = client.get("/compounds/CHEMBL3330226").json()  # macozinone
    assert page["pref_name"] == "MACOZINONE"
    (gene,) = [g for g in page["genes"] if g["rv_id"] == "Rv3790"]
    assert gene["gene_name"] == "dprE1"
    assert gene["evidence"] == "direct"
    assert gene["best_pchembl"] is not None


def test_a_compound_that_is_a_tb_drug_says_so(client: TestClient) -> None:
    page = client.get("/compounds/CHEMBL3330226").json()
    assert page["drug"]["max_phase_tb"] == 2


def test_a_compound_that_is_not_a_drug_says_nothing_about_phase(client: TestClient) -> None:
    page = client.get("/compounds/CHEMBL1076347").json()
    assert page["drug"] is None


def test_whole_cell_stays_separate_from_protein_activity(client: TestClient) -> None:
    """The rule the atlas is built on: a MIC is not evidence against a protein."""
    page = client.get("/compounds/CHEMBL3330226").json()
    assert all(a["evidence"] != "whole_cell" for a in page["activities"])
    assert all(a["evidence"] == "whole_cell" for a in page["whole_cell"])


def test_a_wildcard_in_the_term_is_a_character_not_a_pattern(client: TestClient) -> None:
    """`%` and `_` are LIKE wildcards; typing one should mean itself."""
    for term in ("%", "_", "   "):
        found = client.get("/search", params={"q": term}).json()
        assert all(items == [] for items in found.values()), term
    assert client.get("/targets", params={"q": "%"}).json()["total"] == 0
