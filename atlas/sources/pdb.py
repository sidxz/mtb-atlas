"""Experimental structures from RCSB PDB, keyed on UniProt accession.

Licence: CC0 1.0 — "data files contained in the PDB archive are available under
the CC0 1.0 Universal Public Domain Dedication. All data provided by RCSB PDB
programmatic APIs are available under the same license."

Two things this ingester refuses to do, both learned from the live API:

* It does not search by organism. Querying taxon 83332 returns 1,846 entries and
  misses 7NVH (MmpL3), 1ZID (InhA) and 2CCA (KatG), because those are deposited
  under taxon 1773. Accession is the only reliable key.
* It does not trust `rcsb_entry_info.nonpolymer_bound_components`, which is null
  on entries that plainly have ligands (4KW5). Ligands come from the
  nonpolymer entities themselves.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from ..fetch import post_json
from ..store import write_parquet

SOURCE = "rcsb-pdb"
SEARCH = "https://search.rcsb.org/rcsbsearch/v2/query"
GRAPHQL = "https://data.rcsb.org/graphql"
ACCESSION_ATTR = (
    "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession"
)

# The search endpoint accepts long `in` lists; 300 keeps URLs and payloads sane.
SEARCH_BATCH = 300
# GraphQL returns a lot per entry, so keep these small enough to stay responsive.
ENTRY_BATCH = 50

ENTRY_QUERY = """
query($ids: [String!]!) {
  entries(entry_ids: $ids) {
    rcsb_id
    struct { title }
    exptl { method }
    rcsb_entry_info { resolution_combined deposited_polymer_entity_instance_count }
    rcsb_accession_info { initial_release_date }
    polymer_entities {
      rcsb_polymer_entity { pdbx_description }
      rcsb_polymer_entity_container_identifiers {
        auth_asym_ids
        reference_sequence_identifiers { database_accession database_name }
      }
    }
    nonpolymer_entities {
      nonpolymer_comp { chem_comp { id name formula_weight } }
      rcsb_nonpolymer_entity_container_identifiers { auth_asym_ids }
    }
  }
}
"""

# Crystallisation additives, cryoprotectants and buffer components. Counting
# these as "chemical matter bound to the target" would badly overstate how many
# structures carry a real ligand.
INCIDENTAL = frozenset(
    {
        "HOH",
        "GOL",
        "EDO",
        "PEG",
        "PG4",
        "PGE",
        "1PE",
        "2PE",
        "P6G",
        "MPD",
        "DMS",
        "SO4",
        "PO4",
        "CL",
        "NA",
        "K",
        "MG",
        "CA",
        "ZN",
        "MN",
        "FE",
        "NI",
        "CD",
        "ACT",
        "ACY",
        "FMT",
        "EPE",
        "TRS",
        "MES",
        "IMD",
        "CIT",
        "TLA",
        "BME",
        "IOD",
        "BR",
        "NO3",
        "NH4",
        "CO3",
        "AZI",
        "SCN",
        "CAC",
        "MLI",
        "OXL",
        "GLC",
        "BOG",
    }
)
# Cofactors are real and worth showing, but they are not what a medicinal
# chemist means by "has a ligand".
COFACTORS = frozenset(
    {
        "FAD",
        "FMN",
        "NAD",
        "NAI",
        "NAP",
        "NDP",
        "ADP",
        "ATP",
        "AMP",
        "GDP",
        "GTP",
        "COA",
        "ACO",
        "SAM",
        "SAH",
        "HEM",
        "HEC",
        "PLP",
        "TPP",
        "B12",
        "F43",
        "MQ7",
        "UDP",
        "UTP",
        "CTP",
        "TTP",
        "PPS",
        "APC",
        "ANP",
        "AGS",
    }
)


def _entity_ids(accessions: Sequence[str]) -> list[str]:
    """Polymer entity IDs (e.g. `7NVH_1`) for every accession we know."""
    found: list[str] = []
    for start in range(0, len(accessions), SEARCH_BATCH):
        batch = list(accessions[start : start + SEARCH_BATCH])
        payload = {
            "query": {
                "type": "terminal",
                "service": "text",
                "parameters": {"attribute": ACCESSION_ATTR, "operator": "in", "value": batch},
            },
            "return_type": "polymer_entity",
            "request_options": {"return_all_hits": True, "results_verbosity": "compact"},
        }
        result = post_json(SEARCH, payload, min_interval=0.4)
        found.extend(result.get("result_set") or [])
    return found


def _entries(entry_ids: Sequence[str]) -> Iterator[dict[str, Any]]:
    for start in range(0, len(entry_ids), ENTRY_BATCH):
        batch = list(entry_ids[start : start + ENTRY_BATCH])
        payload = {"query": ENTRY_QUERY, "variables": {"ids": batch}}
        result = post_json(GRAPHQL, payload, min_interval=0.3)
        if result.get("errors"):
            raise RuntimeError(f"RCSB GraphQL: {result['errors'][0].get('message')}")
        yield from (e for e in (result.get("data") or {}).get("entries") or [] if e)


def classify(comp_id: str) -> str:
    if comp_id in INCIDENTAL:
        return "incidental"
    if comp_id in COFACTORS:
        return "cofactor"
    return "ligand"


def normalize(entries: Iterator[dict[str, Any]], accessions: set[str]) -> Iterator[dict[str, Any]]:
    """One row per (PDB entry, accession) pair the atlas knows about."""
    for entry in entries:
        resolution = (entry.get("rcsb_entry_info") or {}).get("resolution_combined") or []
        methods = [m["method"] for m in entry.get("exptl") or [] if m.get("method")]
        components = [
            {
                "comp_id": c["id"],
                "name": c.get("name"),
                "formula_weight": c.get("formula_weight"),
                "role": classify(c["id"]),
                "chains": (n.get("rcsb_nonpolymer_entity_container_identifiers") or {}).get(
                    "auth_asym_ids"
                )
                or [],
            }
            for n in entry.get("nonpolymer_entities") or []
            if (c := (n.get("nonpolymer_comp") or {}).get("chem_comp"))
        ]
        ligands = [c for c in components if c["role"] == "ligand"]

        seen: set[str] = set()
        for polymer in entry.get("polymer_entities") or []:
            identifiers = polymer.get("rcsb_polymer_entity_container_identifiers") or {}
            for reference in identifiers.get("reference_sequence_identifiers") or []:
                accession = reference.get("database_accession")
                if reference.get("database_name") != "UniProt" or accession not in accessions:
                    continue
                # A homodimer lists one polymer entity per chain group; the
                # entry still belongs to the accession exactly once.
                if accession in seen:
                    continue
                seen.add(accession)
                yield {
                    "pdb_id": entry["rcsb_id"],
                    "uniprot_acc": accession,
                    "title": (entry.get("struct") or {}).get("title"),
                    "method": methods[0] if methods else None,
                    "resolution": resolution[0] if resolution else None,
                    "released": (entry.get("rcsb_accession_info") or {}).get(
                        "initial_release_date", ""
                    )[:10],
                    "chains": identifiers.get("auth_asym_ids") or [],
                    "entity_description": (polymer.get("rcsb_polymer_entity") or {}).get(
                        "pdbx_description"
                    ),
                    "components": components,
                    "ligand_ids": [c["comp_id"] for c in ligands],
                    "n_ligands": len(ligands),
                }


def build(accessions: Sequence[str], *, retrieved_at: str, force: bool = False) -> Any:
    """`accessions` comes from the crosswalk: PDB is keyed on accession, not Rv tag."""
    del force  # Nothing is cached on disk; the API batches are cheap to repeat.
    entity_ids = _entity_ids(accessions)
    entry_ids = sorted({str(eid).split("_")[0] for eid in entity_ids})
    rows = list(normalize(_entries(entry_ids), set(accessions)))
    return write_parquet(
        "structures",
        rows,
        source=SOURCE,
        source_version=f"RCSB Search + Data API, {len(entry_ids)} entries",
        retrieved_at=retrieved_at,
    )
