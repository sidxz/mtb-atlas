"""Natural-language questions over the store, answered with cited records.

The agent gets two tools: the store's schema, and read-only SQL against it. One
query tool beats ten narrow ones here, because the questions a target biologist
asks are joins -- "essential, structure, no ligands, no human homolog, not in
the WHO catalogue" is one WHERE clause and would otherwise be five endpoints.

**Why the SQL tool is safe.** The tables are copied into an in-memory DuckDB at
startup, then `enable_external_access` is turned off and the configuration
locked, so no statement can read a file, attach a database or reach the
network. On top of that only a single SELECT/WITH statement is accepted and
every result is capped. The store is public data and read-only either way.

The system prompt carries the same rules as the rest of the codebase, because
an agent that quietly treats a missing row as a zero is worse than no agent:
absences are answers, evidence levels are not interchangeable, and every claim
names the records it came from.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import duckdb

from .store import STORE, provenance

MODEL = "claude-opus-5-5"
MAX_ROWS = 200
MAX_TURNS = 12

TABLES = (
    "target_summary",
    "crosswalk",
    "genes",
    "proteins",
    "structures",
    "predicted_structures",
    "activities",
    "compounds",
    "essentiality",
    "conditional_fitness",
    "conditional_tnseq",
    "tnseq_screens",
    "resistance",
    "vulnerability",
    "strain_vulnerability",
    "interactions",
    "homology",
    "paralogs",
    "orthologue_structures",
    "drug_precedent",
    "chembl_targets",
    "ligands",
    "drugs",
    "drug_mechanisms",
    "drug_genes",
    "trials",
    "trial_drugs",
)

# One line per table: what a question should reach for, and the trap in it.
TABLE_NOTES = {
    "target_summary": "START HERE. One row per gene, every evidence table rolled up. "
    "Scalar columns for filtering and sorting. `n_protein_assays` is how many published "
    "ChEMBL assays run against this gene's own protein -- whether the target can be "
    "screened at all, which is a different question from `n_compounds` (whether anyone "
    "has hit it). `max_assay_compounds` is the largest single published assay by distinct "
    "compounds, which separates one real screening campaign from a dozen small follow-ups: "
    "genome-wide only two genes reach 1,000. `hn878_*` compares vulnerability against a "
    "clinical isolate; see strain_vulnerability for the sign convention. "
    "**`n_pdb` counts structures of this gene's OWN protein; a borrowed one is in "
    "`n_orthologue_pdb` and does NOT make `has_structure` or `structural_gap` true.** "
    "3,146 CDS genes have no structure of their own and 449 of those have a mycobacterial "
    "neighbour that does. `same_sequence_structure` is the stronger case: an identical "
    "sequence deposited under another accession, true for 34 of them. "
    "`n_precedent_approved` counts approved drugs filed against ANOTHER protein sharing one "
    "of this gene's Pfam domains -- precedent that the fold can be bound, **not a "
    "druggability score and not a drug that acts on this gene** (that is `n_drugs`). It is "
    "NULL where UniProt annotates no domain, which is not zero. Always report "
    "`precedent_pfam_name` and `precedent_domain_genes` with it. "
    "`close_paralog` is whether a full-length second copy exists -- see the paralogs table "
    "for why it is stricter than `close_human_homolog`. `closest_paralog_gene` is NULL when "
    "there is no backup, while `nearest_relative_gene` is usually populated anyway, so "
    "reading the latter as redundancy is the trap. "
    "**For whole-cell potency use `best_pmic` / `median_pmic`, not "
    "`best_whole_cell_pchembl`** -- the latter is ChEMBL's pchembl_value, which exists for "
    "only 12 genes because it is NULL on every MIC; the pmic columns cover 71. `n_mic` "
    "counts exact MICs and `n_mic_censored` the '>' non-results, which are evidence of "
    "no activity rather than absence of testing. `whole_cell_conditions` is a list of "
    "structs (condition, n, n_with_pmic, best_pmic) -- UNNEST it to ask what conditions a "
    "gene's chemistry was measured under, remembering that `unspecified` means the deposit "
    "did not say, not standard media.",
    "crosswalk": "Identity only: Rv tag to accession, with source disagreements and "
    "the loci that share an accession.",
    "proteins": "One UniProt entry per accession, keyed on uniprot_acc: cross-references "
    "plus curated biology -- `function`, `locations`, `n_transmembrane`, `pathways`, "
    "`reactions` and `rhea_ids`, `cofactors`, GO term names (`go_process`, `go_function`, "
    "`go_component`), `disruption_phenotype`, and `pubmed_ids` / `n_references` (papers "
    "UniProt cites, a curated subset of the literature). NULL or empty means UniProt says "
    "nothing, which is not a negative finding: 0 transmembrane segments is 'none "
    "annotated', not 'soluble'.",
    "structures": "One row per (pdb_id, uniprot_acc). Join on uniprot_acc, NOT rv_id. "
    "`ligand_ids` excludes cofactors and crystallisation additives. `expression_hosts`, "
    "`plasmids`, `construct_length` and `mutations` are how the protein was PRODUCED, as "
    "the deposition states it -- the only answer in the store to 'has anyone made this "
    "protein, and from what'. An empty list means the entry does not say (1,649 of 4,803 "
    "rows name a plasmid), never that it was not expressed. Host strings are depositor "
    "text and inconsistent in case and strain naming, so group them with care: "
    "'Escherichia coli BL21(DE3)' and 'ESCHERICHIA COLI BL21(DE3)' are the same host. "
    "`mutations` is empty for a wild-type construct; a non-empty one means the sequence "
    "crystallised is not the wild-type protein.",
    "predicted_structures": "AlphaFold, keyed on uniprot_acc.",
    "activities": "ChEMBL bioactivity. `evidence` is direct | orthologue | whole_cell. "
    "Join to a gene through crosswalk.chembl_targets or target_summary. `assay_type` is "
    "ChEMBL's own: B binding, F functional, A ADME. **Do NOT read assay_type as 'protein "
    "assay'** -- every whole_cell row is F, because ChEMBL files MIC screens as functional "
    "assays against the organism. A published assay for a gene's own protein means "
    "`evidence = 'direct'`; count DISTINCT assay_chembl_id, since one assay can carry "
    "hundreds of measurements. `target_summary.n_protein_assays` is that count already "
    "done. **Potency lives in two different columns and they do not overlap.** "
    "`pchembl_value` is ChEMBL's own and is NULL on every one of the 3,870 MIC rows, "
    "because ChEMBL computes it for affinity endpoints only -- so `max(pchembl_value)` "
    "over whole_cell rows answers from 78 IC50/EC50 measurements and silently ignores "
    "every MIC. `pmic` is -log10(MIC in mol/L), computed in the ingester, and is the "
    "number to use for whole-cell potency; `pmic_basis` says which unit conversion "
    "produced it. No row has both. **A censored MIC gets no pmic**: `standard_relation` "
    "'>' means the compound did not inhibit at the highest concentration tested, so "
    "those rows are NULL on purpose and counting them as untested is wrong -- they are "
    "a measured non-result. `assay_condition` (whole_cell rows only) is the growth "
    "condition read from the assay prose: caseum | intracellular | non_replicating | "
    "alt_carbon | nutrient_stress | standard_media | unspecified. **`unspecified` is not "
    "`standard_media`** -- it means the deposit never stated a medium, which is most of "
    "them, and no condition matches `caseum` in this release at all. `resistant_panel` "
    "is a separate flag for strain, not medium (MDR or clinical isolates), so a row can "
    "be both.",
    "compounds": "One row per compound, with properties. Keyed on molecule_chembl_id.",
    "essentiality": "TnSeq calls, one in vitro condition. `essential` is ES or ESD; "
    "`fitness_cost` also includes growth-defect.",
    "conditional_fitness": "Griffin 2011 TnSeq, cholesterol vs glycerol, one row per gene. "
    "`log2_ratio` NEGATIVE means depleted on cholesterol. `cholesterol_required` is the "
    "authors' own call (96 genes), not a threshold. **`measured` is false for every gene "
    "that tolerates no transposon insertions, which is every in-vitro-essential gene** -- "
    "dprE1, inhA and mmpL3 are all unmeasured here, which is NOT the same as unaffected. "
    "A gene absent from this table was never screened.",
    "conditional_tnseq": "MtbTnDB: TRANSIT resampling over 136 screens, one row per gene per "
    "screen, keyed on (rv_id, screen_id). What each screen WAS is in `tnseq_screens` -- join "
    "it on `screen_id`, this table holds only numbers. `log2fc` NEGATIVE means depleted in "
    "the experimental condition. **Two traps.** (1) `measured` is false where the gene took "
    "no insertions in either condition -- TRANSIT still prints `log2fc` 0.00 and `q_value` "
    "1.0 for those, so filtering on q alone reads 13% of the genome as 'no effect'; always "
    "add `measured`. (2) A value here does NOT mean a fitness effect for an essential gene: "
    "TRANSIT counts TA sites over the whole ORF while Griffin counted 5-80%, so dprE1 and "
    "mmpL3 carry fold changes built on non-disruptive terminal insertions and read `n/a` in "
    "`conditional_fitness`. Join `essentiality` and show the call beside any `log2fc`.",
    "tnseq_screens": "One row per screen in `conditional_tnseq`, keyed on `screen_id`: what "
    "was compared to what, and the authors' own description of the condition "
    "(`condition_class` in_vitro/in_vivo/in_cell, `medium`, `carbon_source`, `stress`, "
    "`mouse_strain`). **27 of the screens are genetic-interaction backgrounds, not "
    "conditions** -- a transposon library in a knockout host, so a hit is an interaction with "
    "that gene and NOT a conditional requirement. Both `interaction_gene` (Rv id) and "
    "`interaction_gene_name` are sparse and sparse independently -- 11 have only the id, 5 "
    "only the name -- so test `COALESCE` of the two or read `description`; filtering on one "
    "field alone silently keeps interaction screens in a condition query. **`annotated` is false "
    "for 72 of the 136**, where the authors' table names the screen differently and the atlas "
    "will not guess: a NULL `condition_class` means NOT RECORDED, never 'in vitro'. "
    "**SCREENS ARE NOT INDEPENDENT -- never count them as evidence weight.** Group by "
    "`study`: 61 of the 136 are single mouse strains from one host-genetics panel, and the "
    "1,833 strain-against-strain comparisons in the source are deliberately not ingested. "
    "`cross_study` means the control library came from a different study than the "
    "experimental data, a batch-effect caveat the authors raise themselves.",
    "vulnerability": "CRISPRi in H37Rv, the lab strain.`vulnerability_index` is NEGATIVE: "
    "more negative is more vulnerable. Only rows with `certain` are confident estimates.",
    "strain_vulnerability": "The SAME CRISPRi series in HN878, a Beijing-lineage CLINICAL "
    "isolate, one row per gene. H37Rv is not in here -- it is in `vulnerability`, so a "
    "strain comparison is a join on rv_id. `delta_vi` is the authors' own and runs HN878 "
    "MINUS H37Rv, so POSITIVE means LESS vulnerable in the clinical strain (accD6: -11.5 "
    "in H37Rv, -2.3 in HN878, delta +9.2, confident in both). `delta_vi_norm` is not a "
    "rescaling and can disagree in sign with `delta_vi`. The delta is reported for only "
    "507 genes, a subset the authors chose of the 576 confident in both; NULL there means "
    "no difference was reported, NOT a difference of zero, and "
    "`differential_reported` says which. A gene absent from this table was never measured "
    "in HN878. M. smegmatis is in the same supplement and deliberately NOT ingested.",
    "resistance": "WHO catalogue, keyed on GENE SYMBOL not Rv tag, and only 65 genes "
    "are in it. `associated` marks graded 1 or 2. `residue_position` is null "
    "for promoter, frameshift and stop variants. `drug` uses WHO's names, which are NOT "
    "ChEMBL's (Rifampicin vs RIFAMPIN, Levofloxacin vs LEVOFLOXACIN ANHYDROUS), so join a "
    "drug to a gene through drug_genes WHERE link = 'who_resistance', never on the name.",
    "interactions": "STRING, combined_score >= 700, one row per unordered pair. "
    "A gene appears as rv_id OR partner_rv_id -- check both.",
    "homology": "Human anti-target check: phmmer of each Mtb protein against the reviewed "
    "human proteome, keyed on uniprot_acc. `identity` is a FRACTION (0.48 = 48%); "
    "`close_human_homolog` means identity >= 0.30, a convention of this atlas.",
    "paralogs": "Functional redundancy: phmmer of each Mtb protein against the Mtb "
    "proteome itself, keyed on uniprot_acc. Answers 'could a second copy cover for this "
    "target', which no other table does. **The `close_paralog` flag needs identity >= 0.30 "
    "AND coverage >= 0.70, deliberately stricter than `close_human_homolog`, which flags "
    "on identity alone.** The questions differ: a shared domain is already a selectivity "
    "worry for an off-target, but a backup copy has to be the same protein, not share a "
    "piece of it. Identity alone would call 2,009 genes redundant including dprE1 (30.8% "
    "over 37% of the protein) and mmpL3 (31.7% over 21%), neither of which has a backup. "
    "**Two different 'closest' columns.** `closest_close_gene` is the nearest BACKUP and is "
    "NULL when there is none, even though relatives exist; `closest_gene` is the nearest "
    "RELATIVE, ranked by bitscore rather than identity so that a short exact fragment does "
    "not outrank a full-length near-copy. Self-hits are dropped, and so are pairs of loci "
    "filing the identical sequence under two accessions -- those are in "
    "crosswalk.shared_accession and are identity collapse, not paralogy. `identity` and "
    "`coverage` are FRACTIONS.",
    "orthologue_structures": "A structure to work from that is NOT of this protein: phmmer "
    "of each Mtb protein against the 895 Mycobacteriaceae proteins (excluding H37Rv) that "
    "have a PDB entry, joined to those entries. **Keyed on uniprot_acc for the Mtb side and "
    "via_acc for the neighbour; one row per (Mtb protein, neighbour's PDB entry), so count "
    "DISTINCT pdb_id, not rows.** These entries are NOT in the `structures` table and must "
    "never be added to `n_pdb`: that column answers 'has this protein been solved' and a "
    "borrowed structure does not make it true. **`relation` carries two claims of very "
    "different strength.** `same_sequence` means the deposited sequence is identical to the "
    "Mtb one and merely filed under another accession (CDC 1551, H37Ra, M. bovis) -- the "
    "structure IS of this protein, and 34 genes the atlas calls structure-less have one. "
    "`orthologue` means a related mycobacterial protein, mostly M. smegmatis, down to the "
    "floor of 30% identity over 70% of the query. `identity` and `coverage` are FRACTIONS "
    "and belong in any answer: whether a 34%-identical structure is useful is the reader's "
    "judgement, and this table makes no modelling claim. `n_ligands` counts only ligands on "
    "the neighbour's own chains, the same chain-level rule as `structures`.",
    "drug_precedent": "Has a drug ever been filed against this FOLD? Every ChEMBL "
    "drug-target mechanism, keyed on the Pfam domain of the protein it acts on, restricted "
    "to the 325 domains Mtb proteins carry. **There is no rv_id: join through "
    "proteins.pfam_ids** -- `FROM proteins p, UNNEST(p.pfam_ids) AS d(pfam_id) JOIN "
    "drug_precedent USING (pfam_id)` -- and **exclude rows where `accession` is the gene's "
    "own accession**, or a gene becomes its own precedent (dprE1's only PF04030 compounds "
    "are macozinone and TBA-7371, against dprE1). `target_summary.n_precedent_approved` is "
    "that roll-up already done. **This is NOT a druggability score and nothing in the store "
    "is** -- it counts database records, not pockets. `max_phase` is 4 for approved, 1-3 "
    "clinical, -1 means ChEMBL does not know (neither approved nor clinical). "
    "**A shared domain is not a shared binding site**, so an answer needs the domain name "
    "and how broadly it is shared: `target_summary.precedent_domain_genes` is how many Mtb "
    "genes carry it (37 for PF00005 ABC transporter, 1 for the median domain). 39% of rows "
    "are human targets (tax_id 9606), where tractable chemistry and a selectivity problem "
    "are the same fact -- `n_precedent_human_target` counts those. One row per (pfam_id, "
    "mec_id, accession), so count DISTINCT molecule_chembl_id, not rows.",
    "drugs": "One row per ChEMBL parent molecule with a TUBERCULOSIS indication. "
    "`pref_name` is UPPER CASE ('ISONIAZID'), so match case-insensitively. "
    "`max_phase_tb` is the highest phase for TB; `max_phase` is for ANY indication, so an "
    "approved antibiotic can be phase 2 for TB. The set is ChEMBL's, unedited: it includes "
    "host-directed adjuncts, HIV co-medications, vaccines and placebo excipients -- filter "
    "on `acts_on_mtb`, `host_targeted` or `atc_codes` (J04 = antimycobacterials).",
    "drug_mechanisms": "ChEMBL mechanism of action per drug. `target_organism` is often NOT "
    "Mtb (rifampicin's target is a generic bacterial RNA polymerase built from E. coli "
    "proteins). Gene links are in drug_genes.",
    "ligands": "One row per PDB chemical component id (the three-character codes in "
    "structures.ligand_ids), with the InChIKey and RCSB's ChEMBL cross-reference that "
    "identify the same molecule in `compounds` or `drugs`. `role` is ligand | cofactor | "
    "incidental, the same rule the structures table uses.",
    "drug_genes": "Drug to Rv tag. `link`: mechanism = ChEMBL names this gene's protein as "
    "the single-protein target; mechanism_complex = ChEMBL names a complex the protein "
    "belongs to (bedaquiline -> all 8 ATP synthase subunits), not evidence it binds this "
    "subunit; bosch_2021 = Bosch 2021's own drug annotation, exact name match; "
    "who_resistance = WHO-graded resistance variants in this gene for this drug, which is "
    "NOT target engagement (katG activates isoniazid); structure = the drug is modelled on "
    "this protein's own chain in a PDB entry (`source_text` lists them), which is physical "
    "evidence that the two meet but still not a mechanism claim -- EthR binds many ligands "
    "in soaking studies. Drugs acting on a gene: link IN ('mechanism', 'bosch_2021').",
    "trials": "ClinicalTrials.gov interventional studies for condition 'tuberculosis', "
    "including vaccine, diagnostic and behavioural studies. `phase_max` is numeric "
    "(0.5 = early phase 1 ... 4); NULL means phase not applicable. Dates may be partial "
    "(YYYY-MM).",
    "trial_drugs": "Trial to drug. `via_chembl_ref` = ChEMBL's curated trial reference; "
    "`via_intervention_name` = exact match of an intervention name to a ChEMBL synonym. "
    "A trial with no row here may still have tested a drug under a name nothing matched.",
}

SYSTEM = """You answer questions about Mycobacterium tuberculosis H37Rv drug targets \
by querying the Mtb Target Atlas, a store built only from public data.

Always query. Never answer from memory: your own knowledge of TB biology is useful \
for framing a question but is not a source, and the user is asking what *this store* \
says. Call `describe_store` first if you are unsure of a column.

Cite records. Every factual claim names the identifiers it rests on -- Rv tags, PDB \
ids, ChEMBL ids, variant names -- so the user can check it. Give the numbers you \
actually retrieved rather than rounding them into prose.

An absence is an answer. A gene with no ChEMBL activity, no structure or no WHO \
variant is a real finding, often the interesting one; say so plainly and say which \
source was checked. Never let a missing row read as a zero measurement, and never \
fill a gap from a different source without saying you did.

Respect the evidence levels, because they are not interchangeable:
- ChEMBL `evidence`: `direct` is an Mtb protein target; `orthologue` is another \
mycobacterial protein reached through a UniRef cluster, which is a family-level link \
and not evidence of a shared binding site; `whole_cell` is a MIC against the whole \
organism and says nothing on its own about which protein is engaged.
- Conditional fitness (Griffin 2011) adds growth on cholesterol, the carbon source Mtb \
uses inside a macrophage. A transposon screen cannot measure a gene with no insertions, \
so an essential gene is `measured = false` there -- unmeasured, not unaffected.
- Essentiality is one in vitro condition (7H9 broth). Vulnerability is CRISPRi \
knockdown and answers a different question -- how far expression must fall before \
fitness suffers -- on a negative scale, and only `certain` rows are confident.
- Human homology is a phmmer search against the reviewed human proteome, reported as \
an E-value and a percent identity; the 30% "close" line is this atlas's convention.
- A ligand counts for a protein only when it is modelled on that protein's own chains; \
one bound to a neighbouring subunit is in `ligand_ids_elsewhere`, shown and not counted.
- The WHO catalogue covers 65 genes. For every other gene the correct statement is \
"not in the catalogue", never "no resistance known".
- Drugs: `max_phase_tb` is the phase for tuberculosis, not for any indication. A drug \
reaches a gene through ChEMBL's mechanism (a single protein, or a complex the protein \
belongs to -- membership is not binding), Bosch 2021's annotation, a co-crystal structure, \
or WHO-graded resistance. Resistance is not engagement: katG activates isoniazid and \
Rv0678 is a regulator. A co-crystal is physical evidence the two meet, not a mechanism. \
Say which link an answer rests on.
- Trials link to drugs through ChEMBL's own trial references or an exact \
intervention-name match. An unlinked trial may still have tested a drug.

Be concise and quantitative. Prefer a short table to a paragraph when the answer is \
a list of genes."""


@dataclass
class ToolCall:
    """What the agent did, surfaced so an answer can be audited rather than trusted."""

    name: str
    input: dict[str, Any]
    rows: int | None = None
    error: str | None = None
    result: Any = None


@dataclass
class Answer:
    text: str
    calls: list[ToolCall] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)


_connection: duckdb.DuckDBPyConnection | None = None

SELECT_ONLY = re.compile(r"^\s*(with|select)\b", re.IGNORECASE)
FORBIDDEN = re.compile(
    r"\b(attach|copy|install|load|export|import|create|insert|update|delete|drop|alter|"
    r"pragma|set|call|read_csv|read_parquet|read_json|glob)\b",
    re.IGNORECASE,
)


def connection() -> duckdb.DuckDBPyConnection:
    """An in-memory copy of the store with external access locked off."""
    global _connection
    if _connection is not None:
        return _connection
    con = duckdb.connect(":memory:")
    for name in TABLES:
        path = STORE / f"{name}.parquet"
        if path.exists():
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM '{path}'")
    # After this the model's SQL cannot touch the filesystem or the network, and
    # cannot turn that back on.
    con.execute("SET enable_external_access=false")
    con.execute("SET lock_configuration=true")
    _connection = con
    return con


def available_tables() -> list[str]:
    con = connection()
    return [row[0] for row in con.execute("SHOW TABLES").fetchall()]


def describe() -> str:
    """Schema, row counts, provenance and the per-table gotchas, as text."""
    con = connection()
    lines = []
    for name in available_tables():
        count = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        columns = con.execute(f"DESCRIBE {name}").fetchall()
        try:
            version, retrieved = provenance(name)
        except Exception:  # noqa: BLE001 - provenance is nice to have, not required
            version, retrieved = "unknown", "unknown"
        lines.append(f"## {name} ({count:,} rows) -- {version}, retrieved {retrieved}")
        if name in TABLE_NOTES:
            lines.append(f"NOTE: {TABLE_NOTES[name]}")
        lines.append(", ".join(f"{c[0]} {c[1]}" for c in columns))
        lines.append("")
    return "\n".join(lines)


def run_sql(sql: str, limit: int = MAX_ROWS) -> dict[str, Any]:
    """One read-only SELECT against the store."""
    statement = sql.strip().rstrip(";")
    if ";" in statement:
        raise ValueError("one statement at a time, please")
    if not SELECT_ONLY.match(statement):
        raise ValueError("only SELECT and WITH queries are allowed")
    if FORBIDDEN.search(statement):
        raise ValueError("that statement uses a keyword this tool does not allow")

    capped = min(limit, MAX_ROWS)
    result = connection().execute(f"SELECT * FROM ({statement}) LIMIT {capped}")
    columns = [c[0] for c in result.description]
    rows = [
        {c: (str(v) if hasattr(v, "isoformat") else v) for c, v in zip(columns, row, strict=True)}
        for row in result.fetchall()
    ]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": len(rows) == capped,
    }


def ask(question: str, *, model: str = MODEL, effort: str = "high") -> Answer:
    """Answer one question, returning the tool calls that produced it."""
    import anthropic
    from anthropic import beta_tool

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise RuntimeError(
            "No Anthropic credentials. Set ANTHROPIC_API_KEY, or run `ant auth login`."
        )

    calls: list[ToolCall] = []

    @beta_tool
    def describe_store() -> str:
        """Every table in the atlas: row counts, columns, source versions, and the
        traps in each one. Call this before writing a query you are unsure about.
        """
        calls.append(ToolCall(name="describe_store", input={}))
        return describe()

    @beta_tool
    def query_store(sql: str) -> str:
        """Run one read-only SQL SELECT against the atlas and return the rows as JSON.

        DuckDB syntax. One statement, no semicolons, SELECT or WITH only. Results
        are capped at 200 rows, so aggregate or filter rather than dumping a table.

        Args:
            sql: The SELECT statement to run.
        """
        call = ToolCall(name="query_store", input={"sql": sql})
        calls.append(call)
        try:
            payload = run_sql(sql)
        except Exception as error:  # noqa: BLE001 - the model should see and fix its own SQL
            call.error = str(error)
            return f"ERROR: {error}"
        call.rows = payload["row_count"]
        call.result = payload["rows"][:20]
        return json.dumps(payload, default=str)

    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": effort},
        tools=[describe_store, query_store],
        messages=[{"role": "user", "content": question}],
    )

    text = ""
    for turn, message in enumerate(runner, 1):
        for block in message.content:
            if block.type == "text" and block.text.strip():
                text = block.text
        if turn >= MAX_TURNS:
            break

    sources = {}
    for name in available_tables():
        try:
            version, _ = provenance(name)
            sources[name] = str(version)
        except Exception:  # noqa: BLE001
            continue
    return Answer(text=text, calls=calls, sources=sources)
