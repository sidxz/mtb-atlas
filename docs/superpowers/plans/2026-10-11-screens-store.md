# Screens store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the store layer for the screens and hit-profiling evidence — three new tables, the roll-up columns, and the corrected assay numbers the current store gets wrong.

**Architecture:** Two new ingesters following the existing `fetch_raw` → `normalize` → `build` shape (`atlas/sources/pubchem.py`, `atlas/sources/unichem.py`) plus campaign functions added to `atlas/sources/chembl.py`. They write `screens` (one row per campaign), `screen_stages` (one row per assay within it) and `screen_results` (one row per compound per stage). The pure classifiers that read depositor prose live beside `pmic` and `classify_condition` in `chembl.py`, where the existing tested precedent for prose classification already sits. Nothing in this plan touches the API or the frontend.

**Tech Stack:** Python 3.12, `uv`, httpx via `atlas/fetch.py`, DuckDB via `atlas/store.py`, pytest against committed fixtures, ruff (line length 100).

**Spec:** `docs/superpowers/specs/2026-10-11-screens-design.md`

**Scope note:** this plan covers Milestone 0 (the filter fix) and the M11 **store**. Two plans follow it and are deliberately out of scope here: the API endpoints and the Screens / Hit profiling views; and M12 (PROSPECT). The store is working software on its own — `atlas summary` reports the new columns, `atlas diff` tracks the new tables, and `/ask` can query them, which is one of the atlas's four surfaces.

## Global Constraints

- **Public data only.** Every source goes in `docs/data-sources.md` with its licence before it enters the pipeline.
- **All fetching goes through `atlas/fetch.py`.** It owns the cache, the User-Agent, retry/backoff and the per-host rate limit. No ingester calls httpx directly.
- **Raw downloads cache in `data/raw/<source>/` and are gitignored**, each with a `.meta.json` sidecar.
- **Tests run against committed fixtures, never the network.**
- **Every record carries `source`, `source_version`, `retrieved_at`**, stamped by `store.write_parquet`. A source that will not state a version gets `"unknown"`, never a guess.
- Normalization logic in Python; DuckDB only types rows and writes Parquet.
- **No new runtime dependency.** CSV, gzip and `duckdb` cover this plan. No RDKit in the pipeline.
- Python 3.12, ruff line length 100, conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`).
- **No screen, hit or compound is scored, ranked or summed.** Counts are counts.
- PubChem rate limit: at most 5 requests/second, so `min_interval=0.25` on every PubChem call.

## Review Focus

Five input classes the spec implies that no task's happy path exercises. Each one's test is added to the task that owns the code.

1. **A PubChem AID whose rows are all `Unspecified`** must produce `outcome_stated = false` and `n_active = NULL`, never 0 — PubChem's own summary endpoint reports `SIDCountActive: 0` for exactly this case (Task 6).
2. **An activity row whose assay is a ChEMBL-computed selectivity or therapeutic index** must be labelled `derived` and must not count as a cytotoxicity or potency measurement (Task 3).
3. **A screen filed against a `PROTEIN COMPLEX`** must not become either subunit's protein assay; `crosswalk.chembl_targets` maps the ClpP1P2 target to both `Rv2461c` and `Rv2460c` as `direct` (Tasks 2 and 9).
4. **A PubChem CID with no UniChem mapping** must still produce a real result row, with `molecule_chembl_id` NULL rather than the row being dropped (Task 5).
5. **A store built before these tables exist** must still let `atlas summary` run, reporting absence rather than raising — the `EMPTY_OPTIONAL` pattern (Task 10).

---

## Files

**Create:**
- `atlas/sources/pubchem.py` — AID discovery, per-AID result tables, project links
- `atlas/sources/unichem.py` — the ChEMBL ↔ PubChem compound bridge
- `tests/test_screens.py` — the classifiers and the campaign normalizers
- `tests/test_pubchem.py` — AID discovery, outcomes, projects
- `tests/fixtures/chembl_assay_census.json`
- `tests/fixtures/chembl_campaign_assays.json`
- `tests/fixtures/pubchem_aid_summary.json`
- `tests/fixtures/pubchem_aid_results.csv`
- `tests/fixtures/pubchem_aid_unspecified.csv`
- `tests/fixtures/pubchem_projects.json`
- `tests/fixtures/unichem_src1src22.txt`

**Modify:**
- `atlas/sources/chembl.py` — the census, the campaign document fetch, the prose classifiers
- `atlas/summary.py` — read the census; add the screen roll-up columns
- `atlas/pipeline.py` — wire the new builds into the evidence stage
- `atlas/storediff.py` — keys for the new tables
- `atlas/freshness.py` — a PubChem probe
- `atlas/agent.py` — `TABLES` and `TABLE_NOTES` for the new tables
- `tests/conftest.py` — fixture store gains the new tables
- `tests/fixtures/README.md` — which fixture proves what
- `docs/data-sources.md` — PubChem and UniChem entries; correct the assay numbers
- `README.md` — correct the headline assay numbers

---

### Task 1: The assay census

The store holds only activity rows that carry a `pchembl_value`, so every count of "how big was the biggest assay" is computed from a filtered sample. This task fetches the unfiltered per-assay census and writes it as its own small table.

**Files:**
- Modify: `atlas/sources/chembl.py`
- Create: `tests/fixtures/chembl_assay_census.json`
- Test: `tests/test_screens.py`

**Interfaces:**
- Consumes: `pages()`, `write_parquet()`, `release_from_api()`, `SOURCE`, `PAGE` — all already in `chembl.py`.
- Produces: `CENSUS_FIELDS: str`, `census_rows(target_id: str, *, force: bool = False) -> list[dict]`, `aggregate_sizes(target_id: str, rows: Iterable[Mapping]) -> Iterator[dict]`, and `build_bioactivity` returning a third path for `assay_sizes.parquet`. Row shape: `{"target_chembl_id": str, "assay_chembl_id": str, "n_compounds": int, "n_measurements": int, "endpoint_types": list[str], "latest_year": int | None}`.

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/chembl_assay_census.json`. Three assays on two targets: a 4-compound percent-effect screen, a 2-compound IC50 follow-up, and one duplicate measurement so `n_compounds` and `n_measurements` differ.

```json
{
  "activities": [
    {"assay_chembl_id": "CHEMBL4649965", "molecule_chembl_id": "CHEMBL1", "standard_type": "Percent Effect", "document_year": 2021},
    {"assay_chembl_id": "CHEMBL4649965", "molecule_chembl_id": "CHEMBL2", "standard_type": "Percent Effect", "document_year": 2021},
    {"assay_chembl_id": "CHEMBL4649965", "molecule_chembl_id": "CHEMBL3", "standard_type": "Percent Effect", "document_year": 2021},
    {"assay_chembl_id": "CHEMBL4649965", "molecule_chembl_id": "CHEMBL4", "standard_type": "Percent Effect", "document_year": 2021},
    {"assay_chembl_id": "CHEMBL4649965", "molecule_chembl_id": "CHEMBL4", "standard_type": "Percent Effect", "document_year": 2021},
    {"assay_chembl_id": "CHEMBL9001", "molecule_chembl_id": "CHEMBL1", "standard_type": "IC50", "document_year": 2022},
    {"assay_chembl_id": "CHEMBL9001", "molecule_chembl_id": "CHEMBL2", "standard_type": "IC50", "document_year": 2022},
    {"assay_chembl_id": null, "molecule_chembl_id": "CHEMBL5", "standard_type": "IC50", "document_year": 2022}
  ],
  "page_meta": {"total_count": 8}
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_screens.py`:

```python
"""Campaign-level screening evidence: the census, the classifiers, the tables.

The classifiers read the depositor's own prose, the same standing as
`classify_condition`, so every case here is a shape seen in the live store.
"""

from __future__ import annotations

import json
from pathlib import Path

from atlas.sources.chembl import aggregate_sizes

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
        {"assay_chembl_id": "A", "molecule_chembl_id": "M1", "standard_type": "Percent Effect"},
        {"assay_chembl_id": "A", "molecule_chembl_id": "M2", "standard_type": "IC50"},
    ]
    row = next(iter(aggregate_sizes("T", mixed)))
    assert row["endpoint_types"] == ["IC50", "Percent Effect"]
    assert row["latest_year"] is None
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `uv run pytest tests/test_screens.py -v`
Expected: FAIL with `ImportError: cannot import name 'aggregate_sizes'`

- [ ] **Step 4: Implement the census**

In `atlas/sources/chembl.py`, after `build_bioactivity` (grep for `# --- TB drugs and clinical candidates`) and before that section marker, add:

```python
# --- the assay census: how big was the assay, not how potent was the hit -----

# `activities` carries only rows with a pchembl_value, because that is the
# potency evidence. A primary screen reports percent inhibition and gets no
# pchembl, so counting assays or their compounds from that table measures the
# follow-ups and misses the campaign: ChEMBL files 276,472 `Percent Effect`
# rows against Mtb proteins against 19,754 affinity rows. The census is the
# same query without the filter and with only the fields a count needs.
CENSUS_FIELDS = "assay_chembl_id,molecule_chembl_id,standard_type,document_year"


def census_rows(target_id: str, *, force: bool = False) -> list[dict[str, Any]]:
    """Every activity on one target, unfiltered, cached page by page."""
    return pages(
        "activity",
        f"target_chembl_id={target_id}&only={CENSUS_FIELDS}",
        "activities",
        f"census/{target_id}",
        force=force,
    )


def aggregate_sizes(target_id: str, rows: Iterable[Mapping[str, Any]]) -> Iterator[dict[str, Any]]:
    """One row per assay: distinct compounds, measurements, endpoints, latest year.

    Distinct compounds is the number that answers "is there a tractable screen
    here"; measurements is kept beside it because the two differing is normal
    and their ratio is the only hint that an assay was re-run.
    """
    by_assay: dict[str, dict[str, Any]] = {}
    for row in rows:
        assay = row.get("assay_chembl_id")
        if not assay:
            continue
        entry = by_assay.setdefault(
            assay, {"compounds": set(), "types": set(), "measurements": 0, "year": None}
        )
        entry["measurements"] += 1
        if molecule := row.get("molecule_chembl_id"):
            entry["compounds"].add(molecule)
        if endpoint := row.get("standard_type"):
            entry["types"].add(endpoint)
        year = row.get("document_year")
        if year is not None and (entry["year"] is None or year > entry["year"]):
            entry["year"] = year
    for assay, entry in sorted(by_assay.items()):
        yield {
            "target_chembl_id": target_id,
            "assay_chembl_id": assay,
            "n_compounds": len(entry["compounds"]),
            "n_measurements": entry["measurements"],
            "endpoint_types": sorted(entry["types"]),
            "latest_year": entry["year"],
        }
```

`Iterator` and `Mapping` are needed in the imports: change the `collections.abc` import at the top of the file to `from collections.abc import Iterable, Iterator, Mapping, Sequence`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_screens.py -v`
Expected: 3 passed

- [ ] **Step 6: Write the build function and wire it in**

Still in `atlas/sources/chembl.py`, replace the body of `build_bioactivity` (grep `def build_bioactivity`) so it writes the third table. The census covers the protein targets the crosswalk resolved — not the whole-cell ones, whose 209,493 rows say nothing about a protein assay:

```python
def build_bioactivity(targets: Iterable[tuple[str, str]], *, retrieved_at: str) -> list[Path]:
    """Activities, compounds, and the unfiltered assay census."""
    targets = sorted(set(targets))
    version = release_from_api()

    rows = target_activities(targets)
    molecule_ids = sorted({r["molecule_chembl_id"] for r in rows if r["molecule_chembl_id"]})
    rows += whole_cell_activities(molecule_ids)
    compounds = molecules(molecule_ids)
    rows = annotate_activities(rows, compounds)

    sizes: list[dict[str, Any]] = []
    for target_id, _ in targets:
        sizes += aggregate_sizes(target_id, census_rows(target_id))

    return [
        write_parquet(
            "activities", rows, source=SOURCE, source_version=version, retrieved_at=retrieved_at
        ),
        write_parquet(
            "compounds", compounds, source=SOURCE, source_version=version, retrieved_at=retrieved_at
        ),
        write_parquet(
            "assay_sizes", sizes, source=SOURCE, source_version=version, retrieved_at=retrieved_at
        ),
    ]
```

- [ ] **Step 7: Add the diff key**

In `atlas/storediff.py`, add to `KEYS` after the `"compounds"` line:

```python
    "assay_sizes": ("target_chembl_id", "assay_chembl_id"),
```

A row count would hide the thing this table exists to show: an assay that loses half its compounds upstream still counts as one assay.

- [ ] **Step 8: Run the whole suite and lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass. `test_summary.py` still passes because nothing reads `assay_sizes` yet.

- [ ] **Step 9: Commit**

```bash
git add atlas/sources/chembl.py atlas/storediff.py tests/test_screens.py tests/fixtures/chembl_assay_census.json
git commit -m "feat: count an assay's compounds without the potency filter"
```

---

### Task 2: The corrected numbers, and the complex rule that has to come with them

`n_protein_assays` and `max_assay_compounds` now read the census. This changes published numbers, so the documentation moves in the same commit.

**Files:**
- Modify: `atlas/summary.py`
- Modify: `tests/conftest.py`
- Modify: `docs/data-sources.md`, `README.md`
- Test: `tests/test_summary.py`

**Interfaces:**
- Consumes: `assay_sizes.parquet` from Task 1.
- Produces: `target_summary` columns `n_protein_assays`, `max_assay_compounds`, `latest_protein_assay_year` (recomputed) and `n_complex_assays`, `max_complex_assay_compounds` (new).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_summary.py`:

```python
def test_assay_size_comes_from_the_census_not_the_potency_rows(summary_store):
    """A primary screen reports percent inhibition, so it has no pchembl row.

    Reading assay size from `activities` measured the follow-ups and missed
    the campaign -- pks13 read 143 compounds against a 66,592-compound screen.
    """
    rows = _rows(summary_store, "SELECT * FROM target_summary WHERE rv_id = 'Rv3800c'")
    assert rows[0]["max_assay_compounds"] == 4
    assert rows[0]["n_protein_assays"] == 2


def test_a_complex_screen_is_not_either_subunits_protein_assay(summary_store):
    """ClpP1P2's target maps to both clpP1 and clpP2 as `direct`.

    Counting it would hand each subunit a screen of the pair, which is the
    rule `n_complex_drugs` already follows for the ribosome's 45 drugs.
    """
    rows = _rows(
        summary_store,
        "SELECT * FROM target_summary WHERE rv_id IN ('Rv2460c', 'Rv2461c') ORDER BY rv_id",
    )
    for row in rows:
        assert row["n_protein_assays"] == 0
        assert row["max_assay_compounds"] == 0
        # Shown, never counted.
        assert row["n_complex_assays"] == 1
        assert row["max_complex_assay_compounds"] == 3


def test_a_store_without_the_census_still_summarises(tmp_path, store):
    """An older store has no assay_sizes table; absence is not a failure."""
    import shutil

    from atlas import summary

    for parquet in store.glob("*.parquet"):
        shutil.copy(parquet, tmp_path / parquet.name)
    (tmp_path / "assay_sizes.parquet").unlink(missing_ok=True)
    summary.build(store=tmp_path)
    rows = _rows(tmp_path, "SELECT * FROM target_summary WHERE rv_id = 'Rv3800c'")
    assert rows[0]["n_protein_assays"] == 0
```

If `tests/test_summary.py` has no `_rows` helper and no `summary_store` fixture, grep it for how existing tests read the table and follow that; the assertions above are what matters, not the accessor.

- [ ] **Step 2: Extend the fixture store so the test has something to count**

In `tests/conftest.py`, inside the `summary_store` fixture (grep for where it writes `activities`), add an `assay_sizes` table. Two single-protein assays on Pks13's target and one complex assay on ClpP1P2's, matching the accessions the committed `chembl_uniprot_mapping.txt` fixture carries:

```python
    write_parquet(
        "assay_sizes",
        [
            {
                "target_chembl_id": "CHEMBL4105939",
                "assay_chembl_id": "CHEMBL4649965",
                "n_compounds": 4,
                "n_measurements": 5,
                "endpoint_types": ["Percent Effect"],
                "latest_year": 2021,
            },
            {
                "target_chembl_id": "CHEMBL4105939",
                "assay_chembl_id": "CHEMBL9001",
                "n_compounds": 2,
                "n_measurements": 2,
                "endpoint_types": ["IC50"],
                "latest_year": 2022,
            },
            {
                "target_chembl_id": "CHEMBL4662931",
                "assay_chembl_id": "CHEMBL4649972",
                "n_compounds": 3,
                "n_measurements": 3,
                "endpoint_types": ["Percent Effect"],
                "latest_year": 2021,
            },
        ],
        source="chembl",
        source_version="chembl_37 (01/05/2026)",
        retrieved_at="2026-10-09",
        store=out,
    )
```

The fixture mapping file must contain the three target rows these ids refer to. Check with:

```bash
awk -F'\t' '$2=="CHEMBL4105939"||$2=="CHEMBL4662931"' tests/fixtures/chembl_uniprot_mapping.txt
```

If they are absent, append them — `I6X8D2` for Pks13 (`Rv3800c`), and `P9WPC5` plus `P9WPC3` for the ClpP1P2 complex (`Rv2461c`, `Rv2460c`), which is how the live file maps them:

```
I6X8D2	CHEMBL4105939	Polyketide synthase Pks13	SINGLE PROTEIN
P9WPC5	CHEMBL4662931	ClpP1P2	PROTEIN COMPLEX
P9WPC3	CHEMBL4662931	ClpP1P2	PROTEIN COMPLEX
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_summary.py -k "census or complex_screen" -v`
Expected: FAIL — `max_assay_compounds` is 0 or wrong, and `n_complex_assays` does not exist.

- [ ] **Step 4: Teach the roll-up the new source**

Four edits in `atlas/summary.py`. Grep for each anchor rather than trusting line numbers.

(a) `gene_target` must carry the target type. Replace:

```sql
WITH gene_target AS (
    SELECT w.rv_id, t.target_id, t.evidence
    FROM walk w, UNNEST(w.chembl_targets) AS u(t)
),
```

with:

```sql
WITH gene_target AS (
    SELECT w.rv_id, t.target_id, t.evidence, t.target_type
    FROM walk w, UNNEST(w.chembl_targets) AS u(t)
),
```

(b) Delete the two lines in `protein_act` that compute assay counts from `act` — the `count(DISTINCT a.assay_chembl_id) FILTER (...) AS n_protein_assays,` pair and the `max(a.document_year) FILTER (...) AS latest_protein_assay_year` pair — along with the comment above them that explains the `direct` filter. Delete the whole `screening AS ( ... ),` CTE.

(c) Add a new CTE in their place:

```sql
assay_scale AS (
    -- Assay existence and size come from the census, never from `act`:
    -- `activities` holds only rows with a potency value, so a 66,592-compound
    -- primary screen reporting percent inhibition is invisible there and
    -- pks13 read 143. `direct` only, because an assay on M. smegmatis MmpL3
    -- is a real assay on another organism's protein.
    --
    -- SINGLE PROTEIN only, the same rule n_complex_drugs follows. The
    -- crosswalk maps the ClpP1P2 complex target to clpP1 AND clpP2, so
    -- without the filter each subunit is credited with a screen of the pair.
    SELECT gt.rv_id,
           count(DISTINCT s.assay_chembl_id)
               FILTER (WHERE gt.target_type = 'SINGLE PROTEIN') AS n_protein_assays,
           max(s.n_compounds)
               FILTER (WHERE gt.target_type = 'SINGLE PROTEIN') AS max_assay_compounds,
           max(s.latest_year)
               FILTER (WHERE gt.target_type = 'SINGLE PROTEIN') AS latest_protein_assay_year,
           count(DISTINCT s.assay_chembl_id)
               FILTER (WHERE gt.target_type <> 'SINGLE PROTEIN') AS n_complex_assays,
           max(s.n_compounds)
               FILTER (WHERE gt.target_type <> 'SINGLE PROTEIN') AS max_complex_assay_compounds
    FROM gene_target gt
    JOIN sizes s ON s.target_chembl_id = gt.target_id
    WHERE gt.evidence = 'direct'
    GROUP BY 1
),
```

(d) In the final `SELECT`, replace the two existing lines

```sql
    coalesce(pa.n_protein_assays, 0) AS n_protein_assays,
    coalesce(sc.max_assay_compounds, 0)   AS max_assay_compounds,
```

with

```sql
    coalesce(asz.n_protein_assays, 0)        AS n_protein_assays,
    coalesce(asz.max_assay_compounds, 0)     AS max_assay_compounds,
    coalesce(asz.n_complex_assays, 0)        AS n_complex_assays,
    coalesce(asz.max_complex_assay_compounds, 0) AS max_complex_assay_compounds,
```

and change the `latest_protein_assay_year` reference in the same `SELECT` from `pa.` to `asz.`. Then find the `LEFT JOIN` for the deleted `screening` CTE (grep `screening sc`) and replace it with `LEFT JOIN assay_scale asz ON asz.rv_id = g.rv_id`, dropping the `protein_act`-based join only if `protein_act` is now unreferenced — it is not; it still supplies `n_compounds` and `best_pchembl`.

(e) Register the table. In `TABLES` add `"sizes": "assay_sizes",` and in `EMPTY_OPTIONAL` add the stand-in, so a store built before this table exists still summarises:

```python
    "assay_sizes": "SELECT NULL::VARCHAR AS target_chembl_id,"
    " NULL::VARCHAR AS assay_chembl_id, NULL::BIGINT AS n_compounds,"
    " NULL::BIGINT AS n_measurements, NULL::VARCHAR[] AS endpoint_types,"
    " NULL::BIGINT AS latest_year WHERE false",
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_summary.py -v && uv run pytest -q`
Expected: all pass. If a pre-existing `n_protein_assays` assertion fails, the number it asserts was computed from the potency rows; recompute it from the fixture's `assay_sizes` and update it, noting why in the test's docstring.

- [ ] **Step 6: Rebuild and read the real numbers**

Run:

```bash
uv run atlas evidence
uv run atlas summary
uv run python -c "
import duckdb
print(duckdb.sql(\"SELECT gene_name, n_protein_assays, max_assay_compounds, n_complex_assays FROM 'data/store/target_summary.parquet' WHERE max_assay_compounds >= 1000 ORDER BY max_assay_compounds DESC\"))
print(duckdb.sql(\"SELECT count(*) FILTER (WHERE max_assay_compounds >= 1000) AS over_1000, count(*) FILTER (WHERE max_assay_compounds >= 100) AS over_100 FROM 'data/store/target_summary.parquet'\"))
"
```

Record the actual output. The spec predicts seven genes at 1,000+ compounds, five of them above 60,000, from the Dundee/GHDDI deposit. **If the number differs, the documentation in the next step takes the measured number, not the spec's.**

- [ ] **Step 7: Correct the documentation**

In `docs/data-sources.md`, under "Screened, or merely studied?", replace the paragraph beginning "Genome-wide the answer is stark" with the measured numbers, and add why the count changed:

```markdown
Genome-wide, the largest single assays come from one 2021 deposit
(`CHEMBL3988442`, Dundee/GHDDI/Cornell): Pks13 at 66,592 compounds, CoaBC at
66,942, TrpRS at 65,366, ClpP1P2 at 68,611 and AspRS at 8,841, alongside the
two PubChem deposits that were already visible, `recA` (1,875) and `dnaB`
(1,642). inhA, the best-studied target in TB, still tops out at 52 compounds
in any single assay.

**This number was wrong until the census landed.** It is computed from
`assay_sizes`, which counts every activity row ChEMBL files against an assay.
Reading it from `activities` instead counted only rows carrying a
`pchembl_value`, and a primary screen reports percent inhibition: ChEMBL holds
276,472 `Percent Effect` rows against Mtb proteins against 19,754 affinity
rows, so the five 60,000-compound screens above read as 143, 0, 2, 8 and 12.
The scarcity is still the finding, but it is a scarcity of *campaigns* and not
of compounds.

A screen of `ClpP1P2` is not a screen of `clpP1`. The crosswalk maps that
`PROTEIN COMPLEX` target to both subunits as `direct`, so the counts filter on
`SINGLE PROTEIN` — the rule `n_complex_drugs` already follows — and the
complex screens are reported in `n_complex_assays`.
```

In `README.md`, find the assay line in the "What it answers" block and correct it to the measured numbers from Step 6.

- [ ] **Step 8: Verify the docs match the store**

Run the Step 6 query again and read the output against what you just wrote. Every number in the new prose must appear in that output.

- [ ] **Step 9: Commit**

```bash
git add atlas/summary.py tests/conftest.py tests/test_summary.py tests/fixtures/chembl_uniprot_mapping.txt docs/data-sources.md README.md
git commit -m "fix: assay size came from the potency rows, so every campaign read small"
```

---

### Task 3: The prose classifiers

Modality, funnel stage and the derived-index exclusion. Pure functions, no network, and the only place in this plan where the pipeline interprets a human sentence.

**Files:**
- Modify: `atlas/sources/chembl.py`
- Test: `tests/test_screens.py`

**Interfaces:**
- Produces: `MODALITIES: tuple[str, ...]`, `is_derived(description: str | None) -> bool`, `classify_modality(description: str | None, target_type: str | None, organism: str | None) -> str`, `classify_stage(description: str | None, *, pubchem_type: str | None = None, modality: str | None = None) -> str`. **Every caller passes `modality`** where it has one: `classify_stage` derives the `profiling` stage from it, which is what stops the two axes drifting apart. With no modality it reads one from the description itself.
- Vocabulary, fixed here and relied on by Tasks 5–9. `modality`: `phenotypic_mtb`, `biochemical_mtb`, `mammalian_cytotox`, `adme`, `in_vivo_efficacy`, `other_pathogen`, `other`. `stage`: `primary`, `confirmatory`, `counter_screen`, `profiling`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_screens.py`:

```python
from atlas.sources.chembl import classify_modality, classify_stage, is_derived


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
    # A cell line target is a mammalian reading whatever the prose says.
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_screens.py -k "derived or modality or stage" -v`
Expected: FAIL with `ImportError: cannot import name 'classify_modality'`

- [ ] **Step 3: Implement the classifiers**

In `atlas/sources/chembl.py`, directly after the `_CONDITIONS` block and `classify_condition` (grep `def classify_condition`), add:

```python
# --- what was measured, and where in the funnel -------------------------------
#
# ChEMBL has no modality or stage field, so these read the depositor's prose
# the same way `classify_condition` does, and carry the same standing: the
# description is stored beside the label so a reader can check it, and the
# table records `stages_source = 'from_prose'` wherever that is what happened.

MODALITIES = (
    "phenotypic_mtb",
    "biochemical_mtb",
    "mammalian_cytotox",
    "adme",
    "in_vivo_efficacy",
    "other_pathogen",
    "other",
)

# A ratio ChEMBL computed from two other rows. 6,577 compounds in the Mtb
# whole-cell literature carry one, and counting them as cytotoxicity readings
# inflated that coverage before they were excluded. The number is real; it is
# just not a measurement, so it is labelled and left out of the counts.
_DERIVED = re.compile(
    r"^\s*(selectivity|therapeutic|resistance)\s+(index|ratio)\b|\bratio of\b", re.I
)

# An animal, a bacterial readout, and the organism named. All three, because
# "Toxicity in BALB/c mouse" is an animal study and not an efficacy result,
# and a mouse PK curve is ADME.
_ANIMAL = re.compile(r"\b(mice|mouse|murine|guinea pig|marmoset|rabbit|rat|rats)\b", re.I)
_BACTERIAL_READOUT = re.compile(r"\b(cfu|lung|spleen|bacterial load|burden|survival)\b", re.I)
_ADME = re.compile(
    r"pharmacokinetic|\bauc\b|cmax|half[- ]life|\bt1/2\b|bioavailab|clearance|microsom|"
    r"hepatocyte|solubility|permeab|caco|plasma protein|metabolic stability|\bcyp\b",
    re.I,
)
_CYTOTOX = re.compile(r"cytotox|\bcc50\b|cell viability|\bvero\b|hepg2", re.I)
_MTB = re.compile(r"tubercul", re.I)


def is_derived(description: str | None) -> bool:
    """Whether this assay reports a ratio of two other assays' numbers."""
    return bool(description and _DERIVED.search(description))


def classify_modality(
    description: str | None, target_type: str | None, organism: str | None
) -> str:
    """What this assay measured, from its own target record and its prose.

    The target record is checked before the prose wherever it is decisive: a
    `CELL-LINE` target is a mammalian reading whatever the sentence says, and
    an `ORGANISM` target that is not Mtb is another pathogen even when the
    sentence contains the word "inhibition".
    """
    text = description or ""
    organism = organism or ""
    if _ANIMAL.search(text) and _BACTERIAL_READOUT.search(text) and _MTB.search(text):
        return "in_vivo_efficacy"
    if target_type == "ADMET" or _ADME.search(text):
        return "adme"
    if target_type == "CELL-LINE" or _CYTOTOX.search(text):
        return "mammalian_cytotox"
    if organism.startswith("Mycobacterium tuberculosis"):
        if target_type == "ORGANISM":
            return "phenotypic_mtb"
        if target_type in ("SINGLE PROTEIN", "PROTEIN COMPLEX", "PROTEIN FAMILY"):
            return "biochemical_mtb"
    if target_type == "ORGANISM":
        return "other_pathogen"
    return "other"


# PubChem states the stage; ChEMBL leaves it in the prose. `primary` is the
# fallback for an Mtb assay that names no stage, because a paper's MIC table
# is the first time its compounds met the organism.
_COUNTER = re.compile(r"counter-?screen|selectivity against|counterscreen", re.I)
_CONFIRM = re.compile(r"dose[- ]?response|confirmat|retest|titration|\bqhts\b", re.I)
_PROFILING = re.compile(
    r"cytotox|\bcc50\b|cell viability|hepg2|pharmacokinetic|microsom|hepatocyte|solubility|"
    r"permeab|clearance|\bcfu\b|lung|spleen",
    re.I,
)


def classify_stage(description: str | None, *, pubchem_type: str | None = None) -> str:
    """Where in the funnel this assay sits.

    `pubchem_type` is the depositor's own word and wins outright when present.
    """
    if pubchem_type:
        stated = pubchem_type.strip().lower()
        if stated == "confirmatory":
            return "confirmatory"
        if stated == "screening":
            return "primary"
    text = description or ""
    if _COUNTER.search(text):
        return "counter_screen"
    if _CONFIRM.search(text):
        return "confirmatory"
    if _PROFILING.search(text):
        return "profiling"
    return "primary"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_screens.py -v`
Expected: all pass. If `test_adme_does_not_match_an_antibacterial_assay` fails on the hemolysis case, the assertion is `!= "adme"` — check what it returns and that the value is defensible, rather than widening `_ADME` to catch it.

- [ ] **Step 5: Commit**

```bash
git add atlas/sources/chembl.py tests/test_screens.py
git commit -m "feat: read what an assay measured, and where in the funnel it sits"
```

---

### Task 4: The campaign documents, and every assay in them

An Mtb-target query sees 11,686 assays in these documents. A document query sees 38,335. The difference is every cytotoxicity, microsome and animal assay — the whole hit-profiling layer.

**Files:**
- Modify: `atlas/sources/chembl.py`
- Create: `tests/fixtures/chembl_campaign_assays.json`
- Test: `tests/test_screens.py`

**Interfaces:**
- Consumes: `pages()`, `fetch_json_many()`, `classify_modality`, `classify_stage`, `is_derived`.
- Produces: `CAMPAIGN_ASSAY_FIELDS: str`, `CAMPAIGN_ACTIVITY_FIELDS: str`, `campaign_documents(activities: Iterable[Mapping]) -> list[str]`, `campaign_assays(documents: Sequence[str], *, force: bool = False) -> list[dict]`, `campaign_activities(documents: Sequence[str], *, force: bool = False) -> list[dict]`, `normalize_campaign_assays(assays, targets) -> list[dict]`.
- `normalize_campaign_assays` row shape: `{"stage_id", "screen_id", "assay_chembl_id", "document_chembl_id", "stage", "modality", "description", "target_chembl_id", "target_type", "target_organism", "derived", "assay_condition", "strain"}`.

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/chembl_campaign_assays.json` — one document with the whole ladder plus a derived index and a non-Mtb organism, which is the real shape of a med-chem TB paper:

```json
{
  "assays": [
    {"assay_chembl_id": "CHEMBL100", "document_chembl_id": "CHEMBL_DOC1", "assay_type": "F", "target_chembl_id": "CHEMBL360", "description": "Antitubercular activity against Mycobacterium tuberculosis H37Rv after 14 days by MABA", "assay_strain": "H37Rv"},
    {"assay_chembl_id": "CHEMBL101", "document_chembl_id": "CHEMBL_DOC1", "assay_type": "B", "target_chembl_id": "CHEMBL4105939", "description": "Inhibition of Mycobacterium tuberculosis Pks13 thioesterase", "assay_strain": null},
    {"assay_chembl_id": "CHEMBL102", "document_chembl_id": "CHEMBL_DOC1", "assay_type": "T", "target_chembl_id": "CHEMBL_VERO", "description": "Cytotoxicity against african green monkey Vero cells after 72 hrs by MTT assay", "assay_strain": null},
    {"assay_chembl_id": "CHEMBL103", "document_chembl_id": "CHEMBL_DOC1", "assay_type": "A", "target_chembl_id": null, "description": "Metabolic stability in human liver microsomes", "assay_strain": null},
    {"assay_chembl_id": "CHEMBL104", "document_chembl_id": "CHEMBL_DOC1", "assay_type": "F", "target_chembl_id": null, "description": "Antitubercular activity against Mycobacterium tuberculosis H37Rv infected in BALB/c mouse assessed as reduction in CFU count in lung at 25 mg/kg", "assay_strain": null},
    {"assay_chembl_id": "CHEMBL105", "document_chembl_id": "CHEMBL_DOC1", "assay_type": "F", "target_chembl_id": "CHEMBL_SAUR", "description": "Growth inhibition of Staphylococcus aureus Newman", "assay_strain": null},
    {"assay_chembl_id": "CHEMBL106", "document_chembl_id": "CHEMBL_DOC1", "assay_type": "F", "target_chembl_id": null, "description": "Selectivity index, ratio of CC50 for Vero cells to MIC for Mycobacterium tuberculosis H37Rv", "assay_strain": null}
  ],
  "targets": {
    "CHEMBL360": {"target_type": "ORGANISM", "organism": "Mycobacterium tuberculosis"},
    "CHEMBL4105939": {"target_type": "SINGLE PROTEIN", "organism": "Mycobacterium tuberculosis"},
    "CHEMBL_VERO": {"target_type": "CELL-LINE", "organism": "Chlorocebus aethiops"},
    "CHEMBL_SAUR": {"target_type": "ORGANISM", "organism": "Staphylococcus aureus"}
  }
}
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_screens.py`:

```python
from atlas.sources.chembl import campaign_documents, normalize_campaign_assays


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
    # Everything else in the paper is a measurement.
    assert sum(row["derived"] for row in normalize_campaign_assays(assays, targets)) == 1


def test_a_whole_cell_stage_keeps_its_condition_and_strain():
    assays, targets = _campaign()
    by_assay = {row["assay_chembl_id"]: row for row in normalize_campaign_assays(assays, targets)}
    # The existing condition classifier, reused: this one names no medium.
    assert by_assay["CHEMBL100"]["assay_condition"] == "unspecified"
    assert by_assay["CHEMBL100"]["strain"] == "H37Rv"
    # A biochemical assay on purified protein has no growth condition at all.
    assert by_assay["CHEMBL101"]["assay_condition"] is None


def test_campaign_documents_are_the_documents_behind_whole_cell_activities():
    activities = [
        {"assay_chembl_id": "A", "evidence": "whole_cell", "document_chembl_id": "CHEMBL_DOC1"},
        {"assay_chembl_id": "B", "evidence": "direct", "document_chembl_id": "CHEMBL_DOC2"},
        {"assay_chembl_id": "C", "evidence": "whole_cell", "document_chembl_id": None},
    ]
    assert campaign_documents(activities) == ["CHEMBL_DOC1"]
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_screens.py -k campaign -v`
Expected: FAIL with `ImportError: cannot import name 'campaign_documents'`

- [ ] **Step 4: Implement**

In `atlas/sources/chembl.py`, after the classifiers from Task 3, add:

```python
# --- campaigns: the document, and every assay in it --------------------------
#
# A campaign's cytotoxicity, microsome and animal assays are filed against
# CELL-LINE, ADMET and non-molecular targets, so a target-keyed query cannot
# see them: these documents hold 11,686 assays on Mtb targets and 38,335 in
# total. The document is therefore the unit of the second fetch.

CAMPAIGN_ASSAY_FIELDS = (
    "assay_chembl_id,document_chembl_id,assay_type,target_chembl_id,description,assay_strain"
)
CAMPAIGN_ACTIVITY_FIELDS = (
    "activity_id,assay_chembl_id,document_chembl_id,molecule_chembl_id,standard_type,"
    "standard_relation,standard_value,standard_units,pchembl_value,activity_comment"
)
# Ten documents per request, not fifty: one deposited dataset holds 410k
# activity rows, and a batch containing it pages past ChEMBL's patience at
# deep offsets. Deposited datasets are fetched by target instead, which is
# what `census_rows` already does.
DOC_BATCH = 10


def campaign_documents(activities: Iterable[Mapping[str, Any]]) -> list[str]:
    """The documents that reported whole-cell Mtb activity.

    These are the campaigns: a paper that measured growth inhibition is the
    unit a screening record is organised by, and whatever else it measured on
    the same compounds is its hit profiling.
    """
    return sorted(
        {
            row["document_chembl_id"]
            for row in activities
            if row.get("evidence") == "whole_cell" and row.get("document_chembl_id")
        }
    )


def campaign_assays(documents: Sequence[str], *, force: bool = False) -> list[dict[str, Any]]:
    """Every assay in these documents, whatever it was run against."""
    rows: list[dict[str, Any]] = []
    for index in range(0, len(documents), DOC_BATCH):
        batch = documents[index : index + DOC_BATCH]
        rows += pages(
            "assay",
            f"document_chembl_id__in={','.join(batch)}&only={CAMPAIGN_ASSAY_FIELDS}",
            "assays",
            f"campaigns/assays-{index}",
            force=force,
        )
    return rows


def campaign_activities(documents: Sequence[str], *, force: bool = False) -> list[dict[str, Any]]:
    """Every activity in these documents, which is the per-compound coverage."""
    rows: list[dict[str, Any]] = []
    for index in range(0, len(documents), DOC_BATCH):
        batch = documents[index : index + DOC_BATCH]
        rows += pages(
            "activity",
            f"document_chembl_id__in={','.join(batch)}&only={CAMPAIGN_ACTIVITY_FIELDS}",
            "activities",
            f"campaigns/activities-{index}",
            force=force,
        )
    return rows


def campaign_targets(assays: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Target type and organism for every target these assays name.

    No `force`: this goes through `fetch_json_many`, which does not cache, so a
    parameter here would promise a re-download that `build-force` cannot give.
    """
    ids = sorted({a["target_chembl_id"] for a in assays if a.get("target_chembl_id")})
    out: dict[str, dict[str, Any]] = {}
    urls = [
        f"{API}/target.json?target_chembl_id__in={batch}"
        f"&only=target_chembl_id,target_type,organism&limit={ID_BATCH}"
        for batch in batches(ids)
    ]
    for payload in fetch_json_many(
        urls, workers=6, min_interval=0.1, label="chembl campaign targets"
    ).values():
        for target in payload["targets"]:
            out[target["target_chembl_id"]] = {
                "target_type": target.get("target_type"),
                "organism": target.get("organism"),
            }
    return out


def normalize_campaign_assays(
    assays: Iterable[Mapping[str, Any]], targets: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """One stage row per assay, with what it measured and where in the funnel."""
    rows = []
    for assay in assays:
        target = targets.get(assay.get("target_chembl_id") or "", {})
        description = assay.get("description")
        organism = target.get("organism")
        target_type = target.get("target_type")
        derived = is_derived(description)
        modality = "other" if derived else classify_modality(description, target_type, organism)
        rows.append(
            {
                "stage_id": f"chembl:{assay['assay_chembl_id']}",
                "screen_id": f"chembl:{assay['document_chembl_id']}",
                "assay_chembl_id": assay["assay_chembl_id"],
                "document_chembl_id": assay["document_chembl_id"],
                # modality travels with it: `classify_stage` derives `profiling`
                # from it, so that the two axes cannot drift apart. Passing the
                # description alone reintroduces the disagreement Task 3 fixed.
                "stage": classify_stage(description, modality=modality),
                "modality": modality,
                "description": description,
                "target_chembl_id": assay.get("target_chembl_id"),
                "target_type": target_type,
                "target_organism": organism,
                "derived": derived,
                # Only a whole-cell stage has a growth condition; purified
                # protein has no medium to speak of. Same rule as `activities`.
                "assay_condition": (
                    classify_condition(description) if modality == "phenotypic_mtb" else None
                ),
                "strain": assay.get("assay_strain"),
                # Filled by `stamp_stage_counts` once the activities are in
                # hand. Present here so both sources emit one key set for
                # `screen_stages` -- a column missing from half the rows types
                # as NULL for all of them.
                "n_tested": None,
                "n_active": None,
            }
        )
    return rows
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_screens.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add atlas/sources/chembl.py tests/test_screens.py tests/fixtures/chembl_campaign_assays.json
git commit -m "feat: a campaign is a document, and its stages are every assay in it"
```

---

### Task 5: The UniChem compound bridge

PubChem keys on CID and ChEMBL on `molecule_chembl_id`. One EBI file maps them, so no per-compound requests.

**Files:**
- Create: `atlas/sources/unichem.py`
- Create: `tests/fixtures/unichem_src1src22.txt`
- Test: `tests/test_pubchem.py`

**Interfaces:**
- Produces: `SOURCE: str = "unichem"`, `URL: str`, `fetch_raw(*, force=False) -> Fetched`, `normalize(path: Path) -> Iterator[dict]`, `chembl_by_cid(path: Path) -> dict[str, str]`.

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/unichem_src1src22.txt` — the real file's shape is a header line then two tab-separated columns, ChEMBL id first:

```
From src:'1'	To src:'22'
CHEMBL6329	4
CHEMBL1098659	5
CHEMBL1004	6
CHEMBL6328	
	7
```

The last two lines are malformed on purpose: a ChEMBL id with no CID, and a CID with no ChEMBL id. Both appear in the live file and neither is a mapping.

- [ ] **Step 2: Write the failing test**

Create `tests/test_pubchem.py`:

```python
"""PubChem campaigns and the UniChem bridge that reaches ChEMBL compounds."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.sources import unichem

FIXTURES = Path(__file__).parent / "fixtures"


def test_unichem_maps_cid_to_chembl_id_and_skips_half_rows():
    mapping = unichem.chembl_by_cid(FIXTURES / "unichem_src1src22.txt")
    assert mapping == {"4": "CHEMBL6329", "5": "CHEMBL1098659", "6": "CHEMBL1004"}


def test_unichem_normalize_keeps_both_identifiers():
    rows = list(unichem.normalize(FIXTURES / "unichem_src1src22.txt"))
    assert rows[0] == {"molecule_chembl_id": "CHEMBL6329", "pubchem_cid": "4"}
    assert len(rows) == 3
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_pubchem.py -v`
Expected: FAIL with `ImportError: cannot import name 'unichem'`

- [ ] **Step 4: Implement**

Create `atlas/sources/unichem.py`:

```python
"""UniChem: the ChEMBL <-> PubChem compound bridge, as one file.

PubChem keys a screening result on CID and ChEMBL keys a compound on
`molecule_chembl_id`. Without a bridge, a 215,397-compound screen cannot be
reached from a compound page. The alternatives were a request per compound
against PubChem's synonym endpoint, or PubChem's 1.5 GB CID-Synonym dump;
UniChem publishes the whole src1 <-> src22 mapping as a single gzipped file
from the same provider as ChEMBL.

Licence: UniChem is part of ChEMBL's distribution, CC BY-SA 3.0.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch

SOURCE = "unichem"
URL = (
    "https://ftp.ebi.ac.uk/pub/databases/chembl/UniChem/data/wholeSourceMapping/"
    "src_id1/src1src22.txt.gz"
)


def fetch_raw(*, force: bool = False) -> Fetched:
    return fetch(URL, "src1src22.txt.gz", source=SOURCE, min_interval=0.5, force=force)


def _lines(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        next(handle, None)  # the "From src:'1'  To src:'22'" header
        yield from handle


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    """One row per mapped pair. A half-row is not a mapping and is skipped."""
    for line in _lines(path):
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 2:
            continue
        chembl_id, cid = (part.strip() for part in parts)
        if not chembl_id or not cid:
            continue
        yield {"molecule_chembl_id": chembl_id, "pubchem_cid": cid}


def chembl_by_cid(path: Path) -> dict[str, str]:
    """CID -> ChEMBL id, for stamping a ChEMBL identity onto a PubChem result."""
    return {row["pubchem_cid"]: row["molecule_chembl_id"] for row in normalize(path)}
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_pubchem.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add atlas/sources/unichem.py tests/test_pubchem.py tests/fixtures/unichem_src1src22.txt
git commit -m "feat: one file bridges PubChem CIDs to ChEMBL compounds"
```

---

### Task 6: PubChem campaign discovery, and the zero that means "no call"

**Files:**
- Create: `atlas/sources/pubchem.py`
- Create: `tests/fixtures/pubchem_aid_summary.json`
- Test: `tests/test_pubchem.py`

**Interfaces:**
- Produces: `SOURCE: str = "pubchem"`, `EUTILS`, `PUG`, `MTB_TAXON = "1773"`, `SEARCH_TERM`, `fetch_aids(*, force=False) -> list[str]`, `fetch_summaries(aids, *, force=False) -> list[dict]`, `normalize_screens(summaries) -> list[dict]`, `includes_mtb(summary) -> bool`.
- `normalize_screens` row shape: `{"screen_id", "aid", "title", "depositor", "deposit_kind", "n_tested", "n_active", "n_inactive", "n_inconclusive", "outcome_stated", "library_size_stated", "pubmed_id", "year", "licence"}`.

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/pubchem_aid_summary.json`. Three AIDs: a real primary screen, the re-deposit whose rows are all `Unspecified` (where PubChem itself reports `SIDCountActive: 0`), and one tagged Mtb whose target is another organism.

```json
{
  "AssaySummaries": {
    "AssaySummary": [
      {
        "AID": 1626,
        "SourceName": "SRMLSC",
        "Name": "High Throughput Screen to Identify Inhibitors of Mycobacterium tuberculosis H37Rv",
        "Description": ["Screen of the 215,110-compound TAACF library against M. tuberculosis H37Rv."],
        "SIDCountAll": 215397,
        "SIDCountActive": 2044,
        "SIDCountInactive": 209843,
        "SIDCountInconclusive": 3510,
        "PubMedID": [19748740],
        "Target": [{"Name": "Mycobacterium tuberculosis H37Rv", "TaxonomyID": 83332}]
      },
      {
        "AID": 1671170,
        "SourceName": "ChEMBL",
        "Name": "Biochemical assay for Mt-TrpRS",
        "SIDCountAll": 65366,
        "SIDCountActive": 0,
        "SIDCountInactive": 0,
        "SIDCountInconclusive": 0,
        "Target": [{"Name": "Tryptophan--tRNA ligase", "TaxonomyID": 83332}]
      },
      {
        "AID": 9999,
        "SourceName": "Broad Institute",
        "Name": "Primary screen for inhibitors of Bos taurus MsrA",
        "SIDCountAll": 318000,
        "SIDCountActive": 1200,
        "SIDCountInactive": 316800,
        "SIDCountInconclusive": 0,
        "Target": [{"Name": "methionine sulfoxide reductase A", "TaxonomyID": 9913}]
      }
    ]
  }
}
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_pubchem.py`:

```python
from atlas.sources import pubchem


def _summaries() -> list[dict]:
    data = json.loads((FIXTURES / "pubchem_aid_summary.json").read_text())
    return data["AssaySummaries"]["AssaySummary"]


def test_zero_active_means_no_call_was_stated_not_that_nothing_was_active():
    """PubChem's summary reports SIDCountActive: 0 for a deposit with no cutoff.

    Read literally it says a 65,366-compound screen found nothing. The
    per-compound rows are 65,646 x Unspecified: the depositor never stated a
    threshold, so `n_active` is NULL and `outcome_stated` is false.
    """
    rows = {row["aid"]: row for row in pubchem.normalize_screens(_summaries())}
    assert rows["1671170"]["outcome_stated"] is False
    assert rows["1671170"]["n_active"] is None
    assert rows["1671170"]["n_inactive"] is None
    assert rows["1671170"]["n_tested"] == 65366


def test_a_real_screen_keeps_every_call_it_stated():
    rows = {row["aid"]: row for row in pubchem.normalize_screens(_summaries())}
    assert rows["1626"]["outcome_stated"] is True
    assert rows["1626"]["n_active"] == 2044
    assert rows["1626"]["n_inactive"] == 209843
    assert rows["1626"]["n_inconclusive"] == 3510
    assert rows["1626"]["screen_id"] == "pubchem:1626"
    assert rows["1626"]["depositor"] == "SRMLSC"


def test_the_library_the_prose_names_is_not_what_was_deposited():
    """AID 1259343 states ~300,000 screened and deposits 6,225 SIDs."""
    rows = {row["aid"]: row for row in pubchem.normalize_screens(_summaries())}
    assert rows["1626"]["library_size_stated"] == 215110
    assert rows["1626"]["n_tested"] == 215397
    assert rows["1671170"]["library_size_stated"] is None


def test_an_assay_tagged_mtb_whose_target_is_another_organism_is_not_included():
    """Several AIDs above 300,000 compounds target Bos taurus MsrA or S. aureus
    NadD while carrying an Mtb taxonomy tag."""
    assert pubchem.includes_mtb(_summaries()[0]) is True
    assert pubchem.includes_mtb(_summaries()[1]) is True
    assert pubchem.includes_mtb(_summaries()[2]) is False
    assert len(pubchem.normalize_screens(_summaries())) == 2
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_pubchem.py -k "zero_active or real_screen or library or another_organism" -v`
Expected: FAIL with `ImportError: cannot import name 'pubchem'`

- [ ] **Step 4: Implement**

Create `atlas/sources/pubchem.py`:

```python
"""PubChem BioAssay: the public Mtb screening campaigns, with their inactives.

PubChem is the only public source that states an outcome per compound at
screening scale -- AID 1626 deposits 209,843 `Inactive` rows beside its 2,044
actives -- which is what makes "tested and did nothing" a provable answer
rather than an absence.

Licence: per depositor, not per database. NCBI's policy puts US-government
material in the public domain but explicitly carves PubChem out: "resources
which incorporate material contributed or licensed by individuals, companies,
or organizations ... may be protected by U.S. and foreign copyright laws".
So `depositor` is recorded on every campaign and no blanket licence is claimed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..fetch import fetch

SOURCE = "pubchem"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
# PubChem asks for no more than 5 requests a second.
PACE = 0.25
# Taxonomy 1773 is M. tuberculosis; 83332 is H37Rv and sits inside it.
MTB_TAXON = "1773"
MTB_TAXA = {1773, 83332}
# Reproducible, and quoted in docs/data-sources.md: 12,519 AIDs on 2026-10-11.
SEARCH_TERM = f"txid{MTB_TAXON}[ORGN]"
AID_BATCH = 25

_MTB_NAME = re.compile(r"tubercul|mycobacter", re.I)
# "Screen of the 215,110-compound TAACF library": the depositor's own figure
# for the library, which is not the same claim as the set they deposited.
_LIBRARY_SIZE = re.compile(r"([\d,]{4,})\s*-?\s*compound", re.I)


def fetch_aids(*, force: bool = False) -> list[str]:
    """Every AID tagged M. tuberculosis, newest first."""
    page = fetch(
        f"{EUTILS}/esearch.fcgi?db=pcassay&term={SEARCH_TERM}&retmax=100000&retmode=json",
        "aids.json",
        source=SOURCE,
        min_interval=PACE,
        force=force,
        json_body=True,
    )
    return list(json.loads(page.text)["esearchresult"]["idlist"])


def fetch_summaries(aids: Sequence[str], *, force: bool = False) -> list[dict[str, Any]]:
    """The assay summary for each AID, which carries the counts and the target."""
    out: list[dict[str, Any]] = []
    for index in range(0, len(aids), AID_BATCH):
        batch = aids[index : index + AID_BATCH]
        page = fetch(
            f"{PUG}/assay/aid/{','.join(batch)}/summary/JSON",
            f"summaries/{index}.json",
            source=SOURCE,
            min_interval=PACE,
            force=force,
            json_body=True,
        )
        out += json.loads(page.text)["AssaySummaries"]["AssaySummary"]
    return out


def includes_mtb(summary: Mapping[str, Any]) -> bool:
    """Whether this assay's own record names Mtb, not merely its taxonomy tag.

    Several AIDs above 300,000 compounds carry an Mtb tag while the target is
    Bos taurus MsrA, S. aureus NadD or B. subtilis Sfp, so counting by
    taxonomy alone over-counts the screening record substantially.
    """
    for target in summary.get("Target") or []:
        if target.get("TaxonomyID") in MTB_TAXA:
            return True
        if _MTB_NAME.search(str(target.get("Name") or "")):
            return True
    return bool(_MTB_NAME.search(str(summary.get("Name") or "")))


def _library_size(summary: Mapping[str, Any]) -> int | None:
    for line in summary.get("Description") or []:
        if match := _LIBRARY_SIZE.search(str(line)):
            return int(match.group(1).replace(",", ""))
    return None


def normalize_screens(summaries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One campaign row per AID that names Mtb.

    `outcome_stated` is stored rather than derived because the alternative is
    reading `SIDCountActive: 0` as a finding. A deposit with no threshold
    reports zero actives and zero inactives against a full tested set, which
    means "no call", and `n_active` is NULL there. Anything else publishes a
    65,366-compound screen that found nothing.
    """
    rows = []
    for summary in summaries:
        if not includes_mtb(summary):
            continue
        tested = summary.get("SIDCountAll") or 0
        active = summary.get("SIDCountActive") or 0
        inactive = summary.get("SIDCountInactive") or 0
        inconclusive = summary.get("SIDCountInconclusive") or 0
        stated = bool(active or inactive or inconclusive)
        pubmed = summary.get("PubMedID") or []
        rows.append(
            {
                "screen_id": f"pubchem:{summary['AID']}",
                "aid": str(summary["AID"]),
                "title": summary.get("Name"),
                "depositor": summary.get("SourceName"),
                "deposit_kind": "dataset",
                # The depositor names the library in prose or not at all;
                # PubChem has no field for it.
                "library_name": None,
                "library_size_stated": _library_size(summary),
                "year": None,
                # Both set in `build`, once the project links are known.
                "n_stages": 1,
                "n_tested": tested,
                "n_active": active if stated else None,
                "n_inactive": inactive if stated else None,
                "n_inconclusive": inconclusive if stated else None,
                "outcome_stated": stated,
                "stages_source": "stated",
                "project_declared": False,
                "modalities": [],
                "document_chembl_id": None,
                "pubmed_id": str(pubmed[0]) if pubmed else None,
                "licence": "per depositor; see docs/data-sources.md",
            }
        )
    return rows
```

**Both sources must emit one key set per table.** `write_parquet` hands the
rows to DuckDB's `read_json_auto`, which infers the schema from a sample — a
column present in only some rows types as NULL for all of them, silently. The
key sets here match `chembl.campaign_screens` in Task 8 exactly; Task 8's last
test asserts that, so the two cannot drift.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_pubchem.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add atlas/sources/pubchem.py tests/test_pubchem.py tests/fixtures/pubchem_aid_summary.json
git commit -m "feat: PubChem campaigns, where zero actives can mean no call was made"
```

---

### Task 7: PubChem results and the declared ladder

The per-compound outcomes, and the project links that are the funnel as the depositor declared it.

**Files:**
- Modify: `atlas/sources/pubchem.py`
- Create: `tests/fixtures/pubchem_aid_results.csv`, `tests/fixtures/pubchem_aid_unspecified.csv`, `tests/fixtures/pubchem_projects.json`
- Test: `tests/test_pubchem.py`

**Interfaces:**
- Produces: `fetch_results(aid, *, force=False) -> Fetched`, `normalize_results(path, aid, chembl_by_cid) -> Iterator[dict]`, `fetch_project(aid, *, force=False) -> list[str]`, `group_projects(members) -> dict[str, str]`.
- `normalize_results` row shape: `{"stage_id", "screen_id", "pubchem_cid", "pubchem_sid", "molecule_chembl_id", "outcome", "endpoint", "standard_value", "standard_units", "standard_relation", "target_accession"}`.

- [ ] **Step 1: Write the fixtures**

`tests/fixtures/pubchem_aid_results.csv` — the real shape: three metadata rows after the header, which must not become results.

```csv
PUBCHEM_RESULT_TAG,PUBCHEM_SID,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,PUBCHEM_ACTIVITY_SCORE,Standard Type,Standard Relation,Standard Value,Standard Units,Target Accession
RESULT_TYPE,,,,,STRING,STRING,FLOAT,STRING,
RESULT_DESCR,,,,,Standardized activity type,Qualifier,Standardized value,Unit,
RESULT_UNIT,,,,,,,,,
1,513138063,4,Inactive,0,,,,,P9WHW5
2,513138071,5,Active,62,IC50,=,1.2,uM,P9WHW5
3,513138109,6,Inconclusive,20,,,,,P9WHW5
4,513138200,,Active,55,IC50,>,50,uM,P9WHW5
```

`tests/fixtures/pubchem_aid_unspecified.csv` — a re-deposit with no call:

```csv
PUBCHEM_RESULT_TAG,PUBCHEM_SID,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Standard Type,Standard Relation,Standard Value,Standard Units,Target Accession
RESULT_TYPE,,,,STRING,STRING,FLOAT,STRING,
1,100,1001,Unspecified,Percent Effect,=,4.2,%,P9WFT3
2,101,1002,Unspecified,Percent Effect,=,-1.1,%,P9WFT3
```

`tests/fixtures/pubchem_projects.json` — one declared project and one campaign with none:

```json
{
  "449775": {"linksets": [{"linksetdbs": [{"links": ["449762", "449764", "504335", "449775"]}]}]},
  "1626": {"linksets": [{"dbfrom": "pcassay", "ids": ["1626"]}]}
}
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_pubchem.py`:

```python
def test_results_skip_the_metadata_rows_and_keep_every_outcome():
    rows = list(
        pubchem.normalize_results(FIXTURES / "pubchem_aid_results.csv", "1626", {"5": "CHEMBL25"})
    )
    assert len(rows) == 4
    assert [row["outcome"] for row in rows] == ["inactive", "active", "inconclusive", "active"]
    assert rows[0]["stage_id"] == "pubchem:1626"
    assert rows[0]["screen_id"] == "pubchem:1626"


def test_an_unspecified_outcome_is_null_and_keeps_its_value():
    """No threshold was deposited, so there is no call -- but the number is real."""
    rows = list(pubchem.normalize_results(FIXTURES / "pubchem_aid_unspecified.csv", "1671170", {}))
    assert [row["outcome"] for row in rows] == [None, None]
    assert rows[0]["endpoint"] == "Percent Effect"
    assert rows[0]["standard_value"] == 4.2


def test_a_cid_with_no_unichem_mapping_is_still_a_result():
    rows = list(
        pubchem.normalize_results(FIXTURES / "pubchem_aid_results.csv", "1626", {"5": "CHEMBL25"})
    )
    assert rows[1]["molecule_chembl_id"] == "CHEMBL25"
    # Unmapped, and the row survives: the compound was tested either way.
    assert rows[0]["molecule_chembl_id"] is None
    assert rows[0]["pubchem_cid"] == "4"
    # A row with no CID at all still has its SID.
    assert rows[3]["pubchem_cid"] is None
    assert rows[3]["pubchem_sid"] == "513138200"


def test_results_carry_the_target_accession_pubchem_states():
    """It drops straight into the crosswalk -- no gene-name matching."""
    rows = list(pubchem.normalize_results(FIXTURES / "pubchem_aid_results.csv", "1626", {}))
    assert {row["target_accession"] for row in rows} == {"P9WHW5"}


def test_a_declared_project_groups_its_members_and_an_undeclared_one_stands_alone():
    links = json.loads((FIXTURES / "pubchem_projects.json").read_text())
    grouped = pubchem.group_projects({"449762": links["449775"], "1626": links["1626"]})
    # Every member of the project points at one campaign.
    assert grouped["449762"] == "pubchem:project:449762"
    # MLSCN-era, no siblings: the campaign is the AID, and that is not the
    # same claim as "this screen had no follow-up".
    assert grouped["1626"] == "pubchem:1626"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_pubchem.py -k "results or project" -v`
Expected: FAIL with `AttributeError: module 'atlas.sources.pubchem' has no attribute 'normalize_results'`

- [ ] **Step 4: Implement**

Append to `atlas/sources/pubchem.py`. Add `import csv` and `from pathlib import Path` and `from ..fetch import Fetched, fetch` to the imports:

```python
# --- the per-compound results ------------------------------------------------
#
# Not PUG-REST, which refuses above 10,000 SIDs with
# "PUGREST.BadRequest: Too many SIDs". This route is uncapped: AID 1626
# returns all 215,397 rows as a 30 MB CSV.
RESULTS = (
    "https://pubchem.ncbi.nlm.nih.gov/assay/pcget.cgi"
    "?query=download&record_type=datatable&actvty=all&response_type=save&aid="
)
# The depositor's own call. `Unspecified` is not a fourth outcome -- it is the
# absence of one, and it must not become "inactive".
OUTCOMES = {"active": "active", "inactive": "inactive", "inconclusive": "inconclusive"}


def fetch_results(aid: str, *, force: bool = False) -> Fetched:
    return fetch(
        f"{RESULTS}{aid}",
        f"results/{aid}.csv",
        source=SOURCE,
        min_interval=PACE,
        force=force,
        timeout=600.0,
    )


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def normalize_results(
    path: Path, aid: str, chembl_by_cid: Mapping[str, str]
) -> Iterable[dict[str, Any]]:
    """One row per tested compound.

    The three rows after the header are PubChem's column metadata
    (`RESULT_TYPE`, `RESULT_DESCR`, `RESULT_UNIT`); only a numeric
    `PUBCHEM_RESULT_TAG` is a result.
    """
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            tag = (row.get("PUBCHEM_RESULT_TAG") or "").strip()
            if not tag.isdigit():
                continue
            cid = (row.get("PUBCHEM_CID") or "").strip() or None
            outcome = (row.get("PUBCHEM_ACTIVITY_OUTCOME") or "").strip().lower()
            yield {
                "stage_id": f"pubchem:{aid}",
                "screen_id": f"pubchem:{aid}",
                "pubchem_cid": cid,
                "pubchem_sid": (row.get("PUBCHEM_SID") or "").strip() or None,
                "molecule_chembl_id": chembl_by_cid.get(cid) if cid else None,
                "outcome": OUTCOMES.get(outcome),
                "endpoint": (row.get("Standard Type") or "").strip() or None,
                "standard_value": _number(row.get("Standard Value")),
                "standard_units": (row.get("Standard Units") or "").strip() or None,
                "standard_relation": (row.get("Standard Relation") or "").strip() or None,
                "target_accession": (row.get("Target Accession") or "").strip() or None,
            }


# --- the declared ladder -----------------------------------------------------
#
# PubChem's project links are the funnel as the depositor stated it: AID
# 449775 groups 39 members including the primary (327,669 tested), the
# confirmatory dose-response (2,262) and a Vero cytotoxicity counter-screen.
# 10 of the 20 largest Mtb campaigns declare one; the other 10 -- including
# TAACF 1626 and 1949 -- declare nothing, and that is not the same statement
# as having had no follow-up.
PROJECT_LINK = (
    f"{EUTILS}/elink.fcgi?dbfrom=pcassay&db=pcassay"
    "&linkname=pcassay_pcassay_same_assay_project_list&retmode=json&id="
)


def fetch_project(aid: str, *, force: bool = False) -> dict[str, Any]:
    page = fetch(
        f"{PROJECT_LINK}{aid}",
        f"projects/{aid}.json",
        source=SOURCE,
        min_interval=PACE,
        force=force,
        json_body=True,
    )
    return json.loads(page.text)


def _members(payload: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for linkset in payload.get("linksets") or []:
        for db in linkset.get("linksetdbs") or []:
            out += [str(link) for link in db.get("links") or []]
    return sorted(set(out))


def group_projects(payloads: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """AID -> the campaign it belongs to.

    A declared project becomes one campaign named for its lowest member AID,
    so every member resolves to the same id whichever one was asked. An AID
    with no declared siblings is its own campaign.
    """
    grouped: dict[str, str] = {}
    for aid, payload in payloads.items():
        members = _members(payload)
        if len(members) > 1:
            grouped[aid] = f"pubchem:project:{min(members, key=int)}"
        else:
            grouped[aid] = f"pubchem:{aid}"
    return grouped
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_pubchem.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add atlas/sources/pubchem.py tests/test_pubchem.py tests/fixtures/pubchem_aid_results.csv tests/fixtures/pubchem_aid_unspecified.csv tests/fixtures/pubchem_projects.json
git commit -m "feat: PubChem's per-compound outcomes, and the ladder it declares"
```

---

### Task 8: The three tables

Both sources write into one shape. This is where the campaign, its stages and its results become store files.

**Files:**
- Modify: `atlas/sources/pubchem.py`, `atlas/sources/chembl.py`
- Modify: `atlas/pipeline.py`, `atlas/storediff.py`
- Test: `tests/test_screens.py`

**Interfaces:**
- Consumes: everything from Tasks 3–7.
- Produces: `pubchem.build(*, retrieved_at, force=False) -> list[Path]` writing `screens`, `screen_stages`, `screen_results`; `chembl.build_campaigns(activities, *, retrieved_at, force=False) -> list[dict]` returning rows for the same three tables so one writer stamps them; `chembl.campaign_screens(assays, activities, documents) -> list[dict]`.
- Table keys: `screens` on `screen_id`; `screen_stages` on `stage_id`; `screen_results` on `(stage_id, pubchem_cid, molecule_chembl_id)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_screens.py`:

```python
def test_a_campaign_row_counts_its_stages_and_states_where_they_came_from():
    from atlas.sources.chembl import campaign_screens

    assays, targets = _campaign()
    stages = normalize_campaign_assays(assays, targets)
    activities = [
        {"assay_chembl_id": "CHEMBL100", "molecule_chembl_id": "M1"},
        {"assay_chembl_id": "CHEMBL100", "molecule_chembl_id": "M2"},
        {"assay_chembl_id": "CHEMBL102", "molecule_chembl_id": "M1"},
    ]
    documents = {"CHEMBL_DOC1": {"year": 2019, "title": "A paper", "doc_type": "PUBLICATION"}}
    rows = campaign_screens(stages, activities, documents)
    assert len(rows) == 1
    screen = rows[0]
    assert screen["screen_id"] == "chembl:CHEMBL_DOC1"
    assert screen["deposit_kind"] == "publication"
    assert screen["n_tested"] == 2
    # ChEMBL states no activity call anywhere, so there is none to report.
    assert screen["outcome_stated"] is False
    assert screen["n_active"] is None
    # Classified from the depositor's prose, and the table says so.
    assert screen["stages_source"] == "from_prose"
    assert screen["project_declared"] is False


def test_the_modalities_a_campaign_reached_are_listed_not_scored():
    from atlas.sources.chembl import campaign_screens

    assays, targets = _campaign()
    stages = normalize_campaign_assays(assays, targets)
    documents = {"CHEMBL_DOC1": {"year": 2019, "title": "A paper", "doc_type": "PUBLICATION"}}
    screen = campaign_screens(stages, [], documents)[0]
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


def test_both_sources_emit_one_key_set_per_table():
    """DuckDB infers the schema from a sample of the rows.

    A column present in only some rows types as NULL for all of them and no
    error is raised, so a key set that drifts between the two ingesters loses
    a column quietly. This is the test that stops that.
    """
    import json as _json

    from atlas.sources import pubchem
    from atlas.sources.chembl import campaign_results, campaign_screens

    assays, targets = _campaign()
    stages = normalize_campaign_assays(assays, targets)
    documents = {"CHEMBL_DOC1": {"year": 2019, "title": "A paper", "doc_type": "PUBLICATION"}}
    activities = [{"assay_chembl_id": "CHEMBL100", "molecule_chembl_id": "M1"}]

    summaries = _json.loads((FIXTURES / "pubchem_aid_summary.json").read_text())
    summaries = summaries["AssaySummaries"]["AssaySummary"]

    assert set(campaign_screens(stages, activities, documents)[0]) == set(
        pubchem.normalize_screens(summaries)[0]
    )
    pubchem_results = list(
        pubchem.normalize_results(FIXTURES / "pubchem_aid_results.csv", "1626", {})
    )
    assert set(campaign_results(stages, activities)[0]) == set(pubchem_results[0])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_screens.py -k campaign_row -v`
Expected: FAIL with `ImportError: cannot import name 'campaign_screens'`

- [ ] **Step 3: Implement the ChEMBL campaign roll-up**

In `atlas/sources/chembl.py`, after `normalize_campaign_assays`:

```python
def campaign_screens(
    stages: Sequence[Mapping[str, Any]],
    activities: Iterable[Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """One campaign row per document.

    `outcome_stated` is false for every ChEMBL campaign: ChEMBL stores values,
    not activity calls, so `n_active` is NULL rather than 0 here. The counts
    that exist are of compounds tested, which is a count of rows and not a
    claim about what worked.
    """
    tested: dict[str, set[str]] = {}
    stage_screen = {stage["stage_id"]: stage["screen_id"] for stage in stages}
    for row in activities:
        stage_id = f"chembl:{row.get('assay_chembl_id')}"
        screen_id = stage_screen.get(stage_id)
        if screen_id and row.get("molecule_chembl_id"):
            tested.setdefault(screen_id, set()).add(row["molecule_chembl_id"])

    by_screen: dict[str, list[Mapping[str, Any]]] = {}
    for stage in stages:
        by_screen.setdefault(stage["screen_id"], []).append(stage)

    rows = []
    for screen_id, members in sorted(by_screen.items()):
        document_id = members[0]["document_chembl_id"]
        document = documents.get(document_id, {})
        kind = (document.get("doc_type") or "PUBLICATION").lower()
        rows.append(
            {
                "screen_id": screen_id,
                "aid": None,
                "title": document.get("title"),
                "depositor": "Scientific Literature",
                "deposit_kind": kind,
                "library_name": None,
                "library_size_stated": None,
                "year": document.get("year"),
                "n_stages": len(members),
                "n_tested": len(tested.get(screen_id, ())),
                "n_active": None,
                "n_inactive": None,
                "n_inconclusive": None,
                "outcome_stated": False,
                "stages_source": "from_prose",
                "project_declared": False,
                "modalities": sorted({stage["modality"] for stage in members}),
                "document_chembl_id": document_id,
                "pubmed_id": document.get("pubmed_id"),
                "licence": "CC BY-SA 3.0",
            }
        )
    return rows
```

`campaign_screens` needs the documents' metadata. **`campaign_document_meta` already
exists** — Task 4 moved it forward, because the publications-only filter needs
`doc_type` before any activity is fetched. Do not define it again; its signature
is `campaign_document_meta(documents: Sequence[str]) -> dict[str, dict[str, Any]]`
with **no `force` parameter**, returning `doc_type`, `title`, `year` and
`pubmed_id` per document.

Task 4 also added `campaign_publications(documents, meta)`, which keeps only the
`PUBLICATION` documents and **raises** on a candidate with no document record
rather than silently treating it as a non-paper — `fetch_json_many` skips failed
batches, so a missing record means a lost fetch, not a dataset.

And the per-stage counts, which `normalize_campaign_assays` left as None
because it had not seen the activities yet:

```python
def stamp_stage_counts(
    stages: Sequence[dict[str, Any]], activities: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Fill each stage's `n_tested`. `n_active` stays None: ChEMBL states no calls."""
    tested: dict[str, set[str]] = {}
    for row in activities:
        if row.get("molecule_chembl_id"):
            stage_id = f"chembl:{row.get('assay_chembl_id')}"
            tested.setdefault(stage_id, set()).add(row["molecule_chembl_id"])
    for stage in stages:
        stage["n_tested"] = len(tested.get(stage["stage_id"], ()))
    return stages
```

And the results rows, so ChEMBL's per-compound coverage lands in the same table:

```python
def campaign_results(
    stages: Sequence[Mapping[str, Any]], activities: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """One row per compound per stage. ChEMBL states no outcome, so it is NULL."""
    stage_screen = {stage["stage_id"]: stage["screen_id"] for stage in stages}
    rows = []
    for row in activities:
        stage_id = f"chembl:{row.get('assay_chembl_id')}"
        screen_id = stage_screen.get(stage_id)
        if not screen_id or not row.get("molecule_chembl_id"):
            continue
        rows.append(
            {
                "stage_id": stage_id,
                "screen_id": screen_id,
                "pubchem_cid": None,
                "pubchem_sid": None,
                "molecule_chembl_id": row["molecule_chembl_id"],
                "outcome": None,
                "endpoint": row.get("standard_type"),
                "standard_value": row.get("standard_value"),
                "standard_units": row.get("standard_units"),
                "standard_relation": row.get("standard_relation"),
                "target_accession": None,
            }
        )
    return rows
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_screens.py -v`
Expected: all pass.

- [ ] **Step 5: Write the build that joins both sources**

Add to `atlas/sources/pubchem.py` — it owns the write because it is the source with the outcomes, and the ChEMBL rows are handed to it:

```python
# The campaigns worth their download. The floor is deliberate and stated in
# docs/data-sources.md: the 172 non-ChEMBL taxonomy-tagged AIDs include
# BindingDB re-postings of PDB affinities, which are not screens.
MIN_TESTED = 10_000


def build(
    *,
    retrieved_at: str,
    extra_screens: Sequence[Mapping[str, Any]] = (),
    extra_stages: Sequence[Mapping[str, Any]] = (),
    extra_results: Sequence[Mapping[str, Any]] = (),
    chembl_by_cid: Mapping[str, str] | None = None,
    force: bool = False,
) -> list[Path]:
    """The screens tables, from PubChem plus whatever ChEMBL handed over."""
    aids = fetch_aids(force=force)
    summaries = fetch_summaries(aids, force=force)
    screens = [s for s in normalize_screens(summaries) if s["n_tested"] >= MIN_TESTED]
    projects = {s["aid"]: fetch_project(s["aid"], force=force) for s in screens}
    campaign_of = group_projects(projects)

    stages = []
    results = []
    for screen in screens:
        aid = screen["aid"]
        screen["screen_id"] = campaign_of[aid]
        screen["project_declared"] = campaign_of[aid].startswith("pubchem:project:")
        stages.append(
            {
                "stage_id": f"pubchem:{aid}",
                "screen_id": campaign_of[aid],
                "assay_chembl_id": None,
                "document_chembl_id": None,
                # No modality: a PubChem campaign title names no measurement, so
                # `classify_stage` reads what it can from the title alone.
                "stage": classify_stage(screen["title"]),
                # Left NULL deliberately: the stage rows PubChem gives are
                # campaign-level, and inventing a modality from a title would be
                # a label this pipeline made up rather than one it read.
                "modality": None,
                "description": screen["title"],
                "target_chembl_id": None,
                "target_type": None,
                "target_organism": None,
                "derived": False,
                "assay_condition": None,
                "strain": None,
                "n_tested": screen["n_tested"],
                "n_active": screen["n_active"],
            }
        )
        results += list(
            normalize_results(fetch_results(aid, force=force).path, aid, chembl_by_cid or {})
        )

    # The same statement the probe in `freshness.py` reads, so the comparison
    # is like with like: tagged AIDs, not the subset this build ingested.
    version = f"E-utilities {SEARCH_TERM}, {len(aids)} AIDs"
    return [
        write_parquet(
            "screens",
            list(extra_screens) + screens,
            source=SOURCE,
            source_version=version,
            retrieved_at=retrieved_at,
        ),
        write_parquet(
            "screen_stages",
            list(extra_stages) + stages,
            source=SOURCE,
            source_version=version,
            retrieved_at=retrieved_at,
        ),
        write_parquet(
            "screen_results",
            list(extra_results) + results,
            source=SOURCE,
            source_version=version,
            retrieved_at=retrieved_at,
        ),
    ]
```

Add `from pathlib import Path`, `from ..store import write_parquet` and
`from .chembl import classify_stage` to the imports.

The `version` line replaces the one in Step 10's probe discussion — it is
already written above, so do not change it again there.

- [ ] **Step 6: Wire it into the pipeline**

In `atlas/pipeline.py`, add `pubchem` and `unichem` to the `from .sources import (...)` block, and add this to `build_evidence` immediately before the `precedent` line:

```python
    _say("[evidence] compound bridge (UniChem ChEMBL <-> PubChem)")
    bridge = unichem.chembl_by_cid(unichem.fetch_raw(force=force).path)
    _say("[evidence] screening campaigns (ChEMBL documents)")
    whole_cell = [
        {"assay_chembl_id": a, "evidence": e, "document_chembl_id": d}
        for a, e, d in read("activities")
        .project("assay_chembl_id, evidence, document_chembl_id")
        .fetchall()
    ]
    # Publications only, and the filter has to come before any activity fetch:
    # CHEMBL3988442 is a DATASET with 1,413,047 activity rows, which one batch of
    # ten would page over ~1,414 times. Deposited datasets reach the store
    # through PubChem instead -- that deposit is AIDs 1671154-1671185.
    candidates = chembl.campaign_documents(whole_cell)
    meta = chembl.campaign_document_meta(candidates)
    documents = chembl.campaign_publications(candidates, meta)
    campaign_assays = chembl.campaign_assays(documents, force=force)
    campaign_targets = chembl.campaign_targets(campaign_assays)
    campaign_acts = chembl.campaign_activities(documents, force=force)
    campaign_stages = chembl.stamp_stage_counts(
        chembl.normalize_campaign_assays(campaign_assays, campaign_targets), campaign_acts
    )
    _say(
        f"[evidence] screens: {len(documents)} ChEMBL campaigns "
        f"({len(candidates) - len(documents)} deposits left to PubChem), "
        f"{len(campaign_stages)} stages"
    )
    paths += pubchem.build(
        retrieved_at=retrieved_at,
        extra_screens=chembl.campaign_screens(campaign_stages, campaign_acts, meta),
        extra_stages=campaign_stages,
        extra_results=chembl.campaign_results(campaign_stages, campaign_acts),
        chembl_by_cid=bridge,
        force=force,
    )
```

- [ ] **Step 7: Add the diff keys**

In `atlas/storediff.py`, add to `KEYS`:

```python
    "screens": ("screen_id",),
    "screen_stages": ("stage_id",),
    # A compound is identified by whichever id its source gave; both are in
    # the key because a PubChem row with no UniChem mapping is still a row.
    "screen_results": ("stage_id", "pubchem_cid", "molecule_chembl_id"),
```

- [ ] **Step 8: Run the suite and lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add atlas/sources/pubchem.py atlas/sources/chembl.py atlas/pipeline.py atlas/storediff.py tests/test_screens.py
git commit -m "feat: screens, their stages and every compound tested in them"
```

---

### Task 9: The roll-up

Per-gene screen columns on `target_summary`, with the complex rule and `shared_accession` both respected.

**Files:**
- Modify: `atlas/summary.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_summary.py`

**Interfaces:**
- Consumes: `screens`, `screen_stages`, `screen_results`, `crosswalk`.
- Produces: `target_summary` columns `n_target_screens`, `max_screen_compounds`, `n_screen_actives`, `n_complex_screens`, `latest_screen_year`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_summary.py`:

```python
def test_a_gene_reached_by_a_biochemical_stage_counts_the_screen(summary_store):
    rows = _rows(summary_store, "SELECT * FROM target_summary WHERE rv_id = 'Rv3800c'")
    assert rows[0]["n_target_screens"] == 1
    assert rows[0]["max_screen_compounds"] == 4


def test_a_complex_stage_is_counted_apart_from_the_genes_own_screens(summary_store):
    rows = _rows(
        summary_store,
        "SELECT * FROM target_summary WHERE rv_id IN ('Rv2460c','Rv2461c') ORDER BY rv_id",
    )
    for row in rows:
        assert row["n_target_screens"] == 0
        assert row["n_complex_screens"] == 1


def test_actives_are_null_where_no_source_stated_a_call(summary_store):
    """A percent-effect screen with no cutoff has no actives to report, and 0
    would read as a screen that found nothing."""
    rows = _rows(summary_store, "SELECT * FROM target_summary WHERE rv_id = 'Rv3800c'")
    assert rows[0]["n_screen_actives"] is None


def test_a_gene_never_screened_reads_zero_screens_not_null(summary_store):
    """Most of the 4,031 genes. Zero is the answer, and it must be sayable."""
    rows = _rows(summary_store, "SELECT * FROM target_summary WHERE rv_id = 'Rv3790'")
    assert rows[0]["n_target_screens"] == 0
    assert rows[0]["n_complex_screens"] == 0
```

- [ ] **Step 2: Extend the fixture store**

In `tests/conftest.py`'s `summary_store` fixture, add the three tables. One biochemical stage on Pks13's target with four tested compounds and no stated outcome, and one complex stage on ClpP1P2's:

```python
    write_parquet(
        "screens",
        [
            {
                "screen_id": "chembl:CHEMBL_DOC1",
                "aid": None,
                "title": "A paper",
                "depositor": "Scientific Literature",
                "deposit_kind": "publication",
                "library_name": None,
                "library_size_stated": None,
                "year": 2021,
                "n_stages": 2,
                "n_tested": 4,
                "n_active": None,
                "n_inactive": None,
                "n_inconclusive": None,
                "outcome_stated": False,
                "stages_source": "from_prose",
                "project_declared": False,
                "modalities": ["biochemical_mtb"],
                "document_chembl_id": "CHEMBL_DOC1",
                "pubmed_id": None,
                "licence": "CC BY-SA 3.0",
            }
        ],
        source="chembl",
        source_version="chembl_37 (01/05/2026)",
        retrieved_at="2026-10-09",
        store=out,
    )
    write_parquet(
        "screen_stages",
        [
            {
                "stage_id": "chembl:CHEMBL101",
                "screen_id": "chembl:CHEMBL_DOC1",
                "assay_chembl_id": "CHEMBL101",
                "document_chembl_id": "CHEMBL_DOC1",
                "stage": "primary",
                "modality": "biochemical_mtb",
                "description": "Inhibition of Mycobacterium tuberculosis Pks13",
                "target_chembl_id": "CHEMBL4105939",
                "target_type": "SINGLE PROTEIN",
                "target_organism": "Mycobacterium tuberculosis",
                "derived": False,
                "assay_condition": None,
                "strain": None,
                "n_tested": 4,
                "n_active": None,
            },
            {
                "stage_id": "chembl:CHEMBL4649972",
                "screen_id": "chembl:CHEMBL_DOC1",
                "assay_chembl_id": "CHEMBL4649972",
                "document_chembl_id": "CHEMBL_DOC1",
                "stage": "primary",
                "modality": "biochemical_mtb",
                "description": "in vitro assay for ClpP1P2",
                "target_chembl_id": "CHEMBL4662931",
                "target_type": "PROTEIN COMPLEX",
                "target_organism": "Mycobacterium tuberculosis",
                "derived": False,
                "assay_condition": None,
                "strain": None,
                "n_tested": 3,
                "n_active": None,
            },
        ],
        source="chembl",
        source_version="chembl_37 (01/05/2026)",
        retrieved_at="2026-10-09",
        store=out,
    )
```

`screen_results` is not needed by the roll-up, so it is not in the fixture; Task 8's tests cover it.

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_summary.py -k screen -v`
Expected: FAIL — the columns do not exist.

- [ ] **Step 4: Implement**

In `atlas/summary.py`, add to `TABLES`:

```python
    "screens": "screens",
    "screen_stages": "screen_stages",
```

and to `EMPTY_OPTIONAL`:

```python
    "screens": "SELECT NULL::VARCHAR AS screen_id, NULL::VARCHAR AS depositor,"
    " NULL::BIGINT AS year, NULL::BOOLEAN AS outcome_stated WHERE false",
    "screen_stages": "SELECT NULL::VARCHAR AS stage_id, NULL::VARCHAR AS screen_id,"
    " NULL::VARCHAR AS target_chembl_id, NULL::VARCHAR AS target_type,"
    " NULL::VARCHAR AS modality, NULL::BIGINT AS n_tested, NULL::BIGINT AS n_active"
    " WHERE false",
```

Add a CTE beside `assay_scale`:

```sql
screen_scale AS (
    -- A campaign reaches a gene only through a stage run on that gene's own
    -- protein. SINGLE PROTEIN only, the same rule as assay_scale: a screen of
    -- ClpP1P2 is not a screen of clpP1. `n_screen_actives` is NULL unless a
    -- source stated calls -- 0 would read as a screen that found nothing,
    -- which is what PubChem's own summary endpoint says for a deposit with no
    -- cutoff.
    SELECT gt.rv_id,
           count(DISTINCT st.screen_id)
               FILTER (WHERE st.target_type = 'SINGLE PROTEIN') AS n_target_screens,
           max(st.n_tested)
               FILTER (WHERE st.target_type = 'SINGLE PROTEIN') AS max_screen_compounds,
           sum(st.n_active)
               FILTER (WHERE st.target_type = 'SINGLE PROTEIN') AS n_screen_actives,
           count(DISTINCT st.screen_id)
               FILTER (WHERE st.target_type <> 'SINGLE PROTEIN') AS n_complex_screens,
           max(sc.year) AS latest_screen_year
    FROM gene_target gt
    JOIN screen_stages st ON st.target_chembl_id = gt.target_id
    LEFT JOIN screens sc ON sc.screen_id = st.screen_id
    WHERE gt.evidence = 'direct'
    GROUP BY 1
),
```

In the final `SELECT`, after the assay columns:

```sql
    coalesce(ss.n_target_screens, 0)  AS n_target_screens,
    coalesce(ss.n_complex_screens, 0) AS n_complex_screens,
    ss.max_screen_compounds           AS max_screen_compounds,
    -- NOT coalesced: see screen_scale.
    ss.n_screen_actives               AS n_screen_actives,
    ss.latest_screen_year             AS latest_screen_year,
```

and add `LEFT JOIN screen_scale ss ON ss.rv_id = g.rv_id` beside the other joins.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_summary.py -v && uv run pytest -q`
Expected: all pass. `test_a_gene_reached_by_a_biochemical_stage_counts_the_screen` expects `max_screen_compounds == 4`; if it reads 3, the `SINGLE PROTEIN` filter is missing from the `max` and the complex stage is winning.

- [ ] **Step 6: Commit**

```bash
git add atlas/summary.py tests/conftest.py tests/test_summary.py
git commit -m "feat: per-gene screen counts, with the complex rule carried over"
```

---

### Task 10: The agent's schema, the freshness probe, and the partial-store guard

Three small surfaces that each break silently if missed. The agent is the only place a wrong join gives no error.

**Files:**
- Modify: `atlas/agent.py`, `atlas/freshness.py`
- Test: `tests/test_agent.py`, `tests/test_upkeep.py`, `tests/test_partial_store.py`

**Interfaces:**
- Consumes: the three tables from Task 8.
- Produces: `agent.TABLES` and `agent.TABLE_NOTES` entries; `freshness.SOURCES` entries for `pubchem` and `unichem`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent.py`:

```python
def test_the_schema_warns_about_every_screens_trap():
    """A model that writes a plausible wrong join here gets silent nonsense."""
    from atlas.agent import TABLE_NOTES

    for table in ("screens", "screen_stages", "screen_results"):
        assert table in TABLE_NOTES
    notes = " ".join(TABLE_NOTES[t] for t in ("screens", "screen_stages", "screen_results"))
    # The four joins and readings that go wrong silently.
    assert "stage_id" in notes
    assert "outcome_stated" in notes
    assert "n_tested" in notes and "library_size_stated" in notes
    assert "SINGLE PROTEIN" in notes
```

Add to `tests/test_upkeep.py`:

```python
def test_pubchem_and_unichem_are_checkable():
    from atlas.freshness import BY_NAME, stages_from

    assert "pubchem" in BY_NAME
    assert "unichem" in BY_NAME
    # Both feed the evidence stage, so a refresh runs evidence then the roll-up.
    assert stages_from("pubchem")[0] == "evidence"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_agent.py -k screens_trap tests/test_upkeep.py -k checkable -v`
Expected: FAIL with `KeyError: 'screens'` and `AssertionError`.

- [ ] **Step 3: Add the schema notes**

In `atlas/agent.py`, add the three names to `TABLES` after `"ligands"`, and these to `TABLE_NOTES`:

```python
    "screens": "One row per screening CAMPAIGN, keyed on screen_id "
    "(`pubchem:1626`, `pubchem:project:449762`, `chembl:CHEMBL_DOC`). "
    "**`n_active` is NULL, not 0, where the depositor stated no activity call** "
    "-- `outcome_stated` says which, and PubChem's own summary endpoint reports "
    "0 actives for a 65,366-compound deposit that simply has no cutoff. "
    "**`n_tested` is what was deposited; `library_size_stated` is the figure the "
    "depositor's prose names.** They differ, sometimes hugely (one AID states "
    "~300,000 screened and deposits 6,225), and they are never summed or "
    "substituted. `project_declared` false means PubChem groups no siblings for "
    "it, which is NOT the same as the campaign having had no follow-up. "
    "`depositor` matters legally: PubChem's licence is per depositor.",
    "screen_stages": "One row per assay within a campaign, keyed on stage_id. "
    "**Join screen_results on stage_id, never on screen_id** -- a campaign has "
    "many stages and joining at campaign level multiplies every result by the "
    "number of stages. `stage` is funnel position (primary, confirmatory, "
    "counter_screen, profiling) and `modality` is what was measured "
    "(phenotypic_mtb, biochemical_mtb, mammalian_cytotox, adme, "
    "in_vivo_efficacy, other_pathogen, other); they are different axes, so a "
    "primary screen can be either phenotypic or biochemical. "
    "**To reach a gene, join target_chembl_id through crosswalk.chembl_targets "
    "and keep only target_type = 'SINGLE PROTEIN'** -- the ClpP1P2 complex "
    "target maps to both clpP1 and clpP2, so counting complexes hands each "
    "subunit a 68,611-compound screen of the pair. `derived` true means the "
    "assay is a selectivity or therapeutic index ChEMBL computed from two other "
    "rows: a number, but not a measurement. `stages_source` says whether the "
    "stage was stated by the depositor or classified from their prose.",
    "screen_results": "One row per compound per stage, keyed on "
    "(stage_id, pubchem_cid, molecule_chembl_id) -- **the inactives are here**, "
    "which is what makes 'tested and did nothing' answerable. "
    "**`outcome` NULL is not inactive**: it means the source stated no call "
    "(every ChEMBL row, and every row of a deposit with no cutoff), so filter "
    "on outcome = 'inactive' to find non-hits and never on outcome IS NULL. "
    "A compound carries `pubchem_cid` or `molecule_chembl_id` or both; the "
    "bridge between them is UniChem and it is incomplete, so a NULL "
    "molecule_chembl_id means unmapped, not untested. `target_accession` is the "
    "UniProt accession PubChem states for the assay target and joins straight "
    "to crosswalk.uniprot_acc -- respecting shares_accession_with, since 55 "
    "loci share an accession.",
```

- [ ] **Step 4: Add the freshness probes**

In `atlas/freshness.py`, add two probes beside `_chembl`:

```python
def _pubchem() -> str:
    """How many AIDs PubChem tags M. tuberculosis, which is the search's answer.

    Cheap -- one E-utilities request with retmax=0 -- and it moves when a new
    campaign is deposited, which is the thing worth noticing.
    """
    response = _get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pcassay&term={pubchem.SEARCH_TERM}&retmax=0&retmode=json"
    )
    return f"E-utilities {pubchem.SEARCH_TERM}, {response.json()['esearchresult']['count']} AIDs"
```

and register both sources in `SOURCES`:

```python
(Source("pubchem", "screens", "evidence", _pubchem),)
# UniChem ships inside ChEMBL's distribution and moves with it, so the
# ChEMBL probe already says when to re-download the mapping.
(
    Source(
        "unichem",
        "screen_results",
        "evidence",
        frozen="published with ChEMBL; it moves when chembl does",
    ),
)
```

Add `from .sources import pubchem` to the imports.

The probe and the stamp must read the same statement, or `check` reports stale
forever — the trap `CLAUDE.md` already names for ChEMBL's two faithful release
strings. Task 8 already stamps `f"E-utilities {SEARCH_TERM}, {len(aids)} AIDs"`
from the AID search rather than from the ingested subset, which is why the
probe above is worded identically. Verify by eye that the two f-strings match
character for character, then:

```bash
uv run atlas check --only pubchem
```

Expected: `current`. If it reports stale on a store you just built, the two
strings differ.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_agent.py tests/test_upkeep.py tests/test_partial_store.py -v`
Expected: all pass. If `test_partial_store.py` fails, the `EMPTY_OPTIONAL` stand-ins from Tasks 2 and 9 are missing a column the roll-up references.

- [ ] **Step 6: Commit**

```bash
git add atlas/agent.py atlas/freshness.py atlas/sources/pubchem.py tests/test_agent.py tests/test_upkeep.py
git commit -m "feat: the agent's schema carries the screens traps, and check can ask PubChem"
```

---

### Task 11: Build it for real, and write down what it says

The first full build of the new tables, and the documentation that has to match it.

**Files:**
- Modify: `docs/data-sources.md`, `README.md`, `tests/fixtures/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Build**

Run:

```bash
uv run atlas evidence 2>&1 | tail -30
uv run atlas summary
du -sh data/store data/raw
```

Expected: `screens`, `screen_stages` and `screen_results` in `data/store`. The spec predicts `data/raw` near 900 MB and `data/store` near 100 MB. **Record what actually happens.**

- [ ] **Step 2: Read the real numbers**

```bash
uv run python -c "
import duckdb
q = lambda s: print(duckdb.sql(s))
q(\"SELECT count(*) AS screens, count(*) FILTER (WHERE outcome_stated) AS with_calls, sum(n_tested) AS tested FROM 'data/store/screens.parquet'\")
q(\"SELECT depositor, count(*) AS n, max(n_tested) AS biggest FROM 'data/store/screens.parquet' GROUP BY 1 ORDER BY biggest DESC LIMIT 12\")
q(\"SELECT modality, count(*) AS stages FROM 'data/store/screen_stages.parquet' GROUP BY 1 ORDER BY 2 DESC\")
q(\"SELECT coalesce(outcome, 'no call stated') AS outcome, count(*) FROM 'data/store/screen_results.parquet' GROUP BY 1 ORDER BY 2 DESC\")
q(\"SELECT count(DISTINCT coalesce(molecule_chembl_id, pubchem_cid)) AS compounds FROM 'data/store/screen_results.parquet'\")
q(\"SELECT count(*) FILTER (WHERE n_target_screens > 0) AS screened, count(*) FILTER (WHERE n_complex_screens > 0) AS complex_only, max(max_screen_compounds) AS biggest FROM 'data/store/target_summary.parquet'\")
"
```

- [ ] **Step 3: Write the source entries**

Add to the summary table at the top of `docs/data-sources.md`:

```markdown
| [PubChem BioAssay](#pubchem-bioassay) | E-utilities, live | **per depositor**; see below | Screening campaigns with their inactives |
| [UniChem](#unichem) | src1src22, with ChEMBL | CC BY-SA 3.0 | ChEMBL ↔ PubChem compound bridge |
```

and a full section, with the licence quoted rather than summarised:

```markdown
## PubChem BioAssay

The only public source that states an outcome per compound at screening scale.
AID 1626 deposits 209,843 `Inactive` rows beside 2,044 actives, which is what
makes "tested and did nothing" a provable answer rather than an absence.

Reproducible membership, `db=pcassay` via E-utilities, verified 2026-10-11:

| term | AIDs |
|---|---|
| `txid1773[ORGN]` | 12,519 |
| `txid1773[ORGN] NOT ChEMBL[SNME]` | 172 |
| `txid1773[ORGN] AND 10000:100000000[TSC]` | 28 |

A campaign is ingested when its own target record or title names Mtb and its
deposited set reaches 10,000 compounds. **The taxonomy tag alone over-counts**:
several AIDs above 300,000 compounds are tagged Mtb while the target is
*Bos taurus* MsrA, *S. aureus* NadD or *B. subtilis* Sfp. The 10,000 floor is
this atlas's choice and excludes BindingDB's re-postings of PDB affinities,
which are measurements rather than screens.

Per-AID data comes from
`pubchem.ncbi.nlm.nih.gov/assay/pcget.cgi?query=download&record_type=datatable&actvty=all&response_type=save&aid=N`,
which is uncapped — AID 1626 returns all 215,397 rows as 30 MB. **Not
PUG-REST**, which refuses above 10,000 SIDs with `PUGREST.BadRequest: Too many
SIDs`.

### Zero actives is not a finding

PubChem's summary endpoint reports `SIDCountActive: 0` for AID 1671170, a
65,366-compound TrpRS screen. Read literally that is a screen that found
nothing. The per-compound rows are 65,646 × `Unspecified`: the depositor never
stated a threshold. So `outcome_stated` is a stored column, `n_active` is NULL
wherever it is false, and `outcome` is NULL rather than `inactive` on every
such row.

### Licence

Per depositor, not per database. NCBI's policy puts US-government material in
the public domain and then explicitly carves PubChem out:

> resources which incorporate material contributed or licensed by individuals,
> companies, or organizations that may be protected by U.S. and foreign
> copyright laws. All persons reproducing, redistributing, or making commercial
> use of this information are expected to adhere to the terms and conditions
> asserted by the copyright holder.

— <https://www.ncbi.nlm.nih.gov/home/about/policies/>

So `screens.depositor` is recorded on every campaign and no blanket licence is
claimed. Nothing is redistributed: the pipeline fetches at build time and
`data/raw` is gitignored.

## UniChem

`ftp.ebi.ac.uk/pub/databases/chembl/UniChem/data/wholeSourceMapping/src_id1/src1src22.txt.gz`,
22.8 MB. One file maps every ChEMBL id to its PubChem CID, which is what lets
a 215,397-compound screen be reached from a compound page. The alternatives
were one request per compound against PubChem's synonym endpoint, or PubChem's
1.5 GB CID-Synonym dump.

**The bridge is incomplete, and a gap is recorded rather than patched.** A
PubChem result whose CID has no ChEMBL mapping is still a real result; it just
cannot be reached from a ChEMBL compound. Licence: part of ChEMBL's
distribution, CC BY-SA 3.0.
```

Also add a "Screens and hit profiling" subsection under the ChEMBL section recording that campaigns are documents, that a document query returns 38,335 assays where a target query returns 11,686, and the two classifier caveats (`stages_source = 'from_prose'`, `derived`).

- [ ] **Step 4: Update the fixture register**

Add to `tests/fixtures/README.md`:

```markdown
### Screens and hit profiling

- `chembl_assay_census.json` — three assays, one with a repeated measurement,
  so `n_compounds` and `n_measurements` differ. Proves assay size counts
  compounds.
- `chembl_campaign_assays.json` — one document carrying the whole ladder
  (MIC, protein, cytotox, ADME, animal), a non-Mtb organism, and a derived
  selectivity index. Proves each modality is kept apart and the index is
  flagged.
- `pubchem_aid_summary.json` — AID 1626 (real calls), AID 1671170 (`0` actives
  meaning no call), and an Mtb-tagged assay whose target is *Bos taurus*.
  Proves the outcome trap and the inclusion rule.
- `pubchem_aid_results.csv` — the three metadata rows PubChem puts after the
  header, plus one row with no CID. Proves metadata is not a result and an
  unmapped compound is still tested.
- `pubchem_aid_unspecified.csv` — a re-deposit with no cutoff. Proves
  `outcome` is NULL and the value survives.
- `pubchem_projects.json` — one declared project, one AID with no siblings.
  Proves a NULL project is not "no follow-up".
- `unichem_src1src22.txt` — two half-rows. Proves a half-row is not a mapping.
```

- [ ] **Step 5: Record the rules in CLAUDE.md**

Under "Evidence must stay honest", add:

```markdown
- **A screen has a denominator, and the denominator is what makes a zero
  provable.** `screen_results` holds the compounds that did nothing —
  209,843 `Inactive` rows for AID 1626 alone — so "tested and inactive" is a
  real answer. Three rules keep it honest. **An outcome call is recorded only
  where the source states one**: ChEMBL files values and no calls, and the
  Dundee/GHDDI deposit files 276,472 percent-effect rows with no cutoff, so
  `outcome` is NULL there and a threshold this pipeline picked would be this
  pipeline's finding. **`n_active = 0` is never written where no call was
  stated** — PubChem's own summary endpoint reports 0 actives for a
  65,366-compound screen that simply has no threshold, which reads as a screen
  that found nothing. **`n_tested` is the deposited set, not the screened
  library**; one AID states ~300,000 screened and deposits 6,225, so the prose
  figure lives in `library_size_stated` and the two are never summed.
- **A campaign reaches a gene through a stage on that gene's own protein, and
  nothing else.** `SINGLE PROTEIN` only, the rule `n_complex_drugs` already
  follows: the ClpP1P2 target maps to both `clpP1` and `clpP2`, so counting
  complexes hands each subunit a 68,611-compound screen of the pair. The 251
  documents that report both a protein assay and a whole-cell MIC have
  reported both — that is not target deconvolution, and calling it that would
  invent the resistant-mutant experiment nobody deposited.
- **Hit profiling is coverage, not a score.** 17,763 compounds have a tier
  beyond potency and 20,000 have a MIC and nothing else, which is the answer
  and not a low grade. No column is ranked, weighted or combined with another.
  A derived selectivity index is labelled `derived`: ChEMBL computes it from
  two other rows, so it is a number but not a measurement.
```

Under "Querying it", note that the nav is now the pipeline and that Screens and Hit profiling are views in their own right, pending the UI plan.

- [ ] **Step 6: Verify every number in the docs against the store**

Re-run Step 2 and check each figure you wrote appears in that output. Any number you cannot reproduce comes out of the prose.

- [ ] **Step 7: Run the full suite, lint, and diff**

Run:

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run atlas diff
```

Expected: tests and lint pass; `atlas diff` reports the three new tables as added.

- [ ] **Step 8: Commit**

```bash
git add docs/data-sources.md README.md tests/fixtures/README.md CLAUDE.md
git commit -m "docs: the screening record, its licences, and the zeros it can prove"
```

---

## Self-review notes

Checked against the spec:

- **Spec coverage.** M0 → Tasks 1–2. The campaign/stage/result model → Tasks 4, 7, 8. Two orthogonal axes → Task 3. Compound identity → Task 5. Traps 1, 2, 11 → Tasks 3, 6, 7. Traps 3, 4 → Tasks 6, 8. Trap 5 → Tasks 2, 9. Trap 7 → Task 7. Trap 8 → Task 6. Trap 9 → Tasks 3, 8. Roll-up → Task 9. Agent schema, probes → Task 10. Licences and docs → Task 11.
- **Not covered here, by design:** trap 6 (`shared_accession` on a stage's gene list) is recorded in the agent's note and enforced where the API joins, which is the next plan — the roll-up goes through `crosswalk.chembl_targets`, which already respects it. Trap 10 (unreplicated chemistry) is a UI statement. Trap 12 (anticancer is not a counter-screen) is satisfied by storing the assay's own target and description; no count depends on it.
- **Open question 1** (which AIDs beyond the 28) is answered by the `MIN_TESTED = 10_000` floor in Task 8, documented in Task 11 as this atlas's choice.
- **Open question 2** (whether `max_assay_compounds` retires) is deliberately left: Task 9 adds `max_screen_compounds` beside it. They measure the same thing from two tables, and the UI plan should retire one. Flagged rather than resolved because retiring a column the API serves belongs in the plan that changes the API.
