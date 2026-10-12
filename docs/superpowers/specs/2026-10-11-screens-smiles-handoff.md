# Structures for the screening layer — handoff

**For the session that builds this.** Written 2026-10-11 by the session that built the screening
store (`feat/screens-store`, merged to main at `24a7d7d`).

## The problem

`compounds.parquet` is the **ChEMBL potency set** (5,178 rows). The screening layer's compound
population is a different and much larger one, and almost none of it has a structure:

| population | has a SMILES |
|---|---|
| hit-profiling compounds | 2,013 of **23,730** |
| actives in `pubchem:project:588335` | 200 of **12,676** |
| distinct screened `molecule_chembl_id` store-wide | 4,308 of **479,023** |

So roughly **99% of the screening layer cannot be drawn**. Hit triage is a visual activity — a
chemist scanning a campaign's actives for a recurring scaffold is the main thing the Screens page
is for — and today the pages honestly print their coverage instead, via `n_with_structure` on
`/screens/{id}/results` and `population.with_structure` on `/hits`. That is truthful but it is not
the feature.

## Do it with the bulk file, not the API

This was Sid's call and the measurement backs it. ChEMBL publishes a flat file of every compound's
structure:

```
https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/releases/chembl_37/chembl_37_chemreps.txt.gz
  Content-Length: 292,540,141   (292 MB gzipped)
  Last-Modified:  Fri, 29 May 2026
  Columns (tab-separated, one header line):
    chembl_id   canonical_smiles   standard_inchi   standard_inchi_key
```

**One download replaces roughly 9,500 API requests**, and it covers all 479,023 screened compounds
rather than only the 23,730 profiled ones — so the scope question the API route forced
("which subset can we afford?") simply disappears. Verified reachable and the format confirmed by
reading the first rows.

**There is precedent in this pipeline, deliberately.** `atlas/sources/unichem.py` already downloads
a whole-source mapping file (`src1src22.txt.gz`, 2.8M pairs) for exactly this reason: when the
question is "map my whole key set", a bulk file beats per-id requests and is kinder to the upstream
server. Follow that module's shape.

Rejected: `chembl_37_sqlite.tar.gz` is **5.76 GB** and would need a second database engine in the
pipeline for one column. Rejected: the per-molecule REST endpoint, on request count.

Notes on the download:
- Only `chembl_id` and `canonical_smiles` are needed. The two InChI columns are most of the bytes
  and cannot be avoided (no partial fetch), but they need not be stored. Whether to keep
  `standard_inchi_key` is a judgement call — it is a useful cross-reference key and cheap; decide it
  in the spec rather than by accident.
- Stream the gzip and keep only ids the store actually references. Do not materialise 2.4M rows.
- `data/raw` is currently 1.1 GB; this adds 292 MB.
- The file names its release (`chembl_37`), so `source_version` is honest and the existing ChEMBL
  freshness probe already covers when it moves.
- Licence is ChEMBL's, CC BY-SA 3.0, already recorded in `docs/data-sources.md`.

## Three constraints, all load-bearing

These came from the session that built the API, and they are right:

1. **A compound with no structure must stay distinguishable from one never looked up.** With a ~99%
   starting gap this *is* the column's value — a single NULL for both states makes the coverage
   number the pages already print unverifiable. Same three-state discipline as `measured` on the
   TnSeq tables and `outcome_stated` on `screens`.
2. **Whatever table it lands in needs its own provenance.** Do **not** widen `compounds`: that
   table's `source_version` is stamped for the potency set, and widening it silently re-scopes a
   claim to a population it was never measured over. A **separate Parquet keyed on
   `molecule_chembl_id`** with its own `source`/`source_version`/`retrieved_at` is the design, and
   it is the same seam `CLAUDE.md` describes as deliberately empty for per-compound annotations.
3. **`atlas diff` keys on the table**, so a new table needs an entry in `storediff.KEYS` — and
   `tests/test_upkeep.py` asserts `set(agent.TABLES) == set(storediff.KEYS)` in both directions, so
   it needs an `agent.TABLES` entry and therefore a `TABLE_NOTES` entry too. Budget for that: the
   notes are the only surface where a wrong join is silent, and on this branch they needed four
   review rounds and three false statements were caught in them.

**PubChem-only compounds are out of scope.** A CID with no ChEMBL id has nothing to fetch by; it
needs the UniChem bridge first, and that bridge is incomplete (55.8% of CIDs). An unmapped CID is a
different problem from an unfetched SMILES and should stay one.

## Fold in two removals — Sid approved this

Both are in `screens` and both are schema changes, so doing them with the new table means **one
rebuild rather than two**:

- **`screens.library_name`** is hardcoded `None` in both ingesters (`pubchem.py`, `chembl.py`) and
  NULL on all 999 rows. Not empty in this build — **dead by construction.** It was documented
  rather than dropped only because a concurrent session was building an API against the schema;
  that session has since merged and explicitly unblocked the removal.
- **`screens.deposit_kind`** is `dataset` on all 27 PubChem rows and `publication` on all 972
  ChEMBL ones, so it restates `source` and nothing else. Worse, `dataset` is **the same word** as
  the ChEMBL `doc_type` the campaign builder *excludes*, which `docs/data-sources.md` is at pains to
  say is not in the layer — a reader joining the two statements gets "datasets are excluded, and 27
  of them are here."

Both are named as follow-up 7 in `docs/data-sources.md`. Removing them touches the ingesters, the
agent notes, and the docs.

## Read these before writing code

- **`CLAUDE.md`**, especially "Evidence must stay honest" — the rule that outranks completeness.
- **`docs/data-sources.md`**, the screening section and the eight named follow-ups at the end.
- **`atlas/sources/unichem.py`** — the bulk-file pattern to copy.
- **`atlas/agent.py`'s `TABLE_NOTES`** — what a trap entry has to do.
- **`docs/superpowers/specs/2026-10-11-screens-ui-handover.md`** — the layer's honesty rules with
  worked examples, written for the API session and still accurate.
- **`.superpowers/sdd/2026-10-11-screens-store/progress.md`** — the previous run's ledger: 59
  rulings with their reasons and costs. Long, but it will stop you re-deciding something.

## One known-false sentence on main

`CLAUDE.md:386` still reads *"389 rows of the selectivity-index family are not TB"*. **32 of those
389 are tuberculosis, written as `TBMIC`** — e.g. "Selectivity is the ratio of cytotoxicity compared
to TBMIC". `atlas/agent.py` and `docs/data-sources.md` were corrected at `37711aa`; `CLAUDE.md` was
not, because the session that found it correctly declined to edit that file on a peer's request.
Sid has the replacement text. Fix it if it is still there when you start.

## Also: leave `web/src` alone

Sid is doing manual UI cleanup by hand. Nothing in this work should touch those files — it is an
ingester, a table and its provenance. Another session has a dev server on :5180 and an API on :8098.

## How this project works

Small commits, conventional messages, `Co-Authored-By: Claude …` and **no** `Claude-Session:`
trailer. Python 3.12, `uv`, ruff at line length 100. Tests run against committed fixtures, never the
network. TDD, and mutation-prove each new test — on the previous run seven tests turned out to
assert nothing and were caught that way. Spec → plan → execute is the convention; the specs live in
`docs/superpowers/specs/`.

**And the one thing that matters most here:** a number in the documentation must reproduce against
the store. The previous run published roughly forty figures and a reviewer checked them with DuckDB;
two did not reproduce and both were defects. Three separate "disagreements" between sessions turned
out to be two correct numbers over different populations, which is why every share in these docs
states its denominator. Keep that convention — it is what makes the next reviewer able to verify
instead of guess.
