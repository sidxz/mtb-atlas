"""A fixture store built from committed files. No test touches the network."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.sources import chembl, mycobrowser, uniprot
from atlas.store import write_parquet

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The three source tables, normalized from fixtures into a temp store."""
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
    return out
