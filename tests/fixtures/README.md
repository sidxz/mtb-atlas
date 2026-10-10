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

`chembl_uniprot_mapping.txt` additionally keeps `A0QP27` (*M. smegmatis* MmpL3,
`CHEMBL5465372`) — the far side of the orthologue bridge.

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
