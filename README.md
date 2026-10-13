# Mtb Target Atlas

Every *Mycobacterium tuberculosis* H37Rv gene as a navigable object, unifying the
evidence a TB drug discovery team checks from target selection and hit triage
through to the clinic.

Built **only from public data**. No consortium data, ever.

The questions it exists to answer:

- Is this gene essential, and under which conditions — broth, or the
  cholesterol it lives on inside a macrophage?
- Does its vulnerability hold in a clinical isolate, or only in H37Rv?
- Is there an experimental structure? A predicted one? A druggable pocket?
- What chemical matter hits it, at what potency?
- Is there a published assay for the protein, or does screening start by building one?
- Has this protein ever been screened, against how many compounds, and what did those
  compounds do — including the ones that did nothing?
- Which resistance mutations are known?
- What does the protein do, where does it sit, how many papers is it in?
- Which drugs and clinical candidates act on it, at what phase for TB, and in
  which trials? What is co-crystallised with it?
- And from a compound: what does *it* touch, at what potency, and is it in the
  clinic?
- Which essential targets have a structure and no ligands?

## Status

Twelve milestones are in. Fourteen public sources, one store, one app.

```
make install      # uv venv + dependencies
make build        # whole pipeline -> data/store/*.parquet  (~15 min cold, and the screens block adds ~24)
uv run atlas clinical   # the clinical stage alone, then the roll-up
make api          # FastAPI on :8099
make web          # the app on :5173
make check        # has anything released upstream? nine requests, seconds
make refresh SOURCE=chembl   # re-download one source, rebuild only what it feeds
make diff         # what that did to the numbers
make test         # 588 tests against committed fixtures, no network
```

| Milestone | Scope | |
|---|---|---|
| M0 | Scaffold, verified sources, ID crosswalk + tests, gene annotation | ✅ |
| M1 | PDB, AlphaFold, ChEMBL bioactivity, essentiality, resistance | ✅ |
| M2 | API: `/targets`, `/targets/{rv_id}`, `/compounds/{id}`, `/meta` | ✅ |
| M3 | Target page: evidence panels + Mol* with ligands and resistance residues | ✅ |
| M4 | Genome canvas: all 4,173 genes, recolourable by any evidence axis | ✅ |
| M5 | Agent: natural-language questions, answers cite the records | ✅ |
| M6 | Clinical layer: TB drugs and mechanisms, trials, and every drug–gene and trial–drug link labelled with how it was made | ✅ |
| M7 | UniProt's protein biology per gene; ligand identity; one box over genes, drugs, trials and compounds | ✅ |
| M8 | Target enablement: vulnerability in a clinical isolate, whether a protein assay exists, and how the protein was produced | ✅ |
| M9 | The workspace: browse wide or read wide, compound depictions, every number linked to its assay | ✅ |
| M10 | Upkeep: `check` what released, `refresh` one source, `diff` what it did — scriptable, no LLM | ✅ |
| M11 | The screening record (store only): campaigns, their stages and every compound tested, inactives included, from ChEMBL's literature and 28 PubChem deposits. Reachable through `/ask`; the API and views are a separate plan | ✅ |
| — | Beyond the brief: CRISPRi vulnerability, STRING partners, human anti-target, domains | ✅ |

## What it answers

```
4,173 genes · 489 essential · 885 with a structure · 4,015 predicted
107 with chemical matter · 65 in the WHO catalogue · 594 with a confident
vulnerability index · 847 with a close human homolog
201 essential · structure · no ligands
112 of those also confidently vulnerable and free of a human homolog
```

That last line is the product: a target shortlist short enough to read, with
`nadD`, `nusG` and `hadA` near the top.

Enablement — what it would take to work on one:

```
119 genes with a published assay against the protein · 434 essential genes
    with none, where screening starts by building the assay
3,936 genes also measured in HN878, a clinical isolate · 507 with the
    authors' own H37Rv-vs-HN878 differential
1,649 structure entries name the plasmid they were expressed from;
    581 crystallised a construct that is not the wild-type
```

accD6 is the case that earns the strain column: −11.45 in H37Rv and −2.27 in
HN878, confident in both. It would have read as an excellent target.

The screening record, from the first build (2026-10-11):

```
999 campaigns · 17,530 stages · 5,422,604 compound results
    27 PubChem campaigns (28 AIDs) · 972 ChEMBL papers
4,620,129 results are "tested, inactive" · 28,172 active · 37,197 inconclusive
    737,106 carry no call recorded
71 genes have been screened · 34 of the 489 essential genes among them
    pks13, CoaBC and TrpRS each read a 65,000 to 67,000-compound screen, through PubChem only
```

A screen can read zero for a good reason, and the atlas says which. `aspS` has an 8,841-compound
assay (8,841 compounds, and 8,841 SIDs in PubChem's summary) and reads no screen, because that
deposit is below the 10,000-substance floor; `pks13`
reads nine screens and a NULL count of actives, because none of the nine has an outcome that
counts. A zero is a count and a NULL is "nobody said". A gene can also read small beside a large
screen the atlas could not place on an H37Rv locus: `mbtI` reads none beside a 104,781-compound
MbtI screen, because that deposit names UniProt's CDC 1551 accession and the atlas is keyed to
H37Rv. Four such campaigns exist; three are correct refusals (another strain, or a PDB chain)
and one, `fadD28` against a 355,326-compound screen, is a known bridging defect, listed with its
cost in `docs/data-sources.md`. ChEMBL's half covers 972 of the 1,926
publications that have a whole-cell Mtb assay: it holds the papers in which a compound that
hits an Mtb protein was also tested on cells, and says so in `docs/data-sources.md`.

From the clinical end:

```
112 molecules with a TB indication in ChEMBL · 11 placed on 13 Mtb genes
1,137 interventional TB trials · 483 linked to one of those molecules
281 genes essential · confidently vulnerable · no close human homolog ·
    no TB drug or candidate acting on them
```

A drug counts on a gene only when ChEMBL's mechanism or Bosch 2021 names that
gene's protein. Membership of a target complex and WHO-graded resistance are
shown beside it, never counted, and 25 anti-TB molecules — the rifamycins,
delamanid, pretomanid, BTZ-043 among them — reach no gene because no public
structured source states one.

## The store

One Parquet file per source, rebuilt by the pipeline, read by DuckDB. Raw
downloads are cached on disk and gitignored. Every record carries `source`,
`source_version` and `retrieved_at`, and the UI shows provenance for every value.

| File | Rows | Key | Source |
|---|---|---|---|
| `genes.parquet` | 4,173 | `rv_id` | Mycobrowser |
| `proteins.parquet` | 3,997 | `uniprot_acc` | UniProt |
| `chembl_targets.parquet` | ~17,000 | `uniprot_acc` | ChEMBL |
| `crosswalk.parquet` | 4,173 | `rv_id` | joined |
| `structures.parquet` | 4,803 | `pdb_id`, `uniprot_acc` | RCSB PDB (ligands + construct) |
| `ligands.parquet` | 1,486 | `comp_id` | RCSB chemical components |
| `predicted_structures.parquet` | 3,973 | `uniprot_acc` | AlphaFold DB |
| `activities.parquet` | 15,518 | `activity_id` | ChEMBL |
| `compounds.parquet` | 5,178 | `molecule_chembl_id` | ChEMBL |
| `essentiality.parquet` | 4,019 | `rv_id`, source | DeJesus 2017 |
| `vulnerability.parquet` | 4,005 | `rv_id` | Bosch 2021 (H37Rv) |
| `strain_vulnerability.parquet` | 4,002 | `rv_id` | Bosch 2021 (HN878 clinical isolate) |
| `conditional_fitness.parquet` | 3,987 | `rv_id` | Griffin 2011 |
| `resistance.parquet` | 48,152 | gene, mutation, drug | WHO catalogue |
| `interactions.parquet` | 28,739 | `rv_id`, `partner_rv_id` | STRING |
| `homology.parquet` | 3,997 | `uniprot_acc` | phmmer vs human |
| `drugs.parquet` | 112 | `molecule_chembl_id` | ChEMBL TB indications |
| `drug_mechanisms.parquet` | 92 | molecule, target | ChEMBL |
| `trials.parquet` | 1,137 | `nct_id` | ClinicalTrials.gov |
| `drug_genes.parquet` | 250 | molecule, `rv_id`, link | joined |
| `trial_drugs.parquet` | 1,183 | `nct_id`, molecule | joined |
| `screens.parquet` | 999 | `screen_id` | ChEMBL literature, PubChem BioAssay |
| `screen_stages.parquet` | 17,530 | `stage_id` | ChEMBL literature, PubChem BioAssay |
| `screen_results.parquet` | 5,422,604 | `stage_id`, `result_tag`, `activity_id` | ChEMBL literature, PubChem BioAssay, UniChem bridge |
| `target_summary.parquet` | 4,173 | `rv_id` | rolled up |

See [`docs/data-sources.md`](docs/data-sources.md) for every endpoint, format,
licence and verification date, and [`CLAUDE.md`](CLAUDE.md) for the rules this
codebase is held to.

## Running it publicly

One image, `ghcr.io/sidxz/mtb-atlas`, serves the API at `/api` and the page at
`/`. It holds no data and names no host: build the store (`make build`), mount
it read-only, and configure everything else with environment variables — see
`.env.example` and `docker-compose.prod.yml`.

- **Behind a reverse proxy, set `FORWARDED_ALLOW_IPS`** to the proxy's address or
  subnet. Without it every visitor is the proxy, and they all share one `/ask`
  allowance of 5 an hour.
- `/ask` is the only route that costs money. Anonymous askers pass Cloudflare
  Turnstile and get 5 an hour per IP; ORCID sign-in gives 20 a day; 500 a day
  across everyone. Missing keys switch `/ask` off rather than leaving it open.
- The model is the deployer's choice: Anthropic by default, or OpenRouter, Ollama
  or any OpenAI-compatible server (`ATLAS_LLM`, see `.env.example`). Run
  `atlas eval-ask` before trusting a new one.
- A data refresh never needs a new image: `atlas refresh`, read `atlas diff`,
  copy the store to where the container mounts it, restart.

## Licence

Code: MIT. Each data source keeps its own licence, tracked per source in
`docs/data-sources.md` — they are not all the same, and one of them (Mycobrowser)
states none at all.
