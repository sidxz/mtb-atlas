/**
 * The screening end of the atlas, as two views: the campaigns that were run,
 * and what was measured on the compounds that came out of them.
 *
 * A BARE MOCK, to settle the arrangement before the real build. It reuses the
 * clinical view's classes rather than styling of its own.
 *
 * Two rules the arrangement exists to keep: an actives count is never divided
 * by a screen count (974 of 999 campaigns state no call, so there is nothing
 * to divide), and 71 genes of 4,031 have a screen on their own protein, which
 * is the finding rather than a gap.
 */

import { useEffect, useState } from "react";
import { FilterRail } from "./FilterRail";
import { InterfaceIcon } from "./InterfaceIcon";
import { TableControls, useTablePreferences, type Column } from "./TableControls";
import { ChemblLink, Structure } from "./Structure";
import {
  api,
  type HitPage,
  type HitProfile,
  type ScreenDetail,
  type ScreenPage,
  type ScreenResult,
  type ScreenStage,
  type ScreenSummary,
} from "./api";

/** Funnel order. A derived row is a computed ratio and holds no funnel position. */
const STAGE_ORDER = ["primary", "confirmatory", "counter_screen", "profiling"];

/** What the API will sort on. Anything else is a column you can show but not order by. */
const SORTABLE_SCREENS = new Set(["screen_id", "year", "n_tested", "n_active", "n_stages"]);

const MODALITY_LABEL: Record<string, string> = {
  phenotypic_mtb: "whole-cell Mtb",
  biochemical_mtb: "Mtb protein",
  mammalian_cytotox: "mammalian cytotoxicity",
  adme: "ADME/PK",
  in_vivo_efficacy: "animal efficacy",
  other_pathogen: "another pathogen",
  other: "unclassified",
};

function count(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString();
}

type Sort = { key: string; order: "asc" | "desc" };

/** A page at a time, because `screen_results` is 5.4M rows and `/hits` is 23,730.
 *
 * Sorting and filtering both run on the server for the same reason: sorting the
 * hundred rows that happen to be loaded would answer a different question from
 * the one the column header asks.
 */
const PAGE = 100;

function Pager({ total, offset, onOffset, label }: {
  total: number;
  offset: number;
  onOffset: (next: number) => void;
  label: string;
}) {
  if (!total) return null;
  const last = Math.max(0, Math.floor((total - 1) / PAGE) * PAGE);
  return (
    <div className="pager">
      <span className="dim">
        {(offset + 1).toLocaleString()}–{Math.min(offset + PAGE, total).toLocaleString()} of{" "}
        {total.toLocaleString()} {label}
      </span>
      <button type="button" className="minibtn" disabled={offset === 0} onClick={() => onOffset(0)}>
        ⇤ First
      </button>
      <button type="button" className="minibtn" disabled={offset === 0}
              onClick={() => onOffset(Math.max(0, offset - PAGE))}>
        ← Previous
      </button>
      <button type="button" className="minibtn" disabled={offset >= last}
              onClick={() => onOffset(offset + PAGE)}>
        Next →
      </button>
    </div>
  );
}

/** A header that sorts on the server, so it sorts the population and not the page. */
function SortHeader({ sort, onSort, column, label, numeric }: {
  sort: Sort;
  onSort: (next: Sort) => void;
  column: string;
  label: string;
  numeric?: boolean;
}) {
  const active = sort.key === column;
  return (
    <th scope="col" className={numeric ? "n" : undefined}
        aria-sort={active ? (sort.order === "asc" ? "ascending" : "descending") : undefined}>
      <button className="sortbutton" type="button"
              onClick={() => onSort({
                key: column,
                order: active ? (sort.order === "asc" ? "desc" : "asc") : numeric ? "desc" : "asc",
              })}>
        {label}
        <span className="sorticon" aria-hidden="true">{active ? (sort.order === "asc" ? "↑" : "↓") : "↕"}</span>
      </button>
    </th>
  );
}

/** A stated zero and an absent call are different answers and must not look alike. */
function actives(screen: ScreenSummary): string {
  if (!screen.outcome_stated) return "no call stated";
  if (screen.n_active === null) return "per stage";
  return screen.n_active.toLocaleString();
}

function measurement(row: ScreenResult): string {
  if (row.standard_value === null) return row.activity_comment ?? "—";
  const relation = row.standard_relation && row.standard_relation !== "=" ? row.standard_relation : "";
  return `${row.endpoint ?? ""} ${relation}${row.standard_value} ${row.standard_units ?? ""}`.trim();
}

// --- the campaign page -------------------------------------------------------

function StageLadder({ stages }: { stages: ScreenStage[] }) {
  const ladder = [...stages].sort(
    (a, b) => STAGE_ORDER.indexOf(a.stage ?? "zz") - STAGE_ORDER.indexOf(b.stage ?? "zz"),
  );
  return (
    <table className="clinical-table">
      <thead>
        <tr>
          <th scope="col">Stage</th>
          <th scope="col">Measured</th>
          <th scope="col">Endpoints</th>
          <th scope="col" className="n">Rows</th>
          <th scope="col" className="n">Compounds</th>
          <th scope="col" className="n">Active</th>
          <th scope="col" className="n">Inactive</th>
          <th scope="col" className="n">No call</th>
        </tr>
      </thead>
      <tbody>
        {ladder.map(stage => (
          <tr key={stage.stage_id}>
            <td>
              {stage.derived ? "derived" : stage.stage ?? "—"}
              <div className="clinical-id mono">{stage.stage_id}</div>
            </td>
            <td>
              <span className="clinical-clamp" title={stage.description ?? undefined}>
                {stage.modality ? MODALITY_LABEL[stage.modality] ?? stage.modality : "unclassified"}
              </span>
              {stage.strain && <div className="clinical-id">{stage.strain}</div>}
            </td>
            <td className="dim">{stage.endpoints?.length ? stage.endpoints.join(", ") : "—"}</td>
            <td className="n">{count(stage.n_rows)}</td>
            <td className="n">{count(stage.n_compounds)}</td>
            <td className="n">{count(stage.n_active_rows)}</td>
            <td className="n">{count(stage.n_inactive_rows)}</td>
            <td className="n">{count(stage.n_no_call_rows)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Results({ screenId, outcome }: { screenId: string; outcome: string }) {
  const [page, setPage] = useState<{ total: number; items: ScreenResult[]; n_with_structure: number } | null>(null);
  useEffect(() => {
    setPage(null);
    api.screenResults(screenId, { outcome }).then(setPage, () => setPage(null));
  }, [screenId, outcome]);
  if (!page) return <p className="note">Loading…</p>;
  if (!page.items.length) return <p><span className="absent">none</span></p>;
  return (
    <>
      <p className="note">
        {page.total.toLocaleString()} rows, showing {page.items.length}.{" "}
        {page.n_with_structure.toLocaleString()} of them have a structure in the atlas.
      </p>
      <table className="clinical-table">
        <thead>
          <tr>
            <th scope="col">Structure</th>
            <th scope="col">Compound</th>
            <th scope="col">Stage</th>
            <th scope="col">Measurement</th>
            <th scope="col" className="n">Score</th>
          </tr>
        </thead>
        <tbody>
          {page.items.map(row => (
            <tr key={`${row.stage_id}-${row.pubchem_sid ?? row.molecule_chembl_id}-${row.activity_id ?? row.endpoint ?? ""}`}>
              <td>{row.smiles ? <Structure smiles={row.smiles} width={112} height={60} title={row.molecule_chembl_id ?? undefined} /> : <span className="dim">—</span>}</td>
              <td>
                {row.molecule_chembl_id
                  ? <ChemblLink kind="compound" id={row.molecule_chembl_id} label={row.pref_name ?? row.molecule_chembl_id} />
                  : <span className="mono dim">SID {row.pubchem_sid}</span>}
              </td>
              <td className="dim">{row.stage ?? "—"}</td>
              <td>{measurement(row)}</td>
              <td className="n dim">{row.activity_score ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function CampaignPage({ id, onBack, onSelectGene }: {
  id: string;
  onBack: () => void;
  onSelectGene?: (rvId: string) => void;
}) {
  const [detail, setDetail] = useState<ScreenDetail | null>(null);
  const [outcome, setOutcome] = useState("active");
  useEffect(() => {
    setDetail(null);
    api.screen(id).then(setDetail, () => setDetail(null));
  }, [id]);

  if (!detail) return <main className="col canvascol screen-page"><p className="note">Loading campaign…</p></main>;
  const called = detail.stages.reduce(
    (n, s) => n + (s.n_active_rows ?? 0) + (s.n_inactive_rows ?? 0) + (s.n_inconclusive_rows ?? 0),
    0,
  );
  const own = detail.genes.filter(g => g.own);
  const complex = detail.genes.filter(g => !g.own);
  const outcomes: [string, string][] = [
    ["active", "Active"],
    ["inconclusive", "Inconclusive"],
    ["inactive", "Inactive"],
    ["no_call", "No call stated"],
  ];
  return (
    <main className="col canvascol screen-page">
      <button type="button" className="row-open" onClick={onBack}>← All campaigns</button>
      <h2>{detail.title ?? detail.screen_id}</h2>
      <p className="note">
        {detail.depositor ?? "unknown depositor"} · {detail.source}
        {detail.year ? ` · ${detail.year}` : ""} · <span className="mono">{detail.screen_id}</span>
        {detail.document_chembl_id && <> · <ChemblLink kind="document" id={detail.document_chembl_id} /></>}
      </p>

      <div className="screen-facts">
        <div className="ev">
          <span className="k">Deposited</span>
          <span>{count(detail.n_tested)} {detail.source === "pubchem" ? "substances" : "compounds"}</span>
        </div>
        {detail.library_size_stated !== null && (
          <div className="ev">
            <span className="k">Prose says</span>
            <span>{count(detail.library_size_stated)} compounds</span>
            <span className="src">the depositor's own figure; not substituted for what was deposited</span>
          </div>
        )}
        <div className="ev">
          <span className="k">Actives</span>
          <span>{actives(detail)}</span>
        </div>
        <div className="ev">
          <span className="k">Stages</span>
          <span>{detail.n_stages}</span>
        </div>
      </div>

      <h3>Stage ladder</h3>
      <StageLadder stages={detail.stages} />
      <p className="caveat">Counts are per stage, never summed across them.</p>
      {/* The deposit's summary and its own rows can disagree, and that is recorded
          rather than resolved: picking one would hide a real conflict in the source. */}
      {!detail.outcome_stated && called > 0 && (
        <p className="caveat">
          This deposit&rsquo;s summary states no activity call, yet {called.toLocaleString()} of its
          rows carry one. Both are shown as the source gives them; the atlas does not pick a winner.
        </p>
      )}

      <h3>Genes reached</h3>
      {own.length ? (
        <div className="chips">
          {own.map(g => (
            <button type="button" className="chip accent" key={g.rv_id} onClick={() => onSelectGene?.(g.rv_id)}>
              {g.gene_name ?? g.rv_id}
            </button>
          ))}
        </div>
      ) : (
        <p><span className="absent">no gene's own protein</span></p>
      )}
      {complex.length > 0 && (
        <>
          <div className="chips">
            {complex.map(g => (
              <button type="button" className="chip warn" key={g.rv_id} onClick={() => onSelectGene?.(g.rv_id)}>
                {g.gene_name ?? g.rv_id}
              </button>
            ))}
          </div>
          <p className="caveat">Reached as part of a complex. Shown, never counted as the gene's own.</p>
        </>
      )}
      {detail.unplaced_targets.map(t => (
        <p className="note" key={t.accession ?? t.name}>
          <span className="mono">{t.accession}</span> {t.name}
          <span className="src">not keyed to a locus ({t.accession_kind ?? "unknown"}), so no gene carries this screen</span>
        </p>
      ))}

      <h3>Compounds</h3>
      <div className="tabs" aria-label="Outcome">
        {outcomes.map(([value, label]) => (
          <button key={value} type="button" aria-pressed={outcome === value} onClick={() => setOutcome(value)}>{label}</button>
        ))}
      </div>
      <Results screenId={id} outcome={outcome} />
    </main>
  );
}

// [key, label, numeric]. `screen_id` is the identity column and is always shown.
const SCREEN_COLUMNS: Column[] = [
  ["screen_id", "Campaign", false],
  ["depositor", "Depositor", false],
  ["source", "Source", false],
  ["year", "Year", true],
  ["n_tested", "Tested", true],
  ["library_size_stated", "Prose says", true],
  ["n_active", "Actives", true],
  ["n_inactive", "Inactive", true],
  ["n_stages", "Stages", true],
  ["modalities", "Measured", false],
  ["genes", "Genes reached", false],
];
const SCREEN_GROUPS = [
  { label: "Campaign", keys: ["screen_id", "depositor", "source", "year"] },
  { label: "Size", keys: ["n_tested", "library_size_stated", "n_stages"] },
  { label: "Outcome", keys: ["n_active", "n_inactive"] },
  { label: "Reach", keys: ["modalities", "genes"] },
];

function campaignCell(screen: ScreenSummary, key: string, onOpen: (id: string) => void) {
  switch (key) {
    case "screen_id":
      return (
        <>
          <button type="button" className="row-open"
                  onClick={event => { event.stopPropagation(); onOpen(screen.screen_id); }}>
            <span className="clinical-clamp" title={screen.title ?? undefined}>
              {screen.title ?? screen.screen_id}
            </span>
          </button>
          <div className="clinical-id mono">{screen.screen_id}</div>
        </>
      );
    case "depositor":
      return <span className="clinical-clamp">{screen.depositor ?? "—"}</span>;
    case "source":
      return screen.source;
    case "year":
      return screen.year ?? "—";
    case "n_tested":
      return count(screen.n_tested);
    // The depositor's own figure for the library, which is a different number from
    // what was deposited and is never substituted for it.
    case "library_size_stated":
      return count(screen.library_size_stated);
    case "n_active":
      return actives(screen);
    case "n_inactive":
      return screen.outcome_stated ? count(screen.n_inactive) : "no call stated";
    case "n_stages":
      return screen.n_stages;
    case "modalities":
      return screen.modalities.length
        ? screen.modalities.map(m => MODALITY_LABEL[m] ?? m).join(", ")
        : "—";
    case "genes":
      if (screen.genes.length) {
        return (
          <span className="chips">
            {screen.genes.map(g => (
              <span className={`chip ${g.own ? "accent" : "warn"}`} key={g.rv_id}>
                {g.gene_name ?? g.rv_id}
              </span>
            ))}
          </span>
        );
      }
      // An unresolved target is not "no gene": the screen exists and names a protein.
      return screen.unplaced_targets.length
        ? <span className="absent">protein not keyed to a locus</span>
        : <span className="dim">—</span>;
    default:
      return null;
  }
}

function CampaignTable({ page, onOpen, sort, onSort, columns }: {
  page: ScreenPage;
  onOpen: (id: string) => void;
  sort: Sort;
  onSort: (next: Sort) => void;
  columns: Column[];
}) {
  return (
    <div className="scroller clinical-scroller">
      <table className="clinical-table" aria-label="Screening campaigns">
        <thead>
          <tr>
            {columns.map(([key, label, numeric]) =>
              SORTABLE_SCREENS.has(key)
                ? <SortHeader key={key} sort={sort} onSort={onSort} column={key} label={label} numeric={numeric} />
                : <th key={key} scope="col" className={numeric ? "n" : undefined}>{label}</th>,
            )}
          </tr>
        </thead>
        <tbody>
          {page.items.map(screen => (
            <tr key={screen.screen_id} onClick={() => onOpen(screen.screen_id)}>
              {columns.map(([key, , numeric]) => (
                <td key={key} data-column={key}
                    className={numeric ? "n" : key === "n_active" && !screen.outcome_stated ? "dim" : undefined}>
                  {campaignCell(screen, key, onOpen)}
                </td>
              ))}
            </tr>
          ))}
          {!page.items.length && (
            <tr><td className="clinical-empty" colSpan={columns.length}>No campaign matches.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function Screens({ onSelectGene, focus, onFocus }: {
  onSelectGene?: (rvId: string) => void;
  /** A campaign opened from elsewhere -- a gene page, or the search box. */
  focus?: string | null;
  onFocus?: (id: string | null) => void;
}) {
  const [page, setPage] = useState<ScreenPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [own, setOwn] = useState<string | null>(null);
  const open = focus !== undefined ? focus : own;
  const setOpen = onFocus ?? setOwn;
  const [ownOnly, setOwnOnly] = useState(false);
  // Size first: the public TB screening record is a handful of very large deposits
  // and a long tail, and that shape is the first thing to see.
  const [sort, setSort] = useState<Sort>({ key: "n_tested", order: "desc" });
  const [offset, setOffset] = useState(0);
  const settings = useTablePreferences(SCREEN_COLUMNS, "atlas.screen-table.v1", "screen_id");

  useEffect(() => {
    api
      .screens({
        sort: sort.key,
        order: sort.order,
        limit: PAGE,
        offset,
        // Filtering on the server, like the sort: a filter applied to the loaded
        // page would narrow the page rather than the population.
        has_own_gene: ownOnly ? true : undefined,
      })
      .then(setPage, e => setError(String(e)));
  }, [sort, offset, ownOnly]);

  // A new sort or filter means a different first page, not the same offset into
  // a different list.
  useEffect(() => setOffset(0), [sort, ownOnly]);

  if (error) return <div className="errbox">{error}</div>;
  if (!page) return <div className="body"><p className="note">Loading campaigns…</p></div>;

  const shown = page;
  const columns = SCREEN_COLUMNS.filter(
    ([key]) => !settings.preferences.visible || settings.preferences.visible.includes(key),
  );
  const labels = page.stage_labels;
  const primaryShare = Math.round((labels.n_primary / labels.n_stages) * 100);
  return (
    <div className="body clinical">
      <FilterRail label="Screening filters">
        <div className="rail-heading"><InterfaceIcon name="clinical" /><h2>Screens</h2></div>
        <p className="clinical-count" aria-live="polite">
          <strong>{page.total.toLocaleString()}</strong> campaign{page.total === 1 ? "" : "s"}
          {ownOnly && " on a gene's own protein"}
        </p>
        <div className="group">
          <p className="lab">Reach</p>
          <div className="seg">
            <button type="button" aria-pressed={ownOnly} onClick={() => setOwnOnly(v => !v)}>
              <span className="name">On a gene's own protein</span>
            </button>
          </div>
        </div>
        <p className="caveat"><strong>71 of 4,031 genes</strong> have a campaign on their own protein.</p>
        <details className="group filtergroup">
          <summary>Stage labels</summary>
          <p className="note">{primaryShare}% are the default <span className="mono">primary</span>, read from prose: "nothing said otherwise", not a funnel position.</p>
        </details>
        <details className="group filtergroup">
          <summary>Coverage <span className="filtercount">{page.n_unplaced} unplaced</span></summary>
          <p className="note">Ingested campaigns only: PubChem deposits of 10,000+ substances, and ChEMBL papers reachable from its activities.</p>
          <p className="note">Not in this layer at all: {page.not_ingested.join("; ")}.</p>
          <p className="note">{page.n_unplaced} name a protein not keyed to a locus, so no gene carries them.</p>
        </details>
      </FilterRail>
      {open
        ? <CampaignPage id={open} onBack={() => setOpen(null)} onSelectGene={onSelectGene} />
        : <main className="col canvascol">
            <div className="clinical-toolbar">
              <Pager total={page.total} offset={offset} onOffset={setOffset} label="campaigns" />
              <TableControls
                columns={SCREEN_COLUMNS}
                groups={SCREEN_GROUPS}
                visible={columns}
                preferences={settings.preferences}
                saved={settings.saved}
                onChange={settings.change}
                identity="screen_id"
                recordLabel="campaigns"
                defaultNote=""
              />
            </div>
            <CampaignTable page={shown} onOpen={setOpen} sort={sort} onSort={setSort} columns={columns} />
          </main>}
    </div>
  );
}

// --- hit profiling -----------------------------------------------------------

const HIT_COLUMNS: Column[] = [
  ["structure", "Structure", false],
  ["molecule_chembl_id", "Compound", false],
  ["n_papers", "Papers", true],
  ["first_year", "First seen", true],
  ["latest_year", "Last seen", true],
  ["n_mtb_whole_cell", "Whole cell", true],
  ["n_mtb_protein", "Mtb protein", true],
  ["n_cytotox", "Cytotox", true],
  ["n_adme", "ADME", true],
  ["n_in_vivo", "Animal", true],
  ["n_other_pathogen", "Other pathogen", true],
  ["n_other", "Unclassified", true],
  ["selectivity_median", "Selectivity", true],
  ["n_active_campaigns", "Called active", true],
];
const HIT_GROUPS = [
  { label: "", keys: ["structure", "molecule_chembl_id"] },
  { label: "Literature", keys: ["n_papers", "first_year", "latest_year"] },
  { label: "Potency", keys: ["n_mtb_whole_cell", "n_mtb_protein"] },
  { label: "Beyond potency", keys: ["n_cytotox", "n_adme", "n_in_vivo"] },
  { label: "Elsewhere", keys: ["n_other_pathogen", "n_other"] },
  { label: "Reported", keys: ["selectivity_median", "n_active_campaigns"] },
];
/** Everything but the depiction, which is drawn from a SMILES and has no order. */
const SORTABLE_HITS = new Set(HIT_COLUMNS.map(([key]) => key).filter(key => key !== "structure"));

/** The median of what the papers reported, with the spread behind it on hover.
 *
 * Isoniazid's twelve ratios span 8 to 60,000, so the maximum is one paper's best
 * day. A bound ("> 100-fold") is counted and never shown as the number.
 */
function selectivity(hit: HitProfile): { text: string; title?: string } {
  if (hit.n_selectivity === null) {
    return hit.n_selectivity_censored
      ? { text: `bound only (${hit.n_selectivity_censored})`, title: "every reported ratio was a bound" }
      : { text: "—" };
  }
  const round = (v: number | null) => (v === null ? "?" : v >= 100 ? v.toFixed(0) : v.toFixed(1));
  const spread = `${hit.n_selectivity} reported, ${round(hit.selectivity_min)}–${round(hit.selectivity_max)}`;
  return {
    text: hit.n_selectivity > 1 ? `${round(hit.selectivity_median)} (${hit.n_selectivity})` : round(hit.selectivity_median),
    title: hit.n_selectivity_censored ? `${spread}; ${hit.n_selectivity_censored} further bounds` : spread,
  };
}

function hitCell(hit: HitProfile, key: string) {
  switch (key) {
    case "structure":
      return <Structure smiles={hit.smiles} width={112} height={60} title={hit.pref_name ?? hit.molecule_chembl_id} />;
    case "molecule_chembl_id":
      return (
        <>
          {hit.pref_name ?? hit.molecule_chembl_id}
          <div className="clinical-id"><ChemblLink kind="compound" id={hit.molecule_chembl_id} /></div>
        </>
      );
    case "n_papers":
      return hit.n_papers;
    case "first_year":
      return hit.first_year ?? "—";
    case "latest_year":
      return hit.latest_year ?? "—";
    case "selectivity_median":
      return selectivity(hit).text;
    // Never a bare numerator: 974 of 999 campaigns state no call, so an actives
    // count without its denominator would read as "never a hit".
    case "n_active_campaigns":
      return hit.n_call_campaigns === null ? "—" : `${hit.n_active_campaigns} / ${hit.n_call_campaigns}`;
    default:
      return count(hit[key as keyof HitProfile] as number | null);
  }
}

export function HitProfiling() {
  const [page, setPage] = useState<HitPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [beyond, setBeyond] = useState(false);
  // Most-profiled first. Paper count ranks the famous drugs, which is a literature
  // fact rather than a triage one; cytotoxicity coverage ranks what has been looked
  // at hardest, which is the question this view is for.
  const [sort, setSort] = useState<Sort>({ key: "n_cytotox", order: "desc" });
  const [offset, setOffset] = useState(0);
  const settings = useTablePreferences(HIT_COLUMNS, "atlas.hit-table.v1", "molecule_chembl_id");

  useEffect(() => {
    api
      .hits({
        sort: sort.key,
        order: sort.order,
        limit: PAGE,
        offset,
        beyond_potency: beyond ? true : undefined,
      })
      .then(setPage, e => setError(String(e)));
  }, [sort, offset, beyond]);
  useEffect(() => setOffset(0), [sort, beyond]);

  if (error) return <div className="errbox">{error}</div>;
  if (!page) return <div className="body"><p className="note">Loading compound profiles…</p></div>;

  const shown = page;
  const columns = HIT_COLUMNS.filter(
    ([key]) => !settings.preferences.visible || settings.preferences.visible.includes(key),
  );
  const groups = page.population;
  return (
    <div className="body clinical">
      <FilterRail label="Profiling filters">
        <div className="rail-heading"><InterfaceIcon name="clinical" /><h2>Hit profiling</h2></div>
        <p className="clinical-count" aria-live="polite">
          <strong>{shown.items.length.toLocaleString()}</strong> shown of {groups.compounds.toLocaleString()} compounds
        </p>
        <div className="group">
          <p className="lab">Coverage</p>
          <div className="seg">
            <button type="button" aria-pressed={beyond} onClick={() => setBeyond(v => !v)}>
              <span className="name">Beyond potency</span>
              <span className="c">{groups.beyond_potency}</span>
            </button>
            <button type="button" disabled><span className="name">Potency only</span><span className="c">{groups.potency_only}</span></button>
            <button type="button" disabled><span className="name">Only elsewhere</span><span className="c">{groups.elsewhere_only}</span></button>
          </div>
        </div>
        <p className="caveat">A dash is unmeasured, not a zero. Nothing here is ranked or combined.</p>
        <p className="caveat">
          {groups.with_structure.toLocaleString()} of {groups.compounds.toLocaleString()} can be
          drawn: the atlas holds a structure for the ChEMBL potency set, not for everything screened.
        </p>
        <details className="group filtergroup">
          <summary>Reading the columns</summary>
          <p className="note">{groups.whole_cell_and_nothing_else.toLocaleString()} compounds have a whole-cell MIC and nothing else.</p>
          <p className="note">ADME counts assays; the store does not record which of microsomes, solubility, permeability or PK was run.</p>
          <p className="note">Selectivity is the authors' own ratio. Bounds are counted apart.</p>
        </details>
      </FilterRail>
      <main className="col canvascol">
        <div className="clinical-toolbar">
          <Pager total={page.total} offset={offset} onOffset={setOffset} label="compounds" />
          <TableControls
            columns={HIT_COLUMNS}
            groups={HIT_GROUPS}
            visible={columns}
            preferences={settings.preferences}
            saved={settings.saved}
            onChange={settings.change}
            identity="molecule_chembl_id"
            recordLabel="compounds"
            defaultNote=""
          />
        </div>
        <div className="scroller clinical-scroller">
          <table className="clinical-table" aria-label="Compound profiling">
            <thead>
              <tr>
                {columns.map(([key, label, numeric]) =>
                  SORTABLE_HITS.has(key)
                    ? <SortHeader key={key} sort={sort} onSort={setSort} column={key} label={label} numeric={numeric} />
                    : <th key={key} scope="col" className={numeric ? "n" : undefined}>{label}</th>,
                )}
              </tr>
            </thead>
            <tbody>
              {shown.items.map(hit => (
                <tr key={hit.molecule_chembl_id}>
                  {columns.map(([key, , numeric]) => (
                    <td key={key} data-column={key} className={numeric ? "n" : undefined}
                        title={key === "selectivity_median" ? selectivity(hit).title : undefined}>
                      {hitCell(hit, key)}
                    </td>
                  ))}
                </tr>
              ))}
              {!shown.items.length && (
                <tr><td className="clinical-empty" colSpan={columns.length}>No compound matches.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}
