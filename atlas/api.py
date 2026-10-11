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

from .clinical import TARGET_LINK_SQL, TARGET_LINKS
from .store import STORE, built, provenance
from .summary import EMPTY_CLINICAL, counts

# Licences differ per source and the UI shows them, so they live beside the
# versions rather than in a footnote.
LICENCES = {
    "genes": ("Mycobrowser", "none stated (citation requested)"),
    "proteins": ("UniProt", "CC BY 4.0"),
    "chembl_targets": ("ChEMBL", "CC BY-SA 3.0"),
    "activities": ("ChEMBL", "CC BY-SA 3.0"),
    "compounds": ("ChEMBL", "CC BY-SA 3.0"),
    "structures": ("RCSB PDB", "CC0 1.0"),
    "orthologue_structures": ("phmmer vs Mycobacteriaceae + RCSB PDB", "CC BY 4.0 / CC0 1.0"),
    "predicted_structures": ("AlphaFold DB", "CC BY 4.0"),
    "essentiality": ("DeJesus 2017, mBio", "CC BY 4.0"),
    "resistance": ("WHO catalogue 2nd ed.", "ODC-By 1.0"),
    "vulnerability": ("Bosch 2021, Cell (CRISPRi)", "CC BY 4.0"),
    "interactions": ("STRING v12.5", "CC BY 4.0"),
    "homology": ("phmmer vs reviewed human proteome", "CC BY 4.0"),
    "conditional_fitness": ("Griffin 2011, PLoS Pathog (cholesterol TnSeq)", "CC BY 4.0"),
    "conditional_tnseq": ("MtbTnDB / Jinich 2025, Mol Microbiol (TRANSIT output)", "CC BY 4.0"),
    "tnseq_screens": ("MtbTnDB screen annotation, Jinich 2025", "CC BY 4.0"),
    "ligands": ("RCSB PDB chemical components", "CC0 1.0"),
    "drugs": ("ChEMBL drug indications and mechanisms", "CC BY-SA 3.0"),
    # The terms ask for attribution, the processing date (carried in the
    # version) and a statement of modifications (docs/data-sources.md).
    "trials": ("ClinicalTrials.gov", "US Government database; attribution required"),
}
# Store tables with no licence of their own: joins, and a second table from a
# source already listed above.
DERIVED = ("crosswalk", "target_summary", "drug_mechanisms", "drug_genes", "trial_drugs")
# Read off the gene's UniProt entry for the target page.
PROTEIN_FIELDS = (
    "reviewed",
    "interpro_ids",
    "pfam_ids",
    "go_ids",
    "ec_numbers",
    "function",
    "subcellular_location",
    "locations",
    "signal_peptide",
    "pathways",
    "reactions",
    "rhea_ids",
    "cofactors",
    "go_process",
    "go_function",
    "go_component",
    "disruption_phenotype",
    "pubmed_ids",
    "protein_existence",
    "annotation_score",
)

SORTABLE = {
    "rv_id",
    "gene_name",
    "start",
    "n_pdb",
    "n_activities",
    "best_pchembl",
    "best_whole_cell_pchembl",
    "n_variants_associated",
    "vulnerability_index",
    "n_partners",
    "human_homolog_identity",
    "n_close_paralogs",
    "closest_paralog_identity",
    "plddt_mean",
    "length",
    "n_compounds",
    "n_whole_cell",
    "best_pmic",
    "median_pmic",
    "n_mic",
    "n_protein_assays",
    "max_assay_compounds",
    "best_resolution",
    "n_orthologue_pdb",
    "closest_orthologue_identity",
    "cholesterol_log2_ratio",
    "hn878_vulnerability_index",
    "hn878_delta_vi",
    "best_drug_phase",
    "n_drugs",
    "n_trials",
    "n_transmembrane",
    "n_references",
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
    for name in (*LICENCES, *DERIVED):
        path = STORE / f"{name}.parquet"
        if path.exists():
            connection.sql(f"CREATE VIEW {name} AS SELECT * FROM '{path}'")
        elif name in EMPTY_CLINICAL:
            # An empty stand-in, so a store without the clinical layer answers
            # rather than failing. Without it DuckDB falls back to a
            # replacement scan and binds the route function of the same name.
            connection.sql(f"CREATE VIEW {name} AS {EMPTY_CLINICAL[name]}")
    return connection


def _like(term: str) -> str:
    r"""A search term as a LIKE pattern, with the wildcards taken literally.

    Typing `%` means the character, not "match everything"; without this, `_`
    returned an arbitrary handful of rows where no match is the truth.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _require_clinical() -> None:
    """Routes that are only about drugs and trials have no honest empty answer."""
    if not built("drug_genes"):
        raise HTTPException(
            503, "The clinical layer is not built in this store. Run `atlas clinical`."
        )


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
    # Griffin 2011. None where the locus was never screened; `measured` is
    # False where it was and took no insertions to compare.
    cholesterol_measured: bool | None = None
    cholesterol_log2_ratio: float | None = None
    cholesterol_p: float | None = None
    cholesterol_required: bool | None = None
    required_in_vivo: bool | None = None
    n_pdb: int = 0
    best_resolution: float | None = None
    # A structure to work from that is not of this protein, counted apart from
    # `n_pdb` so a zero there keeps meaning "none of its own".
    # `same_sequence_structure` is the stronger claim: an identical sequence
    # deposited under another accession, which the atlas missed only because
    # `structures` is keyed on the Mtb one.
    n_orthologue_pdb: int = 0
    n_orthologue_pdb_with_ligand: int = 0
    best_orthologue_resolution: float | None = None
    closest_orthologue_gene: str | None = None
    closest_orthologue_organism: str | None = None
    closest_orthologue_identity: float | None = None
    closest_orthologue_coverage: float | None = None
    same_sequence_structure: bool = False
    has_predicted: bool = False
    plddt_mean: float | None = None
    n_activities: int = 0
    n_compounds: int = 0
    best_pchembl: float | None = None
    n_whole_cell: int = 0
    # ChEMBL's own pchembl_value, which it computes for affinity endpoints only
    # and so is NULL on every MIC. Kept because a whole-cell IC50 is a real
    # measurement, but it is not the MIC and covers 12 genes to best_pmic's 71.
    best_whole_cell_pchembl: float | None = None
    # -log10(MIC in mol/L), converted in the ingester from the value and units
    # ChEMBL reports. Censored ('>') MICs are excluded and counted separately.
    best_pmic: float | None = None
    median_pmic: float | None = None
    n_mic: int = 0
    n_mic_censored: int = 0
    n_resistant_panel: int = 0
    whole_cell_conditions: list[dict[str, Any]] = Field(default_factory=list)
    # Whether a way to measure this protein has been published, which is not
    # the same question as whether anyone has hit it. Distinct ChEMBL assays on
    # the Mtb protein itself; orthologue and whole-cell assays are excluded.
    n_protein_assays: int = 0
    # The largest single published assay by distinct compounds: one campaign
    # versus a dozen follow-ups are opposite answers to "can this be screened".
    max_assay_compounds: int = 0
    latest_protein_assay_year: int | None = None
    protein_assay_example: str | None = None
    chembl_evidence: str | None = None
    in_who_catalogue: bool = False
    n_variants_associated: int = 0
    n_variants_mappable: int = 0
    resistance_drugs: list[str] = Field(default_factory=list)
    # CRISPRi knockdown. More negative is more vulnerable; `certain` is the
    # authors' own flag and is true for only ~600 genes.
    vulnerability_index: float | None = None
    vi_lower: float | None = None
    vi_upper: float | None = None
    vulnerability_certain: bool = False
    crispr_essential: bool = False
    # The same series in HN878, a clinical isolate. `hn878_delta_vi` runs HN878
    # minus H37Rv, so positive means less vulnerable in the clinical strain, and
    # it is NULL for the genes the authors reported no difference for.
    hn878_vulnerability_index: float | None = None
    hn878_vi_certain: bool | None = None
    hn878_delta_vi: float | None = None
    hn878_delta_vi_norm: float | None = None
    hn878_differential_reported: bool = False
    antibacterial: str | None = None
    human_homolog: bool = False
    close_human_homolog: bool = False
    human_homolog_gene: str | None = None
    human_homolog_acc: str | None = None
    human_homolog_identity: float | None = None
    human_homolog_evalue: float | None = None

    # Functional redundancy. `close_paralog` is stricter than
    # `close_human_homolog`: a backup copy must be the same protein, not merely
    # share a domain, so it requires coverage as well as identity.
    has_paralog: bool = False
    n_paralogs: int = 0
    close_paralog: bool = False
    n_close_paralogs: int = 0
    closest_paralog_gene: str | None = None
    closest_paralog_identity: float | None = None
    # The nearest relative even when it is not a backup, so a family-level link
    # does not read as "no paralog at all".
    nearest_relative_gene: str | None = None
    nearest_relative_identity: float | None = None
    nearest_relative_coverage: float | None = None
    n_partners: int = 0
    top_partner_score: int | None = None
    has_structure: bool = False
    has_ligands: bool = False
    structural_gap: bool = False
    conflict: bool = False
    # Drugs said to act on this gene's own protein (ChEMBL mechanism or Bosch
    # 2021), their best phase *for TB*, and the trials testing them.
    # None where the clinical layer has not been built; [] means none found.
    drug_names: list[str] | None = None
    # From the UniProt entry; None where there is no protein (RNA genes).
    n_transmembrane: int | None = None
    n_references: int | None = None
    # None, not 0, where the clinical stage has not run in this store.
    n_drugs: int | None = None
    best_drug_phase: float | None = None
    n_complex_drugs: int | None = None
    n_trials: int | None = None
    has_clinical_drug: bool | None = None


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
    orthologue_structures: list[dict[str, Any]] = Field(default_factory=list)
    chembl_targets: list[dict[str, Any]] = Field(default_factory=list)
    activities: list[dict[str, Any]] = Field(default_factory=list)
    whole_cell: list[dict[str, Any]] = Field(default_factory=list)
    compounds: list[dict[str, Any]] = Field(default_factory=list)
    variants: list[dict[str, Any]] = Field(default_factory=list)
    partners: list[dict[str, Any]] = Field(default_factory=list)
    interpro_ids: list[str] = Field(default_factory=list)
    pfam_ids: list[str] = Field(default_factory=list)
    go_ids: list[str] = Field(default_factory=list)
    ec_numbers: list[str] = Field(default_factory=list)
    # UniProt's biology: curated in a reviewed (Swiss-Prot) entry, automatic in an
    # unreviewed one. None or empty means UniProt says nothing.
    reviewed: bool | None = None
    function: str | None = None
    subcellular_location: str | None = None
    locations: list[str] = Field(default_factory=list)
    signal_peptide: bool | None = None
    pathways: list[str] = Field(default_factory=list)
    reactions: list[str] = Field(default_factory=list)
    rhea_ids: list[str] = Field(default_factory=list)
    cofactors: list[str] = Field(default_factory=list)
    go_process: list[str] = Field(default_factory=list)
    go_function: list[str] = Field(default_factory=list)
    go_component: list[str] = Field(default_factory=list)
    disruption_phenotype: str | None = None
    pubmed_ids: list[str] = Field(default_factory=list)
    protein_existence: str | None = None
    annotation_score: float | None = None
    bound_ligands: list[dict[str, Any]] = Field(default_factory=list)
    drugs: list[dict[str, Any]] = Field(default_factory=list)
    trials: list[dict[str, Any]] = Field(default_factory=list)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    interactions: list[dict[str, Any]] = Field(default_factory=list)
    tnseq_coverage: dict[str, int] = Field(default_factory=dict)
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
            "A gene essential there may not be essential in infection. Griffin 2011 "
            "adds one more condition -- growth on cholesterol -- but a transposon "
            "screen cannot measure a gene that tolerates no insertions, so every "
            "in-vitro-essential gene comes back unmeasured there rather than unaffected.",
            "The WHO catalogue covers 65 genes with matched phenotypic testing. "
            "Every other gene has no resistance record, which is an absence of "
            "evidence rather than evidence of absence.",
            "Orthologue chemical matter is a family-level link through a UniRef "
            "cluster, not evidence of a shared binding site.",
            "Whole-cell potency is attached to a gene only through a compound "
            "that already has protein-level activity on it.",
            "No druggability or pocket call is made: no public source provides one.",
            "CRISPRi vulnerability is on a negative scale; more negative is more "
            "vulnerable. Only ~600 genes carry the study's own `certain` flag.",
            "Human homology is computed here with phmmer against the reviewed human "
            "proteome, reported as E-value and percent identity. The 30% 'close' "
            "threshold is this atlas's line, not a fact of biology.",
            "Drugs are ChEMBL molecules with a tuberculosis indication, unedited: the set "
            "includes host-directed adjuncts, HIV co-medications and placebo excipients. "
            "The phase shown is the highest phase for TB, not for any indication.",
            "A drug counts on a gene only when ChEMBL's mechanism or Bosch 2021 names that "
            "gene's protein. Membership of a target complex and WHO-graded resistance are "
            "shown but not counted: resistance is not target engagement.",
            "Trials are ClinicalTrials.gov interventional studies for the condition "
            "'tuberculosis'. A trial links to a drug through ChEMBL's own trial reference "
            "or an exact match of an intervention name; an unlinked trial may still have "
            "tested one.",
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
    cholesterol_required: Annotated[
        bool | None, Query(description="Griffin 2011's own call: required on cholesterol")
    ] = None,
    required_in_vivo: bool | None = None,
    structural_gap: Annotated[
        bool | None, Query(description="Essential, has a structure, has no ligands")
    ] = None,
    conflict: bool | None = None,
    crispr_essential: bool | None = None,
    vulnerability_certain: bool | None = None,
    human_homolog: Annotated[
        bool | None, Query(description="Has any human homolog at E <= 1e-5")
    ] = None,
    close_human_homolog: Annotated[
        bool | None, Query(description="Human homolog at >= 30% identity")
    ] = None,
    has_clinical_drug: Annotated[
        bool | None, Query(description="A drug with a TB indication acts on this gene")
    ] = None,
    min_drug_phase: Annotated[float | None, Query(description="Best phase for TB")] = None,
    min_pchembl: float | None = None,
    max_vulnerability_index: Annotated[
        float | None, Query(description="More negative is more vulnerable")
    ] = None,
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
            "(lower(rv_id) LIKE ? ESCAPE '\\' OR lower(coalesce(gene_name, '')) LIKE ? ESCAPE '\\'"
            " OR lower(coalesce(product, '')) LIKE ? ESCAPE '\\'"
            " OR lower(coalesce(uniprot_acc, '')) LIKE ? ESCAPE '\\')"
        )
        params += [_like(q.lower())] * 4
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
        ("crispr_essential", crispr_essential),
        ("vulnerability_certain", vulnerability_certain),
        ("human_homolog", human_homolog),
        ("close_human_homolog", close_human_homolog),
        ("has_clinical_drug", has_clinical_drug),
        ("cholesterol_required", cholesterol_required),
        ("required_in_vivo", required_in_vivo),
    ):
        if value is not None:
            where.append(f"{column} = ?")
            params.append(value)
    if min_pchembl is not None:
        where.append("best_pchembl >= ?")
        params.append(min_pchembl)
    if max_vulnerability_index is not None:
        where.append("vulnerability_index <= ?")
        params.append(max_vulnerability_index)
    if min_drug_phase is not None:
        where.append("best_drug_phase >= ?")
        params.append(min_drug_phase)

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
        " components, ligand_ids, n_ligands, ligand_ids_elsewhere,"
        # How the protein was made, which the entry states and nothing else does.
        " expression_hosts, plasmids, mutations, construct_length"
        " FROM structures WHERE uniprot_acc = ?"
        " ORDER BY n_ligands DESC, resolution NULLS LAST",
        [accession],
    )
    # Borrowed structures, best first by how similar the protein is and then by
    # whether it was solved with something bound -- the two things that decide
    # whether it is worth opening.
    orthologue_structures = _query(
        connection,
        "SELECT via_acc, via_gene, via_organism, via_taxon, relation, identity, coverage,"
        " evalue, bitscore, pdb_id, title, method, resolution, released,"
        " entity_description, n_ligands, ligand_ids"
        " FROM orthologue_structures WHERE uniprot_acc = ?"
        " ORDER BY identity DESC, n_ligands DESC, resolution NULLS LAST LIMIT 200",
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
    partners = _query(
        connection,
        "SELECT partner_rv_id AS rv_id, partner_name AS gene_name, combined_score,"
        " experimental, database, textmining, coexpression"
        " FROM interactions WHERE rv_id = ?"
        " UNION ALL"
        " SELECT rv_id, rv_name AS gene_name, combined_score,"
        " experimental, database, textmining, coexpression"
        " FROM interactions WHERE partner_rv_id = ?"
        " ORDER BY combined_score DESC LIMIT 40",
        [rv_id, rv_id],
    )
    annotations = _query(
        connection,
        f"SELECT {', '.join(PROTEIN_FIELDS)} FROM proteins WHERE uniprot_acc = ?",
        [accession],
    )
    annotation = annotations[0] if annotations else {}
    clinical = built("drug_genes")
    drugs = (
        _query(
            connection,
            "SELECT g.link, g.target_chembl_id, g.target_name, g.n_target_accessions,"
            " g.target_type,"
            " g.shared_accession, g.source_text, g.n_variants, d.molecule_chembl_id, d.pref_name,"
            # The gene page draws these too, so it needs the SMILES.
            " d.smiles,"
            " d.max_phase_tb, d.max_phase, d.first_approval, d.molecule_type"
            " FROM drug_genes g JOIN drugs d USING (molecule_chembl_id) WHERE g.rv_id = ?"
            " ORDER BY d.max_phase_tb DESC NULLS LAST, d.pref_name, g.link",
            [rv_id],
        )
        if clinical
        else []
    )
    trials = (
        _query(
            connection,
            "SELECT t.nct_id, any_value(t.brief_title) AS brief_title,"
            " any_value(t.phases) AS phases,"
            " any_value(t.phase_max) AS phase_max, any_value(t.status) AS status,"
            " any_value(t.start_date) AS start_date, any_value(t.lead_sponsor) AS lead_sponsor,"
            " any_value(t.has_results) AS has_results,"
            " list_sort(list_distinct(list(d.pref_name))) AS drugs"
            " FROM drug_genes g JOIN trial_drugs td USING (molecule_chembl_id)"
            " JOIN trials t USING (nct_id)"
            " JOIN drugs d ON d.molecule_chembl_id = g.molecule_chembl_id"
            f" WHERE g.rv_id = ? AND g.link IN ({TARGET_LINK_SQL})"
            " GROUP BY t.nct_id ORDER BY start_date DESC NULLS LAST",
            [rv_id],
        )
        if clinical
        else []
    )

    # What is actually bound in this protein's own chains, named, and tied back
    # to the compound and the drug where the same molecule is one.
    bound_ligands = _query(
        connection,
        "WITH bound AS ("
        "  SELECT DISTINCT unnest(ligand_ids) AS comp_id FROM structures WHERE uniprot_acc = ?)"
        " SELECT b.comp_id, l.name, l.formula_weight, l.inchikey, l.smiles,"
        "   coalesce(l.chembl_id, c.molecule_chembl_id) AS molecule_chembl_id,"
        "   d.pref_name AS drug_name, d.max_phase_tb,"
        "   (SELECT max(a.pchembl_value) FROM activities a"
        "     WHERE a.molecule_chembl_id = coalesce(l.chembl_id, c.molecule_chembl_id)"
        "       AND a.evidence <> 'whole_cell') AS best_pchembl"
        " FROM bound b"
        " LEFT JOIN ligands l USING (comp_id)"
        " LEFT JOIN compounds c ON c.molecule_chembl_id = l.chembl_id OR c.inchi_key = l.inchikey"
        " LEFT JOIN drugs d ON d.molecule_chembl_id = l.chembl_id OR d.inchi_key = l.inchikey"
        " ORDER BY d.max_phase_tb DESC NULLS LAST, best_pchembl DESC NULLS LAST, b.comp_id",
        [accession],
    )

    # Conditional TnSeq. Only annotated screens: an unannotated screen's
    # condition is NOT RECORDED, and a row saying nothing about what was tested
    # is not evidence. Interaction backgrounds come back separately because a
    # hit in one is an interaction with that gene, not a conditional
    # requirement -- mmpL3 in marP_KO is the case that taught us.
    SCREENS = (
        " FROM conditional_tnseq t JOIN tnseq_screens s USING (screen_id)"
        " WHERE t.rv_id = ? AND s.annotated"
        "   AND (s.interaction_gene IS NOT NULL OR s.interaction_gene_name IS NOT NULL) = ?"
    )
    COLUMNS = (
        "SELECT s.screen_id, s.condition_class, s.description, s.study, s.cross_study,"
        " s.stress, s.carbon_source, s.medium, s.mouse_strain, s.mtb_strain,"
        " coalesce(s.interaction_gene_name, s.interaction_gene) AS interaction,"
        " t.log2fc, t.q_value, t.measured, t.n_ta_sites, t.sum_control, t.sum_experimental"
    )
    ORDER = " ORDER BY t.q_value, abs(t.log2fc) DESC"
    # q < 0.05 is this atlas's cut, not the authors', so the UI prints it.
    screened = built("conditional_tnseq") and built("tnseq_screens")
    SIGNIFICANT = COLUMNS + SCREENS + " AND t.measured AND t.q_value < 0.05" + ORDER
    conditions = _query(connection, SIGNIFICANT, [rv_id, False]) if screened else []
    interactions = _query(connection, SIGNIFICANT, [rv_id, True]) if screened else []
    # The denominator, so "two hits" can be read against what was testable.
    coverage = (
        _query(
            connection,
            "SELECT count(*) FILTER (WHERE t.measured) AS measured,"
            " count(*) FILTER (WHERE NOT t.measured) AS unmeasured"
            " FROM conditional_tnseq t JOIN tnseq_screens s USING (screen_id)"
            " WHERE t.rv_id = ? AND s.annotated"
            "   AND s.interaction_gene IS NULL AND s.interaction_gene_name IS NULL",
            [rv_id],
        )
        if screened
        else []
    )
    tnseq = dict(coverage[0]) if coverage else {"measured": 0, "unmeasured": 0}

    absences = []
    if not structures and not orthologue_structures:
        absences.append("No experimental structure in the PDB for this accession.")
    elif not structures:
        # The absence is real and stays, but on its own it reads as "nothing to
        # work from", which is the misreading this column exists to correct.
        best = orthologue_structures[0]
        same = best["relation"] == "same_sequence"
        claim = (
            "an identical sequence is deposited under"
            if same
            else f"a {best['identity']:.0%}-identical relative is deposited under"
        )
        absences.append(
            f"No experimental structure under this accession, but {claim} "
            f"{best['via_acc']} ({best['via_organism']}): "
            f"{len({row['pdb_id'] for row in orthologue_structures})} entries."
            + ("" if same else " What that is good for is a judgement, not a fact.")
        )
    if not activities:
        absences.append("No ChEMBL activity: no compound in ChEMBL is recorded against this gene.")
    if not record.get("n_protein_assays"):
        absences.append(
            "No published assay against this protein in ChEMBL, so screening it means "
            "developing the assay first. Orthologue and whole-cell measurements, where "
            "they exist, do not supply one."
        )
    if not variants:
        absences.append(
            "Not in the WHO catalogue, which covers only the 65 genes with matched "
            "phenotypic drug-susceptibility testing."
        )
    if not tnseq["measured"] and tnseq["unmeasured"]:
        absences.append(
            f"Took no transposon insertions in any of the {tnseq['unmeasured']} conditional "
            "TnSeq screens that cover it, so none of them could measure it. That is the "
            "expected result for an essential gene, and it is not 'no effect'."
        )
    elif not conditions and tnseq["measured"]:
        n = tnseq["measured"]
        absences.append(
            f"Measurable in {n} conditional TnSeq screen{'s' if n > 1 else ''} and "
            f"significant in none of them (q < 0.05), so no condition tested here changes "
            "this gene's fitness."
        )
    if record.get("vulnerability_index") is None:
        absences.append("No CRISPRi vulnerability measurement for this gene.")
    elif not record.get("vulnerability_certain"):
        absences.append(
            "A vulnerability index exists but did not meet the study's own criteria "
            "for a confident estimate, so treat it as indicative only."
        )
    if record.get("hn878_vulnerability_index") is None:
        absences.append(
            "Not measured in HN878, so this gene's vulnerability is known only in the "
            "lab strain. Whether it holds in a clinical isolate is untested."
        )
    elif not record.get("hn878_differential_reported"):
        absences.append(
            "Measured in both strains, but Bosch 2021 reports no differential for this "
            "gene, so the two indices should be compared by eye rather than treated as "
            "a tested difference."
        )
    if not clinical:
        absences.append(
            "The clinical layer is not built in this store, so nothing is known here about "
            "drugs or trials. Run `atlas clinical`."
        )
    elif not any(d["link"] in TARGET_LINKS for d in drugs):
        absences.append(
            "No drug with a TB indication in ChEMBL acts on this gene by ChEMBL's mechanism "
            "or Bosch 2021's annotation."
        )
    absences.append("No druggability or pocket call: no public source provides one.")

    return TargetDetail(
        **record,
        alphafold=predicted[0] if predicted else None,
        structures=structures,
        orthologue_structures=orthologue_structures,
        chembl_targets=chembl_targets,
        activities=activities,
        whole_cell=whole_cell,
        compounds=compounds,
        variants=variants,
        partners=partners,
        **{name: value for name, value in annotation.items() if value is not None},
        bound_ligands=bound_ligands,
        drugs=drugs,
        trials=trials,
        conditions=conditions,
        interactions=interactions,
        tnseq_coverage=tnseq,
        absences=absences,
    )


@app.get("/compounds/{molecule_chembl_id}")
def compound(molecule_chembl_id: str) -> dict[str, Any]:
    """One molecule, the way hit triage asks: what does it touch, and how hard?

    Protein-level activity and whole-cell potency are returned apart, because
    a MIC is not evidence against a protein, and the genes it reaches carry
    the evidence level that put them there.
    """
    connection = _db()
    rows = _query(
        connection, "SELECT * FROM compounds WHERE molecule_chembl_id = ?", [molecule_chembl_id]
    )
    if not rows:
        raise HTTPException(404, f"no compound {molecule_chembl_id} in the atlas")
    activities = _query(
        connection,
        "SELECT * FROM activities WHERE molecule_chembl_id = ? AND evidence <> 'whole_cell'"
        " ORDER BY pchembl_value DESC NULLS LAST",
        [molecule_chembl_id],
    )
    whole_cell = _query(
        connection,
        "SELECT * FROM activities WHERE molecule_chembl_id = ? AND evidence = 'whole_cell'"
        " ORDER BY pchembl_value DESC NULLS LAST",
        [molecule_chembl_id],
    )
    # Through the crosswalk's ChEMBL targets, so a gene is reached the same way
    # it is everywhere else -- with its evidence level, never flattened.
    genes = _query(
        connection,
        "WITH gene_target AS ("
        "  SELECT w.rv_id, s.gene_name, s.product, s.essentiality, s.vulnerability_index,"
        "         s.vulnerability_certain, t.target_id, t.evidence, t.via_organism"
        "  FROM crosswalk w, UNNEST(w.chembl_targets) AS u(t)"
        "  JOIN target_summary s ON s.rv_id = w.rv_id)"
        " SELECT gt.rv_id, any_value(gt.gene_name) AS gene_name, any_value(gt.product) AS product,"
        "   any_value(gt.essentiality) AS essentiality,"
        "   any_value(gt.vulnerability_index) AS vulnerability_index,"
        "   any_value(gt.vulnerability_certain) AS vulnerability_certain,"
        "   any_value(gt.evidence) AS evidence, any_value(gt.via_organism) AS via_organism,"
        "   count(*) AS n_activities, max(a.pchembl_value) AS best_pchembl"
        " FROM gene_target gt JOIN activities a ON a.target_chembl_id = gt.target_id"
        " WHERE a.molecule_chembl_id = ? AND a.evidence <> 'whole_cell'"
        " GROUP BY gt.rv_id ORDER BY best_pchembl DESC NULLS LAST",
        [molecule_chembl_id],
    )
    drug = _query(
        connection, "SELECT * FROM drugs WHERE molecule_chembl_id = ?", [molecule_chembl_id]
    )
    return {
        **rows[0],
        "genes": genes,
        "activities": activities,
        "whole_cell": whole_cell,
        # The same molecule where it has reached the clinic, or None.
        "drug": drug[0] if drug else None,
    }


class Hit(BaseModel):
    """One thing the atlas holds, named well enough to pick from a list."""

    id: str
    label: str
    detail: str | None = None


# Each kind of object, with: the view, the id, the label, a line of context, the
# columns to match on, and the column to rank by when nothing is an exact hit.
SEARCHES: dict[str, tuple[str, str, str, str, tuple[str, ...], str]] = {
    "genes": (
        "target_summary",
        "rv_id",
        "coalesce(nullif(gene_name, rv_id), rv_id)",
        "product",
        ("rv_id", "gene_name", "uniprot_acc", "product"),
        "n_pdb DESC NULLS LAST",
    ),
    "drugs": (
        "drugs",
        "molecule_chembl_id",
        "coalesce(pref_name, molecule_chembl_id)",
        "list_aggr(tb_indications, 'string_agg', ', ')",
        ("molecule_chembl_id", "pref_name", "list_aggr(synonyms, 'string_agg', '|')"),
        "max_phase_tb DESC NULLS LAST",
    ),
    "trials": (
        "trials",
        "nct_id",
        "coalesce(acronym, nct_id)",
        "brief_title",
        (
            "nct_id",
            "acronym",
            "brief_title",
            "lead_sponsor",
            # What the trial actually gave people, so a drug name finds it.
            "list_aggr(list_transform(interventions, i -> i.name), 'string_agg', '|')",
        ),
        "start_date DESC NULLS LAST",
    ),
    "compounds": (
        "compounds",
        "molecule_chembl_id",
        "coalesce(pref_name, molecule_chembl_id)",
        "molecule_type",
        ("molecule_chembl_id", "pref_name", "inchi_key"),
        "max_phase DESC NULLS LAST",
    ),
}


@app.get("/search", response_model=dict[str, list[Hit]])
def search(
    q: Annotated[str, Query(min_length=1, description="An id, a name, or part of one")],
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> dict[str, list[Hit]]:
    """One box over genes, drugs, trials and compounds.

    An exact id wins, then a name that starts with the term, then anything that
    mentions it -- so typing `dprE1` opens the gene rather than the list of
    everything whose description mentions it.
    """
    term = q.strip().lower()
    found: dict[str, list[Hit]] = {kind: [] for kind in SEARCHES}
    if not term:
        return found
    connection = _db()
    for kind, (view, key, label, detail, columns, fallback) in SEARCHES.items():
        # Whether the table is in the store, not whether a view is bound: the
        # empty stand-ins exist precisely to let queries bind, and they carry
        # only the columns the roll-up needs.
        if not built(view):
            found[kind] = []
            continue
        haystacks = [f"lower(coalesce({column}, ''))" for column in columns]
        where = " OR ".join(f"{h} LIKE ? ESCAPE '\\'" for h in haystacks)
        rank = (
            f"CASE WHEN lower({key}) = ? THEN 0"
            f" WHEN lower({label}) = ? THEN 1"
            f" WHEN lower({label}) LIKE ? ESCAPE '\\' THEN 2 ELSE 3 END"
        )
        rows = _query(
            connection,
            f"SELECT {key} AS id, {label} AS label, {detail} AS detail, {rank} AS rank"
            f" FROM {view} WHERE {where} ORDER BY rank, {fallback}, id LIMIT ?",
            # Placeholders bind in the order they appear in the text, and the
            # rank expression is in the SELECT list, ahead of the WHERE.
            [term, term, _like(term)[1:], *[_like(term)] * len(haystacks), limit],
        )
        found[kind] = [Hit(**{k: v for k, v in row.items() if k != "rank"}) for row in rows]
    return found


@app.get("/drugs")
def drugs(
    q: Annotated[str | None, Query(description="Name, synonym or ChEMBL id")] = None,
    min_phase: Annotated[float | None, Query(description="Best phase for TB")] = None,
    acts_on_mtb: bool | None = None,
    host_targeted: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """TB drugs and candidates, best TB phase first, with the genes they act on."""
    _require_clinical()
    where: list[str] = []
    params: list[Any] = []
    if q:
        where.append(
            "(lower(d.pref_name) LIKE ? ESCAPE '\\'"
            " OR lower(list_aggr(d.synonyms, 'string_agg', '|')) LIKE ? ESCAPE '\\'"
            " OR lower(d.molecule_chembl_id) = ?)"
        )
        params += [_like(q.lower()), _like(q.lower()), q.lower()]
    if min_phase is not None:
        where.append("d.max_phase_tb >= ?")
        params.append(min_phase)
    for column, value in (("acts_on_mtb", acts_on_mtb), ("host_targeted", host_targeted)):
        if value is not None:
            where.append(f"d.{column} = ?")
            params.append(value)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    connection = _db()
    total = connection.execute(f"SELECT count(*) FROM drugs d {clause}", params).fetchone()[0]
    items = _query(
        connection,
        "SELECT d.molecule_chembl_id, d.pref_name, d.synonyms, d.max_phase_tb, d.max_phase,"
        " d.first_approval, d.molecule_type, d.atc_codes, d.acts_on_mtb, d.host_targeted,"
        " d.target_organisms, d.mechanisms_of_action,"
        # The list draws each molecule, so it needs the SMILES. 112 rows, and
        # the depiction is made in the browser -- nothing is stored.
        " d.smiles,"
        " coalesce(g.genes, []) AS genes, coalesce(t.n_trials, 0) AS n_trials"
        " FROM drugs d"
        " LEFT JOIN (SELECT g.molecule_chembl_id,"
        "   list(DISTINCT {'rv_id': g.rv_id, 'gene_name': s.gene_name}) AS genes"
        "   FROM drug_genes g JOIN target_summary s USING (rv_id)"
        f"   WHERE g.link IN ({TARGET_LINK_SQL}) GROUP BY 1) g USING (molecule_chembl_id)"
        " LEFT JOIN (SELECT molecule_chembl_id, count(DISTINCT nct_id) AS n_trials"
        "   FROM trial_drugs GROUP BY 1) t USING (molecule_chembl_id)"
        f" {clause} ORDER BY d.max_phase_tb DESC NULLS LAST, d.pref_name LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/drugs/{molecule_chembl_id}")
def drug(molecule_chembl_id: str) -> dict[str, Any]:
    """One drug: mechanisms, every gene link with how it was made, trials, bioactivity."""
    _require_clinical()
    connection = _db()
    found = _query(
        connection, "SELECT * FROM drugs WHERE molecule_chembl_id = ?", [molecule_chembl_id]
    )
    if not found:
        raise HTTPException(404, f"no TB drug {molecule_chembl_id} in the atlas")
    mechanisms = _query(
        connection,
        "SELECT * FROM drug_mechanisms WHERE molecule_chembl_id = ? ORDER BY target_name",
        [molecule_chembl_id],
    )
    genes = _query(
        connection,
        "SELECT g.*, s.gene_name, s.product, s.essentiality, s.vulnerability_index,"
        " s.vulnerability_certain FROM drug_genes g JOIN target_summary s USING (rv_id)"
        " WHERE g.molecule_chembl_id = ? ORDER BY CASE g.link WHEN 'mechanism' THEN 0"
        " WHEN 'bosch_2021' THEN 1 WHEN 'mechanism_complex' THEN 2 ELSE 3 END, g.rv_id",
        [molecule_chembl_id],
    )
    trials = _query(
        connection,
        "SELECT t.nct_id, t.brief_title, t.acronym, t.phases, t.phase_max, t.status,"
        " t.start_date, t.completion_date, t.lead_sponsor, t.enrollment, t.has_results,"
        " td.via_chembl_ref, td.via_intervention_name, td.matched_names"
        " FROM trial_drugs td JOIN trials t USING (nct_id) WHERE td.molecule_chembl_id = ?"
        " ORDER BY t.start_date DESC NULLS LAST",
        [molecule_chembl_id],
    )
    # The discovery end of the same molecule, where the atlas holds it.
    bioactivity = _query(
        connection,
        "SELECT count(*) FILTER (WHERE evidence <> 'whole_cell') AS n_protein,"
        " max(pchembl_value) FILTER (WHERE evidence <> 'whole_cell') AS best_protein_pchembl,"
        " count(*) FILTER (WHERE evidence = 'whole_cell') AS n_whole_cell,"
        " max(pchembl_value) FILTER (WHERE evidence = 'whole_cell') AS best_whole_cell_pchembl"
        " FROM activities WHERE molecule_chembl_id = ?",
        [molecule_chembl_id],
    )
    return {
        **found[0],
        "mechanisms": mechanisms,
        "genes": genes,
        "trials": trials,
        "bioactivity": bioactivity[0],
    }


TRIAL_SORTS = ("start_date", "phase_max", "enrollment", "last_update", "nct_id")


@app.get("/trials")
def trials(
    q: Annotated[
        str | None, Query(description="NCT id, title, acronym, sponsor or intervention")
    ] = None,
    min_phase: float | None = None,
    status: Annotated[list[str] | None, Query()] = None,
    molecule: Annotated[str | None, Query(description="Linked to this ChEMBL drug")] = None,
    linked: Annotated[bool | None, Query(description="Linked to any TB drug")] = None,
    sort: str = "start_date",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=2000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    _require_clinical()
    if sort not in TRIAL_SORTS:
        raise HTTPException(400, f"sort must be one of {list(TRIAL_SORTS)}")
    where: list[str] = []
    params: list[Any] = []
    if q:
        where.append(
            "(lower(t.nct_id) = ? OR lower(t.brief_title) LIKE ? ESCAPE '\\'"
            " OR lower(coalesce(t.acronym, '')) LIKE ? ESCAPE '\\'"
            " OR lower(coalesce(t.lead_sponsor, '')) LIKE ? ESCAPE '\\'"
            " OR lower(CAST(t.interventions AS VARCHAR)) LIKE ? ESCAPE '\\')"
        )
        params += [q.lower()] + [_like(q.lower())] * 4
    if min_phase is not None:
        where.append("t.phase_max >= ?")
        params.append(min_phase)
    if status:
        where.append(f"t.status IN ({','.join('?' * len(status))})")
        params += status
    if molecule:
        where.append("t.nct_id IN (SELECT nct_id FROM trial_drugs WHERE molecule_chembl_id = ?)")
        params.append(molecule)
    if linked is not None:
        where.append("(t.nct_id IN (SELECT nct_id FROM trial_drugs)) = ?")
        params.append(linked)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    connection = _db()
    total = connection.execute(f"SELECT count(*) FROM trials t {clause}", params).fetchone()[0]
    items = _query(
        connection,
        "SELECT t.*, coalesce(l.drugs, []) AS drugs FROM trials t"
        " LEFT JOIN (SELECT td.nct_id, list({'molecule_chembl_id': td.molecule_chembl_id,"
        "   'pref_name': d.pref_name, 'via_chembl_ref': td.via_chembl_ref,"
        "   'via_intervention_name': td.via_intervention_name} ORDER BY d.pref_name) AS drugs"
        "   FROM trial_drugs td JOIN drugs d USING (molecule_chembl_id) GROUP BY 1) l"
        f" USING (nct_id) {clause} ORDER BY t.{sort} {order.upper()} NULLS LAST, t.nct_id"
        " LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/trials/{nct_id}")
def trial(nct_id: str) -> dict[str, Any]:
    _require_clinical()
    connection = _db()
    found = _query(connection, "SELECT * FROM trials WHERE nct_id = ?", [nct_id])
    if not found:
        raise HTTPException(404, f"no trial {nct_id} in the atlas")
    drugs = _query(
        connection,
        "SELECT td.*, d.pref_name, d.max_phase_tb FROM trial_drugs td"
        " JOIN drugs d USING (molecule_chembl_id) WHERE td.nct_id = ? ORDER BY d.pref_name",
        [nct_id],
    )
    genes = _query(
        connection,
        "SELECT DISTINCT g.rv_id, s.gene_name"
        " FROM trial_drugs td JOIN drug_genes g USING (molecule_chembl_id)"
        " JOIN target_summary s USING (rv_id)"
        f" WHERE td.nct_id = ? AND g.link IN ({TARGET_LINK_SQL}) ORDER BY g.rv_id",
        [nct_id],
    )
    return {**found[0], "drugs": drugs, "genes": genes}


def _query(
    connection: duckdb.DuckDBPyConnection, sql: str, params: list[Any]
) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, params)
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


# --- agent -------------------------------------------------------------------


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    effort: Literal["low", "medium", "high", "xhigh"] = "high"


class AgentAnswer(BaseModel):
    """The answer plus the queries behind it, so it can be checked rather than trusted."""

    answer: str
    queries: list[dict[str, Any]]
    sources: dict[str, str]


@app.post("/ask", response_model=AgentAnswer)
def ask(body: Question) -> AgentAnswer:
    from . import agent

    try:
        result = agent.ask(body.question, effort=body.effort)
    except RuntimeError as error:
        # No credentials configured: a 503 rather than a 500, because the rest of
        # the API is fine and this one route simply is not available.
        raise HTTPException(503, str(error)) from error
    return AgentAnswer(
        answer=result.text,
        queries=[
            {"tool": c.name, "sql": c.input.get("sql"), "rows": c.rows, "error": c.error}
            for c in result.calls
        ],
        sources=result.sources,
    )
