# Compound structures for the screening layer — design

Approved in chat 2026-10-11. Follows `2026-10-11-screens-smiles-handoff.md`, which states the
problem and three constraints; this records the decisions and the measurements behind them.

## What and why

About 99% of the screening layer cannot be drawn: `compounds` is the ChEMBL potency set, and the
pages draw from it. ChEMBL publishes every compound's structure as one flat file
(`chembl_37_chemreps.txt.gz`, 292,540,141 bytes). One download covers the whole screened set.

## Measured against the downloaded file (ChEMBL 37, store as of 2026-10-11)

| | |
|---|---|
| rows in the file | 2,897,819 (one per `chembl_id`, none with a blank SMILES) |
| ids the store references (`screen_results` ∪ `compounds`) | 479,893 |
| of those, in the file | **479,853** |
| of those, not in the file | **40** |
| screened ids (`screen_results`) in the file | 478,985 of 479,023 |
| `compounds.smiles` equal to the file's `canonical_smiles` | 5,173 of 5,173 non-NULL; 0 differ |
| `compounds.inchi_key` differing from the file's key | 0 |
| `compounds` rows with a NULL SMILES | 5, and all 5 are among the ids the file lacks |

The two sources agree everywhere they overlap, so there is no conflict to record. If a later
release makes them disagree, `compounds` is untouched and the two columns can be compared side by
side; nothing reconciles them.

## Decisions

1. **New table `compound_structures`, from a new module `atlas/sources/chemreps.py`**
   (`fetch_raw` → `normalize` → `build`, shaped like `unichem.py`). It is built in the evidence
   stage, immediately after the screening layer, because its key set is read from
   `screen_results`.
2. **Key set: every `molecule_chembl_id` in `screen_results` and `compounds`.** `drugs` (101
   further ids) carries its own `smiles` and is built in the later clinical stage, so it is out.
   PubChem-only CIDs have no ChEMBL id and are out, as the handoff says: an unmapped CID is a
   different problem from an unfetched SMILES.
3. **Three states, using a `has_structure` column that is never NULL.**
   - A row with `true` has a SMILES.
   - A row with `false` means **ChEMBL 37's structure file has no line for this id**: it was looked
     up and not found. The file omits molecules without a structure and any id not in the release.
     This is what the column states. It is not a claim that the molecule has no structure.
   - **No row** means the id was never looked up. That covers PubChem-only CIDs, and any id a
     future table references before this one is rebuilt. A LEFT JOIN gives `has_structure IS
     NULL`, so this state cannot collapse into `false`.
4. **Columns:** `molecule_chembl_id`, `has_structure`, `canonical_smiles`, `standard_inchi_key`,
   then `source`, `source_version` and `retrieved_at`. The InChIKey stays: it is the key
   `compounds.inchi_key` and `ligands.inchikey` already use, and it is small. `standard_inchi` is
   dropped.
5. **Provenance.** `source = "chembl"`, `source_version = "chembl_37"`, the release the file
   names. The URL is built from the release the ChEMBL mapping file states (the identity stage has
   already fetched it). The raw file is cached at
   `data/raw/chembl/chemreps/chembl_37_chemreps.txt.gz`.
   - `atlas refresh chembl` drops that cache and runs through the evidence stage.
   - A new release changes the URL, and `fetch` re-downloads when the URL changes.
   - ChEMBL's existing freshness probe already covers when the release moves, so there is no new
     `Source` entry.
6. **Parsing in Python.** The gzip is streamed and only wanted ids are kept. The header line is
   checked, as UniChem's is, so that a file whose first line is not the header is refused rather
   than losing a row. `fetch()` holds the 292 MB body in memory once during the download, which is
   accepted.
7. **Registration:** `storediff.KEYS["compound_structures"] = ("molecule_chembl_id",)`, an entry in
   `agent.TABLES`, and a `TABLE_NOTES` entry. The note says three things:
   - join on `molecule_chembl_id`;
   - NULL from the join is "never looked up", and `false` is "not in this release's structure
     file";
   - a structure is a drawing input, not evidence.

   `api.LICENCES` gets `("ChEMBL", "CC BY-SA 3.0")`.
8. **API wiring (approved).** `atlas/api.py` draws from `compound_structures` instead of
   `compounds` in three places, keeping the field name `smiles` so `web/src` is untouched:
   - `/screens/{id}/results`: the row's `smiles` and `n_with_structure`;
   - `/hits`: the row's `smiles` and `population.with_structure`;
   - `/compounds/{id}`: the record for a screen-only compound, which today has no `smiles`.

   `pref_name` still comes from `compounds`. A store built before this table exists must still
   answer, so the API gets an empty stand-in, the same way `EMPTY_CLINICAL` does it.
9. **Removals folded into the same rebuild.** `screens.library_name` and `screens.deposit_kind`
   leave both ingesters, the tests that name them, the agent note, `docs/data-sources.md` and
   `CLAUDE.md`. Follow-ups 7 and 8 in `docs/data-sources.md` are marked done.
10. **`CLAUDE.md:386`**, "389 rows of the selectivity-index family are not TB", is corrected to
    the wording `37711aa` gave `atlas/agent.py`: 32 of those rows are tuberculosis, written
    `TBMIC`.

## Testing

- A committed fixture of chemreps lines (header, a wanted id, an unwanted id, a malformed line).
  Tests cover:
  - the header check;
  - only wanted ids being kept;
  - `has_structure` false for a wanted id missing from the file;
  - no row for an id that was never wanted.
- `test_upkeep`'s `set(agent.TABLES) == set(storediff.KEYS)` check covers the registration.
- API tests: a screen-only compound gets its `smiles` from the new table, `n_with_structure`
  counts from it, and a store without the table still answers.
- Every new test is mutation-proved: break the code it covers and watch it fail.
- After the rebuild, every figure that changes in the docs is re-measured with DuckDB against the
  store. That includes the 99% figure, the 2,013 of 23,730, and the 200 of 12,676.

## Out of scope

- Structures for PubChem-only CIDs.
- Structures for `drugs`.
- Any descriptor or depiction stored in the pipeline. RDKit stays in the browser only.
