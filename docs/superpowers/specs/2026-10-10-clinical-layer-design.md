# M6: from target to clinic — design

> Written before implementation. The counts below are what was measured at
> design time; `docs/data-sources.md` carries the current ones.

Written 2026-10-10 for an autonomous overnight run. The request was:

> enhance the atlas so that it has all information of TB for early drug
> discovery projects, going up to clinical trials. This should be one stop
> place to query any info.

The user said to work autonomously and report in the morning, so this
document records the decisions made without them. They are the ones to
review.

## Understanding

**Said:** cover the path from target to clinical trials; one place to query.

**Assumed:**

- "All information" means *all the public evidence the atlas can source
  honestly*. `CLAUDE.md` still outranks completeness: public data only, every
  source in `docs/data-sources.md` with its licence, and an absent record stays
  an absent record.
- The missing stretch is the clinical end. The atlas already covers target
  biology and chemical matter. It knows nothing about which drugs or clinical
  candidates act on a gene, or which trials test them.
- "Query any info" is served by the agent (the Ask panel) and the API, so
  every new table must be in the agent's schema with its traps written down.

**Success:** the gene pages for DprE1, InhA and MmpL3 name the clinical
candidates that act on them, each with its phase and trials and the source of
the link. A drug page goes back the other way, to genes, resistance and
trials. And the agent can answer "which essential, vulnerable targets have no
clinical-stage drug?" with one join.

## Sources (verified live 2026-10-10)

| Source | What | Licence |
|---|---|---|
| ChEMBL `drug_indication` | 187 TB indications (MeSH heading contains "Tuberculosis") over 112 parent molecules, each with `max_phase_for_ind` and refs (316 ClinicalTrials refs, DailyMed, FDA, EMA, ATC) | CC BY-SA 3.0 (already registered) |
| ChEMBL `mechanism` + `target` | 94 mechanisms over 49 targets, with organism, type and component accessions | CC BY-SA 3.0 |
| ClinicalTrials.gov API v2 | 1,152 interventional studies for condition "tuberculosis"; `dataTimestamp` from `/api/v2/version` | US Government database; terms require attribution, the processing date, current data, and a statement of modifications |

Rejected again: newtbdrugs.org (all rights reserved; see data-sources.md).

## Evidence rules for the clinical layer

1. **TB phase is not overall phase.** `drugs.max_phase_tb` is the highest
   phase ChEMBL records for a tuberculosis indication. `max_phase` is for any
   indication. Moxifloxacin is approved, but for TB it is phase 3.
2. **The drug set is whatever ChEMBL says, not a curated list.** ChEMBL takes
   indications from trial records, so the 112 include host-directed adjuncts
   (glucocorticoids, NSAIDs, statins), HIV co-medications, BCG, and placebo
   excipients ("lactose, anhydrous" at phase 3). They are kept, not edited out.
   Three columns make them filterable: `acts_on_mtb`, `host_targeted` and
   `atc_codes`.
3. **A drug reaches a gene four ways, and they are not interchangeable**
   (`drug_genes.link`):
   - `mechanism`: ChEMBL names this gene's protein as the single-protein
     target.
   - `mechanism_complex`: ChEMBL names a complex this protein belongs to.
     Bedaquiline is filed against the whole ATP synthase and sutezolid against
     the 70S ribosome. Each subunit gets a link, labelled as a complex member
     with the complex size. That is not evidence the drug binds that subunit.
   - `bosch_2021`: the CRISPRi paper's own `antibacterial` annotation, matched
     exactly to a ChEMBL synonym (SQ109 to mmpL3, PBTZ169 to dprE1, Q203 to
     qcrB). Class names ("fluoroquinolones") match nothing and stay as text.
   - `who_resistance`: the WHO catalogue grades variants in this gene as
     associated with resistance to this drug. **Resistance is not
     engagement.** katG activates isoniazid, and Rv0678 is a regulator.

   The roll-up counts `mechanism` and `bosch_2021` as "drugs acting on this
   gene". Complex membership and resistance are shown, not counted.
4. **Non-Mtb mechanism targets get no Mtb gene.** Rifampicin's ChEMBL target
   is a generic *Bacterial* RNA polymerase built from *E. coli* accessions, and
   the fluoroquinolones point at *S. pneumoniae* gyrase. Bridging them to rpoB
   or gyrA by homology would invent a statement ChEMBL does not make. rpoB
   still reaches rifampicin through the WHO catalogue, labelled as resistance.
5. **A trial reaches a drug two ways** (`trial_drugs`). `via_chembl_ref` means
   ChEMBL's own curated NCT reference. `via_intervention_name` means an exact
   match of a cleaned intervention name to a ChEMBL synonym of a TB molecule.
   Cleaning splits combinations, takes parentheticals as alternatives, and
   strips doses. Measured on live data: 259 trials by ref, 335 by name, 175 by
   both, one disagreement. A name that matches two molecules links neither.
6. **Trials are interventional studies for the condition "tuberculosis".**
   That includes vaccine, diagnostic and behavioural studies. Most of those
   link to no drug, which is correct.

## Store

| Table | Key | From |
|---|---|---|
| `drugs` | `molecule_chembl_id` (parent) | ChEMBL |
| `drug_mechanisms` | `molecule_chembl_id`, `target_chembl_id` | ChEMBL |
| `trials` | `nct_id` | ClinicalTrials.gov |
| `drug_genes` | `molecule_chembl_id`, `rv_id`, `link` | joined: drug_mechanisms + crosswalk, vulnerability, resistance |
| `trial_drugs` | `nct_id`, `molecule_chembl_id` | joined: drugs refs + trials interventions |

The new `target_summary` columns are `n_drugs`, `best_drug_phase`,
`drug_names`, `n_complex_drugs`, `n_trials` and `has_clinical_drug`.

Pipeline: identity, then evidence, then **clinical** (ChEMBL drugs,
ClinicalTrials.gov, links), then summary. `atlas clinical` rebuilds just this
stage.

## Surfaces

- **API:** `/drugs`, `/drugs/{id}`, `/trials`, `/trials/{nct_id}`. Target
  detail gains `drugs` and `trials`; `/targets` gains `has_clinical_drug` and
  `min_drug_phase`.
- **App:** a Clinical tab on the gene page, and a "Drugs & trials" view beside
  the genome, with drug and trial detail. Gene chips there jump back to the
  genome.
- **Agent:** the five tables with their traps, and the rules above in the
  system prompt. The stale homology note (UniRef) is fixed while in there.

## Later increments (next loop ticks)

1. UniProt function, subcellular location, transmembrane segments, pathway and
   catalytic activity on the gene page. Same CC BY 4.0 stream, a few more
   fields.
2. Search across genes, drugs, trials and compounds from one box.
3. Literature volume per gene from Europe PMC, with the query shown, as a
   novelty signal.
4. Whole-cell actives as a compound-centric table, never attached to a gene
   without a protein-level link.

Deferred, with reasons, to the morning report: druggability (still no
source), MtbTnDB conditional essentiality (no licence), and a homology bridge
for non-Mtb mechanism targets (it would invent claims).

## Testing

Fixtures are real slices of the live payloads. They cover isoniazid (single
protein), bedaquiline (complex plus Bosch on atpE), macozinone (DprE1), SQ109
(no ChEMBL mechanism; Bosch only), rifampicin (non-Mtb target; WHO rpoB),
delamanid (organism-level target), dexamethasone and its phosphate (host
target, ambiguous synonym), and a salt-to-parent indication. The ClinicalTrials
slice covers a combination regimen, parenthetical abbreviations, the one
disagreement, a vaccine and a placebo arm. The tests pin the link levels, the
name-matching rules, the roll-up counts and the agent's schema notes.
