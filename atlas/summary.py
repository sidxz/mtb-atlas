"""One row per gene, every evidence table rolled up.

Both the `/targets` endpoint and the genome canvas want the same thing: a
scalar per gene per kind of evidence, cheap to filter and sort. Computing that
once here keeps the roll-up rules in a single place instead of drifting between
the API, the frontend and whatever queries the agent writes.

The detail endpoints still read the evidence tables directly; this is a
summary, not a replacement.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from .clinical import TARGET_LINK_SQL
from .store import STORE, built, provenance, read, write_parquet

# Whole-cell potency is attributed to a gene only through a compound that
# already has protein-level activity on it. See CLAUDE.md.
SUMMARY_SQL = """
WITH gene_target AS (
    SELECT w.rv_id, t.target_id, t.evidence
    FROM walk w, UNNEST(w.chembl_targets) AS u(t)
),
protein_act AS (
    SELECT gt.rv_id,
           count(*)                                AS n_activities,
           count(DISTINCT a.molecule_chembl_id)    AS n_compounds,
           max(a.pchembl_value)                    AS best_pchembl,
           -- Whether anyone has published a way to measure this protein, which
           -- is a different question from whether anyone has hit it. Distinct
           -- assays, not measurements: one assay run against 400 compounds is
           -- one assay you could run again. `direct` only -- an orthologue
           -- assay is a real assay on another organism's protein, and
           -- `whole_cell` rows are MICs ChEMBL files against the organism.
           count(DISTINCT a.assay_chembl_id) FILTER (WHERE a.evidence = 'direct')
               AS n_protein_assays,
           max(a.document_year) FILTER (WHERE a.evidence = 'direct')
               AS latest_protein_assay_year
    FROM gene_target gt
    JOIN act a ON a.target_chembl_id = gt.target_id AND a.evidence <> 'whole_cell'
    GROUP BY 1
),
assay_example AS (
    -- The assay the literature leans on hardest, as a readable description of
    -- what the measurement actually is: a coupled enzymatic readout and a
    -- fluorescence cell-free screen are not interchangeable to someone who has
    -- to run one.
    SELECT rv_id, arg_max(assay_description, n_measurements) AS protein_assay_example
    FROM (
        SELECT gt.rv_id, a.assay_description, count(*) AS n_measurements
        FROM gene_target gt
        JOIN act a ON a.target_chembl_id = gt.target_id
        WHERE a.evidence = 'direct' AND a.assay_description IS NOT NULL
        GROUP BY 1, 2
    )
    GROUP BY 1
),
gene_compound AS (
    SELECT DISTINCT gt.rv_id, a.molecule_chembl_id
    FROM gene_target gt
    JOIN act a ON a.target_chembl_id = gt.target_id AND a.evidence <> 'whole_cell'
),
cell_act AS (
    -- `best_whole_cell_pchembl` is kept as it was, but it is NOT the MIC: ChEMBL
    -- computes pchembl_value for affinity endpoints only, so that column comes
    -- from the handful of whole-cell IC50/EC50 rows and is NULL for every MIC.
    -- `best_pmic` is the MIC-derived number, converted in the ingester.
    -- Censored MICs ('>' at the top concentration) carry no pmic by design and
    -- are counted separately, so a gene whose chemistry is all non-inhibition
    -- reads as that rather than as untested.
    SELECT gc.rv_id,
           count(*)             AS n_whole_cell,
           max(a.pchembl_value) AS best_whole_cell_pchembl,
           max(a.pmic)          AS best_pmic,
           median(a.pmic)       AS median_pmic,
           count(a.pmic)        AS n_mic,
           count(*) FILTER (
               WHERE a.pmic IS NULL AND a.standard_relation IN ('>', '>=')
           )                    AS n_mic_censored,
           count(*) FILTER (WHERE a.resistant_panel) AS n_resistant_panel
    FROM gene_compound gc
    JOIN act a ON a.molecule_chembl_id = gc.molecule_chembl_id AND a.evidence = 'whole_cell'
    GROUP BY 1
),
cell_conditions AS (
    -- The growth conditions this gene's chemistry has actually been measured
    -- under, as a list rather than a column each: one row per condition with
    -- its own best potency. `unspecified` is the commonest and means the
    -- deposit never stated a medium -- not that it was standard.
    SELECT rv_id,
           list({
               'condition': condition,
               'n': n,
               'n_with_pmic': n_with_pmic,
               'best_pmic': best_pmic
           } ORDER BY n DESC) AS whole_cell_conditions
    FROM (
        SELECT gc.rv_id,
               a.assay_condition AS condition,
               count(*)          AS n,
               count(a.pmic)     AS n_with_pmic,
               max(a.pmic)       AS best_pmic
        FROM gene_compound gc
        JOIN act a ON a.molecule_chembl_id = gc.molecule_chembl_id
                  AND a.evidence = 'whole_cell'
        GROUP BY 1, 2
    )
    GROUP BY 1
),
screening AS (
    -- Has this target been SCREENED, or merely studied? `n_protein_assays`
    -- counts assays; it cannot tell one 1,880-compound campaign from fourteen
    -- five-compound follow-ups, and those are opposite answers to "is there a
    -- tractable screen here". Genome-wide only three public assays reach 1,000
    -- compounds, so the scarcity is the finding.
    SELECT rv_id, max(n_cpd) AS max_assay_compounds
    FROM (
        SELECT gt.rv_id, a.assay_chembl_id, count(DISTINCT a.molecule_chembl_id) AS n_cpd
        FROM gene_target gt
        JOIN act a ON a.target_chembl_id = gt.target_id AND a.evidence = 'direct'
        GROUP BY 1, 2
    )
    GROUP BY 1
),
struct AS (
    SELECT s.uniprot_acc,
           count(*)                                      AS n_pdb,
           min(s.resolution)                             AS best_resolution,
           sum((s.n_ligands > 0)::int)                    AS n_pdb_with_ligand,
           list_distinct(flatten(list(s.ligand_ids)))     AS ligand_ids,
           list_distinct(list(s.method))                  AS methods
    FROM structures s
    GROUP BY 1
),
inter AS (
    -- Edges are stored once per unordered pair, so each gene has to be counted
    -- from both ends of the edge.
    SELECT rv_id, count(*) AS n_partners, max(combined_score) AS top_partner_score
    FROM (
        SELECT rv_id, combined_score FROM interactions
        UNION ALL
        SELECT partner_rv_id AS rv_id, combined_score FROM interactions
    )
    GROUP BY 1
),
drug_link AS (
    -- A drug counts on a gene only when a source says it acts on that gene's
    -- own protein. Complex membership and resistance are shown on the page,
    -- never counted here. See atlas/clinical.py.
    SELECT g.rv_id,
           count(DISTINCT g.molecule_chembl_id) FILTER (WHERE g.link IN ({target_links}))
               AS n_drugs,
           max(d.max_phase_tb) FILTER (WHERE g.link IN ({target_links}))
               AS best_drug_phase,
           list_sort(list_distinct(
               list(d.pref_name) FILTER (WHERE g.link IN ({target_links}))
           )) AS drug_names
    FROM drug_genes g
    JOIN drugs d USING (molecule_chembl_id)
    GROUP BY 1
),
complex_only AS (
    -- Drugs whose only link to this gene is membership of the complex they act on.
    SELECT g.rv_id, count(DISTINCT g.molecule_chembl_id) AS n_complex_drugs
    FROM drug_genes g
    WHERE g.link = 'mechanism_complex'
      AND NOT EXISTS (
          SELECT 1 FROM drug_genes t
          WHERE t.rv_id = g.rv_id AND t.molecule_chembl_id = g.molecule_chembl_id
            AND t.link IN ({target_links}))
    GROUP BY 1
),
gene_trials AS (
    SELECT g.rv_id, count(DISTINCT t.nct_id) AS n_trials
    FROM drug_genes g
    JOIN trial_drugs t USING (molecule_chembl_id)
    WHERE g.link IN ({target_links})
    GROUP BY 1
),
res AS (
    SELECT r.gene,
           count(*)                                            AS n_catalogued,
           sum(r.associated::int)                              AS n_associated,
           sum((r.associated AND r.residue_position IS NOT NULL)::int) AS n_mappable,
           list_distinct(list(r.drug) FILTER (WHERE r.associated)) AS drugs
    FROM resistance r
    GROUP BY 1
)
SELECT
    w.rv_id, w.feature, w.gene_name, w.product, w.functional_category AS category,
    w.start, w.stop, w.strand, w.is_pseudogene, w.length, w.protein_name,
    w.uniprot_acc, w.acc_status, w.conflict, w.shared_accession, w.shares_accession_with,

    v.vulnerability_index,
    v.vi_lower,
    v.vi_upper,
    coalesce(v.certain, false)         AS vulnerability_certain,
    coalesce(v.crispr_essential, false) AS crispr_essential,
    v.antibacterial,

    -- The same knockdown series in HN878, a clinical isolate. NULL where the
    -- strain sheet never covered the locus. The delta is the authors' own and
    -- runs HN878 minus H37Rv, so positive means less vulnerable in the clinic;
    -- it is reported for 507 genes and absent, not zero, for the rest.
    sv.vulnerability_index                 AS hn878_vulnerability_index,
    sv.certain                             AS hn878_vi_certain,
    sv.delta_vi                            AS hn878_delta_vi,
    sv.delta_vi_norm                       AS hn878_delta_vi_norm,
    coalesce(sv.differential_reported, false) AS hn878_differential_reported,

    coalesce(h.human_homolog, false)       AS human_homolog,
    coalesce(h.close_human_homolog, false) AS close_human_homolog,
    h.human_gene     AS human_homolog_gene,
    h.human_acc      AS human_homolog_acc,
    h.identity       AS human_homolog_identity,
    h.evalue         AS human_homolog_evalue,

    coalesce(i.n_partners, 0) AS n_partners,
    i.top_partner_score,

    -- NULL, not zero, for a gene with no protein: an RNA gene has no helices to count.
    pr.n_transmembrane,
    pr.n_references,

    -- NULL where Griffin never screened the locus; false where it did and the
    -- gene took no insertions to compare. Different answers, kept apart.
    cf.measured          AS cholesterol_measured,
    cf.log2_ratio        AS cholesterol_log2_ratio,
    cf.p_value           AS cholesterol_p,
    cf.cholesterol_required,
    cf.required_in_vivo,

    e.call            AS essentiality,
    e.call_label      AS essentiality_label,
    coalesce(e.essential, false)    AS essentiality_essential,
    coalesce(e.fitness_cost, false) AS essentiality_fitness_cost,
    e.condition       AS essentiality_condition,
    e.ta_sites,

    coalesce(st.n_pdb, 0)             AS n_pdb,
    st.best_resolution,
    coalesce(st.n_pdb_with_ligand, 0) AS n_pdb_with_ligand,
    coalesce(st.ligand_ids, [])       AS ligand_ids,
    coalesce(st.methods, [])          AS methods,

    (w.alphafold_id IS NOT NULL) AS has_predicted,
    p.plddt_mean, p.plddt_very_low,

    w.n_chembl_targets, w.chembl_evidence,
    coalesce(pa.n_activities, 0) AS n_activities,
    coalesce(pa.n_compounds, 0)  AS n_compounds,
    pa.best_pchembl,
    coalesce(ca.n_whole_cell, 0) AS n_whole_cell,
    ca.best_whole_cell_pchembl,
    ca.best_pmic,
    ca.median_pmic,
    coalesce(ca.n_mic, 0)              AS n_mic,
    coalesce(ca.n_mic_censored, 0)     AS n_mic_censored,
    coalesce(ca.n_resistant_panel, 0)  AS n_resistant_panel,
    coalesce(cc.whole_cell_conditions, []) AS whole_cell_conditions,
    coalesce(pa.n_protein_assays, 0) AS n_protein_assays,
    coalesce(sc.max_assay_compounds, 0)   AS max_assay_compounds,
    pa.latest_protein_assay_year,
    ax.protein_assay_example,

    -- CLINICAL COLUMNS

    (res.gene IS NOT NULL)              AS in_who_catalogue,
    coalesce(res.n_catalogued, 0)       AS n_variants_catalogued,
    coalesce(res.n_associated, 0)       AS n_variants_associated,
    coalesce(res.n_mappable, 0)         AS n_variants_mappable,
    coalesce(res.drugs, [])             AS resistance_drugs,

    (coalesce(st.n_pdb, 0) > 0)                   AS has_structure,
    (coalesce(pa.n_activities, 0) > 0)            AS has_ligands,
    -- The question the atlas exists to answer. "Essential" here means ES or
    -- ESD; a growth-defect gene is a softer signal and does not qualify.
    (coalesce(e.essential, false)
     AND coalesce(st.n_pdb, 0) > 0
     AND coalesce(pa.n_activities, 0) = 0)        AS structural_gap
FROM walk w
LEFT JOIN ess   e   ON e.rv_id = w.rv_id
LEFT JOIN cond  cf  ON cf.rv_id = w.rv_id
LEFT JOIN struct st ON st.uniprot_acc = w.uniprot_acc
LEFT JOIN pred  p   ON p.uniprot_acc = w.uniprot_acc
LEFT JOIN protein_act pa ON pa.rv_id = w.rv_id
LEFT JOIN cell_act    ca ON ca.rv_id = w.rv_id
LEFT JOIN cell_conditions cc ON cc.rv_id = w.rv_id
LEFT JOIN screening   sc ON sc.rv_id = w.rv_id
LEFT JOIN assay_example ax ON ax.rv_id = w.rv_id
LEFT JOIN res ON res.gene = coalesce(w.gene_name, w.rv_id)
LEFT JOIN vuln v ON v.rv_id = w.rv_id
LEFT JOIN strain_vuln sv ON sv.rv_id = w.rv_id
LEFT JOIN hom  h ON h.uniprot_acc = w.uniprot_acc
LEFT JOIN inter i ON i.rv_id = w.rv_id
LEFT JOIN prot pr ON pr.uniprot_acc = w.uniprot_acc
LEFT JOIN drug_link    dl ON dl.rv_id = w.rv_id
LEFT JOIN complex_only co ON co.rv_id = w.rv_id
LEFT JOIN gene_trials  gt ON gt.rv_id = w.rv_id
ORDER BY w.start
"""

CLINICAL_COLUMNS = """
    coalesce(dl.n_drugs, 0)             AS n_drugs,
    dl.best_drug_phase,
    coalesce(dl.drug_names, [])         AS drug_names,
    coalesce(co.n_complex_drugs, 0)     AS n_complex_drugs,
    coalesce(gt.n_trials, 0)            AS n_trials,
    (coalesce(dl.n_drugs, 0) > 0)       AS has_clinical_drug,
"""
# The clinical stage reaches ChEMBL and ClinicalTrials.gov, so a cold build can
# stop short of it. Then every clinical column is NULL rather than 0: "not
# built" and "no drug acts on this gene" are different answers, and only one of
# them was measured.
UNBUILT_CLINICAL_COLUMNS = """
    NULL::BIGINT    AS n_drugs,
    NULL::DOUBLE    AS best_drug_phase,
    NULL::VARCHAR[] AS drug_names,
    NULL::BIGINT    AS n_complex_drugs,
    NULL::BIGINT    AS n_trials,
    NULL::BOOLEAN   AS has_clinical_drug,
"""
# Shapes just wide enough for the clinical CTEs to bind when the files are
# absent; they return no rows, and the columns above are NULL regardless.
EMPTY_CLINICAL: dict[str, str] = {
    "drugs": "SELECT NULL::VARCHAR AS molecule_chembl_id, NULL::VARCHAR AS pref_name,"
    " NULL::VARCHAR AS inchi_key, NULL::DOUBLE AS max_phase_tb WHERE false",
    "drug_genes": "SELECT NULL::VARCHAR AS rv_id, NULL::VARCHAR AS molecule_chembl_id,"
    " NULL::VARCHAR AS link WHERE false",
    "trial_drugs": "SELECT NULL::VARCHAR AS nct_id, NULL::VARCHAR AS molecule_chembl_id"
    " WHERE false",
}
CLINICAL_COUNTS = ("with_clinical_drug", "drugs", "trials")

# A store built before the clinical-strain sheets were read has no such table,
# and `make summary` on it should report absence rather than fail. The columns
# are nullable either way, so an empty view is the whole stand-in.
EMPTY_OPTIONAL: dict[str, str] = {
    "strain_vulnerability": "SELECT NULL::VARCHAR AS rv_id, NULL::DOUBLE AS vulnerability_index,"
    " NULL::BOOLEAN AS certain, NULL::DOUBLE AS delta_vi, NULL::DOUBLE AS delta_vi_norm,"
    " NULL::BOOLEAN AS differential_reported WHERE false",
}

TABLES = {
    "walk": "crosswalk",
    "act": "activities",
    "structures": "structures",
    "pred": "predicted_structures",
    "ess": "essentiality",
    "resistance": "resistance",
    "vuln": "vulnerability",
    "strain_vuln": "strain_vulnerability",
    "hom": "homology",
    "interactions": "interactions",
    "cond": "conditional_fitness",
    "prot": "proteins",
    "drugs": "drugs",
    "drug_genes": "drug_genes",
    "trial_drugs": "trial_drugs",
}


def build(*, store: Path | None = None) -> Path:
    base = store or STORE
    connection = duckdb.connect()
    stand_ins = EMPTY_CLINICAL | EMPTY_OPTIONAL
    absent = [name for name in stand_ins if not built(name, store=store)]
    # Only the clinical tables blank the clinical columns; an absent strain
    # sheet must not be read as "no drug acts on this gene".
    missing = [name for name in absent if name in EMPTY_CLINICAL]
    for alias, name in TABLES.items():
        source = (
            stand_ins[name] if name in absent else f"SELECT * FROM '{base / f'{name}.parquet'}'"
        )
        connection.sql(f"CREATE VIEW {alias} AS {source}")
    rows = connection.sql(
        SUMMARY_SQL.replace(
            "    -- CLINICAL COLUMNS\n",
            UNBUILT_CLINICAL_COLUMNS if missing else CLINICAL_COLUMNS,
        ).replace("{target_links}", TARGET_LINK_SQL)
    )
    columns = rows.columns
    records = [dict(zip(columns, row, strict=True)) for row in rows.fetchall()]

    versions = {
        name: provenance(name, store=store)[0]
        for name in sorted(set(TABLES.values()) - set(absent))
    }
    return write_parquet(
        "target_summary",
        records,
        source="atlas-summary",
        source_version="; ".join(f"{k}={v}" for k, v in versions.items()),
        retrieved_at=str(provenance("crosswalk", store=store)[1]),
        store=store,
    )


def counts(*, store: Path | None = None) -> dict[str, int]:
    """Headline numbers, used by `/meta` and by the CLI summary."""
    relation = read("target_summary", store=store).aggregate("""
            count(*) AS genes,
            sum(essentiality_essential::int) AS essential,
            sum(essentiality_fitness_cost::int) AS any_fitness_cost,
            sum(has_structure::int) AS with_structure,
            sum(has_predicted::int) AS with_predicted,
            sum(has_ligands::int) AS with_ligands,
            sum(in_who_catalogue::int) AS in_who_catalogue,
            sum((n_variants_associated > 0)::int) AS with_resistance,
            sum(structural_gap::int) AS structural_gap,
            sum(conflict::int) AS id_conflicts,
            sum((vulnerability_index IS NOT NULL
                 AND vulnerability_certain)::int) AS vulnerability_measured,
            sum(human_homolog::int) AS with_human_homolog,
            sum(close_human_homolog::int) AS with_close_human_homolog,
            sum(has_clinical_drug::int) AS with_clinical_drug
        """)
    row = relation.fetchone()
    out = {name: int(value or 0) for name, value in zip(relation.columns, row, strict=True)}
    for name in ("drugs", "trials"):
        if built(name, store=store):
            out[name] = int(read(name, store=store).aggregate("count(*)").fetchone()[0])
    # A key that is absent says the layer was never built. A zero would say it
    # was built and found nothing.
    if not built("drug_genes", store=store):
        for name in CLINICAL_COUNTS:
            out.pop(name, None)
    return out
