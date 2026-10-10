"""Predicted structures from AlphaFold DB, keyed on UniProt accession.

Licence: CC BY 4.0, stated inside every model file ("Data in this file is
available under a CC-BY-4.0 license").

There is no bulk metadata file carrying pLDDT — the only options are one
request per accession or a 449 MB tar of coordinates — so this fetches ~4,000
small JSON documents concurrently. The `/files/` endpoint returns HTTP 403 to
requests without a User-Agent, which `atlas.fetch` always sets.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from ..fetch import fetch_json_many
from ..store import write_parquet

SOURCE = "alphafold"
API = "https://alphafold.ebi.ac.uk/api/prediction/"


def normalize(payloads: dict[str, object]) -> Iterator[dict[str, Any]]:
    for url, payload in payloads.items():
        models = payload if isinstance(payload, list) else []
        if not models:
            continue
        model = models[0]
        yield {
            "uniprot_acc": url.rsplit("/", 1)[-1],
            "entry_id": model.get("entryId"),
            "version": model.get("latestVersion"),
            "created": (model.get("modelCreatedDate") or "")[:10],
            "plddt_mean": model.get("globalMetricValue"),
            "plddt_very_high": model.get("fractionPlddtVeryHigh"),
            "plddt_confident": model.get("fractionPlddtConfident"),
            "plddt_low": model.get("fractionPlddtLow"),
            "plddt_very_low": model.get("fractionPlddtVeryLow"),
            "cif_url": model.get("cifUrl"),
            "pae_url": model.get("paeDocUrl"),
            "tool": model.get("toolUsed"),
        }


def build(accessions: Sequence[str], *, retrieved_at: str, force: bool = False) -> Any:
    del force
    payloads = fetch_json_many(
        [f"{API}{a}" for a in accessions], workers=8, min_interval=0.05, label="alphafold"
    )
    rows = list(normalize(payloads))
    versions = {r["version"] for r in rows if r["version"]}
    return write_parquet(
        "predicted_structures",
        rows,
        source=SOURCE,
        source_version=f"AlphaFold DB v{max(versions)}" if versions else "AlphaFold DB",
        retrieved_at=retrieved_at,
    )
