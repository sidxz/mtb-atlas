"""What a rebuild actually did to the store.

The outage guard in `fetch.py` catches the network falling over. It cannot
catch an upstream that quietly stopped publishing a third of its rows, or a
release that re-keyed half a table, because those arrive as a complete,
successful download.

So every table is compared on its key, not only on its row count: a table that
gains ten rows and loses ten has a delta of zero and is not unchanged. That is
exactly how a removal hides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from .store import STORE

# The column or columns that identify a row, per table. A table missing from
# here is compared on row count alone and says so, rather than being compared
# on a key that was guessed.
KEYS: dict[str, tuple[str, ...]] = {
    "genes": ("rv_id",),
    "proteins": ("uniprot_acc",),
    "chembl_targets": ("uniprot_acc", "chembl_target_id"),
    "crosswalk": ("rv_id",),
    "structures": ("pdb_id", "uniprot_acc"),
    "predicted_structures": ("uniprot_acc",),
    "ligands": ("comp_id",),
    "activities": ("activity_id",),
    "compounds": ("molecule_chembl_id",),
    "compound_structures": ("molecule_chembl_id",),
    "assay_sizes": ("target_chembl_id", "assay_chembl_id"),
    "essentiality": ("rv_id",),
    "vulnerability": ("rv_id",),
    "strain_vulnerability": ("rv_id",),
    "conditional_fitness": ("rv_id",),
    "conditional_tnseq": ("rv_id", "screen_id"),
    "tnseq_screens": ("screen_id",),
    "resistance": ("gene", "mutation", "drug"),
    "interactions": ("rv_id", "partner_rv_id"),
    "homology": ("uniprot_acc",),
    "paralogs": ("uniprot_acc",),
    "orthologue_structures": ("uniprot_acc", "via_acc", "pdb_id"),
    "drug_precedent": ("pfam_id", "mec_id", "accession"),
    "drugs": ("molecule_chembl_id",),
    "drug_mechanisms": ("molecule_chembl_id", "target_chembl_id"),
    "trials": ("nct_id",),
    "drug_genes": ("molecule_chembl_id", "rv_id", "link"),
    "trial_drugs": ("nct_id", "molecule_chembl_id"),
    "screens": ("screen_id",),
    "screen_stages": ("stage_id",),
    # A PubChem row has a `result_tag` and a NULL `activity_id`; a ChEMBL row the
    # reverse. That is sound here because EXCEPT treats two NULLs as equal, though
    # `NULL = NULL` is not true, so a row with a NULL in its key still compares.
    # `pubchem.RESULT_KEY` is what makes a row unique (the compound and the SID alone
    # both repeat). The SID is added because `compare` is a key-set difference: it sees
    # which keys exist and nothing under them, so a key made only of the row's number
    # stays silent when a re-download puts different substances into the same slots.
    # With the SID, content moving between slots shows as added and removed. An outcome
    # edited in place under the same SID is still invisible, as in every table here.
    "screen_results": ("stage_id", "result_tag", "activity_id", "pubchem_sid"),
    "target_summary": ("rv_id",),
}

EXAMPLES = 5


@dataclass(frozen=True)
class TableDiff:
    table: str
    before: int | None
    after: int | None
    added: int = 0
    removed: int = 0
    version_before: str | None = None
    version_after: str | None = None
    keyed: bool = True
    examples_added: list[str] = field(default_factory=list)
    examples_removed: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return (
            self.before != self.after
            or bool(self.added or self.removed)
            or self.version_before != self.version_after
        )


def _version(connection: duckdb.DuckDBPyConnection, path: Path) -> str | None:
    row = connection.sql(f"SELECT source_version FROM '{path}' LIMIT 1").fetchone()
    return row[0] if row else None


def _keyset(path: Path, key: tuple[str, ...]) -> str:
    return f"SELECT {', '.join(key)} FROM '{path}'"


def compare(old: Path | None = None, new: Path | None = None) -> list[TableDiff]:
    """One row per table in either store, whether or not it changed."""
    old = old or STORE.parent / "store.prev"
    new = new or STORE
    connection = duckdb.connect()
    names = sorted(
        {p.stem for p in old.glob("*.parquet")} | {p.stem for p in new.glob("*.parquet")}
    )

    diffs = []
    for name in names:
        before_path, after_path = old / f"{name}.parquet", new / f"{name}.parquet"
        here, there = before_path.exists(), after_path.exists()
        count = lambda p: connection.sql(f"SELECT count(*) FROM '{p}'").fetchone()[0]  # noqa: E731
        before = count(before_path) if here else None
        after = count(after_path) if there else None
        key = KEYS.get(name)
        added = removed = 0
        gained: list[str] = []
        lost: list[str] = []
        if here and there and key:
            # EXCEPT, not EXCEPT ALL: these tables are keyed, so the set
            # difference is the question being asked.
            was = _keyset(before_path, key)
            now = _keyset(after_path, key)
            gained_rows = connection.sql(f"{now} EXCEPT {was}").fetchall()
            lost_rows = connection.sql(f"{was} EXCEPT {now}").fetchall()
            added, removed = len(gained_rows), len(lost_rows)
            gained = [" ".join(str(v) for v in row) for row in gained_rows[:EXAMPLES]]
            lost = [" ".join(str(v) for v in row) for row in lost_rows[:EXAMPLES]]
        diffs.append(
            TableDiff(
                table=name,
                before=before,
                after=after,
                added=added,
                removed=removed,
                version_before=_version(connection, before_path) if here else None,
                version_after=_version(connection, after_path) if there else None,
                keyed=bool(key),
                examples_added=gained,
                examples_removed=lost,
            )
        )
    return diffs


def as_dict(diff: TableDiff) -> dict[str, object]:
    """The shape a scheduler consumes. A contract, so it has a test."""
    return {
        "table": diff.table,
        "before": diff.before,
        "after": diff.after,
        "added": diff.added,
        "removed": diff.removed,
        "version_before": diff.version_before,
        "version_after": diff.version_after,
        "keyed": diff.keyed,
        "changed": diff.changed,
        "examples_added": list(diff.examples_added),
        "examples_removed": list(diff.examples_removed),
    }


def any_changed(diffs: list[TableDiff]) -> bool:
    return any(diff.changed for diff in diffs)
