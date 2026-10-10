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
    "resistance",
    "vulnerability",
    "interactions",
    "homology",
    "chembl_targets",
    "drugs",
    "drug_mechanisms",
    "drug_genes",
    "trials",
    "trial_drugs",
)

# One line per table: what a question should reach for, and the trap in it.
TABLE_NOTES = {
    "target_summary": "START HERE. One row per gene, every evidence table rolled up. "
    "Scalar columns for filtering and sorting.",
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
    "`ligand_ids` excludes cofactors and crystallisation additives.",
    "predicted_structures": "AlphaFold, keyed on uniprot_acc.",
    "activities": "ChEMBL bioactivity. `evidence` is direct | orthologue | whole_cell. "
    "Join to a gene through crosswalk.chembl_targets or target_summary.",
    "compounds": "One row per compound, with properties. Keyed on molecule_chembl_id.",
    "essentiality": "TnSeq calls, one in vitro condition. `essential` is ES or ESD; "
    "`fitness_cost` also includes growth-defect.",
    "vulnerability": "CRISPRi. `vulnerability_index` is NEGATIVE: more negative is more "
    "vulnerable. Only rows with `certain` are confident estimates.",
    "resistance": "WHO catalogue, keyed on GENE SYMBOL not Rv tag, and only 65 genes "
    "are in it. `associated` marks graded 1 or 2. `residue_position` is null "
    "for promoter, frameshift and stop variants.",
    "interactions": "STRING, combined_score >= 700, one row per unordered pair. "
    "A gene appears as rv_id OR partner_rv_id -- check both.",
    "homology": "Human anti-target check: phmmer of each Mtb protein against the reviewed "
    "human proteome, keyed on uniprot_acc. `identity` is a FRACTION (0.48 = 48%); "
    "`close_human_homolog` means identity >= 0.30, a convention of this atlas.",
    "drugs": "One row per ChEMBL parent molecule with a TUBERCULOSIS indication. "
    "`max_phase_tb` is the highest phase for TB; `max_phase` is for ANY indication, so an "
    "approved antibiotic can be phase 2 for TB. The set is ChEMBL's, unedited: it includes "
    "host-directed adjuncts, HIV co-medications, vaccines and placebo excipients -- filter "
    "on `acts_on_mtb`, `host_targeted` or `atc_codes` (J04 = antimycobacterials).",
    "drug_mechanisms": "ChEMBL mechanism of action per drug. `target_organism` is often NOT "
    "Mtb (rifampicin's target is a generic bacterial RNA polymerase built from E. coli "
    "proteins). Gene links are in drug_genes.",
    "drug_genes": "Drug to Rv tag. `link`: mechanism = ChEMBL names this gene's protein as "
    "the single-protein target; mechanism_complex = ChEMBL names a complex the protein "
    "belongs to (bedaquiline -> all 8 ATP synthase subunits), not evidence it binds this "
    "subunit; bosch_2021 = Bosch 2021's own drug annotation, exact name match; "
    "who_resistance = WHO-graded resistance variants in this gene for this drug, which is "
    "NOT target engagement (katG activates isoniazid). Drugs acting on a gene: "
    "link IN ('mechanism', 'bosch_2021').",
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
- Essentiality is one in vitro condition (7H9 broth). Vulnerability is CRISPRi \
knockdown and answers a different question -- how far expression must fall before \
fitness suffers -- on a negative scale, and only `certain` rows are confident.
- Human homology is a phmmer search against the reviewed human proteome, reported as \
an E-value and a percent identity; the 30% "close" line is this atlas's convention.
- The WHO catalogue covers 65 genes. For every other gene the correct statement is \
"not in the catalogue", never "no resistance known".
- Drugs: `max_phase_tb` is the phase for tuberculosis, not for any indication. A drug \
reaches a gene through ChEMBL's mechanism (a single protein, or a complex the protein \
belongs to -- membership is not binding), Bosch 2021's annotation, or WHO-graded \
resistance. Resistance is not engagement: katG activates isoniazid and Rv0678 is a \
regulator. Say which link an answer rests on.
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
