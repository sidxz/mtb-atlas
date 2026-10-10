# Mtb Target Atlas — working rules

A browser app where every *M. tuberculosis* H37Rv gene is a navigable object,
unifying the evidence a TB drug discovery team checks from target selection and
hit triage through to clinical trials.

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
make api / make web   # FastAPI on :8099, the app on :5173
uv run atlas clinical # rebuild just the clinical stage (drugs, trials, links) and the roll-up

make check                    # has anything released upstream? six requests, seconds
make refresh SOURCE=chembl    # re-download one source, rebuild only what it feeds
make diff                     # what that did to the numbers
```

## Keeping it current

`build` on a warm cache is a no-op and `build-force` re-downloads everything,
including four sources that cannot have changed. The three commands above are
the middle ground, and they are the whole update policy:

- **`atlas check`** asks each source by the cheapest route it offers and
  compares to the `source_version` already on its table. **A probe that fails
  reports `unknown`, never `current`** — a dead endpoint says nothing about
  the data behind it. Sources that cannot move are `frozen`, not `unknown`, so
  the report does not train you to ignore it. `--expensive` adds the RCSB
  probe, which has to replay the structure search to count entries (~6 s).
  - The probe must read the **same statement** the table was stamped from.
    ChEMBL says `chembl_37 (01/05/2026)` in the mapping file and
    `ChEMBL_37 (2026-05-01)` through the API; both are faithful and neither is
    reformatted into the other, so the probe compares against `activities`.
  - Mycobrowser's URL is pinned to a release number, so hashing the download
    compares release 5 to release 5 forever. The probe asks for the *next*
    release instead: 204 and an empty body means it does not exist.
- **`atlas refresh <source>`** drops that source's raw cache and runs the
  stages from its own to the end — `chembl` starts at identity because
  `chembl_targets` is built there, `clinicaltrials-gov` touches only clinical
  and the roll-up. It snapshots the store to `data/store.prev` first.
- **`atlas diff`** compares the two **on each table's key, not its row count**.
  A table that gains ten rows and loses ten has a delta of zero; that is how
  an upstream removal hides, and the outage guard in `fetch.py` cannot see it
  because the download succeeded.

Cadence: trials monthly, ChEMBL/UniProt/PDB when `check` says so, Mycobrowser
only when it moves (it re-keys every gene), papers never.

No Docker Compose, and **no RDKit in the pipeline**. Add infrastructure when a
milestone needs it; adding it earlier is scaffolding for later, and later can
scaffold for itself.

RDKit does now run, as WebAssembly **in the browser only** (`web/src/Structure.tsx`),
to draw compounds from the SMILES the API already serves. That is the
presentation layer: a depiction is a rendering of a SMILES, not a fact about
the molecule, so no depiction is stored, no ingester imports rdkit, and
`make build` and `make test` are unchanged. It is fetched on first use, so
nobody who does not open a chemistry tab pays the 7.4 MB. If a *pipeline* ever
needs rdkit — a descriptor, a scaffold key, a nuisance filter — that is a
separate decision against the rule above, not a precedent set by this one.

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
- **"Is there an assay" is not "is there a hit."** `n_protein_assays` counts
  distinct ChEMBL assays on the gene's own protein (`evidence = 'direct'`), and
  431 essential genes have none. Never read `assay_type = 'F'` as a protein
  assay: ChEMBL files whole-cell MICs that way against the organism, so the
  genome holds 3,083 of them over two "targets".
- Source disagreements are recorded, not resolved silently: `acc_status`,
  `conflict`, and both sources' values side by side.
- Two of the three reference targets have **no** WHO resistance data, because the
  catalogue covers 65 genes and neither `dprE1` nor `mmpL3` is one. That is
  reported as an absence. Do not substitute a different source to fill the cell.
- **A TnSeq screen cannot measure a gene with no insertions**, and every
  in-vitro-essential gene is one. Griffin 2011's cholesterol comparison reads
  `n/a` for dprE1, inhA and mmpL3, which is recorded as `measured = false` and
  must never be shown as "no effect". A locus the screen never covered is NULL
  — a third state. None of the 96 cholesterol-required genes is also called
  essential; the two screens see disjoint sets of genes.
- **Essentiality and vulnerability answer different questions and must not be
  conflated.** TnSeq says whether a gene can be deleted. CRISPRi vulnerability
  says how far expression must fall before fitness suffers -- the question an
  inhibitor actually poses -- on a negative scale where only ~600 genes carry
  the study's own `certain` flag. Show the flag; never present an uncertain
  index as measured.
- **"Essential" means ES or ESD.** Growth-defect is a real but weaker signal and
  lives in `fitness_cost`. Folding it into the word "essential" adds 135 genes.
- **Vulnerability is measured in a strain, and H37Rv is not the only one.**
  `strain_vulnerability` holds Bosch's HN878 series; `vulnerability` holds
  H37Rv, and a comparison is a join. `delta_vi` runs **HN878 minus H37Rv**, so
  positive is *less* vulnerable in the clinical isolate (accD6 −11.45 → −2.27).
  It is reported for 507 genes, which is the authors' own subset of the 576
  confident in both, so a NULL delta is not a difference of zero and
  `differential_reported` says which it is. `delta_vi_norm` is not a rescaling
  and can disagree in sign. The *M. smegmatis* sheet is deliberately not
  ingested: an `MSMEG` tag reaches an Rv locus only through an orthologue
  bridge this atlas does not have.
- **Human homology is computed, not looked up, and always shown with its
  number.** UniRef co-membership was tried and returned zero homologs for all
  3,978 accessions, because UniRef50 clusters above the 25-40% range where
  Mtb-human homology lives. phmmer gives an E-value and a percent identity; the
  30% "close" threshold is this atlas's convention, so the identity sits next to
  the flag.
- No druggability claim without a source. Nothing public supplies one today; see
  the open question in `docs/data-sources.md`.
- **TB phase is not overall phase.** `drugs.max_phase_tb` is the highest phase
  ChEMBL records for a tuberculosis indication. `max_phase` is for any
  indication: linezolid is approved, and phase 3 for TB. The drug set is
  ChEMBL's TB indications, unedited (host-directed adjuncts, HIV co-medications
  and placebo excipients included), made filterable rather than curated away.
- **A drug acts on a gene only when a source names that gene's protein**: a
  ChEMBL single-protein mechanism, or Bosch 2021's annotation matched exactly
  to a ChEMBL synonym. Membership of the complex a drug is filed against
  (bedaquiline: all eight ATP synthase subunits) and WHO-graded resistance are
  shown, never counted. **Resistance is not engagement**: katG activates
  isoniazid. A mechanism target from another organism (rifampicin's *E. coli*
  RNA polymerase) reaches no Mtb gene, and no homology bridge is built to make
  it. See `atlas/clinical.py`.
- **A trial links to a drug** through ChEMBL's curated reference or an exact
  match of a cleaned intervention name. Other names are a fallback only,
  because sponsors list drug classes there, and a name two molecules share
  links neither. Studies of nontuberculous mycobacteria are not TB trials.

## Validation targets

Every milestone is checked against three genes, which between them cover the
interesting shapes:

| Gene | Rv tag | Why |
|---|---|---|
| DprE1 | `Rv3790` | Essential (`ES`), 31 structures, direct ChEMBL target, **no** WHO entry; macozinone and TBA-7371 (phase 2) by ChEMBL mechanism, while BTZ-043 and quabodepistat have none in ChEMBL and so reach no gene |
| InhA | `Rv1484` | Essential (`ES`), 135 structures, best-studied chemistry, full WHO entry; isoniazid and ethionamide, approved |
| MmpL3 | `Rv0206c` | Essential domain (`ESD`), 1 structure, ligands **only** via the *M. smegmatis* orthologue, no WHO entry, most vulnerable of the three (-11.0); SQ109 (phase 2) **only** through Bosch 2021, because ChEMBL records no mechanism for it |

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
negative; `max_phase_tb` is not `max_phase`; a `who_resistance` link is not a
target), because a model that writes a plausible wrong join gets silent
nonsense rather than an error.

## Querying it

Four ways in, and they all read the same store: the genome canvas, the drugs
and trials view, `/search` over every object at once, and the agent. A new kind
of evidence is not finished until the agent's schema carries its trap, because
that is the only surface where a wrong join is silent.

## Conventions

- Small commits, conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`).
- Python 3.12, `uv`, ruff (line length 100).
- Stop at the end of each milestone with a summary and open questions.
