"""The read API over the fixture store: drugs and trials both ways round.

The API reads only the normalized store, so pointing it at the fixture store
exercises every route without a network or a full build.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas import api, store


@pytest.fixture
def client(evidence_store: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(api, "STORE", evidence_store)
    monkeypatch.setattr(store, "STORE", evidence_store)
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
