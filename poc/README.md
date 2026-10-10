# Proof-of-concept views

Two pages built on the M0 store, to show what M3 and M4 look like before
building them. **Neither is part of the pipeline**, and both should be deleted
once the milestones they preview land.

| Page | Previews | What it shows |
|---|---|---|
| `atlas-canvas.html` | M4 | All 4,031 genes on the circular chromosome, coloured by essentiality, structure coverage, chemical matter or resistance. Filters, search, and a detail panel that names a source for every value. |
| `target-dossier.html` | M3 | Four targets side by side, each with its evidence panels and a 3D structure carrying its ligands and WHO-graded resistance residues. |

## Rebuilding the data

`build_poc_data.py` stands in for the M1 ingesters. It reads
`data/store/crosswalk.parquet` and adds essentiality, ligand potency and
resistance. It needs two files the pipeline does not fetch yet:

```bash
# DeJesus 2017 Table S3 — the PMC download is bot-blocked, Europe PMC is not
curl -L -o supp.zip \
  'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5241402/supplementaryFiles'
unzip -j supp.zip 'mbo002173137st3.xlsx' -d raw/

# WHO catalogue 2nd edition master file
curl -L -o 'raw/who-master.txt' \
  'https://raw.githubusercontent.com/GTB-tbsequencing/mutation-catalogue-2023/main/Final%20Result%20Files/WHO-UCN-TB-2023.6-eng_catalogue_master_file.txt'

uv run python poc/build_poc_data.py \
  --dejesus raw/mbo002173137st3.xlsx --who raw/who-master.txt \
  --focus Rv3790 Rv1484 Rv0206c Rv1908c Rv0667
```

That writes `poc/data/atlas-poc.json` (~1.9 MB, the whole genome) and the pages
read it over a relative URL. `poc/data/` is gitignored, like every other
download. The dossier also needs structure files in `poc/data/structures/`:
`4KW5`, `1ZID`, `7NVH` and `2CCA` from `files.rcsb.org/download/<id>.pdb`, plus
`AF-P9WJV5-F1-model_v6.cif` from AlphaFold.

Serve the directory over HTTP (`python -m http.server`) rather than opening the
files directly — `file://` blocks the relative fetches.

## What the POCs established

- **Residue numbering lines up.** KatG Ser315 and Trp328, InhA Ser94 and DprE1
  Cys387 are each the expected amino acid at that author-numbered position in
  the deposited coordinates. M3's mutation mapping rests on this, and it was
  checked against the files rather than assumed.
- **163 genes are essential, have an experimental structure, and have no
  ligands.** The question the atlas exists to answer returns a list short enough
  to read.
- **Mol\* cannot do per-residue selection from a CDN.** Its prebuilt viewer
  bundle exports only `Viewer`, `PluginExtensions`, `setDebugMode` and
  `setSubtreeVisibility` — the selection and query API is not reachable. These
  pages use 3Dmol 2.4.2 instead. This is a constraint of a single-file page, not
  of the project: M3 builds with Vite from npm, where Mol\*'s selection API is
  available, and Mol\* remains the choice.
- **Most resistance is not structural.** 14 of InhA's 15 WHO-graded variants are
  promoter mutations, and most of KatG's are frameshifts or stop codons. A
  viewer that silently dropped them would overstate how much of a gene's
  resistance a structure can explain, so the variant table lists them and marks
  them "not a residue".
