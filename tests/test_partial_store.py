"""A store built only as far as the evidence stage must still work.

The clinical stage reaches two upstream services, so a cold build can stop
short of it. When that happens the atlas has to say the layer is not built --
never show it as zero, which would read as "no drug acts on this gene".
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas import api, store, summary
from atlas.summary import counts

CLINICAL = ("drugs", "drug_mechanisms", "trials", "drug_genes", "trial_drugs")


@pytest.fixture(scope="session")
def evidence_only_store(evidence_store: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("evidence-only")
    for parquet in evidence_store.glob("*.parquet"):
        if parquet.stem not in (*CLINICAL, "target_summary"):
            shutil.copy(parquet, out / parquet.name)
    summary.build(store=out)
    return out


def test_the_summary_still_builds(evidence_only_store: Path) -> None:
    rows = store.records("target_summary", store=evidence_only_store)
    assert rows


def test_an_unbuilt_layer_is_null_not_zero(evidence_only_store: Path) -> None:
    for row in store.records("target_summary", store=evidence_only_store):
        assert row["n_drugs"] is None
        assert row["has_clinical_drug"] is None
        assert row["n_trials"] is None


def test_counts_leave_out_what_was_never_built(evidence_only_store: Path) -> None:
    result = counts(store=evidence_only_store)
    assert result["genes"] > 0
    for key in ("drugs", "trials", "with_clinical_drug"):
        assert key not in result


@pytest.fixture
def client(evidence_only_store: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Each module imports STORE by value, so each one has to be pointed at the
    # fixture store separately.
    for module in (api, store, summary):
        monkeypatch.setattr(module, "STORE", evidence_only_store)
    return TestClient(api.app)


def test_meta_still_answers(client: TestClient) -> None:
    assert client.get("/meta").status_code == 200


def test_the_gene_page_says_the_layer_is_not_built(client: TestClient) -> None:
    page = client.get("/targets/Rv3790")
    assert page.status_code == 200
    body = page.json()
    assert body["drugs"] == []
    assert any("not built" in text for text in body["absences"])
    # Never the sentence that means "we looked and found none".
    assert not any("No drug with a TB indication" in text for text in body["absences"])


def test_the_clinical_routes_say_so_rather_than_answering_empty(client: TestClient) -> None:
    """An empty drug list would read as "there are no TB drugs"."""
    for path in ("/drugs", "/trials", "/drugs/CHEMBL64", "/trials/NCT02333799"):
        response = client.get(path)
        assert response.status_code == 503, path
        assert "atlas clinical" in response.json()["detail"]


def test_rebuilding_the_summary_does_not_need_the_network(evidence_only_store: Path) -> None:
    """The evidence stage ends in a roll-up, and must not need a later stage to do it."""
    assert summary.build(store=evidence_only_store).exists()


def test_search_still_answers(client: TestClient) -> None:
    """The search box is the app's main navigation; a 500 there is the whole UI."""
    found = client.get("/search", params={"q": "dprE1"})
    assert found.status_code == 200
    assert found.json()["genes"][0]["id"] == "Rv3790"
    assert found.json()["drugs"] == []


def test_a_compound_page_still_answers(client: TestClient) -> None:
    page = client.get("/compounds/CHEMBL3330226")
    assert page.status_code == 200
    assert page.json()["drug"] is None
