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

**M0 complete.** Repo scaffold, verified data sources, and the ID crosswalk with
the gene annotation, proteome and ChEMBL target ingesters.

```
make install      # uv venv + dependencies
make build        # run the pipeline -> data/store/*.parquet
make test         # pytest against committed fixtures, no network
make lint
```

| Milestone | Scope |
|---|---|
| M0 ✅ | Scaffold, `docs/data-sources.md`, ID crosswalk + tests, gene annotation ingester |
| M1 | PDB, AlphaFold, ChEMBL bioactivity, essentiality and resistance ingesters |
| M2 | API: `/targets` (filter, sort), `/targets/{rv_id}` (full evidence record) |
| M3 | Target page: evidence panels + Mol* viewer with ligands and resistance mutations |
| M4 | Genome-wide 3D canvas: ~4,000 genes, coloured by essentiality / structure / ligands |
| M5 | Agent: natural-language queries over the store, answers cite records |

## The store

One Parquet file per source, rebuilt by the pipeline, read by DuckDB. Raw
downloads are cached on disk and gitignored. Every record carries `source`,
`source_version` and `retrieved_at`, and the UI shows provenance for every value.

| File | Rows | Key |
|---|---|---|
| `genes.parquet` | 4,031 | `rv_id` |
| `proteins.parquet` | 3,997 | `uniprot_acc` |
| `chembl_targets.parquet` | ~17,000 | `uniprot_acc` |
| `crosswalk.parquet` | 4,031 | `rv_id` |

See [`docs/data-sources.md`](docs/data-sources.md) for every endpoint, format,
licence and verification date, and [`CLAUDE.md`](CLAUDE.md) for the rules this
codebase is held to.

## Licence

Code: MIT. Each data source keeps its own licence, tracked per source in
`docs/data-sources.md` — they are not all the same, and one of them (Mycobrowser)
states none at all.
