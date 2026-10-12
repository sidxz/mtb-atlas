/** Filter and compare H37Rv protein targets. */
import { Children, createContext, isValidElement, useContext, useEffect, useMemo, useRef, useState } from "react";
import { FilterRail } from "./FilterRail";
import { InterfaceIcon } from "./InterfaceIcon";
import { ProteinAssays } from "./ProteinAssays";

import type { TargetSummary, ValidationStatus } from "./api";

const STATUS_ORDER: ValidationStatus[] = [
  "clinically_validated",
  "clinical_stage",
  "biochemically_interrogated",
  "annotated_target",
  "screened",
  "genetically_nominated",
  "not_interrogated",
];

const STATUS_LABEL: Record<ValidationStatus, string> = {
  clinically_validated: "Clinically validated",
  clinical_stage: "Clinical stage",
  biochemically_interrogated: "Protein assays",
  annotated_target: "Annotated target",
  screened: "Screened",
  genetically_nominated: "Genetically nominated",
  not_interrogated: "Not interrogated",
};

const STATUS_BASIS: Record<ValidationStatus, string> = {
  clinically_validated: "An approved drug is recorded against this protein.",
  clinical_stage: "A compound in clinical development is recorded against this protein.",
  biochemically_interrogated: "A ChEMBL assay is recorded against this protein as a single-protein target.",
  annotated_target: "A ChEMBL target exists for this protein, with no assay recorded against it.",
  screened: "A screening campaign reaches this protein, with no assay recorded against it.",
  genetically_nominated: "Essential or confidently vulnerable, with no chemical record.",
  not_interrogated: "No chemical or genetic record in these sources reaches this locus.",
};

type Verdict = "y" | "n" | "r";

interface Criterion {
  id: string;
  label: string;
  hint?: string;
  verdict: (row: TargetSummary) => Verdict;
}

/**
 * Missing evidence stays separate from a negative result.
 */
const CRITERIA: Criterion[] = [
  {
    id: "essential",
    label: "Essential (ES or ESD)",
    verdict: r => (r.essentiality == null ? "r" : r.essentiality_essential ? "y" : "n"),
  },
  {
    id: "vulnerable",
    label: "Confident vulnerability",
    verdict: r => (r.vulnerability_index == null ? "r" : r.vulnerability_certain ? "y" : "n"),
  },
  {
    id: "strain",
    label: "HN878 strain comparison",
    hint: "A vulnerability difference between HN878 and H37Rv is reported.",
    verdict: r => (r.hn878_delta_vi == null ? "r" : "y"),
  },
  {
    id: "cholesterol",
    label: "Assessable on cholesterol",
    verdict: r => (r.cholesterol_measured == null ? "r" : r.cholesterol_measured ? "y" : "n"),
  },
  {
    id: "structure",
    label: "Experimental structure",
    verdict: r => (r.has_structure ? "y" : "n"),
  },
  {
    id: "orthologue",
    label: "Mycobacterial orthologue structure",
    verdict: r => (r.n_orthologue_pdb > 0 ? "y" : "n"),
  },
  {
    id: "human",
    label: "No close human homologue",
    hint: "No human homologue at 30% sequence identity.",
    verdict: r => (r.close_human_homolog ? "n" : "y"),
  },
  {
    id: "paralog",
    label: "No close paralogue",
    hint: "No paralogue at 30% identity over 70% of the query sequence.",
    verdict: r => (r.close_paralog ? "n" : "y"),
  },
  {
    id: "assay",
    label: "Purified-protein assay",
    verdict: r => (r.n_protein_assays > 0 ? "y" : "n"),
  },
  {
    id: "chembl",
    label: "ChEMBL target",
    verdict: r => (r.n_chembl_targets > 0 ? "y" : "n"),
  },
  {
    id: "precedent",
    label: "Approved drug for Pfam domain",
    verdict: r => (r.n_precedent_approved == null ? "r" : r.n_precedent_approved > 0 ? "y" : "n"),
  },
  {
    id: "who",
    label: "WHO resistance catalogue",
    verdict: r => (r.in_who_catalogue ? "y" : "n"),
  },
];

const FILTER_GROUPS = [
  { label: "Genetic evidence", ids: ["essential", "vulnerable", "strain", "cholesterol"] },
  { label: "Structure & selectivity", ids: ["structure", "orthologue", "human", "paralog"] },
  { label: "Chemical evidence", ids: ["assay", "chembl", "precedent", "who"] },
];
const PAGE_SIZE = 50;
const COLUMNS = [
  { key: "rv_id", label: "Target", hint: "Sort by locus ID" },
  { key: "validation_status", label: "Validation" },
  { key: "essentiality", label: "Essentiality" },
  { key: "vulnerability_index", label: "VI", hint: "H37Rv vulnerability index", numeric: true },
  { key: "n_pdb", label: "PDB", hint: "Experimental structures of this protein", numeric: true },
  { key: "n_protein_assays", label: "Assays", hint: "Assays against the purified protein", numeric: true },
  { key: "n_compounds", label: "Compounds", hint: "Compounds with protein-level potency", numeric: true },
] satisfies { key: keyof TargetSummary; label: string; hint?: string; numeric?: boolean }[];
type SortKey = (typeof COLUMNS)[number]["key"];

const VERDICTS: [Verdict, string][] = [["y", "Yes"], ["n", "No"], ["r", "No record"]];

const n0 = (v: number | null | undefined) => (v == null ? null : v.toLocaleString());
const f1 = (v: number | null | undefined) => (v == null ? null : v.toFixed(1));
const f2 = (v: number | null | undefined) => (v == null ? null : v.toFixed(2));
const pct = (v: number | null | undefined) => (v == null ? null : `${Math.round(v * 100)}%`);

const HighlightedCriteria = createContext<ReadonlySet<string>>(new Set());
type ProfileTab = "overview" | "assays";

/** Missing values stay distinct from zero, including highlighted filter matches. */
function Row({ label, value, criterion, onClick }: { label: string; value: string | null; criterion?: string; onClick?: () => void }) {
  const highlighted = useContext(HighlightedCriteria);
  const match = criterion != null && highlighted.has(criterion);
  return (
    <div className={`assess-row${match ? " filter-match" : ""}`}>
      <div className="k">{label}{match && <span className="sr-only"> (selected filter)</span>}</div>
      <div className={value == null ? "v none" : "v"}>
        {onClick ? <button type="button" className="assess-value-link" onClick={onClick} aria-label={`View ${value} protein assays`}>{value} <span aria-hidden="true">→</span></button> : value ?? "no record"}
      </div>
    </div>
  );
}

function Dimension({ title, basis, criteria = [], children }: { title: string; basis: string; criteria?: string[]; children: React.ReactNode }) {
  const highlighted = useContext(HighlightedCriteria);
  const match = criteria.some(id => highlighted.has(id));
  return (
    <section className={`assess-dim${match ? " filter-match-section" : ""}`}>
      <h4>{title}{match && <span className="assess-filter-label">Selected filter</span>}</h4>
      <div className="assess-kv">{children}</div>
      <details className="assess-methods"><summary>Source &amp; method</summary><p>{basis}</p></details>
    </section>
  );
}

function ProfileEvidence({ children }: { children: React.ReactNode }) {
  const highlighted = useContext(HighlightedCriteria);
  const matches = (child: React.ReactNode) => isValidElement<{ criteria?: string[] }>(child) && child.props.criteria?.some(id => highlighted.has(id)) ? 1 : 0;
  return <>{Children.toArray(children).sort((a, b) => matches(b) - matches(a))}</>;
}

function Profile({ row, onOpenGene, picks, statusFilter, tab, onTab }: {
  row: TargetSummary;
  onOpenGene: (rv: string) => void;
  picks: Record<string, Verdict>;
  statusFilter: ValidationStatus | null;
  tab: ProfileTab;
  onTab: (tab: ProfileTab) => void;
}) {
  const highlighted = new Set(Object.keys(picks));
  if (statusFilter === "biochemically_interrogated") highlighted.add("assay");
  if (statusFilter === "annotated_target") highlighted.add("chembl");
  if (statusFilter === "screened") highlighted.add("screen");
  if (statusFilter === "clinically_validated" || statusFilter === "clinical_stage") highlighted.add("drug");
  if (statusFilter === "genetically_nominated") {
    if (row.essentiality_essential) highlighted.add("essential");
    if (row.vulnerability_certain) highlighted.add("vulnerable");
  }
  const status = row.validation_status;
  return (
    <HighlightedCriteria.Provider value={highlighted}>
    <div className="assess-profile">
      <div className="assess-profile-head">
        <div>
          <h3>{row.gene_name ?? row.rv_id}</h3>
          {row.gene_name && row.gene_name !== row.rv_id && <span className="assess-note">{row.rv_id}</span>}
          <p className="assess-product">{row.product}</p>
        </div>
        <button type="button" className="rowbtn" onClick={() => onOpenGene(row.rv_id)}>
          Open gene record
        </button>
      </div>
      {status ? (
        <p className={`assess-status-line${statusFilter ? " filter-match" : ""}`}>
          <span className="chip accent" title={STATUS_BASIS[status]}>{STATUS_LABEL[status]}</span>
          {statusFilter && <span className="assess-filter-label">Selected filter</span>}
        </p>
      ) : (
        <p className="assess-basis">
          Validation status unavailable.
        </p>
      )}
      {row.shared_accession && (
        <p className="assess-caveat">
          Shared UniProt accession: structure, ligand and homology evidence may apply to multiple loci.
        </p>
      )}

      <div className="tabs assess-profile-tabs" role="group" aria-label="Target profile views">
        <button type="button" aria-pressed={tab === "overview"} onClick={() => onTab("overview")}>Overview</button>
        <button type="button" aria-pressed={tab === "assays"} onClick={() => onTab("assays")}>Protein assays <span className="badge">{row.n_protein_assays}</span></button>
      </div>
      {tab === "assays" ? <ProteinAssays key={row.rv_id} rvId={row.rv_id} /> : <ProfileEvidence>
      <Dimension
        title="Genetic validation"
        criteria={["essential", "vulnerable", "strain"]}
        basis="Essentiality: DeJesus 2017 (TnSeq); ES and ESD count as essential. Vulnerability: Bosch 2021 (CRISPRi); more negative values indicate greater vulnerability. A positive HN878 difference indicates reduced vulnerability in that strain."
      >
        <Row label="Essentiality call" criterion="essential" value={row.essentiality_label ?? row.essentiality} />
        <Row
          label="Fitness cost on disruption"
          value={row.essentiality_fitness_cost ? "yes" : "no"}
        />
        <Row label="Vulnerability index, H37Rv" criterion="vulnerable" value={f2(row.vulnerability_index)} />
        <Row
          label="Confident measurement" criterion="vulnerable"
          value={row.vulnerability_index == null ? null : row.vulnerability_certain ? "yes" : "no"}
        />
        <Row label="Vulnerability index, HN878" criterion="strain" value={f2(row.hn878_vulnerability_index)} />
        <Row
          label="HN878 minus H37Rv" criterion="strain"
          value={row.hn878_delta_vi == null ? null : `${row.hn878_delta_vi > 0 ? "+" : ""}${row.hn878_delta_vi.toFixed(2)}`}
        />
      </Dimension>

      <Dimension
        title="Conditional essentiality"
        criteria={["cholesterol"]}
        basis="Fitness with cholesterol as the sole carbon source (Griffin 2011). Transposon screens cannot assess loci that take no insertions; those loci are reported as unmeasured rather than unaffected."
      >
        <Row
          label="Assessable in the screen" criterion="cholesterol"
          value={row.cholesterol_measured == null ? null : row.cholesterol_measured ? "yes" : "no insertions"}
        />
        <Row
          label="Required on cholesterol"
          value={row.cholesterol_required == null ? null : row.cholesterol_required ? "yes" : "no"}
        />
        <Row label="log2 ratio" value={f2(row.cholesterol_log2_ratio)} />
        <Row
          label="Distinct whole-cell conditions"
          value={row.whole_cell_conditions.length ? String(row.whole_cell_conditions.length) : null}
        />
      </Dimension>

      <Dimension
        title="Target engagement"
        criteria={["assay", "chembl", "who"]}
        basis="ChEMBL assays recorded against this protein as a single-protein target; assays filed against complexes containing it are reported separately. Resistance variants are those graded as associated with resistance in the WHO mutation catalogue, 2nd edition."
      >
        <Row label="ChEMBL targets" criterion="chembl" value={n0(row.n_chembl_targets)} />
        <Row label="Evidence class" value={row.chembl_evidence} />
        <Row label="Protein assays" criterion="assay" onClick={() => onTab("assays")} value={n0(row.n_protein_assays)} />
        <Row label="Largest assay (compounds)" value={n0(row.max_assay_compounds)} />
        <Row label="Assays against complexes" value={n0(row.n_complex_assays)} />
        <Row label="In the WHO catalogue" criterion="who" value={row.in_who_catalogue ? "yes" : "no"} />
        <Row label="Variants graded associated" value={n0(row.n_variants_associated)} />
      </Dimension>

      <Dimension
        title="Structural tractability"
        criteria={["structure", "orthologue"]}
        basis="Experimental structures deposited under this protein's own accession, and structures of mycobacterial orthologues reported with sequence identity and coverage. Orthologue residue numbering follows the orthologue, not this protein."
      >
        <Row label="Structures of this protein" criterion="structure" value={n0(row.n_pdb)} />
        <Row label="Best resolution" value={row.best_resolution == null ? null : `${row.best_resolution.toFixed(2)} Å`} />
        <Row label="With a bound ligand" value={n0(row.n_pdb_with_ligand)} />
        <Row
          label="Identical sequence under another accession"
          value={row.same_sequence_structure ? "yes" : "no"}
        />
        <Row label="Orthologue structures" criterion="orthologue" value={n0(row.n_orthologue_pdb)} />
        <Row
          label="Nearest solved orthologue"
          value={row.closest_orthologue_gene ? `${row.closest_orthologue_gene} · ${row.closest_orthologue_organism ?? "organism not stated"}` : null}
        />
        <Row
          label="Its identity and coverage"
          value={row.closest_orthologue_identity == null ? null : `${pct(row.closest_orthologue_identity)} over ${pct(row.closest_orthologue_coverage) ?? "?"}`}
        />
        <Row
          label="Predicted model"
          value={row.has_predicted ? `AlphaFold, mean pLDDT ${f1(row.plddt_mean) ?? "not stated"}` : "none"}
        />
      </Dimension>

      <Dimension
        title="Chemical matter"
        criteria={["screen"]}
        basis="Protein potency: pChEMBL. Whole-cell potency: pMIC (−log10 MIC in mol/L). Censored MICs are excluded from pMIC. Campaign sizes count deposited compounds."
      >
        <Row label="Compounds with protein-level potency" value={n0(row.n_compounds)} />
        <Row label="Best pChEMBL" value={f2(row.best_pchembl)} />
        <Row label="Whole-cell measurements" value={n0(row.n_whole_cell)} />
        <Row label="Best pMIC" value={f2(row.best_pmic)} />
        <Row
          label="MICs, of which censored"
          value={`${n0(row.n_mic)} of which ${n0(row.n_mic_censored)}`}
        />
        <Row label="Campaigns on this protein" criterion="screen" value={n0(row.n_target_screens)} />
        <Row label="Largest campaign, compounds" value={n0(row.max_screen_compounds)} />
        <Row label="Compounds called active" value={n0(row.n_screen_actives)} />
      </Dimension>

      <Dimension
        title="Liabilities"
        criteria={["human", "paralog", "precedent"]}
        basis="Human homologues from phmmer against the reviewed human proteome; paralogues from phmmer against the Mtb proteome, called at 30% identity over 70% of the query length. Drug precedent counts approved drugs recorded against other single-protein targets that share a Pfam domain with this protein; a shared domain is not a shared binding site."
      >
        <Row
          label="Closest human homologue" criterion="human"
          value={row.human_homolog_gene ? `${row.human_homolog_gene} · ${pct(row.human_homolog_identity)}` : row.human_homolog ? "unnamed" : "none above threshold"}
        />
        <Row
          label="Closest paralogue" criterion="paralog"
          value={row.closest_paralog_gene ? `${row.closest_paralog_gene} · ${pct(row.closest_paralog_identity)}` : "none"}
        />
        <Row
          label="Nearest relative, any coverage"
          value={row.nearest_relative_gene ? `${row.nearest_relative_gene} · ${pct(row.nearest_relative_identity)}` : null}
        />
        <Row label="Approved drugs against the domain" criterion="precedent" value={n0(row.n_precedent_approved)} />
        <Row label="Acting on a human protein" value={n0(row.n_precedent_human_target)} />
        <Row label="Complex-only records (excluded)" value={n0(row.n_precedent_complex)} />
        <Row label="Domain carrying the precedent" value={row.precedent_pfam_name} />
      </Dimension>

      {row.drug_names && row.drug_names.length > 0 && (
        <Dimension
          title="Drugs"
          criteria={["drug"]}
          basis="ChEMBL single-protein mechanisms or annotations matched to ChEMBL synonyms. Complex membership and resistance alone do not establish target engagement."
        >
          <Row label="Drugs" criterion="drug" value={row.drug_names.join(", ")} />
          <Row
            label="Highest phase for a TB indication" criterion="drug"
            value={row.best_drug_phase == null ? null : `phase ${row.best_drug_phase}`}
          />
          <Row label="Interventional trials" value={n0(row.n_trials)} />
        </Dimension>
      )}
      </ProfileEvidence>}
    </div>
    </HighlightedCriteria.Provider>
  );
}

export function Targets({
  all,
  onOpenGene,
}: {
  all: TargetSummary[];
  onOpenGene: (rvId: string) => void;
}) {
  const [picks, setPicks] = useState<Record<string, Verdict>>({});
  const [status, setStatus] = useState<ValidationStatus | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [profileTab, setProfileTab] = useState<ProfileTab>("overview");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<{ key: SortKey; descending: boolean }>({ key: "rv_id", descending: false });
  const tableRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const profileRef = useRef<HTMLElement>(null);
  const returnFocus = useRef<HTMLButtonElement | null>(null);

  function closeProfile() {
    setSelected(null);
    requestAnimationFrame(() => returnFocus.current?.focus());
  }

  useEffect(() => {
    if (!selected) return;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeProfile();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);
  useEffect(() => {
    if (profileRef.current) profileRef.current.scrollTop = 0;
  }, [selected, profileTab]);

  // Protein targets exclude noncoding loci.
  const genes = useMemo(() => all.filter(r => r.feature === "CDS"), [all]);

  const searched = useMemo(() => {
    const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return genes.filter(row => {
      const text = `${row.rv_id} ${row.gene_name ?? ""} ${row.product ?? ""} ${row.uniprot_acc ?? ""}`.toLowerCase();
      return terms.every(term => text.includes(term));
    });
  }, [genes, query]);

  const verdicts = useMemo(() => {
    const table = new Map<string, Verdict[]>();
    for (const row of genes) table.set(row.rv_id, CRITERIA.map(c => c.verdict(row)));
    return table;
  }, [genes]);

  const passes = useMemo(
    () => (row: TargetSummary, skip?: string) => {
      const v = verdicts.get(row.rv_id);
      if (!v) return false;
      return CRITERIA.every((c, i) => {
        if (c.id === skip) return true;
        const want = picks[c.id];
        return !want || v[i] === want;
      });
    },
    [verdicts, picks],
  );

  const cohort = useMemo(
    () => searched.filter(r => (status == null || r.validation_status === status) && passes(r)),
    [searched, status, passes],
  );

  // Status counts ignore the status filter itself, so the distribution stays
  // readable while one level is open.
  const statusCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of searched) {
      if (!passes(row)) continue;
      const key = row.validation_status ?? "unknown";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [searched, passes]);


  // Each criterion's counts are taken over the cohort filtered by the others,
  // so the three numbers always sum to a set the reader can act on.
  const criterionCounts = useMemo(
    () =>
      CRITERIA.map((c, i) => {
        const tally: Record<Verdict, number> = { y: 0, n: 0, r: 0 };
        for (const row of searched) {
          if (status != null && row.validation_status !== status) continue;
          if (!passes(row, c.id)) continue;
          const v = verdicts.get(row.rv_id);
          if (v) tally[v[i]] += 1;
        }
        return tally;
      }),
    [searched, status, passes, verdicts],
  );

  // The cohort step by step: what each criterion costs, in the order shown.
  const steps = useMemo(() => {
    const active = CRITERIA.map((c, i) => ({ c, i })).filter(x => picks[x.c.id]);
    const out: { label: string; count: number; drop: number }[] = [];
    let running = searched.filter(r => status == null || r.validation_status === status);
    if (status != null) {
      out.push({ label: STATUS_LABEL[status], count: running.length, drop: searched.length - running.length });
    }
    for (const { c } of active) {
      const want = picks[c.id];
      const before = running.length;
      running = running.filter(r => {
        const v = verdicts.get(r.rv_id);
        return v ? v[CRITERIA.indexOf(c)] === want : false;
      });
      const suffix = want === "y" ? "" : want === "n" ? " — no" : " — no record";
      out.push({ label: c.label + suffix, count: running.length, drop: before - running.length });
    }
    return out;
  }, [searched, status, picks, verdicts]);

  const sorted = useMemo(() => [...cohort].sort((a, b) => {
    const av = a[sort.key], bv = b[sort.key];
    if (av == null) return bv == null ? a.rv_id.localeCompare(b.rv_id) : 1;
    if (bv == null) return -1;
    const comparison = sort.key === "validation_status"
      ? STATUS_ORDER.indexOf(av as ValidationStatus) - STATUS_ORDER.indexOf(bv as ValidationStatus)
      : typeof av === "number" && typeof bv === "number"
        ? av - bv : String(av).localeCompare(String(bv), undefined, { numeric: true });
    return (sort.descending ? -comparison : comparison) || a.rv_id.localeCompare(b.rv_id);
  }), [cohort, sort]);
  const pageCount = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const rows = sorted.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const chosen = selected ? (cohort.find(r => r.rv_id === selected) ?? null) : null;
  const columns = chosen ? COLUMNS.filter(column => ["rv_id", "validation_status", "essentiality", "vulnerability_index", sort.key].includes(column.key)) : COLUMNS;
  const activeCount = Object.keys(picks).length + Number(status != null);
  const active = activeCount > 0 || query.length > 0;

  useEffect(() => {
    setPage(0);
  }, [query, picks, status]);
  useEffect(() => {
    if (selected && !cohort.some(row => row.rv_id === selected)) setSelected(null);
  }, [cohort, selected]);
  useEffect(() => { if (tableRef.current) tableRef.current.scrollTop = 0; }, [currentPage, sort, query, picks, status]);

  function clearFilters() {
    setPicks({});
    setStatus(null);
    setQuery("");
  }
  function removePick(id: string) {
    setPicks(previous => { const next = { ...previous }; delete next[id]; return next; });
  }

  return (
    <div className={`body targets-body${chosen ? " detail-open" : ""}`}>
      <FilterRail label={`Filters${activeCount ? ` (${activeCount})` : ""}`}>
        <div className="assess-rail-head">
          <h2><InterfaceIcon name="filter" /> Filters</h2>
          {active && <button type="button" className="clear-filters" onClick={clearFilters}>Reset</button>}
        </div>
        <div className="targets-status-filter">
          <p className="lab" title="Most advanced record available; stages are not cumulative.">Validation status</p>
          <button type="button" className="assess-stage" aria-pressed={status === null} onClick={() => setStatus(null)}>
            <span>All targets</span><span className="assess-stage-n">{[...statusCounts.values()].reduce((a, b) => a + b, 0).toLocaleString()}</span>
          </button>
          {STATUS_ORDER.map(key => (
            <button key={key} type="button" className="assess-stage" aria-pressed={status === key}
              title={STATUS_BASIS[key]} onClick={() => setStatus(status === key ? null : key)}>
              <span>{STATUS_LABEL[key]}</span><span className="assess-stage-n">{(statusCounts.get(key) ?? 0).toLocaleString()}</span>
            </button>
          ))}
        </div>
        {FILTER_GROUPS.map(group => (
          <details className="filtergroup targets-filter-group" key={group.label} open>
            <summary>{group.label}{group.ids.some(id => picks[id]) && <span className="filtercount">{group.ids.filter(id => picks[id]).length}</span>}</summary>
            {CRITERIA.map((c, i) => group.ids.includes(c.id) && (
              <div className="assess-crit" key={c.id}>
                <span className="assess-crit-label" title={c.hint}>{c.label}</span>
                <div className="assess-seg" role="group" aria-label={c.label}>
                  {VERDICTS.map(([key, label]) => (
                    <button key={key} type="button" aria-pressed={picks[c.id] === key}
                      aria-label={`${c.label}: ${label} (${criterionCounts[i][key].toLocaleString()})`}
                      onClick={() => setPicks(previous => {
                        const next = { ...previous };
                        if (next[c.id] === key) delete next[c.id]; else next[c.id] = key;
                        return next;
                      })}>
                      <span>{label}</span><span className="c">{criterionCounts[i][key].toLocaleString()}</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </details>
        ))}
      </FilterRail>

      <main className="col canvascol targets-main">
        <div className="targets-heading">
          <div><h2>Targets <span>{cohort.length.toLocaleString()}</span></h2><p>H37Rv · Protein-coding genes</p></div>
          <div className="table-gene-search targets-search">
            <InterfaceIcon name="search" />
            <input type="search" aria-label="Search targets" placeholder="Search gene, locus or function…" value={query} onChange={event => setQuery(event.target.value)} />
            {query && <button type="button" aria-label="Clear target search" onClick={() => setQuery("")}>×</button>}
          </div>
        </div>
        {activeCount > 0 && (
          <div className="targets-active-filters" aria-label="Active filters">
            {status && <button type="button" onClick={() => setStatus(null)} aria-label={`Remove ${STATUS_LABEL[status]} filter`}>{STATUS_LABEL[status]} <span aria-hidden="true">×</span></button>}
            {CRITERIA.filter(c => picks[c.id]).map(c => (
              <button key={c.id} type="button" onClick={() => removePick(c.id)} aria-label={`Remove ${c.label} filter`}>
                {c.label}: {VERDICTS.find(([key]) => key === picks[c.id])?.[1]} <span aria-hidden="true">×</span>
              </button>
            ))}
            <button type="button" className="targets-reset" onClick={clearFilters}>Clear all</button>
          </div>
        )}
        {steps.length > 0 && (
          <details className="targets-filter-steps">
            <summary>Filter breakdown <span>{searched.length.toLocaleString()} → {cohort.length.toLocaleString()}</span></summary>
            <div className="assess-funnel">
              {steps.map(step => <div className="assess-step" key={step.label}><span>{step.label}</span><b>{step.count.toLocaleString()}</b><span className="assess-step-d">−{step.drop.toLocaleString()}</span></div>)}
            </div>
          </details>
        )}
        <div className="detail-table-scroll targets-table-scroll" ref={tableRef}>
          <table className="clinical-table workspace-table targets-table">
            <caption className="sr-only">H37Rv protein targets</caption>
            <thead><tr>{columns.map(column => (
              <th key={column.key} className={"numeric" in column ? "num" : ""}
                aria-sort={sort.key === column.key ? sort.descending ? "descending" : "ascending" : "none"}>
                <button type="button" title={"hint" in column ? column.hint : undefined} onClick={() => {
                  setSort({ key: column.key, descending: sort.key === column.key ? !sort.descending : "numeric" in column });
                  setPage(0);
                }}>{column.label}<span aria-hidden="true">{sort.key === column.key ? sort.descending ? "↓" : "↑" : "↕"}</span></button>
              </th>
            ))}</tr></thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.rv_id} aria-selected={selected === row.rv_id} onClick={event => {
                  returnFocus.current = event.currentTarget.querySelector<HTMLButtonElement>(".row-open");
                  setProfileTab("overview");
                  setSelected(row.rv_id);
                }}>
                  <td className="targets-identity">
                    <button type="button" className="row-open" aria-label={`View ${row.gene_name ?? row.rv_id} target profile`}>
                      <strong>{row.gene_name ?? row.rv_id}</strong>{row.gene_name && row.gene_name !== row.rv_id && <span>{row.rv_id}</span>}
                    </button>
                    <span className="targets-product" title={row.product ?? undefined}>{row.product ?? "Unannotated protein"}</span>
                  </td>
                  <td><span className={`target-status status-${row.validation_status ?? "unknown"}`} title={row.validation_status ? STATUS_BASIS[row.validation_status] : "Validation status unavailable"}>
                    {row.validation_status ? STATUS_LABEL[row.validation_status] : "No record"}
                  </span></td>
                  <td><span className={`target-essentiality ess-${row.essentiality ?? "none"}`} title={row.essentiality_label ?? undefined}>{row.essentiality ?? "—"}</span></td>
                  <td className="num">{f2(row.vulnerability_index) ?? "—"}</td>
                  {(!chosen || sort.key === "n_pdb") && <td className="num">{n0(row.n_pdb) ?? "—"}</td>}
                  {(!chosen || sort.key === "n_protein_assays") && <td className="num"><button type="button" className="assess-value-link" aria-label={`View ${row.n_protein_assays} protein assays for ${row.gene_name ?? row.rv_id}`} onClick={event => {
                    event.stopPropagation();
                    returnFocus.current = event.currentTarget.closest("tr")?.querySelector<HTMLButtonElement>(".row-open") ?? null;
                    setProfileTab("assays");
                    setSelected(row.rv_id);
                  }}>{n0(row.n_protein_assays) ?? "—"}</button></td>}
                  {(!chosen || sort.key === "n_compounds") && <td className="num">{n0(row.n_compounds) ?? "—"}</td>}
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={columns.length}><div className="targets-empty"><InterfaceIcon name="search" /><h3>No targets found</h3><p>{active ? "Try a different search or remove a filter." : "No protein-coding targets are available."}</p>{active && <button type="button" className="rowbtn" onClick={clearFilters}>Clear search &amp; filters</button>}</div></td></tr>}
            </tbody>
          </table>
        </div>
        <div className="targets-pagination">
          <span role="status">{sorted.length ? `${(currentPage * PAGE_SIZE + 1).toLocaleString()}–${Math.min((currentPage + 1) * PAGE_SIZE, sorted.length).toLocaleString()} of ${sorted.length.toLocaleString()}` : "0 targets"}</span>
          <div><button type="button" className="rowbtn" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button><span>{currentPage + 1} / {pageCount}</span><button type="button" className="rowbtn" disabled={currentPage >= pageCount - 1} onClick={() => setPage(currentPage + 1)}>Next</button></div>
        </div>
      </main>

      {chosen && (
        <aside className="col detailcol assess-side" aria-label="Target profile" ref={profileRef}>
          <div className="assess-panel-head"><p className="lab">Target profile</p><button ref={closeRef} type="button" className="rowbtn" onClick={closeProfile}>Close</button></div>
          <Profile key={chosen.rv_id} row={chosen} onOpenGene={onOpenGene} picks={picks} statusFilter={status} tab={profileTab} onTab={setProfileTab} />
        </aside>
      )}
    </div>
  );
}
