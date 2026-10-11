"""The agent's SQL sandbox.

The agent hands a language model a SQL tool, so the only thing standing between
a generated string and the filesystem is this guard. It gets its own tests.
The live model call is not tested here: it costs money and needs credentials.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
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
        "PRAGMA enable_profiling",
        "PRAGMA threads=1",
        "SELECT 1; DROP TABLE genes",
        "SELECT 1; SELECT 2",
    ],
)
def test_dangerous_statements_are_refused(sql: str) -> None:
    with pytest.raises(ValueError):
        agent.run_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_parquet('/etc/passwd')",
        "SELECT * FROM '/etc/passwd'",
        "WITH x AS (SELECT 1) SELECT * FROM glob('/etc/*')",
        "SELECT * FROM read_json('https://example.com/x.json')",
    ],
)
def test_file_reads_parse_as_select_and_the_lock_stops_them(sql: str) -> None:
    """These are SELECTs, so the parser passes them; only the lock stands in the way."""
    with pytest.raises(duckdb.Error):
        agent.run_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT rv_id FROM essentiality WHERE call = 'ES'",
        "SELECT 'data set; drop' AS s",
        "SELECT 1;",
    ],
)
def test_keywords_in_names_and_strings_are_not_commands(sql: str) -> None:
    """The old regex refused every query on `essentiality.call`, the essentiality call."""
    agent.run_sql(sql)


def test_exactly_the_cap_is_not_truncated() -> None:
    assert agent.run_sql("SELECT * FROM range(5)", limit=5)["truncated"] is False
    assert agent.run_sql("SELECT * FROM range(6)", limit=5)["truncated"] is True


def test_a_runaway_query_is_interrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "QUERY_SECONDS", 0.2)
    with pytest.raises(duckdb.InterruptException):
        agent.run_sql(
            "SELECT count(*) FROM range(100000) a, range(100000) b WHERE a.range + b.range = -1"
        )


def test_external_access_is_off_even_if_a_guard_is_bypassed() -> None:
    """Defence in depth: the connection itself cannot reach the filesystem.

    This asserts the lock, not the guard, by going around the guard
    deliberately -- on a cursor too, since that is what each query runs on.
    """
    connection = agent.connection()
    with pytest.raises(duckdb.Error):
        connection.cursor().execute("SET enable_external_access=true")
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


def test_describe_names_the_structural_links() -> None:
    text = agent.describe()
    assert "## ligands" in text
    assert "soaking studies" in text  # a co-crystal is not a mechanism claim


def test_describe_warns_that_tnseq_cannot_see_essential_genes() -> None:
    text = agent.describe()
    assert "## conditional_fitness" in text
    assert "NOT the same as unaffected" in text


def test_the_schema_warns_about_every_screens_trap() -> None:
    """A model that writes a plausible wrong join here gets silent nonsense, not an error.

    Each phrase sits under the table it belongs to, so a trap moved to the wrong note (or
    dropped from the right one because a sibling still names it) fails here.
    """
    traps = {
        "screens": (
            "A call count that is NULL is not a zero",  # the headline ...
            "stated no activity call",  # ... first meaning: no cutoff deposited (the common one)
            "`outcome_stated` can be true",  # a NULL count is not 'no calls', even with calls ...
            "n_stages > 1",  # ... and a campaign of several assays is the second NULL
            "0 for AID 1626",  # n_unspecified is PubChem's own count, not n_tested
            "lowest member",  # a declared project is ONE row, named for it
            "`aid` is NULL on a project row",  # so `WHERE aid = ...` misses a declared project ...
            "stage_id = 'pubchem:<AID>'",  # ... and an AID reaches its campaign this way
            "library_size_stated",  # the depositor's figure is not n_tested
            "outcome_method",  # PubChem's Method is not a stage
            "project_declared",  # false is not "had no follow-up"
            "licence is per depositor",
        ),
        "screen_stages": (
            "Join screen_results on stage_id",
            "`evidence = 'direct'`",  # an orthologue's target is another organism's protein
            "SINGLE PROTEIN",  # a complex is not the subunit's screen
            "screens.targets",  # PubChem stages have no ChEMBL target: the other route
            "derived",  # an index ChEMBL computed has no funnel position
            "defaults to `primary`",  # `stage`'s fallback, for a description matching nothing
            "falls back to `other`",  # `modality`'s, and it reads the target record too
        ),
        "screen_results": (
            "outcome = 'inactive'",  # the non-hits ...
            "outcome IS NULL",  # ... and the filter that is not them
            "not a compound",  # a row is a SID or an activity
            "unmapped",  # NULL molecule_chembl_id is not untested
            "Not Determined",  # ChEMBL's failed measurement
        ),
        "target_summary": (
            "n_screen_actives",  # a sum over the screens that stated calls
            "n_complex_screens",  # shown, never counted
            "latest_screen_year",  # undated deposits do not count
        ),
    }
    for table, phrases in traps.items():
        for phrase in phrases:
            assert phrase in agent.TABLE_NOTES[table], (table, phrase)


def test_system_prompt_states_the_screening_rules() -> None:
    """`describe_store` is only called "if you are unsure of a column", and a model that does
    not know screening evidence exists will not look for its traps, so the four distinctions
    that are not interchangeable are in the prompt itself."""
    for phrase in (
        "`outcome` NULL is not `inactive`",
        "not a screen of either subunit",
        "different axes",
        "shares no denominator with `n_target_screens`",
    ):
        assert phrase in agent.SYSTEM, phrase


def test_the_schema_dump_carries_the_screens_notes() -> None:
    """The notes reach the model only through `describe`, and only for tables that exist."""
    text = agent.describe()
    for table in ("screens", "screen_stages"):
        assert f"## {table}" in text
        assert agent.TABLE_NOTES[table] in text
