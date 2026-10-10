"""Keeping the store current: what moved, what to rebuild, and what changed.

Three questions the atlas could not answer about itself. `make build` on a warm
cache is a no-op and `make build-force` re-downloads everything including four
sources that cannot have changed, so there was no way to ask whether anything
upstream had actually moved, no way to refresh one source, and no way to see
what a rebuild did to the numbers.

No network here: the probes are the thin part and are passed in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas import freshness, storediff
from atlas.store import write_parquet

# --- is it stale? ------------------------------------------------------------


def test_matching_versions_are_current() -> None:
    assert freshness.state_of(stored="ChEMBL_37", upstream="ChEMBL_37")[0] == "current"


def test_a_moved_version_is_stale() -> None:
    state, detail = freshness.state_of(stored="ChEMBL_37", upstream="ChEMBL_38")
    assert state == "stale"
    assert "ChEMBL_38" in detail


def test_a_source_that_cannot_move_is_frozen_not_stale() -> None:
    """A paper's supplementary table is the same file forever.

    Re-downloading it on every `build-force` is waste, and reporting it as
    "unknown" would put a permanent question mark next to four sources that
    have no question about them.
    """
    state, detail = freshness.state_of(stored="Griffin 2011", upstream=None, frozen="a 2011 paper")
    assert state == "frozen"
    assert "2011 paper" in detail


def test_a_probe_that_fails_is_unknown_not_current() -> None:
    """An endpoint that is down says nothing about the data behind it.

    Reporting "current" because the question could not be asked is the one
    answer that would be actively misleading.
    """
    assert freshness.state_of(stored="2026_03", upstream=None)[0] == "unknown"


def test_a_table_never_built_is_not_stale() -> None:
    assert freshness.state_of(stored=None, upstream="2026_03")[0] == "unbuilt"


def test_every_source_is_registered_with_a_stage() -> None:
    """A source missing from the registry is one `atlas check` silently skips."""
    assert {s.name for s in freshness.SOURCES} == {
        "mycobrowser",
        "uniprot",
        "chembl",
        "rcsb-pdb",
        "alphafold",
        "dejesus-2017",
        "who-catalogue",
        "griffin-2011",
        "bosch-2021",
        "string-db",
        "phmmer-human",
        "phmmer-paralog",
        "clinicaltrials-gov",
        "mtbtndb",
    }
    assert all(s.stage in freshness.STAGES for s in freshness.SOURCES)


# --- what has to be rebuilt? -------------------------------------------------


def test_the_gene_universe_rebuilds_everything() -> None:
    """Mycobrowser is the canonical key. If it moves, every table re-keys."""
    assert freshness.stages_from("mycobrowser") == ["identity", "evidence", "clinical", "summary"]


def test_a_clinical_source_does_not_rebuild_the_genome() -> None:
    """ClinicalTrials.gov moves daily and reaches nothing upstream of itself."""
    assert freshness.stages_from("clinicaltrials-gov") == ["clinical", "summary"]


def test_an_evidence_source_skips_identity() -> None:
    assert freshness.stages_from("bosch-2021") == ["evidence", "clinical", "summary"]


def test_chembl_starts_at_identity_because_the_crosswalk_holds_its_targets() -> None:
    """`chembl_targets` is built in the identity stage, not the evidence one.

    Refreshing ChEMBL from the evidence stage would leave the crosswalk
    pointing at the previous release's target ids.
    """
    assert freshness.stages_from("chembl")[0] == "identity"


def test_an_unknown_source_is_refused() -> None:
    with pytest.raises(KeyError):
        freshness.stages_from("not-a-source")


# --- what changed? -----------------------------------------------------------


def two_stores(tmp_path: Path, before: list[dict], after: list[dict]) -> tuple[Path, Path]:
    old, new = tmp_path / "old", tmp_path / "new"
    for store, rows, version in ((old, before, "v1"), (new, after, "v2")):
        store.mkdir(parents=True, exist_ok=True)
        write_parquet(
            "drugs",
            rows,
            source="chembl",
            source_version=version,
            retrieved_at="2026-10-10",
            store=store,
        )
    return old, new


def test_a_rebuild_that_changes_nothing_reports_nothing(tmp_path: Path) -> None:
    rows = [{"molecule_chembl_id": "CHEMBL1", "pref_name": "ISONIAZID"}]
    old, new = two_stores(tmp_path, rows, rows)
    (diff,) = storediff.compare(old, new)
    assert diff.added == 0 and diff.removed == 0
    assert diff.before == diff.after == 1


def test_rows_gained_and_lost_are_reported_separately(tmp_path: Path) -> None:
    """A table that gains 10 and loses 10 has a row-count delta of zero.

    Counting only rows would call that unchanged, which is how an upstream
    removal hides. The outage guard catches a network failure; nothing caught
    this.
    """
    old, new = two_stores(
        tmp_path,
        [{"molecule_chembl_id": "CHEMBL1"}, {"molecule_chembl_id": "CHEMBL2"}],
        [{"molecule_chembl_id": "CHEMBL1"}, {"molecule_chembl_id": "CHEMBL3"}],
    )
    (diff,) = storediff.compare(old, new)
    assert (diff.before, diff.after) == (2, 2)
    assert (diff.added, diff.removed) == (1, 1)
    assert "CHEMBL3" in diff.examples_added and "CHEMBL2" in diff.examples_removed


def test_a_version_change_is_carried(tmp_path: Path) -> None:
    rows = [{"molecule_chembl_id": "CHEMBL1"}]
    old, new = two_stores(tmp_path, rows, rows)
    (diff,) = storediff.compare(old, new)
    assert (diff.version_before, diff.version_after) == ("v1", "v2")
    assert diff.changed is True  # the version moved even though the rows did not


def test_a_table_added_or_dropped_is_not_a_row_count_of_zero(tmp_path: Path) -> None:
    """A table absent from one store is NULL on that side, never 0.

    Zero rows is a state `write_parquet` refuses to write at all, so a table
    that is simply not there has to read as absent -- the same three-state rule
    the evidence tables follow.
    """
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    stamp = {"source": "x", "source_version": "v1", "retrieved_at": "2026-10-10"}
    write_parquet("drugs", [{"molecule_chembl_id": "CHEMBL1"}], **stamp, store=old)
    write_parquet("trials", [{"nct_id": "NCT1"}], **stamp, store=new)
    by_table = {d.table: d for d in storediff.compare(old, new)}
    assert (by_table["trials"].before, by_table["trials"].after) == (None, 1)
    assert (by_table["drugs"].before, by_table["drugs"].after) == (1, None)


# --- running it without a person ---------------------------------------------


def test_a_report_is_json_serialisable() -> None:
    """The shape a cron job or CI consumes, so it is a contract, not an accident."""
    report = freshness.Report(
        source="chembl",
        stored="ChEMBL_37",
        upstream="ChEMBL_38",
        state="stale",
        detail="upstream is ChEMBL_38",
        stage="identity",
        rebuilds=["identity", "evidence", "clinical", "summary"],
    )
    payload = json.loads(json.dumps(freshness.as_dict(report)))
    assert payload["state"] == "stale"
    assert payload["rebuilds"][0] == "identity"


def test_a_diff_is_json_serialisable(tmp_path: Path) -> None:
    old, new = two_stores(
        tmp_path,
        [{"molecule_chembl_id": "CHEMBL1"}],
        [{"molecule_chembl_id": "CHEMBL1"}, {"molecule_chembl_id": "CHEMBL2"}],
    )
    (diff,) = storediff.compare(old, new)
    payload = json.loads(json.dumps(storediff.as_dict(diff)))
    assert payload["added"] == 1
    assert payload["changed"] is True


def test_staleness_is_detectable_without_reading_the_table() -> None:
    """`--exit-code` is what lets a scheduler act; the text is for a person."""
    stale = freshness.Report("chembl", "a", "b", "stale", "", "identity", [])
    fine = freshness.Report("uniprot", "a", "a", "current", "", "identity", [])
    assert freshness.any_stale([stale, fine]) is True
    assert freshness.any_stale([fine]) is False
