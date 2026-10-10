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
- Which resistance mutations are known?
- What does the protein do, where does it sit, how many papers is it in?
- Which drugs and clinical candidates act on it, at what phase for TB, and in
  which trials? What is co-crystallised with it?
- And from a compound: what does *it* touch, at what potency, and is it in the
  clinic?
- Which essential targets have a structure and no ligands?

## Status

Six milestones are in. Ten public sources, one store, one app.

```
make install      # uv venv + dependencies
make build        # whole pipeline -> data/store/*.parquet  (~15 min cold)
uv run atlas clinical   # the clinical stage alone, then the roll-up
make api          # FastAPI on :8099
make web          # the app on :5173
make test         # 224 tests against committed fixtures, no network
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
| `structures.parquet` | 4,803 | `pdb_id`, `uniprot_acc` | RCSB PDB |
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
| `drug_genes.parquet` | 233 | molecule, `rv_id`, link | joined |
| `trial_drugs.parquet` | 1,183 | `nct_id`, molecule | joined |
| `target_summary.parquet` | 4,173 | `rv_id` | rolled up |

See [`docs/data-sources.md`](docs/data-sources.md) for every endpoint, format,
licence and verification date, and [`CLAUDE.md`](CLAUDE.md) for the rules this
codebase is held to.

## Licence

Code: MIT. Each data source keeps its own licence, tracked per source in
`docs/data-sources.md` — they are not all the same, and one of them (Mycobrowser)
states none at all.
