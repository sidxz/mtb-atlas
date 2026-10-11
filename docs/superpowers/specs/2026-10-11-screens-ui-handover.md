# Screens UI — handover brief

**For whoever builds the Screens and Hit profiling pages.** Written 2026-10-11 by the session that
built the store layer (`feat/screens-store`, 63 commits, 588 tests). Read this before writing code;
it is the things that are expensive to discover by yourself.

## Start here, and in this order

1. **Branch from `feat/screens-store`, not `main`.** `main` has 28 tables and none of the screening
   ones. If that branch has merged by the time you read this, `main` is fine.
2. **Read `atlas/agent.py`'s `TABLE_NOTES` for `screens`, `screen_stages` and `screen_results`.**
   That is the authoritative description of the three tables, and it is the most heavily reviewed
   prose in the repo — four review rounds, because it is the one surface where a wrong join returns
   confident nonsense instead of an error. Everything the UI must not get wrong is already written
   there. Do not re-derive it from the Parquet schema.
3. **Read `docs/data-sources.md`**, the PubChem and ChEMBL campaign sections, for licence and
   coverage.

## The API does not exist yet, and that is your first job

`atlas/api.py` has no endpoint for these tables. Its fifteen occurrences of "screen" are all the
*TnSeq* genetics layer, which is a different thing entirely. `CLAUDE.md`'s rule is **the API reads
only the normalized store, and the frontend reads only the API** — so there is nothing for a page to
read until you build it.

Do the API first. The pages are much easier to design once you can see real responses, and the
store's real distributions are surprising enough that mock data would mislead you.

## The one hard performance constraint

`screen_results` holds **5,422,604 rows** — 122 MB on disk, and about **1.4 GB if you materialise
it in memory**. DuckDB over Parquet handles it comfortably (a three-table join with an unnest and a
group-by runs in 0.05 s), but:

- **No endpoint may select from `screen_results` unbounded.** Always filter by `stage_id` or
  `screen_id` first, and paginate. The existing `/targets` pagination is the pattern to copy.
- The per-SID rows are the point of the table — the inactives are what make "tested and did
  nothing" answerable — so do not aggregate them away in the store. Aggregate in the query.
- Measured for reference: the `/ask` agent's sandbox copies every table into memory and now sits at
  **1.9 GB resident**, of which `screen_results` is 1.4 GB. Three columns carrying four distinct
  values between them (`source`, `source_version`, `retrieved_at`) cost 516 MB of that, and
  `screen_id` is derivable from `stage_id`. If you touch `atlas/agent.py`, narrowing its copy is
  free money. The lazy-loading idea is in the follow-ups; it is a decision, not a defect.

## The honesty rules that constrain the UI specifically

These are not style preferences. Each one has a test behind it and at least one review round where
getting it wrong was caught.

- **`outcome` NULL is not `inactive`.** It means the source stated no call. Every ChEMBL row is
  NULL, and so is every row of a deposit with no cutoff. To find non-hits, filter
  `outcome = 'inactive'`; never `outcome IS NULL`. A UI that renders NULL as a dash in an
  "inactive" column has lied.
- **`n_screen_actives` and `n_target_screens` do not share a denominator.** The actives count sums
  only the screens that *stated* calls. A gene can legitimately show 120 actives beside 2 screens,
  or **nine screens and a NULL actives count** — pks13 does exactly that, because eight of its nine
  screens are ChEMBL papers (which never state calls) and the ninth deposit called everything
  `Unspecified`. **Never compute a hit rate by dividing one by the other.** If you show a hit rate
  at all, show it per screen, from that screen's own numbers, and only where it stated them.
- **A NULL activity count has two different causes**, and both must read as "not stated" rather
  than zero: no call was stated at all (`outcome_stated` false), or the per-stage counts overlap in
  a multi-assay campaign so a campaign-level number would double-count a compound (`outcome_stated`
  **true**, `n_stages > 1` — `fba` is the worked example). Go to the stage rows for the second case.
- **A screen filed against a complex is not a screen of either subunit.** `n_complex_screens` is
  shown and never counted as the gene's own. ClpP1 and ClpP2 each read 0 own, 2 complex.
- **`stage` and `modality` are orthogonal.** A primary screen can be phenotypic or biochemical.
  Do not collapse them into one funnel control. `stage` is NULL for a derived row (a selectivity
  index ChEMBL computed from two other assays), which occupies no funnel position.
- **Absences are answers and must be visibly different from zeroes.** `mmpL3` reads 0 own and 0
  complex screens, and that is a true finding, not a gap. Separately, **the Pathogen Box, the
  Malaria Box, GSK's TB set and one patent are not in the layer at all** — if a user searches for
  them they must learn the set is absent, not that it was screened and found nothing.
- **`screens` holds the campaigns that were ingested, not every ChEMBL campaign.** ChEMBL has 1,932
  documents with a whole-cell Mtb assay; 977 were ingested and 972 campaigns written, because
  candidates are enumerated from `activities`, which is compound-first. Any count the UI shows from
  this table is a count of ingested campaigns. Widening it is a named follow-up.
- **Provenance per value, as everywhere in this atlas.** Every row carries `source`,
  `source_version` and `retrieved_at`.

## What the store actually contains

Measured on the first real build, 2026-10-11:

| | |
|---|---|
| Campaigns | 999 — 972 ChEMBL literature, 27 PubChem (from 28 AIDs) |
| Stages | 17,530 |
| Result rows | 5,422,604 |
| Outcomes | 4,620,129 inactive · 737,106 no call · 37,197 inconclusive · 28,172 active |
| Genes with an own screen | **71** |
| Genes with a complex screen | 14 |
| Largest campaign | 359,484 substances (`fba`, Rv0363c) |
| Stage labels | 12,719 primary · 3,760 profiling · 986 NULL (derived) · 64 confirmatory · 1 counter_screen |

**71 genes out of 4,031 is the headline finding, and the UI should not hide it.** The scarcity of
public target-based screening in TB is the thing a target biologist learns from this page. Same
shape as the assay census: most of the genome has no chemical matter at all.

Note the stage distribution: **76.9% of stages sit at the default `primary` label** and 7.7% of
modalities at `other`, because the labels are classified from depositor prose. `atlas summary`
prints both shares. Treat a `primary` label as "nothing said otherwise", not as a positive claim.

## The intended shape

Agreed with the user earlier: **new top-level pages, not folded into the genome page.** The
navigation runs genes → targets → **screens** → **hit profiling**, following the early discovery
pipeline, because the organisation is the product here rather than any single number.

Beyond that the design is open. Two things carried over from the genome view that are easy to undo
by accident, both in `CLAUDE.md`:

- **A wider panel must not mean a wider line of text.** Prose caps at 78ch.
- **Numbers stay in columns.** `font-variant-numeric: tabular-nums` is on the body and is what the
  old monospace used to do for free.

## Open questions you will hit

1. **218 `IC50` rows read `Active` inside campaigns that state no outcome.** Row-level `outcome`
   and campaign-level `outcome_stated` disagree for those rows. It is documented, not reconciled,
   and under review as of this writing. Do not build a hit-rate display that depends on the two
   agreeing until it is settled.
2. **`max_screen_compounds` mixes units.** The PubChem branch uses campaign-level `n_tested`, the
   ChEMBL branch stage-level, so for a multi-AID PubChem project they are not the same quantity.
3. **Hit profiling's population is 9,602 compounds** with evidence beyond potency. An earlier
   figure of 17,763 was measured over the full 1,942-publication ChEMBL universe, not the ingested
   subset; both are correct for their own population. Use 9,602 for anything built on this store.

## Do not

- Do not read the store directly from the frontend, or add a second path into it.
- Do not introduce RDKit into the pipeline. It runs as WebAssembly **in the browser only**
  (`web/src/Structure.tsx`), fetched on first use so nobody who skips chemistry pays the 7.4 MB.
  Drawing a compound from a SMILES the API already serves is fine; storing a depiction is not.
- Do not add a nuisance-compound classifier. The seam is deliberately empty — see `CLAUDE.md`.
- Do not fill a gap from a different source to make a page look complete. That is the rule that
  outranks completeness.
