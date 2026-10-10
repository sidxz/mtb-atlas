"""Conditional fitness: does this gene matter on cholesterol, the carbon source
M. tuberculosis lives on inside a macrophage?

The trap here is the one TnSeq always has: a gene with no transposon insertions
has nothing to compare between conditions, and every essential gene is such a
gene. dprE1, inhA and mmpL3 all come back unmeasured, and that is a different
answer from "no effect".
"""

from __future__ import annotations

import pytest

from atlas.sources import conditional

from .conftest import FIXTURES


@pytest.fixture(scope="session")
def rows() -> dict[str, dict]:
    return {r["rv_id"]: r for r in conditional.normalize(FIXTURES / "griffin_supplement.zip")}


def test_a_measured_gene_carries_its_numbers(rows: dict) -> None:
    cyp125 = rows["Rv3545c"]
    assert cyp125["measured"] is True
    assert cyp125["ratio"] == pytest.approx(0.269, abs=0.01)
    assert cyp125["log2_ratio"] == pytest.approx(-1.893, abs=0.01)
    assert cyp125["p_value"] == pytest.approx(0.000283, abs=1e-5)


def test_the_authors_own_call_is_what_is_flagged(rows: dict) -> None:
    """96 genes in Table S4, not a threshold this atlas invented."""
    assert rows["Rv3545c"]["cholesterol_required"] is True  # cyp125
    assert rows["Rv3540c"]["cholesterol_required"] is True  # ltp2, the igr operon
    assert rows["Rv1777"]["cholesterol_required"] is False  # measured, depleted, not called
    assert rows["Rv1777"]["measured"] is True


def test_an_essential_gene_is_unmeasured_not_unaffected(rows: dict) -> None:
    for rv_id in ("Rv3790", "Rv1484", "Rv0206c"):  # dprE1, inhA, mmpL3
        assert rows[rv_id]["measured"] is False
        assert rows[rv_id]["ratio"] is None
        assert rows[rv_id]["log2_ratio"] is None
        assert rows[rv_id]["p_value"] is None
        assert rows[rv_id]["cholesterol_required"] is False


def test_the_in_vivo_flag_is_attributed_to_whose_result_it_is(rows: dict) -> None:
    """The column is Sassetti 2003's mouse screen, carried in Griffin's table."""
    assert rows["Rv3545c"]["required_in_vivo"] is True
    assert rows["Rv2266"]["required_in_vivo"] is False
    assert "Sassetti" in conditional.IN_VIVO_CITATION


def test_every_row_names_its_condition(rows: dict) -> None:
    for row in rows.values():
        assert row["condition"] == "cholesterol vs glycerol, in vitro"
        assert "Griffin" in row["citation"]
