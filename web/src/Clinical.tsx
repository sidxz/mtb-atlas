/**
 * The clinical end of the atlas: TB drugs and candidates, the trials testing
 * them, and the genes they reach -- every link labelled with how it was made.
 *
 * A drug "acts on" a gene only when ChEMBL's mechanism or Bosch 2021 names that
 * gene's protein. Membership of a target complex and WHO-graded resistance are
 * shown, never promoted: resistance is not engagement (katG activates isoniazid).
 */

import { FilterRail } from "./FilterRail";
import { InterfaceIcon } from "./InterfaceIcon";
import { TableControls, useTablePreferences, type Column } from "./TableControls";
import { cellFormatting, numericValue, scaleRanges } from "./table-formatting";
import { useEffect, useMemo, useState } from "react";
// Clinical.tsx cannot import from TargetDetail.tsx -- that is the wrong way
// round -- so both views share the chemistry presentation module.
import { ChemblLink, Structure } from "./Structure";
import {
  api,
  type CompoundDetail,
  type DrugDetail,
  type DrugLink,
  type DrugSummary,
  type Meta,
  type TargetDetail,
  type Trial,
  type TrialDetail,
} from "./api";

export type Focus = { kind: "drug" | "trial" | "compound"; id: string } | null;

const LINK_LABEL: Record<DrugLink, string> = {
  mechanism: "ChEMBL mechanism",
  bosch_2021: "Bosch 2021",
  structure: "co-crystal",
  mechanism_complex: "complex member",
  who_resistance: "WHO resistance",
};

const TARGET_LINKS: DrugLink[] = ["mechanism", "bosch_2021"];

/** The table is plain DOM rows; beyond this many the browser, not the data, is the limit. */
const TRIAL_ROWS = 400;

const SOURCE = {
  chembl: "ChEMBL drug indications and mechanisms · CC BY-SA 3.0",
  // ChEMBL asks that the release be shown; `meta` carries it.
  bosch: "Bosch et al. 2021, Cell · Table S3 · CC BY 4.0",
  who: "WHO catalogue 2nd ed. 2023 · ODC-By 1.0",
  pdb: "RCSB PDB · CC0 1.0",
};

/** The phase ChEMBL records for a TB indication. 4 means approved for TB. */
export function phaseLabel(phase: number | null | undefined): string {
  if (phase === null || phase === undefined) return "—";
  if (phase >= 4) return "approved";
  if (phase < 0) return "phase unknown";
  if (phase < 1) return "early phase 1";
  return `phase ${phase}`;
}

export function trialPhase(phases: string[]): string {
  const real = phases.filter((p) => p !== "NA");
  if (!real.length) return "n/a";
  return `phase ${real.map((p) => (p === "EARLY_PHASE1" ? "early 1" : p.replace("PHASE", ""))).join("/")}`;
}

const status = (value: string | null) => (value ?? "unknown").toLowerCase().replace(/_/g, " ");

const trialUrl = (nctId: string) => `https://clinicaltrials.gov/study/${nctId}`;

/** ChEMBL asks that the release be displayed wherever its data is shown. */
function chemblSource(meta: Meta | null): string {
  const version = meta?.sources.find(
    (s) => s.name === "ChEMBL drug indications and mechanisms",
  )?.version;
  return version ? SOURCE.chembl.replace("ChEMBL ", `ChEMBL ${version} `) : SOURCE.chembl;
}

function trialSource(meta: Meta | null): string {
  const version = meta?.sources.find((s) => s.name === "ClinicalTrials.gov")?.version;
  // The terms ask for the processing date and a statement of modifications.
  return `ClinicalTrials.gov${version ? ` · ${version}` : ""} · Selected trial fields; phases shown numerically. Studies solely of nontuberculous mycobacteria are excluded.`;
}

function GeneChip({ rv, name, onSelect }: { rv: string; name: string | null; onSelect: (rv: string) => void }) {
  return (
    <button
      type="button"
      className="chip accent"
      onClick={(event) => {
        event.stopPropagation();
        onSelect(rv);
      }}
      title={rv}
    >
      {name && name !== rv ? name : rv}
    </button>
  );
}

function Section({ label, source, children }: { label: string; source?: string; children: React.ReactNode }) {
  return (
    <div className="ev">
      <span className="k">{label}</span>
      <div>{children}</div>
      {source && <span className="src">{source}</span>}
    </div>
  );
}

// --- on a gene page ---------------------------------------------------------------

export function ClinicalTab({
  detail,
  meta,
  onOpen,
}: {
  detail: TargetDetail;
  meta: Meta | null;
  onOpen: (focus: Focus) => void;
}) {
  const acting = detail.drugs.filter((d) => TARGET_LINKS.includes(d.link));
  const complex = detail.drugs.filter(
    (d) => d.link === "mechanism_complex" && !acting.some((a) => a.molecule_chembl_id === d.molecule_chembl_id),
  );
  const resistance = detail.drugs.filter((d) => d.link === "who_resistance");
  const crystals = detail.drugs.filter((d) => d.link === "structure");

  const byDrug = new Map<string, typeof acting>();
  for (const link of acting) byDrug.set(link.molecule_chembl_id, [...(byDrug.get(link.molecule_chembl_id) ?? []), link]);

  return (
    <>
      <Section label="Drugs acting on this gene" source={`${chemblSource(meta)} · ${SOURCE.bosch}`}>
        {byDrug.size === 0 ? (
          <span className="absent">
            No drug with a TB indication is linked to this protein by a ChEMBL mechanism or
            Bosch 2021 annotation
          </span>
        ) : (
          <table>
            <tbody>
              {[...byDrug.values()].map((links) => {
                const drug = links[0];
                return (
                  <tr key={drug.molecule_chembl_id} onClick={() => onOpen({ kind: "drug", id: drug.molecule_chembl_id })}>
                    <td>
                      <Structure
                        smiles={drug.smiles}
                        title={drug.pref_name ?? drug.molecule_chembl_id}
                        width={132}
                        height={72}
                      />
                    </td>
                    <td className="id">
                      {drug.pref_name && <div>{drug.pref_name}</div>}
                      <ChemblLink kind="compound" id={drug.molecule_chembl_id} />
                    </td>
                    <td>
                      <span className={`chip ${drug.max_phase_tb !== null && drug.max_phase_tb >= 4 ? "accent" : "ortho"}`}>
                        {phaseLabel(drug.max_phase_tb)}
                      </span>
                    </td>
                    <td className="dim">
                      {links
                        .map((l) =>
                          l.link === "bosch_2021" && l.source_text
                            ? `${LINK_LABEL[l.link]}: “${l.source_text}”`
                            : LINK_LABEL[l.link],
                        )
                        .join(" · ")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {detail.antibacterial && !acting.some((d) => d.link === "bosch_2021") && (
          <p className="caveat">
            Bosch 2021 lists &ldquo;{detail.antibacterial}&rdquo; for this gene. This annotation could not be matched to a single ChEMBL molecule with a TB indication and is excluded from the count.
          </p>
        )}
        <div className="note">
          Phase is the highest recorded in ChEMBL for TB. Bosch 2021 drug annotations can identify either a target or an activating enzyme, such as folC for PAS.
        </div>
      </Section>

      {complex.length > 0 && (
        <Section label="Acts on a complex this protein belongs to" source={chemblSource(meta)}>
          {complex.map((d) => (
            <div className="note" key={d.molecule_chembl_id} style={{ color: "var(--fg)" }}>
              <button type="button" className="chip ortho" onClick={() => onOpen({ kind: "drug", id: d.molecule_chembl_id })}>
                {d.pref_name}
              </button>{" "}
              {phaseLabel(d.max_phase_tb)} · {d.target_name}
              {d.target_type ? ` (${d.target_type.toLowerCase()})` : ""}, {d.n_target_accessions}{" "}
              Mtb proteins
            </div>
          ))}
          <p className="caveat">
            ChEMBL records these drugs against the whole complex. Binding to this specific
            subunit has not been established by these records.
          </p>
        </Section>
      )}

      {crystals.length > 0 && (
        <Section label="Co-crystallised with this protein" source={SOURCE.pdb}>
          {crystals.map((d) => (
            <div className="note" key={d.molecule_chembl_id} style={{ color: "var(--fg)" }}>
              <button
                type="button"
                className="chip accent"
                onClick={() => onOpen({ kind: "drug", id: d.molecule_chembl_id })}
              >
                {d.pref_name}
              </button>{" "}
              {phaseLabel(d.max_phase_tb)} · <span className="mono">{d.source_text}</span>
            </div>
          ))}
          <p className="caveat">
            These ligands are modelled on this protein&rsquo;s chain. A bound ligand supports
            a physical interaction but does not by itself establish a drug mechanism.
          </p>
        </Section>
      )}

      {resistance.length > 0 && (
        <Section label="WHO-graded resistance" source={SOURCE.who}>
          <div className="chips">
            {resistance.map((d) => (
              <button type="button" className="chip warn" key={d.molecule_chembl_id} onClick={() => onOpen({ kind: "drug", id: d.molecule_chembl_id })}>
                {d.source_text} · {d.n_variants}
              </button>
            ))}
          </div>
          <p className="caveat">
            These variants are associated with resistance to the listed drugs. The gene may
            encode a drug activator, an efflux protein or a target regulator, so this association
            alone does not establish binding.
          </p>
        </Section>
      )}

      <Section label={`Trials (${detail.trials.length})`} source={trialSource(meta)}>
        {detail.trials.length === 0 ? (
          <span className="absent">No trial is linked to a drug recorded against this protein</span>
        ) : (
          <div className="scroller" style={{ maxHeight: 360 }}>
            <table>
              <thead>
                <tr>
                  <th>NCT</th>
                  <th>Phase</th>
                  <th>Status</th>
                  <th>Start</th>
                  <th>Drugs</th>
                </tr>
              </thead>
              <tbody>
                {detail.trials.map((t) => (
                  <tr key={t.nct_id} onClick={() => onOpen({ kind: "trial", id: t.nct_id })} title={t.brief_title ?? ""}>
                    <td className="id">{t.nct_id}</td>
                    <td className="dim">{trialPhase(t.phases)}</td>
                    <td className="dim">{status(t.status)}</td>
                    <td className="mono dim">{t.start_date ?? "—"}</td>
                    <td className="mono">{t.drugs.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </>
  );
}

// --- the drugs & trials view ------------------------------------------------------

type DrugFlag = "on_gene" | "acts_on_mtb" | "j04" | "host_targeted" | "with_trials";

const DRUG_FLAGS: [DrugFlag, string, (d: DrugSummary) => boolean][] = [
  ["on_gene", "Placed on an Mtb gene", (d) => d.genes.length > 0],
  ["acts_on_mtb", "Mechanism on Mtb (ChEMBL)", (d) => d.acts_on_mtb],
  ["j04", "Antimycobacterial (ATC J04)", (d) => d.atc_codes.some((c) => c.startsWith("J04"))],
  ["host_targeted", "Host-targeted", (d) => d.host_targeted],
  ["with_trials", "Has linked trials", (d) => d.n_trials > 0],
];

const PHASES: [number, string][] = [
  [4, "Approved for TB"],
  [3, "Phase 3"],
  [2, "Phase 2"],
  [1, "Phase 1"],
];

const DRUG_COLUMNS: Column[] = [
  ["structure", "Structure", false], ["pref_name", "Drug", false],
  ["max_phase_tb", "TB phase", true], ["first_approval", "First approval", true], ["n_trials", "Trials", true],
  ["genes", "Mtb genes", false], ["mechanisms_of_action", "Mechanism", false],
];
const DRUG_GROUPS = [
  { label: "Compound", keys: ["structure", "pref_name"] },
  { label: "Clinical evidence", keys: ["max_phase_tb", "first_approval", "n_trials"] },
  { label: "Target evidence", keys: ["genes", "mechanisms_of_action"] },
];
const TRIAL_COLUMNS: Column[] = [
  ["nct_id", "NCT", false], ["brief_title", "Study title", false],
  ["phase_max", "Phase", true], ["status", "Status", false],
  ["start_date", "Start", false], ["enrollment", "Enrollment", true], ["drugs", "Drugs", false],
];
const TRIAL_GROUPS = [
  { label: "Study", keys: ["nct_id", "brief_title"] },
  { label: "Clinical stage", keys: ["phase_max", "status"] },
  { label: "Recruitment", keys: ["start_date", "enrollment"] },
  { label: "Treatment", keys: ["drugs"] },
];
type ClinicalSort = { key: string; order: "asc" | "desc" } | null;
function sortClinical<T extends DrugSummary | Trial>(rows: T[], sort: ClinicalSort): T[] {
  if (!sort) return rows;
  const value = (row: T): string | number | undefined => {
    const numeric = numericValue(row, sort.key);
    if (numeric !== undefined) return numeric;
    if (["max_phase_tb", "phase_max", "first_approval", "n_trials", "enrollment"].includes(sort.key)) return undefined;
    if (sort.key === "pref_name" && "pref_name" in row) return row.pref_name ?? row.molecule_chembl_id;
    if (sort.key === "genes" && "genes" in row) return row.genes.map(g => g.gene_name ?? g.rv_id).join(", ");
    if (sort.key === "drugs" && "drugs" in row) return row.drugs.map(d => d.pref_name ?? d.molecule_chembl_id).join(", ");
    const raw = (row as unknown as Record<string, unknown>)[sort.key];
    return Array.isArray(raw) ? raw.join("; ") : typeof raw === "string" ? raw : undefined;
  };
  return [...rows].sort((a, b) => {
    const av = value(a), bv = value(b);
    if (av === undefined || bv === undefined) return av === bv ? 0 : av === undefined ? 1 : -1;
    const comparison = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv), undefined, { numeric: true });
    return sort.order === "asc" ? comparison : -comparison;
  });
}

export function DrugsAndTrials({ meta, focus, onFocus, onSelectGene }: {
  meta: Meta | null; focus: Focus; onFocus: (focus: Focus) => void; onSelectGene: (rv: string) => void;
}) {
  const [tab, setTab] = useState<"drugs" | "trials">(focus?.kind === "trial" ? "trials" : "drugs");
  const [drugs, setDrugs] = useState<DrugSummary[]>([]);
  const [trials, setTrials] = useState<Trial[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [phases, setPhases] = useState<Set<number>>(new Set());
  const [flags, setFlags] = useState<Set<DrugFlag>>(new Set(["on_gene"]));
  const [statuses, setStatuses] = useState<Set<string>>(new Set());
  const [linkedOnly, setLinkedOnly] = useState(true);
  const [drugSort, setDrugSort] = useState<ClinicalSort>(null);
  const [trialSort, setTrialSort] = useState<ClinicalSort>(null);
  const drugSettings = useTablePreferences(DRUG_COLUMNS, "atlas.drug-table.v1", "pref_name");
  const trialSettings = useTablePreferences(TRIAL_COLUMNS, "atlas.trial-table.v1", "nct_id");

  useEffect(() => {
    Promise.all([api.drugs(), api.trials()]).then(([d, t]) => {
      setDrugs(d.items); setTrials(t.items);
    }).catch((e: unknown) => setError(String(e))).finally(() => setLoading(false));
  }, []);
  useEffect(() => { if (focus) setTab(focus.kind === "trial" ? "trials" : "drugs"); }, [focus]);

  const shownDrugs = useMemo(() => drugs.filter(d => {
    if (phases.size && !phases.has(Math.floor(d.max_phase_tb ?? -1))) return false;
    return DRUG_FLAGS.every(([key, , test]) => !flags.has(key) || test(d));
  }), [drugs, phases, flags]);
  const shownTrials = useMemo(() => trials.filter(t =>
    (!linkedOnly || t.drugs.length > 0) && (!statuses.size || statuses.has(t.status ?? "UNKNOWN")) &&
    (!phases.size || phases.has(Math.floor(t.phase_max ?? -1)))
  ), [trials, linkedOnly, statuses, phases]);
  const trialStatuses = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of trials) counts.set(t.status ?? "UNKNOWN", (counts.get(t.status ?? "UNKNOWN") ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [trials]);
  const sortedDrugs = useMemo(() => sortClinical(shownDrugs, drugSort), [shownDrugs, drugSort]);
  const sortedTrials = useMemo(() => sortClinical(shownTrials, trialSort), [shownTrials, trialSort]);
  const drugRanges = useMemo(() => scaleRanges(shownDrugs, drugSettings.preferences.scales), [shownDrugs, drugSettings.preferences.scales]);
  const trialRanges = useMemo(() => scaleRanges(shownTrials, trialSettings.preferences.scales), [shownTrials, trialSettings.preferences.scales]);
  const isDrug = tab === "drugs";
  const settings = isDrug ? drugSettings : trialSettings;
  const allColumns = isDrug ? DRUG_COLUMNS : TRIAL_COLUMNS;
  const groups = isDrug ? DRUG_GROUPS : TRIAL_GROUPS;
  const columns = allColumns.filter(([key]) => !settings.preferences.visible || settings.preferences.visible.includes(key));
  const sort = isDrug ? drugSort : trialSort;
  const setSort = isDrug ? setDrugSort : setTrialSort;
  const count = isDrug ? shownDrugs.length : shownTrials.length;
  const toggle = <T,>(set: Set<T>, value: T, apply: (next: Set<T>) => void) => {
    const next = new Set(set); next.has(value) ? next.delete(value) : next.add(value); apply(next);
  };
  function clearFilters() { setPhases(new Set()); if (isDrug) setFlags(new Set()); else { setStatuses(new Set()); setLinkedOnly(false); } }
  function drugCell(d: DrugSummary, key: string) {
    switch (key) {
      case "structure": return <Structure smiles={d.smiles} title={d.pref_name ?? d.molecule_chembl_id} width={112} height={60} />;
      case "pref_name": return <><button className="row-open" type="button" onClick={event => { event.stopPropagation(); onFocus({ kind: "drug", id: d.molecule_chembl_id }); }}>{d.pref_name ?? d.molecule_chembl_id}</button><div className="clinical-id"><ChemblLink kind="compound" id={d.molecule_chembl_id} /></div></>;
      case "max_phase_tb": return phaseLabel(d.max_phase_tb);
      case "first_approval": return d.first_approval ?? "—";
      case "n_trials": return d.n_trials.toLocaleString();
      case "genes": return <span className="chips">{d.genes.length ? d.genes.map(g => <GeneChip key={g.rv_id} rv={g.rv_id} name={g.gene_name} onSelect={onSelectGene} />) : "—"}</span>;
      case "mechanisms_of_action": return <span className="clinical-clamp" title={d.mechanisms_of_action.join("; ")}>{d.mechanisms_of_action.join("; ") || "None recorded"}</span>;
    }
  }
  function trialCell(t: Trial, key: string) {
    switch (key) {
      case "nct_id": return <button className="row-open mono" type="button" onClick={event => { event.stopPropagation(); onFocus({ kind: "trial", id: t.nct_id }); }}>{t.nct_id}</button>;
      case "brief_title": return <span className="clinical-clamp" title={t.brief_title ?? undefined}>{t.acronym && <strong>{t.acronym} · </strong>}{t.brief_title ?? "—"}</span>;
      case "phase_max": return trialPhase(t.phases);
      case "status": return <span className="clinical-status">{status(t.status)}</span>;
      case "start_date": return t.start_date ?? "—";
      case "enrollment": return t.enrollment?.toLocaleString() ?? "—";
      case "drugs": { const names = t.drugs.map(d => d.pref_name ?? d.molecule_chembl_id).join(", "); return <span className="clinical-clamp" title={names}>{names || "—"}</span>; }
    }
  }
  if (error) return <div className="errbox">{error}</div>;
  return (
    <div className={`body clinical${focus ? " detail-open" : ""}`}>
      <FilterRail label="Clinical filters">
        <div className="rail-heading"><InterfaceIcon name="clinical" /><h2>Clinical explorer</h2></div>
        <p className="clinical-count" aria-live="polite"><strong>{count.toLocaleString()}</strong> / {(isDrug ? drugs : trials).length.toLocaleString()} {isDrug ? "drugs & candidates" : "trials"}</p>
        <div className="group clinical-phases">
          <p className="lab">{isDrug ? "Highest phase for TB" : "Study phase"}</p>
          <div className="seg">
            {PHASES.map(([phase, label]) => <button key={phase} type="button" aria-pressed={phases.has(phase)} onClick={() => toggle(phases, phase, setPhases)}>
              <span className="name">{isDrug ? label : label.replace("Approved for TB", "Phase 4")}</span>
              <span className="c">{isDrug ? drugs.filter(d => Math.floor(d.max_phase_tb ?? -1) === phase).length : trials.filter(t => Math.floor(t.phase_max ?? -1) === phase).length}</span>
            </button>)}
          </div>
        </div>
        <details className="group filtergroup" open>
          <summary>Restrict to <span className="filtercount">{isDrug ? flags.size ? `${flags.size} selected` : "" : linkedOnly ? "1 selected" : ""}</span></summary>
          <div className="seg">{isDrug ? DRUG_FLAGS.map(([key, label, test]) => <button key={key} type="button" aria-pressed={flags.has(key)} onClick={() => toggle(flags, key, setFlags)}><span className="name">{label}</span><span className="c">{drugs.filter(test).length}</span></button>) : <button type="button" aria-pressed={linkedOnly} onClick={() => setLinkedOnly(v => !v)}><span className="name">Linked to a TB drug</span><span className="c">{trials.filter(t => t.drugs.length).length}</span></button>}</div>
        </details>
        {!isDrug && <details className="group filtergroup"><summary>Status <span className="filtercount">{statuses.size ? `${statuses.size} selected` : ""}</span></summary><div className="seg">{trialStatuses.map(([value, n]) => <button key={value} type="button" aria-pressed={statuses.has(value)} onClick={() => toggle(statuses, value, setStatuses)}><span className="name">{status(value)}</span><span className="c">{n}</span></button>)}</div></details>}
        <details className="group sources filtergroup"><summary>Sources & coverage</summary><p className="note">{isDrug ? chemblSource(meta) : trialSource(meta)}</p>{isDrug && <p className="note">ChEMBL’s TB indications include host-directed adjuncts, HIV co-medications and placebo excipients from trial records. “Placed on an Mtb gene” is on by default.</p>}</details>
        <button className="clear-filters" type="button" disabled={!phases.size && (isDrug ? !flags.size : !statuses.size && !linkedOnly)} onClick={clearFilters}>Clear filters</button>
      </FilterRail>
      <main className="col canvascol">
        <div className="clinical-toolbar">
          <div className="tabs" aria-label="Clinical datasets">
            <button type="button" aria-pressed={isDrug} onClick={() => setTab("drugs")}>Drugs & candidates</button>
            <button type="button" aria-pressed={!isDrug} onClick={() => setTab("trials")}>Trials</button>
          </div>
          <TableControls key={tab} columns={allColumns} groups={groups} visible={columns} preferences={settings.preferences} saved={settings.saved} onChange={settings.change} identity={isDrug ? "pref_name" : "nct_id"} recordLabel={tab} defaultNote="" />
        </div>
        <div className="scroller clinical-scroller" key={tab}>
          <table className={`clinical-table ${isDrug ? "drug-table" : "trial-table"}`} aria-label={isDrug ? "TB drugs and candidates" : "TB clinical trials"}>
            <thead>
              <tr className="column-groups">{groups.map(group => { const span = columns.filter(([key]) => group.keys.includes(key)).length; return span ? <th key={group.label} scope="colgroup" colSpan={span}>{group.label}</th> : null; })}</tr>
              <tr>{columns.map(([key, label, numeric]) => <th key={key} scope="col" className={numeric ? "n" : undefined} aria-sort={sort?.key === key ? sort.order === "asc" ? "ascending" : "descending" : undefined}>
                {key === "structure" ? label : <button className="sortbutton" type="button" onClick={() => setSort(current => ({ key, order: current?.key === key ? current.order === "asc" ? "desc" : "asc" : numeric ? "desc" : "asc" }))}>{label}<span className="sorticon" aria-hidden="true">{sort?.key === key ? sort.order === "asc" ? "↑" : "↓" : "↕"}</span></button>}
              </th>)}</tr>
            </thead>
            <tbody>
              {isDrug ? sortedDrugs.map(d => <tr key={d.molecule_chembl_id} aria-selected={focus?.kind === "drug" && focus.id === d.molecule_chembl_id} onClick={() => onFocus({ kind: "drug", id: d.molecule_chembl_id })}>
                {columns.map(([key, , numeric]) => <td key={key} data-column={key} className={numeric ? "n" : undefined} style={cellFormatting(d, key, settings.preferences.rules, drugRanges)}>{drugCell(d, key)}</td>)}
              </tr>) : sortedTrials.slice(0, TRIAL_ROWS).map(t => <tr key={t.nct_id} aria-selected={focus?.kind === "trial" && focus.id === t.nct_id} onClick={() => onFocus({ kind: "trial", id: t.nct_id })}>
                {columns.map(([key, , numeric]) => <td key={key} data-column={key} className={numeric ? "n" : undefined} style={cellFormatting(t, key, settings.preferences.rules, trialRanges)}>{trialCell(t, key)}</td>)}
              </tr>)}
              {!count && <tr><td className="clinical-empty" colSpan={columns.length}>{loading ? "Loading clinical evidence…" : "No matching records. Clear filters to see all records."}</td></tr>}
            </tbody>
          </table>
        </div>
        {!isDrug && count > TRIAL_ROWS && <div className="clinical-limit">Showing the first {TRIAL_ROWS} of {count.toLocaleString()} matching trials. Use filters or sort to narrow the view.</div>}
      </main>

      <aside className="col detailcol">
        <button
          className="closedetail"
          type="button"
          title="Close and widen the table (Esc)"
          aria-label="Close detail"
          onClick={() => onFocus(null)}
        >
          ×
        </button>
        {focus?.kind === "compound" ? (
          <CompoundPanel id={focus.id} onFocus={onFocus} onSelectGene={onSelectGene} />
        ) : focus?.kind === "drug" ? (
          <DrugPanel id={focus.id} meta={meta} onFocus={onFocus} onSelectGene={onSelectGene} />
        ) : focus?.kind === "trial" ? (
          <TrialPanel id={focus.id} meta={meta} onFocus={onFocus} onSelectGene={onSelectGene} />
        ) : (
          <div className="empty">Pick a drug or a trial.</div>
        )}
      </aside>
    </div>
  );
}

function useLoaded<T>(load: () => Promise<T>, key: string): [T | null, string | null] {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setValue(null);
    setError(null);
    load()
      .then(setValue)
      .catch((e: unknown) => setError(String(e)));
    // Keyed on the id alone: `load` is a fresh closure every render.
  }, [key]);
  return [value, error];
}

/** The best measured pChEMBL, or null when none of them carries one. */
function bestOf(activities: { pchembl_value: number | null }[]): number | null {
  const values = activities
    .map((a) => a.pchembl_value)
    .filter((v): v is number => v !== null && v !== undefined);
  return values.length ? Math.max(...values) : null;
}

function CompoundPanel({
  id,
  onFocus,
  onSelectGene,
}: {
  id: string;
  onFocus: (focus: Focus) => void;
  onSelectGene: (rv: string) => void;
}) {
  const [compound, error] = useLoaded<CompoundDetail>(() => api.compound(id), id);
  if (error) return <div className="errbox">{error}</div>;
  if (!compound) return <div className="empty">Loading {id}…</div>;

  const number = (v: number | null | undefined, d = 2) =>
    v === null || v === undefined ? "—" : v.toFixed(d);

  return (
    <>
      <div className="detailhead">
        <div className="row">
          <span className="gn">{compound.pref_name ?? compound.molecule_chembl_id}</span>
          <span className="rv">{compound.molecule_chembl_id}</span>
        </div>
        <p>
          {compound.drug ? (
            <button
              type="button"
              className="chip accent"
              onClick={() => onFocus({ kind: "drug", id: compound.molecule_chembl_id })}
            >
              {phaseLabel(compound.drug.max_phase_tb)} for TB — open the drug
            </button>
          ) : (
            <span className="dim">Not a molecule with a TB indication in ChEMBL.</span>
          )}
        </p>
      </div>
      <div className="panel">
        <Section label="Acts on" source="ChEMBL bioactivity · CC BY-SA 3.0">
          {compound.genes.length === 0 ? (
            <span className="absent">No protein-level activity is linked to an Mtb gene in this dataset</span>
          ) : (
            <table>
              <tbody>
                {compound.genes.map((g) => (
                  <tr key={g.rv_id} onClick={() => onSelectGene(g.rv_id)}>
                    <td className="id">{g.gene_name ?? g.rv_id}</td>
                    <td className="n">{number(g.best_pchembl)}</td>
                    <td className="dim">{g.essentiality ?? "—"}</td>
                    <td>
                      {g.evidence === "orthologue" && (
                        <span className="chip ortho" title={g.via_organism ?? ""}>
                          orthologue
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="note">
            Best pChEMBL per gene. Orthologue measurements come from a related mycobacterial protein;
            binding-site similarity has not been assessed.
          </div>
        </Section>

        <Section label="Whole-cell potency" source="ChEMBL bioactivity · CC BY-SA 3.0">
          {compound.whole_cell.length === 0 ? (
            <span className="absent">no whole-cell measurement for this compound</span>
          ) : (
            <>
              <span className="big">
                {number(bestOf(compound.whole_cell))}
              </span>{" "}
              <span className="dim">best of {compound.whole_cell.length} measurements</span>
            </>
          )}
          <div className="note">
            Measured against the whole organism. This measurement alone does not identify the target protein.
          </div>
        </Section>

        {/* Where a zero becomes provable: "tested in a 215,098-compound library and
            inactive" is a measurement, and the only public source that records it.
            A row with no call is printed as that, never as inactive. */}
        <Section label="Tested in" source="PubChem BioAssay + ChEMBL campaigns">
          {compound.tested_in.length === 0 ? (
            <span className="absent">No screening result for this compound in the included campaigns</span>
          ) : (
            <>
              <div className="scroller" style={{ maxHeight: 320 }}>
                <table>
                  <thead>
                    <tr>
                      <th>Campaign</th>
                      <th>Stage</th>
                      <th>Outcome</th>
                      <th>Measurement</th>
                    </tr>
                  </thead>
                  <tbody>
                    {compound.tested_in.map((row, i) => (
                      <tr key={`${row.stage_id}-${row.activity_id ?? row.pubchem_sid ?? i}`}>
                        <td>
                          <span className="clinical-clamp" title={row.screen_title ?? undefined}>
                            {row.screen_title ?? row.screen_id}
                          </span>
                        </td>
                        <td className="dim">{row.derived ? "derived" : row.stage ?? "—"}</td>
                        <td className={row.outcome ? undefined : "dim"}>
                          {row.outcome ?? "no call stated"}
                        </td>
                        <td className="dim">
                          {row.standard_value === null
                            ? row.activity_comment ?? "—"
                            : `${row.endpoint ?? ""} ${
                                row.standard_relation && row.standard_relation !== "=" ? row.standard_relation : ""
                              }${row.standard_value} ${row.standard_units ?? ""}`.trim()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="note">
                No reported activity outcome means the source did not classify this result as active,
                inactive or inconclusive.
              </div>
            </>
          )}
        </Section>

        <Section label="Properties" source="ChEMBL · CC BY-SA 3.0">
          <div className="ids">
            <span>MW {number(compound.mw, 0)}</span>
            <span>cLogP {number(compound.alogp, 1)}</span>
            <span>TPSA {number(compound.psa, 0)}</span>
            <span>HBD {compound.hbd ?? "—"}</span>
            <span>HBA {compound.hba ?? "—"}</span>
            <span>Ro5 violations {compound.ro5_violations ?? "—"}</span>
            {compound.qed !== null && <span>QED {number(compound.qed, 2)}</span>}
          </div>
          {compound.smiles && <div className="note mono">{compound.smiles}</div>}
        </Section>
      </div>
    </>
  );
}

function DrugPanel({
  id,
  meta,
  onFocus,
  onSelectGene,
}: {
  id: string;
  meta: Meta | null;
  onFocus: (focus: Focus) => void;
  onSelectGene: (rv: string) => void;
}) {
  const [drug, error] = useLoaded<DrugDetail>(() => api.drug(id), id);
  if (error) return <div className="errbox">{error}</div>;
  if (!drug) return <div className="empty">Loading {id}…</div>;

  const group = (link: DrugLink) => drug.genes.filter((g) => g.link === link);
  const complex = group("mechanism_complex");
  const mtbMechanism = drug.mechanisms.some((m) => m.component_accessions.length && drug.genes.some((g) => g.link.startsWith("mechanism")));

  return (
    <>
      <div className="detailhead">
        <div className="row">
          <span className="gn">{drug.pref_name ?? drug.molecule_chembl_id}</span>
          <ChemblLink kind="compound" id={drug.molecule_chembl_id} />
        </div>
        <p>
          <span className={`chip ${drug.max_phase_tb !== null && drug.max_phase_tb >= 4 ? "accent" : "ortho"}`}>
            {phaseLabel(drug.max_phase_tb)} for TB
          </span>{" "}
          {drug.max_phase !== null && drug.max_phase !== drug.max_phase_tb && (
            <span className="chip">{phaseLabel(drug.max_phase)} for any indication</span>
          )}{" "}
          {drug.first_approval && <span className="dim">first approved {drug.first_approval}</span>}
        </p>
        {/* The molecule itself, where a reader arrives: a name and a phase say
            nothing about what it is, and these are the compounds people are
            deciding whether to work on. */}
        <div className="headstruct">
          <Structure
            smiles={drug.smiles}
            title={drug.pref_name ?? drug.molecule_chembl_id}
            width={230}
            height={130}
          />
          <div className="note">
            {drug.mw ? `MW ${Math.round(drug.mw)}` : null}
            {drug.alogp !== null && drug.alogp !== undefined ? ` · cLogP ${drug.alogp.toFixed(1)}` : null}
            {drug.inchi_key && (
              <>
                <br />
                <span className="faint">{drug.inchi_key}</span>
              </>
            )}
          </div>
        </div>
      </div>
      <div className="panel">
        <Section label="Mechanism of action" source={chemblSource(meta)}>
          {drug.mechanisms.length === 0 ? (
            <span className="absent">ChEMBL records no mechanism for this molecule</span>
          ) : (
            drug.mechanisms.map((m, index) => (
              <div key={`${m.target_chembl_id}-${index}`} style={{ marginBottom: 8 }}>
                <div>
                  <b>{m.mechanism_of_action ?? "—"}</b>{" "}
                  {m.target_type && m.target_type !== "SINGLE PROTEIN" && (
                    <span className="chip">{m.target_type.toLowerCase()}</span>
                  )}
                </div>
                <div className="note">
                  {m.target_name} · <span className="mono">{m.target_chembl_id ?? "no target"}</span> ·{" "}
                  <i>{m.target_organism ?? "organism not stated"}</i>
                  {m.component_accessions.length > 1 && ` · ${m.component_accessions.length} components`}
                </div>
                {m.mechanism_comment && <div className="note">{m.mechanism_comment}</div>}
                {m.refs.length > 0 && (
                  <div className="ids" style={{ marginTop: 4 }}>
                    {m.refs.slice(0, 6).map((r) => (
                      <span key={`${r.type}-${r.id}`}>
                        {/* Some ids are whole URLs; the link already carries them. */}
                        {r.url ? (
                          <a href={r.url} target="_blank" rel="noreferrer">
                            {r.type} {r.id.startsWith("http") ? "" : r.id}
                          </a>
                        ) : (
                          `${r.type} ${r.id}`
                        )}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
          {drug.mechanisms.length > 0 && !mtbMechanism && (
            <p className="caveat">
              These ChEMBL mechanism targets do not match a protein in the <i>M. tuberculosis</i> reference proteome.
            </p>
          )}
        </Section>

        <Section label="Genes" source={`${chemblSource(meta)} · ${SOURCE.bosch} · ${SOURCE.who}`}>
          {drug.genes.length === 0 && <span className="absent">No Mtb gene association is recorded in the included sources</span>}
          {(["mechanism", "bosch_2021"] as DrugLink[]).map((link) =>
            group(link).length ? (
              <div key={link} style={{ marginBottom: 6 }}>
                <div className="note">{link === "mechanism" ? "Acts on (ChEMBL mechanism)" : "Annotated target (Bosch 2021)"}</div>
                <div className="chips">
                  {group(link).map((g) => (
                    <GeneChip key={g.rv_id} rv={g.rv_id} name={g.gene_name} onSelect={onSelectGene} />
                  ))}
                </div>
              </div>
            ) : null,
          )}
          {complex.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div className="note">
                Members of the target complex ({complex.length}). Binding to individual subunits is not established by this record.
              </div>
              <div className="chips">
                {complex.slice(0, 24).map((g) => (
                  <GeneChip key={g.rv_id} rv={g.rv_id} name={g.gene_name} onSelect={onSelectGene} />
                ))}
                {complex.length > 24 && <span className="dim">+{complex.length - 24}</span>}
              </div>
            </div>
          )}
          {group("who_resistance").length > 0 && (
            <div>
              <div className="note">WHO resistance associations</div>
              <div className="chips">
                {group("who_resistance").map((g) => (
                  <button key={g.rv_id} type="button" className="chip warn" onClick={() => onSelectGene(g.rv_id)}>
                    {g.gene_name ?? g.rv_id} · {g.n_variants}
                  </button>
                ))}
              </div>
            </div>
          )}
        </Section>

        {(drug.bioactivity.n_protein > 0 || drug.bioactivity.n_whole_cell > 0) && (
          <Section label="Bioactivity in the atlas" source="ChEMBL · CC BY-SA 3.0">
            <div className="note" style={{ color: "var(--fg)" }}>
              {drug.bioactivity.n_protein} protein-level measurements on Mtb targets
              {drug.bioactivity.best_protein_pchembl !== null && `, best pChEMBL ${drug.bioactivity.best_protein_pchembl.toFixed(2)}`}
              {drug.bioactivity.n_whole_cell > 0 &&
                ` · ${drug.bioactivity.n_whole_cell} whole-cell, ${
                  drug.bioactivity.best_whole_cell_pchembl === null
                    ? "none with a pChEMBL value"
                    : `best pChEMBL ${drug.bioactivity.best_whole_cell_pchembl.toFixed(2)}`
                }`}
            </div>
          </Section>
        )}

        <Section label={`Trials (${drug.trials.length})`} source={trialSource(meta)}>
          {drug.trials.length === 0 ? (
            <span className="absent">No interventional TB trial is linked to this drug in the atlas</span>
          ) : (
            <div className="scroller" style={{ maxHeight: 340 }}>
              <table>
                <tbody>
                  {drug.trials.map((t) => (
                    <tr key={t.nct_id} onClick={() => onFocus({ kind: "trial", id: t.nct_id })} title={t.brief_title ?? ""}>
                      <td className="id">{t.nct_id}</td>
                      <td className="dim">{trialPhase(t.phases)}</td>
                      <td className="dim">{status(t.status)}</td>
                      <td className="mono dim">{t.start_date ?? "—"}</td>
                      <td>
                        {t.via_chembl_ref && <span className="chip ok">ChEMBL ref</span>}{" "}
                        {t.via_intervention_name && <span className="chip ortho">name</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="note">
            &ldquo;ChEMBL ref&rdquo; is ChEMBL&rsquo;s own curated trial link; &ldquo;name&rdquo; is an exact
            match of an intervention name to one of this drug&rsquo;s ChEMBL names.
          </div>
        </Section>

        <Section label="Identity">
          <div className="ids">
            {drug.atc_codes.map((c) => (
              <span key={c}>ATC {c}</span>
            ))}
            {drug.tb_indications.map((i) => (
              <span key={i}>{i}</span>
            ))}
          </div>
          {drug.synonyms.length > 0 && (
            <div className="note">Also known as {drug.synonyms.slice(0, 12).join(", ")}{drug.synonyms.length > 12 ? "…" : ""}</div>
          )}
          {drug.label_refs.length > 0 && (
            <div className="ids" style={{ marginTop: 5 }}>
              {drug.label_refs.slice(0, 6).map((r) => (
                <span key={`${r.type}-${r.id}`}>{r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.type}</a> : r.type}</span>
              ))}
            </div>
          )}
        </Section>
      </div>
    </>
  );
}

function TrialPanel({
  id,
  meta,
  onFocus,
  onSelectGene,
}: {
  id: string;
  meta: Meta | null;
  onFocus: (focus: Focus) => void;
  onSelectGene: (rv: string) => void;
}) {
  const [trial, error] = useLoaded<TrialDetail>(() => api.trial(id), id);
  if (error) return <div className="errbox">{error}</div>;
  if (!trial) return <div className="empty">Loading {id}…</div>;

  return (
    <>
      <div className="detailhead">
        <div className="row">
          <span className="rv">{trial.nct_id}</span>
          {trial.acronym && <span className="gn">{trial.acronym}</span>}
        </div>
        <p>{trial.brief_title}</p>
        <p>
          <span className="chip ortho">{trialPhase(trial.phases)}</span> <span className="chip">{status(trial.status)}</span>{" "}
          {trial.has_results && <span className="chip ok">results posted</span>}{" "}
          <a href={trialUrl(trial.nct_id)} target="_blank" rel="noreferrer">
            ClinicalTrials.gov ↗
          </a>
        </p>
      </div>
      <div className="panel">
        <Section label="Drugs linked" source={chemblSource(meta)}>
          {trial.drugs.length === 0 ? (
            <span className="absent">
              No drug link was found through ChEMBL trial references or matching intervention names
            </span>
          ) : (
            trial.drugs.map((d) => (
              <div key={d.molecule_chembl_id} className="note" style={{ color: "var(--fg)" }}>
                <button type="button" className="chip accent" onClick={() => onFocus({ kind: "drug", id: d.molecule_chembl_id })}>
                  {d.pref_name}
                </button>{" "}
                {phaseLabel(d.max_phase_tb)} for TB · {d.via_chembl_ref && "ChEMBL ref"}
                {d.via_chembl_ref && d.via_intervention_name && " · "}
                {d.via_intervention_name && `name: ${d.matched_names.join(", ")}`}
              </div>
            ))
          )}
          {trial.genes.length > 0 && (
            <div style={{ marginTop: 6 }}>
              <div className="note">Genes those drugs act on</div>
              <div className="chips">
                {trial.genes.map((g) => (
                  <GeneChip key={g.rv_id} rv={g.rv_id} name={g.gene_name} onSelect={onSelectGene} />
                ))}
              </div>
            </div>
          )}
        </Section>

        <Section label="Arms and interventions" source={trialSource(meta)}>
          {trial.arms.length === 0 ? (
            trial.interventions.map((i, index) => (
              <div className="note" key={index}>
                <span className="mono">{(i.type ?? "").toLowerCase()}</span> {i.name}
              </div>
            ))
          ) : (
            trial.arms.map((arm, index) => (
              <div key={index} style={{ marginBottom: 6 }}>
                <div>
                  <b>{arm.label}</b> <span className="dim">{(arm.type ?? "").toLowerCase().replace(/_/g, " ")}</span>
                </div>
                <div className="note">{arm.interventions.join(" · ")}</div>
              </div>
            ))
          )}
        </Section>

        <Section label="Study">
          <div className="note" style={{ color: "var(--fg)" }}>
            {trial.enrollment ? `${trial.enrollment.toLocaleString()} participants` : "enrolment not stated"} ·{" "}
            {(trial.primary_purpose ?? "purpose not stated").toLowerCase()} ·{" "}
            {(trial.allocation ?? "allocation not stated").toLowerCase().replace(/_/g, " ")}
          </div>
          <div className="note">
            start {trial.start_date ?? "—"} · primary completion {trial.primary_completion_date ?? "—"} · completion{" "}
            {trial.completion_date ?? "—"}
          </div>
          {trial.why_stopped && <p className="caveat">Stopped: {trial.why_stopped}</p>}
          <div className="note">
            {trial.lead_sponsor} {trial.sponsor_class && `(${trial.sponsor_class.toLowerCase()})`}
            {trial.collaborators.length > 0 && ` with ${trial.collaborators.join(", ")}`}
          </div>
          {trial.countries.length > 0 && <div className="note">{trial.countries.join(", ")}</div>}
          <div className="ids" style={{ marginTop: 5 }}>
            {trial.conditions.map((c) => (
              <span key={c}>{c}</span>
            ))}
          </div>
        </Section>
      </div>
    </>
  );
}
