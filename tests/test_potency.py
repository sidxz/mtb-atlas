"""Whole-cell potency: the MIC conversion and the condition it was measured in.

The conversion is the only place in the pipeline that turns a reported number
into a different number, so it is the one that has to be wrong loudly rather
than quietly. Every case here is a shape seen in the live store.
"""

from __future__ import annotations

import math

from atlas.sources.chembl import annotate_activities, classify_condition, pmic


def test_molar_units_need_no_weight():
    # 10 nM -> 1e-8 M -> 8.0. The commonest MIC unit in the store (2,446 rows).
    assert pmic("MIC", "=", 10.0, "nM", None) == (8.0, "nM")
    assert pmic("MIC90", "=", 1.0, "uM", None) == (6.0, "uM")


def test_mass_units_convert_through_molecular_weight():
    # 1 ug/mL of a 500 g/mol compound is 2e-6 M, so pMIC 5.699.
    value, basis = pmic("MIC", "=", 1.0, "ug.mL-1", 500.0)
    assert value == round(-math.log10(2e-6), 3)
    # The basis names the weight used, because the number is not in the source.
    assert "MW 500.0" in basis


def test_mass_units_without_a_weight_give_nothing():
    assert pmic("MIC", "=", 1.0, "ug.mL-1", None) == (None, None)
    assert pmic("MIC", "=", 1.0, "ug.mL-1", 0.0) == (None, None)


def test_censored_values_get_no_potency():
    """`MIC > 64` means it did not inhibit at 64, not that it inhibited at 64.

    A fifth of the store's MICs are censored this way. Converting them would
    pull every aggregate toward a potency nobody measured.
    """
    assert pmic("MIC", ">", 64.0, "ug.mL-1", 500.0) == (None, None)
    assert pmic("MIC", "<", 0.5, "nM", None) == (None, None)
    assert pmic("MIC", None, 10.0, "nM", None) == (None, None)


def test_only_the_mic_family_converts():
    # Thresholded MICs are exact values at a stated inhibition level.
    assert pmic("MIC>90", "=", 10.0, "nM", None)[0] == 8.0
    assert pmic("MIC99", "=", 10.0, "nM", None)[0] == 8.0
    # Already a log: converting would double-log it.
    assert pmic("pMIC", "=", 6.0, "nM", None) == (None, None)
    assert pmic("-logMIC", "=", 6.0, "nM", None) == (None, None)
    # A different endpoint, not an inhibitory concentration.
    assert pmic("MBC", "=", 10.0, "nM", None) == (None, None)
    # Affinity endpoints keep their own pchembl_value and are not MICs.
    assert pmic("IC50", "=", 10.0, "nM", None) == (None, None)


def test_unusable_shapes_are_declined_not_guessed():
    assert pmic("MIC", "=", 0.0, "nM", None) == (None, None)
    assert pmic("MIC", "=", 10.0, None, None) == (None, None)
    assert pmic("MIC", "=", 10.0, "mg", 500.0) == (None, None)  # no volume
    assert pmic(None, "=", 10.0, "nM", None) == (None, None)


def test_silence_is_not_standard_media():
    """The rule that keeps the condition column honest."""
    assert classify_condition("Antimycobacterial activity against M. tuberculosis H37Rv") == (
        "unspecified"
    )
    assert classify_condition(None) == "unspecified"
    assert classify_condition("") == "unspecified"
    # Only an explicitly named medium counts.
    assert classify_condition("MIC against H37Rv in Middlebrook 7H9 broth") == "standard_media"


def test_conditions_are_recognised():
    assert classify_condition("activity against Mtb in THP-1 macrophages") == "intracellular"
    assert classify_condition("LORA assay under hypoxia") == "non_replicating"
    assert classify_condition("growth on cholesterol as sole carbon source") == "alt_carbon"
    assert classify_condition("MIC in Fe-deficient medium") == "nutrient_stress"
    assert classify_condition("activity in caseum surrogate") == "caseum"


def test_the_harder_condition_wins():
    """A hypoxic assay run in 7H9 is a hypoxia result, not a standard-media one."""
    assert classify_condition("MIC in Middlebrook 7H9 under hypoxia") == "non_replicating"
    assert classify_condition("intracellular activity in 7H9-grown macrophages") == (
        "intracellular"
    )


def test_resistant_panel_is_separate_from_condition():
    """Strain and medium are different claims; neither may hide the other."""
    rows = [
        {
            "evidence": "whole_cell",
            "molecule_chembl_id": "CHEMBL1",
            "standard_type": "MIC",
            "standard_relation": "=",
            "standard_value": 10.0,
            "standard_units": "nM",
            "assay_description": "Activity against MDR Mycobacterium tuberculosis in 7H9 broth",
        }
    ]
    (row,) = annotate_activities(rows, [])
    assert row["resistant_panel"] is True
    assert row["assay_condition"] == "standard_media"
    assert row["pmic"] == 8.0


def test_annotation_leaves_protein_assays_without_a_condition():
    """A biochemical assay on purified protein has no growth medium."""
    rows = [
        {
            "evidence": "direct",
            "molecule_chembl_id": "CHEMBL1",
            "standard_type": "IC50",
            "standard_relation": "=",
            "standard_value": 10.0,
            "standard_units": "nM",
            "assay_description": "Inhibition of DprE1 in 7H9",
        }
    ]
    (row,) = annotate_activities(rows, [])
    assert row["assay_condition"] is None
    assert row["resistant_panel"] is False
    assert row["pmic"] is None


def test_annotation_reads_weights_from_the_compound_rows():
    rows = [
        {
            "evidence": "whole_cell",
            "molecule_chembl_id": "CHEMBL1",
            "standard_type": "MIC",
            "standard_relation": "=",
            "standard_value": 1.0,
            "standard_units": "ug.mL-1",
            "assay_description": "MIC against H37Rv",
        }
    ]
    (row,) = annotate_activities(rows, [{"molecule_chembl_id": "CHEMBL1", "mw": 500.0}])
    assert row["pmic"] == round(-math.log10(2e-6), 3)
