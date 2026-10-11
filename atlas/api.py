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
    "drug_precedent": ("ChEMBL mechanisms by Pfam domain", "CC BY-SA 3.0"),
    # The terms ask for attribution, the processing date (carried in the
    # version) and a statement of modifications (docs/data-sources.md).
    "trials": ("ClinicalTrials.gov", "US Government database; attribution required"),
    # PubChem's licence is per depositor, so every campaign row carries its own
    # `licence`; the version on this table is PubChem's (its first row).
    "screens": ("PubChem BioAssay + ChEMBL literature campaigns", "per depositor / CC BY-SA 3.0"),
}
# Store tables with no licence of their own: joins, and a second table from a
# source already listed above.
DERIVED = (
    "crosswalk",
    "target_summary",
    "drug_mechanisms",
    "drug_genes",
    "trial_drugs",
    "screen_stages",
    "screen_results",
)
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
    "n_target_screens",
    "max_screen_compounds",
    "best_resolution",
    "n_orthologue_pdb",
    "closest_orthologue_identity",
    "n_precedent_approved",
    "n_precedent_clinical",
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
    # Has a drug ever been filed against this FOLD? Approved and clinical-phase
    # drugs ChEMBL records against another single protein carrying one of this
    # gene's Pfam domains. Not a druggability score, and not a drug that acts
    # on this gene -- that is `n_drugs`. NULL where UniProt annotates no
    # domain, which is not the same as none found.
    n_precedent_approved: int | None = None
    n_precedent_clinical: int | None = None
    # Of the approved ones, how many act on a human protein: tractable
    # chemistry and a selectivity problem are the same fact here.
    n_precedent_human_target: int | None = None
    # Filed against a complex or protein family containing such a protein.
    # Shown, never counted -- ChEMBL files the ribosome's 45 approved drugs
    # against every subunit.
    n_precedent_complex: int | None = None
    precedent_pfam: str | None = None
    precedent_pfam_name: str | None = None
    # How many Mtb genes share that domain. A precedent on a domain 37 genes
    # carry is a statement about a superfamily, not about this protein.
    precedent_domain_genes: int | None = None
    precedent_example: str | None = None
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
    # Screening campaigns on this protein, from either source. None, not 0, where the
    # layer is not built. `n_screen_actives` sums only the screens that stated calls,
    # so it shares no denominator with `n_target_screens` and is never divided by it.
    # A complex screen is shown in `n_complex_screens` and never counted as own.
    n_target_screens: int | None = None
    n_complex_screens: int | None = None
    max_screen_compounds: int | None = None
    n_screen_actives: int | None = None
    latest_screen_year: int | None = None
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
    drug_precedent: list[dict[str, Any]] = Field(default_factory=list)
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
    # Campaigns that reach this gene, own protein first; `via_complex` ones are shown
    # and never counted as the gene's own.
    screens: list[dict[str, Any]] = Field(default_factory=list)
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
    numbers = counts()
    # Absent keys, not zeros, when the layer was never built -- the rule counts() keeps.
    if built("screen_results"):
        connection = _db()
        numbers["screens"] = connection.sql("SELECT count(*) FROM screens").fetchone()[0]
        numbers["genes_with_target_screen"] = connection.sql(
            "SELECT count(*) FROM target_summary WHERE n_target_screens > 0"
        ).fetchone()[0]
        numbers["profiled_compounds"] = connection.sql(
            f"SELECT count(*) FROM ({PROFILE_SQL})"
            f" WHERE {' OR '.join(f'{t} IS NOT NULL' for t in TIERS)}"
        ).fetchone()[0]
    return Meta(
        counts=numbers,
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
            "Drug precedent is not that call. `n_precedent_approved` counts approved drugs "
            "ChEMBL files against *another* single protein carrying one of this gene's Pfam "
            "domains, which is a count of database records. A gene's own protein is excluded, "
            "complex and family targets are shown but never counted, and a shared domain is "
            "not a shared binding site -- so the domain, how many Mtb genes carry it, and how "
            "much of the precedent is against human proteins travel with the number.",
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
            "Screens are the campaigns the atlas ingested: PubChem deposits of 10,000+ "
            "substances and the ChEMBL papers reachable from its activities, not every "
            "campaign ever run. A result with no outcome means the source stated no call, "
            "which is not 'inactive', and an actives count is never divided by a screen count.",
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
    has_target_screen: Annotated[
        bool | None, Query(description="A screening campaign on this gene's own protein")
    ] = None,
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
    if has_target_screen is not None:
        where.append("(n_target_screens > 0) = ?")
        params.append(has_target_screen)

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
    # Drug precedent for the fold, joined through this protein's own Pfam
    # domains and with its own accession excluded. The counted rows -- ChEMBL
    # `SINGLE PROTEIN` targets -- come first, because the complex and
    # protein-family filings below them are shown and never counted.
    drug_precedent = _query(
        connection,
        "SELECT pfam_id, pfam_name, accession, molecule_chembl_id, molecule_name, max_phase,"
        " target_chembl_id, target_name, target_type, organism, tax_id, action_type,"
        " mechanism_of_action"
        " FROM drug_precedent"
        " WHERE pfam_id IN (SELECT unnest(pfam_ids) FROM proteins WHERE uniprot_acc = ?)"
        "   AND accession IS DISTINCT FROM ?"
        " ORDER BY (target_type = 'SINGLE PROTEIN') DESC, max_phase DESC NULLS LAST,"
        " pfam_id, molecule_name LIMIT 200",
        [accession, accession],
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

    screening = built("screens") and built("screen_stages")
    screened_in = (
        _query(
            connection,
            f"WITH reach AS ({SCREEN_REACH})"
            " SELECT r.own, r.via_complex, sc.screen_id, sc.title, sc.depositor, sc.source,"
            " sc.year, sc.n_stages, sc.n_tested, sc.library_size_stated, sc.outcome_stated,"
            " sc.n_active, sc.n_inactive, sc.modalities"
            " FROM reach r JOIN screens sc USING (screen_id) WHERE r.rv_id = ?"
            " ORDER BY r.own DESC, sc.n_tested DESC NULLS LAST, sc.screen_id",
            [rv_id],
        )
        if screening
        else []
    )

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
    if not screening:
        absences.append(
            "The screening layer is not built in this store, so nothing is known here "
            "about screening campaigns."
        )
    elif not any(row["own"] for row in screened_in):
        complex_only = sum(row["via_complex"] for row in screened_in)
        absences.append(
            "No screening campaign in the atlas was run on this protein alone"
            + (
                f"; {complex_only} reached it only as part of a complex or a multi-protein "
                "deposit, which is not a screen of this protein."
                if complex_only
                else "."
            )
            + " The atlas holds the campaigns it ingested (PubChem deposits of 10,000+ "
            "substances, and ChEMBL papers reachable from its activities), not every one "
            "ever run."
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
    # The one open question in docs/data-sources.md that no source closes. The
    # precedent counts are the nearest sourced thing to it and are deliberately
    # worded as what they are: records in a database, not a pocket.
    pocket = "No druggability or pocket call: no public source provides one."
    approved = record.get("n_precedent_approved")
    shared = record.get("precedent_domain_genes") or 0
    carry = f"{shared} Mtb gene{'s carry' if shared != 1 else ' carries'} that domain"
    if approved:
        human = record.get("n_precedent_human_target") or 0
        warning = ", which is as much a selectivity warning as a precedent"
        whose = (
            (
                ", against a human protein"
                if approved == 1
                else ", all of them against human proteins"
            )
            + warning
            if human == approved
            else f", {human} of them against a human protein"
            if human
            else ", none of them against a human protein"
        )
        pocket += (
            f" What is sourced is precedent for the fold: {approved} approved "
            f"drug{'s are' if approved != 1 else ' is'} filed against another protein "
            f"carrying {record.get('precedent_pfam_name')} "
            f"({record.get('precedent_pfam')}){whose}. {carry}, and a shared domain is not "
            f"a shared binding site."
        )
    elif approved == 0:
        pocket += (
            " No approved drug is filed against any other protein carrying this gene's "
            "Pfam domains either, which is a measured zero rather than an untested one."
        )
        if record.get("n_precedent_complex"):
            pocket += (
                f" {record['n_precedent_complex']} "
                f"{'is' if record['n_precedent_complex'] == 1 else 'are'} filed against a "
                f"complex or protein family that contains one, which is not evidence about "
                f"this fold."
            )
    absences.append(pocket)

    return TargetDetail(
        **record,
        alphafold=predicted[0] if predicted else None,
        structures=structures,
        orthologue_structures=orthologue_structures,
        drug_precedent=drug_precedent,
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
        screens=screened_in,
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
    # Every campaign stage that tested it, with the outcome as the source gave it:
    # this is where "tested and inactive" is provable, and NULL stays "no call".
    tested_in = (
        _query(
            connection,
            "SELECT r.screen_id, sc.title AS screen_title, sc.source AS screen_source, sc.year,"
            " r.stage_id, st.stage, st.modality, st.description, st.derived, r.outcome,"
            " r.activity_score, r.endpoint, r.standard_relation, r.standard_value,"
            " r.standard_units, r.activity_comment, r.pubchem_cid, r.pubchem_sid"
            " FROM screen_results r JOIN screen_stages st USING (stage_id)"
            " JOIN screens sc ON sc.screen_id = r.screen_id"
            " WHERE r.molecule_chembl_id = ?"
            f" ORDER BY sc.n_tested DESC NULLS LAST, r.screen_id, {STAGE_ORDER}, r.stage_id"
            " LIMIT 1000",
            [molecule_chembl_id],
        )
        if built("screen_results")
        else []
    )
    if not rows and not tested_in:
        raise HTTPException(404, f"no compound {molecule_chembl_id} in the atlas")
    # A molecule known only from a screen has no `compounds` row: the page still
    # answers, with the identifier and what it was tested in, and nothing invented.
    record = rows[0] if rows else {"molecule_chembl_id": molecule_chembl_id}
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
        **record,
        "genes": genes,
        "activities": activities,
        "whole_cell": whole_cell,
        "tested_in": tested_in,
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
    # Ingested campaigns only. A set that was never ingested (the Pathogen Box) finds
    # nothing here, and `/screens` names those sets so the page can say why.
    "screens": (
        "screens",
        "screen_id",
        "coalesce(title, screen_id)",
        "depositor",
        ("screen_id", "aid", "title", "depositor", "document_chembl_id"),
        "n_tested DESC NULLS LAST",
    ),
}


@app.get("/search", response_model=dict[str, list[Hit]])
def search(
    q: Annotated[str, Query(min_length=1, description="An id, a name, or part of one")],
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> dict[str, list[Hit]]:
    """One box over genes, drugs, trials, compounds and screening campaigns.

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


# --- screens: the campaign, its stages, and every result row ---------------------

# Every (gene, campaign) pair, by the two routes the store records targets on, with
# `own` meaning a screen of the gene's own protein and `via_complex` a screen of a
# complex or a deposit naming several proteins. This is `summary.screen_reach` per
# campaign rather than per gene, and a test holds the two to the same counts: if the
# rule changes there, it changes here, or the gene page and the gene table disagree.
SCREEN_REACH = """
WITH gene_target AS (
    SELECT w.rv_id, t.target_id, t.evidence
    FROM crosswalk w, UNNEST(w.chembl_targets) AS u(t)
), reach AS (
    SELECT gt.rv_id, st.screen_id,
           st.target_type IS NOT DISTINCT FROM 'SINGLE PROTEIN' AS own
    FROM gene_target gt JOIN screen_stages st ON st.target_chembl_id = gt.target_id
    WHERE gt.evidence = 'direct'
    UNION ALL
    SELECT r.rv_id, sc.screen_id,
           len(list_distinct(list_transform(
               list_filter(sc.targets, t -> len(t.rv_ids) > 0), t -> t.rv_ids
           ))) = 1
    FROM screens sc, UNNEST(sc.targets) AS u(tg), UNNEST(tg.rv_ids) AS r(rv_id)
)
SELECT r.rv_id, r.screen_id, s.gene_name,
       bool_or(r.own) AS own, bool_or(NOT r.own) AS via_complex
FROM reach r JOIN target_summary s USING (rv_id)
GROUP BY r.rv_id, r.screen_id, s.gene_name
"""
# Funnel order for a stage ladder. A derived row (a ratio ChEMBL computed from two
# other assays) has no funnel position, so it sorts last rather than first.
STAGE_ORDER = (
    "CASE stage WHEN 'primary' THEN 0 WHEN 'confirmatory' THEN 1"
    " WHEN 'counter_screen' THEN 2 WHEN 'profiling' THEN 3 ELSE 4 END"
)
SCREEN_SORTS = ("n_tested", "year", "n_stages", "n_active", "screen_id")
# The targets a deposit names that reach no locus: another strain's accession (MbtI's
# CDC 1551 P9WFX0), a GenBank protein id, a PDB chain. Strains are not bridged, so the
# gene reads zero screens and this is the only place the screen shows. It belongs to
# the campaign and is never attributed to a gene by name.
UNPLACED = "[t FOR t IN sc.targets IF len(t.rv_ids) = 0]"
# Sets a reader will look for and will not find, because they were never ingested.
# Their absence is coverage, not a screen that found nothing (docs/data-sources.md).
NOT_INGESTED = (
    "The Pathogen Box (MMV)",
    "The Malaria Box (MMV)",
    "GSK's TB set (TCAMS beyond the hit sets ChEMBL already holds)",
    "One patent campaign",
)


def _require_screens() -> None:
    if not built("screen_results"):
        raise HTTPException(
            503, "The screening layer is not built in this store. Run `atlas build`."
        )


@app.get("/screens")
def screens(
    q: Annotated[
        str | None, Query(description="Title, depositor, campaign id, AID, document or PMID")
    ] = None,
    source: Literal["chembl", "pubchem"] | None = None,
    modality: Annotated[str | None, Query(description="Any stage measured this")] = None,
    rv_id: Annotated[str | None, Query(description="Reaches this gene")] = None,
    own: Annotated[
        bool | None, Query(description="With rv_id: true for its own protein, false for complex")
    ] = None,
    outcome_stated: bool | None = None,
    unplaced: Annotated[
        bool | None, Query(description="Names a protein the atlas could not key to a locus")
    ] = None,
    sort: str = "n_tested",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """The campaigns the atlas ingested -- not every campaign that exists."""
    _require_screens()
    if sort not in SCREEN_SORTS:
        raise HTTPException(400, f"sort must be one of {list(SCREEN_SORTS)}")
    where: list[str] = []
    params: list[Any] = []
    if q:
        where.append(
            "(lower(sc.screen_id) = ? OR sc.aid = ? OR lower(coalesce(sc.document_chembl_id, ''))"
            " = ? OR sc.pubmed_id = ? OR lower(coalesce(sc.title, '')) LIKE ? ESCAPE '\\'"
            " OR lower(coalesce(sc.depositor, '')) LIKE ? ESCAPE '\\'"
            # An AID inside a project is a stage, not a campaign: find its campaign.
            " OR sc.screen_id IN (SELECT screen_id FROM screen_stages WHERE stage_id = ?))"
        )
        params += [q.lower(), q, q.lower(), q, _like(q.lower()), _like(q.lower()), f"pubchem:{q}"]
    if source:
        where.append("sc.source = ?")
        params.append(source)
    if modality:
        where.append("sc.screen_id IN (SELECT screen_id FROM screen_stages WHERE modality = ?)")
        params.append(modality)
    if rv_id:
        side = "" if own is None else f" AND {'own' if own else 'via_complex'}"
        where.append(f"sc.screen_id IN (SELECT screen_id FROM reach WHERE rv_id = ?{side})")
        params.append(rv_id)
    if outcome_stated is not None:
        where.append("sc.outcome_stated = ?")
        params.append(outcome_stated)
    if unplaced is not None:
        where.append(f"(len({UNPLACED}) > 0) = ?")
        params.append(unplaced)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    connection = _db()
    connection.sql(f"CREATE TEMP VIEW reach AS {SCREEN_REACH}")
    total = connection.execute(f"SELECT count(*) FROM screens sc {clause}", params).fetchone()[0]
    items = _query(
        connection,
        f"SELECT sc.*, {UNPLACED} AS unplaced_targets, coalesce(g.genes, []) AS genes"
        " FROM screens sc"
        " LEFT JOIN (SELECT screen_id, list({'rv_id': rv_id, 'gene_name': gene_name,"
        "   'own': own, 'via_complex': via_complex} ORDER BY rv_id) AS genes"
        "   FROM reach GROUP BY 1) g USING (screen_id)"
        f" {clause} ORDER BY sc.{sort} {order.upper()} NULLS LAST, sc.screen_id"
        " LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    # The classifier's fallbacks, as shares, so a funnel drawn from these labels can
    # say how much of it is "nothing said otherwise" (the UniRef-level rule again).
    # Over measured stages: a derived ratio has no funnel position to default.
    labels = connection.sql(
        "SELECT count(*) AS n_stages,"
        " count(*) FILTER (WHERE stage = 'primary') AS n_primary,"
        " count(*) FILTER (WHERE modality = 'other') AS n_modality_other,"
        " count(*) FILTER (WHERE modality IS NULL) AS n_modality_unclassified"
        " FROM screen_stages WHERE NOT derived"
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
        "stage_labels": dict(zip(labels.columns, labels.fetchone(), strict=True)),
        "n_unplaced": connection.sql(
            f"SELECT count(*) FROM screens sc WHERE len({UNPLACED}) > 0"
        ).fetchone()[0],
        "not_ingested": list(NOT_INGESTED),
    }


@app.get("/screens/{screen_id}")
def screen(screen_id: str) -> dict[str, Any]:
    """One campaign: its stage ladder with each stage's counts, and the genes it reaches."""
    _require_screens()
    connection = _db()
    found = _query(
        connection,
        f"SELECT sc.*, {UNPLACED} AS unplaced_targets FROM screens sc WHERE screen_id = ?",
        [screen_id],
    )
    if not found:
        raise HTTPException(404, f"no campaign {screen_id} in the atlas")
    # Counted from the rows, per stage, and never summed across stages: a compound
    # active in a primary and inactive in its confirmation is one compound twice.
    stages = _query(
        connection,
        "SELECT st.*, r.n_rows, r.n_compounds, r.n_active_rows, r.n_inactive_rows,"
        " r.n_inconclusive_rows, r.n_no_call_rows, r.endpoints"
        " FROM screen_stages st LEFT JOIN ("
        "   SELECT stage_id, count(*) AS n_rows,"
        "     count(DISTINCT coalesce(molecule_chembl_id, 'cid:' || pubchem_cid)) AS n_compounds,"
        "     count(*) FILTER (WHERE outcome = 'active') AS n_active_rows,"
        "     count(*) FILTER (WHERE outcome = 'inactive') AS n_inactive_rows,"
        "     count(*) FILTER (WHERE outcome = 'inconclusive') AS n_inconclusive_rows,"
        "     count(*) FILTER (WHERE outcome IS NULL) AS n_no_call_rows,"
        "     list_sort(list_distinct(list(endpoint))) AS endpoints"
        "   FROM screen_results WHERE screen_id = ? GROUP BY 1) r USING (stage_id)"
        f" WHERE st.screen_id = ? ORDER BY {STAGE_ORDER}, st.n_tested DESC NULLS LAST,"
        " st.stage_id",
        [screen_id, screen_id],
    )
    genes = _query(
        connection,
        f"WITH reach AS ({SCREEN_REACH})"
        " SELECT r.rv_id, r.gene_name, r.own, r.via_complex, s.product, s.essentiality,"
        " s.vulnerability_index, s.vulnerability_certain, s.shared_accession"
        " FROM reach r JOIN target_summary s USING (rv_id) WHERE r.screen_id = ?"
        " ORDER BY r.own DESC, r.rv_id",
        [screen_id],
    )
    return {**found[0], "stages": stages, "genes": genes}


@app.get("/screens/{screen_id}/results")
def screen_results(
    screen_id: str,
    stage_id: str | None = None,
    outcome: Annotated[
        list[Literal["active", "inactive", "inconclusive", "no_call"]] | None, Query()
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Result rows of one campaign, a page at a time. Never the whole table.

    A row is a SID (PubChem) or an activity (ChEMBL), not a compound, and none is
    collapsed: choosing which of a compound's rows wins would be silent.
    """
    _require_screens()
    where = ["r.screen_id = ?"]
    params: list[Any] = [screen_id]
    if stage_id:
        where.append("r.stage_id = ?")
        params.append(stage_id)
    if outcome:
        named = [o for o in outcome if o != "no_call"]
        either = []
        if named:
            either.append(f"r.outcome IN ({','.join('?' * len(named))})")
            params += named
        if "no_call" in outcome:
            either.append("r.outcome IS NULL")
        where.append(f"({' OR '.join(either)})")
    clause = " AND ".join(where)
    connection = _db()
    if not connection.execute("SELECT 1 FROM screens WHERE screen_id = ?", [screen_id]).fetchone():
        raise HTTPException(404, f"no campaign {screen_id} in the atlas")
    total = connection.execute(
        f"SELECT count(*) FROM screen_results r WHERE {clause}", params
    ).fetchone()[0]
    items = _query(
        connection,
        "SELECT r.*, st.stage, st.modality, c.pref_name, c.smiles"
        " FROM screen_results r JOIN screen_stages st USING (stage_id)"
        " LEFT JOIN compounds c USING (molecule_chembl_id)"
        f" WHERE {clause}"
        " ORDER BY CASE r.outcome WHEN 'active' THEN 0 WHEN 'inconclusive' THEN 1"
        " WHEN 'inactive' THEN 3 ELSE 2 END, r.activity_score DESC NULLS LAST,"
        " r.stage_id, r.result_tag, r.activity_id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


# --- hit profiling: one row per compound, a column per thing measured ------------

# Column -> the stage modality it counts. The last three are the tiers "beyond
# potency"; an Mtb protein assay is potency at the protein, not a tier.
PROFILE_COLUMNS = {
    "n_mtb_whole_cell": "phenotypic_mtb",
    "n_mtb_protein": "biochemical_mtb",
    "n_other_pathogen": "other_pathogen",
    "n_cytotox": "mammalian_cytotox",
    "n_adme": "adme",
    "n_in_vivo": "in_vivo_efficacy",
    # The classifier's fallback, and a real label: prose that matched no pattern.
    # Listed so "measured nothing but Mtb potency" can mean exactly that.
    "n_other": "other",
}
TIERS = ("n_cytotox", "n_adme", "n_in_vivo")
# The ratio of a cytotoxicity endpoint to a potency one, AS THE AUTHORS REPORTED IT.
# It lives on the `derived` stages, which are not measurements of this atlas's making
# -- but a published ratio is the paper's own number, not arithmetic performed here,
# and it is the first thing triage asks after potency. Only endpoints that name
# selectivity, and only dimensionless rows: 5 rows carry a `10^4No_unit` scale factor,
# and mixing those in would read as 10,000-fold more selective.
SELECTIVITY = (
    "st.derived AND r.standard_value IS NOT NULL"
    " AND (lower(r.endpoint) LIKE '%selectivity%' OR lower(r.endpoint) LIKE '%cc50/ic50%')"
    " AND (r.standard_units IS NULL OR r.standard_units = 'SI')"
)
# A bound is not a value, the same rule `pmic` follows for a censored MIC: "> 100-fold"
# says the experiment never reached the number, so it is counted and not averaged in.
MEASURED_SELECTIVITY = "r.standard_relation IS NULL OR r.standard_relation = '='"
PROFILE_SORTS = (
    *PROFILE_COLUMNS,
    "n_papers",
    "first_year",
    "latest_year",
    "n_selectivity",
    "selectivity_max",
    "n_active_campaigns",
    "molecule_chembl_id",
)
# ChEMBL only, because no PubChem stage carries a modality, and measured stages only:
# a derived ratio occupies no funnel position and does not make a compound "tested".
# Each count is of distinct assays, and NULL where there are none, so an unmeasured
# tier can never read as a measured zero.
_PROFILE_COUNTS = ", ".join(
    f"nullif(count(DISTINCT r.stage_id) FILTER (WHERE st.modality = '{modality}'), 0) AS {column}"
    for column, modality in PROFILE_COLUMNS.items()
)
PROFILE_SQL = f"""
WITH tested AS (
    SELECT r.molecule_chembl_id,
           count(DISTINCT r.screen_id) AS n_papers,
           min(sc.year) AS first_year,
           max(sc.year) AS latest_year,
           {_PROFILE_COUNTS}
    FROM screen_results r
    JOIN screen_stages st USING (stage_id)
    JOIN screens sc ON sc.screen_id = r.screen_id
    WHERE st.source = 'chembl' AND NOT st.derived AND r.molecule_chembl_id IS NOT NULL
    GROUP BY 1
), selectivity AS (
    SELECT r.molecule_chembl_id,
           nullif(count(*) FILTER (WHERE {MEASURED_SELECTIVITY}), 0) AS n_selectivity,
           min(r.standard_value) FILTER (WHERE {MEASURED_SELECTIVITY}) AS selectivity_min,
           max(r.standard_value) FILTER (WHERE {MEASURED_SELECTIVITY}) AS selectivity_max,
           count(*) FILTER (WHERE NOT ({MEASURED_SELECTIVITY})) AS n_selectivity_censored
    FROM screen_results r JOIN screen_stages st USING (stage_id)
    WHERE {SELECTIVITY} AND r.molecule_chembl_id IS NOT NULL
    GROUP BY 1
), calls AS (
    -- How often a stated call went this compound's way, with its own denominator:
    -- only 25 campaigns state calls at all, so `n_active_campaigns` alone would read
    -- as "never a hit" for a compound nobody ever called either way. Both or neither.
    SELECT molecule_chembl_id,
           count(DISTINCT screen_id) AS n_call_campaigns,
           count(DISTINCT screen_id) FILTER (WHERE outcome = 'active') AS n_active_campaigns
    FROM screen_results WHERE outcome IS NOT NULL AND molecule_chembl_id IS NOT NULL
    GROUP BY 1
)
SELECT t.*, s.n_selectivity, s.selectivity_min, s.selectivity_max,
       s.n_selectivity_censored, c.n_call_campaigns, c.n_active_campaigns
FROM tested t
LEFT JOIN selectivity s USING (molecule_chembl_id)
LEFT JOIN calls c USING (molecule_chembl_id)
"""


@app.get("/hits")
def hits(
    q: Annotated[str | None, Query(description="ChEMBL id or name")] = None,
    has: Annotated[
        list[
            Literal[
                "n_mtb_whole_cell",
                "n_mtb_protein",
                "n_other_pathogen",
                "n_other",
                "n_selectivity",
                *TIERS,
            ]
        ]
        | None,
        Query(description="Measured in every one of these"),
    ] = None,
    beyond_potency: Annotated[
        bool | None, Query(description="Has cytotoxicity, ADME or in-vivo data")
    ] = None,
    sort: str = "n_papers",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """What was measured on each compound in the ingested literature campaigns.

    Coverage, not a verdict: nothing here is ranked, weighted or combined into a
    score, and a compound with a MIC and nothing else is an answer, not a low one.

    Every count is of distinct ChEMBL assays, so this is the literature census. A
    compound tested only in a PubChem deposit has no row here, because no PubChem
    stage carries a modality; `/compounds/{id}` reaches it either way.
    """
    _require_screens()
    if sort not in PROFILE_SORTS:
        raise HTTPException(400, f"sort must be one of {list(PROFILE_SORTS)}")
    where: list[str] = []
    params: list[Any] = []
    if q:
        where.append("(lower(p.molecule_chembl_id) = ? OR lower(c.pref_name) LIKE ? ESCAPE '\\')")
        params += [q.lower(), _like(q.lower())]
    where += [f"p.{column} IS NOT NULL" for column in has or []]
    if beyond_potency is not None:
        where.append(f"({' OR '.join(f'p.{t} IS NOT NULL' for t in TIERS)}) = ?")
        params.append(beyond_potency)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    connection = _db()
    connection.sql(f"CREATE TEMP TABLE profile AS {PROFILE_SQL}")
    base = " FROM profile p LEFT JOIN compounds c USING (molecule_chembl_id)"
    total = connection.execute(f"SELECT count(*){base} {clause}", params).fetchone()[0]
    items = _query(
        connection,
        f"SELECT p.*, c.pref_name, c.smiles{base} {clause}"
        f" ORDER BY p.{sort} {order.upper()} NULLS LAST, p.molecule_chembl_id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    # The population, so a page can say "N of M" without a second request. Three
    # buckets, because two would lose the third: a compound measured only against
    # another pathogen (or `other`) is neither Mtb potency nor a tier beyond it.
    # The tier counts overlap -- a compound can carry several -- so they are not a split.
    tiered = " OR ".join(f"{t} IS NOT NULL" for t in TIERS)
    potency = "n_mtb_whole_cell IS NOT NULL OR n_mtb_protein IS NOT NULL"
    # "A MIC and nothing else" is the strict reading: whole-cell Mtb potency and no
    # other measurement of any kind. The looser count includes compounds carrying
    # other-pathogen or unclassified assays, which is not nothing else.
    nothing_else = " AND ".join(
        f"{column} IS NULL" for column in PROFILE_COLUMNS if column != "n_mtb_whole_cell"
    )
    population = connection.sql(
        "SELECT count(*) AS compounds,"
        f" count(*) FILTER (WHERE {tiered}) AS beyond_potency,"
        f" count(*) FILTER (WHERE NOT ({tiered}) AND ({potency})) AS potency_only,"
        f" count(*) FILTER (WHERE NOT ({tiered}) AND NOT ({potency})) AS elsewhere_only,"
        f" count(*) FILTER (WHERE n_mtb_whole_cell IS NOT NULL AND {nothing_else})"
        " AS whole_cell_and_nothing_else,"
        " count(n_selectivity) AS with_selectivity,"
        f" {', '.join(f'count({t}) AS {t}' for t in TIERS)} FROM profile"
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
        "population": dict(zip(population.columns, population.fetchone(), strict=True)),
    }


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
