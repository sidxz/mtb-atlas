"""The orthologue bridge: mycobacterial ChEMBL targets -> Mtb accessions.

Some Mtb proteins with real chemical matter have no ChEMBL target of their own;
MmpL3 (Rv0206c) is the standing example -- its inhibitors are assayed against
the *M. smegmatis* orthologue, which ChEMBL holds as CHEMBL5465372. Without a
bridge the atlas would report "no ligands" for one of the most-pursued targets
in TB drug discovery.

The bridge is built from the ChEMBL side, not the Mtb side: there are only ~28
non-Mtb mycobacterial proteins with a ChEMBL target, so this costs tens of
requests rather than one per Mtb gene.

Two traps, both verified against the live APIs and recorded in
docs/data-sources.md:

* ChEMBL names the same species inconsistently -- MmpL3's host appears as
  *Mycolicibacterium smegmatis*, which no `Mycobacterium*` name filter matches.
  Every query here keys on taxonomy or accession, never on an organism string.
* UniRef50 means 50% identity, and clusters are broad (MmpL3's holds 611
  members). So UniRef90 is tried first and the identity level that produced each
  link is recorded, for the UI to show alongside the source organism.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from .fetch import USER_AGENT, fetch_json

# Mycobacteriaceae, excluding M. tuberculosis H37Rv itself.
MYCOBACTERIACEAE = 1762
H37RV = 83332
CHEMBL_HOSTS_URL = (
    f"https://rest.uniprot.org/uniprotkb/stream?query=(taxonomy_id:{MYCOBACTERIACEAE})"
    f"+AND+(database:chembl)+NOT+(taxonomy_id:{H37RV})"
    "&format=tsv&fields=accession,organism_name,organism_id,gene_primary,xref_chembl"
)
IDENTITY_LEVELS = ("0.9", "0.5")


@dataclass(frozen=True)
class Link:
    """One Mtb accession's claim on a non-Mtb mycobacterial ChEMBL target."""

    mtb_acc: str
    chembl_target_id: str
    via_accession: str
    via_organism: str
    via_gene: str | None
    uniref_cluster: str
    identity_level: str
    cluster_size: int


def chembl_hosts() -> list[dict[str, str]]:
    """Non-Mtb mycobacterial proteins that ChEMBL holds as targets."""
    import httpx

    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        response = client.get(CHEMBL_HOSTS_URL, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(response.text), delimiter="\t"))
    return [
        {
            "uniprot_acc": r["Entry"],
            "organism": r["Organism"],
            "gene": r["Gene Names (primary)"] or None,
            "chembl_target_ids": [t for t in r["ChEMBL"].split(";") if t],
        }
        for r in rows
        if r["ChEMBL"].strip()
    ]


def _cluster(accession: str, identity: str) -> tuple[str, set[str], int] | None:
    """The UniRef cluster for `accession` at `identity`, with its members."""
    found = fetch_json(
        f"https://rest.uniprot.org/uniref/search?query=uniprot_id:{accession}"
        f"+AND+identity:{identity}&format=json&fields=id"
    )
    results = found.get("results") or []
    if not results:
        return None
    cluster_id = results[0]["id"]
    detail = fetch_json(f"https://rest.uniprot.org/uniref/{cluster_id}?format=json")
    members = set(detail["representativeMember"].get("accessions") or [])
    for member in detail.get("members") or []:
        # Some member records carry no accession list at all; skip rather than fail.
        members.update(member.get("accessions") or [])
    return cluster_id, members, detail.get("memberCount", len(members))


def build_links(mtb_accessions: set[str]) -> list[Link]:
    """Resolve every mycobacterial ChEMBL target onto Mtb accessions we know."""
    links: list[Link] = []
    for host in chembl_hosts():
        for identity in IDENTITY_LEVELS:
            cluster = _cluster(host["uniprot_acc"], identity)
            if cluster is None:
                continue
            cluster_id, members, size = cluster
            hits = sorted(members & mtb_accessions)
            if not hits:
                continue
            links.extend(
                Link(
                    mtb_acc=hit,
                    chembl_target_id=target_id,
                    via_accession=host["uniprot_acc"],
                    via_organism=host["organism"],
                    via_gene=host["gene"],
                    uniref_cluster=cluster_id,
                    identity_level=identity,
                    cluster_size=size,
                )
                for hit in hits
                for target_id in host["chembl_target_ids"]
            )
            break  # Tightest identity level that produced a hit wins.
    return links
