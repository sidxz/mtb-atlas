"""Natural-language questions over the store, answered with cited records.

The agent gets two tools: the store's schema, and read-only SQL against it. One
query tool beats ten narrow ones here, because the questions a target biologist
asks are joins -- "essential, structure, no ligands, no human homolog, not in
the WHO catalogue" is one WHERE clause and would otherwise be five endpoints.

**Why the SQL tool is safe.** The tables are copied into an in-memory DuckDB at
startup, then `enable_external_access` is turned off and the configuration
locked, so no statement can read a file, attach a database or reach the
network. On top of that DuckDB's own parser must find exactly one SELECT, every
result is capped and every query is timed out. The store is public data and
read-only either way.

The system prompt carries the same rules as the rest of the codebase, because
an agent that quietly treats a missing row as a zero is worse than no agent:
absences are answers, evidence levels are not interchangeable, and every claim
names the records it came from.
"""

from __future__ import annotations

import atexit
import json
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any

import duckdb

from .store import STORE, provenance

MODEL = "claude-haiku-5-5"
MAX_ROWS = 200
MAX_TURNS = 12
QUERY_SECONDS = 30
# The sandbox's ceiling, data and query state together, so a long-lived API worker cannot
# grow with the store or with one expensive question; see the note on `screen_results` below.
# A query that cannot fit even with spilling fails as a tool error, which the model sees.
MEMORY_LIMIT = "512MB"
# DuckDB's default disk ceiling for spill is 90% of the free disk.
SPILL_LIMIT = "8GB"
# Working memory is per thread: on all 18 cores the API's /hits profile could not build in
# 448 MB, and on 4 it builds in 256. The same holds for a model's aggregate here.
THREADS = 4

# What to say when the loop ends on anything but a finished answer.
STOPPED = {
    "tool_use": f"No final answer: the agent used all {MAX_TURNS} turns.",
    "max_tokens": "Cut off at the length limit; what follows is incomplete.",
    "refusal": "The model declined to answer this question.",
}

TABLES = (
    "target_summary",
    "crosswalk",
    "genes",
    "proteins",
    "structures",
    "predicted_structures",
    "activities",
    "compounds",
    "compound_structures",
    "assay_sizes",
    "essentiality",
    "conditional_fitness",
    "conditional_tnseq",
    "tnseq_screens",
    "resistance",
    "vulnerability",
    "strain_vulnerability",
    "interactions",
    "homology",
    "paralogs",
    "orthologue_structures",
    "drug_precedent",
    "chembl_targets",
    "ligands",
    "screens",
    "screen_stages",
    # The one big table: millions of rows, and `connection()` copies every name here into
    # the in-memory DuckDB. Unbounded, that copy held the process at 1.98 GB resident
    # (2026-10-11, 5,422,604 rows, with `compound_structures` in). It is bounded by
    # MEMORY_LIMIT instead, past which DuckDB moves blocks to spill files. Measured on the
    # rebuilt store: 0.64 GB after `connection()`, which takes 1.4 s rather than 0.4 s, and
    # 0.69 GB at peak under a 5.4M-row self-join that answers in 0.7 s. The copy is
    # deliberate and a view cannot replace it: `CREATE VIEW ... AS SELECT * FROM
    # '<parquet>'` reads its file at query time, after `enable_external_access` is off and
    # the configuration locked, and DuckDB 1.5.6 refuses it ("file system operations are
    # disabled by configuration"). Spilling is DuckDB's own buffer manager, not a file the
    # SQL names, so the lock does not stop it.
    "screen_results",
    "drugs",
    "drug_mechanisms",
    "drug_genes",
    "trials",
    "trial_drugs",
)

# One line per table: what a question should reach for, and the trap in it.
TABLE_NOTES = {
    "target_summary": "START HERE. One row per gene, every evidence table rolled up. "
    "Scalar columns for filtering and sorting. `n_protein_assays` is how many published "
    "ChEMBL assays run against this gene's own protein -- whether the target can be "
    "screened at all, which is a different question from `n_compounds` (whether anyone "
    "has hit it). `max_assay_compounds` is the largest single published assay by distinct "
    "compounds, which separates one real screening campaign from a dozen small follow-ups: "
    "genome-wide six genes reach 1,000 (dfp 66,942, pks13 66,592, trpS 65,366, aspS 8,841, "
    "dnaB 2,123, recA 2,118). `hn878_*` compares vulnerability against a "
    "clinical isolate; see strain_vulnerability for the sign convention. "
    "**`n_pdb` counts structures of this gene's OWN protein; a borrowed one is in "
    "`n_orthologue_pdb` and does NOT make `has_structure` or `structural_gap` true.** "
    "3,146 CDS genes have no structure of their own and 449 of those have a mycobacterial "
    "neighbour that does. `same_sequence_structure` is the stronger case: an identical "
    "sequence deposited under another accession, true for 34 of them. "
    "`n_precedent_approved` counts approved drugs filed against ANOTHER protein sharing one "
    "of this gene's Pfam domains -- precedent that the fold can be bound, **not a "
    "druggability score and not a drug that acts on this gene** (that is `n_drugs`). It is "
    "NULL where UniProt annotates no domain, which is not zero. Always report "
    "`precedent_pfam_name` and `precedent_domain_genes` with it. "
    "`close_paralog` is whether a full-length second copy exists -- see the paralogs table "
    "for why it is stricter than `close_human_homolog`. `closest_paralog_gene` is NULL when "
    "there is no backup, while `nearest_relative_gene` is usually populated anyway, so "
    "reading the latter as redundancy is the trap. "
    "**For whole-cell potency use `best_pmic` / `median_pmic`, not "
    "`best_whole_cell_pchembl`** -- the latter is ChEMBL's pchembl_value, which exists for "
    "only 12 genes because it is NULL on every MIC; the pmic columns cover 71. `n_mic` "
    "counts exact MICs and `n_mic_censored` the '>' non-results, which are evidence of "
    "no activity rather than absence of testing. `whole_cell_conditions` is a list of "
    "structs (condition, n, n_with_pmic, best_pmic) -- UNNEST it to ask what conditions a "
    "gene's chemistry was measured under, remembering that `unspecified` means the deposit "
    "did not say, not standard media. "
    "**The screen columns count CAMPAIGNS (the `screens` table), ChEMBL papers and PubChem "
    "deposits alike.** `n_target_screens` is campaigns that screened this gene's OWN protein: "
    "a ChEMBL stage on a direct SINGLE PROTEIN target, or a PubChem deposit naming one "
    "protein among those that reach a locus. A target that reaches no locus is dropped from "
    "that count, so a deposit naming this protein beside a different one the crosswalk "
    "cannot place still reads as this gene's own screen -- check `screens.targets`. "
    "`n_complex_screens` is campaigns of a complex or of several proteins that include it: "
    "shown, never counted, so a ClpP subunit reads 0 own screens beside the pair's. Both are "
    "NULL if the screening layer was never built; built, 0 means no campaign in that table "
    "(PubChem deposits of 10,000+ SIDs, ChEMBL papers reachable from `activities`; see "
    "`screens` for what that leaves out), not that nobody screened it. **`n_screen_actives` "
    "sums `n_active` over only the screens "
    "that stated a countable call, and `n_target_screens` is the denominator for neither**: "
    "none is read from ChEMBL, and a campaign of several assays carries no campaign-level count, "
    "so one PubChem deposit stating 120 actives beside one ChEMBL paper reads 120 actives "
    "with `n_target_screens` = 2. NULL means no own screen stated a count; 0 means calls were "
    "stated and none was active. `max_screen_compounds` is the largest single `n_tested` of "
    "an own screen -- SIDs for a PubChem campaign (a project's distinct union), one assay's "
    "compounds for ChEMBL -- so it is not one quantity across sources; it is NULL for a gene "
    "with no own screen where `max_assay_compounds` reads 0. **`latest_screen_year` sees only "
    "dated screens**: PubChem deposits carry no year, so a gene whose newest screen is a "
    "deposit reads the year of its newest ChEMBL paper. `n_target_screens` takes the stage's "
    "own `target_type` where `n_protein_assays` takes the crosswalk's, which is NULL for a "
    "target reached only through a UniProt cross-reference, so the two can disagree on one "
    "gene; the stage's is the better evidence.",
    "crosswalk": "Identity only: Rv tag to accession, with source disagreements and "
    "the loci that share an accession.",
    "proteins": "One UniProt entry per accession, keyed on uniprot_acc: cross-references "
    "plus curated biology -- `function`, `locations`, `n_transmembrane`, `pathways`, "
    "`reactions` and `rhea_ids`, `cofactors`, GO term names (`go_process`, `go_function`, "
    "`go_component`), `disruption_phenotype`, and `pubmed_ids` / `n_references` (papers "
    "UniProt cites, a curated subset of the literature). NULL or empty means UniProt says "
    "nothing, which is not a negative finding: 0 transmembrane segments is 'none "
    "annotated', not 'soluble'.",
    "structures": "One row per (pdb_id, uniprot_acc). Join on uniprot_acc, NOT rv_id. "
    "`ligand_ids` excludes cofactors and crystallisation additives. `expression_hosts`, "
    "`plasmids`, `construct_length` and `mutations` are how the protein was PRODUCED, as "
    "the deposition states it -- the only answer in the store to 'has anyone made this "
    "protein, and from what'. An empty list means the entry does not say (1,649 of 4,803 "
    "rows name a plasmid), never that it was not expressed. Host strings are depositor "
    "text and inconsistent in case and strain naming, so group them with care: "
    "'Escherichia coli BL21(DE3)' and 'ESCHERICHIA COLI BL21(DE3)' are the same host. "
    "`mutations` is empty for a wild-type construct; a non-empty one means the sequence "
    "crystallised is not the wild-type protein.",
    "predicted_structures": "AlphaFold, keyed on uniprot_acc.",
    "activities": "ChEMBL bioactivity. `evidence` is direct | orthologue | whole_cell. "
    "Join to a gene through crosswalk.chembl_targets or target_summary. `assay_type` is "
    "ChEMBL's own: B binding, F functional, A ADME. **Do NOT read assay_type as 'protein "
    "assay'** -- every whole_cell row is F, because ChEMBL files MIC screens as functional "
    "assays against the organism. A published assay for a gene's own protein means "
    "`evidence = 'direct'`; count DISTINCT assay_chembl_id, since one assay can carry "
    "hundreds of measurements. `target_summary.n_protein_assays` is that count already "
    "done. **Potency lives in two different columns and they do not overlap.** "
    "`pchembl_value` is ChEMBL's own and is NULL on every one of the 3,870 MIC rows, "
    "because ChEMBL computes it for affinity endpoints only -- so `max(pchembl_value)` "
    "over whole_cell rows answers from 78 IC50/EC50 measurements and silently ignores "
    "every MIC. `pmic` is -log10(MIC in mol/L), computed in the ingester, and is the "
    "number to use for whole-cell potency; `pmic_basis` says which unit conversion "
    "produced it. No row has both. **A censored MIC gets no pmic**: `standard_relation` "
    "'>' means the compound did not inhibit at the highest concentration tested, so "
    "those rows are NULL on purpose and counting them as untested is wrong -- they are "
    "a measured non-result. `assay_condition` (whole_cell rows only) is the growth "
    "condition read from the assay prose: caseum | intracellular | non_replicating | "
    "alt_carbon | nutrient_stress | standard_media | unspecified. **`unspecified` is not "
    "`standard_media`** -- it means the deposit never stated a medium, which is most of "
    "them, and no condition matches `caseum` in this release at all. `resistant_panel` "
    "is a separate flag for strain, not medium (MDR or clinical isolates), so a row can "
    "be both.",
    "compounds": "One row per compound, with properties. Keyed on molecule_chembl_id.",
    "compound_structures": "A structure (SMILES, InChIKey) for every ChEMBL compound the "
    "store references -- the screened set and the potency set -- from ChEMBL's release-wide "
    "structure file. Join on molecule_chembl_id. **Three states, and two of them look alike "
    "after a LEFT JOIN.** `has_structure` true: a SMILES is here. `has_structure` false: "
    "looked up, and the id is not in this release's structure file (a molecule with no "
    "structure, or an id outside the release) -- not a claim that the molecule has none. No "
    "row: never looked up, which a LEFT JOIN shows as has_structure IS NULL, never as false; "
    "every PubChem-only compound (a CID with no molecule_chembl_id) is one, so it cannot be "
    "drawn from here and was not checked. A structure is a drawing input and not evidence: it "
    "says nothing about what a compound did. `compounds.smiles` agrees with this table for "
    "every compound in the potency set.",
    "assay_sizes": "Per-assay census keyed on (target_chembl_id, assay_chembl_id): reach a gene "
    "by unnesting `crosswalk.chembl_targets` and matching `target_id`, never rv_id, and keep "
    "only entries with `evidence` = `direct`, since an `orthologue` entry is a relative's "
    "protein. `n_compounds` counts distinct compounds and `n_measurements` counts rows, so a "
    "re-run is not a second assay. It sizes an assay and never measures potency: `activities` "
    "is the potency table.",
    "essentiality": "TnSeq calls, one in vitro condition. `essential` is ES or ESD; "
    "`fitness_cost` also includes growth-defect.",
    "conditional_fitness": "Griffin 2011 TnSeq, cholesterol vs glycerol, one row per gene. "
    "`log2_ratio` NEGATIVE means depleted on cholesterol. `cholesterol_required` is the "
    "authors' own call (96 genes), not a threshold. **`measured` is false for every gene "
    "that tolerates no transposon insertions, which is every in-vitro-essential gene** -- "
    "dprE1, inhA and mmpL3 are all unmeasured here, which is NOT the same as unaffected. "
    "A gene absent from this table was never screened.",
    "conditional_tnseq": "MtbTnDB: TRANSIT resampling over 136 screens, one row per gene per "
    "screen, keyed on (rv_id, screen_id). What each screen WAS is in `tnseq_screens` -- join "
    "it on `screen_id`, this table holds only numbers. `log2fc` NEGATIVE means depleted in "
    "the experimental condition. **Two traps.** (1) `measured` is false where the gene took "
    "no insertions in either condition -- TRANSIT still prints `log2fc` 0.00 and `q_value` "
    "1.0 for those, so filtering on q alone reads 13% of the genome as 'no effect'; always "
    "add `measured`. (2) A value here does NOT mean a fitness effect for an essential gene: "
    "TRANSIT counts TA sites over the whole ORF while Griffin counted 5-80%, so dprE1 and "
    "mmpL3 carry fold changes built on non-disruptive terminal insertions and read `n/a` in "
    "`conditional_fitness`. Join `essentiality` and show the call beside any `log2fc`.",
    "tnseq_screens": "One row per screen in `conditional_tnseq`, keyed on `screen_id`: what "
    "was compared to what, and the authors' own description of the condition "
    "(`condition_class` in_vitro/in_vivo/in_cell, `medium`, `carbon_source`, `stress`, "
    "`mouse_strain`). **27 of the screens are genetic-interaction backgrounds, not "
    "conditions** -- a transposon library in a knockout host, so a hit is an interaction with "
    "that gene and NOT a conditional requirement. Both `interaction_gene` (Rv id) and "
    "`interaction_gene_name` are sparse and sparse independently -- 11 have only the id, 5 "
    "only the name -- so test `COALESCE` of the two or read `description`; filtering on one "
    "field alone silently keeps interaction screens in a condition query. **`annotated` is false "
    "for 72 of the 136**, where the authors' table names the screen differently and the atlas "
    "will not guess: a NULL `condition_class` means NOT RECORDED, never 'in vitro'. "
    "**SCREENS ARE NOT INDEPENDENT -- never count them as evidence weight.** Group by "
    "`study`: 61 of the 136 are single mouse strains from one host-genetics panel, and the "
    "1,833 strain-against-strain comparisons in the source are deliberately not ingested. "
    "`cross_study` means the control library came from a different study than the "
    "experimental data, a batch-effect caveat the authors raise themselves.",
    "vulnerability": "CRISPRi in H37Rv, the lab strain.`vulnerability_index` is NEGATIVE: "
    "more negative is more vulnerable. Only rows with `certain` are confident estimates.",
    "strain_vulnerability": "The SAME CRISPRi series in HN878, a Beijing-lineage CLINICAL "
    "isolate, one row per gene. H37Rv is not in here -- it is in `vulnerability`, so a "
    "strain comparison is a join on rv_id. `delta_vi` is the authors' own and runs HN878 "
    "MINUS H37Rv, so POSITIVE means LESS vulnerable in the clinical strain (accD6: -11.5 "
    "in H37Rv, -2.3 in HN878, delta +9.2, confident in both). `delta_vi_norm` is not a "
    "rescaling and can disagree in sign with `delta_vi`. The delta is reported for only "
    "507 genes, a subset the authors chose of the 576 confident in both; NULL there means "
    "no difference was reported, NOT a difference of zero, and "
    "`differential_reported` says which. A gene absent from this table was never measured "
    "in HN878. M. smegmatis is in the same supplement and deliberately NOT ingested.",
    "resistance": "WHO catalogue, keyed on GENE SYMBOL not Rv tag, and only 65 genes "
    "are in it. `associated` marks graded 1 or 2. `residue_position` is null "
    "for promoter, frameshift and stop variants. `drug` uses WHO's names, which are NOT "
    "ChEMBL's (Rifampicin vs RIFAMPIN, Levofloxacin vs LEVOFLOXACIN ANHYDROUS), so join a "
    "drug to a gene through drug_genes WHERE link = 'who_resistance', never on the name.",
    "interactions": "STRING, combined_score >= 700, one row per unordered pair. "
    "A gene appears as rv_id OR partner_rv_id -- check both.",
    "homology": "Human anti-target check: phmmer of each Mtb protein against the reviewed "
    "human proteome, keyed on uniprot_acc. `identity` is a FRACTION (0.48 = 48%); "
    "`close_human_homolog` means identity >= 0.30, a convention of this atlas.",
    "paralogs": "Functional redundancy: phmmer of each Mtb protein against the Mtb "
    "proteome itself, keyed on uniprot_acc. Answers 'could a second copy cover for this "
    "target', which no other table does. **The `close_paralog` flag needs identity >= 0.30 "
    "AND coverage >= 0.70, deliberately stricter than `close_human_homolog`, which flags "
    "on identity alone.** The questions differ: a shared domain is already a selectivity "
    "worry for an off-target, but a backup copy has to be the same protein, not share a "
    "piece of it. Identity alone would call 2,009 genes redundant including dprE1 (30.8% "
    "over 37% of the protein) and mmpL3 (31.7% over 21%), neither of which has a backup. "
    "**Two different 'closest' columns.** `closest_close_gene` is the nearest BACKUP and is "
    "NULL when there is none, even though relatives exist; `closest_gene` is the nearest "
    "RELATIVE, ranked by bitscore rather than identity so that a short exact fragment does "
    "not outrank a full-length near-copy. Self-hits are dropped, and so are pairs of loci "
    "filing the identical sequence under two accessions -- those are in "
    "crosswalk.shared_accession and are identity collapse, not paralogy. `identity` and "
    "`coverage` are FRACTIONS.",
    "orthologue_structures": "A structure to work from that is NOT of this protein: phmmer "
    "of each Mtb protein against the 895 Mycobacteriaceae proteins (excluding H37Rv) that "
    "have a PDB entry, joined to those entries. **Keyed on uniprot_acc for the Mtb side and "
    "via_acc for the neighbour; one row per (Mtb protein, neighbour's PDB entry), so count "
    "DISTINCT pdb_id, not rows.** These entries are NOT in the `structures` table and must "
    "never be added to `n_pdb`: that column answers 'has this protein been solved' and a "
    "borrowed structure does not make it true. **`relation` carries two claims of very "
    "different strength.** `same_sequence` means the deposited sequence is identical to the "
    "Mtb one and merely filed under another accession (CDC 1551, H37Ra, M. bovis) -- the "
    "structure IS of this protein, and 34 genes the atlas calls structure-less have one. "
    "`orthologue` means a related mycobacterial protein, mostly M. smegmatis, down to the "
    "floor of 30% identity over 70% of the query. `identity` and `coverage` are FRACTIONS "
    "and belong in any answer: whether a 34%-identical structure is useful is the reader's "
    "judgement, and this table makes no modelling claim. `n_ligands` counts only ligands on "
    "the neighbour's own chains, the same chain-level rule as `structures`.",
    "drug_precedent": "Has a drug ever been filed against this FOLD? Every ChEMBL "
    "drug-target mechanism, keyed on the Pfam domain of the protein it acts on, restricted "
    "to the 325 domains Mtb proteins carry. **There is no rv_id: join through "
    "proteins.pfam_ids** -- `FROM proteins p, UNNEST(p.pfam_ids) AS d(pfam_id) JOIN "
    "drug_precedent USING (pfam_id)` -- and **exclude rows where `accession` is the gene's "
    "own accession**, or a gene becomes its own precedent (dprE1's only PF04030 compounds "
    "are macozinone and TBA-7371, against dprE1). `target_summary.n_precedent_approved` is "
    "that roll-up already done. **This is NOT a druggability score and nothing in the store "
    "is** -- it counts database records, not pockets. `max_phase` is 4 for approved, 1-3 "
    "clinical, -1 means ChEMBL does not know (neither approved nor clinical). "
    "**A shared domain is not a shared binding site**, so an answer needs the domain name "
    "and how broadly it is shared: `target_summary.precedent_domain_genes` is how many Mtb "
    "genes carry it (37 for PF00005 ABC transporter, 1 for the median domain). 39% of rows "
    "are human targets (tax_id 9606), where tractable chemistry and a selectivity problem "
    "are the same fact -- `n_precedent_human_target` counts those. One row per (pfam_id, "
    "mec_id, accession), so count DISTINCT molecule_chembl_id, not rows.",
    "drugs": "One row per ChEMBL parent molecule with a TUBERCULOSIS indication. "
    "`pref_name` is UPPER CASE ('ISONIAZID'), so match case-insensitively. "
    "`max_phase_tb` is the highest phase for TB; `max_phase` is for ANY indication, so an "
    "approved antibiotic can be phase 2 for TB. The set is ChEMBL's, unedited: it includes "
    "host-directed adjuncts, HIV co-medications, vaccines and placebo excipients -- filter "
    "on `acts_on_mtb`, `host_targeted` or `atc_codes` (J04 = antimycobacterials).",
    "drug_mechanisms": "ChEMBL mechanism of action per drug. `target_organism` is often NOT "
    "Mtb (rifampicin's target is a generic bacterial RNA polymerase built from E. coli "
    "proteins). Gene links are in drug_genes.",
    "ligands": "One row per PDB chemical component id (the three-character codes in "
    "structures.ligand_ids), with the InChIKey and RCSB's ChEMBL cross-reference that "
    "identify the same molecule in `compounds` or `drugs`. `role` is ligand | cofactor | "
    "incidental, the same rule the structures table uses.",
    "screens": "One row per screening CAMPAIGN, keyed on screen_id: `pubchem:1626` (one "
    "deposit), `pubchem:project:435019` (a project the depositor declared: ONE row for all "
    "its member AIDs, named for the lowest member by integer, so 435019 and not 449762) or "
    "`chembl:CHEMBL...` (a paper). **This table holds the campaigns the atlas INGESTED, not "
    "every campaign that exists, so a count from it is a count of ingested campaigns.** "
    "PubChem: only deposits of 10,000+ substances (AspRS is absent: its ChEMBL assay "
    "CHEMBL4649947 has 8,841 compounds, and PubChem's summary of AID 1671160 counted 8,841 "
    "SIDs, under the floor). ChEMBL: only papers reachable from `activities`, which holds "
    "whole-cell data for compounds that already have protein-level activity -- ChEMBL has "
    "1,932 documents with a whole-cell Mtb assay and 977 are candidates, of which 972 "
    "papers are here, so "
    "954 publications with such an assay are not. 'How many ChEMBL screening campaigns are "
    "there?' cannot be answered from this table, and neither can 'is the GSK TB set, the "
    "Malaria Box or the Pathogen Box in the atlas?': they are not, which is an absence of "
    "coverage and not a screen that found nothing. **`aid` is NULL on every ChEMBL row and on "
    "a campaign of several assays (`n_stages > 1`)**, so `WHERE aid = '588726'` finds nothing "
    "for an AID that is one of them (it sits in `pubchem:project:588335`); a declared project "
    "with only one ingested assay keeps its `aid`. Reach a campaign from any ingested AID through "
    "`screen_stages.stage_id = 'pubchem:<AID>'` and its `screen_id`. Rows carry their own "
    "`source` and `source_version`; the "
    "version in this header is PubChem's. **A call count that is NULL is not a zero, and "
    "NULL has two meanings.** `n_active`, `n_inactive` and `n_inconclusive` are NULL (1) where "
    "`outcome_stated` is false, meaning the deposit does not split its tested set into called "
    "outcomes -- PubChem's own summary reports 0 actives for a 65,366-SID deposit (AID "
    "1671170) that has no cutoff at all, and this pipeline reads no call from ChEMBL's papers "
    "(their free-text `activity_comment` is kept, not read) -- and (2) for a campaign of "
    "SEVERAL assays, because the "
    "per-stage counts overlap (a primary hit that fails confirmation is active in one stage "
    "and inactive in another). So `outcome_stated` can be true while the counts are NULL: "
    "when `n_stages > 1`, read `screen_stages.n_active`. Never read that NULL as 'no calls "
    "were made' or 'no hits'. **`outcome_stated` false does not always mean no call was "
    "made.** Six of the eight ChEMBL-deposited AIDs (1671154, 1671161, 1671162, 1671178, "
    "1671184, 1671185) state a one-sided rule in their PubChem Comment, 'activity <= 10uM "
    "... flagged as active': 218 `IC50` rows (relation '=', under 10,000 nM) are `Active` "
    "in screen_results while the campaign reads `outcome_stated` false and `n_active` NULL, "
    "and only there: the other 27,954 Active rows are in campaigns that state their calls. "
    "That Active set is a follow-up potency flag on the SIDs that have an IC50 row, not a "
    "hit rate: AID 1671178 has 25 Active of the 302 SIDs with an IC50 row (about 8%), not "
    "25 of its 66,592, and dividing by `n_tested` is wrong by two orders of magnitude. No "
    "row of these deposits is ever `Inactive` (above 10 uM stays unspecified), and the "
    "campaign-level veto is a deliberate under-claim, not an error. `n_unspecified` is "
    "PubChem's own count of SIDs with no call: 0 for AID 1626, where all 215,397 were "
    "called, and `n_tested` where every SID is unspecified -- which holds by construction "
    "whenever each SID also has an unspecified percent-effect row, so it holds for those six "
    "too. For ChEMBL it is `n_tested`, because no call is read. For a PubChem "
    "project of several assays it is `n_tested` only where every stage is wholly "
    "unspecified, and NULL otherwise. So on a single deposit `n_tested` minus `n_unspecified` "
    "is the SIDs that carry a call, except for those six, where it is 0 beside 175 Active "
    "SIDs. **`n_tested` is what was deposited -- SIDs (substances) for "
    "PubChem, distinct compounds for ChEMBL, and for a project the distinct SID union, not "
    "the sum of its stages. `library_size_stated` is the figure the depositor's prose names:** "
    "AID 1626 deposits 215,397 SIDs and its prose says 216,163 compounds. They differ, "
    "sometimes hugely, and are never summed or substituted. `outcome_method` is PubChem's "
    "`Method` (a dose-response curve or one concentration) and is NOT a stage: AID 1626, a "
    "primary library screen, is `confirmatory` there. `project_declared` false means PubChem "
    "groups no siblings for it, which is NOT the same as the campaign having had no follow-up. "
    "`stages_source` is `from_prose` on every row, PubChem included: neither source states "
    "a funnel stage. `modalities` lists what ChEMBL's stages measured and is empty for "
    "PubChem, which classifies none -- unclassified, not 'nothing measured'. `targets` is the "
    "target AS THE DEPOSITOR GAVE IT (accession, name) with `accession_kind` (uniprot | "
    "refseq | other), `uniprot_accessions` and the loci it reaches in `rv_ids`; empty "
    "`rv_ids` means unmatched, not 'no gene', a shared accession reaches every locus that "
    "owns it, and a `name` is never matched to a gene symbol. **Four deposits reach no "
    "locus, for three different reasons.** Three are correct refusals: bioA, 356,486 SIDs "
    "(CCE37082 is M. tuberculosis UT205, locus tag UDA_1568, which matches H37Rv's Rv1568 only "
    "by shared synteny and is never to be bridged), MbtI, 104,781 (P9WFX0 is the CDC 1551 "
    "entry; the H37Rv crosswalk holds P9WFX1) and panC, 10,011 (a PDB chain). **The fourth is "
    "a false absence**: fadD28, 355,326 (CAB06100 IS H37Rv, locus Rv2941, but UniProt holds "
    "no cross-reference for the id), a known defect, so fadD28 reads a largest screen of 47 "
    "compounds beside it. Those genes read 0 or a small `n_target_screens` beside a screen of "
    "that size: before saying a protein was never screened, look for an unplaced accession "
    "here. ChEMBL campaigns have empty "
    "`targets` and reach genes through screen_stages. `year` is NULL for PubChem, which "
    "carries no deposit year. `depositor` matters legally: "
    "PubChem's licence is per "
    "depositor (`licence`), 'Scientific Literature' marks a ChEMBL paper.",
    "screen_stages": "One row per ASSAY within a campaign, keyed on stage_id "
    "(`pubchem:<AID>`, `chembl:<assay>`); `screen_id` is its campaign. "
    "**Join screen_results on stage_id, never screen_stages to screen_results on screen_id** "
    "-- a campaign has many stages, and a campaign-level join multiplies every result by "
    "the number of stages. `stage` is funnel position (primary, confirmatory, counter_screen, "
    "profiling) and `modality` is what was measured (phenotypic_mtb, biochemical_mtb, "
    "mammalian_cytotox, adme, in_vivo_efficacy, other_pathogen, other); they are different "
    "axes, so a primary screen can be either. **Neither is stated, and each has a fallback.** "
    "`stage` is read from the description (profiling, from the modality) and defaults to "
    "`primary`: an assay whose prose matches nothing is `primary`, so that value is a weak "
    "claim. `modality` is read from the "
    "target record (type, organism) and the description, and falls back to `other`, which is "
    "also a real label. A PubChem stage has `modality` NULL -- unclassified, not 'other'. "
    "`stage` is NULL for a `derived` row, a ratio of two other assays: it has no funnel "
    "position and is never a measurement THIS ATLAS made, but its value may be a ratio the "
    "depositor published, which is triage-relevant -- do not skip it as 'not a measurement'. "
    "**Its `endpoint` is at least four quantities in one column (23 strings; 161 rows, 3%, "
    "are none of them: AUC, FC, Delta Tm, Kcat/Km, Ratio Ki): choose an endpoint family, do "
    "not trust the column.** Counts are rows with a value. `Selectivity Index` (1,951), "
    "`Selectivity index` (145: a distinct string, so an exact match on one case silently "
    "loses the other), `Ratio CC50/IC50` (183) and `Selectivity ratio` (116) are selectivity "
    "indices. **The column mixes organisms as well as quantities, and the organism is "
    "invisible in the endpoint string**: of the selectivity-index family's rows with a "
    "value, around 2,010 name tuberculosis in the stage description and around 390 do not, "
    "about 250 of those naming another pathogen outright -- HIV 1 and 2, Yersinia pestis, "
    "Plasmodium (3D7, K1), influenza A, Acinetobacter, M. abscessus, Trichophyton, atypical "
    "mycobacteria. Only the stage's own description tells a TB selectivity index from an "
    "HIV one, so filter on it, or a clean-looking table is about the wrong pathogen. "
    "**And that filter is leaky in both directions: 32 rows write tuberculosis as "
    "`TBMIC`** ('Selectivity is the ratio of cytotoxicity compared to TBMIC'), which no "
    "match on the word drops in with the foreign ones -- the same false absence, arriving "
    "through the remedy. A bare `Ratio` (1,350) and `Ratio "
    "IC50` (630) say nothing about what was divided by what; `TI` (63) is a therapeutic "
    "index in name only -- all ten of its stage descriptions are an in-vitro ratio of "
    "red-cell MHC50 or cell-line IC50/CC50 to an MIC or GI50, nine on Mtb and one on S. "
    "aureus, and none is an animal dose ratio; `PI` (100) is mostly a protection index of "
    "cell CC50 to MIC (92), plus 6 ciprofloxacin potency indices and 2 neurotoxicity "
    "protective indices in mice. **Check `standard_units` too**: the 21 `SI` rows in `ug "
    "ml-1` all come from one assay, CHEMBL874728, described as a ratio of IC50 and MIC "
    "(values 0.77 to 470), so its unit or its endpoint is mislabelled; 23 bare `Ratio` rows "
    "are also `ug ml-1`, and 5 `Selectivity Index` rows carry `10^3No_unit`-style scaled "
    "units (1,946 of its 1,951 have NULL units). A large minority of rows are censored (a "
    "'>' or '<' `screen_results.standard_relation`), so the `pmic` rule applies: a bound is "
    "a bound, not a value. "
    "**`assay_condition` is set only on `phenotypic_mtb` stages, and has four states.** "
    "NULL on 12,184 ChEMBL stages means classified as not whole-cell, but NULL on the 28 "
    "PubChem stages means never classified at all, and several of those are whole-cell Mtb "
    "growth screens (AID 1626, 215,397 substances; 1671161, 1671162, 1671174), so "
    "`assay_condition IS NULL` does not exclude whole-cell stages and would drop the largest "
    "screens in the layer. `unspecified` (4,763) means whole-cell with no medium stated, "
    "and it is not `standard_media`; the 5,318 whole-cell stages are ChEMBL only; a "
    "condition query over all 17,530 stages has the wrong denominator; no stage matches "
    "`caseum`. **`strain` mixes organisms** and is meaningful only beside `modality` (4,166 "
    "of the 9,259 stages that have one are `phenotypic_mtb`): it is ChEMBL's `assay_strain`, "
    "H37Rv in several spellings (`H37Rv` 2,262, `H37Rv ATCC 27294` 437), then H37Ra, BCG, "
    "host animals (BALB/c, Sprague-Dawley, C57BL/6) and 879 distinct strains of other "
    "pathogens across the `other_pathogen` stages (ATCC 29213 is S. aureus), so `WHERE "
    "strain = 'H37Rv'` undercounts and `GROUP BY strain` returns a column that means "
    "different things per row. "
    "**A campaign reaches a gene by one of two routes, and a query that takes only one finds "
    "half the screens.** ChEMBL stages: UNNEST `crosswalk.chembl_targets`, match `target_id` "
    "to this table's `target_chembl_id`, keep `evidence = 'direct'` and the stage's own "
    "`target_type = 'SINGLE PROTEIN'` -- the ClpP1P2 complex target maps to both clpP1 and "
    "clpP2, so counting complexes hands each subunit a screen of the pair. PubChem stages "
    "have NO target_chembl_id: they reach a gene through `screens.targets[].rv_ids`, and "
    "that is where the largest screens are. A deposit naming two proteins is a complex "
    "screen whose actives belong to neither; `target_summary.n_target_screens` has both "
    "routes done (its note has the one boundary: a target the crosswalk cannot place). "
    "`n_tested` is SIDs for PubChem and distinct compounds "
    "for ChEMBL. `n_active` is NULL on every ChEMBL stage (no call is read) and on a "
    "PubChem stage whose `outcome_stated` is false; 0 means calls were stated and none was "
    "active.",
    "screen_results": "One row per RESULT ROW a source deposited, keyed on (stage_id, "
    "result_tag, activity_id, pubchem_sid): a PubChem row has a `result_tag` and no "
    "`activity_id`, a ChEMBL row the reverse. A row is a SID (PubChem) or an activity "
    "(ChEMBL), not a compound: a CID sits under several SIDs that can disagree (11 CIDs in "
    "AID 1626 do: 8 `inactive` beside `inconclusive`, 3 `active` beside `inconclusive`), a "
    "SID can repeat (AID "
    "1671170: 65,646 rows over 65,366 SIDs), and a compound with several ChEMBL activities "
    "has several rows. None of that is collapsed, because choosing a winner would be "
    "silent: count DISTINCT, and join to a stage on stage_id. Millions of rows -- "
    "aggregate, never dump. **The inactives are here**, which is what makes 'tested and "
    "did nothing' answerable. **`outcome` NULL is not inactive**: it means the source stated "
    "no call was recorded (every ChEMBL row, and the rows of a deposit above or without a "
    "cutoff), so filter on outcome = 'inactive' to find non-hits and never on outcome IS NULL. "
    "`outcome = 'active'` on an `IC50` row of a campaign whose `outcome_stated` is false is "
    "a one-sided potency flag (<= 10 uM) and not a hit rate over `n_tested` (see `screens`). "
    "A compound carries `pubchem_cid` (PubChem rows) or `molecule_chembl_id` or both; the "
    "bridge between them is UniChem and it is incomplete, so a NULL molecule_chembl_id on a "
    "PubChem row means unmapped, not untested. **`compounds` is the ChEMBL potency set "
    "(5,178), not the screened set**: a screened compound's structure is in "
    "`compound_structures`, which has one for 478,985 of the 479,023 screened ChEMBL ids. A "
    "row with a NULL molecule_chembl_id (572,581 of them: 361,870 distinct CIDs, and 88 rows "
    "with no CID either) is PubChem-only and was never looked up there, so no structure may "
    "be assumed for it. There is no "
    "target column: a ChEMBL result's target is its stage's, a PubChem result's is on "
    "`screens.targets`. `activity_comment` is ChEMBL's own words, including 'Not "
    "Determined' -- a measurement that failed, with no "
    "value -- and free-text calls ('Not Active', 'Toxic', 'Resistant') that this pipeline "
    "keeps and does not read as an `outcome`. "
    "`endpoint`, `standard_value`, `standard_units` and `standard_relation` are the typed "
    "value where the source gave one and NULL otherwise; a '>' or '<' relation is a bound, "
    "not a measurement. **`activity_score` is PubChem's depositor-defined "
    "`PUBCHEM_ACTIVITY_SCORE`** (PubChem rows only; NULL on every ChEMBL row and on deposits "
    "that give none): comparable within one deposit and meaningless across them -- 0 to 80 in "
    "AID 1626, -8,525 to 100 in AID 2221 -- so never order or filter it across `screen_id`s "
    "to find 'the strongest hits'.",
    "drug_genes": "Drug to Rv tag. `link`: mechanism = ChEMBL names this gene's protein as "
    "the single-protein target; mechanism_complex = ChEMBL names a complex the protein "
    "belongs to (bedaquiline -> all 8 ATP synthase subunits), not evidence it binds this "
    "subunit; bosch_2021 = Bosch 2021's own drug annotation, exact name match; "
    "who_resistance = WHO-graded resistance variants in this gene for this drug, which is "
    "NOT target engagement (katG activates isoniazid); structure = the drug is modelled on "
    "this protein's own chain in a PDB entry (`source_text` lists them), which is physical "
    "evidence that the two meet but still not a mechanism claim -- EthR binds many ligands "
    "in soaking studies. Drugs acting on a gene: link IN ('mechanism', 'bosch_2021').",
    "trials": "ClinicalTrials.gov interventional studies for condition 'tuberculosis', "
    "including vaccine, diagnostic and behavioural studies. `phase_max` is numeric "
    "(0.5 = early phase 1 ... 4); NULL means phase not applicable. Dates may be partial "
    "(YYYY-MM).",
    "trial_drugs": "Trial to drug. `via_chembl_ref` = ChEMBL's curated trial reference; "
    "`via_intervention_name` = exact match of an intervention name to a ChEMBL synonym. "
    "A trial with no row here may still have tested a drug under a name nothing matched.",
}

SYSTEM = """You answer questions about Mycobacterium tuberculosis H37Rv drug targets \
by querying the Mtb Target Atlas, a store built only from public data.

Always query. Never answer from memory: your own knowledge of TB biology is useful \
for framing a question but is not a source, and the user is asking what *this store* \
says. Call `describe_store` first if you are unsure of a column.

Cite records. Every factual claim names the identifiers it rests on -- Rv tags, PDB \
ids, ChEMBL ids, variant names -- so the user can check it. Give the numbers you \
actually retrieved rather than rounding them into prose.

An absence is an answer. A gene with no ChEMBL activity, no structure or no WHO \
variant is a real finding, often the interesting one; say so plainly and say which \
source was checked. Never let a missing row read as a zero measurement, and never \
fill a gap from a different source without saying you did.

Respect the evidence levels, because they are not interchangeable:
- ChEMBL `evidence`: `direct` is an Mtb protein target; `orthologue` is another \
mycobacterial protein reached through a UniRef cluster, which is a family-level link \
and not evidence of a shared binding site; `whole_cell` is a MIC against the whole \
organism and says nothing on its own about which protein is engaged.
- Conditional fitness (Griffin 2011) adds growth on cholesterol, the carbon source Mtb \
uses inside a macrophage. A transposon screen cannot measure a gene with no insertions, \
so an essential gene is `measured = false` there -- unmeasured, not unaffected.
- Essentiality is one in vitro condition (7H9 broth). Vulnerability is CRISPRi \
knockdown and answers a different question -- how far expression must fall before \
fitness suffers -- on a negative scale, and only `certain` rows are confident.
- Human homology is a phmmer search against the reviewed human proteome, reported as \
an E-value and a percent identity; the 30% "close" line is this atlas's convention.
- A ligand counts for a protein only when it is modelled on that protein's own chains; \
one bound to a neighbouring subunit is in `ligand_ids_elsewhere`, shown and not counted.
- The WHO catalogue covers 65 genes. For every other gene the correct statement is \
"not in the catalogue", never "no resistance known".
- Drugs: `max_phase_tb` is the phase for tuberculosis, not for any indication. A drug \
reaches a gene through ChEMBL's mechanism (a single protein, or a complex the protein \
belongs to -- membership is not binding), Bosch 2021's annotation, a co-crystal structure, \
or WHO-graded resistance. Resistance is not engagement: katG activates isoniazid and \
Rv0678 is a regulator. A co-crystal is physical evidence the two meet, not a mechanism. \
Say which link an answer rests on.
- Trials link to drugs through ChEMBL's own trial references or an exact \
intervention-name match. An unlinked trial may still have tested a drug.
- Screens: `outcome` NULL is not `inactive` -- it means no call was recorded (every \
ChEMBL row, and the rows of a deposit above or without a cutoff); only `outcome = \
'inactive'` is a non-hit, and an `Active` IC50 row in a campaign with `outcome_stated` false \
is a potency flag (<= 10 uM) on the SIDs measured, not a hit rate over `n_tested`. A \
screen filed against a complex is not a screen of either subunit: shown, not \
counted. `stage` and `modality` are different axes (a primary screen can be phenotypic or \
biochemical), and `n_screen_actives` counts only the screens that stated calls, so it shares \
no denominator with `n_target_screens`. `screens` holds the campaigns the atlas ingested, \
not every campaign that exists, so a count from it is a count of ingested campaigns.

Be concise and quantitative. Prefer a short table to a paragraph when the answer is \
a list of genes."""


@dataclass
class ToolCall:
    """What the agent did, surfaced so an answer can be audited rather than trusted."""

    name: str
    input: dict[str, Any]
    rows: int | None = None
    error: str | None = None
    result: Any = None


@dataclass
class Answer:
    text: str
    calls: list[ToolCall] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)


_connection: duckdb.DuckDBPyConnection | None = None
# Two first questions at once would otherwise build two sandboxes, each with its own ceiling.
_connection_lock = threading.Lock()


def connection() -> duckdb.DuckDBPyConnection:
    """An in-memory copy of the store with external access locked off."""
    global _connection
    with _connection_lock:
        if _connection is None:
            _connection = _sandbox()
        return _connection


def _sandbox() -> duckdb.DuckDBPyConnection:
    # Set at open, before the lock below, so the model's SQL cannot lift either ceiling.
    spill = tempfile.mkdtemp(prefix="atlas-agent-")
    atexit.register(shutil.rmtree, spill, ignore_errors=True)
    con = duckdb.connect(
        ":memory:",
        config={
            "memory_limit": MEMORY_LIMIT,
            "temp_directory": spill,
            "max_temp_directory_size": SPILL_LIMIT,
            "threads": THREADS,
        },
    )
    for name in TABLES:
        path = STORE / f"{name}.parquet"
        if path.exists():
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM '{path}'")
    # After this the model's SQL cannot touch the filesystem or the network, and
    # cannot turn that back on.
    con.execute("SET enable_external_access=false")
    con.execute("SET lock_configuration=true")
    return con


def available_tables() -> list[str]:
    con = connection()
    return [row[0] for row in con.execute("SHOW TABLES").fetchall()]


def describe() -> str:
    """Schema, row counts, provenance and the per-table gotchas, as text."""
    con = connection()
    lines = []
    for name in available_tables():
        count = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        columns = con.execute(f"DESCRIBE {name}").fetchall()
        try:
            version, retrieved = provenance(name)
        except Exception:  # noqa: BLE001 - provenance is nice to have, not required
            version, retrieved = "unknown", "unknown"
        lines.append(f"## {name} ({count:,} rows) -- {version}, retrieved {retrieved}")
        if name in TABLE_NOTES:
            lines.append(f"NOTE: {TABLE_NOTES[name]}")
        lines.append(", ".join(f"{c[0]} {c[1]}" for c in columns))
        lines.append("")
    return "\n".join(lines)


def run_sql(sql: str, limit: int = MAX_ROWS) -> dict[str, Any]:
    """One read-only SELECT against the store.

    The statement type comes from DuckDB's own parser, not a keyword match, so a
    column called `call` or a description containing "data set" is not refused.
    Table functions that read files parse as SELECT too; the connection's lock is
    what stops those.
    """
    # A DuckDB connection is not thread-safe and FastAPI serves /ask from a
    # thread pool; a cursor per query is the documented way to share one, and
    # it inherits the lock.
    cursor = connection().cursor()
    try:
        statements = cursor.extract_statements(sql)
        if len(statements) != 1:
            raise ValueError("one statement at a time, please")
        if statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("only SELECT and WITH queries are allowed")

        capped = min(limit, MAX_ROWS)
        # A generated cross join must not hold a server thread forever.
        timer = threading.Timer(QUERY_SECONDS, cursor.interrupt)
        timer.start()
        try:
            result = cursor.execute(
                f"SELECT * FROM ({statements[0].query.strip().rstrip(';')}) LIMIT {capped + 1}"
            )
            fetched = result.fetchall()
        finally:
            timer.cancel()
        columns = [c[0] for c in result.description]
    finally:
        cursor.close()
    rows = [
        {c: (str(v) if hasattr(v, "isoformat") else v) for c, v in zip(columns, row, strict=True)}
        for row in fetched[:capped]
    ]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": len(fetched) > capped,
    }


def ask(question: str, *, model: str = MODEL, effort: str = "high") -> Answer:
    """Answer one question, returning the tool calls that produced it."""
    import anthropic
    from anthropic import beta_tool

    # Ask the SDK rather than the environment: it also resolves an `ant auth login`
    # profile, which a check on two variables would refuse.
    client = anthropic.Anthropic()
    if not (client.api_key or client.auth_token or client.credentials):
        raise RuntimeError(
            "No Anthropic credentials. Set ANTHROPIC_API_KEY, or run `ant auth login`."
        )

    calls: list[ToolCall] = []

    @beta_tool
    def describe_store() -> str:
        """Every table in the atlas: row counts, columns, source versions, and the
        traps in each one. Call this before writing a query you are unsure about.
        """
        calls.append(ToolCall(name="describe_store", input={}))
        return describe()

    @beta_tool
    def query_store(sql: str) -> str:
        """Run one read-only SQL SELECT against the atlas and return the rows as JSON.

        DuckDB syntax. One statement, no semicolons, SELECT or WITH only. Results
        are capped at 200 rows, so aggregate or filter rather than dumping a table.

        Args:
            sql: The SELECT statement to run.
        """
        call = ToolCall(name="query_store", input={"sql": sql})
        calls.append(call)
        try:
            payload = run_sql(sql)
        except Exception as error:  # noqa: BLE001 - the model should see and fix its own SQL
            call.error = str(error)
            return f"ERROR: {error}"
        call.rows = payload["row_count"]
        call.result = payload["rows"][:20]
        return json.dumps(payload, default=str)

    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=16000,
        max_iterations=MAX_TURNS,
        # Every turn resends the ~9k-token schema dump the first one fetched.
        cache_control={"type": "ephemeral"},
        system=SYSTEM,
        output_config={"effort": effort},
        tools=[describe_store, query_store],
        messages=[{"role": "user", "content": question}],
    )
    try:
        final = runner.until_done()
    except anthropic.APIError as error:
        # Rate limit or outage upstream: this route is unavailable, the rest of the API is not.
        raise RuntimeError(f"The model call failed: {error}") from error

    text = "".join(block.text for block in final.content if block.type == "text").strip()
    if final.stop_reason != "end_turn":
        # Narration from a loop that never finished must not pass for an answer.
        text = f"**{STOPPED.get(final.stop_reason, final.stop_reason)}**\n\n{text}".strip()

    sources = {}
    for name in available_tables():
        try:
            version, _ = provenance(name)
            sources[name] = str(version)
        except Exception:  # noqa: BLE001
            continue
    return Answer(text=text, calls=calls, sources=sources)
