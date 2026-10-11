# Test fixtures

Small slices of the real source files, committed so tests never touch the
network. Each is the genuine upstream format — same header, same columns, same
quirks — cut down to the loci that exercise a specific behaviour.

To refresh after an upstream release: run the pipeline (`make build`), then copy
the rows for the loci below out of `data/raw/` into these files, keeping the
header intact. If a locus below no longer behaves as described, that is a real
upstream change and the test that names it should be updated deliberately.

## Why each locus is here

| Locus | Exercises |
|---|---|
| `Rv3790` (dprE1) | Reference target: sources agree, direct ChEMBL target, 27 PDB entries |
| `Rv1484` (inhA) | Reference target: most-studied, 126 PDB entries, `resistance_drugs` populated |
| `Rv0206c` (mmpL3) | Reference target: one structure, **no** Mtb ChEMBL target → orthologue bridge |
| `Rv2879c` | Accession disagreement — Mycobrowser `P0A644` vs proteome `P9WH15` |
| `Rv0236A` | Second accession disagreement, different gene class |
| `Rv1180` / `Rv1181` | Two loci sharing one accession (`A0A089QRB9`) |
| `Rv2561` / `Rv2562` | Shared accession *and* a disagreement at once |
| `Rv0796` / `Rv1369c` | IS6110 transposase `P9WKH9`, shared across 16 loci upstream |
| `Rv0795` / `Rv1370c` | A *different* shared transposase accession, so groups can't bleed |
| `Rv2099c` (PE21) | Mycobrowser names `Q79FH7`, which is not in UP000001584; also a pseudogene |
| `Rv2307D` | Mycobrowser-only link to `L7N683`, an entry carrying no Rv tag |
| `Rv0947c` | No accession from either source |
| `Rv2266` (cyp124) | ChEMBL target that UniProt's cross-references omit |
| `Rv1777` (cyp144) | Second ChEMBL-mapping-only target |
| `Rv1908c` (katG) | In the WHO catalogue but with no ChEMBL target — for M1 |
| `Rv0667` (rpoB) | Ditto, the canonical rifampicin resistance gene |
| `Rv0148` | Present **only** as a `promoter` row, to prove non-CDS rows are dropped |
| `Rv2447c` (folC) | Essential, **zero** PDB entries of its own, and two under a CDC 1551 accession at 100% identity — the `same_sequence` case, which no other fixture locus has |
| `Rv2461c` / `Rv2460c` (clpP1 / clpP2) | The pair behind `CHEMBL4662931`, ClpP1P2, a `PROTEIN COMPLEX` target the crosswalk maps to both as `direct`. A screen filed against it is reported in `n_complex_assays` and counted as neither subunit's own `n_protein_assays`. No Pfam on either, so `precedent_domain_genes` is untouched |

`chembl_bioactivity.json` carries three whole-cell rows added for the potency
layer, all on `CHEMBL1976041`: a censored `MIC > 128 uM` (must produce no
`pmic`), a hypoxic LORA MIC (must classify as `non_replicating`, not
`standard_media`, despite naming no stress elsewhere), and an MDR
clinical-isolate MIC in 7H9 (must set `resistant_panel` *and* classify as
`standard_media`, proving the two fields are independent). The existing rows
already cover the `uM`, `nM` and `ug ml-1` conversion paths, and the same
compound's `MIC 3100 nM` and `MIC99 3.1 uM` both convert to 5.509, which is a
free consistency check on the unit handling.

`chembl_uniprot_mapping.txt` additionally keeps `A0QP27` (*M. smegmatis* MmpL3,
`CHEMBL5465372`) — the far side of the orthologue bridge.

The fixture store's `assay_sizes` is not a file here: `tests/conftest.py`
derives it from `chembl_bioactivity.json` through `chembl.aggregate_sizes`, so a
gene cannot have activities and no assays. Two census rows are added by hand
because the potency rows cannot show them: a percent-inhibition screen of 5
compounds on dprE1 (in the census, never in `activities`), and a 4-compound
screen on `CHEMBL5629`, which reaches `Rv3545c` only through UniProt's
cross-reference and so has no `target_type` — it must be reported as
not-a-single-protein rather than dropped. The ClpP1P2 screen is three hand-written
potency rows in `tests/conftest.py` (compounds borrowed from dprE1's), so the
complex's assay has a description that `protein_assay_example` must not offer.

`extra_evidence.json` carries nine real `orthologue_structures` rows, chosen to
be the three shapes rather than a sample: folC's two `same_sequence` entries
(the rescue — no structure of its own), mmpL3's three *M. smegmatis* entries
(all better than its own 3.0 Å, all liganded, so a borrowed structure can beat
a real one), and dprE1's and inhA's, which sit beside 31 and 135 entries of
their own and so must not read as a rescue. `Rv1908c` (katG) has none, which is
how the zero gets tested.

It also carries 23 real `drug_precedent` rows, picked for the readings rather
than for coverage — the table's risk is entirely in what gets counted:

| Rows | Exercises |
|---|---|
| inhA's `PF13561`: isoniazid and ethionamide on `P9WGR1`, triclosan and hexachlorophene on *E. coli* FabI, three phase-2 compounds on the *S. aureus* and *B. pseudomallei* enzymes | The gene's own two approved drugs must be excluded and the other organisms' five counted, which is the whole shape of the column |
| dprE1's `PF01565` and `PF04030`: triparanol on human Δ24-sterol reductase, macozinone and TBA-7371 on `P9WJF1` | An all-human approved precedent beside a clinical one the gene must not claim for itself |
| atpE's `PF00137`: bedaquiline on the ATP synthase complex | Filed against `P9WPS1`, atpE's own accession — excluded by the own-protein rule before the complex rule ever applies |
| rpoC's `PF00623`: rifampin, rifabutin and fidaxomicin on a `PROTEIN COMPLEX`, TAS-106 on a human RNA polymerase III subunit | The complex exclusion, with one `SINGLE PROTEIN` row left to prove the filter is not just dropping everything |
| cyp124/cyp144/cyp125's `PF00067`: cobicistat on the "Cytochrome P450 3A" `PROTEIN FAMILY`, abiraterone and aminoglutethimide on single human P450s | The family exclusion, and the only fixture domain three genes share, so `precedent_domain_genes` reads 3 |

mmpL3's `PF03176` is deliberately absent: a measured zero is a state the table
has to produce, and an RNA gene reads NULL because it has no protein to carry a
domain at all.

## `bosch_vulnerability.xlsx`

A real slice of Bosch 2021 Table S3, keeping the four sheets' headers and nine
loci. It is the only fixture for the CRISPRi ingester, which read one sheet of
the four until the clinical-strain sheets were added.

| Locus | Exercises |
|---|---|
| `RVBD3790` (dprE1) | Confident in both strains and in the differential sheet: the happy path |
| `RVBD1484` (inhA) | Raw delta **+0.382**, normalised **−0.286** — the two disagree in sign, so neither can be derived from the other |
| `RVBD0206c` (mmpL3) | The `c` suffix surviving the `RVBD` → `Rv` prefix swap |
| `RVBD2247` (accD6) | −11.45 in H37Rv, −2.27 in HN878, confident in both: a target that collapses outside the lab strain |
| `RVBD3601c` (panD) | The same comparison running the other way, −4.07 → −9.28 |
| `RVBD0023` | Confident in **both** strains and still absent from the differential sheet — a NULL delta that is not a zero |
| `RVBD0467` | Confident in H37Rv, **not** confident in HN878: the flag is per strain |
| `RVBD2021c` | In the H37Rv sheet, absent from the HN878 sheet entirely — never measured, a third state |
| `16S` | Not a locus tag: must be skipped rather than coerced |

## `mtbtndb_transit_outputs.tar.gz`

Four real TRANSIT resampling files cut to eight loci, plus the loess dump the
archive also ships, which must be ignored. The `#Control Data:` /
`#Experimental Data:` headers are kept intact — they are where each screen's
source study and replicate count come from, and they include TRANSIT's leaked
`b'...'` bytes repr.

| Screen | Exercises |
|---|---|
| `griffin_cholesterol_vs_griffin_glycerol` | Same-study screen, and the comparison against `conditional_fitness`: `dprE1`/`mmpL3` carry fold changes here and read `n/a` in Griffin's own table |
| `CC001.Unc_vs_mbio_H37Rv` | A mouse strain against the shared reference library: kept, and `cross_study` because the control is DeJesus's library |
| `CC002.Unc_vs_C57BL.6J` | Strain against strain, both sides Smith 2020: **must be skipped entirely** |
| `bellerose_MB_HRZE_wk1_vs_bellerose_MB_d21_untreated` | Drug exposure in mice, within one study |

| Locus | Exercises |
|---|---|
| `Rv3545c` (cyp125) | Measured, real depletion, `q_value` 0.0 — the happy path |
| `Rv0001` (dnaA) | Zero insertions in both conditions, so `log2fc` 0.00 / `q` 1.0 means nothing |
| `Rv1908c` (katG) | Unmeasured in Griffin's library, `log2fc` −6.78 at `q` 0.0 in Smith's — unmeasurability is per screen, not per gene |
| `Rv1484` (inhA) | 1.3 reads over 9 sites in `CC001`: measured by the structural line, and visibly weak |
| `Rv3790`, `Rv0206c` | 27 and 34 TA sites against Griffin's 20 and 26 — the whole-ORF vs 5-80% window |

`mtbtndb_col_desc.tsv` holds the authors' screen annotation for three of those
four screens, with all 18 real column names. `CC001.Unc_vs_mbio_H37Rv` is
deliberately **absent** from it, because the authors' table names host-panel
screens differently — that is what proves `annotated = false` and a NULL
`condition_class` rather than a guessed match.

## `unichem_src1src22.txt`

The header and the mapped pairs are real rows of UniChem's `src1src22` file,
fetched 2026-10-11. The four malformed lines are **deliberately synthetic**: the
live file has no malformed lines at all. Do not read them as observed upstream
shapes. Each one exists to exercise one guard in `normalize`.

| Rows | Exercises |
|---|---|
| `CHEMBL6329` → `12846578`; `CHEMBL1004` → `3162` | Single-CID compounds: the plain mapping |
| `CHEMBL1098659` → `22247451` and `962` | One compound, two PubChem CIDs |
| `CHEMBL3833402` → `16694118`, `24850`, `75366293` | One compound, three CIDs, all three real |
| **Synthetic:** `CHEMBL6328` with no CID; a `\t7` line with no ChEMBL id | The emptiness check: two fields, one side blank |
| **Synthetic:** `12846579` alone | The length check: one field, which would fail the unpack |
| **Synthetic:** `CHEMBL1004`, `3162`, `x` | The length check: three fields |

The CID-collision case is not a fixture. A collision is not a shape the real
file has, so its test writes a two-line temporary file.

## `pubchem_aid_summary.json`

Five real records from PUG-REST's `assay/aid/<aids>/summary/JSON`, fetched
2026-10-11, with `Protocol` and `Comment` dropped (nothing reads them) and the
description of AID 1626 cut to its institution lines and the paragraph that
states the library size. Nothing is synthetic.

| AID | Exercises |
|---|---|
| `1626` | The TAACF primary screen: real calls (2,044 / 209,843 / 3,510), `Method` is `confirmatory` though it is a single-concentration primary, no `Target` key (whole-cell), prose says 216,163 compounds against 215,397 SIDs deposited (215,098 CIDs) |
| `1671170` | `SIDCountActive: 0` and `SIDCountUnspecified` equal to `SIDCountAll`: no cutoff was deposited. Neither its title (`Mt-TrpRS`) nor its target name says *tuberculosis* |
| `1671178` | The other all-`Unspecified` shape: 25 actives (the IC50 rows) beside `SIDCountUnspecified` equal to `SIDCountAll`. Six of the eight ChEMBL deposits among the 28 large AIDs look like this |
| `2060911` | `SourceName` is the bare string `11908`; a prose library of 100,639 compounds against 93,270 SIDs deposited; a UniProt target accession |
| `2253871` | A **partial** deposit: 13 actives and 2 `Unspecified` of 15 SIDs, so `0 < SIDCountUnspecified < SIDCountAll`. A small ChEMBL deposit, far below the 10,000 floor, kept only for the shape (1,912 of the 8,400 small AIDs fetched look like this; none of the 28 large ones do) |

The summary has no `TaxonomyID` on any target and no `PubMedID` field, in any of
the 28 AIDs of 10,000 or more tested SIDs.
