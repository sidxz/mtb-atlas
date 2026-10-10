# Mtb Target Atlas

Every *Mycobacterium tuberculosis* H37Rv gene as a navigable object, unifying the
evidence early drug discovery teams check during target selection and hit triage.

Built **only from public data**. No consortium data, ever.

The questions it exists to answer:

- Is this gene essential, and under which conditions?
- Is there an experimental structure? A predicted one? A druggable pocket?
- What chemical matter hits it, at what potency?
- Which resistance mutations are known?
- Which essential targets have a structure and no ligands?

## Status

All five milestones are in. Nine public sources, one store, one app.

```
make install      # uv venv + dependencies
make build        # whole pipeline -> data/store/*.parquet  (~15 min cold)
make api          # FastAPI on :8099
make web          # the app on :5173
make test         # 92 tests against committed fixtures, no network
```

| Milestone | Scope | |
|---|---|---|
| M0 | Scaffold, verified sources, ID crosswalk + tests, gene annotation | ✅ |
| M1 | PDB, AlphaFold, ChEMBL bioactivity, essentiality, resistance | ✅ |
| M2 | API: `/targets`, `/targets/{rv_id}`, `/compounds/{id}`, `/meta` | ✅ |
| M3 | Target page: evidence panels + Mol* with ligands and resistance residues | ✅ |
| M4 | Genome canvas: all 4,173 genes, recolourable by any evidence axis | ✅ |
| M5 | Agent: natural-language questions, answers cite the records | ✅ |
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
| `vulnerability.parquet` | 4,005 | `rv_id` | Bosch 2021 |
| `resistance.parquet` | 48,152 | gene, mutation, drug | WHO catalogue |
| `interactions.parquet` | 28,739 | `rv_id`, `partner_rv_id` | STRING |
| `homology.parquet` | 3,997 | `uniprot_acc` | phmmer vs human |
| `target_summary.parquet` | 4,173 | `rv_id` | rolled up |

See [`docs/data-sources.md`](docs/data-sources.md) for every endpoint, format,
licence and verification date, and [`CLAUDE.md`](CLAUDE.md) for the rules this
codebase is held to.

## Licence

Code: MIT. Each data source keeps its own licence, tracked per source in
`docs/data-sources.md` — they are not all the same, and one of them (Mycobrowser)
states none at all.
