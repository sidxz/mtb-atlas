# Data sources

Every endpoint, format and licence below was checked against the live service on
**2026-10-09** (the clinical sources on **2026-10-10**). Nothing here is from
memory or documentation alone — where a claim could not be verified, it says so.

All sources are public. No consortium data, ever.

## Summary

| Source | Version seen | Licence | Used for |
|---|---|---|---|
| [Mycobrowser](#mycobrowser) | Release 5 (2024-07-11) | **none stated** | Gene universe, annotation |
| [UniProt](#uniprot) | 2026_03 (2026-09-02) | CC BY 4.0 | Accessions, cross-references |
| [ChEMBL](#chembl) | ChEMBL_37 (2026-05-01) | CC BY-SA 3.0 | Targets, bioactivity (M1) |
| [RCSB PDB](#rcsb-pdb) | live | CC0 1.0 | Experimental structures (M1) |
| [AlphaFold DB](#alphafold-db) | v6 (2025-08-24) | CC BY 4.0 | Predicted structures (M1) |
| [DeJesus 2017](#essentiality-dejesus-2017) | mBio, Table S3 | CC BY 4.0 | Essentiality (M1) |
| [WHO catalogue](#who-mutation-catalogue) | 2nd ed. (2023) | ODC-By 1.0 | Resistance mutations |
| [Bosch 2021 CRISPRi](#vulnerability-bosch-2021) | Cell, Table S3 | CC BY 4.0 | Vulnerability index |
| [STRING](#string) | v12.5, taxon 83332 | CC BY 4.0 | Interaction partners |
| [phmmer vs human proteome](#human-homology) | UniProt UP000005640, reviewed | CC BY 4.0 | Human anti-target check |
| [ChEMBL drugs](#chembl-tb-drugs-and-mechanisms) | ChEMBL_37 | CC BY-SA 3.0 | TB drugs, phases, mechanisms (M6) |
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
- **Sheet to use: `(1) Mtb H37Rv`**, 28 columns, 4,052 rows (4,005 `RVBD*`
  genes plus 47 RNA features).
- **Key:** `locus_tag` is **`RVBD3790`, not `Rv3790`**. The `c` suffix survives
  (`RVBD0206c`), so the transform is a prefix swap.

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

Only `mechanism` and `bosch_2021` count as a drug acting on the gene: **11
drugs land on 13 genes**. A mechanism target from another organism links no
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
other name "Rifamycin". A name two molecules share links neither. Live: 483
trials link to at least one drug; 219 trial–drug pairs come by both methods,
57 by reference only and 247 by name only. ChEMBL references 3 trials outside
this search, and those links are dropped rather than left dangling.

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

## Noted but not ingested: MtbTnDB

`github.com/ajinich/mtb_tn_db` carries 158 conditional TnSeq screens
reprocessed uniformly, keyed directly on Rv tag
(`data/standardized_data_dash.tsv`, 59 MB, 583,346 rows over 4,055 genes and
146 screens), including cholesterol, hypoxia, acid stress and mouse infection.
The paper is CC BY. **The repository has no LICENSE file** — `LICENSE`,
`LICENSE.md`, `LICENSE.txt` and `COPYING` all 404 and the GitHub API reports
`license: null` — while its README links to one. That is unresolved, and worth
an email to the authors before shipping.

There is also a scientific caveat: TnSeq log2FC is structurally uninformative
for essential genes, which have few insertions to count. `inhA` reads 0.00 with
q = 1.0 in all 146 screens. This dataset would complement Bosch 2021 for
conditional shifts in non-essential genes; it cannot substitute for it.

## Residue-level structure mapping (M3)

For placing resistance mutations onto structures:

- `https://www.ebi.ac.uk/pdbe/api/mappings/uniprot_segments/{pdb_id}` gives
  UniProt ↔ PDB chain segments (SIFTS). Verified for `4kw5` → `P9WJF1`, chains
  A and B, `unp_start` 1 → `unp_end` 461.
- **Gotcha:** `start.author_residue_number` came back `null` for that segment
  while `end.author_residue_number` was 461. Segment-level mapping is therefore
  not sufficient for per-residue work; M3 should use the residue-level SIFTS
  endpoint.

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
