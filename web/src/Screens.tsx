/**
 * The screening end of the atlas: the campaigns that were run, and what was
 * measured on the compounds that came out of them.
 *
 * A BARE MOCK, to settle the arrangement before the real build. It reuses the
 * clinical view's classes rather than adding styling of its own.
 *
 * Two rules this view exists to keep visible:
 *
 * - An actives count is never divided by a screen count. They share no
 *   denominator: the actives sum only the campaigns that stated calls, and 974
 *   of 999 campaigns state none. "no call stated" is printed as itself.
 * - 71 genes of 4,031 have a screen on their own protein. The scarcity is the
 *   finding, so it is the first thing the rail says.
 */

import { useEffect, useMemo, useState } from "react";
import { FilterRail } from "./FilterRail";
import { InterfaceIcon } from "./InterfaceIcon";
import { ChemblLink } from "./Structure";
import {
  api,
  type HitPage,
  type HitProfile,
  type ScreenDetail,
  type ScreenPage,
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

function stageLabel(stage: ScreenStage): string {
  if (stage.derived) return "derived";
  return stage.stage ?? "—";
}

function CampaignDetail({ id }: { id: string }) {
  const [detail, setDetail] = useState<ScreenDetail | null>(null);
  useEffect(() => {
    setDetail(null);
    api.screen(id).then(setDetail, () => setDetail(null));
  }, [id]);
  if (!detail) return <aside className="col detailcol"><p className="note">Loading campaign…</p></aside>;

  const ladder = [...detail.stages].sort(
    (a, b) => STAGE_ORDER.indexOf(a.stage ?? "zz") - STAGE_ORDER.indexOf(b.stage ?? "zz"),
  );
  const own = detail.genes.filter(g => g.own);
  const complex = detail.genes.filter(g => !g.own);
  return (
    <aside className="col detailcol">
      <h2>{detail.title ?? detail.screen_id}</h2>
      <p className="note">
        {detail.depositor ?? "unknown depositor"} · {detail.source}
        {detail.year ? ` · ${detail.year}` : ""} · <span className="mono">{detail.screen_id}</span>
      </p>

      <div className="ev">
        <span className="k">Deposited</span>
        <span>{count(detail.n_tested)} {detail.source === "pubchem" ? "substances" : "compounds"}</span>
      </div>
      {detail.library_size_stated !== null && (
        <div className="ev">
          <span className="k">The depositor’s prose says</span>
          <span>{count(detail.library_size_stated)} compounds</span>
          <span className="src">a different number from what was deposited; neither is substituted for the other</span>
        </div>
      )}
      <div className="ev">
        <span className="k">Actives</span>
        <span>{actives(detail)}</span>
        {!detail.outcome_stated && <span className="src">this source states no activity call, so there is no hit rate to show</span>}
      </div>

      <h3>Stage ladder</h3>
      <table className="clinical-table">
        <thead>
          <tr><th scope="col">Stage</th><th scope="col">Measured</th><th scope="col" className="n">Rows</th><th scope="col" className="n">Active</th><th scope="col" className="n">Inactive</th><th scope="col" className="n">No call</th></tr>
        </thead>
        <tbody>
          {ladder.map(stage => (
            <tr key={stage.stage_id}>
              <td>{stageLabel(stage)}<div className="clinical-id mono">{stage.stage_id}</div></td>
              <td><span className="clinical-clamp" title={stage.description ?? undefined}>{stage.modality ? MODALITY_LABEL[stage.modality] ?? stage.modality : "unclassified"}</span></td>
              <td className="n">{count(stage.n_rows)}</td>
              <td className="n">{count(stage.n_active_rows)}</td>
              <td className="n">{count(stage.n_inactive_rows)}</td>
              <td className="n">{count(stage.n_no_call_rows)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="caveat">
        Counts are per stage and never summed: a compound active in a primary screen and
        inactive in its confirmation is one compound measured twice, not two compounds.
      </p>

      <h3>Genes reached</h3>
      {own.length ? (
        <div className="chips">{own.map(g => <span className="chip accent" key={g.rv_id}>{g.gene_name ?? g.rv_id}</span>)}</div>
      ) : (
        <p><span className="absent">no gene’s own protein</span></p>
      )}
      {complex.length > 0 && (
        <>
          <div className="chips">{complex.map(g => <span className="chip warn" key={g.rv_id}>{g.gene_name ?? g.rv_id}</span>)}</div>
          <p className="caveat">Reached only as part of a complex or a multi-protein deposit. Shown, never counted as the gene’s own screen.</p>
        </>
      )}
      {detail.unplaced_targets.length > 0 && (
        <>
          <h3>Named, but not keyed to a locus</h3>
          {detail.unplaced_targets.map(t => (
            <p className="note" key={t.accession ?? t.name}>
              <span className="mono">{t.accession}</span> {t.name}
              <span className="src">{t.accession_kind ?? "unknown"} — this atlas could not key it to a locus, so no gene carries this screen</span>
            </p>
          ))}
        </>
      )}
    </aside>
  );
}

function Campaigns({ page, selected, onSelect }: {
  page: ScreenPage;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
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
            <tr key={screen.screen_id} aria-selected={selected === screen.screen_id}
                onClick={() => onSelect(screen.screen_id === selected ? null : screen.screen_id)}>
              <td>
                <span className="clinical-clamp" title={screen.title ?? undefined}>{screen.title ?? screen.screen_id}</span>
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
                  <span className="absent">names a protein not keyed to a locus</span>
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

function HitProfiling({ page }: { page: HitPage }) {
  return (
    <div className="scroller clinical-scroller">
      <table className="clinical-table" aria-label="Compound profiling">
        <thead>
          <tr className="column-groups">
            <th scope="colgroup" colSpan={2} />
            <th scope="colgroup" colSpan={2}>Potency</th>
            <th scope="colgroup" colSpan={3}>Beyond potency</th>
            <th scope="colgroup" colSpan={2}>Elsewhere</th>
            <th scope="colgroup" colSpan={2}>Reported</th>
          </tr>
          <tr>
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
          {page.items.map(hit => (
            <tr key={hit.molecule_chembl_id}>
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
              {/* Never a bare numerator: 974 of 999 campaigns state no call. */}
              <td className="n">{hit.n_call_campaigns === null ? "—" : `${hit.n_active_campaigns} / ${hit.n_call_campaigns}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Screens({ onSelectGene }: { onSelectGene?: (rvId: string) => void }) {
  const [tab, setTab] = useState<"campaigns" | "hits">("campaigns");
  const [screens, setScreens] = useState<ScreenPage | null>(null);
  const [hits, setHits] = useState<HitPage | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ownOnly, setOwnOnly] = useState(false);
  const [beyond, setBeyond] = useState(false);

  useEffect(() => { void onSelectGene; }, [onSelectGene]);
  useEffect(() => {
    api.screens().then(setScreens, e => setError(String(e)));
  }, []);
  useEffect(() => {
    if (tab === "hits" && !hits) api.hits().then(setHits, e => setError(String(e)));
  }, [tab, hits]);

  const shown = useMemo(() => {
    if (!screens) return null;
    const items = ownOnly ? screens.items.filter(s => s.genes.some(g => g.own)) : screens.items;
    return { ...screens, items };
  }, [screens, ownOnly]);
  const shownHits = useMemo(() => {
    if (!hits) return null;
    const items = beyond
      ? hits.items.filter(h => h.n_cytotox !== null || h.n_adme !== null || h.n_in_vivo !== null)
      : hits.items;
    return { ...hits, items };
  }, [hits, beyond]);

  if (error) return <div className="errbox">{error}</div>;
  if (!screens || !shown) return <div className="body"><p className="note">Loading screening campaigns…</p></div>;

  const labels = shown.stage_labels;
  const primaryShare = Math.round((labels.n_primary / labels.n_stages) * 100);
  const isCampaigns = tab === "campaigns";

  return (
    <div className={`body clinical${selected && isCampaigns ? " detail-open" : ""}`}>
      <FilterRail label="Screening filters">
        <div className="rail-heading"><InterfaceIcon name="clinical" /><h2>Screening explorer</h2></div>

        {isCampaigns ? (
          <>
            <p className="clinical-count" aria-live="polite">
              <strong>{shown.items.length.toLocaleString()}</strong> / {screens.total.toLocaleString()} campaigns
            </p>
            <div className="group">
              <p className="lab">Reach</p>
              <div className="seg">
                <button type="button" aria-pressed={ownOnly} onClick={() => setOwnOnly(v => !v)}>
                  <span className="name">On a gene’s own protein</span>
                  <span className="c">{screens.items.filter(s => s.genes.some(g => g.own)).length}</span>
                </button>
              </div>
            </div>
            <p className="caveat">
              <strong>71 of 4,031 genes</strong> have a screening campaign on their own protein. The
              scarcity of public target-based screening in TB is the finding here, not a gap in
              this table.
            </p>
            <details className="group filtergroup" open>
              <summary>What the stage labels mean</summary>
              <p className="note">
                {primaryShare}% of the {labels.n_stages.toLocaleString()} measured stages carry the
                default <span className="mono">primary</span> label, because the labels are read
                from the depositor’s prose. Read <span className="mono">primary</span> as “nothing
                said otherwise”, not as a claim about funnel position.
              </p>
              <p className="note">
                {labels.n_modality_other.toLocaleString()} stages measured something no pattern
                recognised, and {labels.n_modality_unclassified.toLocaleString()} are unclassified
                rather than “other”.
              </p>
            </details>
            <details className="group filtergroup">
              <summary>Coverage <span className="filtercount">{shown.n_unplaced} unplaced</span></summary>
              <p className="note">
                These are the campaigns the atlas <em>ingested</em>: PubChem deposits of 10,000+
                substances and the ChEMBL papers reachable from its activities. A count here is a
                count of ingested campaigns.
              </p>
              <p className="note">Not in this layer at all, so a search for one finds nothing rather than an empty screen:</p>
              <ul className="note">{shown.not_ingested.map(name => <li key={name}>{name}</li>)}</ul>
              <p className="note">
                {shown.n_unplaced} campaigns name a protein this atlas could not key to a locus, so
                no gene carries them — including a 104,781-substance screen.
              </p>
            </details>
          </>
        ) : (
          <>
            <p className="clinical-count" aria-live="polite">
              <strong>{(shownHits?.items.length ?? 0).toLocaleString()}</strong> shown of{" "}
              {(hits?.population.compounds ?? 0).toLocaleString()} compounds
            </p>
            <div className="group">
              <p className="lab">Coverage</p>
              <div className="seg">
                <button type="button" aria-pressed={beyond} onClick={() => setBeyond(v => !v)}>
                  <span className="name">Has data beyond potency</span>
                  <span className="c">{hits?.population.beyond_potency ?? 0}</span>
                </button>
              </div>
            </div>
            {hits && (
              <div className="group">
                <p className="lab">The whole population</p>
                <div className="seg">
                  <button type="button" disabled><span className="name">Beyond potency</span><span className="c">{hits.population.beyond_potency}</span></button>
                  <button type="button" disabled><span className="name">Potency only</span><span className="c">{hits.population.potency_only}</span></button>
                  <button type="button" disabled><span className="name">Measured only elsewhere</span><span className="c">{hits.population.elsewhere_only}</span></button>
                </div>
                <p className="caveat">
                  Three groups, not two: {hits.population.elsewhere_only.toLocaleString()} compounds
                  were measured against another pathogen or an unclassified endpoint and carry no
                  Mtb potency at all. A two-way split would lose them.
                  {" "}{hits.population.whole_cell_and_nothing_else.toLocaleString()} have a
                  whole-cell MIC and nothing else whatsoever, which is an answer rather than a low score.
                </p>
              </div>
            )}
            <p className="caveat">
              Nothing here is ranked, weighted or combined. The columns count assays, so a dash
              means unmeasured — never a measured zero, and never a weak compound.
            </p>
            <p className="caveat">
              The ADME column counts assays, not which of microsomes, solubility, permeability or
              PK was run: the store does not record that split.
            </p>
          </>
        )}
      </FilterRail>

      <main className="col canvascol">
        <div className="clinical-toolbar">
          <div className="tabs" aria-label="Screening datasets">
            <button type="button" aria-pressed={isCampaigns} onClick={() => setTab("campaigns")}>Campaigns</button>
            <button type="button" aria-pressed={!isCampaigns} onClick={() => setTab("hits")}>Hit profiling</button>
          </div>
        </div>
        {isCampaigns
          ? <Campaigns page={shown} selected={selected} onSelect={setSelected} />
          : shownHits
            ? <HitProfiling page={shownHits} />
            : <p className="note">Loading compound profiles…</p>}
      </main>

      {isCampaigns && selected && <CampaignDetail id={selected} />}
    </div>
  );
}
