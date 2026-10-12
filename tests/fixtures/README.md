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
complex's assay has a description that `protein_assay_example` must not offer;
the assay id and its description are the live ones.

The fixture store's `screens` and `screen_stages` are not files either. `tests/conftest.py`
runs nine hand-written ChEMBL assays through `chembl.normalize_campaign_assays`,
`stamp_stage_counts` and `campaign_screens`, so the rows have the ingesters' own key
set and the classifiers' own labels. The assay ids (`CHEMBL91xxxxx`) and the two
documents are **synthetic**; the targets are the fixture genes' own:

| Assay | Exercises |
|---|---|
| `CHEMBL9100001` | A 4-compound stage on dprE1's `SINGLE PROTEIN` target: the gene's own screen |
| `CHEMBL9100006` | A 2-compound confirmation stage of the same campaign on the same protein: one screen, not two, and the size is the biggest single stage |
| `CHEMBL9100002` | A 3-compound stage on `CHEMBL4662931`, the ClpP1P2 complex the crosswalk maps to both subunits: shown in `n_complex_screens`, never in `n_target_screens` |
| `CHEMBL9100003` | A stage on `CHEMBL5629` whose target type was not looked up (`NULL`), so it must land on the shown-not-counted side rather than in neither column. Its modality is `other` |
| `CHEMBL9100007` | A stage on the *M. smegmatis* MmpL3 target (`CHEMBL5465372`). The store's crosswalk is built without the orthologue bridge, so it reaches no gene; the test that turns the bridge on shows `Rv0206c` still reads 0 screens |
| `CHEMBL9100004` | A computed selectivity index: `derived`, `stage = NULL`, modality `other` by assignment. The unclassified-share counters leave it out |
| `CHEMBL9100008` | A 3-compound stage on cyp144's own protein, in the 2019 paper: the ChEMBL half of a gene PubChem also screened (deposit `9000008`) |
| `CHEMBL9100009` | A 2-compound stage on the same protein in the other document (2021): cyp144 has two dated papers, so the latest year is told from the earlier one |
| `CHEMBL9100005` | Prose no pattern has seen: modality `other`, stage the default `primary`. Reaches no gene |

Eight PubChem deposits join them, built through `pubchem.normalize_screens`, `link_targets`
and `stage_row` from records in PUG-REST's shape. The AIDs (`9000001-9000008`) are
**synthetic**, and so are their SID counts; the accessions are the fixture genes' own. PubChem
names its target on the campaign, and its stages carry no ChEMBL target:

| AID | Exercises |
|---|---|
| `9000001` | One protein (`P9WIL3`, panD), 12,000 SIDs, every one `Unspecified`: the TrpRS shape. A screen that reaches the gene, with `n_screen_actives` NULL |
| `9000002` | One UniProt entry two loci share (`A0A089QRB9`: pks3, pks4), with 7 stated actives: both loci carry the screen and the actives, and `shared_accession` says why |
| `9000003` | Two targets (`P9WPC3`, `P9WPC5`), as AID 1671185 lists ClpP1 and ClpP2: PubChem has no target type, so a deposit naming two proteins is the complex, and its 5 stated actives belong to neither subunit |
| `9000004` | No `Target` key, as the 12 whole-cell AIDs: reaches no gene. Its stage has no modality, which the unclassified-share counters must not read as `other` |
| `9000005` | A second deposit on the same protein as `9000001`: two deposits are two screens, so a gene's count is not collapsed to one |
| `9000006` | `P9WIE5` named twice beside `4KW5_A`, a PDB chain that reaches no locus: one protein, so one screen of its own. Counting entries read it as a complex |
| `9000007` | Calls stated, 11,000 inactive and none active: `n_screen_actives` is a real 0, not NULL |
| `9000008` | 120 stated actives on cyp144, which `CHEMBL9100008` also screened: pins that the actives are the stated ones alone beside three screens, and that the year is the latest dated paper's |

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

## `chembl_assay_census.json` and `chembl_campaign_assays.json`

Hand-written in ChEMBL's response shapes, with synthetic ids (`CHEMBL1`...`CHEMBL5`,
`CHEMBL_DOC1`, `CHEMBL_VERO`). Nothing in either is a real record except the two assay ids
`CHEMBL4649965` (Pks13's assay) and `CHEMBL4105939` (its target, not an assay), borrowed so
that the first can be recognised.

`chembl_assay_census.json` is eight activity rows, as `census_rows` pulls them:

| Assay | Exercises |
|---|---|
| `CHEMBL4649965` | Five `Percent Effect` rows over four compounds (`CHEMBL4` twice), so `n_measurements` is 5 and `n_compounds` is 4: assay size counts compounds, not rows |
| `CHEMBL9001` | Two `IC50` rows, a second assay of a different type beside the first |
| *(no assay id)* | One row with `assay_chembl_id` null: it belongs to no assay and is not counted into one |

`chembl_campaign_assays.json` is one document (`CHEMBL_DOC1`) carrying the whole ladder as
seven assays, with the four target records they name (`targets`):

| Assay | Exercises |
|---|---|
| `CHEMBL100` | A MABA MIC on the Mtb organism target: `phenotypic_mtb`, strain H37Rv, condition `unspecified`: a method (MABA) is not a medium |
| `CHEMBL101` | A thioesterase assay on a `SINGLE PROTEIN` Mtb target: `biochemical_mtb` |
| `CHEMBL102` | Vero cytotoxicity on a `CELL-LINE` target: `mammalian_cytotox`, a `profiling` stage that a target-keyed query cannot see |
| `CHEMBL103` | Microsomal stability with no target at all: `adme` |
| `CHEMBL104` | A BALB/c mouse CFU assay with no target: `in_vivo_efficacy`, a `profiling` stage |
| `CHEMBL105` | *S. aureus* growth inhibition: `other_pathogen`, kept apart from an Mtb MIC |
| `CHEMBL106` | "Selectivity index, ratio of CC50 ... to MIC": `derived`, `stage` NULL, `modality` `other` by assignment. It is a ratio, not a measurement this atlas made, though its value may be one the depositor published |

The first proves assay size counts compounds. The second proves each modality is kept apart
and that the computed index is flagged rather than read as a seventh measurement.

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

## `chembl_chemreps.txt`

The header and the first three rows are real lines of `chembl_37_chemreps.txt.gz`, fetched
2026-10-11, uncompressed (`_lines` opens either). The last two are **deliberately synthetic**;
the live file has no blank SMILES among its 2,897,819 rows.

| Rows | Exercises |
|---|---|
| `CHEMBL3330226` (macozinone), `CHEMBL64` (isoniazid) | A wanted id with a structure |
| `CHEMBL1` | An id the store does not reference: streamed past, no row |
| **Synthetic:** `CHEMBL_SHORT`, three fields | The length check |
| **Synthetic:** `CHEMBL_BLANK`, an empty SMILES | A blank SMILES is no structure |

Headerless and duplicated files are written by their tests from these lines.

## `pubchem_aid_summary.json`

Five real records from PUG-REST's `assay/aid/<aids>/summary/JSON`, fetched
2026-10-11, with `Protocol` and `Comment` dropped (nothing reads them) and the
description of AID 1626 cut to its institution lines and the paragraph that
states the library size. Nothing is synthetic.

| AID | Exercises |
|---|---|
| `1626` | The TAACF primary screen: real calls (2,044 / 209,843 / 3,510), `Method` is `confirmatory` though it is a single-concentration primary, no `Target` key (whole-cell), prose says 216,163 compounds against 215,397 SIDs deposited (215,098 CIDs) |
| `1671170` | `SIDCountActive: 0` and `SIDCountUnspecified` equal to `SIDCountAll`: no cutoff was deposited. Neither its title (`Mt-TrpRS`) nor its target name says *tuberculosis* |
| `1671178` | The other shape: 25 actives (IC50 rows, under 10 uM) beside `SIDCountUnspecified` equal to `SIDCountAll`, which holds by construction whenever each SID also has an unspecified Percent Effect row. The real record states the depositor's one-sided rule ("activity <= 10uM ... flagged as active") in its `Comment`; the fixture drops `Comment`. Six of the eight ChEMBL deposits among the 28 large AIDs look like this (`1671170` and `1671174` do not state the rule and have no actives) |
| `2060911` | `SourceName` is the bare string `11908`; a prose library of 100,639 compounds against 93,270 SIDs deposited; a UniProt target accession |
| `2253871` | A **partial** deposit: 13 actives and 2 `Unspecified` of 15 SIDs, so `0 < SIDCountUnspecified < SIDCountAll`. A small ChEMBL deposit, far below the 10,000 floor, kept only for the shape (1,912 small AIDs in Task 6's census look like this; none of the 28 large ones do) |

The summary has no `TaxonomyID` on any target and no `PubMedID` field, in any of
the 28 AIDs of 10,000 or more tested SIDs.

## `pubchem_aid_results.csv` and `pubchem_aid_unspecified.csv`

Real rows of `pcget.cgi?query=download&record_type=datatable&actvty=all`, fetched
2026-10-11 and trimmed to a handful of rows. Every column of every kept row is as
PubChem sent it, and so are the header and the metadata rows after it: **five** of
them in both files (`RESULT_TYPE`, `RESULT_DESCR`, `RESULT_UNIT` and two
`RESULT_IS_ACTIVE_CONCENTRATION*` rows), not the three the plan assumed. Only a
numeric `PUBCHEM_RESULT_TAG` tells a result from one.

`pubchem_aid_results.csv` is AID 1626, the TAACF primary screen, which names its
own columns (`IC90`, `% Inhibition of H37Rv @ 100 uM`, 49 in all) and has **no**
`Standard *` column:

| Tag | Exercises |
|---|---|
| `1`, `13` | `Active`, score 80. CID `911287` has a ChEMBL id in UniChem (`CHEMBL1461400`); `135458645` has none |
| `2045`, `2046` | `Inactive`, score 0: the 209,843 "tested and did nothing" this source exists for. CIDs `3803930` and `7314608` are mapped (`CHEMBL533602`, `CHEMBL1404086`) |
| `2275` | `Inconclusive`, score 40, **CID `135458645` again**: SID `49681785` (tag 13) is `Active` and SID `26719829` is `Inconclusive`. 11 CIDs in this AID have SIDs that disagree |

`pubchem_aid_unspecified.csv` is AID 1671170 (Mt-TrpRS), a ChEMBL deposit that
states no activity call, and it **does** carry `Standard Type`, `Standard
Relation`, `Standard Value` and `Standard Units`:

| Tag | Exercises |
|---|---|
| `3777`, `3778` | One SID (`312401710`) on two rows: a single-point `Percent Effect` of 54.24 % and an `IC50` of `>` 194984 nM, a censored value stored with its relation. 612 of the file's 65,646 rows are IC50, the rest `Percent Effect` |
| `2227`, `2228` | One SID (`312400166`) measured twice, `Percent Effect` `-1.988` and `1.19`. 280 SIDs are on two rows (259 `IC50` beside `Percent Effect`, 15 two IC50s, 6 two replicates), so 65,646 rows cover 65,366 SIDs |
| `65639` | The only row with no CID (and no SMILES): its SID is all there is |

The first four of those rows are why `screen_results` is keyed on `result_tag` and not
on the SID: SID and endpoint repeat (21 pairs in the full file, 15 of them with the
same value too), and the tag does not. A re-keying on the SID or the value fails
`test_the_sid_and_endpoint_do_not_tell_two_rows_apart_but_the_row_number_does`.

The summary counts in `tests/test_screens.py`'s build tests are trimmed to these five
rows (AID 1626: 5 SIDs; AID 1671170: 3), because the completeness check compares the
file to the summary and a trimmed file would otherwise fail it.

## `pubchem_projects.json`

Three real E-utilities eLink answers (`retmode=json`,
`linkname=pcassay_pcassay_same_assay_project_list`), fetched 2026-10-11 from
`eutils.ncbi.nlm.nih.gov`. PubChem itself was blocking this machine that day;
E-utilities was not.

| Key | Exercises |
|---|---|
| `449775` | A declared project: 39 member AIDs, among them the 327,669-SID primary (449762) and the confirmatory. Its lowest member is `435019`, which is neither the primary nor the AID that was asked |
| `1626` | The genuine "declares no project" answer: a linkset whose `ids` is the AID asked, with no `linksetdbs` |
| `error` | `db=nosuchdb`, `id=1`: HTTP **200** with `{"linksets": [], "ERROR": "Invalid db name specified: nosuchdb"}`. E-utilities answers a bad db, id or linkname this way, and `fetch` caches it as a success |

## `pubchem_refseq_uniprot.json`

Two real answers from UniProt's `search?query=xref:refseq-<NP>&fields=accession`,
fetched 2026-10-11 (UniProt release 2026_03). `NP_214877` is Rv0363c (`P9WQA3`,
Swiss-Prot). `NP_999999` is not an *M. tuberculosis* protein at all: UniProt
answers with a TrEMBL entry (`D3ZNH9`), because RefSeq `NP_` spans organisms,
which is why the crosswalk and not this answer decides whether a locus is reached.
`xref:embl-CCE37082` returned zero results the same day and is not a fixture,
because nothing here queries an EMBL id.

## `ncbi_genome_slices.json`

Two real slices of NC_000962.3 (`efetch db=nuccore rettype=fasta`, fetched
2026-10-12), keyed by their 1-based start, with the chromosome's real length.
The test store pads everything else with `N`, which no assertion reads.
`4235779` is dprE1 on the `+` strand (ATG...TAG, 1,386 bp); `244484` is mmpL3
on the `-` strand, which reads GTG...TAA only once reverse-complemented, so a
slice that forgets the strand fails on it.
