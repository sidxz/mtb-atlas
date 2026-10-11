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

`extra_evidence.json` carries nine real `orthologue_structures` rows, chosen to
be the three shapes rather than a sample: folC's two `same_sequence` entries
(the rescue — no structure of its own), mmpL3's three *M. smegmatis* entries
(all better than its own 3.0 Å, all liganded, so a borrowed structure can beat
a real one), and dprE1's and inhA's, which sit beside 31 and 135 entries of
their own and so must not read as a rescue. `Rv1908c` (katG) has none, which is
how the zero gets tested.

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
