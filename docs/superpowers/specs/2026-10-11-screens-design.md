# Screens: the public screening record, arranged as the early pipeline

M11 and M12. Status: design, not built.

The atlas answers *target selection* (genes, essentiality, vulnerability,
structures) and *the clinic* (drugs, trials). The middle is missing: what has
actually been screened against this organism, in what, how big the library
was, what came out, and how far those hits were profiled. This layer is that
middle, and its job is **organisation, not judgement** — no score, no ranking,
no verdict on whether a screen or a hit was any good. Counts are counts.

The questions it exists to answer:

- Has this protein ever been screened, and against how many compounds?
- Has this compound ever been tested against Mtb, and what happened?
- What public screening campaigns exist, phenotypic and target-based, and
  under which conditions and strains?
- For a campaign's hits: was there a dose–response, a counter-screen, a
  cytotoxicity check, ADME, an animal?
- For one compound: what has been measured on it beyond whether it works?
- Which phenotypic hits have a candidate gene? (M12)

## Why now: the atlas is discarding most of the chemistry it downloads

Measured live against ChEMBL_37 on 2026-10-11.

ChEMBL holds **509,693 activities** across 144 Mtb targets.
`data/store/activities.parquet` holds **15,518**. The cause is one filter,
`pchembl_value__isnull=false` in `atlas/sources/chembl.py:138`. Primary
screening data has no pChEMBL value:

| endpoint, protein targets | rows |
|---|---|
| `Percent Effect` | 276,472 |
| `IC50`/`AC50`/`EC50`/`Inhibition`/`Ki`/`Kd`/`Activity` | 19,754 |

So `max_assay_compounds` is wrong wherever a campaign reported percent
inhibition, which is wherever there was a campaign. One deposit
(`CHEMBL3988442`, Dundee/GHDDI/Cornell, 2021):

| target | compounds tested | atlas `max_assay_compounds` |
|---|---|---|
| ClpP1P2 (`PROTEIN COMPLEX`) | 68,611 | 8 |
| CoaBC (`Rv1391`/`dfp`) | 66,942 | 0 |
| Pks13 (`Rv3800c`) | 66,592 | 143 |
| TrpRS (`Rv3336c`) | 65,366 | 2 |
| AspRS (`Rv2572c`) | 8,841 | 12 |
| whole-cell, Cornell ×2 | 68,614 / 53,166 | n/a |

`docs/data-sources.md` therefore states a finding that is false: "two genes
have a public assay reaching 1,000 compounds — `recA` (1,875) and `dnaB`
(1,642)". The scarcity claim inverts, and that correction is prerequisite to
this layer rather than part of it.

**Measured after the fix landed: six genes, three of them above 60,000** —
`dfp`/CoaBC (66,942), `pks13` (66,592), `trpS` (65,366), `aspS` (8,841),
`dnaB` (2,123) and `recA` (2,118). Even `recA` and `dnaB` move, because the
old numbers counted only rows carrying a `pchembl_value`.

An earlier draft of this section predicted seven genes with five above 60,000.
That was wrong, and wrong in an instructive way: it counted ClpP1P2's
68,611-compound screen as two genes, `clpP1` and `clpP2`. The complex rule
below forbids exactly that, so the prediction contradicted this spec's own
trap 5. The screen is real and is reported in `n_complex_assays`; it is not
either subunit's own.

## Scope

**M11 — the screening record, and hit profiling.** ChEMBL + PubChem.
Campaigns, their stages, their per-compound results including the compounds
that did nothing, and the gene links that are real. One ingest, two views:
**Screens** pivots on the campaign, **Hit profiling** pivots on the compound.

The second view is justified by measurement, not symmetry. Across the 1,942
Mtb whole-cell publications, 48,106 distinct compounds appear and 37,555 carry
an Mtb MIC. Beyond potency:

| also measured on the same compound | compounds |
|---|---|
| mammalian cytotoxicity | 16,141 |
| ADME/PK | 5,211 |
| efficacy in an infected animal | 625 |
| cytotoxicity **and** ADME | 3,735 |
| cytotoxicity **and** ADME **and** animal | 267 |
| any tier beyond potency | **17,763** |
| also a measurement on an Mtb protein | 3,836 |

17,763 compounds is the second-largest object population in the atlas after
genes — larger than drugs (112), trials (1,137) and `compounds` (5,178)
together. PubChem adds 45 counter-screen/cytotoxicity AIDs and 13 confirmatory
assays across the 124 declared project members, at thousands of compounds
each.

**The view is named for coverage, not for a verdict.** "Hit assessment" is the
pipeline stage and stays in prose; the view is **Hit profiling**, and its
content is what was measured, with the absences visible. 20,000 compounds have
a MIC and nothing else, which is the answer and not a low score. No column in
it is ranked, weighted or summed.

**M12 — chemical genetics.** PROSPECT (Broad, CC0): compound × hypomorph
growth rate, the only public source at scale that proposes a *gene* for a
phenotypic hit. Separate because a chemical-genetic profile is a different
claim from a screen result and needs its own traps.

**Deliberately excluded**, with reasons, so they are not revisited:

- **newtbdrugs.org** — the only public TB pipeline registry, and the obvious
  source for "portfolio". Footer reads `©2016 Working Group on New TB Drugs.
  All Rights Reserved.`, no CSV/JSON/API, content behind a Google Slides deck.
  Link-out only. 32 discovery projects, 14 naming a target; worth citing, not
  ingesting.
- **CDD Vault public TB datasets** — re-hostings of the TAACF/MLSMR PubChem
  data, registration-gated, no redistribution licence found. Ingest the
  PubChem originals: same data, traceable provenance.
- **GSK TCAMS beyond what ChEMBL already holds** — ChEMBL-NTD sets 9 and 17
  are CC0 but are the 177- and 50-compound *hit* sets. The ~2M-compound parent
  screen was never released, so a zero in TCAMS cannot mean "tested and
  inactive". Nothing to add beyond the ChEMBL records.
- **Portfolio and post-portfolio stages.** Public data does not support them.
  Said plainly in the UI rather than approximated from trials.
- **Any screen or hit scoring.** Not a data gap — a deliberate omission.

## Milestone 0: the filter fix, as its own commit, first

Narrow and landing before any of the above.

1. `atlas/sources/chembl.py` — fetch an unfiltered per-target activity census
   (`assay_chembl_id`, `molecule_chembl_id`, `standard_type`, value, units,
   relation only). The potency rows that reach `activities.parquet` are
   unchanged; the census is a separate cached artefact, and M11 reads the same
   cache rather than re-downloading it.
2. `atlas/summary.py` — compute `n_protein_assays`, `max_assay_compounds` and
   `latest_protein_assay_year` from the census.
3. **Apply the existing complex rule while doing so.** `n_protein_assays`
   filters on `evidence = 'direct'` but not on `target_type`, and
   `crosswalk.parquet` maps the `ClpP1P2` `PROTEIN COMPLEX` target to *both*
   `Rv2461c` and `Rv2460c` as `direct`. Without the filter the fix hands each
   subunit its own 68,611-compound screen — the ribosome problem `CLAUDE.md`
   already rules on ("Only `SINGLE PROTEIN` targets count"). Complex screens
   get their own column and are shown, never counted.
4. Correct the numbers in `docs/data-sources.md` ("Screened, or merely
   studied?") and `README.md`.

Without step 3 the fix introduces a wrong number while removing another, which
is why it belongs in the fix and not in M11.

## The model: campaign → stage → result

Three levels, because the sources have three levels and the pipeline is the
middle one.

A **campaign** is one screening effort. A **stage** is one assay within it. A
**result** is one compound's outcome at one stage.

| level | ChEMBL | PubChem |
|---|---|---|
| campaign | `document_chembl_id` | project (`pcassay_pcassay_same_assay_project_list`), else the AID |
| stage | `assay_chembl_id` | AID |
| result | activity row | data table row |

PubChem's project links are the pipeline **as the depositor declared it**:
AID 449775 (Summary) groups 39 members including 449762 (primary, 327,669
tested), 449764 (confirmatory dose–response, 2,262 tested / 1,732 active) and
504335 (Vero cytotoxicity counter-screen). That is the arrangement, sourced
rather than inferred.

**One campaign, one source.** A campaign with a PubChem AID is ingested from
PubChem; a ChEMBL document without one is ingested from ChEMBL. No campaign is
assembled from both, so nothing is double-counted. PubChem supplies the
tested set and the stated outcome; ChEMBL supplies the literature ladder and
the potency values.

### Two orthogonal axes, never one

**The ingest takes every assay in a campaign document, not only the Mtb-target
ones.** This is the step that makes hit profiling possible and the easiest one
to leave out: a paper's cytotoxicity, microsome and animal assays are filed
against `CELL-LINE`, `ADMET` and non-molecular targets, so an Mtb-target query
cannot see them. Querying ChEMBL by target returns 11,686 assays for these
documents; querying by document returns **38,335**. The campaign document is
the unit of the second fetch, and ~293,000 further activity rows come with it.

`stage` is funnel position: `primary` | `confirmatory` | `counter_screen` |
`profiling`. `modality` is what was measured: `phenotypic_mtb` |
`biochemical_mtb` | `mammalian_cytotox` | `adme` | `in_vivo_efficacy` |
`other_pathogen`. A primary screen can be phenotypic or biochemical; collapsing
the two axes into one vocabulary would make "primary" and "MIC" look like
alternatives.

Measured over the 1,949 ChEMBL documents that report Mtb whole-cell data:

| modality present in the campaign | documents |
|---|---|
| `phenotypic_mtb` | 1,949 |
| `mammalian_cytotox` | 1,215 |
| `adme` | 405 |
| `in_vivo_efficacy` (CFU/lung/spleen/survival, infected animal) | 150 |
| `biochemical_mtb` | 251 |
| all of MIC + cytotox + ADME + animal | **65** |

65 public compound series have been profiled to an animal. Nobody has arranged
them as a funnel; that is the deliverable.

## Tables

### `screens` — one row per campaign

`screen_id` (`pubchem:project:449775` | `pubchem:1626` | `chembl:CHEMBL3988442`),
`title`, `depositor`, `deposit_kind` (`dataset` | `publication` | `patent`,
from the source's own `doc_type`/deposit status), `library_name` where the
source names one (MLSMR, TAACF, Pathogen Box, Dundee Small-Polar-MMV),
`library_size_stated` (the depositor's prose figure, separate from what was
deposited), `year`, `n_stages`, `n_tested`, `n_active`, `n_inactive`,
`n_inconclusive`, `outcome_stated` (bool), `stages_source`
(`stated` | `from_prose`), `project_declared` (bool), `document_chembl_id`,
`pubmed_id`, `aids`, `licence`, `source`, `source_version`, `retrieved_at`.

### `screen_stages` — one row per assay

`stage_id`, `screen_id`, `stage`, `modality`, `description`,
`target_chembl_id`, `target_type`, `genes` (struct list: `rv_id`, `via`,
`target_type`, `shared_accession`), `assay_condition` (the existing
`_CONDITIONS` classifier), `strain`, `n_tested`, `n_active`, `endpoint`,
`source_*`.

### `screen_results` — one row per compound per stage

`stage_id`, `molecule_chembl_id`, `pubchem_cid`, `outcome`
(`active` | `inactive` | `inconclusive` | NULL), `endpoint`,
`standard_value`, `standard_units`, `standard_relation`, `source_*`.

Roughly 4–5M rows (the 20 non-ChEMBL AIDs over 10,000 tested compounds carry
~4.4M between them), an estimated 60–100 MB of Parquet against today's 19 MB
store. It is a new table and not an extension of `activities`: 276,472 of
those rows are single-concentration `Percent Effect`, and adding them to
`activities` would move `n_compounds`, `best_pchembl` and every potency
roll-up on every gene page.

### Compound identity

PubChem keys on CID, ChEMBL on `molecule_chembl_id`. The bridge is EBI's
UniChem whole-source mapping,
`ftp.ebi.ac.uk/pub/databases/chembl/UniChem/data/wholeSourceMapping/src_id1/src1src22.txt.gz`
(22.8 MB, verified 2026-10-11) — one file, same provider and licence family as
ChEMBL, no per-compound requests. Where UniChem has no mapping the CID stands
alone and the row is still a real result; it simply cannot be reached from a
ChEMBL compound page, which is recorded rather than patched.

**Structures are not stored for the tested sets.** The per-AID CSV carries
`PUBCHEM_EXT_DATASOURCE_SMILES` and sits in `data/raw`, so it stays available,
but a depiction is a rendering and not a fact about the molecule
(`CLAUDE.md`, the RDKit rule). `compounds.parquet` keeps its current meaning.

## The traps

These are the rules that make the layer worth building rather than merely
large.

1. **An outcome call is recorded only where the source states one.** Verified
   contrast: AID 1626 returns 209,843 `Inactive` / 2,044 `Active` / 3,510
   `Inconclusive` — real calls. AID 1671170 (the ChEMBL/Gates TrpRS
   re-deposit) returns 65,646 × `Unspecified`. No cutoff was deposited, so
   `outcome` is NULL on all 65,646 rows and the percent-effect value stands
   alone. A threshold this pipeline picked would be this pipeline's finding,
   not the depositor's.
2. **`n_active = 0` is not a finding of zero hits.** PubChem's summary
   endpoint reports `SIDCountActive: 0` for that same TrpRS deposit, which
   means "no call stated" and reads as "a 65,366-compound screen that found
   nothing". `n_active` is NULL when `outcome_stated` is false, never 0. This
   trap is the reason `outcome_stated` is a stored column and not a derived
   one.

   **And a zero active count is not the only shape it takes**, which an earlier
   draft of this rule missed. Measured: **six of the eight ChEMBL deposits
   report between 1 and 90 actives while `SIDCountUnspecified` equals
   `SIDCountAll`.** So a heuristic reading "any non-zero call count means calls
   were stated" publishes `n_inactive = 0` on six real screens. The signal is
   `SIDCountUnspecified`, used as a veto: if every SID is unspecified, no call
   was stated, whatever the active count says. One consequence to expect —
   Pks13's 25 IC50-row actives give a NULL `n_active` on the campaign row and
   live on `screen_results` instead.
3. **`n_tested` is the deposited set, not the screened library.** AID 1259343
   states ~300,000 compounds screened and deposits 6,225 SIDs. The prose
   figure lives in `library_size_stated`, sourced and separate, and the two
   are never summed, compared or silently substituted.
4. **A campaign reaches a gene two ways, and "reported both" is not one of
   them.** `via = 'target_based'` (a `biochemical_mtb` stage on the gene's own
   `SINGLE PROTEIN` target) or `via = 'chemical_genetic'` (M12). The 251
   documents reporting a protein assay *and* a whole-cell MIC have reported
   both — calling that target deconvolution would invent the resistant-mutant
   experiment nobody deposited.
5. **The complex rule carries over.** A screen filed against `ClpP1P2` is not
   68,611 compounds screened against `clpP1`. `target_type` is on every stage
   row; complex screens are shown and counted separately.
6. **`shared_accession` applies.** 55 loci share an accession, so a stage's
   `genes` is a list and a sibling must not claim another's screen.
7. **A NULL project is not "no follow-up".** AID 1626 is MLSCN-era and has no
   project siblings; its Vero counter-screen exists only in its prose.
   `project_declared` says which, and a campaign with one stage is not a
   campaign that stopped.
8. **`depositor` is recorded per AID, because PubChem's licence is
   per-depositor, not per-database** — NCBI policy explicitly carves PubChem out
   of its public-domain statement.

   **An earlier draft of this trap was false and is worth recording as a
   lesson.** It claimed that "several AIDs above 300,000 compounds are tagged
   Mtb while the assay target is *Bos taurus* MsrA, *S. aureus* NadD or
   *B. subtilis* Sfp", and required inclusion to need the assay's own target or
   description to name Mtb. Measured against the live search, both halves are
   wrong: those AIDs (651718, 602163, 602399, 1490) **are not in
   `txid1773[ORGN]` at all**, so the hazard does not exist in this query — and
   the extra name test *rejects 8 of the 28 real Mtb AIDs*, including the
   65,366-compound TrpRS screen, whose title ("Biochemical assay for Mt-TrpRS")
   names neither tuberculosis nor mycobacterium. The taxonomy search is the
   filter. The claim came from a literature survey and was written into this
   spec without being checked against the endpoint.
9. **Stage labels state their provenance.** `stages_source = 'stated'` where
   PubChem gives `Assay Type` and project roles; `'from_prose'` where they are
   classified from the depositor's description, the same standing as
   `assay_condition`. The description is kept so the reader can check.
10. **Public TB chemistry is almost unreplicated**, and the layer should make
    that visible rather than imply a consensus: 105,833 of the 107,463
    distinct whole-cell compounds appear in exactly one document.
11. **A ratio ChEMBL computed is not a measurement.** ChEMBL files selectivity
    indices, therapeutic indices and resistance ratios as activity rows —
    6,577 compounds in these documents carry one. They are arithmetic over two
    other rows, so they are labelled `derived` and never counted as a
    cytotoxicity or potency measurement. Counting them inflated the
    cytotoxicity coverage by ~250 compounds before they were excluded.
12. **Anticancer is not a cytotoxicity counter-screen.** The same molecules are
    screened against cancer lines in papers that also report MICs. Both are
    mammalian-cell readings and both are kept, but `modality` records the
    assay's own target and the description travels with it, so an
    antiproliferative assay on RKO cells is not presented as a selectivity
    control.

## Reproducible source definition

PubChem, `db=pcassay` via E-utilities, verified 2026-10-11:

| term | AIDs |
|---|---|
| `txid1773[ORGN]` | 12,519 |
| `txid1773[ORGN] NOT ChEMBL[SNME]` | 172 |
| `txid1773[ORGN] AND 10000:100000000[TSC]` | 28 |

Of those 28, twenty are non-ChEMBL deposits (Scripps, Broad, Southern
Research, ICCB-Longwood/NSRB, SRMLSC, PCMD, UW-Madison) and eight are the
ChEMBL/Gates re-deposits. Per-AID data comes from
`pubchem.ncbi.nlm.nih.gov/assay/pcget.cgi?query=download&record_type=datatable&actvty=all&response_type=save&aid=N`
— verified uncapped (AID 1626: 215,397 rows, 30 MB; AID 1671170: 65,646 rows,
7.5 MB). **Not** PUG-REST, which refuses above 10,000 SIDs
(`PUGREST.BadRequest: Too many SIDs`). One file plus one `.meta.json` per AID,
as `fetch.py` already does.

## The pages

The nav becomes the pipeline, early to late:

```
[ Genome ]   [ Screens ]   [ Hit profiling ]   [ Drugs & trials ]
   4,031        ~200            17,763            112 / 1,137
   genes      campaigns        compounds         drugs / trials

 target selection ──▶ screening ──▶ hit assessment ──▶ the clinic
```

### Screens

A third view beside Genome and Drugs & trials, following the two-state rule
from the genome view: the campaign table takes the full width until a campaign
is opened, then keeps the scanning columns while the detail panel takes the
rest. Prose caps at 78ch; `tabular-nums` stays.

- **Campaign table** — depositor, year, library, modality, condition, strain,
  tested, actives (or "no call stated"), stages reached.
- **Campaign detail** — the stage ladder in funnel order, each with its
  counts and its own description; the actives with structures (from
  `compounds` where UniChem bridges them); the genes it legitimately reaches.
- **Gene page panel** — "Screened in": target-based campaigns on this
  protein, their library sizes, and the stated actives. For most of the 4,031
  genes this panel is empty, and that is the answer.
- **Compound page panel** — "Tested in": every campaign that tested this
  molecule, with the outcome. This is where a zero becomes provable — "tested
  in AID 1626 (215,098 compounds of the MLSMR library), inactive".

  **The unit matters and this sentence had it wrong.** AID 1626's `SIDCountAll`
  is 215,397, but a SID is a depositor's *sample*, not a compound: the same
  summary gives `CIDCountAll` as 215,098, and the UniChem bridge is keyed on
  CID. The depositor's own prose says 216,163 compounds were screened, which is
  a third number and belongs in `library_size_stated`. So: 216,163 claimed
  screened, 215,397 samples deposited, 215,098 distinct compounds. Any string
  shown to a reader uses compounds and says so.

### Hit profiling

One row per compound, columns for what was measured: MIC, cytotoxicity, ADME,
animal efficacy, Mtb protein, year, how many papers. The rail filters on which
tiers exist rather than on values. The ADME cell shows *how many* of
{microsomes, solubility, permeability, PK} were measured — a count of
measurements, not a grade — and an unmeasured tier reads `—`, never 0.

The view's own copy carries the rule: 20,000 compounds have a MIC and nothing
else, and that is the answer. Sorting is allowed on any column because a
reader may want the most-profiled compounds first; no column is combined with
another, because that would be the score this layer refuses to compute.

`target_summary` gains `n_target_screens`, `max_screen_compounds`,
`n_screen_actives` (NULL where no calls are stated), `n_complex_screens` and
`latest_screen_year`. The canvas rings gain a screening stage between chemical
matter and the clinic.

The agent's schema dump gains this layer's traps, since that is the only
surface where a wrong join is silent: `screen_results` is keyed on
`stage_id` and not `screen_id`; `outcome` NULL is not inactive; `n_active`
NULL is not zero; a complex stage is not the subunit's screen; `n_tested` is
not `library_size_stated`.

## M12: PROSPECT

figshare `10.6084/m9.figshare.28373561`, licence **CC0** (verified via the
figshare API), 26 files. The call-level data is small — the 352 MB
`sGR_reference_set…` archive holds the full dose–response, but
`max_dose_min_gr_archive.tar.gz` is **63 KB** and
`any_dose_min_gr_archive.tar.gz` 0.31 MB. Inspected: 1,141
compound-concentration instances, 611 distinct compounds, 253 strains, 880
active by the authors' own cutoff (min GR ≤ 0.3, stated in the file's README —
so rule 1 is satisfied by the source).

Two traps already visible:

- **`strain_id` is a mixed key.** Mostly Rv tags (`Rv0023`, `Rv0204c`), some
  gene symbols (`trpG`, `ppk1`), and 7 wild-type controls (`H37RvBC06`…) that
  are not genes. Symbol-keyed rows need the same care as `resistance`.
- **Compound ids are `BRD-` (967 rows) and `TCMDC-` (173).** The TCMDC series
  is GSK TCAMS, for which ChEMBL-NTD set 9 carries a CC0 mapping; `BRD-` ids
  have no public ChEMBL bridge, so most PROSPECT compounds will not reach a
  `compounds` row, and that is reported rather than bridged by structure
  guessing.

A PROSPECT link is a **candidate** gene from profile similarity, never a
mechanism, and `CLAUDE.md`'s rule that a drug acts on a gene only when a
source names that gene's protein is not relaxed by it.

## Costs

`data/raw` grows from 384 MB to roughly 900 MB (20 large AID CSVs, UniChem's
22.8 MB, and ~90 MB of document-level ChEMBL activity JSON); `data/store`
from 19 MB to roughly 100 MB. `screen_results` is ~4.4M rows from PubChem and
~300k from the ChEMBL literature. Cold `make
build` grows by the AID downloads, which cache like everything else. No new
runtime dependency: CSV, gzip and DuckDB cover it. `atlas check` gains a
PubChem probe (an AID's `SIDCountAll` is cheap) and the ingesters follow the
existing `fetch_raw` → `normalize` → `build` shape.

## Open questions

1. **Which AIDs beyond the 28.** The 172 non-ChEMBL taxonomy-tagged AIDs
   include BindingDB re-postings of PDB affinities, which are not screens. A
   size floor is one answer and `Assay Type = Screening` is another; the
   spec's inclusion rule (the assay's own target or description names Mtb)
   decides membership but not the floor.
2. **Whether `max_assay_compounds` survives M11** or is replaced by
   `max_screen_compounds`. Two columns measuring one thing from two tables is
   the kind of duplication that rots; the fix keeps the existing column so the
   correction can land first, and M11 should probably retire it.
3. **`folC`/PAS is still open** and untouched by this layer.
