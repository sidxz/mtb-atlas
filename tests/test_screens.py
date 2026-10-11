"""Campaign-level screening evidence: the census, the classifiers, the tables.

The classifiers read the depositor's own prose, the same standing as
`classify_condition`, so every case here is a shape seen in the live store.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from atlas.sources import chembl
from atlas.sources.chembl import (
    aggregate_sizes,
    campaign_document_meta,
    campaign_documents,
    campaign_publications,
    census_rows,
    classify_modality,
    classify_stage,
    is_derived,
    normalize_campaign_assays,
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


@pytest.mark.parametrize("organ", ["lung", "spleen"])
def test_a_singular_organ_alone_is_a_bacterial_readout(organ):
    """Every singular positive above also says "CFU", so `lungs?` could lose its `s?` and the
    suite would pass. Here the organ is the only readout word in the sentence."""
    assert (
        classify_modality(
            "Antitubercular activity against Mycobacterium tuberculosis H37Rv infected in "
            f"BALB/c mouse assessed as reduction of bacterial count in {organ}",
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


def test_an_admet_target_is_adme_on_its_own_when_the_prose_says_nothing():
    """927 corpus assays reach `adme` solely through `target_type == "ADMET"`: their prose
    names no ADME word at all. Dropping that clause relabels all of them `other`."""
    assert classify_modality("Measured property of the compound", "ADMET", None) == "adme"
    assert classify_modality("Measured property of the compound", None, None) == "other"


def test_efficacy_is_decided_before_adme_though_clearance_is_an_adme_word():
    """14 corpus rows depend on the order: a bacterial-clearance study in a mouse lung
    says "clearance", which would read as host ADME if the ADME test ran first."""
    assert (
        classify_modality(
            "Clearance of Mycobacterium tuberculosis H37Rv in BALB/c mouse lung",
            "ORGANISM",
            "Mus musculus",
        )
        == "in_vivo_efficacy"
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


def _campaign() -> tuple[list[dict], dict[str, dict]]:
    data = json.loads((FIXTURES / "chembl_campaign_assays.json").read_text())
    return data["assays"], data["targets"]


def test_the_campaign_is_the_document_and_its_stages_are_the_assays():
    assays, targets = _campaign()
    rows = normalize_campaign_assays(assays, targets)
    assert {row["screen_id"] for row in rows} == {"chembl:CHEMBL_DOC1"}
    assert len(rows) == 7
    assert rows[0]["stage_id"] == "chembl:CHEMBL100"


def test_every_modality_in_one_paper_is_kept_apart():
    assays, targets = _campaign()
    by_assay = {row["assay_chembl_id"]: row for row in normalize_campaign_assays(assays, targets)}
    assert by_assay["CHEMBL100"]["modality"] == "phenotypic_mtb"
    assert by_assay["CHEMBL101"]["modality"] == "biochemical_mtb"
    assert by_assay["CHEMBL102"]["modality"] == "mammalian_cytotox"
    assert by_assay["CHEMBL103"]["modality"] == "adme"
    assert by_assay["CHEMBL104"]["modality"] == "in_vivo_efficacy"
    # A selectivity panel against another organism is not Mtb evidence.
    assert by_assay["CHEMBL105"]["modality"] == "other_pathogen"


def test_a_derived_index_is_flagged_and_not_given_a_modality_of_its_own():
    assays, targets = _campaign()
    by_assay = {row["assay_chembl_id"]: row for row in normalize_campaign_assays(assays, targets)}
    assert by_assay["CHEMBL106"]["derived"] is True
    assert by_assay["CHEMBL106"]["modality"] == "other"
    # A ratio of two other assays holds no position in a funnel: NULL, not `primary`, so a
    # count of primary screens never has to remember to exclude it.
    assert by_assay["CHEMBL106"]["stage"] is None
    # Everything else in the paper is a measurement, and every measurement has a stage.
    rows = normalize_campaign_assays(assays, targets)
    assert sum(row["derived"] for row in rows) == 1
    assert all(row["stage"] for row in rows if not row["derived"])


def test_a_whole_cell_stage_keeps_its_condition_and_strain():
    assays, targets = _campaign()
    by_assay = {row["assay_chembl_id"]: row for row in normalize_campaign_assays(assays, targets)}
    # The existing condition classifier, reused: this one names no medium.
    assert by_assay["CHEMBL100"]["assay_condition"] == "unspecified"
    assert by_assay["CHEMBL100"]["strain"] == "H37Rv"
    # A biochemical assay on purified protein has no growth condition at all.
    assert by_assay["CHEMBL101"]["assay_condition"] is None


def test_a_stage_carries_its_assay_and_target_record_unchanged():
    assays, targets = _campaign()
    by_assay = {row["assay_chembl_id"]: row for row in normalize_campaign_assays(assays, targets)}
    vero = by_assay["CHEMBL102"]
    assert vero["document_chembl_id"] == "CHEMBL_DOC1"
    assert vero["description"] == (
        "Cytotoxicity against african green monkey Vero cells after 72 hrs by MTT assay"
    )
    assert vero["target_chembl_id"] == "CHEMBL_VERO"
    assert vero["target_type"] == "CELL-LINE"
    assert vero["target_organism"] == "Chlorocebus aethiops"
    # A microsome assay names no target, and none is invented for it.
    microsomes = by_assay["CHEMBL103"]
    assert (microsomes["target_chembl_id"], microsomes["target_type"]) == (None, None)
    assert microsomes["target_organism"] is None


def test_a_stage_follows_the_modality_read_from_the_target_not_the_prose_alone():
    """The prose says nothing about cells; the CELL-LINE target does. The stage has to be
    derived from the modality the target settled, or the two columns disagree."""
    assay = {
        "assay_chembl_id": "CHEMBL1",
        "document_chembl_id": "CHEMBL_DOC1",
        "target_chembl_id": "CHEMBL_HEK",
        "description": "Antiproliferative activity",
    }
    targets = {"CHEMBL_HEK": {"target_type": "CELL-LINE", "organism": "Homo sapiens"}}
    (row,) = normalize_campaign_assays([assay], targets)
    assert row["modality"] == "mammalian_cytotox"
    assert row["stage"] == "profiling"
    # The fixture's own profiling rows, so the column is checked against a whole paper.
    assays, fixture_targets = _campaign()
    stages = {
        r["assay_chembl_id"]: r["stage"] for r in normalize_campaign_assays(assays, fixture_targets)
    }
    assert [stages[a] for a in ("CHEMBL100", "CHEMBL101", "CHEMBL105")] == ["primary"] * 3
    assert [stages[a] for a in ("CHEMBL102", "CHEMBL103", "CHEMBL104")] == ["profiling"] * 3


def _digest(batch: list[str], fields: str) -> str:
    return hashlib.sha1(f"{','.join(batch)}|{fields}".encode()).hexdigest()[:10]


@pytest.mark.parametrize(
    ("fetch_all", "endpoint", "key", "fields", "dest"),
    [
        (
            chembl.campaign_assays,
            "assay",
            "assays",
            chembl.CAMPAIGN_ASSAY_FIELDS,
            "campaigns/assays",
        ),
        (
            chembl.campaign_activities,
            "activity",
            "activities",
            chembl.CAMPAIGN_ACTIVITY_FIELDS,
            "campaigns/activities",
        ),
    ],
    ids=["assays", "activities"],
)
def test_a_campaign_is_fetched_by_document_in_batches_of_ten(
    monkeypatch: pytest.MonkeyPatch, fetch_all, endpoint, key, fields, dest
):
    """The query is keyed on the document, not the target: that is the whole difference
    between the 11,686 assays a target query sees and the 38,335 a document holds."""
    calls: list[tuple] = []

    def fake_pages(endpoint, query, key, dest, *, force):
        calls.append((endpoint, query, key, dest, force))
        return [{"from": dest}]

    monkeypatch.setattr(chembl, "pages", fake_pages)
    documents = [f"CHEMBL_DOC{n}" for n in range(23)]
    batches = [documents[:10], documents[10:20], documents[20:]]
    assert len(fetch_all(documents, force=True)) == 3
    assert [call[0] for call in calls] == [endpoint] * 3
    # The payload key is what `pages` reads out of the response; the wrong one is a KeyError.
    assert [call[2] for call in calls] == [key] * 3
    assert [call[3] for call in calls] == [f"{dest}-{_digest(batch, fields)}" for batch in batches]
    assert all(call[4] is True for call in calls)
    assert calls[0][1] == f"document_chembl_id__in={','.join(documents[:10])}&only={fields}"
    assert calls[2][1].startswith(f"document_chembl_id__in={','.join(documents[20:])}&")
    assert not any("target_chembl_id=" in call[1] for call in calls)


def test_a_campaign_batch_is_cached_by_what_it_holds_not_where_it_sits(
    monkeypatch: pytest.MonkeyPatch,
):
    """The document list comes from live, uncached fetches, so it differs between builds: a
    new target, a skipped batch. A cache named by position would hand one batch another's
    pages, and the documents that moved would lose their assays with no error."""
    dests: list[str] = []

    def fake_pages(endpoint, query, key, dest, *, force):
        dests.append(dest)
        return []

    monkeypatch.setattr(chembl, "pages", fake_pages)
    documents = [f"CHEMBL_DOC{n:02d}" for n in range(20)]
    chembl.campaign_assays(documents)
    first, second = dests
    dests.clear()
    # The second batch alone: same documents, now first in the list.
    chembl.campaign_assays(documents[10:])
    assert dests == [second]
    # One document changed, wherever it sits in the batch: a different batch, so a different
    # cache name. The last position alone would let a name built from the last document pass.
    for position in (0, 5, 9):
        dests.clear()
        changed = documents[10:]
        changed[position] = "CHEMBL_NEW"
        chembl.campaign_assays(changed)
        assert dests[0] not in (first, second), position


@pytest.mark.parametrize("fetch_all", [chembl.campaign_assays, chembl.campaign_activities])
def test_a_campaign_batch_is_cached_by_the_columns_it_asked_for(
    monkeypatch: pytest.MonkeyPatch, fetch_all
):
    """The name must follow the field list as well as the documents. The URL is checked by
    `fetch` too, but a name that ignores the columns would let two column sets overwrite
    each other's pages, and a rolled-back list re-download what it already had."""
    dests: list[str] = []
    monkeypatch.setattr(
        chembl, "pages", lambda endpoint, query, key, dest, *, force: dests.append(dest) or []
    )
    documents = [f"CHEMBL_DOC{n:02d}" for n in range(10)]
    fetch_all(documents)
    monkeypatch.setattr(
        chembl, "CAMPAIGN_ASSAY_FIELDS", chembl.CAMPAIGN_ASSAY_FIELDS + ",assay_type"
    )
    monkeypatch.setattr(
        chembl, "CAMPAIGN_ACTIVITY_FIELDS", chembl.CAMPAIGN_ACTIVITY_FIELDS + ",activity_type"
    )
    fetch_all(documents)
    assert len(set(dests)) == 2


def test_document_meta_is_keyed_by_document_and_keeps_the_type(monkeypatch: pytest.MonkeyPatch):
    seen: list[str] = []

    def fake_many(urls, **kwargs):
        seen.extend(urls)
        document = {"document_chembl_id": "CHEMBL_DOC1", "doc_type": "PUBLICATION"}
        dataset = {"document_chembl_id": "CHEMBL_DS", "doc_type": "DATASET"}
        document |= {"title": "A paper", "year": 2019, "pubmed_id": 12345}
        dataset |= {"title": "A library", "year": None, "pubmed_id": None}
        return {url: {"documents": [document, dataset]} for url in urls}

    monkeypatch.setattr(chembl, "fetch_json_many", fake_many)
    meta = campaign_document_meta(["CHEMBL_DOC1", "CHEMBL_DS"])
    assert len(seen) == 1
    assert "/document.json?document_chembl_id__in=CHEMBL_DOC1,CHEMBL_DS&" in seen[0]
    assert meta["CHEMBL_DOC1"] == {
        "doc_type": "PUBLICATION",
        "title": "A paper",
        "year": 2019,
        "pubmed_id": "12345",
    }
    assert meta["CHEMBL_DS"]["doc_type"] == "DATASET"
    assert meta["CHEMBL_DS"]["pubmed_id"] is None


def test_only_publications_are_campaigns_because_datasets_come_in_through_pubchem():
    """CHEMBL3988442 is Dundee's Small-Polar-MMV library, a DATASET with 1,413,047 activity
    rows (1,414 pages), and it is already in PubChem as AIDs 1671154-1671185."""
    meta = {
        "CHEMBL_PAPER1": {"doc_type": "PUBLICATION"},
        "CHEMBL3988442": {"doc_type": "DATASET"},
        "CHEMBL_PAPER2": {"doc_type": "PUBLICATION"},
        "CHEMBL_PATENT": {"doc_type": "PATENT"},
        "CHEMBL_UNTYPED": {"doc_type": None},
    }
    assert campaign_publications(list(meta), meta) == ["CHEMBL_PAPER1", "CHEMBL_PAPER2"]


def test_a_candidate_with_no_record_is_an_error_not_a_dropped_campaign():
    """`fetch_json_many` skips a batch that fails. Its documents then have no type, and
    treating that as "not a publication" would lose their campaigns without a word."""
    meta = {"CHEMBL_PAPER1": {"doc_type": "PUBLICATION"}}
    with pytest.raises(RuntimeError, match="CHEMBL_LOST"):
        campaign_publications(["CHEMBL_PAPER1", "CHEMBL_LOST"], meta)


def test_campaign_documents_are_the_documents_behind_whole_cell_activities():
    activities = [
        {"assay_chembl_id": "A", "evidence": "whole_cell", "document_chembl_id": "CHEMBL_DOC1"},
        {"assay_chembl_id": "B", "evidence": "direct", "document_chembl_id": "CHEMBL_DOC2"},
        {"assay_chembl_id": "C", "evidence": "whole_cell", "document_chembl_id": None},
    ]
    assert campaign_documents(activities) == ["CHEMBL_DOC1"]


def test_campaign_documents_are_sorted_and_unique():
    """The sort is what makes batch composition, and so the cache names, the same on every
    build: a set's order changes with the process. A document with many assays repeats."""
    documents = ["CHEMBL_DOC6", "CHEMBL_DOC2", "CHEMBL_DOC5", "CHEMBL_DOC1", "CHEMBL_DOC4"]
    activities = [
        {"evidence": "whole_cell", "document_chembl_id": d} for d in [*documents, *documents[:2]]
    ]
    assert campaign_documents(activities) == sorted(documents)


# --- the three tables -----------------------------------------------------------
#
# ChEMBL's rows and PubChem's go into one file per table, so they must carry one set of
# keys: DuckDB types a column from the rows it sees, and a key that only some rows carry
# is NULL for all of them with no error. The sets below are the contract, spelled out.

SCREEN_KEYS = {
    "screen_id",
    "aid",
    "title",
    "depositor",
    "deposit_kind",
    "library_name",
    "library_size_stated",
    "year",
    "n_stages",
    "n_tested",
    "n_active",
    "n_inactive",
    "n_inconclusive",
    "n_unspecified",
    "outcome_stated",
    "outcome_method",
    "stages_source",
    "project_declared",
    "modalities",
    "document_chembl_id",
    "pubmed_id",
    "targets",
    "licence",
}
STAGE_KEYS = {
    "stage_id",
    "screen_id",
    "assay_chembl_id",
    "document_chembl_id",
    "stage",
    "modality",
    "description",
    "target_chembl_id",
    "target_type",
    "target_organism",
    "derived",
    "assay_condition",
    "strain",
    "n_tested",
    "n_active",
}
RESULT_KEYS = {
    "stage_id",
    "screen_id",
    "pubchem_cid",
    "pubchem_sid",
    "molecule_chembl_id",
    "outcome",
    "activity_score",
    "endpoint",
    "standard_value",
    "standard_units",
    "standard_relation",
    "result_tag",
    "activity_id",
}


def _documents() -> dict[str, dict]:
    return {
        "CHEMBL_DOC1": {
            "year": 2019,
            "title": "A paper",
            "doc_type": "PUBLICATION",
            "pubmed_id": "12345",
        }
    }


def _activities() -> list[dict]:
    """ChEMBL sends `standard_value` as a string."""
    return [
        {
            "activity_id": 11,
            "assay_chembl_id": "CHEMBL100",
            "molecule_chembl_id": "M1",
            "standard_type": "MIC",
            "standard_relation": "=",
            "standard_value": "0.5",
            "standard_units": "ug.mL-1",
        },
        {
            "activity_id": 12,
            "assay_chembl_id": "CHEMBL100",
            "molecule_chembl_id": "M2",
            "standard_type": "MIC",
            "standard_relation": ">",
            "standard_value": "100.0",
            "standard_units": "ug.mL-1",
        },
        {
            "activity_id": 13,
            "assay_chembl_id": "CHEMBL102",
            "molecule_chembl_id": "M1",
            "standard_type": "CC50",
            "standard_relation": "=",
            "standard_value": "20.0",
            "standard_units": "uM",
        },
    ]


def _stages() -> list[dict]:
    assays, targets = _campaign()
    return normalize_campaign_assays(assays, targets)


def test_a_campaign_row_counts_its_stages_and_states_where_they_came_from():
    screens = chembl.campaign_screens(_stages(), _activities(), _documents())
    assert len(screens) == 1
    screen = screens[0]
    assert screen["screen_id"] == "chembl:CHEMBL_DOC1"
    assert screen["deposit_kind"] == "publication"
    assert (screen["n_stages"], screen["n_tested"]) == (7, 2)
    assert (screen["title"], screen["year"], screen["pubmed_id"]) == ("A paper", 2019, "12345")
    assert screen["document_chembl_id"] == "CHEMBL_DOC1"
    assert (screen["depositor"], screen["licence"]) == ("Scientific Literature", "CC BY-SA 3.0")
    # ChEMBL states no activity call anywhere, so there is none to report.
    assert screen["outcome_stated"] is False
    assert screen["n_active"] is None
    assert screen["n_inactive"] is None
    assert screen["n_inconclusive"] is None
    assert screen["outcome_method"] is None
    # Classified from the depositor's prose, and the table says so.
    assert screen["stages_source"] == "from_prose"
    assert screen["project_declared"] is False
    # A paper has no AID and no single target, and a literature campaign has no library.
    assert screen["aid"] is None
    assert screen["targets"] == []
    assert (screen["library_name"], screen["library_size_stated"]) == (None, None)


def test_every_compound_of_a_literature_campaign_is_unspecified_not_missing():
    """With no calls stated, all `n_tested` compounds are in the one bucket that says so.
    That keeps `n_active + n_inactive + n_inconclusive + n_unspecified == n_tested` true on
    both sides, which is what makes a partial deposit detectable."""
    screen = chembl.campaign_screens(_stages(), _activities(), _documents())[0]
    assert screen["n_unspecified"] == screen["n_tested"] == 2


def test_the_modalities_a_campaign_reached_are_listed_not_scored():
    screen = chembl.campaign_screens(_stages(), [], _documents())[0]
    assert screen["modalities"] == [
        "adme",
        "biochemical_mtb",
        "in_vivo_efficacy",
        "mammalian_cytotox",
        "other",
        "other_pathogen",
        "phenotypic_mtb",
    ]
    # A list, so a reader can see what was measured. No count is summed into
    # a completeness figure.
    assert "completeness" not in screen
    assert "score" not in screen
    assert screen["n_tested"] == screen["n_unspecified"] == 0


def test_a_campaign_whose_document_record_is_missing_is_an_error_not_a_guess():
    with pytest.raises(KeyError, match="CHEMBL_DOC1"):
        chembl.campaign_screens(_stages(), _activities(), {})


def test_a_stage_counts_the_compounds_tested_in_its_own_assay():
    stages = chembl.stamp_stage_counts(_stages(), _activities())
    counts = {stage["assay_chembl_id"]: stage["n_tested"] for stage in stages}
    assert counts["CHEMBL100"] == 2
    assert counts["CHEMBL102"] == 1
    # An assay with no activity row has no compound on record, which is a count of zero.
    assert counts["CHEMBL101"] == 0
    # ChEMBL states no calls, so there is no count of actives: NULL, never 0.
    assert {stage["n_active"] for stage in stages} == {None}


def test_a_compound_measured_twice_in_one_assay_is_tested_once():
    activities = [*_activities(), {**_activities()[0], "activity_id": 99, "standard_type": "MBC"}]
    stages = chembl.stamp_stage_counts(_stages(), activities)
    assert {s["assay_chembl_id"]: s["n_tested"] for s in stages}["CHEMBL100"] == 2


def test_an_activity_outside_the_campaigns_assays_is_not_counted():
    stray = {"activity_id": 77, "assay_chembl_id": "CHEMBL999", "molecule_chembl_id": "M9"}
    stages = chembl.stamp_stage_counts(_stages(), [*_activities(), stray])
    assert sum(stage["n_tested"] for stage in stages) == 3
    screen = chembl.campaign_screens(stages, [*_activities(), stray], _documents())[0]
    assert screen["n_tested"] == 2


def test_a_results_row_is_one_activity_with_the_value_as_a_number():
    stages = _stages()
    rows = chembl.campaign_results(stages, _activities())
    assert [row["activity_id"] for row in rows] == [11, 12, 13]
    first, censored, cytotox = rows
    assert first["stage_id"] == "chembl:CHEMBL100"
    assert first["screen_id"] == "chembl:CHEMBL_DOC1"
    assert first["molecule_chembl_id"] == "M1"
    # ChEMBL sends "0.5". A string in some rows and a float in others is a column DuckDB
    # cannot type, and PubChem's side is a float.
    assert first["standard_value"] == 0.5
    assert isinstance(first["standard_value"], float)
    assert (first["endpoint"], first["standard_relation"], first["standard_units"]) == (
        "MIC",
        "=",
        "ug.mL-1",
    )
    # `>` 100 is a bound, stored with its relation and not as a measurement.
    assert (censored["standard_relation"], censored["standard_value"]) == (">", 100.0)
    assert (cytotox["stage_id"], cytotox["endpoint"]) == ("chembl:CHEMBL102", "CC50")


def test_chembl_states_no_outcome_and_the_pubchem_columns_are_empty():
    for row in chembl.campaign_results(_stages(), _activities()):
        assert row["outcome"] is None
        assert row["activity_score"] is None
        assert row["pubchem_cid"] is None
        assert row["pubchem_sid"] is None
        assert row["result_tag"] is None


def test_an_activity_with_no_compound_or_no_campaign_assay_has_no_results_row():
    activities = [
        *_activities(),
        {"activity_id": 20, "assay_chembl_id": "CHEMBL100", "molecule_chembl_id": None},
        {"activity_id": 21, "assay_chembl_id": "CHEMBL999", "molecule_chembl_id": "M1"},
    ]
    assert [row["activity_id"] for row in chembl.campaign_results(_stages(), activities)] == [
        11,
        12,
        13,
    ]


def _patch_chembl_network(monkeypatch: pytest.MonkeyPatch, calls: dict) -> None:
    meta = {
        "CHEMBL_DOC1": _documents()["CHEMBL_DOC1"],
        "CHEMBL3988442": {"doc_type": "DATASET", "title": "A library", "year": None},
    }
    assays, targets = _campaign()

    def fake_meta(documents):
        calls["meta"] = list(documents)
        return meta

    def fake_assays(documents, *, force):
        calls["assays"] = (list(documents), force)
        return assays

    def fake_activities(documents, *, force):
        calls["activities"] = (list(documents), force)
        return _activities()

    monkeypatch.setattr(chembl, "campaign_document_meta", fake_meta)
    monkeypatch.setattr(chembl, "campaign_assays", fake_assays)
    monkeypatch.setattr(chembl, "campaign_activities", fake_activities)
    monkeypatch.setattr(chembl, "campaign_targets", lambda assays: targets)
    monkeypatch.setattr(chembl, "release_from_api", lambda: "ChEMBL_37 (2026-05-01)")


def test_only_publications_have_their_activities_fetched_and_the_rows_say_chembl(monkeypatch):
    """CHEMBL3988442 is a DATASET with 1,413,047 activity rows: one batch of ten documents
    pages over it ~1,414 times. The filter has to come before the fetch, and the dataset
    reaches the store through PubChem."""
    calls: dict = {}
    _patch_chembl_network(monkeypatch, calls)
    whole_cell = [
        {"evidence": "whole_cell", "document_chembl_id": "CHEMBL_DOC1"},
        {"evidence": "whole_cell", "document_chembl_id": "CHEMBL3988442"},
        {"evidence": "direct", "document_chembl_id": "CHEMBL_OTHER"},
    ]
    screens, stages, results = chembl.build_campaigns(
        whole_cell, retrieved_at="2026-10-11", force=True
    )
    assert calls["meta"] == ["CHEMBL3988442", "CHEMBL_DOC1"]
    assert calls["assays"] == (["CHEMBL_DOC1"], True)
    assert calls["activities"] == (["CHEMBL_DOC1"], True)
    assert [row["screen_id"] for row in screens] == ["chembl:CHEMBL_DOC1"]
    assert len(stages) == 7 and len(results) == 3
    assert {s["assay_chembl_id"]: s["n_tested"] for s in stages}["CHEMBL100"] == 2
    # Each row says where it came from: this is a ChEMBL paper, whatever ingester wrote it.
    for row in [*screens, *stages, *results]:
        assert row["source"] == "chembl"
        assert row["source_version"] == "ChEMBL_37 (2026-05-01)"
        assert row["retrieved_at"] == "2026-10-11"


def test_a_lost_document_record_stops_the_campaign_build(monkeypatch):
    calls: dict = {}
    _patch_chembl_network(monkeypatch, calls)
    monkeypatch.setattr(chembl, "campaign_document_meta", lambda documents: {})
    whole_cell = [{"evidence": "whole_cell", "document_chembl_id": "CHEMBL_DOC1"}]
    with pytest.raises(RuntimeError, match="CHEMBL_DOC1"):
        chembl.build_campaigns(whole_cell, retrieved_at="2026-10-11")
    assert "activities" not in calls


class _Downloaded:
    """What `pubchem.fetch_results` returns, as far as `build` reads it."""

    def __init__(self, path: Path) -> None:
        self.path = path


def _eutils(aid: str, members: list[str]) -> dict:
    """An eLink answer for `aid`: a linkset naming the AID, with its project's members."""
    linkset = {"ids": [aid]}
    if members:
        linkset["linksetdbs"] = [{"links": members}]
    return {"linksets": [linkset]}


def _fake_pubchem(monkeypatch, tmp_path: Path, *, project: list[str] | None = None) -> dict:
    """Two campaigns' worth of PubChem, from the committed fixtures and no network.

    The result files are trimmed to five rows each, so their summary counts are trimmed to
    match: AID 1626 has 5 SIDs (2 active, 2 inactive, 1 inconclusive) and AID 1671170 has
    3 (a SID on two rows, a second SID on two, and one with no CID).
    """
    from atlas.sources import pubchem

    base = {
        s["AID"]: s
        for s in json.loads((FIXTURES / "pubchem_aid_summary.json").read_text())["AssaySummaries"][
            "AssaySummary"
        ]
    }
    summaries = [
        {
            **base[1626],
            "SIDCountAll": 5,
            "SIDCountActive": 2,
            "SIDCountInactive": 2,
            "SIDCountInconclusive": 1,
            "SIDCountUnspecified": 0,
        },
        {**base[1671170], "SIDCountAll": 3, "SIDCountUnspecified": 3},
    ]
    files = {
        "1626": FIXTURES / "pubchem_aid_results.csv",
        "1671170": FIXTURES / "pubchem_aid_unspecified.csv",
    }
    monkeypatch.setattr(pubchem, "fetch_aids", lambda *, force=False: ["1626", "1671170"])
    monkeypatch.setattr(pubchem, "fetch_summaries", lambda aids, *, force=False: summaries)
    monkeypatch.setattr(
        pubchem, "fetch_project", lambda aid, *, force=False: _eutils(aid, project or [])
    )
    monkeypatch.setattr(
        pubchem, "fetch_results", lambda aid, *, force=False: _Downloaded(files[aid])
    )

    bridge = tmp_path / "bridge.txt"
    bridge.write_text(
        "From src:'1'\tTo src:'22'\nCHEMBL1461400\t911287\nCHEMBL533602\t3803930\n"
        "CHEMBL_NOT_IN_ANY_SCREEN\t999999999\n"
    )
    asked: dict = {}
    real = pubchem.unichem.chembl_by_cid

    def spy(path, *, only=None):
        asked["only"] = set(only)
        return real(path, only=only)

    monkeypatch.setattr(pubchem.unichem, "chembl_by_cid", spy)
    return {"bridge": bridge, "asked": asked, "store": tmp_path / "store"}


def _build(monkeypatch, tmp_path: Path, **kwargs):
    from atlas.sources import pubchem

    env = _fake_pubchem(monkeypatch, tmp_path, **kwargs)
    _patch_chembl_network(monkeypatch, {})
    screens, stages, results = chembl.build_campaigns(
        [{"evidence": "whole_cell", "document_chembl_id": "CHEMBL_DOC1"}],
        retrieved_at="2026-10-09",
    )
    paths = pubchem.build(
        retrieved_at="2026-10-11",
        bridge=env["bridge"],
        rv_by_acc={"P9WFT3": ["Rv2348c"]},
        extra_screens=screens,
        extra_stages=stages,
        extra_results=results,
        store=env["store"],
    )
    return env, paths


def _sql(env: dict, query: str) -> list[tuple]:
    import duckdb

    store = env["store"]
    for name in ("screens", "screen_stages", "screen_results"):
        query = query.replace(f"<{name}>", f"'{store / (name + '.parquet')}'")
    return duckdb.sql(query).fetchall()


def test_a_declared_project_is_one_campaign_row_and_no_result_is_orphaned(monkeypatch, tmp_path):
    """The two PubChem AIDs share a project (synthetic here; 588335 and 588726 do in
    life), the ChEMBL paper is a third thing. `screen_id` is the table's key, so a row per
    AID would write the campaign twice, and a result still keyed on its AID would match no
    campaign at all."""
    env, paths = _build(monkeypatch, tmp_path, project=["1626", "1671170"])
    assert [p.name for p in paths] == [
        "screens.parquet",
        "screen_stages.parquet",
        "screen_results.parquet",
    ]
    screens = _sql(
        env,
        "SELECT screen_id, aid, n_stages, n_tested, project_declared FROM <screens> "
        "ORDER BY screen_id",
    )
    assert screens == [
        ("chembl:CHEMBL_DOC1", None, 7, 2, False),
        ("pubchem:project:1626", None, 2, 8, True),
    ]
    stages = _sql(env, "SELECT stage_id, screen_id FROM <screen_stages> ORDER BY stage_id")
    assert [s for s in stages if s[0].startswith("pubchem")] == [
        ("pubchem:1626", "pubchem:project:1626"),
        ("pubchem:1671170", "pubchem:project:1626"),
    ]
    orphan_results = (
        "SELECT count(*) FROM <screen_results> r LEFT JOIN <screens> s USING (screen_id)"
    )
    assert _sql(env, orphan_results + " WHERE s.screen_id IS NULL") == [(0,)]
    orphan_stages = (
        "SELECT count(*) FROM <screen_results> r LEFT JOIN <screen_stages> s USING (stage_id)"
    )
    assert _sql(env, orphan_stages + " WHERE s.stage_id IS NULL") == [(0,)]
    assert _sql(env, "SELECT count(*) FROM <screen_results>") == [(13,)]
    # A campaign's stage count is the stages it has, in the table.
    assert _sql(
        env,
        "SELECT count(*) FROM <screens> c WHERE n_stages != "
        "(SELECT count(*) FROM <screen_stages> s WHERE s.screen_id = c.screen_id)",
    ) == [(0,)]


def test_assays_with_no_declared_project_are_each_their_own_campaign(monkeypatch, tmp_path):
    env, _ = _build(monkeypatch, tmp_path)
    assert _sql(
        env, "SELECT screen_id, aid, project_declared FROM <screens> ORDER BY screen_id"
    ) == [
        ("chembl:CHEMBL_DOC1", None, False),
        ("pubchem:1626", "1626", False),
        ("pubchem:1671170", "1671170", False),
    ]


def test_each_row_says_which_source_it_came_from(monkeypatch, tmp_path):
    """`provenance()` reads a table's first row, so PubChem's come first: the freshness
    probe for PubChem compares against that row."""
    from atlas.store import provenance

    env, _ = _build(monkeypatch, tmp_path)
    for table in ("screens", "screen_stages", "screen_results"):
        rows = _sql(env, f"SELECT source, source_version, retrieved_at FROM <{table}>")
        assert {r[0] for r in rows} == {"pubchem", "chembl"}
        assert {(r[0], r[1], str(r[2])) for r in rows} == {
            (
                "pubchem",
                "E-utilities txid1773[ORGN] AND 10000:100000000[TSC], 2 AIDs",
                "2026-10-11",
            ),
            ("chembl", "ChEMBL_37 (2026-05-01)", "2026-10-09"),
        }
        version, retrieved = provenance(table, store=env["store"])
        assert version.startswith("E-utilities")
        assert str(retrieved) == "2026-10-11"


def test_the_columns_keep_their_types_when_one_source_leaves_them_empty(monkeypatch, tmp_path):
    """The ChEMBL rows have no outcome, CID or SID, and the PubChem 1671170 rows no outcome
    at all. A column that is NULL in what DuckDB sees first types as JSON and stores
    every later string in quotation marks, so `outcome = 'active'` finds nothing."""
    import duckdb

    env, _ = _build(monkeypatch, tmp_path)

    def types(table):
        path = env["store"] / f"{table}.parquet"
        return dict(
            duckdb.sql(f"SELECT column_name, column_type FROM (DESCRIBE '{path}')").fetchall()
        )

    results = types("screen_results")
    assert results["outcome"] == "VARCHAR"
    assert results["pubchem_cid"] == results["pubchem_sid"] == "VARCHAR"
    assert (results["activity_id"], results["result_tag"]) == ("BIGINT", "BIGINT")
    assert results["standard_value"] == "DOUBLE"
    assert results["activity_score"] == "BIGINT"
    screens = types("screens")
    assert screens["modalities"] == "VARCHAR[]"
    assert screens["targets"].startswith("STRUCT(") and screens["targets"].endswith("[]")
    assert (screens["n_active"], screens["n_tested"], screens["year"]) == (
        "BIGINT",
        "BIGINT",
        "BIGINT",
    )
    assert _sql(env, "SELECT count(*) FROM <screen_results> WHERE outcome = 'active'") == [(2,)]
    assert _sql(env, "SELECT count(*) FROM <screen_results> WHERE outcome = 'inactive'") == [(2,)]


def test_the_compounds_of_a_campaign_are_bridged_and_only_the_wanted_cids_are_read(
    monkeypatch, tmp_path
):
    env, _ = _build(monkeypatch, tmp_path)
    # Every CID in either results file, and nothing the bridge happens to hold besides.
    assert env["asked"]["only"] == {
        "911287",
        "135458645",
        "3803930",
        "7314608",
        "56761864",
        "97398757",
    }
    mapped = _sql(
        env,
        "SELECT pubchem_cid, molecule_chembl_id FROM <screen_results> "
        "WHERE stage_id = 'pubchem:1626' ORDER BY result_tag",
    )
    assert mapped == [
        ("911287", "CHEMBL1461400"),
        ("135458645", None),
        ("3803930", "CHEMBL533602"),
        ("7314608", None),
        ("135458645", None),
    ]


def test_a_target_reaches_the_loci_the_crosswalk_gives_it(monkeypatch, tmp_path):
    env, _ = _build(monkeypatch, tmp_path)
    targets = _sql(
        env,
        "SELECT targets[1].accession, targets[1].rv_ids, targets[1].accession_kind "
        "FROM <screens> WHERE screen_id = 'pubchem:1671170'",
    )
    assert targets == [("P9WFT3", ["Rv2348c"], "uniprot")]
    assert _sql(
        env, "SELECT len(targets) FROM <screens> WHERE screen_id = 'chembl:CHEMBL_DOC1'"
    ) == [(0,)]


def test_a_download_short_of_its_sids_stops_the_build_and_writes_nothing(monkeypatch, tmp_path):
    """AID 1626's summary counts 6 SIDs but the file holds 5: a truncated download is a
    successful one, and the screen would read as five compounds nobody else tested."""
    from atlas.sources import pubchem

    env = _fake_pubchem(monkeypatch, tmp_path)
    real = pubchem.fetch_summaries
    summaries = [{**s, "SIDCountAll": 6} if s["AID"] == 1626 else s for s in real([])]
    monkeypatch.setattr(pubchem, "fetch_summaries", lambda aids, *, force=False: summaries)
    with pytest.raises(ValueError, match="AID 1626.*5.*6"):
        pubchem.build(
            retrieved_at="2026-10-11", bridge=env["bridge"], rv_by_acc={}, store=env["store"]
        )
    assert not env["store"].exists()


def test_a_chembl_activity_listed_twice_stops_the_build(monkeypatch, tmp_path):
    from atlas.sources import pubchem

    env = _fake_pubchem(monkeypatch, tmp_path)
    twice = chembl.campaign_results(_stages(), _activities())[:1] * 2
    with pytest.raises(ValueError, match="repeats 1 time"):
        pubchem.build(
            retrieved_at="2026-10-11",
            bridge=env["bridge"],
            rv_by_acc={},
            extra_results=twice,
            store=env["store"],
        )


def test_the_evidence_stage_hands_the_campaigns_and_the_crosswalk_to_pubchems_build(
    monkeypatch, evidence_store
):
    """`build_evidence` reaches 17 services and cannot run here, so every other builder is
    stubbed and only this block is real. It reads the store the way a build does."""
    import duckdb

    from atlas import pipeline, store

    monkeypatch.setattr(store, "STORE", evidence_store)
    marker = Path("/built-elsewhere.parquet")
    for module, name in [
        (pipeline.pdb, "build"),
        (pipeline.pdb, "build_ligands"),
        (pipeline.alphafold, "build"),
        (pipeline.essentiality, "build"),
        (pipeline.resistance, "build"),
        (pipeline.conditional, "build"),
        (pipeline.vulnerability, "build"),
        (pipeline.vulnerability, "build_strain"),
        (pipeline.string_db, "build"),
        (pipeline.homology, "build"),
        (pipeline.paralogs, "build"),
        (pipeline.orthologue_structures, "build"),
        (pipeline.precedent, "build"),
    ]:
        monkeypatch.setattr(module, name, lambda *a, **k: marker)
    monkeypatch.setattr(pipeline.chembl, "build_bioactivity", lambda *a, **k: [])
    monkeypatch.setattr(pipeline.mtbtndb, "build", lambda *a, **k: [])

    seen: dict = {}

    def fake_campaigns(activities, **kwargs):
        seen["campaigns"] = (activities, kwargs)
        return ["screen"], ["stage"], ["result"]

    def fake_build(**kwargs):
        seen["build"] = kwargs
        return [Path("/screens.parquet")]

    monkeypatch.setattr(pipeline.chembl, "build_campaigns", fake_campaigns)
    monkeypatch.setattr(pipeline.pubchem, "build", fake_build)
    monkeypatch.setattr(
        pipeline.unichem, "fetch_raw", lambda *, force: _Downloaded(Path("/unichem.txt.gz"))
    )

    paths = pipeline.build_evidence(force=True)

    activities, kwargs = seen["campaigns"]
    wanted = {
        d
        for (d,) in duckdb.sql(
            f"SELECT document_chembl_id FROM '{evidence_store / 'activities.parquet'}' "
            "WHERE evidence = 'whole_cell'"
        ).fetchall()
    }
    assert wanted, "the fixture store must hold a whole-cell activity for this to prove anything"
    assert {row["document_chembl_id"] for row in activities} == wanted
    assert {row["evidence"] for row in activities} == {"whole_cell"}
    assert kwargs == {"retrieved_at": "2026-10-09", "force": True}

    built = seen["build"]
    assert built["bridge"] == Path("/unichem.txt.gz")
    assert (built["extra_screens"], built["extra_stages"], built["extra_results"]) == (
        ["screen"],
        ["stage"],
        ["result"],
    )
    assert built["retrieved_at"] == "2026-10-09" and built["force"] is True
    # The crosswalk's own accession -> loci map, and a shared accession keeps both loci.
    walk = duckdb.sql(
        f"SELECT uniprot_acc, rv_id FROM '{evidence_store / 'crosswalk.parquet'}' "
        "WHERE uniprot_acc IS NOT NULL"
    ).fetchall()
    assert {a: sorted(v) for a, v in built["rv_by_acc"].items()} == {
        a: sorted(rv for acc, rv in walk if acc == a) for a in {acc for acc, _ in walk}
    }
    assert Path("/screens.parquet") in paths


def test_the_diff_compares_a_result_on_the_key_that_tells_rows_apart(tmp_path):
    """A PubChem row has a NULL `activity_id` and a ChEMBL row a NULL `result_tag`, and EXCEPT
    treats two NULLs as equal, so the composite key compares. A key that needed `NULL = NULL`
    to be true would report every row as both added and removed."""
    from atlas import storediff
    from atlas.sources import pubchem
    from atlas.store import write_parquet

    assert storediff.KEYS["screens"] == ("screen_id",)
    assert storediff.KEYS["screen_stages"] == ("stage_id",)
    assert storediff.KEYS["screen_results"] == pubchem.RESULT_KEY

    pubchem_rows = list(pubchem.normalize_results(FIXTURES / "pubchem_aid_results.csv", "1626", {}))
    chembl_rows = chembl.campaign_results(_stages(), _activities())
    old, new = tmp_path / "old", tmp_path / "new"
    for store, rows in ((old, pubchem_rows + chembl_rows), (new, pubchem_rows + chembl_rows[:-1])):
        write_parquet(
            "screen_results",
            rows,
            source="x",
            source_version="1",
            retrieved_at="2026-10-11",
            store=store,
        )
    (diff,) = storediff.compare(old, new)
    assert (diff.before, diff.after, diff.added, diff.removed) == (8, 7, 0, 1)
    assert diff.examples_removed == ["chembl:CHEMBL102 None 13"]


def test_both_sources_emit_one_key_set_per_table():
    """DuckDB infers the schema from the rows it sees. A column present in only some rows
    types as NULL for all of them and no error is raised, so a key set that drifts between
    the two ingesters loses a column quietly. This is the test that stops that."""
    from atlas.sources import pubchem

    stages = _stages()
    summaries = json.loads((FIXTURES / "pubchem_aid_summary.json").read_text())
    summaries = summaries["AssaySummaries"]["AssaySummary"]
    pubchem_screens = pubchem.normalize_screens(summaries)

    chembl_screens = chembl.campaign_screens(stages, _activities(), _documents())
    assert set(chembl_screens[0]) == set(pubchem_screens[0]) == SCREEN_KEYS
    # The campaign row `build` writes is built from the same row, and keeps the set.
    merged = pubchem.campaign_row("pubchem:project:1", pubchem_screens[:2], declared=True)
    assert set(merged) == SCREEN_KEYS

    pubchem_stage = pubchem.stage_row(pubchem_screens[0], "pubchem:1626")
    assert set(stages[0]) == set(pubchem_stage) == STAGE_KEYS

    pubchem_rows = list(pubchem.normalize_results(FIXTURES / "pubchem_aid_results.csv", "1626", {}))
    chembl_rows = chembl.campaign_results(stages, _activities())
    assert {frozenset(row) for row in chembl_rows + pubchem_rows} == {frozenset(RESULT_KEYS)}
