"""The agent's SQL sandbox.

The agent hands a language model a SQL tool, so the only thing standing between
a generated string and the filesystem is this guard. It gets its own tests.
The live model call is not tested here: it costs money and needs credentials.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas import agent


@pytest.fixture(autouse=True)
def _store(evidence_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the agent at the fixture store, and give each test a fresh one."""
    monkeypatch.setattr(agent, "STORE", evidence_store)
    monkeypatch.setattr(agent, "_connection", None)


def test_queries_the_fixture_store() -> None:
    result = agent.run_sql("SELECT rv_id, gene_name FROM target_summary ORDER BY rv_id")
    assert result["row_count"] > 0
    assert {"rv_id", "gene_name"} == set(result["columns"])


def test_results_are_capped() -> None:
    """A model asking for a whole table must not get one."""
    result = agent.run_sql("SELECT * FROM resistance", limit=5)
    assert result["row_count"] <= 5
    assert result["truncated"] is True


def test_cap_cannot_be_raised_past_the_ceiling() -> None:
    result = agent.run_sql("SELECT * FROM resistance", limit=10_000)
    assert result["row_count"] <= agent.MAX_ROWS


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE genes",
        "DELETE FROM genes",
        "UPDATE genes SET rv_id = 'x'",
        "CREATE TABLE evil AS SELECT 1",
        "ATTACH '/etc/passwd' AS leak",
        "SET enable_external_access=true",
        "COPY genes TO '/tmp/leak.csv'",
        "INSTALL httpfs",
        "PRAGMA database_list",
        "SELECT 1; DROP TABLE genes",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_parquet('/etc/passwd')",
        "WITH x AS (SELECT 1) SELECT * FROM glob('/etc/*')",
    ],
)
def test_dangerous_statements_are_refused(sql: str) -> None:
    with pytest.raises(ValueError):
        agent.run_sql(sql)


def test_external_access_is_off_even_if_a_guard_is_bypassed() -> None:
    """Defence in depth: the connection itself cannot reach the filesystem.

    The keyword guard is a string match and string matches can be fooled, so
    the DuckDB connection is also locked down. This asserts the lock, not the
    guard, by going around the guard deliberately.
    """
    import duckdb

    connection = agent.connection()
    with pytest.raises(duckdb.Error):
        connection.execute("SELECT * FROM read_csv_auto('/etc/passwd')")
    with pytest.raises(duckdb.Error):
        connection.execute("SET enable_external_access=true")


def test_describe_names_the_traps() -> None:
    """The schema dump has to carry the gotchas, or the model writes wrong joins."""
    text = agent.describe()
    assert "target_summary" in text
    assert "NEGATIVE" in text  # vulnerability index direction
    assert "GENE SYMBOL not Rv tag" in text  # the resistance join
    assert "uniprot_acc, NOT rv_id" in text  # the structures join
    for table in ("activities", "resistance", "structures"):
        assert f"## {table}" in text


def test_system_prompt_states_the_evidence_rules() -> None:
    """These rules are the difference between an answer and a confident guess."""
    for phrase in (
        "absence is an answer",
        "orthologue",
        "whole_cell",
        "65 genes",
        "Cite records",
    ):
        assert phrase in agent.SYSTEM, phrase


def test_describe_names_the_clinical_traps() -> None:
    text = agent.describe()
    for table in ("drugs", "drug_mechanisms", "drug_genes", "trials", "trial_drugs"):
        assert f"## {table}" in text
    assert "max_phase_tb" in text  # TB phase, not any-indication phase
    assert "NOT target engagement" in text  # who_resistance links
    assert "via_chembl_ref" in text


def test_system_prompt_states_the_clinical_rules() -> None:
    for phrase in ("for tuberculosis", "Resistance is not engagement", "complex"):
        assert phrase in agent.SYSTEM, phrase
    # The homology column is a phmmer search now, not UniRef co-membership.
    assert "UniRef cluster membership" not in agent.SYSTEM


def test_describe_warns_that_unannotated_is_not_negative() -> None:
    text = agent.describe()
    assert "n_transmembrane" in text
    assert "not a negative finding" in text
