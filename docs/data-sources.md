# Data sources

Every endpoint, format and licence below was checked against the live service on
**2026-10-09**. Nothing here is from memory or documentation alone — where a
claim could not be verified, it says so.

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
| [WHO catalogue](#who-mutation-catalogue) | 2nd ed. (2023) | ODC-By 1.0 | Resistance mutations (M1) |

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
