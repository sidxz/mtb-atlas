# Data sources

Every endpoint, format and licence below was checked against the live service on
**2026-10-09** (the clinical sources on **2026-10-10**, PubChem and UniChem on
**2026-10-11**). Nothing here is from
memory or documentation alone — where a claim could not be verified, it says so.

All sources are public. No consortium data, ever.

## Summary

| Source | Version seen | Licence | Used for |
|---|---|---|---|
| [Mycobrowser](#mycobrowser) | Release 5 (2024-07-11) | **none stated** | Gene universe, annotation |
| [UniProt](#uniprot) | 2026_03 (2026-09-02) | CC BY 4.0 | Accessions, cross-references |
| [ChEMBL](#chembl) | ChEMBL_37 (2026-05-01) | CC BY-SA 3.0 | Targets, bioactivity (M1) |
| [UniChem](#unichem-the-chembl-to-pubchem-bridge) | `unknown`: no release stated, fetched 2026-10-11 | CC BY-SA 3.0, inherited from ChEMBL | ChEMBL to PubChem compound bridge |
| [PubChem BioAssay](#pubchem-bioassay) | E-utilities `txid1773[ORGN] AND 10000:100000000[TSC]`, 28 AIDs on 2026-10-11 | **per depositor**; see below | Screening campaigns, with their inactives |
| [RCSB PDB](#rcsb-pdb) | live | CC0 1.0 | Experimental structures (M1) |
| [AlphaFold DB](#alphafold-db) | v6 (2025-08-24) | CC BY 4.0 | Predicted structures (M1) |
| [DeJesus 2017](#essentiality-dejesus-2017) | mBio, Table S3 | CC BY 4.0 | Essentiality (M1) |
| [WHO catalogue](#who-mutation-catalogue) | 2nd ed. (2023) | ODC-By 1.0 | Resistance mutations |
| [Bosch 2021 CRISPRi](#vulnerability-bosch-2021) | Cell, Table S3 | CC BY 4.0 | Vulnerability index, in H37Rv and in the HN878 clinical isolate |
| [Griffin 2011](#conditional-fitness-griffin-2011) | PLoS Pathog, Tables S3/S4 | CC BY 4.0 | Fitness on cholesterol (M7) |
| [MtbTnDB](#conditional-tnseq-mtbtndb) | Zenodo 10.5281/zenodo.15284946 (2025-04-20) | CC BY 4.0 | Conditional TnSeq, 136 screens |
| [STRING](#string) | v12.5, taxon 83332 | CC BY 4.0 | Interaction partners |
| [phmmer vs human proteome](#human-homology) | UniProt UP000005640, reviewed | CC BY 4.0 | Human anti-target check |
| [phmmer vs the Mtb proteome](#paralogs-functional-redundancy) | UniProt UP000001584 | CC BY 4.0 | Paralogs: is there a backup copy? |
| [phmmer vs Mycobacteriaceae + RCSB](#orthologue-structures-a-structure-to-work-from) | UniProt taxon 1762 with a PDB entry, live RCSB | CC BY 4.0 / CC0 1.0 | A structure to work from that is not of this protein |
| [ChEMBL drugs](#chembl-tb-drugs-and-mechanisms) | ChEMBL_37 | CC BY-SA 3.0 | TB drugs, phases, mechanisms (M6) |
| [ChEMBL mechanisms by Pfam](#drug-precedent-has-this-fold-ever-been-drugged) | ChEMBL_37 | CC BY-SA 3.0 | Has a drug ever been filed against this fold? |
| [ClinicalTrials.gov](#clinicaltrialsgov) | API 2.0.5, data 2026-10-09 | US Government database; terms below | Interventional TB trials (M6) |

Licences differ, so they are tracked per source rather than rolled up. The code
in this repository is MIT; the data is not.

---

## Mycobrowser

The backbone of the gene universe.

- **Release list:** `https://mycobrowser.epfl.ch/releases` → Release 5, 2024-07-11
- **File:** `https://mycobrowser.epfl.ch/releases/5/get_file?dir=txt&file=Mycobacterium_tuberculosis_H37Rv.txt`
- **Format:** TSV, 35 columns, 4,187 rows, 3.5 MB. `Content-Disposition` names it
  `Mycobacterium_tuberculosis_H37Rv_txt_v5.txt`.
- **Key:** `Locus` — the Rv tag.

**Licence: none stated.** The site carries only `©2018-2026 EPFL` and a citation
request (Kapopoulou, Lew & Cole, *Tuberculosis* 2011;91(1):8–13). There is no
licence file, no terms-of-use page for the data, and the linked EPFL disclaimer
says nothing about data reuse. The pipeline therefore **downloads at build time
and never redistributes**: `data/raw/` is gitignored, and no Mycobrowser row is
committed to this repository beyond the handful in `tests/fixtures/`.

**Verified quirks, each one handled in `atlas/sources/mycobrowser.py`:**

- 4,031 rows are `CDS`; the rest are `ncRNA` (92), `tRNA` (45), `promoter` (6),
  `-10_signal` (4), `-35_signal` (4), `rRNA` (3), `misc_RNA` (2).
- **Regulatory rows re-use gene locus tags.** `Rv3571`, `Rv0148`, `Rv1219c`,
  `Rv1964`, `Rv1994c`, `Rv2940c`, `Rv3287c` and `MTB000063` each appear more than
  once. Filtering to `CDS` makes the locus unique; not filtering duplicates genes.
- **The header has a duplicate name:** `Orthologues M. tuberculosis` appears
  twice (columns 31 and 35), which `csv.DictReader` silently collapses. The
  ingester reads by index.
- **All ten `Orthologues *` columns are empty** in this export — 0 non-empty
  values across 4,187 rows. They cannot be used for the orthologue bridge.
- `Drug Resistance Mutations` holds drug abbreviations (`ETH,INH`), not mutations.
- 13 CDS rows are flagged `Is_Pseudogene = Yes`.
- **No `ETag` and no `Last-Modified`** on the file response, so a new release
  cannot be detected by conditional GET. `fetch` records a sha256 instead.

**Not verified:** whether the `/releases/5/...` URL stays stable once Release 6
ships, and whether an older release remains downloadable. No API exists.

## UniProt

Source of truth for Rv tag → accession, and for the PDB, ChEMBL and AlphaFold
cross-references.

- **Endpoint:** `https://rest.uniprot.org/uniprotkb/stream?query=proteome:UP000001584&format=tsv&fields=...`
- **Version:** reported in response headers — `x-uniprot-release: 2026_03`,
  `x-uniprot-release-date: 02-September-2026`. The ingester reads the release
  from the headers rather than hardcoding it.
- **Contents:** 3,997 entries, all taxon 83332. 2,341 reviewed, 1,656 unreviewed.
  3,991 carry an AlphaFold cross-reference, 871 a PDB one, 131 a ChEMBL one.
- **Licence:** CC BY 4.0, stated in every flat-file record
  (`CC   Distributed under the Creative Commons Attribution (CC BY 4.0) License`).

**Verified quirks, each one handled in `atlas/sources/uniprot.py` and
`atlas/crosswalk.py`:**

- **`gene_oln` is not one tag per entry.** Observed shapes: `Rv3790`,
  `Rv0846c RVBD_0846c`, `Rv1180/Rv1181`, `Rv2880c/Rv2879c`, `Rv3423.1`,
  `Rv1706c.1`, `Rv2922.1c`, `Rv0236A`, and a 16-tag semicolon list for the
  IS6110 transposase `P9WKH9`. Splitting on whitespace is wrong; the ingester
  matches tags with a regex, which also skips the `RVBD_` aliases.
- **No Rv tag appears in two entries**, so Rv → accession is a function. The
  reverse is not: accession → Rv is many-to-one.
- **One entry has no Rv tag at all:** `L7N683`. Mycobrowser links it to `Rv2307D`.
- **19 Rv tags exist in UniProt but not Mycobrowser:** `Rv3423.1`, `Rv1706c.1`,
  `Rv1706c.2`, `Rv2922.1c`, `Rv1094.5`, `Rv2975A`, `Rv3221B`, `Rv1155A`,
  `Rv0229A`, `Rv2386A`, `Rv0028A`, `Rv3202A` and others. They are outside the
  gene universe because they have no Mycobrowser coordinates, so the M4 canvas
  could not place them.
- **No UniRef fields are available** on `uniprotkb` TSV exports
  (`uniref_cluster_50` and friends are rejected as invalid). UniRef must be
  queried from the `uniref` endpoint — see the orthologue bridge below.

### Protein context (M7)

The same stream carries the curated biology a target page leads with:
`cc_function`, `cc_subcellular_location`, `ft_transmem`, `ft_signal`,
`cc_pathway`, `cc_catalytic_activity`, `cc_cofactor`, `go_p` / `go_f` / `go_c`
(GO term names), `cc_disruption_phenotype`, `lit_pubmed_id`,
`protein_existence` and `annotation_score`. Verified 2026-10-10 against
release 2026_03.

- **Coverage:** of 3,997 entries, 1,702 state a function, 722 carry
  transmembrane segments, 543 a pathway, 936 a reaction with a Rhea id and 452
  a disruption phenotype. The median entry cites 2 papers and `esxA` the most
  (45).
- **Free text is prefixed and tagged:** every comment starts `FUNCTION: `,
  `PATHWAY: `, and so on, and claims carry evidence codes such as
  `{ECO:0000269|PubMed:25906160}`. The ingester strips both and keeps the
  citations written into the prose ("(PubMed:16291675)").
- **Absence is not a negative:** no transmembrane segment means none
  annotated, not soluble, and 1,656 entries are unreviewed (TrEMBL), where
  annotation is automatic. The UI says which kind of entry each value comes
  from.
- **`n_references` counts the papers UniProt cites:** a curated subset of the
  literature, useful as a rough how-studied signal and nothing more.

### Agreement with Mycobrowser

Of 4,031 CDS loci: **4,006 agree** on the accession, **13 disagree**, 5 name an
accession absent from the proteome, and 7 have no accession from either source.
Examples kept as test fixtures:

| Locus | Mycobrowser | UP000001584 | Resolution |
|---|---|---|---|
| `Rv2879c` | `P0A644` | `P9WH15` | UniProt wins; both recorded |
| `Rv0236A` | `P0A5C5` | `P9WLB1` | UniProt wins; both recorded |
| `Rv1180`, `Rv1181` | `O50436`, `O50437` | `A0A089QRB9` (both) | UniProt wins; flagged shared |
| `Rv2099c` | `Q79FH7` | — | No accession; flagged conflict |
| `Rv2307D` | `L7N683` | — (no Rv tag) | Mycobrowser accepted |
| `Rv0947c` | — | — | Unmapped; flagged conflict |

## ChEMBL

- **Status:** `https://www.ebi.ac.uk/chembl/api/data/status.json` → `ChEMBL_37`,
  released 2026-05-01; 24,527,044 activities, 18,552 targets.
- **Target mapping:** `https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/latest/chembl_uniprot_mapping.txt`
  — TSV, 17,258 rows, `accession / target_id / name / target_type`. The first
  line names the release.
- **Licence:** CC BY-SA 3.0 (`LICENSE` on the FTP root), with
  `REQUIRED.ATTRIBUTION` asking that ChEMBL IDs be preserved and the release
  number displayed. Both are honoured: IDs are stored verbatim and
  `source_version` carries the release.

**Verified:**

- 121 `SINGLE PROTEIN` targets map to accessions in UP000001584, over 190
  accessions; also 57 `PROTEIN NUCLEIC-ACID COMPLEX`, 12 `PROTEIN COMPLEX`,
  2 `PROTEIN FAMILY`.
- UniProt's `xref_chembl` and this file agree in both directions bar two targets
  that only the mapping file knows: `P9WPP3` (Rv2266, cyp124) and `P9WPL1`
  (Rv1777, cyp144). The crosswalk unions the two.
- Reference targets: DprE1 `CHEMBL3804751` (306 activities, 136 with pChEMBL),
  InhA `CHEMBL1849` (1,460 / 490).
- **MmpL3 has no Mtb target.** See the orthologue bridge.
- **Organism names are unreliable.** *M. smegmatis* MmpL3 is filed under
  *Mycolicibacterium smegmatis*, which no `Mycobacterium*` name filter matches.
  Every query in this codebase keys on taxonomy or accession, never on an
  organism string.
- Whole-cell targets: `CHEMBL360` (*M. tuberculosis*, 209,493 activities) and
  `CHEMBL2111188` (H37Rv, 422).
- `molecule_chembl_id__in` accepts at least 50 IDs per request, which is how M1
  will pull whole-cell MICs compound-first instead of dumping 209k rows.

**Not verified:** any published rate limit. No API key is required.

### Is there an assay, as opposed to a hit?

`target_summary.n_protein_assays` counts the DISTINCT `assay_chembl_id` values
run against a gene's own protein, read from the `assay_sizes` census rather
than from `activities` (see "Screened, or merely studied?" below for why that
matters). It answers a question none of the other columns do: whether this
target can be screened at all, as against whether anyone has already hit it.
119 genes have one; **434 essential genes have none**, and for those the first
experiment is building the assay.

Two traps, both of which would inflate the number badly:

- **`assay_type` does not mean what it looks like.** ChEMBL files whole-cell
  MICs as `F` (functional) against the organism, so the genome-wide counts are
  3,083 `F` assays over *two* targets (`CHEMBL360`, `CHEMBL2111188`) against
  454 `B` assays over 92. Reading `assay_type = 'F'` as "functional protein
  assay" credits every MIC screen in the database to whichever genes its
  compounds touch. The filter that works is `evidence = 'direct'` on a
  `SINGLE PROTEIN` target, the second half of which keeps a complex's assays
  out of its subunits' counts (see "Screened, or merely studied?" below).
- **Count assays, not measurements.** InhA has 205 assays behind 1,460
  activity rows; one assay run against 400 compounds is one assay you could
  run again.

Orthologue assays are excluded. An assay on *M. smegmatis* MmpL3 is a real
assay, but not one for the Mtb protein, so mmpL3 reads 0 here while still
showing its orthologue chemistry — which is the honest answer to "what would
it take to screen this".

### Whole-cell potency: the MICs `pchembl_value` cannot see

ChEMBL computes `pchembl_value` for affinity endpoints only. It is **NULL on
every one of the 3,870 MIC rows** in the store, because an MIC is a growth
endpoint rather than a binding constant. So the original roll-up, which read
`max(pchembl_value)` over whole-cell rows, answered from **78 IC50/EC50
measurements and silently ignored every MIC** — reporting a whole-cell number
for 12 genes when 71 have one, and reporting the wrong kind of number for
those 12. For a TB atlas that is the wrong way round: the MIC *is* the
whole-cell number.

`activities.pmic` is `-log10(MIC in mol/L)`, converted in the ingester from the
value and units ChEMBL reports, with `pmic_basis` recording which conversion
produced it (including the molecular weight, when a mass unit needed one).
3,941 of 6,752 whole-cell rows now carry one. The distribution is sane —
median 5.6, 1st percentile 3.44, 99th 8.44 — and the two rows above pMIC 10
are faithful conversions of ChEMBL's own deposited `1.6e-05 ug.mL-1`, not
conversion errors. `best_whole_cell_pchembl` is kept beside it, because a
whole-cell IC50 is a real measurement; it is simply a different endpoint, and
no row has both.

Three rules keep it honest:

- **A censored MIC gets no `pmic`.** `MIC > 64 ug/mL` means the compound did
  not inhibit at the highest concentration tested. That is a measured result,
  not a potency of 64, and converting it would invent the one thing the
  experiment failed to establish. A fifth of the MICs are censored this way,
  so including them would drag every aggregate toward a potency nobody
  observed. They are counted in `n_mic_censored` instead, because a gene whose
  chemistry is all non-inhibition has to read differently from one nobody
  tested.
- **The MIC family only.** `MBC` is bactericidal rather than inhibitory and is
  a different endpoint; `pMIC` and `-logMIC` are already logs and would be
  double-logged. Thresholded names like `MIC>90` *are* exact values at a stated
  inhibition level and do convert.
- **A mass unit without a molecular weight converts to nothing**, rather than
  to a guess.

### Under which conditions, for chemistry as well as genetics

The atlas answers "under which conditions is this gene required" from
conditional TnSeq, and could not answer the same question of its chemistry:
every MIC was pooled into one number. ChEMBL has no condition field, so
`activities.assay_condition` reads the depositor's own prose —
`caseum | intracellular | non_replicating | alt_carbon | nutrient_stress |
standard_media | unspecified` — with the most demanding condition named
winning, since an assay run in 7H9 under hypoxia is a hypoxia result.

**`unspecified` is not `standard_media`**, and it is the commonest answer
(6,118 of 6,752 rows). Most ChEMBL MICs never state a medium, and asserting
the default would turn silence into a measurement. A gene whose every MIC is
`unspecified` has a real answer: nobody has published its chemistry outside
ordinary aerobic growth.

**Nothing in the current release matches `caseum`.** The label is kept
deliberately: caseum penetration is among the most decisive questions in TB
target assessment, and a visible zero is the honest way to say the public
chemistry does not cover it. It will not be filled by relabelling something
else.

`resistant_panel` is a **separate boolean**, not a value of the enum, because
strain and medium are different claims: "tested on MDR clinical isolates"
(1,121 rows) and "tested under hypoxia" must not hide each other, and a row
can be both. Folding them into one column was tried and rejected — it let the
resistance panels swallow a thousand rows whose medium was simply unstated.

### Screened, or merely studied?

`target_summary.max_assay_compounds` is the largest single published assay on
the gene's own protein, by distinct compounds. `n_protein_assays` cannot
separate one 66,592-compound campaign from fourteen five-compound follow-ups,
and those are opposite answers to "is there a tractable screen here".

Genome-wide, **six genes have a public assay reaching 1,000 compounds** and
thirteen reach 100. The four largest come from one 2021 deposit
(`CHEMBL3988442`, Dundee/GHDDI/Cornell): CoaBC (`dfp`) at 66,942 compounds,
Pks13 at 66,592, TrpRS at 65,366 and AspRS at 8,841. The other two are the
PubChem deposits that were already visible, `dnaB` (2,123) and `recA` (2,118).
ClpP1P2 has the largest single assay in the store, 68,611 compounds, and is
counted for neither subunit (below). inhA, the best-studied target in TB, tops
out at 76 compounds in any single assay.

**This number was wrong until the census landed.** It is computed from
`assay_sizes`, which counts every activity row ChEMBL files against an assay.
Reading it from `activities` instead counted only rows carrying a
`pchembl_value`, and a primary screen reports percent inhibition: the census
holds 295,278 measurements across 1,099 assays on 132 targets, 279,306
of them in assays that report `Percent Effect`, while `activities` holds 8,766
protein-level rows. The screens above therefore read as 143 (Pks13), 5 (CoaBC),
2 (TrpRS), 8 (ClpP1P2) and 12 (AspRS), and `dnaB` and `recA` as 1,642 and
1,875. The scarcity is still the finding, but it is a scarcity of *campaigns*
and not of compounds.

A screen of `ClpP1P2` is not a screen of `clpP1`. The crosswalk maps that
`PROTEIN COMPLEX` target to both subunits as `direct`, so the counts filter on
`SINGLE PROTEIN` — the rule `n_complex_drugs` already follows — and complex
screens are reported beside them in `n_complex_assays` and
`max_complex_assay_compounds`. Fourteen genes carry one: both ClpP subunits,
eight ATP synthase subunits, `gyrA`/`gyrB`, and `rmlC`/`rmlD`, whose target
ChEMBL files as a `PROTEIN FAMILY` and which the same filter keeps out of the
single-protein count. The rule is not free: eleven essential genes (`gyrB`,
seven ATP synthase subunits, `clpP1`, `clpP2` and `rmlC`) had an assay before
and read zero now, which is why "essential genes with no protein assay" moved
from 431 to 434 while the census gave eight others their first.

### The orthologue bridge

MmpL3 is among the most-pursued targets in TB drug discovery and has **no Mtb
ChEMBL target**; its inhibitors are assayed against the *M. smegmatis*
orthologue, `CHEMBL5465372` (accession `A0QP27`). Reporting "no ligands" for it
would be technically true of ChEMBL's Mtb targets and substantively misleading.

Built from the ChEMBL side, because it is far smaller:

1. One UniProt query returns every non-Mtb Mycobacteriaceae protein with a
   ChEMBL cross-reference — `(taxonomy_id:1762) AND (database:chembl) NOT
   (taxonomy_id:83332)` → **28 accessions**, `A0QP27` among them.
2. For each, the UniRef cluster at 90% identity, falling back to 50%.
3. Cluster members intersected with the 3,997 Mtb accessions.

Verified for MmpL3: `P9WJV5` and `A0QP27` are both in `UniRef50_A0QP27`
(611 members, representative `A0QP27`). They are **not** in the same UniRef90
cluster — pairwise identity is 61% by RCSB sequence search — so this link exists
only at the 50% level.

**UniRef50 is broad.** A 611-member cluster is not evidence of a shared binding
site. Every orthologue link therefore records its `identity_level`,
`uniref_cluster`, `cluster_size` and source organism, and is labelled
`evidence = "orthologue"`, never `"direct"`. A direct target always wins: the
crosswalk attaches orthologue targets only to genes with no Mtb target of their
own.

## UniChem: the ChEMBL to PubChem bridge

Checked on **2026-10-11** at
`https://ftp.ebi.ac.uk/pub/databases/chembl/UniChem/data/wholeSourceMapping/src_id1/src1src22.txt.gz`:
HTTP 200, 22.8 MB gzipped (`Content-Length 22816479`). One header line, then one
ChEMBL id and one PubChem CID per tab-separated line.

**Licence: CC BY-SA 3.0, inherited.** The file sits in ChEMBL's FTP distribution,
and ChEMBL's release README states CC BY-SA 3.0. UniChem's own README and `data/`
directory state no licence, so the licence recorded here is ChEMBL's, not one
UniChem states itself.

**Why one file.** PubChem keys a screen on CID; ChEMBL keys a compound on
`molecule_chembl_id`. Without a mapping, PubChem AID 1626 cannot reach a ChEMBL
compound. Its `SIDCountAll` is 215,397 tested SIDs, checked live on 2026-10-11
(`https://pubchem.ncbi.nlm.nih.gov/rest/pug/assay/aid/1626/summary/JSON`: source
SRMLSC, "High Throughput Screen to Identify Inhibitors of Mycobacterium
tuberculosis H37Rv"). Its own description says 216,163 compounds were screened, so
the SID count is the figure used here. The alternative is a PubChem lookup per
compound. This file is fetched once and covers the whole mapping. `pubchem.build`
reads it, keeping only the CIDs the screens contain rather than all 2.8M pairs.

**Fan-out, measured on the full file** (2,832,793 pairs, 2,800,246 distinct ChEMBL ids):

- 25,938 ChEMBL ids (0.9%) map to more than one CID. The most is 32 (`CHEMBL1981887`).
- No CID appears twice. The bridge is keyed on CID for that reason, and
  `chembl_by_cid` raises if a CID ever maps to two ChEMBL ids, rather than keeping one.
- Every line has exactly two non-empty fields. The live file has no malformed lines.

The file states no release, so its `source_version` is recorded as `unknown`,
with its retrieval date.

## PubChem BioAssay

The only public source that states an outcome per compound at screening scale.
AID 1626 deposits 209,843 `Inactive` SIDs beside 2,044 `Active` and 3,510
`Inconclusive`, which is what makes "tested and did nothing" a provable answer
rather than an absence.

**Membership is a search, and it is reproducible.** `db=pcassay` through
E-utilities, counted on **2026-10-11**:

| term | AIDs |
|---|---|
| `txid1773[ORGN]` | 12,519 |
| `txid1773[ORGN] NOT ChEMBL[SNME]` | 172 |
| `txid1773[ORGN] AND 10000:100000000[TSC]` | 28 (20 not deposited by ChEMBL) |

The third is the term `fetch_aids` sends. The 10,000-SID floor is this atlas's
choice and it is in the search, not applied afterwards: the 12,519 summaries are 501
requests, and PubChem answered 429 from the 337th and kept answering it. Below the
floor sit BindingDB's re-postings of PDB affinities, which are measurements and not
screens. The taxonomy tag is the only Mtb test, since the summary carries no taxonomy.

**Routes, and why not PUG-REST for the rows.**

- AID list and project links: E-utilities (`esearch`, and `elink` with
  `linkname=pcassay_pcassay_same_assay_project_list`). E-utilities allows 3 requests a
  second without an API key, PUG-REST 5, so every request is paced at 0.34 s.
- Counts and targets: PUG-REST `assay/aid/<aids>/summary/JSON`, 25 AIDs a request.
- Rows: `pubchem.ncbi.nlm.nih.gov/assay/pcget.cgi?query=download&record_type=datatable&actvty=all&response_type=save&aid=N`,
  uncapped (AID 1626 is all 215,397 rows in a 30 MB CSV). **Not PUG-REST**, whose
  `concise/JSON` refuses above 10,000 SIDs with `PUGREST.BadRequest: Too many SIDs`.
  `actvty=all` is what returns the inactives; `actvty=active` would cut AID 1626 to
  about 2,000 rows.

All of this was checked on 2026-10-11, before PubChem began refusing requests from
the build machine that day. The first full build is pending, and `data/raw/pubchem/`
is empty until it runs.

**`SIDCountActive: 0` is not a finding.** PubChem's summary reports 0 actives for
AID 1671170 (Mt-TrpRS, 65,366 SIDs), which read literally is a screen that found
nothing. The depositor never stated a cutoff: all 65,366 SIDs are `Unspecified`. So
`screens.outcome_stated` is stored, `n_active`, `n_inactive` and `n_inconclusive` are
NULL wherever it is false, and `screen_results.outcome` is NULL, never `inactive`, on
every such row. The zero is not always a zero either: six of the eight ChEMBL
deposits report 1 to 90 actives beside an all-`Unspecified` set, which are the IC50
rows, so `SIDCountUnspecified` equal to `SIDCountAll` is what vetoes the calls.

**Three numbers for one screen, and only one is `n_tested`.** AID 1626 deposits
215,397 SIDs (`SIDCountAll`) over 215,098 CIDs, and its own description says 216,163
compounds were screened. `n_tested` is the SID count, the deposited set;
`library_size_stated` keeps the prose figure; neither is substituted for the other.
A CID can sit under several SIDs that disagree (11 CIDs in AID 1626 are `Active` as
one SID and `Inconclusive` as another), so a result row is a SID, not a compound.

**A row is told from its neighbours by its number in PubChem's table.**
`PUBCHEM_RESULT_TAG`, stored as `screen_results.result_tag`, is 1 to N and unique in
both AIDs checked. The SID is not enough: AID 1671170 has 65,646 rows over 65,366
SIDs, because a SID can be measured twice for one endpoint (6 replicate `Percent
Effect` rows and 15 SIDs with two `IC50`), and for 15 of those the value repeats too.
Every build asserts the key `(stage_id, result_tag, activity_id)` is unique, and
that each download holds exactly as many distinct SIDs as the summary counts, since
a truncated download parses as a smaller screen.

**A declared project is one campaign.** PubChem's project links give the funnel the
depositor stated (AID 449775 groups 39 AIDs); 10 of the 20 largest non-ChEMBL
campaigns declare one, and the other 10 declare nothing, which is not the same as
having had no follow-up. A project is one `screens` row named for its lowest member
AID. On 2026-10-11, AIDs 588335 and 588726 both reach 10,000 SIDs and share one.
PubChem does not state the funnel stage: its `Method` is how the outcome was called
(AID 1626, the 215,397-SID primary screen, says `confirmatory`), so the stage is read
from the title and `stages_source` is `from_prose`.

**Where a campaign comes from.** One campaign has exactly one source. A ChEMBL
document that is a publication is ingested from ChEMBL; a deposited dataset (ChEMBL
files Dundee's 1,413,047-row library as a `DATASET`) is ingested from PubChem as
AIDs 1671154 to 1671185. Each row carries its own `source`, `source_version` and
`retrieved_at`, because `screens` is fed by both.

### Licence

Per depositor, not per database. NCBI's policy puts US-government material in the
public domain and then carves PubChem out by name:

> NOTE: This site contains resources which incorporate material contributed or
> licensed by individuals, companies, or organizations that may be protected by U.S.
> and foreign copyright laws. These include, but are not limited to PubMed Central
> (PMC) (see PMC Copyright Notice), Bookshelf (see Bookshelf Copyright Notice), OMIM
> (see OMIM Copyright Status), and PubChem. All persons reproducing, redistributing,
> or making commercial use of this information are expected to adhere to the terms
> and conditions asserted by the copyright holder.

(<https://www.ncbi.nlm.nih.gov/home/about/policies/>, read 2026-10-11.) So
`screens.depositor` is recorded on every campaign and no blanket licence is claimed.
Nothing is redistributed: the pipeline fetches at build time and `data/raw` is
gitignored. `depositor` is stored as PubChem gives it, and is not resolved to a
licence: AID 2060911's is the bare string `11908`.

## RCSB PDB

- **Search API:** `POST https://search.rcsb.org/rcsbsearch/v2/query`
- **Data API:** `https://data.rcsb.org/rest/v1/core/entry/{id}`,
  `.../polymer_entity/{id}/{n}`, `.../nonpolymer_entity/{id}/{n}`
- **Licence:** CC0 1.0 — "data files contained in the PDB archive are available
  under the CC0 1.0 Universal Public Domain Dedication. All data provided by
  RCSB PDB programmatic APIs are available under the same license."

**Verified:** querying
`rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession`
by accession returns 31 entries for DprE1, 135 for InhA, 1 for MmpL3 (`7NVH`) —
slightly more than UniProt's cross-reference lists, which lag. Ligands come from
`nonpolymer_entity` (`comp_id` + name); note `rcsb_entry_info.nonpolymer_bound_components`
is `null` on some entries that *do* have ligands (`4KW5`), so the entity
endpoint is authoritative, not that summary field. Full-text search is unusable
for target lookup: `MmpL3` + organism returns `6T0J`, which is CYP124.

`results_verbosity: "verbose"` is required to get sequence-identity scores back
from a `sequence` service query; the default omits the `services` block.

### A ligand belongs to a chain, not to the entry (M7)

**This is a modification of the upstream data, and the most consequential one
in the pipeline.** An entry's `nonpolymer_entities` list covers the whole
entry. Attributing it to every protein in the entry makes each subunit of a
complex claim its neighbours' chemical matter: in `5UHB` rifampicin is modelled
on chain C, which is rpoB, while rpoA, rpoC, rpoZ and sigA are other chains
entirely. A ligand therefore counts for an accession only when the ligand's
`auth_asym_ids` meet that accession's; the rest are kept in
`ligand_ids_elsewhere`, shown and never counted. Live: 662 of 2,655 structure
rows had been claiming a neighbour's ligand.

**The trap inside the trap.** One accession can own more than one polymer
entity — a precursor processed into alpha and beta chains, as in `6OYY`, where
panD is listed twice and pyrazinoic acid sits on the second entity's chains.
Taking the first entity's chains alone reported "no ligand" for the structure
of pyrazinamide's active metabolite on its own target, across 41 entries. Every
chain an accession owns is pooled before the comparison.

### Has anyone made this protein, and from what?

A structure is itself proof the protein was produced; the deposition says how,
and nothing else in the store does. Four columns on `structures`, all from
fields added to the GraphQL query already being sent — no new source, no new
request.

| Column | From | Populated |
|---|---|---|
| `expression_hosts` | `entity_src_gen.pdbx_host_org_scientific_name` + `_strain` | 4,262 of 4,803 |
| `plasmids` | `entity_src_gen.plasmid_name` | 1,649 |
| `construct_length` | `entity_poly.rcsb_sample_sequence_length` | 4,803 |
| `mutations` | `rcsb_polymer_entity.pdbx_mutation` | 581 |

DprE1 reads: *E. coli* BL21(DE3), pET28a, a 481-residue construct — the whole
protein, not a domain. 134 entries were expressed in *Mycolicibacterium
smegmatis* MC² 155 rather than *E. coli*, which for a membrane protein is the
useful part of the answer.

Three things depositors do that the ingester has to absorb:

- **`pdbx_mutation` states the absence of a mutation in words.** 4KW5 says
  `wild-type`, and others say `none` or `-`. Those are dropped, so a non-empty
  `mutations` always means the crystallised sequence differs from the
  wild-type protein. 1ZID (InhA) keeps `T2A`.
- **The strain appears in either field, or both.** 1ZID gives host
  `Escherichia coli BL21` and strain `BL21`; joining them naively reads
  "Escherichia coli BL21 BL21". The strain is appended only when it is not
  already in the name.
- **Casing is the depositor's.** `ESCHERICHIA COLI UM262` is recorded as
  written rather than tidied, so grouping hosts means normalising at query
  time. The agent's schema note says so.

An empty list means the entry does not state it — common for older
depositions — and never that the protein was not expressed. Entities are
pooled per accession, so panD's alpha and beta chains (6OYY) give one host and
one plasmid, and `construct_length` is the longer chain rather than their sum:
one precursor, expressed once and then cut.

### Chemical components (M7)

- **Query:** `chem_comps(comp_ids: [...])` on the same GraphQL endpoint, 100
  ids per call, for every component id the structures table saw (1,486).
- **What it gives:** the component's name and formula weight, an InChIKey for
  **1,484** of them, and RCSB's own cross-reference to ChEMBL for **546**.
- **What it is for:** a three-character PDB code says nothing on its own. With
  the InChIKey or the ChEMBL id, 151 of them match a compound the atlas already
  holds bioactivity for, and 16 are molecules with a TB indication — which is
  how the atlas can say that the PDB holds rifampicin on rpoB in five entries
  and quabodepistat on dprE1, neither of which ChEMBL's mechanism annotation
  states. Licence unchanged: CC0 1.0, same archive.

**Not verified:** published rate limits. RCSB documents none numerically; the
convention is a few requests per second, backing off on HTTP 429. `fetch`
throttles and retries 429/5xx.

## AlphaFold DB

- **Per-accession API:** `https://alphafold.ebi.ac.uk/api/prediction/{accession}`
  → JSON array with `globalMetricValue` (mean pLDDT), the four
  `fractionPlddt*` bands, `cifUrl`, `pdbUrl`, `paeDocUrl`, `latestVersion`,
  `modelCreatedDate`.
- **Bulk:** `https://ftp.ebi.ac.uk/pub/databases/alphafold/latest/UP000001584_83332_MYCTU_v6.tar`
  — 3,991 structures, 449,242,624 bytes, `Last-Modified: 2025-08-24`. Listed in
  `download_metadata.json` as `type: global_health`. Range requests work (206),
  so the download is resumable.
- **Version:** v6. `P9WJV5` is `AF-P9WJV5-F1`, model created 2025-08-01,
  pLDDT 79.31 (52.8% very high, 18.0% very low — a membrane transporter).
- **Licence:** CC BY 4.0, stated inside each CIF: *"Data in this file is
  available under a CC-BY-4.0 license."*

**Verified gotcha:** `https://alphafold.ebi.ac.uk/files/...` returns **HTTP 403
to requests with no `User-Agent`**. This is why `atlas/fetch.py` sets one
unconditionally for every source.

**Not verified:** published rate limits for the prediction API.

## Essentiality: DeJesus 2017

DeJesus MA, Gerrick ER, Xu W, et al. *Comprehensive essentiality analysis of the
Mycobacterium tuberculosis genome via saturating transposon mutagenesis.* mBio
2017;8(1):e02133-16. PMID 28096490, PMCID PMC5241402, DOI 10.1128/mBio.02133-16.

- **Licence:** CC BY 4.0 (article and supplementary material).
- **Table to use: S3** — `ORF Essentiality Calls`, 4,019 ORFs keyed on Rv tag,
  13 columns, calls from a motif-dependent HMM.
  - `ES` 461, `ESD` 29 (essential domain), `GD` 135 (growth defect),
    `NE` 3,008, `GA` 310 (growth advantage), `Uncertain` 76.
  - Reference targets: **Rv3790 `ES`**, **Rv1484 `ES`**, **Rv0206c `ESD`**.
  - Row 1 is a title and caption; the real header is row 2.
  - Covers 4,018 of 4,031 Mycobrowser CDS loci. The 13 missing are
    `Rv0277A`, `Rv0947c`, `Rv1150`, `Rv1792`, `Rv2023A`, `Rv2098c`, `Rv2099c`,
    `Rv3021c`, `Rv3022c`, `Rv3128c`, `Rv3216`, `Rv2427A`, `Rv2098c`. One ID in
    S3 is not a locus at all (`Rvnr01`).
- **Table S5** is keyed on genomic features, not ORFs, and does **not** contain
  Rv tags — it is not a substitute for S3.

**Download gotcha:** `pmc.ncbi.nlm.nih.gov/articles/instance/.../bin/*.xlsx`
returns an HTML "Preparing to download" interstitial to scripted requests, not
the file. Use Europe PMC instead:
`https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5241402/supplementaryFiles`
→ a zip of all supplementary files (~4.7 MB, slow: about 90 seconds).

**Caveat on meaning:** these are calls from a single *in vitro* condition
(7H9 broth). "Essential, and under which conditions?" is only partly answered by
this one study; conditional-essentiality datasets are a later addition, which is
why the store keys essentiality on `(rv_id, source)` rather than on `rv_id`.

## WHO mutation catalogue

*Catalogue of mutations in Mycobacterium tuberculosis complex and their
association with drug resistance*, 2nd edition, WHO 2023. **This is the latest
edition** — no 2024/2025/2026 edition exists as of 2026-10-09.

- **Data:** `https://github.com/GTB-tbsequencing/mutation-catalogue-2023`
  (the only repository in that organisation), `Final Result Files/`:
  - `WHO-UCN-TB-2023.6-eng_catalogue_master_file.txt` — TSV, 114 columns,
    **48,152 rows**, 37 MB
  - `WHO-UCN-TB-2023.7-eng.xlsx`, `..._genomic_coordinates.txt`,
    `Genomic_coordinates_7May2024.vcf.gz`
- **Licence: ODC-By 1.0** — `Final Result Files/LICENSE.md`: "All data published
  here, in excel or VCF format, are licensed under the Open Data Commons
  Attribution License (ODC-By) v1.0." The repository itself is MIT.
- **Key columns:** `drug`, `gene`, `mutation`, `variant`, `tier`, `effect`,
  `genomic position`, `FINAL CONFIDENCE GRADING`.
- **Grading:** `1) Assoc w R` 253, `2) Assoc w R - Interim` 1,130,
  `3) Uncertain significance` 33,906, `4) Not assoc w R - Interim` 12,379,
  `5) Not assoc w R` 484.

**Scope limit, and it matters.** The catalogue covers **65 genes** — those with
matched phenotypic DST — keyed by **gene symbol, not Rv tag**. `inhA` has 520
rows (3 graded `1) Assoc w R`); `Rv0678` has 453. **Neither `dprE1` nor `mmpL3`
appears at all.** No amount of ingestion will populate WHO resistance data for
two of the three reference targets; the atlas reports an honest absence, and the
M1 acceptance criteria were adjusted accordingly.

Joining to the gene universe is by gene symbol → Rv tag, which works because the
65 symbols are all standard (`katG`, `rpoB`, `gyrA`, …) or are themselves Rv tags
(`Rv0678`, `Rv1258c`, …).

## Vulnerability: Bosch 2021

Bosch B, DeJesus MA, Poulton NC, et al. *Genome-wide gene expression tuning
reveals diverse vulnerabilities of M. tuberculosis.* Cell 2021;184(17):
4579-4592.e24. PMC8382161, doi 10.1016/j.cell.2021.06.033. **CC BY 4.0**
(stated in the article's JATS `<permissions>` block and confirmed by Crossref).

- **File:** `https://ars.els-cdn.com/content/image/1-s2.0-S0092867421008242-mmc3.xlsx`
  — 3,088,676 bytes, verified byte-identical to the copy inside the Europe PMC
  zip. PMC's own supplementary path returns a 1,817-byte HTML interstitial to
  scripted requests, and the Europe PMC zip is 50 MB for the same file.
- **Key:** `locus_tag` is **`RVBD3790`, not `Rv3790`**. The `c` suffix survives
  (`RVBD0206c`), so the transform is a prefix swap.

**Four sheets, three of them used.**

| Sheet | Rows | Table | Note |
|---|---|---|---|
| `(1) Mtb H37Rv` | 4,052 | `vulnerability` | 28 columns, 4,005 `RVBD*` genes plus 47 RNA features |
| `(2) Mtb HN878` | 4,049 | `strain_vulnerability` | identical 28 columns, the same series in a clinical isolate |
| `(3) Msmeg` | — | **not ingested** | `MSMEG*` tags; reaching an Rv id needs an orthologue mapping this atlas does not have, and building one would attribute a surrogate's measurement to an Mtb gene |
| `(4) Mtb diff vuln` | 512 | `strain_vulnerability` | the authors' own H37Rv-vs-HN878 differential, joined onto sheet 2 |

**Why this matters more than essentiality.** TnSeq answers "can this gene be
deleted" — yes or no. CRISPRi titration answers "how much of this protein can
the organism lose before it suffers", which is the question an inhibitor
actually poses: a drug reduces a target, it rarely removes one. Three genes
can all be `ES` and differ by orders of magnitude in required engagement.

The index is negative; more negative is more vulnerable. Reference targets,
all flagged `certain`: **MmpL3 −11.01, InhA −9.91, DprE1 −9.42**, and for
contrast KatG +0.96, not certain.

**`certain` is the authors' own flag** for a confident estimate and is true for
only 594 of 4,005 genes. It is carried alongside the index rather than used to
filter, so the UI can show an uncertain number as uncertain.

Bonus: the sheet's `antibacterial` column names the drug already targeting each
gene — SQ109→mmpL3, PBTZ169→dprE1, Q203, bedaquiline, rifamycins and others.
That is a machine-readable, openly licensed list of validated TB targets, which
is exactly what the newtbdrugs pipeline page could not supply.

### Does it hold in a clinical strain?

H37Rv has been in culture since 1905. HN878 is a Beijing-lineage clinical
isolate, and sheet 2 runs the same knockdown series in it: 4,002 genes reach an
Rv locus, 579 of them `certain`. **This is the only axis in the atlas that
tests whether a target's vulnerability is a property of the organism or of the
lab strain.**

- `delta_vi` is the authors' own, from sheet 4, and runs **HN878 minus H37Rv**.
  The index is negative-is-vulnerable, so a **positive delta means *less*
  vulnerable in the clinical strain**. accD6: −11.45 in H37Rv, −2.27 in HN878,
  delta +9.19, `certain` in both. purK and pmmA do the same thing.
- It runs the other way too. panD (−4.07 → −9.28) and panC (−3.93 → −9.00,
  40 structures and 123 compounds already) are substantially *more* vulnerable
  in the clinical strain, along with the rest of the pantothenate pathway.
- `delta_vi_norm` is **not** a rescaling of `delta_vi`: for inhA the two
  disagree in sign (+0.382 raw, −0.286 normalised). Neither is derivable from
  the other, so both are carried.
- **The differential covers 507 genes, not every gene.** All 507 are `certain`
  in both strains, but so are 576 genes — the authors selected a subset on
  grounds the sheet does not state, so the atlas carries their selection rather
  than reconstructing a threshold. `differential_reported` distinguishes "they
  reported no difference" from "they reported none for this gene", and a gene
  absent from sheet 2 altogether (2 in the gene universe) is a third state
  again: never measured in HN878.

## Conditional fitness: Griffin 2011

Griffin JE, Gawronski JD, DeJesus MA, Ioerger TR, Akerley BJ, Sassetti CM.
*High-resolution phenotypic profiling defines genes essential for mycobacterial
growth and cholesterol catabolism.* PLoS Pathog 2011;7(9):e1002251. PMC3182942,
doi 10.1371/journal.ppat.1002251. **CC BY**, confirmed through Europe PMC's
`license` field on 2026-10-10.

The first answer in the atlas to "essential *under which conditions*". Every
essentiality number until now carried the caveat that DeJesus 2017 is one
condition — 7H9 broth. Cholesterol is the carbon source *M. tuberculosis* uses
inside a macrophage, so a gene required on cholesterol and not on glycerol is
one the broth screen cannot see.

- **Download:** the same Europe PMC route as DeJesus 2017,
  `https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3182942/supplementaryFiles`
  — a 7.9 MB zip of all supplementary files, about 60 seconds.
- **Table S3** (`ppat.1002251.s003.xlsx`, sheet `supp table 3`): 3,987 gene
  rows keyed on `Locus`, the Rv tag. The title and legend occupy the first
  seven rows and the column names run over rows 8 and 9, so the header is row
  9. Carries normalized reads per insertion in each carbon source, the
  cholesterol/glycerol ratio and a t-test p value.
- **Table S4** (`ppat.1002251.s004.xlsx`): the authors' own list of **96 genes
  specifically required for growth on cholesterol**. The atlas flags those
  rather than drawing its own line through the ratio, for the same reason it
  carries Bosch's `certain` flag.
- **Coverage:** 3,985 of the 3,987 loci are in the gene universe (`Rv0061` and
  `Rv1784` are not). 3,185 rows carry a ratio; p values all fall in (0, 1).

**The blind spot, which is the whole point of recording `measured`.** A
transposon screen compares insertion counts between conditions, and a gene that
tolerates no insertions has nothing to compare. Every in-vitro-essential gene is
such a gene: `dprE1`, `inhA`, `mmpL3` and `katG` all read `n/a`. The store
records `measured = false` for them, and **not one of the 96 cholesterol-required
genes is also called essential by DeJesus** — the two screens are structurally
disjoint. A gene absent from the table altogether is `NULL`, a third state
meaning it was never screened.

**`Required in vivo` is not this paper's measurement.** The column carries
Sassetti & Rubin 2003 (PNAS 100:12989-12994), a mouse screen, 193 genes. It is
stored with its own citation so the attribution does not drift.

## STRING

- **Version:** v12.5 (since 2026-09-29; v12.0 is archived).
- **Files:** `https://stringdb-downloads.org/download/protein.links.detailed.v12.5/83332.protein.links.detailed.v12.5.txt.gz`
  (10,248,889 bytes) and the matching `protein.info` file (443,953 bytes).
- **Licence: CC BY 4.0**, stated explicitly: "All data and download files in
  STRING are freely available under a 'Creative Commons BY 4.0' license",
  covering "tables, data files, individual scores and data points". STRING also
  asks that bulk users take the flat files rather than the API, which is what
  this does.
- **Key:** `string_protein_id` is literally `83332.Rv0001`. Strip the prefix and
  4,026 of 4,026 are Rv tags. This is the only source in the pipeline that keys
  with nothing but a prefix strip.

The ingester keeps edges with `combined_score >= 700` — STRING's own
high-confidence cut — which leaves 28,739 unordered pairs over 3,375 genes out
of 1.39M raw edges, most of which are low-confidence text mining. **The
download lists every edge twice** (A→B and B→A); emitting both would double
every partner count. Per-channel scores are kept, because an edge supported
only by text mining is a far weaker claim than one with experimental support
and the combined score hides which it is.

## Human homology

A target whose closest relative is human is a selectivity problem first. **No
public resource publishes this for Mtb in a downloadable form:**

- UniProt exposes **no** orthology or UniRef field on UniProtKB — `uniref_cluster_50`
  is rejected as an invalid field, and a cross-taxon UniRef query
  (`taxonomy_id:83332 AND taxonomy_id:9606`) returns 0 results, as does the
  human/mouse control, so that field is not a member index.
- OrthoDB's current download path returns 403; v11's files are 1.8 GB and 21 GB.
- eggNOG 7's family files are ~1 GB.
- InParanoiDB 9's download is a CSRF-protected Django form that returns HTML,
  not a file, to every scripted attempt.
- DIAMOND and BLAST are not installed in this environment.

**Tried first and abandoned: UniRef co-membership.** Four bulk UniProt
ID-mapping jobs, both proteomes into UniRef90 and UniRef50, cluster ids
intersected. It returned **zero human homologs across all 3,978 accessions**.
UniRef50 clusters at 50% identity to the representative, and Mtb–human
homology mostly lives at 25–40%: GroEL2 (`P9WPE7`) and human HSPD1 (`P10809`),
textbook homologs, land in different UniRef50 clusters. A column that says
"no" to every gene reads as reassurance, so it was removed.

**What this pipeline does instead:** `phmmer` (via `pyhmmer`, a pip package —
no system tooling) searches each Mtb protein against the **reviewed** human
proteome (`UP000005640`, reviewed only: the unreviewed set is mostly isoforms
and fragments). The best hit at E ≤ 1e-5 is kept with its E-value, bit score,
coverage and a percent identity computed from the aligned columns. A hit at
≥ 30% identity is flagged `close_human_homolog`; that line is this atlas's
convention, which is why the identity is always shown beside the flag. GroEL2
comes back 48% identical to HSPD1. Both proteomes are UniProt, CC BY 4.0.

## Paralogs: functional redundancy

No download, no new source: the same `phmmer` machinery pointed at the Mtb
proteome instead of the human one, reusing the cached FASTA. 15.8 s for
3,997 x 3,997.

An essential, vulnerable, structurally tractable gene with a close paralog is a
different proposition from the same gene standing alone. Inhibit one copy and
the other may cover for it — and the compound then looks inactive for a reason
that has nothing to do with the chemistry. It was the first thing after
essentiality that the store could not answer.

**The flag is deliberately stricter than the human one, and that is the whole
design.** `close_human_homolog` fires on identity alone, because a shared
domain is already a selectivity worry for an off-target. A *backup copy* has to
be the same protein, not share a piece of it, so `close_paralog` requires
**≥ 30% identity over ≥ 70% of the query**. The difference is not cosmetic:

| rule | genes flagged | dprE1 | mmpL3 | groEL2 |
|---|---|---|---|---|
| identity ≥ 30% alone | 2,009 | yes (30.8% / 37% cov) | yes (31.7% / 21% cov) | yes |
| identity **and** coverage | 1,346 | no | no | yes (62% / 98% cov) |

dprE1 and mmpL3 both have family members and neither has a backup; groEL2 has
groEL1 at 62% over 98% of the protein, which is real redundancy. Median
coverage among 30%-identity best hits is 0.68, so the threshold discriminates
rather than rubber-stamps. This is the UniRef50 lesson in another costume: a
family-level link is not evidence that two proteins do the same job.

**Two different "closest" columns, and conflating them is the trap.**
`closest_paralog_gene` is the nearest *backup* and is NULL when there is none,
even though relatives exist. `nearest_relative_gene` is the nearest *relative*
and is usually populated anyway — mmpL3 reads `mmpL13b` at 31.5% over 47%. It
is ranked by bit score rather than identity, because ranking by identity
crowns a short exact fragment over a full-length near-copy: mmpL3's answer
under identity ranking was mmpL1 over a fifth of the protein.

Three things are dropped, each for a reason:

- **Self-hits.** A protein's best hit against its own proteome is itself at
  100%.
- **Identical sequences under two accessions.** Those are annotation artefacts
  — the `shared_accession` case the crosswalk already records, 55 loci
  including the IS6110 transposase across 16. Left in, each would be the
  other's perfect full-length "backup" and the flag would fire on every one.
- **Hits weaker than E ≤ 1e-5**, phmmer's own reporting threshold.

What it immediately buys: 489 essential genes, of which **87 have a
full-length backup copy and 402 do not**. The 87 are worth knowing about —
kasA/kasB at 66%, nrdF2/nrdF1 at 71%, glyA1/glyA2 at 68%, groEL2/groEL1 at
62%. And the atlas can now answer a question it could not form before:
**129 genes are essential, have no backup copy, have no close human homolog,
and have a structure.**

## Orthologue structures: a structure to work from

**3,146 CDS genes have no experimental structure under their own accession, and
that is reported as the absence it is. But "no structure" and "nothing to work
from" are different claims**, and MmpL3 is the standing example: one Mtb entry
at 3.0 Å with one ligand, against 18 *M. smegmatis* MmpL3 entries whose best is
2.15 Å and eleven of which were solved with something bound. The ChEMBL
orthologue bridge already reaches that protein for its *ligands*
([above](#the-orthologue-bridge), via `UniRef50_A0QP27`); its *structures* were
invisible, because `structures` is keyed on the Mtb accession and nothing
mapped the neighbour back.

One download (the 895 Mycobacteriaceae proteins, excluding H37Rv, that have a
PDB cross-reference), 5.8 s of phmmer, and the entries themselves from RCSB
through the same code path `structures` uses — so a borrowed entry gets the
same chain-level ligand attribution, and a ligand on a neighbouring chain is
not counted for it either.

### Two findings, different strengths, not flattened

`relation` says which claim a row makes.

| relation | genes | means |
|---|---|---|
| `same_sequence` | 124 | the deposited sequence is **identical** to the Mtb one, filed under another accession |
| `orthologue` | 721 | a related mycobacterial protein, with the identity and coverage on the row |

**The `same_sequence` case is a key artefact, not a modelling exercise.** 34
genes the atlas called structure-less have a 100%-identical structure deposited
against a CDC 1551, H37Ra or *M. bovis* accession. folC (`Rv2447c`, `I6Y0R5`)
has none of its own and two under `O53174` — 2VOR at 2.3 Å with ACP bound, 2VOS
at 2.0 Å. The structure *is* of this protein; only the key hid it.

**The `orthologue` case makes no claim beyond the numbers.** Whether a
34%-identical structure is worth opening is the reader's judgement, so identity
and coverage sit on every row and in the UI, and nothing here is described as a
model, a template or a druggability signal.

### Thresholds, and the one false positive worth a rule

The floor is **≥ 30% identity over ≥ 70% of the query**, the same pair as
[`close_paralog`](#paralogs-functional-redundancy) and for the same reason: a
structure is only worth borrowing if it is of the same protein rather than of
something that shares a domain. 30% is also the conventional floor for a usable
homology model. Both numbers are on every row, so a stricter line can be drawn
downstream.

`same_sequence` needs no threshold — identity and coverage are exactly 1.0, and
nothing in the data sits between 0.999 and 1.0. It does need one guard:
`O07717` (398 aa) matches at 100% identity over its whole length *inside*
`Q8VJU4` (766 aa), which is a different, longer protein that contains it. 3 of
165 perfect pairs look like this, so a perfect match also has to span ≥ 80% of
the *target*. When query coverage is already 1.0 that is the query/target
length ratio, so it is the same measurement from the other end rather than a
new rule.

### What it does not touch

**Nothing here feeds `n_pdb`, `has_structure` or `structural_gap`.** Those
count structures of the gene's own protein and have to keep meaning that, or a
zero in the column the atlas exists to answer stops meaning zero. The borrowed
entries are also deliberately kept out of the 3D viewer: the residue numbering
is the neighbour's, so overlaying a gene's WHO-graded residues on one would
place them wrongly.

### What it buys

Of 3,146 genes with no structure of their own, **449 have a mycobacterial
neighbour that does and 227 of those neighbours were solved with a ligand
bound**. Among the 489 essential genes: 234 have no structure of their own, 44
have a borrowed one, 22 of those with a ligand, and 6 are `same_sequence`
rescues (folC, glgE, trpE, murC, ribA2, `Rv0543c`). trpE is the shape this was
built for — essential, vulnerability −6.36, no structure under its own
accession, and two entries at 1.7 Å with ligands under an identical sequence.

### Freshness

`orthologue-pdb` is **not** frozen, unlike the two phmmer siblings: the bridge
is computed here, but the structures on the far end come from RCSB and move
weekly. The probe replays the neighbour search and counts entries, the same
detector as `rcsb-pdb`, and compares against `version_label()` — the single
function that also stamps the table, so the probe cannot drift from the
statement it is checking. A neighbour gaining its *first* structure arrives as
a new sequence in the filtered UniProt stream, so the `uniprot` probe is what
notices that.

## Drug precedent: has this fold ever been drugged?

`docs/data-sources.md` has carried an open question since M1 —
[druggable pockets](#druggable-pockets--unresolved), which no public source
answers. **This is not that answer.** It is the one sourced thing in its
neighbourhood: a count of the drugs ChEMBL records against *some other* protein
that carries the same Pfam domain as this gene. "Twenty-one approved drugs are
filed against proteins with this domain" is a fact about a database. Whether
that makes the gene druggable is the reader's call, which is why every row
names the drug, its phase, the protein it actually acts on, and that protein's
organism.

### Pfam, not ChEMBL's own protein classification

ChEMBL publishes a protein family tree and assigns every target component to
it, which looks like the obvious key. It is not: **only 199 of the 4,031 CDS
genes are a ChEMBL target component at all**, and those are the genes that
already have chemistry — precisely the ones a precedent signal is least needed
for. Pfam is annotated on **3,531** of them, in the UniProt stream the atlas
already downloads, and ChEMBL publishes a Pfam cross-reference on its own
components (2,215 of 2,283 carry one). So both ends of the bridge are a domain
accession rather than a name match, and the reach is 18× wider.

### The fetch

Four sequential steps, each page cached like the rest of the drug layer, ~110
requests in all:

| Step | Endpoint | Count |
|---|---|---|
| Every drug–target mechanism in ChEMBL | `mechanism.json` | 7,561 |
| The targets those point at | `target.json?target_chembl_id__in=` | 1,518 |
| Those targets' components, for their Pfam xrefs | `target_component.json?accession__in=` | 2,283 |
| Names for the drugs that survive the filter | `molecule.json?molecule_chembl_id__in=` | 1,159 |

`mechanism.json` carries `max_phase` itself, so the phase of a precedent costs
no extra request. Rows are then restricted to the **325** domains Mtb proteins
actually carry, which takes the table from 34,561 rows over 1,403 domains to
**9,603 over 325** and loses nothing that could ever reach a gene.

One row per distinct claim — (domain, protein, drug, target, mechanism) — with
`mec_id` naming the earliest ChEMBL record that states it. Not one row per
`mec_id`: ChEMBL files a mechanism per salt, so folding salts into their parent
the way the drug layer does would otherwise print daunorubicin, its
hydrochloride and its citrate as three identical rows about human topoisomerase
II.

### Two exclusions, and both are the difference between a number and a misreading

**A gene is not its own precedent.** The roll-up drops rows whose component
accession is the gene's own. dprE1 is the case: its PF04030 rows are macozinone
and TBA-7371, which are phase 2 *against dprE1*. They are already in `n_drugs`;
counting them again as evidence that dprE1's fold can be drugged would make the
column self-confirming. It changes 8 genes genome-wide, and those 8 are exactly
the ones where it would have been circular.

**Only `SINGLE PROTEIN` targets count.** This is the rule `n_complex_drugs`
already follows, applied one level out. ChEMBL files the ribosome's approved
drugs against a `PROTEIN NUCLEIC-ACID COMPLEX` that names every subunit, so
counting those hands chloramphenicol to rplC's fold as precedent; 4,485 of the
9,603 rows are that one complex. `PROTEIN FAMILY` is the same problem in
another shape — cobicistat is filed against "Cytochrome P450 3A", which names
several accessions and attributes the drug to none of them. The rows are kept
and shown, never counted, and `n_precedent_complex` is how many there are:
**200 genes have no precedent except through a complex or a family**, and
reading them as drugged folds would be the single biggest error this table
could cause.

| `target_type` | rows | counted |
|---|---|---|
| `PROTEIN NUCLEIC-ACID COMPLEX` | 4,485 | no |
| `PROTEIN FAMILY` | 1,547 | no |
| `PROTEIN COMPLEX GROUP` | 1,526 | no |
| `SINGLE PROTEIN` | 1,153 | **yes** |
| `PROTEIN COMPLEX` | 888 | no |
| `SELECTIVITY GROUP` | 4 | no |

### A shared domain is not a shared binding site

The same caveat UniRef50 carries in `CLAUDE.md`, and it is answered the same
way: by showing the numbers rather than by building them into the count.

- **The domain is named.** `precedent_pfam_name` is on the gene row and on
  every detail row.
- **Its breadth is named.** `precedent_domain_genes` is how many Mtb genes
  carry it. The median precedented domain covers **one** gene, the 90th
  percentile seven, and `PF00005` (ABC transporter) covers **37** — a precedent
  there is a statement about a superfamily, and four essential genes read 7
  approved drugs from it, every one a CFTR modulator.
- **The human share is named.** `n_precedent_human_target` counts the approved
  drugs whose target is human (tax 9606). 39% of rows are, and for **340 genes
  every approved precedent is human** — where tractable chemistry and a
  selectivity problem are the same fact, next to the `close_human_homolog`
  column that says the same thing from the sequence end.

PIKfyve is the worked example of why the row detail matters: it is a human
lipid kinase that genuinely carries `PF00118` (Cpn60_TCP1), so apilimod shows
up as clinical precedent for groEL2's fold. The annotation is correct and the
inference would be absurd — which the reader can see, because the row says
"APILIMOD · phase 2 · 1-phosphatidylinositol 3-phosphate 5-kinase · *Homo
sapiens*".

### What it buys

**519 of the 4,031 CDS genes have at least one approved drug filed against
another single protein that shares a domain with them**, and 475 have one in
clinical phases. **479 of those 519 have no ChEMBL target of their own**, so
for them this is information the atlas could not previously produce at all, and
487 have no ligand of their own. 3,012 genes have a domain and a precedent of
exactly zero, which is a measured zero; 500 have no Pfam annotation and read
NULL, because nothing to look up is not nothing found.

Among the 489 essential genes, 88 have approved precedent, 75 of those have no
ligand of their own, and 61 of the 88 have precedent only from human proteins.

The reference genes behave as a TB chemist would predict:

| Gene | Domain | Approved | Clinical | What the precedent is |
|---|---|---|---|---|
| inhA | `PF13561` adh_short_C2, 19 Mtb genes | 2 | 3 | Triclosan and hexachlorophene on *E. coli* FabI; afabicin, AFN-1252 and CG-400549 in phase 2 on the *S. aureus* and *B. pseudomallei* enzymes. Isoniazid and ethionamide are excluded — they are on inhA itself |
| dprE1 | `PF01565` FAD_binding_4, 13 Mtb genes | 1 | 0 | Triparanol on human Δ24-sterol reductase. All of it human, which is a selectivity warning as much as a precedent |
| mmpL3 | `PF03176` MMPL, 14 Mtb genes | **0** | **0** | Nothing. No drug in ChEMBL is filed against any MmpL protein, anywhere — a measured zero on the most vulnerable of the three reference genes |
| folP1 | `PF00809` Pterin_bind, 3 Mtb genes | 21 | 1 | The entire sulfonamide and sulfone class, on dihydropteroate synthases of other organisms. Essential, no ligand of its own |

### Freshness

No new probe. Every fact in the table is ChEMBL's and the table is stamped with
ChEMBL's release, which is the version the existing `chembl` probe already
checks; `atlas refresh chembl` runs from the identity stage and rebuilds this
with the rest. The Mtb side of the bridge is `proteins.pfam_ids`, so a
Mycobrowser or UniProt release moves it through those sources' own probes.

## ChEMBL: TB drugs and mechanisms

The clinical end of the atlas starts here. Same release and licence as the
rest of ChEMBL (CC BY-SA 3.0, IDs preserved, release displayed).

- **Indications:** `drug_indication.json?mesh_heading__icontains=tuberculosis`
  → **187 indications** over **112 parent molecules**. MeSH headings seen:
  Tuberculosis (109), Tuberculosis, Pulmonary (50), Multidrug-Resistant (22),
  Meningeal (6). `Mycobacterium Infections` (10) and the MAC headings (16) are
  broader than TB and are left out. Filtering on `efo_term` returns the same
  187 rows.
- **Phase:** `max_phase_for_ind` is the phase *for that indication* (a string,
  `"4.0"`). The atlas keeps it as `max_phase_tb`, apart from the molecule's
  `max_phase` for any indication: linezolid is approved, and phase 3 for TB.
  Of the 112, 22 are approved for TB, 32 are phase 3, 45 phase 2, 13 phase 1.
- **Trial references:** an indication's `ClinicalTrials` ref packs every NCT id
  into one comma-separated `ref_id` — 316 such refs naming 262 distinct trials.
  Other refs are DailyMed, FDA, EMA and ATC labels.
- **Salts:** 42 indications name a salt (`CHEMBL2105700`, bedaquiline
  fumarate) whose `parent_molecule_chembl_id` is the drug. Everything is keyed
  on the parent; salt ids and names are kept as synonyms.
- **Mechanisms:** `mechanism.json?molecule_chembl_id__in=...` → 94 records over
  49 targets (92 after de-duplicating salt and parent). **41 of the 112 have
  no mechanism at all**, including BTZ-043, quabodepistat, SQ109, telacebec,
  pretomanid and TBAJ-876.
- **Targets:** `target.json?target_chembl_id__in=...` gives organism, `tax_id`,
  type and component accessions. Only 12 molecules have a mechanism on an
  *M. tuberculosis* target. Rifampicin, rifapentine and rifabutin point at
  `CHEMBL2364672`, a *Bacterial* RNA polymerase built from *E. coli*
  accessions. The fluoroquinolones point at *S. pneumoniae* gyrase and
  topoisomerase IV. Bedaquiline points at Mtb ATP synthase as an eight-subunit
  `PROTEIN COMPLEX`, and sutezolid, capreomycin and pyrazinamide at the Mtb 70S
  ribosome (60 components).
- **The set is unedited:** ChEMBL reads indications off trial records, so the
  112 include host-directed adjuncts (glucocorticoids, NSAIDs, statins), HIV
  co-medications, BCG, tuberculin and placebo excipients ("lactose, anhydrous"
  at phase 3). They are kept and made filterable — `acts_on_mtb` (12),
  `host_targeted` (23), `atc_codes` (22 carry a J04 antimycobacterial code) —
  rather than curated away.
- **Gotcha:** the API sometimes answers a JSON request with an HTML error page.
  `fetch(..., json_body=True)` treats that as transient and never caches it.

**How a drug reaches a gene** (`atlas/clinical.py`, `drug_genes.link`):

| Link | Meaning | Live count |
|---|---|---|
| `mechanism` | ChEMBL's mechanism names this gene's protein as the single-protein target | 9 links, 8 drugs, 7 genes |
| `mechanism_complex` | ChEMBL names a complex this protein belongs to — not evidence it binds this subunit | 179 links, 4 drugs, 65 genes |
| `bosch_2021` | Bosch 2021's `antibacterial` column, matched exactly to a ChEMBL synonym | 12 links, 8 drugs, 12 genes |
| `who_resistance` | WHO-graded resistance variants in this gene for this drug — **not** target engagement | 33 links, 15 drugs, 24 genes |
| `structure` | The drug is modelled on this protein's own chain in a PDB entry — physical evidence they meet, still not a mechanism claim | 17 links, 13 drugs, 15 genes |

Only `mechanism` and `bosch_2021` count as a drug acting on the gene: **11
drugs land on 13 genes**. A co-crystal is shown beside them and never counted:
EthR is a repressor that binds many ligands in soaking studies, so 5NZ0 holding
linezolid says nothing about linezolid's target. It does, though, place
rifampicin on rpoB (5 entries) and quabodepistat on dprE1 (43FX) where no
curated mechanism can. A mechanism target from another organism links no
Mtb gene; bridging rifampicin to rpoB by homology would state something ChEMBL
does not. rpoB still meets rifampicin through the WHO catalogue, as resistance.

**Anti-TB drugs the public structured data cannot place on a gene** (25): the
rifamycins (non-Mtb target), delamanid and pretomanid (prodrugs; organism-level
or no target), capreomycin and the oxazolidinones (ribosome complex or non-Mtb
ribosome), clofazimine (DNA), and BTZ-043, quabodepistat, TBAJ-876, TBAJ-587,
TBI-223, TBA-354 and GSK-2556286 (no mechanism in ChEMBL 37). Each still has its
drug page, phase and trials; it is the gene link that is absent, and the UI
says so.

## ClinicalTrials.gov

- **API:** `https://clinicaltrials.gov/api/v2/studies?query.cond=tuberculosis&filter.advanced=AREA[StudyType]INTERVENTIONAL&fields=...&pageSize=1000`,
  paged by `nextPageToken`. **1,152 studies** on 2026-10-10 (1,665 with
  observational; `query.term` returns 2,449). Version from `/api/v2/version`:
  `apiVersion 2.0.5`, `dataTimestamp 2026-10-09T09:00:05`.
- **Terms** (ClinicalTrials.gov Terms and Conditions, last modified
  2023-01-31; the page renders client-side, so the text was read from the
  site's own bundle): data are available to all requesters at no charge. In
  any publication or distribution you should attribute ClinicalTrials.gov,
  keep the data current, clearly display the date the data were processed by
  ClinicalTrials.gov, and state any modifications. No proprietary rights may be
  asserted, and extracted email addresses may not be used for marketing. Data
  carry international copyright outside the US, and some may be subject to
  third-party copyright.
- **How this pipeline complies:** it fetches at build time and commits only
  test fixtures. `source_version` carries the `dataTimestamp`, which the UI
  shows next to every trial. Contacts are never requested. **Modifications,
  stated:** a subset of fields is kept; phases gain a number for sorting
  (early phase 1 = 0.5, "NA" = none); 15 studies whose conditions are solely
  nontuberculous mycobacterial disease are dropped; nothing else is
  rewritten.
- **Quirks:** dates are often partial (`2018-06`) and are kept as given. The
  condition search also matches "Non-tuberculous" (15 NTM studies, now
  excluded). Another 60 list no TB condition at all. Most are TB studies by
  title — vaccine trials in "Healthy" volunteers, TMC207 in hepatic impairment.
  A few are adjacent, such as pleural-effusion diagnostics and TB-service
  integration. All 60 are kept, because a condition list is not a reliable
  test of scope.
  Phase "NA" (411) is behavioural, diagnostic and device studies.
- **Scope after exclusion:** 1,137 trials. 104 phase 4, 178 phase 3, 253
  phase 2, 182 phase 1, 9 early phase 1.

**How a trial reaches a drug** (`trial_drugs`): ChEMBL's own curated NCT
reference (`via_chembl_ref`), or an exact match of a cleaned intervention name
to a ChEMBL synonym (`via_intervention_name`). Cleaning splits combinations,
takes parentheticals as alternatives, and strips doses and dosage forms. An
intervention's other names are consulted only when its own name matches
nothing, because sponsors list classes there: NCT02651259 gives rifapentine the
other name "Rifamycin". A name two molecules share links neither, and `matched_names` records the
string that actually matched -- for a fallback, the other name rather than the
intervention's own, so a link never cites a string that does not name the drug.
Live: **483 of 1,137 trials** link to at least one drug, over 1,183 trial-drug
pairs: 547 found both ways, 76 by reference only, 560 by name only. ChEMBL
references 3 trials outside this search, and those links are dropped rather
than left dangling.

## Rejected: the TB clinical pipeline

`newtbdrugs.org/pipeline/clinical` is HTML only: no tables, no JSON-LD, no
CSV/JSON endpoint, and `/api/pipeline`, `/pipeline.json` and `/wp-json/...` all
404. The compound names are in the markup but **the target annotation is not** —
grepping for `dprE1|MmpL3|InhA|QcrB` returns zero hits on the clinical page. A
separate `/pipeline/drug-targets` page lists targets as free text with no
identifiers and inconsistent casing. The footer reads "©2016 Working Group on
New TB Drugs. All Rights Reserved" — no open licence.

Not ingested. The validated-target information the atlas needed is available,
openly licensed, from Bosch 2021's `antibacterial` column instead. The phases
and trials of the clinical pipeline now come from ChEMBL's TB indications and
ClinicalTrials.gov, above, both with clear terms.

## Conditional TnSeq: MtbTnDB

Jinich A, Zaveri A, DeJesus MA, Spencer A, Almada-Monter R, Flores-Bautista E,
Smith CM, Sassetti CM, Rock JM, Ehrt S, Schnappinger D, Ioerger TR, Rhee KY.
*The Mycobacterium tuberculosis Transposon Sequencing Database (MtbTnDB): a
large-scale guide to genetic conditional essentiality.* Mol Microbiol
2025;124(1):91–101. doi 10.1111/mmi.15370, PMC12242109, PMID 40527579.

Everything below was checked against the live services on **2026-10-10**.

### The licence question, answered — but not where you would look

Three artifacts, and only two of them are licensed:

| Artifact | Where | Licence | Used |
|---|---|---|---|
| Paper | [doi.org/10.1111/mmi.15370](https://doi.org/10.1111/mmi.15370) | **CC BY 4.0**, verbatim: *"This is an open access article under the terms of the Creative Commons Attribution License"* | cited by every row |
| Raw TRANSIT output | Zenodo [10.5281/zenodo.13937393](https://doi.org/10.5281/zenodo.13937393) (concept DOI → latest) | **CC BY 4.0**, `cc-by-4.0` in the record metadata, access `open` | **yes** — the numbers |
| Screen annotation | `data/col_desc_dash.tsv` in `github.com/ajinich/mtb_tn_db`, pinned to the paper's commit | repo states **none effective**; used on the article's CC BY plus factual compilation — see below | **yes** — the conditions |
| Processed data tables | same repository | same | **no** — cannot support `measured` |

The repository **still has no LICENSE file**: `LICENSE`, `LICENSE.md`,
`LICENSE.txt`, `COPYING` and `license` all return 404 on raw.githubusercontent,
and the GitHub API reports `license: null`. The README nonetheless states *"This
project is licensed under the MIT License"* and links to that missing file.

That shapes what is taken from where. The **numbers** come from the CC BY Zenodo
deposit, which is also the only artifact that can support the atlas's honesty
rule. The **screen annotation** is one small file from the repository, used on
the article's own CC BY and on its being a compilation of facts about published
experiments — the reasoning is under "The condition annotation" below. The
repository's processed data tables are **not** used at all.

Current Zenodo version: `10.5281/zenodo.15284946`, 2025-04-20,
`transit_outputs_mtbtndb.tar.gz`, 267,217,387 bytes, sha256
`614d0535e09edba7267a1a8b3c81aee07a54ae980c49e1bb0e1be99e6471ae33`. Creators
Jinich and DeJesus. Use the **versioned** DOI as `source_version`; the concept
DOI always resolves to the newest and would make the stamp drift.

Contents: `Results/`, 1,969 `result_resampling_<experimental>_vs_<control>.txt`
files plus a batch log. **No `.wig` files and no `prot_table`** — position-level
insertion data is not in the deposit, which matters below.

### Why the processed table cannot be used, and the raw output can

`data/standardized_data_dash.tsv` (59 MB, keyed on Rv tag) has exactly eight
columns: `Rv_ID, gene_name, Description, Expt, log2FC, q-val, q_val_D,
annotation_score`. The TRANSIT output it was built from has twelve:

```
#Orf  Name  Desc  Sites  Mean Ctrl  Mean Exp  log2FC  Sum Ctrl  Sum Exp  Delta Mean  p-value  Adj. p-value
```

The standardization drops `Sites`, `Mean Ctrl`, `Mean Exp`, `Sum Ctrl`,
`Sum Exp`, `Delta Mean` and the raw `p-value`. Those are the only columns that
distinguish **"measured, no effect"** from **"no insertions, nothing to
measure"**, and without them the two are byte-identical. The first two rows of
the Griffin reprocessing make it concrete — `dnaA` and `dnaN`, both essential,
31 TA sites each, `Sum Ctrl = 0.0`, `Sum Exp = 0.0`, and therefore
`log2FC = 0.00`, `Adj. p-value = 1.00000`. `recF` beside them carries 1250.8 and
2278.69 reads and a real fold change. In the processed table all three are
numbers of the same kind.

Measured on the Griffin comparison: **534 of 3,990 genes have zero insertions in
both conditions, and all 534 read exactly `log2FC 0.00, q 1.00000`.** That is
13.4% of the genome silently presented as "no effect" by the processed table.

Two further reasons to take the raw output. The repository's own
`code/data_wrangling/Tn_data_wrangling.py` builds the processed table by
harvesting **each paper's supplementary table** and renaming columns — so its
numbers are per-study, not the uniform reprocessing that is MtbTnDB's whole
point. And its binarized path calls `fillna(0)`, which turns *"this gene was not
in this screen"* into *"this gene was not called"*. **The binarized matrices
(`result_bin_matrix_*.csv`, `Tn_library_*_DASH.xlsx`) must not be ingested.**

### What is in it

`data/col_desc_dash.tsv` inventories 158 screens, 146 of which carry a
standardized column id. By condition: **109 in vivo, 47 in vitro, 2 in cell.**

The in-vitro set includes conditions the atlas cannot currently answer at all:
hypoxia at 3 and 6 weeks, acid stress, nitrosative stress, iron, tryptophan and
amino-acid starvation, and **drug exposure — isoniazid, ethambutol, rifampicin,
vancomycin, meropenem**.

**The in-vivo count needs reading carefully, and this is a counting trap.** Of
the 109, **61 are Collaborative Cross mouse strains and 21 are BXD** — host
genotype arms of two host-genetics studies, not 82 independent biological
conditions. A gene "required in 61 screens" may be required in one experiment
with 61 arms. Screen counts are not evidence weight, and the 1,969 resampling
files are mostly pairwise strain comparisons from those same panels.

### The trap that outranks the others: the 5–80% ORF window

Validating the zero-insertion rule against the atlas's existing Griffin ingest
turned up a genuine disagreement between Griffin's published table and MtbTnDB's
reprocessing of Griffin's own `.wig` files:

| Gene | Griffin Table S3 | MtbTnDB TRANSIT |
|---|---|---|
| `Rv1484` inhA | 7 sites, 0 hit, 0 reads → `n/a` | 9 sites, 0 reads → unmeasurable ✓ agrees |
| `Rv0440` groEL2 | 10 sites, 0 reads → `n/a` | 13 sites, 0 reads ✓ agrees |
| `Rv1908c` katG | 26 sites, 0 reads → `n/a` | 39 sites, 0 reads ✓ agrees |
| `Rv3790` dprE1 | 20 sites, **0 hit, 0 reads** → `n/a` | 27 sites, **937.8 / 1813.56 reads, log2FC +0.37** |
| `Rv0206c` mmpL3 | 26 sites, **0 hit, 0 reads** → `n/a` | 34 sites, **94.9 / 44.82 reads, log2FC −1.67** |
| `Rv0003` recF | 30 sites, 14 hit, ratio 1.76 (log2 0.82) | 35 sites, log2FC 0.28 |

The atlas's Griffin ingester was checked against the raw workbook and reads the
right columns; Griffin really does report zero. The cause is in Griffin's own
header: **its TA-site columns are labelled "5-80% of ORF"**, excluding the
termini, where an insertion is least likely to disrupt function. TRANSIT counts
the whole ORF. Across the 3,917 genes both cover, the ratio of TRANSIT sites to
Griffin sites has **median 1.333** — exactly 1/0.75, the window.

So the atlas's 802 `measured = false` Griffin genes split in two:

- **532** have zero insertions by either method. Truly dead.
- **270** have reads that fall *only outside* the disruptive window. MtbTnDB
  gives each of them a fold change. **dprE1 and mmpL3 are in this 270.**

`Sum Ctrl`/`Sum Exp` catch the first class and **cannot** catch the second,
because fixing it needs insertion positions and the deposit has no `.wig` files.
A log2FC of −1.67 for mmpL3 on cholesterol is therefore not evidence of a
cholesterol phenotype; it is consistent with terminal-insertion noise in a gene
that tolerates no disruptive insertion at all.

**Decided: carry the value, flag what the data supports, and never show it
alone.** `measured = (sum_ctrl > 0 OR sum_exp > 0)` per screen × gene, every
TRANSIT column kept unrecomputed, and the full-ORF window stated in the agent's
schema so a fold change on an ES/ESD gene is read with the essentiality call
beside it.

The two alternatives were rejected on the same grounds. Suppressing `log2fc`
wherever DeJesus calls a gene ES/ESD (490 genes) would have one source's call
decide whether another's value is shown, and 7H9 essentiality is not the same
question as insertion tolerance in a given screen's library — `katG` is `NE`
with `insertion_fraction = 1.0` in DeJesus and takes **zero** insertions in
Griffin's library, while `mmpL3` is `ESD` and is measured in it. The proxy fails
in both directions. Carrying values only for non-essential genes withholds
published numbers for precisely the genes the atlas exists to discuss.

### Scope: 136 screens, not 1,969

The archive holds 1,969 resampling files, **1,833 of which set one mouse strain
against another** from Smith 2020's Collaborative Cross and BXD panels. That is
a host-genetics question, not "is this gene required under condition X", and
those files are skipped. The rule needs no curated strain list: skip a screen
when *both* its experimental and control reads come from `2020_Smith`. The 61
Smith screens comparing a strain to the shared in-vitro reference library are
kept, because those do answer "is this gene required in this mouse".

That leaves **136 screens over 14 studies, 543,008 rows**: `2020_Smith` 61
(each a mouse strain against the reference library), `2018_Carey_A-H` 19
(clinical isolates), `FLUTE` 15, `2013_Zhang` 10, `2017B_DeJesus_1A-1C` 10,
`2017_Xu_1A-1E` 7 (**drug exposure** — isoniazid, rifampicin, ethambutol,
vancomycin, meropenem), `2019_Bellerose` 3 (HRZE in mice), `2017_Mishra` 3,
`2018_Ritterhaus_A-B` 2 (hypoxia), `2011_Griffin` 2, and one each from
`2015_Kieser`, `2015_Nambi`, `2016_Korte`, `2019_Minato`.

Of the 4,055 distinct loci, **4,022 are in the gene universe**. The 33 outside
it are older annotation tags — `Rv0186Ac`, `Rv0229Ac` and friends, plus
`Rv0061` and `Rv1784`, which Griffin's table also carries and Mycobrowser does
not. They are kept as rows and simply do not join.

**Two annotations ship in one archive, and this cost a silent loss.** Most
screens were resampled against `H37Rv.prot_table` and key genes as `Rv0206c`.
Eight — the whole Xu drug-exposure series and Nambi 2015 — used
`H37RvBD.prot_table` and key them as `RVBD_0206c`: the same `RVBD` prefix swap
Bosch 2021 needs, but with an underscore. Those eight parsed to zero rows and
vanished without an error until the screen count came back 128 instead of 136.
`normalize` now **raises** when a screen parses to no genes, because a screen
that yields nothing is a format change, not a result.

Ingesting all 1,969 was rejected on two counts: 7.86M rows is 275× the largest
existing table for a question the atlas does not ask, and `store.write_parquet`
materialises its rows, so it would need the shared writer rewritten for one
source's benefit. Scanning the whole archive takes 0.7 s, so cost was never the
constraint — proportion was. The 136 screens write a 12 MB Parquet in about
20 s once the archive is cached.

### Study attribution comes from the deposit, condition annotation does not

Every one of the 1,969 files carries `#Control Data:` and `#Experimental Data:`
headers naming the input `.wig` paths — `2011_Griffin/glycerol_H37Rv_rep1.wig`.
The directory is the authors' own study label, so each row's `study`,
`control_study` and replicate counts are attribution read out of the CC BY
deposit rather than anything this atlas inferred. **76 of the 136 screens take
their control library from a different study than their experimental data**,
which is recorded as `cross_study`; the paper's own Fig S1 is about batch
effects between screens, so this is their caveat, not ours.

### The condition annotation, and the basis for using it

What each screen *was* — in vitro vs in vivo, medium, carbon source, stress,
mouse strain, the knockout background of a genetic-interaction screen, and the
source publication — is **not** in the Zenodo deposit. It is
`data/col_desc_dash.tsv` in the authors' repository, which carries no LICENSE
file.

**Sid's call, 2026-10-10: it is from the same paper, so the atlas uses it.** The
basis recorded here is the **article's own CC BY 4.0** plus the fact that the
file is a compilation of facts about published experiments — screen name,
publication title and URL, medium, stress, mouse strain. Not the README's "MIT",
which is a software licence pointing at a file that 404s. Attribution is
satisfied either way, because every row cites the paper and the data DOI. And
nothing is redistributed: `data/raw/` is gitignored, the same reasoning that
lets Mycobrowser, which states **no** licence at all, be the gene universe.

The URL is pinned to **the commit the paper's Methods cites**
(`a2f223042a40d01f3188e1f7465b7b1eccaffb43`), not `master`. The two files
differ; the pinned one is the revision the CC BY article actually refers to,
which is the whole basis for using it, and it is reproducible. Both give the
same 146 annotated screens over 18 columns.

**It joins 64 of the 136 screens, and the other 72 are honestly blank.** The
authors' `column_ID_std` is the same slug the archive names its files with — for
the condition screens. For the host panel it is not: their table says
`<strain>_vs_in_vitro` and `<strain>_vs_in_vitro_H37Rv`, and **no file in the
archive uses either name** (the archive's equivalent is
`<strain>_vs_mbio_H37Rv`). They are very probably the same comparison, but
"very probably" is an inference, so those screens carry `annotated = false` and
NULL condition fields rather than a guessed match. A NULL `condition_class`
means *not recorded*, never "in vitro".

One thing the annotation settled on its own: **the authors' 146 standardized
screens contain no strain-against-strain comparison at all** — their 82
host-panel entries are all strain-against-in-vitro. That is independent
confirmation that the 1,833 pairwise files skipped above are extra re-runs
rather than part of the published resource.

**27 of the screens are genetic-interaction backgrounds, not conditions**, and
the annotation is the only thing that says so. `marP_KO_vs_marP_WT` is the case
that proves it: `mmpL3` reads `log2fc -5.37` at `q = 0.0145` there, on 1,906
control reads against 46 — which looks like a strong conditional phenotype until
the description says *"mutants exhibiting altered fitness in the absence of gene
marP"*. Without the annotation the only visible field was
`carbon_source = glycerol`, and that result reads as "mmpL3 is required on
glycerol", which it does not say. It is the single significant hit across all
three validation genes, so the first thing this file bought was stopping one
wrong conclusion about a reference target.

A related trap: `interaction_gene` (an Rv id) and `interaction_gene_name` are
**sparse independently** — 11 screens carry only the id, 5 only the name, 11
both. `marP` has a name and no id, and the atlas does not fill it in. Filtering
on one field alone leaves interaction screens inside a condition query.

Of the 64 annotated: 43 in vitro, 21 in vivo. The conditions include
cholesterol, **3 and 6 weeks of hypoxia**, acid stress (two buffers),
nitrosative stress, high iron, tryptophan and amino-acid starvation, minimal
versus rich medium, and **drug exposure to isoniazid, rifampicin, ethambutol,
vancomycin and meropenem**. That is what turns 136 slugs into answerable
questions, and it is the reason this file was worth the licence call.

### Download route, when it is ingested

`https://zenodo.org/records/15284946/files/transit_outputs_mtbtndb.tar.gz?download=1`
— 267 MB, returns `HTTP 200` with `content-length: 267217387`, no auth, roughly
three minutes. Zenodo is not in `fetch.py`'s host list yet and will need a rate
limit entry. 1,969 files at ~4,000 rows each is ~7.9M rows before filtering to
the 146 standardized screens, so the ingester should select screens from
`col_desc_dash.tsv` rather than walking the whole archive.

Citation, both required: the paper above, and the versioned Zenodo DOI for the
data. Attribution satisfies CC BY 4.0 for both.

## Residue-level structure mapping (M3)

For placing resistance mutations onto structures:

- `https://www.ebi.ac.uk/pdbe/api/mappings/uniprot_segments/{pdb_id}` gives
  UniProt ↔ PDB chain segments (SIFTS). Verified for `4kw5` → `P9WJF1`, chains
  A and B, `unp_start` 1 → `unp_end` 461.
- **Gotcha:** `start.author_residue_number` came back `null` for that segment
  while `end.author_residue_number` was 461. Segment-level mapping is therefore
  not sufficient for per-residue work; M3 should use the residue-level SIFTS
  endpoint.

## folC and PAS — a rule Sid has not set yet

**Open. The atlas currently counts it; nobody has decided that it should.**

`CLAUDE.md` says resistance is not engagement, and gives katG/isoniazid as the
case: katG *activates* isoniazid, so a WHO resistance link to katG is shown and
never counted as a drug acting on that gene.

Bosch 2021's `antibacterial` column has the same shape in at least one place.
ChEMBL's own note on para-aminosalicylic acid is that **FolC incorporates PAS
into the antimetabolite that then inhibits DfrA** — so folC activates the drug
rather than being inhibited by it, exactly like katG. `ribD` is arguably the
same. Those are 2 of the 13 genes in the headline "11 drugs on 13 genes".

Three options, none taken:

1. **Leave it.** Bosch's column is the authors' own annotation and the atlas
   carries it as stated. This is what the code does today.
2. **Exclude activating enzymes from the count**, the way katG already is.
   Needs a list, and the only source for "is this activation or inhibition" is
   ChEMBL's free-text mechanism comment, which is not structured.
3. **Drop Bosch as a counting link entirely.** Worst of the three: it is the
   *only* source for mmpL3/SQ109, qcrB/telacebec and atpE/bedaquiline, which
   ChEMBL records no mechanism for.

Until it is decided, the UI quotes Bosch's own wording and says the annotation
can name an activating enzyme (`web/src/Clinical.tsx`). See
`TARGET_LINKS` in `atlas/clinical.py` for where the rule would change.

## Druggable pockets — unresolved

**No public source provides this.** Nothing in the seven sources above gives a
pocket call or a druggability score. The options are to compute pockets
(fpocket over experimental and AlphaFold structures, which adds a heavy
dependency and a compute step), to use ligand presence as a weak proxy, or to
drop the question. Deferred past M1; the UI should not claim a pocket it cannot
source.

## Extension point: per-compound annotations

Deliberately **not implemented**. A nuisance-compound classifier will be plugged
in later. The seam is the compound table M1 writes: annotations attach by
`molecule_chembl_id` in a separate Parquet file with its own `source` and
`source_version`, so a classifier can be added, re-run and versioned without
touching an ingester or the bioactivity rows.
