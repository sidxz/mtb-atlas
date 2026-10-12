# Target assessment — design

_2026-10-12. What to bring over from `parsnip` / `parsnip-ai`, and what not to.
Decided with Sid in conversation: **ship the evidence, not the score**, and
**parsnip-ai is an upstream source — the atlas does not mine.**_

## The shape in one sentence

Parsnip asks 76 weighted questions about a target and returns four 0–100 scores.
This milestone takes **the questions** and throws away **the scores**: a per-gene
assessment view that says, for each question a target team actually asks, what the
atlas can answer from a source and what it cannot — and ingests parsnip-ai's mined
literature facts as one more public source, for the assay contexts no database
covers.

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
| Mined literature facts (`parsnip-ai/kb/facts/*.jsonl`, 850 rows) + run manifests (`kb/runs/`) | Mostly OA; see the licence split | **Yes — ingested as an upstream source.** |
| Assay-context vocabulary (`caseum`, `nr_hypoxia`, `gluconeogenic`, `macrophage`, `mouse_acute/chronic`, `nhp`, and the `_gen` genetic variants) | — | **Yes** — a taxonomy, and it extends `assay_condition`. |
| Saturation markers (`kb/runs/*.saturated`, 36 of them) | — | **Yes** — they are the only thing that separates "searched and found nothing" from "never looked". |
| Scoring JS (`score.js`, `section2–6.js`), weights, `constants.json` | Public | **No** — see above. The weights are not ingested at all, so the file cannot be mistaken for a scorer. |
| CRISPRi vulnerability, PDB, ChEMBL, essentiality, redundancy | Public | **No** — the atlas already has all five, with provenance and honesty rules parsnip does not have. |
| Anything derived from consortium data | **Consortium** | **Never.** Nothing from it enters this repo. |
| `analysis/perplex/` | Public method, but the attempt that underperformed and is marked outdated | **No.** |

## The new source: `literature_facts`, ingested not mined

### Why ingesting is the right call

Parsnip already did the work, and it did it with a discipline the atlas can
stand behind:

- **"Every fact carries a verbatim quote or it is not a fact."** All 850 rows have
  a non-empty quote.
- **`kb/verify.py` is a gate**, not a report: every quote is re-confirmed verbatim
  against the frozen corpus text and the run is not done until it exits 0. The
  atlas can re-run that same gate on ingest.
- **"The LLM never answers from its own knowledge"** — extraction is over
  retrieved primary text only, and empty retrieval returns `UNKNOWN`. This is the
  rule whose absence made the earlier `analysis/` attempt fail.
- **The durable artifact is committed JSONL**, not the SQLite: 18 files under
  `kb/facts/`, with the DB rebuilt from them by `kb.py load`. Clean to ingest.
- **The run manifests are real provenance**: run id, questions, assay contexts,
  search date, model, method, every query run, and per-PMID inclusions with the
  mode and a note. `kb/runs/2026Q3-genetic-invivo-section4.json` is the example.

So the atlas does not mine, imports no `anthropic` dependency into the pipeline,
and needs no API key. **`make build`, `check`, `refresh` and `diff` stay exactly
as CLAUDE.md describes them** — nothing in the update path touches an LLM. This is
the same relationship the atlas already has with MtbTnDB: someone else computed
it, we record what they computed and what it does not cover.

### Version and refresh

`source_version` is the run-manifest id, which is already quarter-stamped
(`2026Q2-rpoB-2C3`, `2026Q3-genetic-invivo-section4`), or a release tag once
parsnip-ai publishes. `atlas check` probes the published location the way the
other sources are probed; a new mining run is a new version and `atlas diff` is
the gate, as it is for everything else.

This source **does not re-key the crosswalk** — facts attach to Rv loci that
already exist — so by CLAUDE.md's rule it is in the safe-unattended class with
`clinicaltrials-gov`. A new run can still change which genes carry evidence, so
the diff still has to be read.

### The licence split, which is the one real gate

Of 850 facts, **154 (18%) come from papers whose source is `citations-paywalled`**.
They are the three user-supplied genome-wide supplementaries — Rock 2026 mBio
in-vivo CRISPRi (76 acute + 76 chronic hits), Rengarajan 2005 macrophage Tn-seq,
Sassetti 2003 in-vivo Tn-seq. Also, `oa_status` is empty on all 445 papers, so OA
status is not currently recorded anywhere and must be established per paper
before a quote is served.

Three options, Sid's call:

1. **Exclude the paywalled rows.** Safest; loses the genome-wide in-vivo CRISPRi,
   which is the richest single contribution and the one that covers essential
   genes (Tn-seq structurally misses them).
2. **Carry the value without the verbatim quote** for those rows — gene, context,
   direction, confidence, PMID, and a `quote_withheld` flag. Defensible for
   table-derived data: a hit call in a supplementary table is a fact, not
   copyrightable expression. But it breaks the "quote travels with the value"
   rule for 18% of rows, so the flag has to be visible.
3. **Ingest only rows from papers confirmed in the PMC OA subset**, establishing
   `oa_status` per paper first. The most work, the cleanest result, and it
   subsumes option 1.

I recommend **3 for the quote, with 2 as the fallback for the three
screen-derived deposits** — their value is a table row, and withholding the
prose while keeping the call is both legal and honest if the flag is shown.

### Honesty rules this layer needs

It is the first layer whose rows are an LLM's reading of a paper, so it carries
rules the others do not.

- **A mined fact is a reading of a paper, not a measurement.** It never merges
  into a ChEMBL row and never counts into a column that reads as measured.
  `source` is `parsnip-ai` with its run id; the PMID is the citation.
- **The quote travels with the value** (except where the licence split withholds
  it, flagged). A row whose quote does not support its value is a defect, not a
  low-confidence row — and `verify.py` is what catches that.
- **Three states, not two: mined-and-found, mined-and-found-nothing, never
  mined.** The 36 `.saturated` markers are what make the middle state sayable
  ("caseum corpus saturated 2026-06-30 after 3 rounds"). Without them, absence
  over the 3,944 genes nobody looked at would read the same as a searched zero.
  This inverts the atlas's usual rule that a zero can mean zero, and the column
  must say which zero it is.
- **`direction = inactive` is a result; absence is not.** BTZ-043 reading
  inactive in rabbit caseum is a finding the atlas wants — the same shape of
  "tested and inactive" that `screen_results` exists to preserve. Parsnip's own
  rule matches: "never assert INACTIVE from absence of data".
- **`confidence` is the extractor's, not the paper's** (493 high, 336 medium, 21
  low). Shown, never used to filter silently.
- **`extractor_model` is recorded as given, including where it is unhelpful.**
  It is the bare string `subagent` on 526 of 850 rows; the run manifest names
  the real model where the row does not. Recorded as given, the way
  `screens.depositor` holds PubChem's bare `11908` — not laundered, not guessed.

### Keying

`rv_id`, resolved from the gene symbol through the existing crosswalk. Three
things the ingester must handle, all visible in the current data:

- **95 distinct `target_gene` strings, case-inconsistent.** `AspS`/`aspS`,
  `Pks13`/`pks13`, `PckA`/`pckA`, `MenA`/`menA`, `LepB`/`lepB`, `LeuS`/`leuS`,
  `TopA`/`topA`, `PknB`/`pknB` are eight pairs that are one gene each.
- **Compound keys.** One row is keyed `dprE1/ubiA` and names two genes; it has to
  split, not be dropped or assigned to one.
- **Unresolved names get a row in an `unmatched` table with the string as
  given** — never a guess. Parsnip hit this itself (`EtfD` was unresolvable until
  Beites 2021 named it `Rv0338c`), which is exactly why the atlas records rather
  than bridges, the same rule `screens.targets` follows for `P9WFX0`.

Coverage after resolution is roughly **87 genes of 4,031** — about 2%. That is
the point of the three-state rule above.

## The view: assessment, not "targets"

`/targets` is already the gene-table route in `atlas/api.py` and the genome canvas
reads it. The new surface is **assessment**: per gene, the TPQ's questions grouped
as parsnip groups them, each one showing

- what the atlas answers from a source, with the value and its provenance;
- what no public source answers, said plainly;
- which questions `literature_facts` reaches, with the quote and PMID.

The atlas already answers a large share of the structural, genetic and
chemical-matter questions better than parsnip did, because parsnip read them from
the same public sources without the honesty rules: essentiality and vulnerability
(and HN878, which parsnip has no equivalent of), structures with resolution and
ligands, redundancy via paralogs at a stated threshold, human homology with its
identity number, drug precedent with its three guards, whole-cell pMIC with
conditions, screening scale with denominators. The gaps the view exposes honestly
are the in-vivo and host-context ones — exactly where `literature_facts` lands,
and exactly where parsnip needed tier-3 mining too.

**No score, no axis, no ranking, no weight is displayed or stored.**

## Prerequisite on the parsnip side

`parsnip-ai` is not a git repository and has no remote — the CLAUDE.md table
lists it with none. The atlas fetches everything through `atlas/fetch.py` from a
URL, so the facts need a published location. The cheap route is the one parsnip
already uses: publish `kb/facts/`, `kb/runs/` and `kb/corpus/` into
`parsnip-data` (or a new public repo) and fetch from `raw.githubusercontent.com`,
exactly as the parsnip app fetches its data today. `kb/corpus/` is 11 MB over 454
files, so it is publishable as-is — and it has to be, for `verify.py` to be
re-runnable here.

Until that exists, the ingester can be built and tested against committed
fixtures (which is the rule anyway), but the build cannot run.

## Open questions for Sid

1. **The licence split** above — exclude, withhold-quote, or OA-confirm per paper.
   Recommendation: OA-confirm, with withhold-quote for the three screen deposits.
2. **Where parsnip-ai publishes**, and under what licence. `parsnip-data` states
   none today; "none stated" is how Mycobrowser is already recorded, so it is an
   acceptable answer, but it should be a decision.
3. **Scope of the first cut**: the ~87 genes the facts already cover (includes
   dprE1, inhA, mmpL3 — not GroEL2), which I recommend, since it is bounded and
   three of the four validation genes are in it.
4. **Does the assessment view show the question identifiers** (`2C3`, `6B5A`)?
   Meaningful to anyone who has used parsnip, noise to anyone who has not.

## Cost

One ingester of the usual shape (`fetch_raw` → `normalize` → `build`), one
`atlas check` probe, one API route, one view. No new pipeline dependency and no
API key: the mining already happened upstream. The only real work outside the
usual is the OA-status determination the licence split needs.
