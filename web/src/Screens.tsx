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

import { useEffect, useMemo, useState } from "react";
import { FilterRail } from "./FilterRail";
import { InterfaceIcon } from "./InterfaceIcon";
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

function CampaignTable({ page, onOpen }: { page: ScreenPage; onOpen: (id: string) => void }) {
  return (
    <div className="scroller clinical-scroller">
      <table className="clinical-table" aria-label="Screening campaigns">
        <thead>
          <tr>
            <th scope="col">Campaign</th>
            <th scope="col">Depositor</th>
            <th scope="col" className="n">Year</th>
            <th scope="col" className="n">Tested</th>
            <th scope="col" className="n">Actives</th>
            <th scope="col" className="n">Stages</th>
            <th scope="col">Genes reached</th>
          </tr>
        </thead>
        <tbody>
          {page.items.map(screen => (
            <tr key={screen.screen_id} onClick={() => onOpen(screen.screen_id)}>
              <td>
                <button type="button" className="row-open" onClick={event => { event.stopPropagation(); onOpen(screen.screen_id); }}>
                  <span className="clinical-clamp" title={screen.title ?? undefined}>{screen.title ?? screen.screen_id}</span>
                </button>
                <div className="clinical-id mono">{screen.screen_id}</div>
              </td>
              <td className="dim"><span className="clinical-clamp">{screen.depositor ?? "—"}</span></td>
              <td className="n dim">{screen.year ?? "—"}</td>
              <td className="n">{count(screen.n_tested)}</td>
              <td className={screen.outcome_stated ? "n" : "n dim"}>{actives(screen)}</td>
              <td className="n dim">{screen.n_stages}</td>
              <td>
                {screen.genes.length ? (
                  <span className="chips">
                    {screen.genes.map(g => (
                      <span className={`chip ${g.own ? "accent" : "warn"}`} key={g.rv_id}>{g.gene_name ?? g.rv_id}</span>
                    ))}
                  </span>
                ) : screen.unplaced_targets.length ? (
                  <span className="absent">protein not keyed to a locus</span>
                ) : (
                  <span className="dim">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Screens({ onSelectGene }: { onSelectGene?: (rvId: string) => void }) {
  const [page, setPage] = useState<ScreenPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [ownOnly, setOwnOnly] = useState(false);

  useEffect(() => { api.screens().then(setPage, e => setError(String(e))); }, []);

  const shown = useMemo(() => {
    if (!page) return null;
    return ownOnly ? { ...page, items: page.items.filter(s => s.genes.some(g => g.own)) } : page;
  }, [page, ownOnly]);

  if (error) return <div className="errbox">{error}</div>;
  if (!page || !shown) return <div className="body"><p className="note">Loading campaigns…</p></div>;

  const labels = page.stage_labels;
  const primaryShare = Math.round((labels.n_primary / labels.n_stages) * 100);
  return (
    <div className="body clinical">
      <FilterRail label="Screening filters">
        <div className="rail-heading"><InterfaceIcon name="clinical" /><h2>Screens</h2></div>
        <p className="clinical-count" aria-live="polite">
          <strong>{shown.items.length.toLocaleString()}</strong> / {page.total.toLocaleString()} campaigns
        </p>
        <div className="group">
          <p className="lab">Reach</p>
          <div className="seg">
            <button type="button" aria-pressed={ownOnly} onClick={() => setOwnOnly(v => !v)}>
              <span className="name">On a gene's own protein</span>
              <span className="c">{page.items.filter(s => s.genes.some(g => g.own)).length}</span>
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
        : <main className="col canvascol"><CampaignTable page={shown} onOpen={setOpen} /></main>}
    </div>
  );
}

// --- hit profiling -----------------------------------------------------------

/** A measured range, with bounds reported as bounds. */
function selectivity(hit: HitProfile): string {
  if (hit.n_selectivity === null) {
    return hit.n_selectivity_censored ? `bound only (${hit.n_selectivity_censored})` : "—";
  }
  const range = hit.selectivity_min === hit.selectivity_max
    ? `${hit.selectivity_min}`
    : `${hit.selectivity_min}–${hit.selectivity_max}`;
  return hit.n_selectivity > 1 ? `${range} (${hit.n_selectivity})` : range;
}

export function HitProfiling() {
  const [page, setPage] = useState<HitPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [beyond, setBeyond] = useState(false);

  useEffect(() => { api.hits().then(setPage, e => setError(String(e))); }, []);

  const shown = useMemo(() => {
    if (!page) return null;
    const items = beyond
      ? page.items.filter(h => h.n_cytotox !== null || h.n_adme !== null || h.n_in_vivo !== null)
      : page.items;
    return { ...page, items };
  }, [page, beyond]);

  if (error) return <div className="errbox">{error}</div>;
  if (!page || !shown) return <div className="body"><p className="note">Loading compound profiles…</p></div>;

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
        <div className="scroller clinical-scroller">
          <table className="clinical-table" aria-label="Compound profiling">
            <thead>
              <tr className="column-groups">
                <th scope="colgroup" colSpan={3} />
                <th scope="colgroup" colSpan={2}>Potency</th>
                <th scope="colgroup" colSpan={3}>Beyond potency</th>
                <th scope="colgroup" colSpan={2}>Elsewhere</th>
                <th scope="colgroup" colSpan={2}>Reported</th>
              </tr>
              <tr>
                <th scope="col">Structure</th>
                <th scope="col">Compound</th>
                <th scope="col" className="n">Papers</th>
                <th scope="col" className="n">Whole cell</th>
                <th scope="col" className="n">Mtb protein</th>
                <th scope="col" className="n">Cytotox</th>
                <th scope="col" className="n">ADME</th>
                <th scope="col" className="n">Animal</th>
                <th scope="col" className="n">Other pathogen</th>
                <th scope="col" className="n">Unclassified</th>
                <th scope="col" className="n">Selectivity</th>
                <th scope="col" className="n">Called active</th>
              </tr>
            </thead>
            <tbody>
              {shown.items.map(hit => (
                <tr key={hit.molecule_chembl_id}>
                  <td><Structure smiles={hit.smiles} width={112} height={60} title={hit.pref_name ?? hit.molecule_chembl_id} /></td>
                  <td>
                    {hit.pref_name ?? hit.molecule_chembl_id}
                    <div className="clinical-id"><ChemblLink kind="compound" id={hit.molecule_chembl_id} /></div>
                  </td>
                  <td className="n dim">{hit.n_papers}</td>
                  <td className="n">{count(hit.n_mtb_whole_cell)}</td>
                  <td className="n">{count(hit.n_mtb_protein)}</td>
                  <td className="n">{count(hit.n_cytotox)}</td>
                  <td className="n">{count(hit.n_adme)}</td>
                  <td className="n">{count(hit.n_in_vivo)}</td>
                  <td className="n dim">{count(hit.n_other_pathogen)}</td>
                  <td className="n dim">{count(hit.n_other)}</td>
                  <td className="n">{selectivity(hit)}</td>
                  {/* Never a bare numerator: most campaigns state no call. */}
                  <td className="n">{hit.n_call_campaigns === null ? "—" : `${hit.n_active_campaigns} / ${hit.n_call_campaigns}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}
