"""Campaign-level screening evidence: the census, the classifiers, the tables.

The classifiers read the depositor's own prose, the same standing as
`classify_condition`, so every case here is a shape seen in the live store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.sources import chembl
from atlas.sources.chembl import aggregate_sizes, census_rows

FIXTURES = Path(__file__).parent / "fixtures"


def _census() -> list[dict]:
    return json.loads((FIXTURES / "chembl_assay_census.json").read_text())["activities"]


def test_aggregate_sizes_counts_compounds_not_measurements():
    """One assay run against 400 compounds is one assay; a repeat is not a compound."""
    sizes = {row["assay_chembl_id"]: row for row in aggregate_sizes("CHEMBL4105939", _census())}
    assert sizes["CHEMBL4649965"]["n_compounds"] == 4
    assert sizes["CHEMBL4649965"]["n_measurements"] == 5
    assert sizes["CHEMBL4649965"]["endpoint_types"] == ["Percent Effect"]
    assert sizes["CHEMBL4649965"]["latest_year"] == 2021


def test_aggregate_sizes_stamps_the_target_and_skips_rows_without_an_assay():
    rows = list(aggregate_sizes("CHEMBL4105939", _census()))
    assert {row["target_chembl_id"] for row in rows} == {"CHEMBL4105939"}
    # A row with no assay id cannot be attributed to an assay, so it is not one.
    assert len(rows) == 2


def test_aggregate_sizes_keeps_every_endpoint_the_assay_reported():
    """A screen's percent-effect rows and its IC50 follow-ups are both its own."""
    mixed = [
        {
            "assay_chembl_id": "A",
            "molecule_chembl_id": "M1",
            "standard_type": "Percent Effect",
            "document_year": 2019,
        },
        {
            "assay_chembl_id": "A",
            "molecule_chembl_id": "M2",
            "standard_type": "IC50",
            "document_year": 2023,
        },
        {"assay_chembl_id": "B", "molecule_chembl_id": "M1", "standard_type": "IC50"},
    ]
    rows = {row["assay_chembl_id"]: row for row in aggregate_sizes("T", mixed)}
    assert rows["A"]["endpoint_types"] == ["IC50", "Percent Effect"]
    # 2019 comes first, so first-seen or a `<` comparison would answer 2019.
    assert rows["A"]["latest_year"] == 2023
    assert rows["B"]["latest_year"] is None


def test_census_query_is_unfiltered_and_cached_per_target(monkeypatch: pytest.MonkeyPatch):
    """The potency filter is the bug the census exists to fix, so it must not come back."""
    seen: dict = {}

    def fake_pages(endpoint, query, key, dest, *, force):
        seen.update(query=query, dest=dest, force=force)
        return []

    monkeypatch.setattr(chembl, "pages", fake_pages)
    assert census_rows("CHEMBL_T", force=True) == []
    assert f"only={chembl.CENSUS_FIELDS}" in seen["query"]
    assert "pchembl_value__isnull" not in seen["query"]
    assert seen["dest"] == "census/CHEMBL_T"
    assert seen["force"] is True
