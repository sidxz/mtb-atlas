"""The per-gene roll-up, where the rules that could quietly mislead live.

Two of them matter more than the rest: whole-cell potency must only reach a
gene through a compound with protein-level activity on it, and "essential"
must not silently widen to include growth-defect genes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.store import read
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
    assert any(r["n_whole_cell"] > 0 for r in rows.values()), "fixture should exercise the join"


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
    assert all(isinstance(v, int) for v in result.values())
