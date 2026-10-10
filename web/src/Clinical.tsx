/**
 * The clinical end of the atlas: TB drugs and candidates, the trials testing
 * them, and the genes they reach -- every link labelled with how it was made.
 *
 * A drug "acts on" a gene only when ChEMBL's mechanism or Bosch 2021 names that
 * gene's protein. Membership of a target complex and WHO-graded resistance are
 * shown, never promoted: resistance is not engagement (katG activates isoniazid).
 */

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
  return `ClinicalTrials.gov${version ? ` · ${version}` : ""} · the atlas selects fields, numbers the phases and leaves out studies solely of nontuberculous mycobacteria; nothing else is rewritten`;
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
            no drug with a TB indication in ChEMBL acts on this gene, by ChEMBL&rsquo;s mechanism or
            Bosch 2021&rsquo;s annotation
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
            Bosch 2021 annotates this gene with &ldquo;{detail.antibacterial}&rdquo;, which names no
            single molecule in ChEMBL&rsquo;s TB indications, so it is not counted here.
          </p>
        )}
        <div className="note">
          Phase is the highest ChEMBL records for a tuberculosis indication. Bosch 2021&rsquo;s
          column names the drug associated with a gene, which is usually its target but can be
          the enzyme that activates it &mdash; as folC is for PAS.
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
            ChEMBL files these against the whole assembly. That this protein is one of its components
            is not evidence the drug binds it.
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
            Modelled on this protein&rsquo;s own chain, which is physical evidence that the two
            meet. It is not a claim about the mechanism: a repressor like EthR binds many
            ligands in soaking studies.
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
            Variants here are graded as associated with resistance to these drugs. Resistance is not
            engagement: a resistance gene can activate the drug, pump it out or regulate the target.
          </p>
        </Section>
      )}

      <Section label={`Trials (${detail.trials.length})`} source={trialSource(meta)}>
        {detail.trials.length === 0 ? (
          <span className="absent">no trial is linked to a drug acting on this gene</span>
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

export function DrugsAndTrials({
  meta,
  focus,
  onFocus,
  onSelectGene,
}: {
  meta: Meta | null;
  focus: Focus;
  onFocus: (focus: Focus) => void;
  onSelectGene: (rv: string) => void;
}) {
  const [tab, setTab] = useState<"drugs" | "trials">(focus?.kind === "trial" ? "trials" : "drugs");
  const [drugs, setDrugs] = useState<DrugSummary[]>([]);
  const [trials, setTrials] = useState<Trial[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [phases, setPhases] = useState<Set<number>>(new Set());
  const [flags, setFlags] = useState<Set<DrugFlag>>(new Set(["on_gene"]));
  const [statuses, setStatuses] = useState<Set<string>>(new Set());
  const [linkedOnly, setLinkedOnly] = useState(true);

  useEffect(() => {
    Promise.all([api.drugs(), api.trials()])
      .then(([d, t]) => {
        setDrugs(d.items);
        setTrials(t.items);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (focus) setTab(focus.kind === "trial" ? "trials" : "drugs");
  }, [focus]);

  const text = query.trim().toLowerCase();
  const shownDrugs = useMemo(
    () =>
      drugs.filter((d) => {
        if (phases.size && !phases.has(Math.floor(d.max_phase_tb ?? -1))) return false;
        for (const [key, , test] of DRUG_FLAGS) if (flags.has(key) && !test(d)) return false;
        if (!text) return true;
        return [d.pref_name, d.molecule_chembl_id, ...d.synonyms, ...d.mechanisms_of_action, ...d.genes.map((g) => g.gene_name ?? g.rv_id)]
          .some((v) => (v ?? "").toLowerCase().includes(text));
      }),
    [drugs, phases, flags, text],
  );

  const trialStatuses = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of trials) counts.set(t.status ?? "UNKNOWN", (counts.get(t.status ?? "UNKNOWN") ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [trials]);

  const shownTrials = useMemo(
    () =>
      trials.filter((t) => {
        if (linkedOnly && !t.drugs.length) return false;
        if (statuses.size && !statuses.has(t.status ?? "UNKNOWN")) return false;
        if (phases.size && !phases.has(Math.floor(t.phase_max ?? -1))) return false;
        if (!text) return true;
        return [t.nct_id, t.brief_title, t.acronym, t.lead_sponsor, ...t.interventions.map((i) => i.name), ...t.drugs.map((d) => d.pref_name)]
          .some((v) => (v ?? "").toLowerCase().includes(text));
      }),
    [trials, linkedOnly, statuses, phases, text],
  );

  const toggle = <T,>(set: Set<T>, value: T, apply: (next: Set<T>) => void) => {
    const next = new Set(set);
    next.has(value) ? next.delete(value) : next.add(value);
    apply(next);
  };

  if (error) return <div className="errbox">{error}</div>;

  return (
    <div className={`body clinical${focus ? " detail-open" : ""}`}>
      <aside className="col col-pad">
        <div className="group">
          <p className="lab">Search</p>
          <input
            className="search"
            type="search"
            value={query}
            placeholder={tab === "drugs" ? "bedaquiline, TMC207, dprE1" : "NCT02333799, Nix-TB, sponsor"}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <div className="group">
          <p className="lab">{tab === "drugs" ? "Highest phase for TB" : "Phase"}</p>
          <div className="seg">
            {PHASES.map(([phase, label]) => (
              <button key={phase} type="button" aria-pressed={phases.has(phase)} onClick={() => toggle(phases, phase, setPhases)}>
                <span className="name">{tab === "drugs" ? label : label.replace("Approved for TB", "Phase 4")}</span>
                <span className="c">
                  {tab === "drugs"
                    ? drugs.filter((d) => Math.floor(d.max_phase_tb ?? -1) === phase).length
                    : trials.filter((t) => Math.floor(t.phase_max ?? -1) === phase).length}
                </span>
              </button>
            ))}
          </div>
        </div>

        {tab === "drugs" ? (
          <div className="group">
            <p className="lab">Restrict to</p>
            <div className="seg">
              {DRUG_FLAGS.map(([key, label, test]) => (
                <button key={key} type="button" aria-pressed={flags.has(key)} onClick={() => toggle(flags, key, setFlags)}>
                  <span className="name">{label}</span>
                  <span className="c">{drugs.filter(test).length}</span>
                </button>
              ))}
            </div>
            <p className="note">
              ChEMBL&rsquo;s TB indications, unedited: they include host-directed adjuncts, HIV
              co-medications and placebo excipients, because ChEMBL reads indications off trial
              records. &ldquo;Placed on an Mtb gene&rdquo; is on by default.
            </p>
          </div>
        ) : (
          <>
            <div className="group">
              <p className="lab">Restrict to</p>
              <div className="seg">
                <button type="button" aria-pressed={linkedOnly} onClick={() => setLinkedOnly((v) => !v)}>
                  <span className="name">Linked to a TB drug</span>
                  <span className="c">{trials.filter((t) => t.drugs.length).length}</span>
                </button>
              </div>
            </div>
            <div className="group">
              <p className="lab">Status</p>
              <div className="seg">
                {trialStatuses.map(([value, count]) => (
                  <button key={value} type="button" aria-pressed={statuses.has(value)} onClick={() => toggle(statuses, value, setStatuses)}>
                    <span className="name">{status(value)}</span>
                    <span className="c">{count}</span>
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
      </aside>

      <main className="col canvascol">
        <div className="tabs">
          <button type="button" aria-pressed={tab === "drugs"} onClick={() => setTab("drugs")}>
            Drugs and candidates<span className="badge">{drugs.length}</span>
          </button>
          <button type="button" aria-pressed={tab === "trials"} onClick={() => setTab("trials")}>
            Trials<span className="badge">{trials.length}</span>
          </button>
        </div>
        <div className="listhead">
          <h2>{tab === "drugs" ? "TB drugs and candidates (ChEMBL)" : "Interventional TB trials (ClinicalTrials.gov)"}</h2>
          <span className="count">
            {(tab === "drugs" ? shownDrugs : shownTrials).length.toLocaleString()} of{" "}
            {(tab === "drugs" ? drugs : trials).length.toLocaleString()}
            {tab === "trials" && shownTrials.length > TRIAL_ROWS ? ` · showing first ${TRIAL_ROWS}` : ""}
          </span>
        </div>
        <div className="scroller" style={{ flex: 1 }}>
          {tab === "drugs" ? (
            <table>
              <thead>
                <tr>
                  <th>Structure</th>
                  <th>Drug</th>
                  <th>TB phase</th>
                  <th className="n">Approved</th>
                  <th>Mtb genes</th>
                  <th className="n">Trials</th>
                  <th>Mechanism (ChEMBL)</th>
                </tr>
              </thead>
              <tbody>
                {shownDrugs.map((d) => (
                  <tr
                    key={d.molecule_chembl_id}
                    aria-selected={focus?.kind === "drug" && focus.id === d.molecule_chembl_id}
                    onClick={() => onFocus({ kind: "drug", id: d.molecule_chembl_id })}
                  >
                    <td>
                      <Structure
                        smiles={d.smiles}
                        title={d.pref_name ?? d.molecule_chembl_id}
                      />
                    </td>
                    <td className="id">
                      {d.pref_name && <div>{d.pref_name}</div>}
                      <ChemblLink kind="compound" id={d.molecule_chembl_id} />
                    </td>
                    <td className="dim">{phaseLabel(d.max_phase_tb)}</td>
                    <td className="n">{d.first_approval ?? "—"}</td>
                    <td>
                      <span className="chips">
                        {d.genes.length
                          ? d.genes.map((g) => <GeneChip key={g.rv_id} rv={g.rv_id} name={g.gene_name} onSelect={onSelectGene} />)
                          : <span className="absent">—</span>}
                      </span>
                    </td>
                    <td className="n">{d.n_trials || "—"}</td>
                    <td className="prodcell">
                      {d.mechanisms_of_action.join("; ") || <span className="absent">none recorded</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>NCT</th>
                  <th>Phase</th>
                  <th>Status</th>
                  <th>Start</th>
                  <th>Drugs</th>
                  <th>Title</th>
                </tr>
              </thead>
              <tbody>
                {shownTrials.slice(0, TRIAL_ROWS).map((t) => (
                  <tr
                    key={t.nct_id}
                    aria-selected={focus?.kind === "trial" && focus.id === t.nct_id}
                    onClick={() => onFocus({ kind: "trial", id: t.nct_id })}
                  >
                    <td className="id">{t.nct_id}</td>
                    <td className="dim">{trialPhase(t.phases)}</td>
                    <td className="dim">{status(t.status)}</td>
                    <td className="mono dim">{t.start_date ?? "—"}</td>
                    <td className="mono">{t.drugs.map((d) => d.pref_name).join(", ") || <span className="absent">—</span>}</td>
                    <td className="prodcell">{t.acronym ? `${t.acronym} · ` : ""}{t.brief_title}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
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
            <span className="absent">no Mtb protein in the atlas has measured activity for it</span>
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
            Best pChEMBL per gene. An orthologue link is a family-level reach through another
            mycobacterium, not evidence of a shared binding site.
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
            Against the whole organism. It says nothing on its own about which protein is engaged.
          </div>
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
                    <span className="chip warn">{m.target_type.toLowerCase()}</span>
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
              None of these targets is an <i>M. tuberculosis</i> protein in the reference proteome, so
              ChEMBL&rsquo;s mechanism places this drug on no Mtb gene.
            </p>
          )}
        </Section>

        <Section label="Genes" source={`${chemblSource(meta)} · ${SOURCE.bosch} · ${SOURCE.who}`}>
          {drug.genes.length === 0 && <span className="absent">reaches no Mtb gene in any source the atlas holds</span>}
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
                Members of the target complex ({complex.length}) &mdash; one subunit of what the drug acts
                on, not evidence it binds that subunit
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
              <div className="note">WHO-graded resistance &mdash; not a target claim</div>
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
            <span className="absent">no interventional TB trial in the store links to this drug</span>
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
              no intervention matches a ChEMBL TB drug, and ChEMBL cites none for this trial
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
