"""The per-gene roll-up, where the rules that could quietly mislead live.

Two of them matter more than the rest: whole-cell potency must only reach a
gene through a compound with protein-level activity on it, and "essential"
must not silently widen to include growth-defect genes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from atlas import summary
from atlas.store import read, records
from atlas.summary import counts


@pytest.fixture(scope="session")
def rows(evidence_store: Path) -> dict[str, dict]:
    relation = read("target_summary", store=evidence_store)
    columns = relation.columns
    return {
        row[columns.index("rv_id")]: dict(zip(columns, row, strict=True))
        for row in relation.fetchall()
    }


def test_one_row_per_gene(rows: dict, evidence_store: Path) -> None:
    walk = read("crosswalk", store=evidence_store).aggregate("count(*)").fetchone()[0]
    assert len(rows) == walk


def test_rna_genes_are_in_the_universe(rows: dict) -> None:
    """rrs is the reason: it carries resistance for five drugs."""
    rrna = [r for r in rows.values() if r["feature"] == "rRNA"]
    assert rrna
    assert all(r["uniprot_acc"] is None for r in rrna)
    assert all(not r["conflict"] for r in rrna), "a protein-less RNA gene is not a conflict"


# --- essentiality ------------------------------------------------------------


def test_essential_and_fitness_cost_are_distinct(rows: dict) -> None:
    assert rows["Rv3790"]["essentiality_essential"] is True
    assert rows["Rv3790"]["essentiality_fitness_cost"] is True
    assert rows["Rv1908c"]["essentiality_essential"] is False  # katG is NE
    assert rows["Rv0206c"]["essentiality_essential"] is True  # ESD still counts


def test_missing_essentiality_is_not_false_confidence(rows: dict) -> None:
    """A gene with no TnSeq call must not read as "not essential"."""
    uncalled = [r for r in rows.values() if r["essentiality"] is None]
    assert uncalled
    for row in uncalled:
        assert row["essentiality_essential"] is False
        assert row["essentiality_label"] is None
        assert row["structural_gap"] is False


# --- structures ---------------------------------------------------------------


def test_structure_rollup(rows: dict) -> None:
    dpre1 = rows["Rv3790"]
    assert dpre1["n_pdb"] == 1  # the fixture holds 4KW5 only
    assert dpre1["has_structure"] is True
    assert dpre1["ligand_ids"] == ["1W6"]
    assert dpre1["best_resolution"] == pytest.approx(2.612, abs=0.01)


def test_predicted_rollup(rows: dict) -> None:
    assert rows["Rv0206c"]["has_predicted"] is True
    assert rows["Rv0206c"]["plddt_mean"] == pytest.approx(79.31, abs=0.5)


# --- chemistry ----------------------------------------------------------------


def test_protein_activity_rollup(rows: dict) -> None:
    dpre1 = rows["Rv3790"]
    assert dpre1["n_activities"] > 0
    assert dpre1["has_ligands"] is True
    assert dpre1["best_pchembl"] is not None


def test_whole_cell_only_reaches_genes_through_their_own_compounds(rows: dict) -> None:
    """The rule that keeps a cell MIC from implying target engagement.

    A whole-cell number belongs on a gene page only when the same compound
    already has protein-level activity on that gene. Any gene with no protein
    activity must therefore show no whole-cell count, however many MICs that
    compound has elsewhere.
    """
    for row in rows.values():
        if row["n_activities"] == 0:
            assert row["n_whole_cell"] == 0, row["rv_id"]
            assert row["best_whole_cell_pchembl"] is None, row["rv_id"]
            assert row["best_pmic"] is None, row["rv_id"]
            assert row["n_mic"] == 0, row["rv_id"]
    assert any(r["n_whole_cell"] > 0 for r in rows.values()), "fixture should exercise the join"


def test_the_mic_rollup_sees_what_pchembl_cannot(rows: dict) -> None:
    """ChEMBL gives MIC rows no pchembl_value, so the old column cannot see them.

    This is the gap the pmic columns close: the fixture's whole-cell rows are
    MICs, so `best_whole_cell_pchembl` has nothing to report while `best_pmic`
    does. If this ever inverts, the conversion stopped running.
    """
    with_mic = [r for r in rows.values() if r["n_mic"] > 0]
    assert with_mic, "fixture should exercise the MIC conversion"
    for row in with_mic:
        assert row["best_pmic"] is not None, row["rv_id"]
        assert row["median_pmic"] is not None, row["rv_id"]


def test_a_censored_mic_is_counted_but_not_converted(rows: dict) -> None:
    """`MIC > 128` is a measured non-result, not a missing measurement.

    It must never become a potency, and it must not vanish either -- a gene
    whose chemistry is all non-inhibition has to read differently from one
    nobody tested.
    """
    censored = [r for r in rows.values() if r["n_mic_censored"] > 0]
    assert censored, "fixture should carry a censored MIC"
    for row in censored:
        # The censored row is excluded from n_mic, which counts convertible ones.
        assert row["n_whole_cell"] > row["n_mic"], row["rv_id"]


def test_conditions_roll_up_without_claiming_standard_media(rows: dict) -> None:
    """`unspecified` must stay distinct from `standard_media` in the roll-up."""
    conditions = {
        c["condition"]: c for row in rows.values() for c in (row["whole_cell_conditions"] or [])
    }
    assert "non_replicating" in conditions, "fixture should carry a hypoxia MIC"
    assert "unspecified" in conditions, "most ChEMBL MICs name no medium"
    # The hypoxic row was deposited in no named medium beyond the condition, so
    # it must not have been swept into standard_media.
    assert conditions["non_replicating"]["n"] >= 1


def test_the_resistant_panel_flag_does_not_eat_the_condition(rows: dict) -> None:
    """Strain and medium are separate claims; the MDR row names 7H9 as well."""
    panels = [r for r in rows.values() if r["n_resistant_panel"] > 0]
    assert panels, "fixture should carry an MDR clinical-isolate MIC"
    for row in panels:
        named = {c["condition"] for c in (row["whole_cell_conditions"] or [])}
        assert "standard_media" in named, row["rv_id"]


def test_screening_scale_separates_a_campaign_from_a_follow_up(rows: dict) -> None:
    """`max_assay_compounds` is the biggest single assay, not the assay count."""
    for row in rows.values():
        if row["n_protein_assays"] == 0:
            assert row["max_assay_compounds"] == 0, row["rv_id"]
        else:
            assert row["max_assay_compounds"] >= 1, row["rv_id"]


def test_assay_size_comes_from_the_census_not_the_potency_rows(rows: dict) -> None:
    """A primary screen reports percent inhibition, so it has no pchembl row.

    Reading assay size from `activities` measured the follow-ups and missed the
    campaign: genome-wide, pks13 read 143 compounds against a 66,592-compound
    screen. The fixture's dprE1 has 7 assays with potency rows (the largest
    over 3 compounds) plus a percent-inhibition screen of 5 that only the
    census holds; both numbers must include it.
    """
    dpre1 = rows["Rv3790"]
    assert dpre1["n_protein_assays"] == 8
    assert dpre1["max_assay_compounds"] == 5
    # Potency-based measures are untouched: the screen added no pchembl row.
    assert dpre1["n_activities"] == 10


def test_a_complex_screen_is_not_either_subunits_protein_assay(rows: dict) -> None:
    """ClpP1P2's target maps to both clpP1 and clpP2 as `direct`.

    Counting it would hand each subunit a screen of the pair, which is the rule
    `n_complex_drugs` already follows for the ribosome's 45 approved drugs.
    """
    for rv_id in ("Rv2460c", "Rv2461c"):
        assert rows[rv_id]["n_protein_assays"] == 0, rv_id
        assert rows[rv_id]["max_assay_compounds"] == 0, rv_id
        # Shown, never counted.
        assert rows[rv_id]["n_complex_assays"] == 1, rv_id
        assert rows[rv_id]["max_complex_assay_compounds"] == 3, rv_id
        # The example illustrates `n_protein_assays`, so it answers the same
        # question: a gene with no assay on its own protein names none. The
        # fixture gives the complex's assay a description to wrongly offer.
        assert rows[rv_id]["protein_assay_example"] is None, rv_id


def test_a_target_of_unknown_type_is_reported_not_lost(rows: dict, evidence_store: Path) -> None:
    """A screen whose target has no `target_type` is not counted as a single protein.

    Rv3545c reaches CHEMBL5629 only through UniProt's cross-reference, so the
    crosswalk carries no type for it. `= 'SINGLE PROTEIN'` and `<> 'SINGLE
    PROTEIN'` are both NULL there, which dropped the assay from both columns
    without an error: neither a protein assay nor a shown-not-counted one.
    """
    walk = {r["rv_id"]: r for r in records("crosswalk", store=evidence_store)}
    (target,) = walk["Rv3545c"]["chembl_targets"]
    assert target["target_type"] is None, "the fixture no longer carries an untyped target"
    assert rows["Rv3545c"]["n_protein_assays"] == 0
    assert rows["Rv3545c"]["max_assay_compounds"] == 0
    assert rows["Rv3545c"]["n_complex_assays"] == 1
    assert rows["Rv3545c"]["max_complex_assay_compounds"] == 4


def test_a_store_without_the_census_still_summarises(
    evidence_store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """An older store has no assay_sizes table; absence is not a failure."""
    out = tmp_path_factory.mktemp("no-census")
    for parquet in evidence_store.glob("*.parquet"):
        if parquet.stem not in ("assay_sizes", "target_summary"):
            shutil.copy(parquet, out / parquet.name)
    summary.build(store=out)
    by_id = {r["rv_id"]: r for r in records("target_summary", store=out)}
    assert by_id["Rv3790"]["n_protein_assays"] == 0


# --- resistance ---------------------------------------------------------------


def test_resistance_rollup_counts_only_associated(rows: dict) -> None:
    katg = rows["Rv1908c"]
    assert katg["in_who_catalogue"] is True
    assert 0 < katg["n_variants_associated"] <= katg["n_variants_catalogued"]
    assert katg["n_variants_mappable"] < katg["n_variants_associated"]
    assert "Isoniazid" in katg["resistance_drugs"]


def test_genes_outside_the_catalogue_say_so(rows: dict) -> None:
    """DprE1 and MmpL3 are not in the WHO catalogue, and that is a real answer."""
    for rv_id in ("Rv3790", "Rv0206c"):
        assert rows[rv_id]["in_who_catalogue"] is False
        assert rows[rv_id]["n_variants_associated"] == 0
        assert rows[rv_id]["resistance_drugs"] == []


# --- the question the atlas exists to answer -----------------------------------


def test_structural_gap_definition(rows: dict) -> None:
    """Essential, has an experimental structure, has no chemical matter."""
    for row in rows.values():
        expected = row["essentiality_essential"] and row["n_pdb"] > 0 and row["n_activities"] == 0
        assert row["structural_gap"] is expected, row["rv_id"]


def test_structural_gap_excludes_growth_defect_genes(rows: dict) -> None:
    """A growth-defect gene with a structure and no ligands is not the answer."""
    for row in rows.values():
        if row["essentiality"] == "GD":
            assert row["structural_gap"] is False


def test_counts_cover_every_summary_flag(evidence_store: Path) -> None:
    result = counts(store=evidence_store)
    assert result["genes"] == len(read("target_summary", store=evidence_store).fetchall())
    assert result["essential"] <= result["any_fitness_cost"]
    assert result["structural_gap"] <= result["with_structure"]
    assert 0 < result["with_clinical_drug"] <= result["genes"]
    assert result["drugs"] > 0
    assert result["trials"] > 0
    assert all(isinstance(v, int) for v in result.values())


# --- drugs and trials ------------------------------------------------------------


def test_drugs_acting_on_a_gene(rows: dict) -> None:
    dpre1 = rows["Rv3790"]
    assert dpre1["drug_names"] == ["MACOZINONE"]  # ChEMBL mechanism and Bosch's PBTZ169
    assert dpre1["n_drugs"] == 1
    assert dpre1["best_drug_phase"] == 2
    assert dpre1["has_clinical_drug"] is True
    assert rows["Rv0206c"]["drug_names"] == ["SQ109"]  # Bosch 2021 is the only link
    assert rows["Rv1484"]["best_drug_phase"] == 4  # isoniazid, ethionamide


def test_complex_membership_is_not_counted_twice(rows: dict) -> None:
    """Bedaquiline reaches atpE as Bosch's annotation and as an ATP synthase member."""
    atpe = rows["Rv1305"]
    assert atpe["n_drugs"] == 1
    assert atpe["n_complex_drugs"] == 0


def test_resistance_does_not_make_a_drug_target(rows: dict) -> None:
    """rpoB carries rifampicin resistance, but no source here calls it the target."""
    rpob = rows["Rv0667"]
    assert "Rifampicin" in rpob["resistance_drugs"]
    assert rpob["n_drugs"] == 0
    assert rpob["best_drug_phase"] is None
    assert rpob["has_clinical_drug"] is False


def test_trials_reach_genes_through_their_drugs(rows: dict) -> None:
    assert rows["Rv3790"]["n_trials"] == 2  # NCT03036163, NCT03423030
    assert rows["Rv0206c"]["n_trials"] == 1  # NCT01218217
    assert rows["Rv0667"]["n_trials"] == 0


def test_genes_with_no_drug_say_so(rows: dict) -> None:
    for row in rows.values():
        if not row["n_drugs"]:
            assert row["drug_names"] == []
            assert row["has_clinical_drug"] is False


# --- protein context ---------------------------------------------------------------


def test_membrane_topology_and_literature_roll_up(rows: dict) -> None:
    assert rows["Rv0206c"]["n_transmembrane"] == 12  # MmpL3
    assert rows["Rv3790"]["n_transmembrane"] == 0
    assert rows["Rv1484"]["n_references"] > 20


def test_a_gene_with_no_protein_has_no_protein_counts(rows: dict) -> None:
    """rrs has no UniProt entry; zero transmembrane helices would be a claim about a protein."""
    rrna = [r for r in rows.values() if r["feature"] == "rRNA"]
    assert rrna and all(r["n_transmembrane"] is None and r["n_references"] is None for r in rrna)


def test_ligand_rollup_excludes_a_neighbours_ligand(rows: dict) -> None:
    """rpoC is in the rifampicin structure, but the drug is on rpoB's chain."""
    assert rows["Rv0667"]["ligand_ids"] == ["RFP"]
    assert rows["Rv0667"]["n_pdb_with_ligand"] == 1
    assert rows["Rv0668"]["ligand_ids"] == []
    assert rows["Rv0668"]["n_pdb_with_ligand"] == 0


# --- conditional fitness -----------------------------------------------------------


def test_cholesterol_rolls_up_with_its_own_flag(rows: dict) -> None:
    cyp125 = rows["Rv3545c"]
    assert cyp125["cholesterol_required"] is True
    assert cyp125["cholesterol_log2_ratio"] == pytest.approx(-1.893, abs=0.01)
    assert cyp125["required_in_vivo"] is True


def test_an_unmeasured_gene_gets_no_number(rows: dict) -> None:
    """Every essential gene is unmeasured here; a zero would be a false reading."""
    dpre1 = rows["Rv3790"]
    assert dpre1["cholesterol_measured"] is False
    assert dpre1["cholesterol_log2_ratio"] is None
    assert dpre1["cholesterol_required"] is False


def test_a_gene_the_screen_never_saw_is_null_not_false(rows: dict) -> None:
    """Griffin covers 3,987 loci; the rest were not screened at all."""
    missing = [r for r in rows.values() if r["cholesterol_measured"] is None]
    assert missing
    for row in missing:
        assert row["cholesterol_log2_ratio"] is None
        assert row["required_in_vivo"] is None


# --- vulnerability in a clinical strain --------------------------------------------


def test_the_clinical_strain_index_rolls_up(rows: dict) -> None:
    """dprE1 is confidently vulnerable in both strains, a little less so in HN878."""
    dpre1 = rows["Rv3790"]
    assert dpre1["vulnerability_index"] == pytest.approx(-9.417)
    assert dpre1["hn878_vulnerability_index"] == pytest.approx(-7.837)
    assert dpre1["hn878_vi_certain"] is True
    assert dpre1["hn878_delta_vi"] == pytest.approx(1.58)
    assert dpre1["hn878_differential_reported"] is True


def test_both_deltas_survive_the_roll_up(rows: dict) -> None:
    """inhA's raw and normalised deltas disagree in sign, so neither is dropped."""
    inha = rows["Rv1484"]
    assert inha["hn878_delta_vi"] == pytest.approx(0.382)
    assert inha["hn878_delta_vi_norm"] == pytest.approx(-0.28623)


def test_a_gene_never_measured_in_the_clinical_strain_is_null(rows: dict) -> None:
    """rpoB has an H37Rv index and no HN878 row.

    A zero would read as "equally vulnerable in the clinic", which is the one
    thing the data does not say.
    """
    rpob = rows["Rv0667"]
    assert rpob["vulnerability_index"] == pytest.approx(-9.567)
    assert rpob["hn878_vulnerability_index"] is None
    assert rpob["hn878_delta_vi"] is None
    assert rpob["hn878_differential_reported"] is False


# --- is there a published assay for this protein? ------------------------------------


def test_a_published_protein_assay_is_counted_and_shown(rows: dict) -> None:
    """DprE1 has eight distinct ChEMBL assays on the Mtb protein itself.

    The count is of assays, not measurements: one assay run against 400
    compounds is one assay you could run again. Seven of the eight carry a
    potency row; the eighth is the percent-inhibition screen that only the
    census holds (it was seven while this was read from `activities`).
    """
    dpre1 = rows["Rv3790"]
    assert dpre1["n_protein_assays"] == 8
    assert dpre1["latest_protein_assay_year"] == 2024
    assert "DprE1" in dpre1["protein_assay_example"]


def test_a_gene_with_no_protein_assay_reads_zero(rows: dict) -> None:
    """mmpL3 has a structure and no assay on the Mtb protein in ChEMBL.

    Zero here is the answer, not a gap: it is the difference between a target
    you can screen on Monday and one that needs an assay built first.
    """
    mmpl3 = rows["Rv0206c"]
    assert mmpl3["n_protein_assays"] == 0
    assert mmpl3["latest_protein_assay_year"] is None
    assert mmpl3["protein_assay_example"] is None


def test_whole_cell_screens_are_not_protein_assays(rows: dict) -> None:
    """Every whole-cell row is assay_type F, which is an MIC, not a protein assay.

    ChEMBL files them against the organism, so counting assay_type would
    credit 3,083 MIC screens to whichever genes the compounds touch.
    """
    assert any(row["n_whole_cell"] > 0 for row in rows.values())
    for row in rows.values():
        if row["n_activities"] == 0:
            assert row["n_protein_assays"] == 0


# --- is there a structure to work from, even if not of this protein? ----------------


def test_a_borrowed_structure_does_not_become_one_of_its_own(rows: dict) -> None:
    """The whole point of the separate column.

    folC has no entry under its own accession and two under a CDC 1551 one.
    If those were added to `n_pdb` the atlas could never again answer "has
    this protein been solved", which is the question the column is for.
    """
    folc = rows["Rv2447c"]
    assert folc["n_pdb"] == 0
    assert folc["has_structure"] is False
    assert folc["structural_gap"] is False
    assert folc["n_orthologue_pdb"] == 2


def test_an_identical_sequence_elsewhere_is_the_stronger_claim(rows: dict) -> None:
    """folC's borrowed entries are of the same sequence, filed under another accession."""
    folc = rows["Rv2447c"]
    assert folc["same_sequence_structure"] is True
    assert folc["closest_orthologue_identity"] == pytest.approx(1.0)
    assert folc["closest_orthologue_gene"] == "folC"
    assert "CDC 1551" in folc["closest_orthologue_organism"]


def test_a_relative_does_not_set_the_same_sequence_flag(rows: dict) -> None:
    """mmpL3's structures are *M. smegmatis* MmpL3 at 67%, which is not this protein."""
    mmpl3 = rows["Rv0206c"]
    assert mmpl3["same_sequence_structure"] is False
    assert mmpl3["closest_orthologue_identity"] == pytest.approx(0.6741)
    assert mmpl3["closest_orthologue_coverage"] == pytest.approx(0.9068)
    assert "smegmatis" in mmpl3["closest_orthologue_organism"]


def test_a_borrowed_structure_can_be_better_than_the_gene_s_own(rows: dict) -> None:
    """The MmpL3 case: one Mtb entry at 3.0 A, the neighbour's at 2.6.

    This is why the column is not restricted to genes with nothing of their
    own -- "has a structure" and "has a structure worth working from" differ.
    """
    mmpl3 = rows["Rv0206c"]
    assert mmpl3["n_pdb"] == 1
    assert mmpl3["best_resolution"] == pytest.approx(3.0)
    assert mmpl3["best_orthologue_resolution"] < mmpl3["best_resolution"]
    assert mmpl3["n_orthologue_pdb_with_ligand"] == 3


def test_entries_are_counted_distinctly_not_as_rows(rows: dict) -> None:
    """One row per (protein, entry) pair, so a rows count would overstate."""
    for row in rows.values():
        assert row["n_orthologue_pdb_with_ligand"] <= row["n_orthologue_pdb"]


def test_a_gene_with_no_mycobacterial_relative_reads_zero(rows: dict) -> None:
    """Absence again: most of the genome has no neighbour with a structure."""
    katg = rows["Rv1908c"]
    assert katg["n_orthologue_pdb"] == 0
    assert katg["same_sequence_structure"] is False
    assert katg["closest_orthologue_gene"] is None
    assert katg["best_orthologue_resolution"] is None


# --- has a drug ever been filed against this fold? ---------------------------


def test_a_drug_on_a_relative_s_protein_is_precedent(rows: dict) -> None:
    """inhA's fold: the FabI inhibitor class, from three other organisms.

    Triclosan and hexachlorophene are approved against E. coli FabI, and
    afabicin, AFN-1252 and CG-400549 are phase 2 against the S. aureus and
    B. pseudomallei enzymes. All five share PF13561 with inhA. That is the
    strongest sourced answer the atlas can give to "is this fold tractable",
    and it is a count of ChEMBL records, never a druggability claim.
    """
    inha = rows["Rv1484"]
    assert inha["n_precedent_approved"] == 2
    assert inha["n_precedent_clinical"] == 3
    assert inha["precedent_pfam"] == "PF13561"
    assert inha["precedent_example"] == "HEXACHLOROPHENE"


def test_a_gene_is_not_its_own_precedent(rows: dict) -> None:
    """Isoniazid and ethionamide are filed against inhA itself.

    They are already in `n_drugs` and `drug_names`. Counting them again as
    precedent for inhA's fold would make the column self-confirming, which is
    the whole reason the roll-up excludes the gene's own accession.
    """
    inha = rows["Rv1484"]
    assert inha["n_drugs"] == 2, "the two drugs are still on the gene itself"
    assert "ISONIAZID" in inha["drug_names"]
    # ...and not in the precedent, which counts only the other three organisms'
    # proteins: 4 approved rows on PF13561, 2 of them inhA's own.
    assert inha["n_precedent_approved"] == 2


def test_dpre1_s_only_precedent_is_a_human_protein(rows: dict) -> None:
    """Triparanol against human Delta(24)-sterol reductase, which shares
    PF01565 with dprE1. Tractable chemistry and a selectivity problem are the
    same fact, so the human share is its own column rather than a footnote."""
    dpre1 = rows["Rv3790"]
    assert dpre1["n_precedent_approved"] == 1
    assert dpre1["n_precedent_human_target"] == 1
    assert dpre1["precedent_example"] == "TRIPARANOL"


def test_dpre1_s_own_clinical_compounds_are_not_fold_precedent(rows: dict) -> None:
    """Macozinone and TBA-7371 are phase 2 against dprE1 itself, on both of its
    domains. The clinical count has to read zero, or the gene's own pipeline
    comes back as evidence that its fold can be drugged."""
    assert rows["Rv3790"]["n_precedent_clinical"] == 0


def test_a_complex_filing_is_shown_and_never_counted(rows: dict) -> None:
    """rpoC: the rifamycins are filed against a bacterial RNA polymerase.

    ChEMBL names every subunit on that one target, so counting it would hand
    rifampicin to rpoC's fold as precedent -- the same rule `n_complex_drugs`
    follows for drugs on this gene. The one counted compound is TAS-106,
    against a human RNA polymerase III subunit filed as a SINGLE PROTEIN.
    """
    rpoc = rows["Rv0668"]
    assert rpoc["n_precedent_complex"] == 3
    assert rpoc["n_precedent_approved"] == 0
    assert rpoc["n_precedent_clinical"] == 1
    assert rpoc["precedent_example"] == "TAS-106"


def test_a_protein_family_filing_is_not_counted_either(rows: dict) -> None:
    """Cobicistat is filed against "Cytochrome P450 3A", a PROTEIN FAMILY
    target naming several accessions, so it is no more attributable to one
    protein than a complex is. The three counted drugs are against single
    human P450s."""
    cyp124 = rows["Rv2266"]
    assert cyp124["n_precedent_complex"] == 1
    assert cyp124["n_precedent_approved"] == 3
    assert cyp124["n_precedent_human_target"] == 3


def test_the_breadth_of_the_domain_travels_with_the_count(rows: dict) -> None:
    """Three fixture genes carry PF00067, and the reader has to see that.

    A shared domain is not a shared binding site. Genome-wide PF00005 covers 37
    genes, so a precedent on it is a statement about a superfamily; without
    this column the count reads as being about one protein.
    """
    for rv_id in ("Rv2266", "Rv1777", "Rv3545c"):
        assert rows[rv_id]["precedent_pfam"] == "PF00067"
        assert rows[rv_id]["precedent_domain_genes"] == 3
    assert rows["Rv1484"]["precedent_domain_genes"] == 1


def test_a_fold_nobody_has_drugged_reads_zero(rows: dict) -> None:
    """mmpL3 again: no drug in ChEMBL is filed against any MmpL protein.

    A measured zero, and one of the more interesting numbers in the atlas --
    the most vulnerable of the three reference genes has no chemical precedent
    at all. It must not be NULL, which would mean nobody looked.
    """
    mmpl3 = rows["Rv0206c"]
    assert mmpl3["n_precedent_approved"] == 0
    assert mmpl3["n_precedent_clinical"] == 0
    assert mmpl3["n_precedent_complex"] == 0
    assert mmpl3["precedent_pfam"] is None


def test_no_domain_annotated_is_null_not_zero(rows: dict) -> None:
    """An RNA gene has no protein, so no domain, so no question to answer.

    Zero would say the lookup ran and found nothing. 500 CDS genes are in the
    same position for want of a Pfam annotation.
    """
    rrs = rows["MTB000019"]
    assert rrs["n_precedent_approved"] is None
    assert rrs["n_precedent_complex"] is None
