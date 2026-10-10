"""ChEMBL target list, keyed on UniProt accession.

M0 ingests only the accession -> target mapping, which is what the ID crosswalk
needs. Bioactivity lands in M1. Licence: CC BY-SA 3.0, attribution requested;
ChEMBL asks that ChEMBL IDs be preserved and the release number displayed, which
is why `source_version` is parsed from the file rather than hardcoded.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch, fetch_json, fetch_json_many
from ..store import write_parquet

SOURCE = "chembl"
URL = "https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/latest/chembl_uniprot_mapping.txt"
API = "https://www.ebi.ac.uk/chembl/api/data"

# Whole-cell Mtb. CHEMBL360 holds the bulk (209k activities); CHEMBL2111188 is
# the H37Rv-specific target and much smaller.
WHOLE_CELL_TARGETS = ("CHEMBL360", "CHEMBL2111188")
PAGE = 1000
# `molecule_chembl_id__in` is verified to accept at least 50 ids per request.
ID_BATCH = 50

# First line is e.g. "# chembl_37 target list, 01/05/2026".
_VERSION = re.compile(r"#\s*(chembl_\S+)\s+target list,\s*(\S+)")


def fetch_raw(*, force: bool = False) -> Fetched:
    return fetch(URL, "chembl_uniprot_mapping.txt", source=SOURCE, min_interval=0.5, force=force)


def release(path: Path) -> str:
    with path.open(encoding="utf-8") as handle:
        match = _VERSION.match(handle.readline())
    return f"{match.group(1)} ({match.group(2)})" if match else "unknown"


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    """The whole table, not just Mycobacterium.

    Keeping every row (~17k) lets the crosswalk resolve both the direct Mtb
    targets and the mycobacterial orthologue targets without this ingester
    needing to know anything about the gene universe.
    """
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 4:
                continue
            accession, target_id, pref_name, target_type = parts
            yield {
                "uniprot_acc": accession,
                "chembl_target_id": target_id,
                "pref_name": pref_name,
                "target_type": target_type,
            }


def build(*, force: bool = False) -> Path:
    raw = fetch_raw(force=force)
    return write_parquet(
        "chembl_targets",
        normalize(raw.path),
        source=SOURCE,
        source_version=release(raw.path),
        retrieved_at=raw.retrieved_at,
    )


# --- bioactivity -------------------------------------------------------------

ACTIVITY_FIELDS = (
    "activity_id,molecule_chembl_id,target_chembl_id,target_organism,standard_type,"
    "standard_relation,standard_value,standard_units,pchembl_value,assay_chembl_id,"
    "assay_type,assay_description,document_chembl_id,document_year,data_validity_comment,"
    "activity_comment,potential_duplicate,canonical_smiles"
)
MOLECULE_FIELDS = (
    "molecule_chembl_id,pref_name,max_phase,molecule_type,first_approval,oral,"
    "molecule_properties,molecule_structures"
)


def _activity_url(query: str, *, offset: int = 0, limit: int = PAGE) -> str:
    return f"{API}/activity.json?{query}&only={ACTIVITY_FIELDS}&limit={limit}&offset={offset}"


def _activity_row(record: dict[str, Any], evidence: str) -> dict[str, Any]:
    def number(key: str) -> float | None:
        value = record.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "activity_id": record.get("activity_id"),
        "molecule_chembl_id": record.get("molecule_chembl_id"),
        "target_chembl_id": record.get("target_chembl_id"),
        "target_organism": record.get("target_organism"),
        "evidence": evidence,
        "standard_type": record.get("standard_type"),
        "standard_relation": record.get("standard_relation"),
        "standard_value": number("standard_value"),
        "standard_units": record.get("standard_units"),
        "pchembl_value": number("pchembl_value"),
        "assay_chembl_id": record.get("assay_chembl_id"),
        "assay_type": record.get("assay_type"),
        "assay_description": record.get("assay_description"),
        "document_chembl_id": record.get("document_chembl_id"),
        "document_year": record.get("document_year"),
        # ChEMBL's own warning that a value is suspect. Kept rather than
        # filtered, so the UI can show it instead of quietly dropping evidence.
        "data_validity_comment": record.get("data_validity_comment"),
        "potential_duplicate": bool(record.get("potential_duplicate")),
    }


def target_activities(targets: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
    """Every activity with a pChEMBL value for these (target_id, evidence) pairs."""
    evidence_of = dict(targets)
    first = fetch_json_many(
        [_activity_url(f"target_chembl_id={t}&pchembl_value__isnull=false") for t, _ in targets],
        workers=6,
        min_interval=0.1,
        label="chembl activities",
    )

    rows: list[dict[str, Any]] = []
    overflow: list[str] = []
    for url, payload in first.items():
        target_id = url.split("target_chembl_id=")[1].split("&")[0]
        rows.extend(_activity_row(a, evidence_of[target_id]) for a in payload["activities"])
        total = payload["page_meta"]["total_count"]
        overflow.extend(
            _activity_url(f"target_chembl_id={target_id}&pchembl_value__isnull=false", offset=off)
            for off in range(PAGE, total, PAGE)
        )
    if overflow:
        for url, payload in fetch_json_many(
            overflow, workers=6, min_interval=0.1, label="chembl activities (cont.)"
        ).items():
            target_id = url.split("target_chembl_id=")[1].split("&")[0]
            rows.extend(_activity_row(a, evidence_of[target_id]) for a in payload["activities"])
    return rows


def whole_cell_activities(molecule_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Whole-cell Mtb potency, pulled compound-first.

    Never target-first: CHEMBL360 alone holds 209k activities, and a whole-cell
    number only belongs on a gene page when the same compound already has
    protein-level activity against that gene.
    """
    urls = [
        _activity_url(f"target_chembl_id={target}&molecule_chembl_id__in={','.join(batch)}")
        for target in WHOLE_CELL_TARGETS
        for batch in (molecule_ids[i : i + ID_BATCH] for i in range(0, len(molecule_ids), ID_BATCH))
    ]
    rows: list[dict[str, Any]] = []
    for payload in fetch_json_many(
        urls, workers=6, min_interval=0.1, label="chembl whole-cell"
    ).values():
        rows.extend(_activity_row(a, "whole_cell") for a in payload["activities"])
    return rows


def molecules(molecule_ids: Sequence[str]) -> list[dict[str, Any]]:
    urls = [
        f"{API}/molecule.json?molecule_chembl_id__in={','.join(molecule_ids[i : i + ID_BATCH])}"
        f"&only={MOLECULE_FIELDS}&limit={ID_BATCH}"
        for i in range(0, len(molecule_ids), ID_BATCH)
    ]
    rows: list[dict[str, Any]] = []
    for payload in fetch_json_many(
        urls, workers=6, min_interval=0.1, label="chembl molecules"
    ).values():
        for molecule in payload["molecules"]:
            properties = molecule.get("molecule_properties") or {}
            structures = molecule.get("molecule_structures") or {}
            rows.append(
                {
                    "molecule_chembl_id": molecule["molecule_chembl_id"],
                    "pref_name": molecule.get("pref_name"),
                    "molecule_type": molecule.get("molecule_type"),
                    "max_phase": molecule.get("max_phase"),
                    "first_approval": molecule.get("first_approval"),
                    "smiles": structures.get("canonical_smiles"),
                    "inchi_key": structures.get("standard_inchi_key"),
                    "mw": _float(properties.get("full_mwt")),
                    "alogp": _float(properties.get("alogp")),
                    "hba": properties.get("hba"),
                    "hbd": properties.get("hbd"),
                    "psa": _float(properties.get("psa")),
                    "rotatable_bonds": properties.get("rtb"),
                    "aromatic_rings": properties.get("aromatic_rings"),
                    "ro5_violations": properties.get("num_ro5_violations"),
                    "qed": _float(properties.get("qed_weighted")),
                }
            )
    return rows


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def release_from_api() -> str:
    status = fetch_json(f"{API}/status.json")
    return f"{status['chembl_db_version']} ({status['chembl_release_date']})"


def build_bioactivity(targets: Iterable[tuple[str, str]], *, retrieved_at: str) -> list[Path]:
    """Activities and compounds for the targets the crosswalk resolved."""
    targets = sorted(set(targets))
    version = release_from_api()

    rows = target_activities(targets)
    molecule_ids = sorted({r["molecule_chembl_id"] for r in rows if r["molecule_chembl_id"]})
    rows += whole_cell_activities(molecule_ids)
    compounds = molecules(molecule_ids)

    return [
        write_parquet(
            "activities", rows, source=SOURCE, source_version=version, retrieved_at=retrieved_at
        ),
        write_parquet(
            "compounds", compounds, source=SOURCE, source_version=version, retrieved_at=retrieved_at
        ),
    ]
