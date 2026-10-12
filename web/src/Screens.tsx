import { useEffect, useRef, useState, type ReactNode } from "react";
import { FilterRail } from "./FilterRail";
import { InterfaceIcon } from "./InterfaceIcon";
import { TableControls, useTablePreferences, type Column } from "./TableControls";
import { cellFormatting, scaleRanges } from "./table-formatting";
import { ChemblLink, Structure } from "./Structure";
import { api, type HitProfile, type ScreenSummary, type ScreenStage, type ScreenResult, type CompoundEvidence } from "./api";

const PAGE = 100;
type Sort = { key: string; order: "asc" | "desc" };
const MODALITIES: Record<string, string> = {
  phenotypic_mtb: "Whole-cell Mtb", biochemical_mtb: "Mtb protein",
  mammalian_cytotox: "Cytotoxicity", adme: "ADME / PK", in_vivo_efficacy: "Animal efficacy",
  other_pathogen: "Other pathogens", other: "Unclassified",
};
const EVIDENCE: [string, string, string][] = [
  ["n_mtb_whole_cell", "Whole-cell", "phenotypic_mtb"],
  ["n_mtb_protein", "Mtb protein", "biochemical_mtb"],
  ["n_cytotox", "Cytotoxicity", "mammalian_cytotox"],
  ["n_adme", "ADME / PK", "adme"],
  ["n_in_vivo", "Animal", "in_vivo_efficacy"],
  ["n_other_pathogen", "Other pathogens", "other_pathogen"],
  ["n_other", "Unclassified", "other"],
];
const OUTCOMES: [string, string, keyof ScreenStage][] = [
  ["active", "Active", "n_active_rows"], ["inactive", "Inactive", "n_inactive_rows"],
  ["inconclusive", "Inconclusive", "n_inconclusive_rows"], ["no_call", "No call", "n_no_call_rows"],
];
const count = (n: number | null | undefined) => n == null ? "—" : n.toLocaleString();
const labelStage = (stage: string | null) => stage ? stage.replaceAll("_", " ") : "Not stated";
function measurement(row: ScreenResult) {
  if (row.standard_value === null) return row.activity_comment ?? "—";
  const relation = row.standard_relation && row.standard_relation !== "=" ? row.standard_relation : "";
  return `${row.endpoint ?? ""} ${relation}${row.standard_value.toLocaleString(undefined, { maximumSignificantDigits: 6 })} ${row.standard_units ?? ""}`.trim();
}
function actives(screen: ScreenSummary) {
  return !screen.outcome_stated ? "Not stated" : screen.n_active === null ? "Per stage" : count(screen.n_active);
}

/** Ignore responses from an earlier filter or selection, including failed requests. */
function useRemote<T>(key: string, fetcher: () => Promise<T>) {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null }>({ data: null, loading: true, error: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    setState(s => ({ ...s, loading: true, error: null }));
    fetcher().then(data => {
      if (current) setState({ data, loading: false, error: null });
    }, e => {
      if (current) setState({ data: null, loading: false, error: String(e) });
    });
    return () => { current = false; };
    // The explicit key contains the query; the fetch closure needn't be stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);
  return { ...state, retry: () => setAttempt(n => n + 1) };
}
function useDebounced(value: string) {
  const [settled, setSettled] = useState(value);
  useEffect(() => { const timer = setTimeout(() => setSettled(value.trim()), 250); return () => clearTimeout(timer); }, [value]);
  return settled;
}
function RequestState({ loading, error, retry }: { loading: boolean; error: string | null; retry: () => void }) {
  return loading ? <p className="workspace-status" role="status">Loading…</p> : error ?
    <div className="workspace-status" role="alert"><p>Could not load these records.</p><button type="button" className="minibtn" onClick={retry}>Try again</button><details><summary>Error details</summary><p>{error}</p></details></div> : null;
}
function Pager({ total, offset, onOffset, label, loading = false }: {
  total: number; offset: number; onOffset: (n: number) => void; label: string; loading?: boolean;
}) {
  const last = Math.max(0, Math.floor((total - 1) / PAGE) * PAGE);
  return <div className="pager workspace-pager">
    <span aria-live="polite">{total ? `${count(offset + 1)}–${count(Math.min(offset + PAGE, total))} of ${count(total)}` : "0"} {label}</span>
    <div className="pager-actions">
      <button type="button" className="minibtn" disabled={loading || offset === 0} onClick={() => onOffset(0)} aria-label={`First page of ${label}`}>⇤</button>
      <button type="button" className="minibtn" disabled={loading || offset === 0} onClick={() => onOffset(Math.max(0, offset - PAGE))} aria-label={`Previous page of ${label}`}>←</button>
      <button type="button" className="minibtn" disabled={loading || offset >= last} onClick={() => onOffset(offset + PAGE)} aria-label={`Next page of ${label}`}>Next →</button>
    </div>
  </div>;
}
function SortHeader({ sort, onSort, column }: { sort: Sort; onSort: (s: Sort) => void; column: Column }) {
  const [key, label, numeric] = column, active = sort.key === key;
  return <th scope="col" className={numeric ? "n" : undefined} aria-sort={active ? sort.order === "asc" ? "ascending" : "descending" : undefined}>
    <button type="button" className="sortbutton" onClick={() => onSort({ key, order: active ? sort.order === "asc" ? "desc" : "asc" : numeric ? "desc" : "asc" })}>
      {label}<span className="sorticon" aria-hidden="true">{active ? sort.order === "asc" ? "↑" : "↓" : "↕"}</span>
    </button>
  </th>;
}
function SearchBox({ value, onChange, label, placeholder }: { value: string; onChange: (s: string) => void; label: string; placeholder: string }) {
  return <div className="workspace-search" role="search" aria-label={label}>
    <InterfaceIcon name="search" /><input type="search" value={value} onChange={e => onChange(e.target.value)} aria-label={label} placeholder={placeholder} />
    {value && <button type="button" className="row-open" onClick={() => onChange("")} aria-label={`Clear ${label.toLowerCase()}`}>×</button>}
  </div>;
}
function FilterSelect({ label, value, onChange, children }: { label: string; value: string; onChange: (s: string) => void; children: ReactNode }) {
  return <label className="workspace-filter"><span>{label}</span><select aria-label={label} value={value} onChange={e => onChange(e.target.value)}>{children}</select></label>;
}
function ActiveFilters({ filters, onClear }: { filters: { label: string; clear: () => void }[]; onClear: () => void }) {
  return filters.length ? <div className="active-filters" aria-label="Active filters">
    {filters.map(f => <button type="button" key={f.label} className="filter-chip" onClick={f.clear} aria-label={`Remove ${f.label} filter`}>{f.label}<span aria-hidden="true">×</span></button>)}
    <button type="button" className="row-open" onClick={onClear}>Clear all</button>
  </div> : null;
}
function Source({ row }: { row: { source?: string; source_version?: string; retrieved_at?: string } }) {
  return <span className="source-meta">{[row.source, row.source_version, row.retrieved_at ? `Retrieved ${row.retrieved_at.slice(0, 10)}` : null].filter(Boolean).join(" · ")}</span>;
}
function MaximizeButton({ expanded, onToggle, label }: { expanded: boolean; onToggle: () => void; label: string }) {
  return <button type="button" className="minibtn maximize-button" aria-label={`${expanded ? "Restore" : "Maximize"} ${label}`} title={`${expanded ? "Restore" : "Maximize"} ${label}`} aria-pressed={expanded} onClick={onToggle}><InterfaceIcon name={expanded ? "collapse" : "expand"} /></button>;
}
function DetailShell({ title, subtitle, onClose, children, expanded, onMaximize }: { title: string; subtitle?: ReactNode; onClose: () => void; children: ReactNode; expanded: boolean; onMaximize: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return <section className={`col detailcol workspace-detail${expanded ? " is-maximized" : ""}`} aria-label={title} onKeyDown={e => { if (e.key === "Escape") { e.stopPropagation(); if (expanded) onMaximize(); else onClose(); } }}>
    <header className="workspace-detail-head"><div><h2 tabIndex={-1} ref={heading}>{title}</h2>{subtitle}</div><div className="detail-head-actions"><MaximizeButton expanded={expanded} onToggle={onMaximize} label="detail panel" /><button type="button" className="minibtn detail-close" onClick={onClose} aria-label="Close detail">×</button></div></header>
    {children}
  </section>;
}
function Empty({ noun, onClear }: { noun: string; onClear?: () => void }) {
  return <div className="workspace-status"><p>No {noun} match.</p>{onClear && <button type="button" className="minibtn" onClick={onClear}>Clear filters</button>}</div>;
}

const SCREEN_COLUMNS: Column[] = [
  ["screen_id", "Campaign", false], ["source", "Source", false], ["n_tested", "Tested", true],
  ["n_active", "Actives", true], ["n_stages", "Stages", true], ["genes", "Genes", false],
  ["depositor", "Depositor", false], ["year", "Year", true], ["library_size_stated", "Reported library size", true],
  ["n_inactive", "Inactive", true], ["modalities", "Measurement types", false],
];
const SCREEN_DEFAULT = ["screen_id", "source", "n_tested", "n_active", "n_stages", "genes"];
const SCREEN_GROUPS = [
  { label: "Campaign", keys: ["screen_id", "depositor", "source", "year"] },
  { label: "Size", keys: ["n_tested", "library_size_stated", "n_stages"] },
  { label: "Outcome", keys: ["n_active", "n_inactive"] }, { label: "Targets", keys: ["modalities", "genes"] },
];
const SCREEN_SORTS = new Set(["screen_id", "year", "n_tested", "n_active", "n_stages"]);
function campaignCell(screen: ScreenSummary, key: string, onOpen: () => void) {
  switch (key) {
    case "screen_id": return <><button type="button" className="row-open campaign-title" onClick={e => { e.stopPropagation(); onOpen(); }} data-record={screen.screen_id}>{screen.title ?? screen.screen_id}</button><div className="record-secondary">{screen.depositor ?? screen.screen_id}</div></>;
    case "source": return <span className="source-badge">{screen.source === "pubchem" ? "PubChem" : "ChEMBL"}</span>;
    case "n_tested": return <>{count(screen.n_tested)}<span className="cell-unit">{screen.source === "pubchem" ? "substances" : "compounds"}</span></>;
    case "n_active": return <span className={screen.n_active == null ? "dim" : undefined}>{actives(screen)}</span>;
    case "n_inactive": return screen.outcome_stated ? screen.n_inactive == null ? "Per stage" : count(screen.n_inactive) : "Not stated";
    case "genes": return screen.genes.length ? <span className="chips">{screen.genes.map(g => <span className={`chip ${g.own ? "accent" : "warn"}`} key={g.rv_id} title={g.own ? g.rv_id : `${g.rv_id} · complex subunit`}>{g.gene_name ?? g.rv_id}{!g.own && " · complex"}</span>)}</span> : screen.unplaced_targets.length ? <span className="dim">Unmapped protein</span> : "—";
    case "modalities": return <span className="clinical-clamp">{screen.modalities.map(m => MODALITIES[m] ?? m).join(", ") || "Not stated"}</span>;
    case "depositor": return <span className="clinical-clamp">{screen.depositor ?? "—"}</span>;
    case "year": return screen.year ?? "—";
    case "n_stages": return count(screen.n_stages);
    case "library_size_stated": return count(screen.library_size_stated);
    default: return null;
  }
}

function CampaignDetail({ id, onClose, onSelectGene, onProfile, onCompound, expanded, onMaximize }: {
  id: string; onClose: () => void; onSelectGene?: (id: string) => void;
  onProfile?: (id: string, title: string | null) => void; onCompound?: (id: string) => void; expanded: boolean; onMaximize: () => void;
}) {
  const request = useRemote(id, () => api.screen(id));
  const [tab, setTab] = useState("overview");
  const [resultsOpened, setResultsOpened] = useState(false);
  function changeTab(next: string) { setTab(next); if (next === "results") setResultsOpened(true); }
  const [stage, setStage] = useState("");
  const detail = request.data;
  return <DetailShell title={detail?.title ?? id} subtitle={<div className="record-secondary">{id}{detail?.year ? ` · ${detail.year}` : ""}</div>} onClose={onClose} expanded={expanded} onMaximize={onMaximize}>
    <RequestState {...request} />
    {!request.loading && detail && <>
      <div className="tabs" aria-label="Campaign sections">{[["overview", "Overview"], ["assays", `Assays & stages (${detail.stages.length})`], ["results", "Results"]].map(([key, label]) => <button type="button" key={key} aria-pressed={tab === key} onClick={() => changeTab(key)}>{label}</button>)}</div>
      <div className="workspace-detail-body">
        {tab === "overview" && <>
          <div className="workspace-facts">
            <div><span>Deposited</span><strong>{count(detail.n_tested)}</strong><small>{detail.source === "pubchem" ? "substances" : "compounds"}</small></div>
            <div><span>Active</span><strong>{actives(detail)}</strong></div>
            <div><span>Stages</span><strong>{detail.n_stages}</strong></div>
          </div>
          {detail.library_size_stated !== null && <p className="note">Reported library size: <strong>{count(detail.library_size_stated)} compounds</strong></p>}
          <h3>Targets</h3>
          {detail.genes.length ? <div className="target-links">{detail.genes.map(g => <button type="button" className="target-link" key={g.rv_id} onClick={() => onSelectGene?.(g.rv_id)}><strong>{g.gene_name ?? g.rv_id}</strong><span>{g.rv_id}{!g.own && " · complex subunit"}</span>{g.product && <small>{g.product}</small>}</button>)}</div> : <p className="note">No gene-level target mapped.</p>}
          {detail.unplaced_targets.map(t => <p className="note" key={t.accession ?? t.name}>{t.name} {t.accession} · Unmapped protein</p>)}
          <h3>Source</h3><p className="note">{detail.depositor ?? "Depositor not stated"}</p><Source row={detail} />
          <div className="source-links">{detail.document_chembl_id && <ChemblLink kind="document" id={detail.document_chembl_id} />}{detail.pubmed_id && <a href={`https://pubmed.ncbi.nlm.nih.gov/${detail.pubmed_id}/`} target="_blank" rel="noreferrer">PubMed ↗</a>}{detail.aid && <a href={`https://pubchem.ncbi.nlm.nih.gov/bioassay/${detail.aid}`} target="_blank" rel="noreferrer">PubChem assay ↗</a>}</div>
          {!detail.outcome_stated && detail.stages.some(s => (s.n_active_rows ?? 0) + (s.n_inactive_rows ?? 0) + (s.n_inconclusive_rows ?? 0) > 0) && <p className="note">Activity calls appear in result rows but not in the campaign summary.</p>}
          <div className="detail-actions"><button type="button" className="minibtn" onClick={() => changeTab("results")}>View results →</button>{onProfile && <button type="button" className="minibtn settings-apply" onClick={() => onProfile(id, detail.title)}>Profile compounds →</button>}</div>
        </>}
        {tab === "assays" && <>
          <p className="note">Counts are per assay. Select an assay to view its results.</p>
          <div className="detail-table-scroll"><table className="clinical-table assay-table"><thead><tr><th>Assay description</th><th className="n">Rows</th><th className="n">Compounds</th><th className="n">Active</th><th className="n">Inactive</th><th className="n">Inconclusive</th><th className="n">No call</th></tr></thead><tbody>{detail.stages.map(s => <tr key={s.stage_id}>
            <td>
              <button type="button" className="row-open assay-description" onClick={() => { setStage(s.stage_id); changeTab("results"); }}>{s.description?.trim() || "Description not available"}</button>
              <div className="record-secondary">{s.derived ? "Derived" : labelStage(s.stage)} · {MODALITIES[s.modality ?? ""] ?? "Unclassified"}{s.strain ? ` · ${s.strain}` : ""}</div>
              {s.endpoints?.length ? <div className="record-secondary">Endpoints: {s.endpoints.join(", ")}</div> : null}
              <div className="record-secondary assay-id">{s.stage_id}</div>
            </td>
            <td className="n">{count(s.n_rows)}</td><td className="n">{count(s.n_compounds)}</td><td className="n">{count(s.n_active_rows)}</td><td className="n">{count(s.n_inactive_rows)}</td><td className="n">{count(s.n_inconclusive_rows)}</td><td className="n">{count(s.n_no_call_rows)}</td>
          </tr>)}</tbody></table></div>
        </>}
        <div hidden={tab !== "results"}>{resultsOpened && <CampaignResults key={id} id={id} stages={detail.stages} stage={stage} onStage={setStage} onCompound={onCompound} />}</div>
      </div>
    </>}
  </DetailShell>;
}
function CampaignResults({ id, stages, stage, onStage, onCompound }: { id: string; stages: ScreenStage[]; stage: string; onStage: (id: string) => void; onCompound?: (id: string) => void }) {
  const scope = stages.filter(s => !stage || s.stage_id === stage);
  const totals = OUTCOMES.map(([key, label, field]) => ({ key, label, n: scope.reduce((n, s) => n + (Number(s[field]) || 0), 0) }));
  const [chosen, setChosen] = useState<{ stage: string; outcome: string } | null>(null);
  const outcome = (chosen?.stage === stage ? chosen.outcome : null) ?? totals.find(o => o.n > 0)?.key ?? "active";
  const pageKey = `${stage}:${outcome}`;
  const [paging, setPaging] = useState({ key: "", offset: 0 });
  const offset = paging.key === pageKey ? paging.offset : 0;
  const setOffset = (n: number) => setPaging({ key: pageKey, offset: n });
  const query = { stage_id: stage || undefined, outcome, offset, limit: PAGE };
  const request = useRemote(JSON.stringify([id, query]), () => api.screenResults(id, query));
  return <>
    <FilterSelect label="Assay" value={stage} onChange={s => { onStage(s); setChosen(null); setOffset(0); }}><option value="">All assays</option>{stages.map(s => <option key={s.stage_id} value={s.stage_id}>{s.stage_id} · {s.derived ? "derived" : labelStage(s.stage)}</option>)}</FilterSelect>
    <div className="tabs outcome-tabs" aria-label="Result outcomes">{totals.map(o => <button type="button" key={o.key} aria-pressed={outcome === o.key} onClick={() => { setChosen({ stage, outcome: o.key }); setOffset(0); }}>{o.label}<span className="badge">{count(o.n)}</span></button>)}</div>
    <RequestState {...request} />
    {!request.loading && request.data && <>
      {request.data.items.length ? <div className="detail-table-scroll"><table className="clinical-table result-table"><thead><tr><th>Structure</th><th>Compound</th><th>Assay</th><th>Measurement</th><th className="n">Score</th><th>Source</th></tr></thead><tbody>{request.data.items.map((row, i) => <tr key={`${row.stage_id}-${row.result_tag}-${row.activity_id}-${i}`}>
        <td>{row.smiles ? <Structure smiles={row.smiles} width={112} height={60} title={row.pref_name ?? row.molecule_chembl_id ?? undefined} /> : <span className="dim">—</span>}</td>
        <td>{row.molecule_chembl_id ? <button type="button" className="row-open" onClick={() => onCompound?.(row.molecule_chembl_id!)}>{row.pref_name ?? row.molecule_chembl_id}</button> : row.pubchem_cid ? <a href={`https://pubchem.ncbi.nlm.nih.gov/compound/${row.pubchem_cid}`} target="_blank" rel="noreferrer">CID {row.pubchem_cid} ↗</a> : `SID ${row.pubchem_sid ?? "—"}`}{row.pubchem_sid && <div className="record-secondary">SID {row.pubchem_sid}</div>}</td>
        <td>{row.stage_id}<div className="record-secondary">{labelStage(row.stage)}</div></td><td>{measurement(row)}</td><td className="n">{count(row.activity_score)}</td><td><Source row={row} /></td>
      </tr>)}</tbody></table></div> : <Empty noun="results" />}
    </>}
    <Pager total={request.data?.total ?? 0} offset={offset} onOffset={setOffset} label="result rows" loading={request.loading} />
  </>;
}

export function Screens({ onSelectGene, focus, onFocus, onProfile, onCompound, geneFocus }: {
  onSelectGene?: (id: string) => void; focus?: string | null; onFocus?: (id: string | null) => void;
  onProfile?: (id: string, title: string | null) => void; onCompound?: (id: string) => void;
  /** Set from outside to list one gene's own-protein campaigns; a new object re-applies it. */
  geneFocus?: { rv: string } | null;
}) {
  const [ownFocus, setOwnFocus] = useState<string | null>(null);
  const open = focus === undefined ? ownFocus : focus, setOpen = onFocus ?? setOwnFocus;
  const [maximized, setMaximized] = useState<"table" | "detail" | null>(null);
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [source, setSource] = useState("");
  const [modality, setModality] = useState("");
  const [gene, setGene] = useState("");
  const rv = useDebounced(gene);
  const [reach, setReach] = useState("");
  useEffect(() => {
    if (!geneFocus) return;
    setGene(geneFocus.rv);
    setReach("own");
  }, [geneFocus]);
  const [outcome, setOutcome] = useState("");
  const [sort, setSort] = useState<Sort>({ key: "n_tested", order: "desc" });
  const [paging, setPaging] = useState({ key: "", offset: 0 });
  const filterKey = JSON.stringify([q, source, modality, rv, reach, outcome, sort]);
  const offset = paging.key === filterKey ? paging.offset : 0;
  const setOffset = (n: number) => setPaging({ key: filterKey, offset: n });
  const query = { q: q || undefined, source: source || undefined, modality: modality || undefined, rv_id: rv || undefined, has_own_gene: reach === "own" ? true : undefined, own: rv && reach === "own" ? true : undefined, unplaced: reach === "unplaced" ? true : undefined, outcome_stated: outcome ? outcome === "stated" : undefined, sort: sort.key, order: sort.order, offset, limit: PAGE };
  const request = useRemote(JSON.stringify(query), () => api.screens(query));
  const settings = useTablePreferences(SCREEN_COLUMNS, "atlas.screen-table.v1", "screen_id");
  const visible = SCREEN_COLUMNS.filter(([key]) => (settings.preferences.visible ?? SCREEN_DEFAULT).includes(key));
  const columns = open && maximized !== "table" ? SCREEN_COLUMNS.filter(([key]) => ["screen_id", "n_tested", sort.key].includes(key)) : visible;
  const ranges = scaleRanges(request.data?.items ?? [], settings.preferences.scales);
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => { if (scroller.current) scroller.current.scrollTop = 0; }, [filterKey, offset]);
  function clear() { setSearch(""); setSource(""); setModality(""); setGene(""); setReach(""); setOutcome(""); }
  function openCampaign(id: string) { setMaximized(null); setOpen(id); }
  function close() { setMaximized(null); setOpen(null); requestAnimationFrame(() => scroller.current?.querySelector<HTMLButtonElement>(`button[data-record="${CSS.escape(open ?? "")}"]`)?.focus()); }
  const filters = [
    ...(search ? [{ label: `Search: ${search}`, clear: () => setSearch("") }] : []),
    ...(source ? [{ label: source === "pubchem" ? "PubChem" : "ChEMBL", clear: () => setSource("") }] : []),
    ...(modality ? [{ label: MODALITIES[modality], clear: () => setModality("") }] : []),
    ...(gene ? [{ label: `Gene: ${gene}`, clear: () => setGene("") }] : []),
    ...(reach ? [{ label: reach === "own" ? "Own protein" : "Unmapped protein", clear: () => setReach("") }] : []),
    ...(outcome ? [{ label: outcome === "stated" ? "Outcomes stated" : "Outcomes not stated", clear: () => setOutcome("") }] : []),
  ];
  return <div className={`body clinical screen-workspace${open ? " detail-open" : ""}`}>
    <FilterRail label="Screening filters"><div className="rail-heading"><InterfaceIcon name="screens" /><h2>Screens</h2></div>
      <p className="clinical-count"><strong>{count(request.data?.total)}</strong> campaigns</p>
      <FilterSelect label="Source" value={source} onChange={setSource}><option value="">All sources</option><option value="pubchem">PubChem</option><option value="chembl">ChEMBL</option></FilterSelect>
      <FilterSelect label="Measurement type" value={modality} onChange={setModality}><option value="">All types</option>{Object.entries(MODALITIES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</FilterSelect>
      <label className="workspace-filter"><span>Gene</span><input value={gene} onChange={e => setGene(e.target.value)} placeholder="Gene name or Rv ID" /></label>
      <FilterSelect label="Target mapping" value={reach} onChange={setReach}><option value="">All campaigns</option><option value="own">Gene’s own protein</option><option value="unplaced">Unmapped protein</option></FilterSelect>
      <FilterSelect label="Activity calls" value={outcome} onChange={setOutcome}><option value="">All campaigns</option><option value="stated">Stated</option><option value="unstated">Not stated</option></FilterSelect>
      {filters.length > 0 && <button type="button" className="clear-filters" onClick={clear}>Clear filters</button>}
      {request.data && <div className="coverage-note"><strong>{count(request.data.n_own_genes)} / {count(request.data.n_genes)}</strong><span>genes with an own-protein campaign</span></div>}
      <details className="group filtergroup"><summary>Dataset coverage</summary><p className="note">Ingested PubChem and ChEMBL campaigns.</p><p className="note">Not included: {request.data?.not_ingested.join("; ") ?? "—"}.</p></details>
    </FilterRail>
    <main className={`col canvascol workspace-list${maximized === "table" ? " is-maximized" : ""}`} onKeyDown={e => { if (e.key === "Escape" && maximized === "table") { e.stopPropagation(); setMaximized(null); } }}>
      <div className="workspace-toolbar"><SearchBox value={search} onChange={setSearch} label="Search campaigns" placeholder="Search campaigns, depositors or IDs…" />{(!open || maximized === "table") && <TableControls columns={SCREEN_COLUMNS} groups={SCREEN_GROUPS} visible={visible} preferences={settings.preferences} saved={settings.saved} onChange={settings.change} identity="screen_id" recordLabel="campaigns" defaultNote="" />}<MaximizeButton expanded={maximized === "table"} onToggle={() => setMaximized(maximized === "table" ? null : "table")} label="campaigns table" /></div>
      <ActiveFilters filters={filters} onClear={clear} />
      <div className="scroller clinical-scroller" ref={scroller} aria-busy={request.loading}>
        <RequestState {...request} />
        {!request.loading && request.data && (request.data.items.length ? <table className="clinical-table workspace-table campaign-table" aria-label="Screening campaigns"><thead><tr>{columns.map(c => SCREEN_SORTS.has(c[0]) ? <SortHeader key={c[0]} column={c} sort={sort} onSort={setSort} /> : <th key={c[0]} scope="col" className={c[2] ? "n" : undefined}>{c[1]}</th>)}</tr></thead><tbody>{request.data.items.map(s => <tr key={s.screen_id} aria-selected={open === s.screen_id} onClick={() => openCampaign(s.screen_id)}>{columns.map(([key, , numeric]) => <td data-column={key} key={key} className={numeric ? "n" : undefined} style={cellFormatting(s, key, settings.preferences.rules, ranges)}>{campaignCell(s, key, () => openCampaign(s.screen_id))}</td>)}</tr>)}</tbody></table> : <Empty noun="campaigns" onClear={clear} />)}
      </div>
      <Pager total={request.data?.total ?? 0} offset={offset} onOffset={setOffset} label="campaigns" loading={request.loading} />
    </main>
    {open && <CampaignDetail key={open} id={open} onClose={close} onSelectGene={onSelectGene} onProfile={onProfile} onCompound={onCompound} expanded={maximized === "detail"} onMaximize={() => setMaximized(maximized === "detail" ? null : "detail")} />}
  </div>;
}

const HIT_COLUMNS: Column[] = [
  ["molecule_chembl_id", "Compound", false], ["structure", "Structure", false], ["n_mtb_whole_cell", "Whole-cell", true],
  ["n_mtb_protein", "Mtb protein", true], ["n_cytotox", "Cytotoxicity", true],
  ["n_adme", "ADME / PK", true], ["n_in_vivo", "Animal", true], ["n_papers", "Papers", true],
  ["first_year", "First seen", true], ["latest_year", "Last seen", true],
  ["n_other_pathogen", "Other pathogens", true], ["n_other", "Unclassified", true],
  ["selectivity_median", "Selectivity median", true], ["n_active_campaigns", "Active / called", true],
];
const HIT_DEFAULT = ["molecule_chembl_id", "structure", "n_mtb_whole_cell", "n_mtb_protein", "n_cytotox", "n_adme", "n_in_vivo", "n_papers"];
const HIT_GROUPS = [
  { label: "Compound", keys: ["molecule_chembl_id", "structure"] },
  { label: "Assay coverage", keys: EVIDENCE.map(e => e[0]) },
  { label: "Literature", keys: ["n_papers", "first_year", "latest_year"] },
  { label: "Reported outcomes", keys: ["selectivity_median", "n_active_campaigns"] },
];
const COVERAGE = [["", "All compounds"], ["beyond_potency", "Beyond potency"], ["potency_only", "Potency only"], ["elsewhere_only", "Only elsewhere"]];
function selectivity(hit: HitProfile) {
  if (hit.n_selectivity == null) return hit.n_selectivity_censored ? "Bounds only" : "—";
  return hit.selectivity_median?.toLocaleString(undefined, { maximumFractionDigits: 1 }) ?? "—";
}
function HitDetail({ id, initial, category: initialCategory, onClose, onCampaign, onGene, expanded, onMaximize }: {
  id: string; initial?: HitProfile; category: string; onClose: () => void; onCampaign?: (id: string) => void; onGene?: (id: string) => void; expanded: boolean; onMaximize: () => void;
}) {
  const profile = useRemote(id, async () => initial ?? (await api.hits({ q: id, limit: 1 })).items[0] ?? null);
  const compound = useRemote(id, () => api.compound(id));
  const hit = profile.data;
  const [category, setCategory] = useState(initialCategory);
  const [offset, setOffset] = useState(0);
  const query = { category: category || undefined, offset, limit: PAGE };
  const evidence = useRemote(JSON.stringify([id, query]), () => api.compoundEvidence(id, query));
  const evidenceHeading = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (evidence.loading || (!category && !offset)) return;
    const heading = evidenceHeading.current;
    const container = heading?.closest(".workspace-detail-body");
    if (heading && container) container.scrollTop += heading.getBoundingClientRect().top - container.getBoundingClientRect().top - 16;
  }, [category, offset, evidence.loading]);
  function choose(next: string) { setCategory(next); setOffset(0); }
  return <DetailShell title={hit?.pref_name ?? compound.data?.pref_name ?? id} subtitle={<ChemblLink kind="compound" id={id} />} onClose={onClose} expanded={expanded} onMaximize={onMaximize}>
    <div className="workspace-detail-body">
      <div className="compound-overview">
        {(hit?.smiles ?? compound.data?.smiles) ? <Structure smiles={hit?.smiles ?? compound.data?.smiles ?? null} width={220} height={130} title={hit?.pref_name ?? id} /> : <span className="structure-absent">Structure unavailable</span>}
        <div><h3>Literature coverage</h3><RequestState {...profile} />{hit && <><p><strong>{count(hit.n_papers)}</strong> papers</p><p className="note">{hit.first_year ?? "—"}–{hit.latest_year ?? "—"}</p></>}{!profile.loading && !profile.error && !hit && <p className="note">No literature profile in this dataset.</p>}{hit?.n_call_campaigns != null && <p className="note">Active in {count(hit.n_active_campaigns)} of {count(hit.n_call_campaigns)} campaigns with calls.</p>}</div>
      </div>
      {compound.error && <div className="note" role="status">Compound metadata unavailable. <button type="button" className="row-open" onClick={compound.retry}>Retry</button></div>}
      {compound.data?.genes.length ? <div className="chips">{compound.data.genes.map(g => <button type="button" className="chip accent" key={g.rv_id} onClick={() => onGene?.(g.rv_id)}>{g.gene_name ?? g.rv_id}{g.evidence === "orthologue" && " · orthologue"}</button>)}</div> : null}
      {hit && <><h3>Assay coverage</h3><div className="evidence-grid">{EVIDENCE.map(([key, label, value]) => <button type="button" key={key} aria-pressed={category === value} onClick={() => choose(value)}><span>{label}</span><strong>{count(hit[key as keyof HitProfile] as number | null)}</strong></button>)}</div><p className="note">Distinct assays · — No recorded measurement</p>
        <div className="selectivity-summary"><div><span>Reported selectivity</span><strong>{selectivity(hit)}</strong></div>{hit.n_selectivity != null && <p className="note">Median · range {count(hit.selectivity_min)}–{count(hit.selectivity_max)} · {count(hit.n_selectivity)} values</p>}{!!hit.n_selectivity_censored && <p className="note">{count(hit.n_selectivity_censored)} additional bounds</p>}{(hit.n_selectivity != null || !!hit.n_selectivity_censored) && <button type="button" className="row-open" onClick={() => choose("selectivity")}>View reported ratios →</button>}</div>
      </>}
      <div className="evidence-heading" ref={evidenceHeading}><h3>Evidence</h3><select aria-label="Evidence type" value={category} onChange={e => choose(e.target.value)}><option value="">All measurements</option>{Object.entries(MODALITIES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}<option value="selectivity">Reported selectivity</option></select></div>
      <Pager total={evidence.data?.total ?? 0} offset={offset} onOffset={setOffset} label="measurements" loading={evidence.loading} />
      <RequestState {...evidence} />
      {!evidence.loading && evidence.data && (evidence.data.items.length ? <div className="evidence-records">{evidence.data.items.map((row, i) => <EvidenceRecord row={row} key={`${row.stage_id}-${row.activity_id}-${row.result_tag}-${i}`} onCampaign={onCampaign} />)}</div> : <Empty noun="measurements" />)}
      <Pager total={evidence.data?.total ?? 0} offset={offset} onOffset={setOffset} label="measurements" loading={evidence.loading} />
    </div>
  </DetailShell>;
}
function EvidenceRecord({ row, onCampaign }: { row: CompoundEvidence; onCampaign?: (id: string) => void }) {
  return <article className="evidence-record">
    <div className="evidence-record-top"><strong>{measurement(row)}</strong><span className={`outcome-label ${row.outcome ?? "no-call"}`}>{row.outcome ? labelStage(row.outcome) : "No call stated"}</span></div>
    <p className="note">{row.derived ? "Derived ratio" : MODALITIES[row.modality ?? ""] ?? labelStage(row.stage)}{row.strain ? ` · ${row.strain}` : ""}{row.assay_condition ? ` · ${labelStage(row.assay_condition)}` : ""}</p>
    <button type="button" className="row-open evidence-campaign" onClick={() => onCampaign?.(row.screen_id)}>{row.screen_title ?? row.screen_id}</button>
    <div className="record-secondary">{row.stage_id}{row.year ? ` · ${row.year}` : ""}</div>
    <details><summary>Assay & source</summary>{row.description && <p>{row.description}</p>}{row.activity_comment && <p>{row.activity_comment}</p>}<Source row={row} /><div className="source-links">{row.document_chembl_id && <ChemblLink kind="document" id={row.document_chembl_id} />}{row.stage_id.startsWith("chembl:") && <a href={`https://www.ebi.ac.uk/chembl/explore/assay/${row.stage_id.slice(7)}`} target="_blank" rel="noreferrer">ChEMBL assay ↗</a>}{row.stage_id.startsWith("pubchem:") && <a href={`https://pubchem.ncbi.nlm.nih.gov/bioassay/${row.stage_id.slice(8)}`} target="_blank" rel="noreferrer">PubChem assay ↗</a>}</div></details>
  </article>;
}
export function HitProfiling({ screen, onClearScreen, focus, onFocus, onCampaign, onSelectGene }: {
  screen?: { id: string; title: string | null } | null; onClearScreen?: () => void;
  focus?: string | null; onFocus?: (id: string | null) => void; onCampaign?: (id: string) => void; onSelectGene?: (id: string) => void;
} = {}) {
  const [maximized, setMaximized] = useState<"table" | "detail" | null>(null);
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [coverage, setCoverage] = useState("");
  const [has, setHas] = useState<string[]>([]);
  const [sort, setSort] = useState<Sort>({ key: "n_cytotox", order: "desc" });
  const [paging, setPaging] = useState({ key: "", offset: 0 });
  const filterKey = JSON.stringify([q, coverage, has, sort, screen?.id]);
  const offset = paging.key === filterKey ? paging.offset : 0;
  const setOffset = (n: number) => setPaging({ key: filterKey, offset: n });
  const [ownFocus, setOwnFocus] = useState<string | null>(null);
  const selected = focus === undefined ? ownFocus : focus, setSelected = onFocus ?? setOwnFocus;
  const [initial, setInitial] = useState<HitProfile | undefined>();
  const [category, setCategory] = useState("");
  const query = { q: q || undefined, coverage: coverage || undefined, has, screen: screen?.id, sort: sort.key, order: sort.order, offset, limit: PAGE };
  const request = useRemote(JSON.stringify(query), () => api.hits(query));
  const settings = useTablePreferences(HIT_COLUMNS, "atlas.hit-table.v1", "molecule_chembl_id");
  const visible = HIT_COLUMNS.filter(([key]) => (settings.preferences.visible ?? HIT_DEFAULT).includes(key));
  const columns = selected && maximized !== "table" ? HIT_COLUMNS.filter(([key]) => ["molecule_chembl_id", sort.key].includes(key)) : visible;
  const ranges = scaleRanges(request.data?.items ?? [], settings.preferences.scales);
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => { if (scroller.current) scroller.current.scrollTop = 0; }, [filterKey, offset]);
  function clear() { setSearch(""); setCoverage(""); setHas([]); onClearScreen?.(); }
  function open(hit: HitProfile, type = "") { setMaximized(null); setInitial(hit); setCategory(type); setSelected(hit.molecule_chembl_id); }
  function close() { setMaximized(null); setSelected(null); requestAnimationFrame(() => scroller.current?.querySelector<HTMLButtonElement>(`button[data-record="${CSS.escape(selected ?? "")}"]`)?.focus()); }
  const filters = [
    ...(search ? [{ label: `Search: ${search}`, clear: () => setSearch("") }] : []),
    ...(coverage ? [{ label: COVERAGE.find(c => c[0] === coverage)![1], clear: () => setCoverage("") }] : []),
    ...has.map(key => ({ label: EVIDENCE.find(e => e[0] === key)?.[1] ?? "Selectivity", clear: () => setHas(has.filter(h => h !== key)) })),
    ...(screen ? [{ label: `Campaign: ${screen.title ?? screen.id}`, clear: () => onClearScreen?.() }] : []),
  ];
  function cell(hit: HitProfile, key: string) {
    if (key === "molecule_chembl_id") return <><button type="button" className="row-open compound-name" data-record={hit.molecule_chembl_id} onClick={e => { e.stopPropagation(); open(hit); }}>{hit.pref_name ?? hit.molecule_chembl_id}</button>{hit.pref_name && <div className="record-secondary">{hit.molecule_chembl_id}</div>}</>;
    if (key === "structure") return hit.smiles ? <Structure smiles={hit.smiles} width={112} height={60} title={hit.pref_name ?? hit.molecule_chembl_id} /> : <span className="dim">—</span>;
    if (key === "selectivity_median") return <button type="button" className="evidence-count" onClick={e => { e.stopPropagation(); open(hit, "selectivity"); }}>{selectivity(hit)}</button>;
    if (key === "n_active_campaigns") return hit.n_call_campaigns == null ? "—" : `${count(hit.n_active_campaigns)} / ${count(hit.n_call_campaigns)}`;
    const evidence = EVIDENCE.find(e => e[0] === key);
    const value = hit[key as keyof HitProfile] as number | null;
    return evidence && value != null ? <button type="button" className="evidence-count" aria-label={`${count(value)} ${evidence[1]} assays for ${hit.pref_name ?? hit.molecule_chembl_id}`} onClick={e => { e.stopPropagation(); open(hit, evidence[2]); }}>{count(value)}</button> : count(value);
  }
  return <div className={`body clinical screen-workspace${selected ? " detail-open" : ""}`}>
    <FilterRail label="Profiling filters"><div className="rail-heading"><InterfaceIcon name="profiling" /><h2>Hit profiling</h2></div><p className="clinical-count"><strong>{count(request.data?.total)}</strong> compounds</p>
      <div className="group"><p className="lab">Coverage</p><div className="seg">{COVERAGE.map(([key, label]) => <button type="button" key={key} aria-pressed={coverage === key} onClick={() => setCoverage(key)}><span className="name">{label}</span></button>)}</div></div>
      <fieldset className="evidence-filters"><legend>Has measurements</legend>{[...EVIDENCE.map(([key, label]) => [key, label]), ["n_selectivity", "Reported selectivity"]].map(([key, label]) => <label key={key}><input type="checkbox" checked={has.includes(key)} onChange={() => setHas(has.includes(key) ? has.filter(h => h !== key) : [...has, key])} />{label}</label>)}<p className="note">Matches every selected type.</p></fieldset>
      {filters.length > 0 && <button type="button" className="clear-filters" onClick={clear}>Clear filters</button>}
      {screen && <div className="campaign-scope"><span className="lab">From campaign</span><button type="button" className="row-open" onClick={() => onCampaign?.(screen.id)}>{screen.title ?? screen.id}</button><p className="note">Showing each compound’s full literature profile.</p><button type="button" className="row-open" onClick={onClearScreen}>Clear campaign</button></div>}
      <details className="group filtergroup"><summary>About these counts</summary><p className="note">Counts are distinct assays. — means no recorded measurement.</p><p className="note">Potency only: Mtb potency without cytotoxicity, ADME or animal data. Other assays may be present.</p><p className="note">Selectivity: reported ratios; bounds excluded from the median.</p></details>
    </FilterRail>
    <main className={`col canvascol workspace-list${maximized === "table" ? " is-maximized" : ""}`} onKeyDown={e => { if (e.key === "Escape" && maximized === "table") { e.stopPropagation(); setMaximized(null); } }}>
      <div className="workspace-toolbar"><SearchBox value={search} onChange={setSearch} label="Search compounds" placeholder="Search compound name or ChEMBL ID…" />{(!selected || maximized === "table") && <TableControls columns={HIT_COLUMNS} groups={HIT_GROUPS} visible={visible} preferences={settings.preferences} saved={settings.saved} onChange={settings.change} identity="molecule_chembl_id" recordLabel="compounds" defaultNote="" />}<MaximizeButton expanded={maximized === "table"} onToggle={() => setMaximized(maximized === "table" ? null : "table")} label="compounds table" /></div>
      <ActiveFilters filters={filters} onClear={clear} /><div className="table-context">Assay counts · — No recorded measurement</div>
      <div className="scroller clinical-scroller" ref={scroller} aria-busy={request.loading}>
        <RequestState {...request} />
        {!request.loading && request.data && (request.data.items.length ? <table className="clinical-table workspace-table hit-table" aria-label="Compound profiling"><thead><tr>{columns.map(c => c[0] === "structure" ? <th key={c[0]} scope="col">{c[1]}</th> : <SortHeader key={c[0]} column={c} sort={sort} onSort={setSort} />)}</tr></thead><tbody>{request.data.items.map(hit => <tr key={hit.molecule_chembl_id} aria-selected={selected === hit.molecule_chembl_id} onClick={() => open(hit)}>{columns.map(([key, , numeric]) => <td key={key} data-column={key} className={numeric ? "n" : undefined} style={cellFormatting(hit, key, settings.preferences.rules, ranges)}>{cell(hit, key)}</td>)}</tr>)}</tbody></table> : <Empty noun="compounds" onClear={clear} />)}
      </div>
      <Pager total={request.data?.total ?? 0} offset={offset} onOffset={setOffset} label="compounds" loading={request.loading} />
    </main>
    {selected && <HitDetail key={`${selected}-${initial?.molecule_chembl_id === selected ? category : ""}`} id={selected} initial={initial?.molecule_chembl_id === selected ? initial : undefined} category={initial?.molecule_chembl_id === selected ? category : ""} onClose={close} onCampaign={onCampaign} onGene={onSelectGene} expanded={maximized === "detail"} onMaximize={() => setMaximized(maximized === "detail" ? null : "detail")} />}
  </div>;
}
