"""Campaign-level screening evidence: the census, the classifiers, the tables.

The classifiers read the depositor's own prose, the same standing as
`classify_condition`, so every case here is a shape seen in the live store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.sources import chembl
from atlas.sources.chembl import (
    aggregate_sizes,
    census_rows,
    classify_modality,
    classify_stage,
    is_derived,
)

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


def test_a_ratio_chembl_computed_is_not_a_measurement():
    """6,577 compounds carry one. They are arithmetic over two other rows."""
    assert is_derived("Selectivity index, ratio of CC50 for Vero cells to MIC for M. tuberculosis")
    assert is_derived("Therapeutic index, CC50 for african green monkey Vero cells to MIC")
    assert is_derived("Ratio of IC50 for Plasmodium falciparum W2 to IC50 for Vero cells")
    assert not is_derived("Cytotoxicity against human HepG2 cells at 30 uM by CCK8 assay")
    assert not is_derived(None)


def test_whole_cell_mtb_is_phenotypic_and_a_purified_protein_is_biochemical():
    assert (
        classify_modality(
            "In vitro minimum inhibitory concentration against Mycobacterium tuberculosis",
            "ORGANISM",
            "Mycobacterium tuberculosis",
        )
        == "phenotypic_mtb"
    )
    assert (
        classify_modality(
            "Biochemical assay for Mt-TrpRS", "SINGLE PROTEIN", "Mycobacterium tuberculosis"
        )
        == "biochemical_mtb"
    )
    assert (
        classify_modality(
            "in vitro assay for ClpP1P2", "PROTEIN COMPLEX", "Mycobacterium tuberculosis"
        )
        == "biochemical_mtb"
    )


def test_cytotoxicity_is_read_from_the_target_as_well_as_the_prose():
    assert classify_modality("Cytotoxicity against HepG2 cells", None, None) == "mammalian_cytotox"
    # A cell line target is a mammalian reading whatever the prose says.
    assert (
        classify_modality("Antiproliferative activity", "CELL-LINE", "Homo sapiens")
        == "mammalian_cytotox"
    )


def test_adme_does_not_match_an_antibacterial_assay():
    """The first pass matched "Growth inhibition of Staphylococcus aureus" and a
    HEK viability assay as ADME, which inflated the count from 405 to 1,021."""
    assert classify_modality("Clearance in human liver microsomes", "ADMET", None) == "adme"
    assert classify_modality("Metabolic stability in mouse hepatocytes", None, None) == "adme"
    assert (
        classify_modality(
            "Growth inhibition of Staphylococcus aureus Newman", "ORGANISM", "Staphylococcus aureus"
        )
        == "other_pathogen"
    )
    assert (
        classify_modality("Hemolytic activity against human RBC after 1 hr", None, None) != "adme"
    )


def test_in_vivo_efficacy_needs_an_animal_a_readout_and_the_organism():
    assert (
        classify_modality(
            "Antitubercular activity against Mycobacterium tuberculosis H37Rv infected in "
            "BALB/c mouse assessed as reduction in CFU count in lung",
            None,
            None,
        )
        == "in_vivo_efficacy"
    )
    # An animal PK study is not an efficacy study.
    assert classify_modality("Pharmacokinetics in BALB/c mouse plasma", None, None) == "adme"
    # A mouse with no bacterial readout is not efficacy against Mtb.
    assert classify_modality("Toxicity in BALB/c mouse", None, None) != "in_vivo_efficacy"


def test_stage_prefers_what_the_depositor_stated():
    """PubChem names the stage; ChEMBL leaves it in the prose."""
    assert classify_stage("anything at all", pubchem_type="Confirmatory") == "confirmatory"
    assert classify_stage("anything at all", pubchem_type="Screening") == "primary"
    assert (
        classify_stage("Counterscreen for inhibitors of the fructose-bisphosphate aldolase")
        == "counter_screen"
    )
    assert (
        classify_stage("Fluorescence-based biochemical high throughput confirmation assay")
        == "confirmatory"
    )
    assert classify_stage("Cytotoxicity against HepG2 cells") == "profiling"
    assert (
        classify_stage("Fluorescence-based biochemical primary high throughput screening assay")
        == "primary"
    )


def test_a_non_tuberculosis_mycobacterium_is_other_pathogen_whatever_the_prose():
    """An NTM study is not a TB study. The depositor's word "antitubercular" does not
    make a M. avium infection a tuberculosis result, and CLAUDE.md is explicit that
    nontuberculous mycobacteria are not TB."""
    assert (
        classify_modality(
            "In vitro cytotoxicity against Mycobacterium avium (CIP 103317) was determined",
            "ORGANISM",
            "Mycobacterium avium",
        )
        == "other_pathogen"
    )
    assert (
        classify_modality(
            "Antitubercular activity against Mycobacterium avium infected in C57BL/6J mouse "
            "assessed as reduction in CFU count in lung",
            "ORGANISM",
            "Mycobacterium avium",
        )
        == "other_pathogen"
    )
    # Renamed: M. smegmatis is Mycolicibacterium, which has no "Mycobact" substring.
    assert (
        classify_modality(
            "In vitro cytotoxicity against Mycolicibacterium smegmatis",
            "ORGANISM",
            "Mycolicibacterium smegmatis",
        )
        == "other_pathogen"
    )
