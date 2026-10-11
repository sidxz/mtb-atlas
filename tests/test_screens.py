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
    # A CELL-LINE target with no ADME or in-vivo language is a mammalian reading.
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


def test_bcg_is_phenotypic_mtb_because_it_is_in_the_complex():
    """BCG is *M. bovis*, a member of the M. tuberculosis complex and not a nontuberculous
    mycobacterium, so the NTM guard must not catch it. The 396 BCG and bovis-variant
    phenotypic assays keep their label; `target_organism` is what separates BCG from
    H37Rv downstream."""
    assert (
        classify_modality(
            "In vitro minimum inhibitory concentration against Mycobacterium tuberculosis",
            "ORGANISM",
            "Mycobacterium tuberculosis variant bovis BCG",
        )
        == "phenotypic_mtb"
    )


def test_a_mouse_host_target_is_efficacy_not_other_pathogen():
    """ChEMBL files a mouse infection study against the mouse, so the target record is
    Mus musculus and not Mtb. An organism-first rule would relabel every such study
    other_pathogen. The prose names the animal, the CFU readout and the organism."""
    assert (
        classify_modality(
            "Reduction in body weight of C3H mouse infected with 10^6 CFU of Mycobacterium "
            "tuberculosis H37Rv assessed as CFU count in lung",
            "ORGANISM",
            "Mus musculus",
        )
        == "in_vivo_efficacy"
    )


_MTB = "Mycobacterium tuberculosis"


def test_in_vivo_efficacy_fails_when_any_one_of_its_conjuncts_is_missing():
    """Each negative carries two of the three, so dropping any single conjunct fails one.
    The older negatives have only one of the three, which left every conjunct untested:
    a mouse *S. aureus* CFU study read as Mtb efficacy under a mutant with no organism test."""
    # Readout and organism, no animal: an in-vitro CFU assay.
    assert (
        classify_modality(
            "Antitubercular activity against Mycobacterium tuberculosis H37Rv assessed as "
            "reduction in CFU count",
            "ORGANISM",
            _MTB,
        )
        == "phenotypic_mtb"
    )
    # Animal and organism, no readout.
    assert (
        classify_modality(
            "Toxicity in BALB/c mouse infected with Mycobacterium tuberculosis H37Rv", None, None
        )
        != "in_vivo_efficacy"
    )
    # Animal and readout, another organism.
    assert (
        classify_modality(
            "Antibacterial activity against Staphylococcus aureus infected in CD1 mouse thigh "
            "assessed as reduction in CFU count",
            "ORGANISM",
            "Staphylococcus aureus",
        )
        == "other_pathogen"
    )


@pytest.mark.parametrize(
    "animal",
    [
        "guinea pigs",
        "guinea-pig",
        "hamsters",
        "rabbits",
        "macaques",
        "monkeys",
        "marmosets",
        "zebrafish",
    ],
)
def test_in_vivo_efficacy_reads_the_other_animals_a_tuberculosis_study_uses(animal):
    assert (
        classify_modality(
            f"Antitubercular activity against Mycobacterium tuberculosis H37Rv infected in "
            f"{animal} assessed as reduction in CFU count in lung",
            None,
            None,
        )
        == "in_vivo_efficacy"
    )


def test_a_monkey_kidney_cell_line_is_not_an_animal_study():
    """Monkey is an animal word and also the host of the Vero line. With the organism named
    and no bacterial readout this carries two of the three conjuncts, so it fails if the
    readout conjunct is dropped."""
    assert (
        classify_modality(
            "Selectivity index, ratio of CC50 for african green monkey Vero cells to MIC for "
            "Mycobacterium tuberculosis H37Rv",
            None,
            None,
        )
        == "mammalian_cytotox"
    )


@pytest.mark.parametrize(
    "culture",
    [
        "mouse macrophages assessed as reduction in bacterial burden",
        "mouse J774A.1 cells assessed as reduction in bacterial burden",
        "mouse RAW 264.7 cells assessed as reduction in bacterial burden",
        "mouse RAW264.7 cells assessed as reduction in colony forming units",
        "mouse BMDM assessed as reduction in colony forming units",
        "mouse bone marrow cells assessed as reduction in bacterial burden",
        "monolayers of mouse cells assessed as reduction in bacterial burden",
        "mouse cells assessed as reduction in intracellular bacterial burden",
    ],
)
def test_an_infected_cell_culture_is_not_an_animal_study(culture):
    """The culture says "mouse", a CFU or burden, and the organism, so all three conjuncts
    fire; 35 of 739 in-vivo-labelled assays were macrophage or monolayer culture."""
    assert (
        classify_modality(
            f"Antitubercular activity against Mycobacterium tuberculosis H37Rv infected in "
            f"{culture}",
            "ORGANISM",
            _MTB,
        )
        == "phenotypic_mtb"
    )


@pytest.mark.parametrize(
    "readout",
    [
        "reduction of bacterial count in lungs",
        "reduction of bacterial count in spleens",
        "reduction in colony forming units",
        "reduction in colony forming unit",
        "reduction in colony-forming units",
    ],
)
def test_the_readout_takes_plural_organs_and_the_spelled_out_cfu(readout):
    """A trailing word boundary after `lung` missed "lungs", and nothing matched "colony
    forming units", so about 70 mouse and guinea-pig efficacy studies read phenotypic_mtb.
    Each case here has no other readout word, so only the alternative under test can match."""
    assert (
        classify_modality(
            "Antitubercular activity against Mycobacterium tuberculosis H37Rv infected in "
            f"BALB/c mouse assessed as {readout}",
            "ORGANISM",
            _MTB,
        )
        == "in_vivo_efficacy"
    )


def test_a_real_animal_study_that_says_cells_is_still_in_vivo():
    """The culture words are specific on purpose. A bare "cells" alternative would exclude
    this study, which dosed mice and counted CFU in lung cells."""
    assert (
        classify_modality(
            "Antitubercular activity against Mycobacterium tuberculosis H37Rv infected in "
            "BALB/c mouse assessed as reduction in CFU count in lung cells",
            None,
            None,
        )
        == "in_vivo_efficacy"
    )


def test_animal_pharmacokinetics_is_adme_even_though_chembl_files_it_against_the_animal():
    """ChEMBL files a rat clearance study against *Rattus norvegicus* as an ORGANISM target.
    An organism-first rule (ORGANISM and not Mtb is other_pathogen) would relabel every one
    of these 821 assays, and Mus musculus, rat and guinea pig are most of them."""
    assert (
        classify_modality(
            "Clearance rate after i.v. administration in rats", "ORGANISM", "Rattus norvegicus"
        )
        == "adme"
    )


def test_cytotoxicity_prose_beats_an_admet_target_type():
    """ChEMBL types a few hundred cytotoxicity assays as ADMET. Explicit prose is the better
    witness, and "hepatocytes" in a cytotoxicity sentence is the cell, not the metabolism."""
    assert (
        classify_modality("Cytotoxicity against Vero cells", "ADMET", None) == "mammalian_cytotox"
    )
    assert (
        classify_modality("Cytotoxicity against human primary hepatocytes", None, None)
        == "mammalian_cytotox"
    )


def test_a_pharmacokinetic_word_in_an_in_vitro_model_is_not_host_adme():
    assert (
        classify_modality(
            "Antimycobacterial activity against Mycobacterium tuberculosis H37Rv ATCC 25618-"
            "infected hollow fiber system based in vitro pharmacokinetic-pharmacodynamic model",
            "ORGANISM",
            _MTB,
        )
        == "phenotypic_mtb"
    )
    assert (
        classify_modality(
            "Bacterial clearance of Mycobacterium tuberculosis in macrophages", "ORGANISM", _MTB
        )
        == "phenotypic_mtb"
    )


def test_an_adme_endpoint_wins_over_the_cell_line_it_ran_in():
    """Caco-2 permeability is filed against a CELL-LINE target and is still ADME."""
    assert (
        classify_modality("Permeability across Caco-2 cells", "CELL-LINE", "Homo sapiens") == "adme"
    )


@pytest.mark.parametrize(
    ("description", "target_type", "organism"),
    [
        ("Inhibition of human CYP3A4", "SINGLE PROTEIN", "Homo sapiens"),
        ("Inhibition of CYP2D6", None, None),
        ("Inhibition of CYP450", None, None),
        ("Inhibition of CYP", None, None),
        ("AUC0-24 in mouse", None, None),
        ("AUC (0 to 24 hrs) in BALB/c mouse", None, None),
        ("AUClast in Sprague-Dawley rat at 5 mg/kg, iv", "ORGANISM", "Rattus norvegicus"),
        ("AUCinfinity in CD1 mouse at 10 mg/kg, po", "ORGANISM", "Mus musculus"),
        ("fAUC (0 to 24 hrs) in plasma of patient", None, None),
    ],
)
def test_the_real_forms_of_cyp_and_auc_are_adme(description, target_type, organism):
    """A trailing word boundary fails before a digit, so `\\bcyp\\b` and `\\bauc\\b` matched
    only a bare CYP and a bare AUC and lost these."""
    assert classify_modality(description, target_type, organism) == "adme"


def test_a_mycobacterial_cytochrome_is_a_protein_assay_not_adme():
    """CYP121, CYP125 and CYP51 are Mtb enzymes. A pattern of `\\bcyp\\d` would call their
    binding assays ADME; human isoforms have a subfamily letter and these do not."""
    assert (
        classify_modality(
            "Binding affinity to Mycobacterium tuberculosis His6-tagged CYP121 expressed in "
            "Escherichia coli",
            "SINGLE PROTEIN",
            _MTB,
        )
        == "biochemical_mtb"
    )


def test_a_profiling_modality_is_a_profiling_stage():
    """classify_stage kept its own word list, which omitted bioavailability, half-life, AUC,
    CYP and Caco-2, so "Oral bioavailability in mouse" was adme by modality and primary by
    stage. The stage now follows the modality, so the two cannot disagree."""
    assert classify_stage("Oral bioavailability in mouse") == "profiling"
    for modality in ("mammalian_cytotox", "adme", "in_vivo_efficacy"):
        assert classify_stage("anything at all", modality=modality) == "profiling"
    for modality in ("phenotypic_mtb", "biochemical_mtb", "other_pathogen", "other"):
        assert classify_stage("anything at all", modality=modality) == "primary"
    # A modality that is passed is not second-guessed by a word in the prose.
    assert (
        classify_stage("Cytotoxicity against HepG2 cells", modality="phenotypic_mtb") == "primary"
    )


def test_stage_order_is_stated_then_counter_screen_then_profiling_then_confirmation():
    assert classify_stage("Cytotoxicity, dose response, HepG2") == "profiling"
    assert classify_stage("Counter screen against HEK293 cytotoxicity") == "counter_screen"
    assert (
        classify_stage("Cytotoxicity against HepG2", pubchem_type="Confirmatory") == "confirmatory"
    )


def test_qhts_is_a_primary_screen_not_a_confirmation():
    """NCGC's qHTS runs a concentration-response curve across the whole library."""
    assert classify_stage("qHTS for inhibitors of Mycobacterium tuberculosis") == "primary"
