"""A fixture store built from committed files. No test touches the network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas import clinical, crosswalk, summary
from atlas.sources import (
    alphafold,
    chembl,
    clinicaltrials,
    conditional,
    essentiality,
    mycobrowser,
    pdb,
    resistance,
    uniprot,
)
from atlas.store import read, write_parquet

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The identity stage: three source tables plus the crosswalk they join into."""
    out = tmp_path_factory.mktemp("store")
    write_parquet(
        "genes",
        mycobrowser.normalize(FIXTURES / "mycobrowser_h37rv.txt"),
        source=mycobrowser.SOURCE,
        source_version="release 5 (2024-07-11)",
        retrieved_at="2026-10-09",
        store=out,
    )
    write_parquet(
        "proteins",
        uniprot.normalize(FIXTURES / "uniprot_proteome.tsv"),
        source=uniprot.SOURCE,
        source_version="2026_03 02-September-2026",
        retrieved_at="2026-10-09",
        store=out,
    )
    write_parquet(
        "chembl_targets",
        chembl.normalize(FIXTURES / "chembl_uniprot_mapping.txt"),
        source=chembl.SOURCE,
        source_version=chembl.release(FIXTURES / "chembl_uniprot_mapping.txt"),
        retrieved_at="2026-10-09",
        store=out,
    )
    crosswalk.build(store=out, with_orthologues=False)
    return out


@pytest.fixture(scope="session")
def evidence_store(store: Path) -> Path:
    """The identity store plus every evidence and clinical table, all from fixtures.

    Built once so the summary roll-up can be tested end to end: the whole-cell
    attribution rule, the structural-gap definition and the drug link levels
    are the parts most likely to drift, and they only exist once the tables
    are joined.
    """
    entries = json.loads((FIXTURES / "rcsb_entries.json").read_text())
    accessions = {
        row[0] for row in read("crosswalk", store=store).project("uniprot_acc").fetchall() if row[0]
    }
    write_parquet(
        "structures",
        pdb.normalize(iter(entries), accessions),
        source=pdb.SOURCE,
        source_version="RCSB fixture",
        retrieved_at="2026-10-09",
        store=store,
    )
    write_parquet(
        "ligands",
        pdb.normalize_chem_comps(json.loads((FIXTURES / "rcsb_chem_comps.json").read_text())),
        source=pdb.SOURCE,
        source_version="RCSB chemical components fixture",
        retrieved_at="2026-10-09",
        store=store,
    )
    write_parquet(
        "predicted_structures",
        alphafold.normalize(json.loads((FIXTURES / "alphafold_predictions.json").read_text())),
        source=alphafold.SOURCE,
        source_version="AlphaFold DB v6",
        retrieved_at="2026-10-09",
        store=store,
    )
    bioactivity = json.loads((FIXTURES / "chembl_bioactivity.json").read_text())
    write_parquet(
        "activities",
        bioactivity["activities"],
        source=chembl.SOURCE,
        source_version="chembl_37",
        retrieved_at="2026-10-09",
        store=store,
    )
    write_parquet(
        "compounds",
        bioactivity["compounds"],
        source=chembl.SOURCE,
        source_version="chembl_37",
        retrieved_at="2026-10-09",
        store=store,
    )
    write_parquet(
        "essentiality",
        essentiality.normalize(FIXTURES / "dejesus_supplement.zip"),
        source=essentiality.SOURCE,
        source_version=essentiality.CITATION,
        retrieved_at="2026-10-09",
        store=store,
    )
    write_parquet(
        "conditional_fitness",
        conditional.normalize(FIXTURES / "griffin_supplement.zip"),
        source=conditional.SOURCE,
        source_version=conditional.CITATION,
        retrieved_at="2026-10-09",
        store=store,
    )
    write_parquet(
        "resistance",
        resistance.normalize(FIXTURES / "who_catalogue.txt"),
        source=resistance.SOURCE,
        source_version=resistance.EDITION,
        retrieved_at="2026-10-09",
        store=store,
    )
    extra = json.loads((FIXTURES / "extra_evidence.json").read_text())
    for name, source, version in (
        ("vulnerability", "bosch-2021", "Bosch 2021 Table S3"),
        ("interactions", "string-db", "STRING v12.5"),
        ("homology", "phmmer-human", "phmmer vs reviewed human proteome"),
    ):
        write_parquet(
            name,
            extra[name],
            source=source,
            source_version=version,
            retrieved_at="2026-10-09",
            store=store,
        )

    drug_rows, mechanism_rows = chembl.normalize_drugs(
        json.loads((FIXTURES / "chembl_drugs.json").read_text())
    )
    for name, rows in (("drugs", drug_rows), ("drug_mechanisms", mechanism_rows)):
        write_parquet(
            name,
            rows,
            source=chembl.SOURCE,
            source_version="chembl_37",
            retrieved_at="2026-10-10",
            store=store,
        )
    studies = json.loads((FIXTURES / "clinicaltrials_studies.json").read_text())
    write_parquet(
        "trials",
        clinicaltrials.normalize(studies["studies"]),
        source=clinicaltrials.SOURCE,
        source_version=clinicaltrials.version(studies["version"]),
        retrieved_at="2026-10-10",
        store=store,
    )
    clinical.build(store=store)
    summary.build(store=store)
    return store
