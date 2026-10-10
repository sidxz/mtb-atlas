"""The read API. It touches the normalized store and nothing else.

No ingester is imported here and no upstream service is called at request time:
if a source is down, the API still answers from the last build, and every
answer can name the release it came from.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .store import STORE, provenance
from .summary import counts

# Licences differ per source and the UI shows them, so they live beside the
# versions rather than in a footnote.
LICENCES = {
    "genes": ("Mycobrowser", "none stated (citation requested)"),
    "proteins": ("UniProt", "CC BY 4.0"),
    "chembl_targets": ("ChEMBL", "CC BY-SA 3.0"),
    "activities": ("ChEMBL", "CC BY-SA 3.0"),
    "compounds": ("ChEMBL", "CC BY-SA 3.0"),
    "structures": ("RCSB PDB", "CC0 1.0"),
    "predicted_structures": ("AlphaFold DB", "CC BY 4.0"),
    "essentiality": ("DeJesus 2017, mBio", "CC BY 4.0"),
    "resistance": ("WHO catalogue 2nd ed.", "ODC-By 1.0"),
}

SORTABLE = {
    "rv_id",
    "gene_name",
    "start",
    "n_pdb",
    "n_activities",
    "best_pchembl",
    "best_whole_cell_pchembl",
    "n_variants_associated",
    "plddt_mean",
    "length",
    "n_compounds",
    "n_whole_cell",
    "best_resolution",
}

app = FastAPI(
    title="Mtb Target Atlas",
    version="0.1.0",
    summary="Public-data target evidence for every M. tuberculosis H37Rv gene.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def _db() -> duckdb.DuckDBPyConnection:
    """A fresh connection per request; DuckDB reads Parquet straight off disk."""
    connection = duckdb.connect()
    for name in (*LICENCES, "crosswalk", "target_summary"):
        path = STORE / f"{name}.parquet"
        if path.exists():
            connection.sql(f"CREATE VIEW {name} AS SELECT * FROM '{path}'")
    return connection


# --- models ------------------------------------------------------------------


class Source(BaseModel):
    name: str
    version: str
    licence: str
    retrieved: str


class Meta(BaseModel):
    counts: dict[str, int]
    sources: list[Source]
    caveats: list[str]


class TargetSummary(BaseModel):
    rv_id: str
    gene_name: str | None = None
    product: str | None = None
    category: str | None = None
    start: int
    stop: int
    strand: str
    length: int | None = None
    uniprot_acc: str | None = None
    essentiality: str | None = None
    essentiality_label: str | None = None
    feature: str = "CDS"
    essentiality_essential: bool = False
    essentiality_fitness_cost: bool = False
    essentiality_condition: str | None = None
    ta_sites: int | None = None
    n_pdb: int = 0
    best_resolution: float | None = None
    has_predicted: bool = False
    plddt_mean: float | None = None
    n_activities: int = 0
    n_compounds: int = 0
    best_pchembl: float | None = None
    n_whole_cell: int = 0
    best_whole_cell_pchembl: float | None = None
    chembl_evidence: str | None = None
    in_who_catalogue: bool = False
    n_variants_associated: int = 0
    n_variants_mappable: int = 0
    resistance_drugs: list[str] = Field(default_factory=list)
    has_structure: bool = False
    has_ligands: bool = False
    structural_gap: bool = False
    conflict: bool = False


class TargetPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TargetSummary]


class TargetDetail(TargetSummary):
    """The full evidence record: everything the atlas knows about one gene."""

    protein_name: str | None = None
    acc_status: str | None = None
    shares_accession_with: list[str] = Field(default_factory=list)
    is_pseudogene: bool = False
    alphafold: dict[str, Any] | None = None
    structures: list[dict[str, Any]] = Field(default_factory=list)
    chembl_targets: list[dict[str, Any]] = Field(default_factory=list)
    activities: list[dict[str, Any]] = Field(default_factory=list)
    whole_cell: list[dict[str, Any]] = Field(default_factory=list)
    compounds: list[dict[str, Any]] = Field(default_factory=list)
    variants: list[dict[str, Any]] = Field(default_factory=list)
    absences: list[str] = Field(default_factory=list)


# --- endpoints ---------------------------------------------------------------


@app.get("/meta", response_model=Meta)
def meta() -> Meta:
    sources = []
    for name, (label, licence) in LICENCES.items():
        try:
            version, retrieved = provenance(name)
        except (duckdb.IOException, duckdb.CatalogException):
            continue
        sources.append(
            Source(name=label, version=str(version), licence=licence, retrieved=str(retrieved))
        )
    return Meta(
        counts=counts(),
        sources=sources,
        caveats=[
            "Essentiality is one in vitro condition (7H9 broth, DeJesus 2017). "
            "A gene essential there may not be essential in infection.",
            "The WHO catalogue covers 65 genes with matched phenotypic testing. "
            "Every other gene has no resistance record, which is an absence of "
            "evidence rather than evidence of absence.",
            "Orthologue chemical matter is a family-level link through a UniRef "
            "cluster, not evidence of a shared binding site.",
            "Whole-cell potency is attached to a gene only through a compound "
            "that already has protein-level activity on it.",
            "No druggability or pocket call is made: no public source provides one.",
        ],
    )


@app.get("/targets", response_model=TargetPage)
def targets(
    q: Annotated[str | None, Query(description="Rv tag, gene name, product or accession")] = None,
    essentiality: Annotated[list[str] | None, Query()] = None,
    category: Annotated[list[str] | None, Query()] = None,
    has_structure: bool | None = None,
    has_predicted: bool | None = None,
    has_ligands: bool | None = None,
    in_who_catalogue: bool | None = None,
    structural_gap: Annotated[
        bool | None, Query(description="Essential, has a structure, has no ligands")
    ] = None,
    conflict: bool | None = None,
    min_pchembl: float | None = None,
    sort: str = "start",
    order: Literal["asc", "desc"] = "asc",
    limit: Annotated[int, Query(ge=1, le=5000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TargetPage:
    if sort not in SORTABLE:
        raise HTTPException(400, f"sort must be one of {sorted(SORTABLE)}")

    where: list[str] = []
    params: list[Any] = []
    if q:
        where.append(
            "(lower(rv_id) LIKE ? OR lower(coalesce(gene_name, '')) LIKE ?"
            " OR lower(coalesce(product, '')) LIKE ?"
            " OR lower(coalesce(uniprot_acc, '')) LIKE ?)"
        )
        params += [f"%{q.lower()}%"] * 4
    if essentiality:
        where.append(f"essentiality IN ({','.join('?' * len(essentiality))})")
        params += essentiality
    if category:
        where.append(f"category IN ({','.join('?' * len(category))})")
        params += category
    for column, value in (
        ("has_structure", has_structure),
        ("has_predicted", has_predicted),
        ("has_ligands", has_ligands),
        ("in_who_catalogue", in_who_catalogue),
        ("structural_gap", structural_gap),
        ("conflict", conflict),
    ):
        if value is not None:
            where.append(f"{column} = ?")
            params.append(value)
    if min_pchembl is not None:
        where.append("best_pchembl >= ?")
        params.append(min_pchembl)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    connection = _db()
    total = connection.execute(f"SELECT count(*) FROM target_summary {clause}", params).fetchone()[
        0
    ]
    # NULLS LAST so "best potency first" does not open with the unmeasured genes.
    rows = connection.execute(
        f"SELECT * FROM target_summary {clause} ORDER BY {sort} {order.upper()} NULLS LAST,"
        f" rv_id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    items = [dict(zip([c[0] for c in rows.description], r, strict=True)) for r in rows.fetchall()]
    return TargetPage(
        total=total, limit=limit, offset=offset, items=[TargetSummary(**i) for i in items]
    )


@app.get("/targets/{rv_id}", response_model=TargetDetail)
def target(rv_id: str) -> TargetDetail:
    connection = _db()
    summary = _query(connection, "SELECT * FROM target_summary WHERE rv_id = ?", [rv_id])
    if not summary:
        raise HTTPException(404, f"no gene {rv_id} in the atlas")
    record = summary[0]
    accession = record.get("uniprot_acc")
    gene_key = record.get("gene_name") or rv_id

    # Everything scalar already comes from target_summary; the crosswalk is
    # read only for the nested ChEMBL target structs it alone carries.
    walk = _query(connection, "SELECT chembl_targets FROM crosswalk WHERE rv_id = ?", [rv_id])
    chembl_targets = list(walk[0]["chembl_targets"] or []) if walk else []

    structures = _query(
        connection,
        "SELECT pdb_id, title, method, resolution, released, chains, entity_description,"
        " components, ligand_ids, n_ligands FROM structures WHERE uniprot_acc = ?"
        " ORDER BY n_ligands DESC, resolution NULLS LAST",
        [accession],
    )
    predicted = _query(
        connection, "SELECT * FROM predicted_structures WHERE uniprot_acc = ?", [accession]
    )
    target_ids = [t["target_id"] for t in chembl_targets]
    activities = (
        _query(
            connection,
            "SELECT * FROM activities WHERE evidence <> 'whole_cell'"
            f" AND target_chembl_id IN ({','.join('?' * len(target_ids))})"
            " ORDER BY pchembl_value DESC NULLS LAST LIMIT 500",
            target_ids,
        )
        if target_ids
        else []
    )
    molecules = sorted({a["molecule_chembl_id"] for a in activities if a["molecule_chembl_id"]})
    whole_cell = (
        _query(
            connection,
            "SELECT * FROM activities WHERE evidence = 'whole_cell'"
            f" AND molecule_chembl_id IN ({','.join('?' * len(molecules))})"
            " ORDER BY pchembl_value DESC NULLS LAST LIMIT 500",
            molecules,
        )
        if molecules
        else []
    )
    compounds = (
        _query(
            connection,
            "SELECT * FROM compounds WHERE molecule_chembl_id IN "
            f"({','.join('?' * len(molecules))})",
            molecules,
        )
        if molecules
        else []
    )
    variants = _query(
        connection,
        "SELECT * FROM resistance WHERE gene = ? AND associated"
        " ORDER BY grading, residue_position NULLS LAST",
        [gene_key],
    )

    absences = []
    if not structures:
        absences.append("No experimental structure in the PDB for this accession.")
    if not activities:
        absences.append("No ChEMBL activity: no compound in ChEMBL is recorded against this gene.")
    if not variants:
        absences.append(
            "Not in the WHO catalogue, which covers only the 65 genes with matched "
            "phenotypic drug-susceptibility testing."
        )
    absences.append("No druggability or pocket call: no public source provides one.")

    return TargetDetail(
        **record,
        alphafold=predicted[0] if predicted else None,
        structures=structures,
        chembl_targets=chembl_targets,
        activities=activities,
        whole_cell=whole_cell,
        compounds=compounds,
        variants=variants,
        absences=absences,
    )


@app.get("/compounds/{molecule_chembl_id}")
def compound(molecule_chembl_id: str) -> dict[str, Any]:
    connection = _db()
    rows = _query(
        connection, "SELECT * FROM compounds WHERE molecule_chembl_id = ?", [molecule_chembl_id]
    )
    if not rows:
        raise HTTPException(404, f"no compound {molecule_chembl_id} in the atlas")
    activities = _query(
        connection,
        "SELECT * FROM activities WHERE molecule_chembl_id = ?"
        " ORDER BY pchembl_value DESC NULLS LAST",
        [molecule_chembl_id],
    )
    return {**rows[0], "activities": activities}


def _query(
    connection: duckdb.DuckDBPyConnection, sql: str, params: list[Any]
) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, params)
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
