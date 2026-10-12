# Compound Structures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the screening layer's compounds structures. Build a `compound_structures` table from
ChEMBL's chemreps file and serve it through the API. In the same rebuild, drop two dead `screens`
columns and bound the `/ask` sandbox's memory.

**Architecture:** A new ingester, `atlas/sources/chemreps.py`, streams the gzip and keeps only ids
the store references. It writes a three-state table (`has_structure` is never NULL, and an id
that was never looked up has no row). The pipeline builds it in the evidence stage, after the
screening layer. The API swaps three SMILES reads from `compounds` to the new table. The agent
sandbox gets a `memory_limit` and a spill directory.

**Tech Stack:** Python 3.12, DuckDB 1.5.6, FastAPI, pytest, uv, ruff (line length 100).

**Spec:** `docs/superpowers/specs/2026-10-11-compound-structures-design.md`

## Global Constraints

- Public data only; the licence is ChEMBL's, CC BY-SA 3.0.
- `source = "chembl"`, `source_version = "chembl_37"` (the release name the file states).
- `has_structure` is never NULL. No row means the id was never looked up.
- `compounds` is not widened or changed.
- `web/src` is not touched. The API keeps the field name `smiles`.
- Tests read committed fixtures, never the network. Every new test is mutation-proved.
- Every number added to the docs is re-measured with DuckDB against the rebuilt store.
- Commits: conventional, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, no
  `Claude-Session:` trailer.

## Review Focus

1. A chemreps file whose first line is not the header must be refused, not read one row short.
2. An id appearing twice in the file must raise, not keep one silently.
3. A line whose SMILES is blank must not make `has_structure` true with a NULL SMILES.
4. A store built before this table existed must still answer the screens, `/hits` and compound
   routes. That needs an empty stand-in.
5. A model query in `/ask` that needs more memory than the limit must spill or fail as a tool
   error. It must never grow the process without bound, and it must not be able to raise the
   limit, because the configuration is locked.

---

### Task 1: The chemreps ingester

**Files:**
- Create: `atlas/sources/chemreps.py`
- Create: `tests/fixtures/chembl_chemreps.txt` (header plus six lines, uncompressed; `_lines`
  opens a `.gz` or a plain file, as `unichem._lines` does)
- Create: `tests/test_chemreps.py`

**Interfaces:**
- Produces:
  - `chemreps.SOURCE = "chembl"`
  - `chemreps.url(release: str) -> str`
  - `chemreps.release_name(mapping: Path) -> str`, which returns e.g. `"chembl_37"`
  - `chemreps.normalize(path: Path, wanted: Collection[str]) -> Iterator[dict]`
  - `chemreps.build(wanted: Collection[str], *, force: bool = False, store: Path | None = None) -> Path`

- [ ] **Step 1: Write the fixture.** Header
  `chembl_id\tcanonical_smiles\tstandard_inchi\tstandard_inchi_key`, then these lines:
  - `CHEMBL3330226` (macozinone), wanted;
  - `CHEMBL64`, wanted;
  - `CHEMBL1`, not wanted;
  - a three-field line;
  - `CHEMBL_BLANK` with an empty SMILES, wanted.
- [ ] **Step 2: Write the failing tests.**
  - Wanted and found gives `has_structure` true, with the SMILES and the key.
  - An unwanted id gives no row.
  - Wanted and absent gives `has_structure` false, with the SMILES and key NULL.
  - A blank SMILES gives false.
  - A malformed line is skipped.
  - A missing header raises.
  - A duplicate id raises.
  - `release_name` reads `chembl_37` from the mapping fixture, and raises on `unknown`.
  - `url("chembl_37")` gives the `releases/chembl_37/chembl_37_chemreps.txt.gz` path.
- [ ] **Step 3: Run** `uv run pytest tests/test_chemreps.py -q`. Expect a FAIL (no module).
- [ ] **Step 4: Implement** the module in `unichem.py`'s shape:
  - `_lines` checks the header.
  - `normalize` yields found rows, then the not-found wanted ids in sorted order, and raises on a
    duplicate id.
  - `build` reads the release from `chembl.fetch_raw().path`, fetches with `timeout=900.0`, and
    writes through `store.write_parquet` with `retrieved_at` taken from the fetch.
- [ ] **Step 5: Run the tests** and expect a PASS. Then mutation-prove each one: break the
  matching line, see it fail, restore it.
- [ ] **Step 6: Commit** `feat: compound structures from ChEMBL's chemreps file, three states`.

### Task 2: Wire it into the pipeline, the diff and the agent's schema

**Files:**
- Modify: `atlas/pipeline.py` (after `pubchem.build` in `build_evidence`)
- Modify: `atlas/storediff.py` (`KEYS`)
- Modify: `atlas/agent.py` (`TABLES`, `TABLE_NOTES`)
- Modify: `atlas/api.py` (`LICENCES`)
- Test: `tests/test_upkeep.py` already asserts that the agent's tables and the diff keys are the
  same set and that every table has a note. `tests/test_agent.py` gets a test that the note names
  its trap.

- [ ] **Step 1:** Write a failing test in `tests/test_agent.py`. `describe()`'s text for
  `compound_structures` must contain `never looked up` and `not in this release's structure file`.
- [ ] **Step 2:** Add the KEYS, TABLES, LICENCES and note entries.
  - The note names the join on `molecule_chembl_id`.
  - It names the three states, and says a NULL from a LEFT JOIN is "never looked up".
  - It says PubChem-only CIDs have no row.
  - It says a structure is a drawing input, not evidence.
  - It says `compounds.smiles` agrees with it for the potency set.
- [ ] **Step 3:** Pipeline:
  `wanted = distinct molecule_chembl_id from screen_results ∪ compounds`, then
  `paths.append(chemreps.build(wanted, force=force))`, with a `_say` line.
- [ ] **Step 4:** Run `uv run pytest -q` and expect a PASS. Mutation-prove the note test.
  Then commit.

### Task 3: Bound the /ask sandbox's memory

**Files:**
- Modify: `atlas/agent.py` (`connection()`, constants)
- Test: `tests/test_agent.py`

Measured on 2026-10-11 against the real store: an unbounded in-memory copy peaks at 1.98 GB with
`compound_structures` in, and `COMPRESS` saves only 0.1 GB. With `memory_limit='512MB'` and a
`temp_directory`, peak RSS is 0.82 GB, loading takes 1.1 s, four representative queries run in
under 0.1 s, and the lock still holds.

- [ ] **Step 1: Write the failing tests.**
  - `current_setting('memory_limit')` on `agent.connection()` reports the limit.
  - `SET memory_limit='100GB'` raises, because the configuration is locked.
  - `SET temp_directory` raises.
- [ ] **Step 2: Implement.**
  - Add `MEMORY_LIMIT = "512MB"` and `SPILL_LIMIT = "8GB"`.
  - Open the connection with `duckdb.connect(":memory:", config={"memory_limit": ...,
    "temp_directory": mkdtemp(prefix="atlas-agent-"), "max_temp_directory_size": ...})`.
  - Register an `atexit` that removes the directory.
  - Update the comment at `TABLES` with the new measurements.
- [ ] **Step 3: Run** the tests, mutation-prove them, and commit
  `fix: the agent's sandbox spills to disk at 512 MB instead of holding 2 GB`.

### Task 4: The API draws from compound_structures

**Files:**
- Modify: `atlas/api.py`:
  - `/screens/{id}/results`: the `smiles` column and `n_with_structure`;
  - `/hits`: the profile's `smiles` and `with_structure`;
  - `/compounds/{id}`: `smiles` on the record;
  - an empty stand-in in `_db()`.
- Test: `tests/test_api.py` (`screen_store` gets a `compound_structures` table)

- [ ] **Step 1:** Extend `screen_store` with a `compound_structures` write that has three rows:
  - macozinone `true`, with a SMILES that differs from `compounds` so the test can tell the
    source;
  - one profiled compound `false`;
  - nothing for a third.
- [ ] **Step 2: Write the failing tests.**
  - A results row's `smiles` comes from the new table.
  - `n_with_structure` counts `has_structure` rows.
  - `/hits` `with_structure` counts from the new table.
  - `/compounds/{id}` for a screen-only compound carries `smiles`.
  - The `client` fixture (no table) still answers `/hits` and the results route with
    `with_structure` 0.
- [ ] **Step 3: Implement.**
  - Join `LEFT JOIN compound_structures s USING (molecule_chembl_id)` and select
    `s.canonical_smiles AS smiles`.
  - Keep `c.pref_name` from `compounds`.
  - The stand-in is
    `SELECT NULL::VARCHAR AS molecule_chembl_id, NULL::BOOLEAN AS has_structure, NULL::VARCHAR AS canonical_smiles, NULL::VARCHAR AS standard_inchi_key WHERE false`.
- [ ] **Step 4:** Run the tests, mutation-prove them, and commit
  `feat(api): screens and hit profiling draw from compound_structures`.

### Task 5: Remove `screens.library_name` and `screens.deposit_kind`

**Files:**
- Modify: `atlas/sources/pubchem.py:230-234`, `atlas/sources/chembl.py:834-836`
- Modify: `atlas/agent.py` (screens note, `:384-388`)
- Modify: `tests/test_pubchem.py:279-280`, `tests/test_screens.py:799-800, 919, 936`,
  `tests/test_agent.py:211-212`

- [ ] **Step 1:** Change the column-list tests so the two names are absent, and assert they are
  not in a screen row. Expect a FAIL.
- [ ] **Step 2:** Delete both keys from both ingesters, and the note's two sentences about them.
- [ ] **Step 3:** Run `uv run pytest -q` and `make lint`. Commit
  `refactor: drop screens.library_name and deposit_kind, dead and redundant`.

### Task 6: Rebuild, re-measure and document

- [ ] **Step 1:** `make build` (warm cache: the chemreps file is already in `data/raw`).
- [ ] **Step 2:** Re-measure with DuckDB:
  - row counts and true/false counts for `compound_structures`;
  - the drawable shares for the hit-profiling population, for the actives of
    `pubchem:project:588335` and for screened ids (each with its denominator);
  - that `screens` has neither dropped column;
  - the sandbox's peak RSS on the real store;
  - the peak RSS of `/hits` and `/screens/{id}/results` through the API. If either exceeds about
    1 GB, give `_db()` the same `memory_limit`, as a separate commit.
- [ ] **Step 3: Docs.**
  - `docs/data-sources.md`: a section for `compound_structures` with the figures from Step 2;
    follow-ups 7 and 8 marked done; the drawable figures updated.
  - `CLAUDE.md`:
    - the "389 rows" sentence corrected to the TBMIC wording;
    - the `library_name`/`deposit_kind` sentence removed;
    - the bridge paragraph's "most of this layer cannot be drawn" replaced with the new figures;
    - the agent memory paragraph updated.
  - The agent notes that still say "2,013 of the 23,730" updated.
- [ ] **Step 4:** Run `uv run pytest -q` and `make lint`. Commit
  `docs: compound structures, the removals, and the sandbox's new memory figure`.
- [ ] **Step 5:** Whole-branch review by a fresh reviewer, which re-runs every new figure.
