# Mtb Target Atlas — working rules

A browser app where every *M. tuberculosis* H37Rv gene is a navigable object,
unifying the evidence early drug discovery teams check during target selection
and hit triage.

**Public data only. No consortium data, ever.** Every source is listed in
`docs/data-sources.md` with its licence. If a source is not in that file, it does
not go in the pipeline.

## Commands

```bash
make install          # uv venv + dependencies (also: uv pip install -e '.[dev]')
make build            # run the pipeline -> data/store/*.parquet  (~75 s cold, seconds warm)
make build-force      # ignore the raw cache and re-download (picks up upstream releases)
make summary          # row counts and conflict counts from the crosswalk
make test             # pytest, fixtures only, no network
make lint             # ruff check + ruff format --check
make fmt              # ruff format
```

No Docker Compose, FastAPI, RDKit or frontend yet — those arrive with M2/M3.
Adding them before their milestone is scaffolding for later; later can scaffold
for itself.

## Canonical key

The **Rv locus tag** (`Rv3790`). Every source maps to it. The gene universe is
Mycobrowser's 4,031 `CDS` loci.

Rv → UniProt accession is a function; **accession → Rv is not**. 55 loci share an
accession with at least one sibling (`Rv1180`/`Rv1181`, and the IS6110
transposase across 16 loci). Anything that attributes structures or ligands to a
gene must respect `shared_accession` / `shares_accession_with`, or siblings will
silently claim each other's evidence.

## Architecture rules

- **One ingester module per source** in `atlas/sources/`, each exposing the same
  three functions: `fetch_raw` → `normalize` → `build`. Same shape, no abstract
  base class — an interface with one implementation per source earns nothing.
- **All fetching goes through `atlas/fetch.py`.** It owns the cache, the
  User-Agent (AlphaFold returns 403 without one), the retry/backoff on 429 and
  5xx, and the per-host rate limit. Ingesters are idempotent and resumable: a
  cached file is returned untouched, so re-running costs nothing.
- **Raw downloads are cached in `data/raw/` and gitignored.** Each file gets a
  `.meta.json` sidecar with url, sha256, retrieval date and response headers —
  that sidecar is where provenance comes from.
- **Tests run against committed fixtures, never the network.** See
  `tests/fixtures/README.md` for which locus proves what.
- **The API reads only the normalized store. The frontend reads only the API.**
- **Every record carries `source`, `source_version`, `retrieved_at`**, stamped by
  `store.write_parquet`. The UI shows provenance for every value. A source that
  will not state its version gets `"unknown"` recorded, not a guess.
- Normalization logic lives in Python (it is branchy, and branchy code belongs
  somewhere testable); DuckDB only types the rows and writes the Parquet.

## Evidence must stay honest

This is the rule that outranks completeness.

- An absent record is a real answer, not a gap to paper over. "Essential, has a
  structure, no ligands" is a question the atlas exists to answer, so a zero
  must be able to mean zero.
- ChEMBL evidence is labelled `direct` | `orthologue` | `whole_cell`, never
  flattened into one ligand count. A direct Mtb target always wins; orthologue
  links attach only where there is no direct target, and carry their source
  organism, UniRef cluster, cluster size and identity level. **UniRef50 means 50%
  identity** — a 611-member cluster is not evidence of a shared binding site, so
  the UI shows the level rather than hiding it.
- Whole-cell MIC attaches to a gene **only** through a compound that already has
  direct or orthologue activity on it. Attaching cell data to a gene with no
  protein-level link invents an association that is not in the data.
- Source disagreements are recorded, not resolved silently: `acc_status`,
  `conflict`, and both sources' values side by side.
- Two of the three reference targets have **no** WHO resistance data, because the
  catalogue covers 65 genes and neither `dprE1` nor `mmpL3` is one. That is
  reported as an absence. Do not substitute a different source to fill the cell.
- **Essentiality and vulnerability answer different questions and must not be
  conflated.** TnSeq says whether a gene can be deleted. CRISPRi vulnerability
  says how far expression must fall before fitness suffers -- the question an
  inhibitor actually poses -- on a negative scale where only ~600 genes carry
  the study's own `certain` flag. Show the flag; never present an uncertain
  index as measured.
- **"Essential" means ES or ESD.** Growth-defect is a real but weaker signal and
  lives in `fitness_cost`. Folding it into the word "essential" adds 135 genes.
- **Human homology is computed, not looked up, and always shown with its
  number.** UniRef co-membership was tried and returned zero homologs for all
  3,978 accessions, because UniRef50 clusters above the 25-40% range where
  Mtb-human homology lives. phmmer gives an E-value and a percent identity; the
  30% "close" threshold is this atlas's convention, so the identity sits next to
  the flag.
- No druggability claim without a source. Nothing public supplies one today; see
  the open question in `docs/data-sources.md`.

## Validation targets

Every milestone is checked against three genes, which between them cover the
interesting shapes:

| Gene | Rv tag | Why |
|---|---|---|
| DprE1 | `Rv3790` | Essential (`ES`), 31 structures, direct ChEMBL target, **no** WHO entry |
| InhA | `Rv1484` | Essential (`ES`), 135 structures, best-studied chemistry, full WHO entry |
| MmpL3 | `Rv0206c` | Essential domain (`ESD`), 1 structure, ligands **only** via the *M. smegmatis* orthologue, no WHO entry, most vulnerable of the three (-11.0) |

A fourth is worth keeping to hand: **GroEL2 (`Rv0440`)** is essential and highly
vulnerable (-11.6) and would look like an excellent target, except that it is
48% identical to human HSPD1. It is the case that proves the anti-target column
is doing work.

## Extension point, deliberately empty

Per-compound annotations (a nuisance-compound classifier) plug in against
`molecule_chembl_id` as a separate Parquet file with its own provenance. **Do not
implement the classifier.** The seam exists so it can be added, re-run and
versioned without touching an ingester or a bioactivity row.

## The agent

`atlas/agent.py` gives a model two tools: the store's schema and read-only SQL.
One query tool beats ten narrow ones, because the questions a target biologist
asks are joins.

It is safe because the tables are copied into an in-memory DuckDB and then
`enable_external_access` is turned off and the configuration locked, so no
statement can read a file, attach a database or reach the network -- with a
single-SELECT guard and a row cap on top. **That sandbox is the only thing
between a generated string and the filesystem; it has its own tests and they
test the lock as well as the guard.**

The schema dump carries each table's trap (join `structures` on `uniprot_acc`
not `rv_id`; `resistance` is keyed on gene symbol; the vulnerability index is
negative), because a model that writes a plausible wrong join gets silent
nonsense rather than an error.

## Conventions

- Small commits, conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`).
- Python 3.12, `uv`, ruff (line length 100).
- Stop at the end of each milestone with a summary and open questions.
