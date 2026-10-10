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
* It does not attribute an entry's ligands to every protein in the entry. The
  component list belongs to the whole entry, so in a complex each subunit would
  claim its neighbours' chemical matter: in 5UHB rifampicin is modelled on chain
  C, which is rpoB, while rpoA, rpoC, rpoZ and sigA are other chains entirely.
  A ligand counts for an accession only when their chains meet; the rest are
  kept visible in `ligand_ids_elsewhere`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
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
      rcsb_polymer_entity { pdbx_description pdbx_mutation }
      entity_poly { rcsb_sample_sequence_length }
      entity_src_gen { pdbx_host_org_scientific_name pdbx_host_org_strain plasmid_name }
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


# `pdbx_mutation` states the absence of one in words as often as it states one,
# and in whatever case the depositor typed.
NO_MUTATION = frozenset({"wild-type", "wild type", "wt", "none", "no", "-", "n/a", "na"})


def _host(source: dict[str, Any]) -> str | None:
    """Expression host as one string, without repeating the strain.

    Depositors put the strain in either field or both: 1ZID gives host
    `Escherichia coli BL21` and strain `BL21`, which naively joined reads
    "Escherichia coli BL21 BL21". Casing is left as deposited -- 2CCA's
    `ESCHERICHIA COLI UM262` is what the entry says, and tidying it would be
    editing the source.
    """
    name = (source.get("pdbx_host_org_scientific_name") or "").strip()
    strain = (source.get("pdbx_host_org_strain") or "").strip()
    if strain and strain.lower() not in name.lower():
        name = f"{name} {strain}".strip()
    return name or None


def _construct(entities: list[dict[str, Any]]) -> dict[str, Any]:
    """What was expressed, pooled over every entity the accession owns.

    A structure is itself evidence that the protein has been produced; this is
    the entry saying how. Empty means the deposition does not state it, which
    is common for older entries and is not "not expressed".
    """
    hosts: list[str] = []
    plasmids: list[str] = []
    mutations: list[str] = []
    lengths: list[int] = []
    for entity in entities:
        for source in entity.get("entity_src_gen") or []:
            if (host := _host(source)) and host not in hosts:
                hosts.append(host)
            plasmid = (source.get("plasmid_name") or "").strip()
            if plasmid and plasmid not in plasmids:
                plasmids.append(plasmid)
        mutation = ((entity.get("rcsb_polymer_entity") or {}).get("pdbx_mutation") or "").strip()
        if mutation and mutation.lower() not in NO_MUTATION and mutation not in mutations:
            mutations.append(mutation)
        if length := (entity.get("entity_poly") or {}).get("rcsb_sample_sequence_length"):
            lengths.append(length)
    return {
        "expression_hosts": hosts,
        "plasmids": plasmids,
        # Engineered changes to the sequence that was crystallised, so a
        # construct that is not the wild-type protein says so.
        "mutations": mutations,
        # The longest chain, not their sum: a precursor cleaved into an alpha
        # and a beta chain (6OYY, panD) was expressed once.
        "construct_length": max(lengths) if lengths else None,
    }


def normalize(entries: Iterator[dict[str, Any]], accessions: set[str]) -> Iterator[dict[str, Any]]:
    """One row per (PDB entry, accession) pair the atlas knows about."""
    for entry in entries:
        resolution = (entry.get("rcsb_entry_info") or {}).get("resolution_combined") or []
        methods = [m["method"] for m in entry.get("exptl") or [] if m.get("method")]
        entry_components = [
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

        # One accession can own more than one polymer entity: a precursor
        # processed into alpha and beta chains (6OYY, panD) lists two, and its
        # ligand sits on the second. The entry still belongs to the accession
        # once, but with every chain the accession owns -- keeping only the
        # first entity's chains reported "no ligand" for panD bound to
        # pyrazinoic acid, which is pyrazinamide's active metabolite.
        chains_of: dict[str, list[str]] = {}
        entity_of: dict[str, dict[str, Any]] = {}
        described: dict[str, list[str]] = {}
        entities_of: dict[str, list[dict[str, Any]]] = {}
        for polymer in entry.get("polymer_entities") or []:
            identifiers = polymer.get("rcsb_polymer_entity_container_identifiers") or {}
            for reference in identifiers.get("reference_sequence_identifiers") or []:
                accession = reference.get("database_accession")
                if reference.get("database_name") != "UniProt" or accession not in accessions:
                    continue
                chains_of.setdefault(accession, []).extend(identifiers.get("auth_asym_ids") or [])
                entity_of.setdefault(accession, polymer)
                entities_of.setdefault(accession, []).append(polymer)
                description = (polymer.get("rcsb_polymer_entity") or {}).get("pdbx_description")
                if description and description not in described.setdefault(accession, []):
                    described[accession].append(description)

        for accession, entity_chains in chains_of.items():
            polymer = entity_of[accession]
            chains = sorted(set(entity_chains))
            # An entry's component list belongs to the whole entry, so in a
            # complex every subunit would otherwise claim its neighbours'
            # ligands: in 5UHB, rifampicin sits on chain C (rpoB), and rpoA,
            # rpoC, rpoZ and sigA have no business reporting it as theirs.
            # A component with no chains listed is kept rather than dropped.
            components = [
                {**c, "on_chain": not c["chains"] or bool(set(c["chains"]) & set(chains))}
                for c in entry_components
            ]
            ligands = [c for c in components if c["role"] == "ligand" and c["on_chain"]]
            elsewhere = [c for c in components if c["role"] == "ligand" and not c["on_chain"]]
            yield {
                "pdb_id": entry["rcsb_id"],
                "uniprot_acc": accession,
                "title": (entry.get("struct") or {}).get("title"),
                "method": methods[0] if methods else None,
                "resolution": resolution[0] if resolution else None,
                "released": (entry.get("rcsb_accession_info") or {}).get(
                    "initial_release_date", ""
                )[:10],
                "chains": chains,
                # Every entity the accession owns, so a row covering an alpha
                # and a beta chain is not labelled as just one of them. Sorted,
                # because RCSB does not return entities in a stable order and a
                # rebuild should not produce a diff over that.
                "entity_description": " / ".join(sorted(described.get(accession, []))) or None,
                **_construct(entities_of.get(accession, [])),
                "components": components,
                "ligand_ids": [c["comp_id"] for c in ligands],
                "n_ligands": len(ligands),
                # In the entry, but bound to another chain. Shown, not counted.
                "ligand_ids_elsewhere": [c["comp_id"] for c in elsewhere],
            }


# --- ligand identity ---------------------------------------------------------

# A PDB component is a three-character code; the keys that find the same
# molecule in ChEMBL, in the atlas's own compound table and in a drug label are
# the InChIKey and RCSB's own ChEMBL cross-reference.
CHEM_COMP_QUERY = """
query($ids: [String!]!) {
  chem_comps(comp_ids: $ids) {
    chem_comp { id name formula_weight }
    rcsb_chem_comp_descriptor { InChIKey SMILES }
    rcsb_chem_comp_related { resource_name resource_accession_code }
  }
}
"""
COMP_BATCH = 100


def normalize_chem_comps(comps: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """One row per component id, with the identifiers that leave the PDB."""
    for comp in comps:
        if not comp or not (chem := comp.get("chem_comp")):
            continue
        descriptor = comp.get("rcsb_chem_comp_descriptor") or {}
        related = {
            r["resource_name"]: r["resource_accession_code"]
            for r in comp.get("rcsb_chem_comp_related") or []
        }
        yield {
            "comp_id": chem["id"],
            "name": chem.get("name"),
            "formula_weight": chem.get("formula_weight"),
            "role": classify(chem["id"]),
            "inchikey": descriptor.get("InChIKey"),
            "smiles": descriptor.get("SMILES"),
            # RCSB's own cross-reference, where it has one: 546 of 1,486 do.
            "chembl_id": related.get("ChEMBL"),
            "pubchem_cid": related.get("PubChem"),
        }


def build_ligands(comp_ids: Sequence[str], *, retrieved_at: str) -> Any:
    """`comp_ids` are the components the structures table actually saw."""
    comps: list[dict[str, Any]] = []
    for start in range(0, len(comp_ids), COMP_BATCH):
        batch = list(comp_ids[start : start + COMP_BATCH])
        result = post_json(
            GRAPHQL, {"query": CHEM_COMP_QUERY, "variables": {"ids": batch}}, min_interval=0.3
        )
        if result.get("errors"):
            raise RuntimeError(f"RCSB GraphQL: {result['errors'][0].get('message')}")
        comps.extend(c for c in (result.get("data") or {}).get("chem_comps") or [] if c)
    return write_parquet(
        "ligands",
        normalize_chem_comps(comps),
        source=SOURCE,
        source_version=f"RCSB Data API, {len(comps)} chemical components",
        retrieved_at=retrieved_at,
    )


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
