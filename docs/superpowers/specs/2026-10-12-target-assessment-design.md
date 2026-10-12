# Target assessment — design

_2026-10-12. What to bring over from `parsnip` / `parsnip-ai`, and what not to.
Decided with Sid in conversation: **ship the evidence, not the score.**_

## The shape in one sentence

Parsnip asks 76 weighted questions about a target and returns four 0–100 scores.
This milestone takes **the questions** and throws away **the scores**: a per-gene
assessment view that says, for each question a target team actually asks, what the
atlas can answer from a source and what it cannot — plus one new source,
`literature_facts`, for the assay contexts no database covers.

## Why not the scores

Parsnip's own validation is the argument: its scores could only be calibrated
against non-public reference baselines, which cannot come here, and without them
there is nothing public to calibrate a score against.

Two further reasons the number would be dishonest in this atlas:

- **`UNKNOWN` earns ~1% of `ACTIVE` credit** rather than nothing, so a target with
  no evidence at all scores above zero and the scale reads as measurement of
  something. For a genuinely novel target — the whole point — most answers are
  honestly `UNKNOWN`, and parsnip's chemical axis duly showed "systematic
  UNDER-scoring (many novel targets → 0)".
- The weights live in `parsnip-data/config/constants.json` and have changed over
  time, so even parsnip treats its own scores as rank-comparable only.

A 0–100 next to sourced columns reads as the same kind of fact as `n_pdb`. It is
not one. The questions, by contrast, are a real public artifact: the structured
list of what the decision actually turns on.

## What comes over, and from where

| Asset | Public? | Verdict |
|---|---|---|
| TPQ: 76 questions, per-question answer vocabularies (`parsnip-data/data/questions.json`) | `github.com/sidxz/parsnip-data`, public | **Yes** — as a checklist. Licence needs stating (Sid's own repo). |
| Literature KB: 445 papers, 850 quote-backed facts (`parsnip-ai/kb/literature.db`) | Mostly OA; see the gate below | **Yes, re-derived** — the one new source. |
| Assay-context vocabulary (`caseum`, `nr_hypoxia`, `gluconeogenic`, `macrophage`, `mouse_acute/chronic`, `nhp`) | — | **Yes** — a taxonomy, and it extends `assay_condition`. |
| Scoring JS (`score.js`, `section2–6.js`), weights, `constants.json` | Public | **No** — see above. |
| CRISPRi vulnerability, PDB, ChEMBL, essentiality, redundancy | Public | **No** — the atlas already has all five, with provenance and honesty rules parsnip does not have. |
| Anything derived from consortium data | **Consortium** | **Never.** Nothing from it enters this repo. |
| `analysis/perplex/` | Public method, but it is the attempt that underperformed and is marked outdated | **No.** |

## The new source: `literature_facts`

### What it is

Per-gene, per-assay-context evidence mined from open-access full text, each row
carrying a **verbatim quote** and the PMID it came from. This is the layer the
atlas has no database for: `assay_condition` today has **no `caseum` rows at
all** and the CLAUDE.md keeps that zero visible rather than filling it. The KB
has 11 `caseum` active and 4 inactive, 21 `nr_hypoxia` across both directions,
12 `macrophage`, 19 mouse, 4 NHP — all quote-backed.

### The licence gate, which decides the scope

Of 850 facts, **154 (18%) come from papers whose source is `citations-paywalled`**.
Their quotes are not redistributable, so they do not come. Of the 445 papers,
318 carry a PMCID and `source` is `europepmc` for 344 and `pubmed` for 82 — but
**`oa_status` is empty on all 445**, so which papers are in the PMC OA subset
has not been established and must be, per paper, before any quote is stored.
Only the PMC OA subset (CC BY / CC BY-NC / CC0, stated per article) permits
storing and serving a quote with attribution. A PMID is a fact and a
bibliography is not copyrightable, so the *paper list* can be reused freely;
the text cannot.

### Why re-derive rather than import the SQLite

Three reasons, each one of the atlas's own existing rules:

1. **`source_version` must be stated or `"unknown"`.** `facts.extractor_model` is
   the bare string `subagent` for **526 of 850 rows (62%)** — no model named. The
   rest are `claude-fable-5` (231), `claude-opus-4-8` (27), `claude-opus-4-8+sonnet-finder`
   (63) and `recovery-abstract` (3). Five extractors, mostly unnamed, is not a
   version this atlas can stamp.
2. **All fetching goes through `atlas/fetch.py`**, which owns the cache and writes
   the `.meta.json` sidecar that provenance comes from. Parsnip's corpus is 454
   loose `.txt` files with no sidecars.
3. **The gene key is a free string, and it collides.** 95 distinct `target_gene`
   values, case-inconsistent — `AspS`/`aspS`, `Pks13`/`pks13`, `PckA`/`pckA`,
   `MenA`/`menA`, `LepB`/`lepB`, `LeuS`/`leuS`, `TopA`/`topA`, `PknB`/`pknB` are
   eight pairs that are one gene each. Parsnip's own notes record `EtfD` as
   unresolved (the name matches the ETF subunit, not the oxidoreductase). The
   atlas is keyed on the Rv locus and **an unresolved name must be recorded
   unmatched, never guessed** — the same rule `screens.targets` already follows
   for `P9WFX0`.

So: **reuse the paper list, re-fetch the OA subset through `fetch.py`, re-extract
with one named model.** That is the cheap route that does not break a rule.

### Honesty rules this layer needs

It is the first layer where an LLM extraction becomes a stored row, so it carries
rules the others do not.

- **A mined fact is this atlas's reading of a paper, not a measurement.** It never
  merges into a ChEMBL row and never counts into a column that reads as measured.
  `source` is the mining run, not the journal; the PMID is the citation.
- **The quote travels with the value, always.** All 850 KB rows have a non-empty
  quote; that property is a requirement here, not a happy accident. A row whose
  quote does not support its value is a defect, not a low-confidence row.
- **Absence means not mined, and for this layer that is the common case.** 95
  strings reach perhaps 87 genes of 4,031 — **2% coverage**. This inverts the
  atlas's usual rule that a zero can mean zero: here a zero means "nobody looked",
  and the column must say so. `mined` is a separate boolean from any direction.
- **`direction = inactive` is a result; absence is not.** BTZ-043 reading inactive
  in rabbit caseum is a finding, and one the atlas wants: it is exactly the shape
  of "tested and inactive" that `screen_results` exists to preserve.
- **`confidence` is the extractor's, not the paper's** (KB: 493 high, 336 medium,
  21 low). It is shown, never used to filter silently.
- **The extracting model is part of the provenance**, recorded per row, because a
  re-mine with a different model is a different source version.

### Keying

`rv_id`, resolved from the gene symbol through the existing crosswalk, with the
case collapse applied once and the result checked. Unresolved names get a row in
an `unmatched` table with the string as given — not a guess, not a drop.

## The view: assessment, not "targets"

`/targets` is already the gene-table route in `atlas/api.py` and the genome canvas
reads it. The new surface is **assessment**: per gene, the TPQ's questions grouped
as parsnip groups them, each one showing

- what the atlas answers from a source, with the value and its provenance;
- what no public source answers, said plainly;
- which questions the `literature_facts` layer reaches, with the quote and PMID.

The atlas already answers a large share of the structural, genetic and
chemical-matter questions better than parsnip did, because parsnip read them from
the same public sources without the honesty rules: essentiality and vulnerability
(and HN878, which parsnip has no equivalent of), structures with resolution and
ligands, redundancy via paralogs at a stated threshold, human homology with its
identity number, drug precedent with its three guards, whole-cell pMIC with
conditions, screening scale with denominators. The gaps the view will expose
honestly are the in-vivo and host-context ones — exactly where
`literature_facts` lands, and exactly where parsnip needed tier-3 mining too.

**No score, no axis, no ranking, no weight is displayed or stored.** The
questions' weights are not ingested at all; without them the file cannot be
mistaken for a scorer.

## Open questions for Sid

1. **Licence for the TPQ question set.** `parsnip-data` is public and yours, but
   states no licence. `docs/data-sources.md` needs one, and "none stated" is
   already how Mycobrowser is recorded, so that is an acceptable answer — but it
   should be a decision, not a default.
2. **Which model, and is one pass enough?** Re-extraction needs one named model
   for a stampable `source_version`. The pipeline currently imports `anthropic`
   only in `atlas/agent.py`, and `check`/`refresh`/`diff` run with no API key —
   this would be the first stage that needs one. That breaks "nothing in the
   update path touches an LLM" unless the mining stage is explicitly **outside**
   the update path: mined once, committed as a versioned input, re-run only on
   request. I recommend that.
3. **Scope of the first cut.** The ~87 resolvable genes the KB already covers
   (includes dprE1, inhA, mmpL3 — not GroEL2), or widen the paper search? I
   recommend the former: it is bounded, and three of the four validation genes
   are in it.
4. **Does the assessment view show the question identifiers** (`2C3`, `6B5A`)?
   They are meaningful to anyone who has used parsnip and noise to anyone who has
   not.

## Cost

The paper list and OA-status check are cheap. Re-extraction is one LLM pass over
the OA subset of ~450 papers — the only real cost, and it is a one-off per mining
run, not per build. The view is one route plus one component. No new pipeline
dependency: `fetch.py` already does the fetching, and the extraction stage runs
outside `make build` by question 2's recommendation.
