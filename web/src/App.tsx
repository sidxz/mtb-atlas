/**
 * The one stop. Filters on the left, the whole genome in the middle, the full
 * evidence record for whatever you picked on the right -- and, one switch
 * away, the same layout for TB drugs and the trials testing them.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Meta, type TargetDetail, type TargetSummary } from "./api";
import { CATEGORIES, GenomeCanvas, RINGS, colourOf, type ColourBy } from "./GenomeCanvas";
import { TargetDetailPanel } from "./TargetDetail";
import { Ask } from "./Ask";
import { DrugsAndTrials, phaseLabel, type Focus } from "./Clinical";
import { Search } from "./Search";

const ESSENTIALITY: [string, string][] = [
  ["ES", "Essential"],
  ["ESD", "Essential domain"],
  ["GD", "Growth defect"],
  ["NE", "Non-essential"],
  ["GA", "Growth advantage"],
  ["Uncertain", "Uncertain"],
];

/** The ring order, inner to outer, so the control reads as the legend it is.
 *
 * This is the discovery pipeline: what the gene is, then can the organism
 * lose it, how much, can you see the protein, can you measure it, has anyone
 * hit it, did it reach the clinic, did resistance come back. Keep this in step
 * with `RINGS` in GenomeCanvas — the list is the picture. */
const COLOUR_MODES: [ColourBy, string][] = [
  ["category", "What it is"],
  ["essentiality", "Essential"],
  ["vulnerability", "Vulnerable"],
  ["structure", "Structure"],
  ["assay", "Protein assay"],
  ["chemistry", "Chemical matter"],
  ["clinical", "Clinical stage"],
  ["resistance", "Resistance"],
];

type Flag =
  | "structural_gap"
  | "crispr_essential"
  | "vulnerability_certain"
  | "has_structure"
  | "has_predicted"
  | "has_ligands"
  | "in_who_catalogue"
  | "has_clinical_drug"
  | "cholesterol_required"
  | "required_in_vivo"
  | "n_transmembrane"
  | "conflict";

const FLAGS: [Flag, string][] = [
  ["structural_gap", "Essential · structure · no ligands"],
  ["crispr_essential", "Essential by CRISPRi"],
  ["vulnerability_certain", "Vulnerability measured confidently"],
  ["has_structure", "Has an experimental structure"],
  ["has_predicted", "Has a predicted structure"],
  ["has_ligands", "Has chemical matter"],
  ["in_who_catalogue", "In the WHO catalogue"],
  ["has_clinical_drug", "A TB drug or candidate acts on it"],
  ["cholesterol_required", "Required on cholesterol"],
  ["required_in_vivo", "Required in mouse infection"],
  ["n_transmembrane", "Transmembrane segments annotated"],
  ["conflict", "ID conflict between sources"],
];

// Columns where a *lower* number is the better answer, so the first click
// should sort ascending: vulnerability runs negative, and so does an E-value.
const LOWER_IS_BETTER = new Set(["vulnerability_index", "best_resolution", "human_homolog_identity"]);

const COLUMNS: [string, string, boolean][] = [
  ["rv_id", "Locus", false],
  ["gene_name", "Gene", false],
  ["essentiality", "Essentiality", false],
  ["vulnerability_index", "Vuln.", true],
  ["n_pdb", "PDB", true],
  ["plddt_mean", "pLDDT", true],
  ["n_compounds", "Cpds", true],
  ["n_protein_assays", "Assays", true],
  ["best_pchembl", "Best pChEMBL", true],
  ["best_whole_cell_pchembl", "Cell", true],
  ["n_variants_associated", "WHO", true],
  ["best_drug_phase", "TB phase", true],
  ["n_partners", "Partners", true],
  ["n_references", "Refs", true],
  ["product", "Product", false],
];

/** What you scan down while reading one gene, as against what you triage on.
 *
 * With a gene open the table gives up most of its width to the detail panel,
 * so it keeps only the columns you move between rows by. The active sort
 * column is always kept too -- sorting by potency and then watching the
 * column vanish is the kind of thing that makes a tool feel hostile.
 */
const SCAN_COLUMNS = new Set([
  "rv_id",
  "gene_name",
  "essentiality",
  "vulnerability_index",
  "n_pdb",
  "n_compounds",
]);

const cellClass = (key: string, numeric: boolean) =>
  key === "rv_id" ? "id" : key === "product" ? "prodcell" : numeric ? "n" : undefined;

/** One row, memoised.
 *
 * The whole genome is in the table, so a sort reorders 4,173 rows over 15
 * columns. Without this React rebuilds all 62,595 cells and a column click
 * costs the best part of a second; memoised, the reorder moves existing DOM
 * nodes and only the row whose selection changed re-renders.
 */
const GeneRow = memo(function GeneRow({
  gene,
  columns,
  selected,
  onSelect,
}: {
  gene: TargetSummary;
  columns: [string, string, boolean][];
  selected: boolean;
  onSelect: (rv: string) => void;
}) {
  return (
    <tr className="generow" aria-selected={selected} onClick={() => onSelect(gene.rv_id)}>
      {columns.map(([key, , numeric]) => (
        <td key={key} className={cellClass(key, numeric)}>
          {cell(gene, key)}
        </td>
      ))}
    </tr>
  );
});

// Rows off screen are not rendered, so a few above and below keep a fast
// scroll from showing blank bands before React catches up.
const OVERSCAN = 15;

/** Height for the rows that are not rendered, so the scrollbar tells the truth.
 *
 * Every row is exactly one line — `white-space: nowrap` on every cell and the
 * product column ellipsised — so one measured height stands for all of them.
 */
function Spacer({ rows, height, columns }: { rows: number; height: number; columns: number }) {
  if (rows <= 0) return null;
  return (
    <tr aria-hidden="true">
      <td colSpan={columns} style={{ height: rows * height, padding: 0, border: 0 }} />
    </tr>
  );
}

/** One cell renderer per column, so the header and the body cannot drift apart. */
function cell(gene: TargetSummary, key: string): React.ReactNode {
  switch (key) {
    case "rv_id":
      return gene.rv_id;
    case "gene_name":
      return gene.gene_name && gene.gene_name !== gene.rv_id ? gene.gene_name : "—";
    case "essentiality":
      return gene.essentiality ? (
        <>
          <i className="dot" style={{ background: colourOf(gene, "essentiality") }} />
          {gene.essentiality_label}
        </>
      ) : (
        <span className="absent">—</span>
      );
    case "vulnerability_index":
      return gene.vulnerability_index === null ? (
        "—"
      ) : (
        // Faint where the study does not stand behind the number.
        <span className={gene.vulnerability_certain ? undefined : "faint"}>
          {gene.vulnerability_index.toFixed(1)}
        </span>
      );
    case "n_pdb":
      return gene.n_pdb || "—";
    case "plddt_mean":
      return gene.plddt_mean ? gene.plddt_mean.toFixed(0) : "—";
    case "n_compounds":
      return gene.n_compounds || "—";
    case "n_protein_assays":
      return gene.n_protein_assays || "—";
    case "best_pchembl":
      return (
        <>
          {gene.best_pchembl?.toFixed(2) ?? "—"}
          {gene.chembl_evidence === "orthologue" && (
            <span className="chip ortho" style={{ marginLeft: 4 }}>
              o
            </span>
          )}
        </>
      );
    case "best_whole_cell_pchembl":
      return gene.best_whole_cell_pchembl?.toFixed(2) ?? "—";
    case "n_variants_associated":
      return gene.n_variants_associated || "—";
    case "best_drug_phase":
      return gene.best_drug_phase === null ? "—" : phaseLabel(gene.best_drug_phase);
    case "n_partners":
      return gene.n_partners || "—";
    case "n_references":
      return gene.n_references ?? "—";
    case "product":
      return (
        <>
          {gene.antibacterial && (
            <span className="chip accent" style={{ marginRight: 5 }}>
              {gene.antibacterial}
            </span>
          )}
          {gene.close_human_homolog && (
            <span
              className="chip warn"
              style={{ marginRight: 5 }}
              title={`Human homolog ${gene.human_homolog_gene ?? ""} at ${Math.round(
                (gene.human_homolog_identity ?? 0) * 100,
              )}% identity`}
            >
              human
            </span>
          )}
          {gene.product}
        </>
      );
    default:
      return null;
  }
}

function useTheme() {
  const [theme, setTheme] = useState<string>(
    () => document.documentElement.getAttribute("data-theme") ?? "system",
  );
  const toggle = useCallback(() => {
    const root = document.documentElement;
    const dark =
      root.getAttribute("data-theme") === "dark" ||
      (!root.hasAttribute("data-theme") &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    const next = dark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    setTheme(next);
  }, []);
  return { theme, toggle };
}

export function App() {
  const { theme, toggle } = useTheme();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [all, setAll] = useState<TargetSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [essentiality, setEssentiality] = useState<Set<string>>(new Set());
  const [category, setCategory] = useState<Set<string>>(new Set());
  const [flags, setFlags] = useState<Set<Flag>>(new Set());
  // Anti-target filter: hide anything sharing a UniRef cluster with a human
  // protein. Off by default, because UniRef50 co-membership is a family-level
  // flag rather than a measured identity.
  const [hideHumanHomologs, setHideHumanHomologs] = useState(false);
  const [colourBy, setColourBy] = useState<ColourBy>("essentiality");
  const [zoomed, setZoomed] = useState(false);
  const [sort, setSort] = useState<{ key: string; order: "asc" | "desc" }>({
    key: "start",
    order: "asc",
  });

  const [view, setView] = useState<"genome" | "clinical">("genome");
  const [focus, setFocus] = useState<Focus>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TargetDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  // The whole genome once: 4,031 rows is small, and holding it locally keeps
  // the canvas, the filters and the counts in step without a round trip each.
  useEffect(() => {
    Promise.all([api.meta(), api.targets({ limit: 5000, sort: "start" })])
      .then(([m, page]) => {
        setMeta(m);
        setAll(page.items);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  // Landing on a pre-opened gene meant landing in the narrow layout. The whole
  // table at full width is the better first screen; dprE1 is one click away.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Esc closes the thing most recently in front of you: the full-size
      // genome if it is open, otherwise the detail panel.
      setZoomed((open) => {
        if (open) return false;
        setSelected(null);
        setFocus(null);
        return false;
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    setDetailError(null);
    api
      .target(selected)
      .then(setDetail)
      .catch((e: unknown) => setDetailError(String(e)));
  }, [selected]);

  const filtered = useMemo(() => {
    const text = query.trim().toLowerCase();
    return all.filter((gene) => {
      if (essentiality.size && !essentiality.has(gene.essentiality ?? "")) return false;
      if (category.size && !category.has(gene.category ?? "")) return false;
      for (const flag of flags) if (!gene[flag]) return false;
      if (hideHumanHomologs && gene.close_human_homolog) return false;
      if (!text) return true;
      return (
        gene.rv_id.toLowerCase().includes(text) ||
        (gene.gene_name ?? "").toLowerCase().includes(text) ||
        (gene.product ?? "").toLowerCase().includes(text) ||
        (gene.uniprot_acc ?? "").toLowerCase().includes(text) ||
        (gene.drug_names ?? []).some((name) => name.toLowerCase().includes(text))
      );
    });
  }, [all, query, essentiality, category, flags, hideHumanHomologs]);

  const sorted = useMemo(() => {
    const direction = sort.order === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const left = a[sort.key as keyof TargetSummary];
      const right = b[sort.key as keyof TargetSummary];
      if (left === null || left === undefined) return 1;
      if (right === null || right === undefined) return -1;
      if (left === right) return a.rv_id.localeCompare(b.rv_id);
      return (left > right ? 1 : -1) * direction;
    });
  }, [filtered, sort]);

  const matching = useMemo(() => new Set(filtered.map((g) => g.rv_id)), [filtered]);
  const narrowed = filtered.length !== all.length && all.length > 0;

  // The table holds every gene, so only the rows on screen are rendered.
  // Without this a sort reorders 4,173 keyed rows, which is half a second of
  // DOM work however well the rows themselves are memoised.
  const scroller = useRef<HTMLDivElement | null>(null);
  const [viewport, setViewport] = useState({ top: 0, height: 900 });
  const [rowHeight, setRowHeight] = useState(30);
  useEffect(() => {
    // The distance between two rows, not one row's box: with collapsed
    // borders those differ by half a pixel, and over 4,000 spacer rows half a
    // pixel is a two-thousand-pixel lie in the scrollbar.
    const rows = scroller.current?.querySelectorAll("tbody tr.generow");
    if (!rows || rows.length < 2) return;
    const measured = rows[1].getBoundingClientRect().top - rows[0].getBoundingClientRect().top;
    if (measured > 1 && Math.abs(measured - rowHeight) > 0.05) setRowHeight(measured);
  });
  // Clamped so the window is never empty. The spacer's height is derived from
  // `rowHeight` and the scroll position is derived from the spacer, so a
  // corrected measurement can briefly put the scroll position past where the
  // new maths expects the last row to be.
  const firstRow = Math.min(
    Math.max(0, sorted.length - 1),
    Math.max(0, Math.floor(viewport.top / rowHeight) - OVERSCAN),
  );
  const lastRow = Math.min(
    sorted.length,
    Math.max(firstRow + 1, Math.ceil((viewport.top + viewport.height) / rowHeight) + OVERSCAN),
  );
  // With a gene open the table yields most of its width to the detail panel.
  const columns = useMemo(
    () =>
      selected
        ? COLUMNS.filter(([key]) => SCAN_COLUMNS.has(key) || key === sort.key)
        : COLUMNS,
    [selected, sort.key],
  );
  const counted = useCallback(
    (predicate: (gene: TargetSummary) => boolean) => all.filter(predicate).length,
    [all],
  );

  const openGene = useCallback((rvId: string) => {
    setSelected(rvId);
    setView("genome");
  }, []);
  const openClinical = useCallback((next: Focus) => {
    setFocus(next);
    setView("clinical");
  }, []);

  const toggleIn = <T,>(set: Set<T>, value: T, apply: (next: Set<T>) => void) => {
    const next = new Set(set);
    next.has(value) ? next.delete(value) : next.add(value);
    apply(next);
  };

  if (error) {
    return (
      <div className="errbox">
        <b>Could not reach the API.</b>
        <p>{error}</p>
        <p className="dim">
          Start it with <code>make api</code>, then reload. The frontend reads only the API, and the
          API reads only the built store — so <code>make build</code> has to have run at least once.
        </p>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>Mtb Target Atlas</h1>
          <em>H37Rv</em>
        </div>
        {/* Eight static facts about the store restated what the rail already
            counts per filter. What is worth a permanent line is the answer to
            "what have I narrowed to", which changes as you work. */}
        {meta && (
          <div className="topstats">
            {view === "genome" && narrowed ? (
              <span className="hero">
                <b>{filtered.length.toLocaleString()}</b> of{" "}
                {meta.counts.genes.toLocaleString()} genes match
              </span>
            ) : (
              <span>
                <b>{meta.counts.genes.toLocaleString()}</b> genes
              </span>
            )}
            <span>
              <b>{meta.counts.essential.toLocaleString()}</b> essential
            </span>
            <span>
              <b>{(meta.counts.vulnerability_measured ?? 0).toLocaleString()}</b> vulnerability
              measured
            </span>
            {/* Absent, not zero, when the clinical stage has not run here. */}
            <span>
              <b>{meta.counts.with_clinical_drug?.toLocaleString() ?? "—"}</b> with a TB drug ·{" "}
              <b>{meta.counts.trials?.toLocaleString() ?? "—"}</b> trials
            </span>
            <span className={narrowed ? undefined : "hero"}>
              <b>{meta.counts.structural_gap.toLocaleString()}</b> essential · structure · no
              ligands
            </span>
          </div>
        )}
        <Search
          onPick={(kind, id) => {
            if (kind === "genes") openGene(id);
            else if (kind === "trials") openClinical({ kind: "trial", id });
            else if (kind === "compounds") openClinical({ kind: "compound", id });
            else openClinical({ kind: "drug", id });
          }}
        />
        <div className="viewswitch" role="group" aria-label="View">
          <button type="button" aria-pressed={view === "genome"} onClick={() => setView("genome")}>
            Genome
          </button>
          <button type="button" aria-pressed={view === "clinical"} onClick={() => setView("clinical")}>
            Drugs &amp; trials
          </button>
        </div>
        <button className="iconbtn" type="button" onClick={toggle}>
          Theme
        </button>
      </header>

      <Ask base={import.meta.env.VITE_API_BASE ?? "/api"} />

      {view === "clinical" ? (
        <DrugsAndTrials meta={meta} focus={focus} onFocus={setFocus} onSelectGene={openGene} />
      ) : (
        <div className={`body${selected ? " detail-open" : ""}`}>
          <aside className="col col-pad">
            {/* The ring lives with the control that colours it: it is that
                control's legend, and it was reserving a 1,237px band to draw a
                340px circle. Filtered-out genes draw faint, so it answers
                "where do my 281 sit" rather than "here is a genome". */}
            <div className="railring">
              <GenomeCanvas
                genes={all}
                matching={matching}
                colourBy={colourBy}
                selected={selected}
                onSelect={setSelected}
                theme={theme}
              />
              <button
                className="maximise"
                type="button"
                title="Open the genome full size"
                aria-label="Open the genome full size"
                onClick={() => setZoomed(true)}
              >
                ⤢
              </button>
            </div>

            <div className="group">
              <p className="lab">Search</p>
              <input
                className="search"
                type="search"
                value={query}
                placeholder="Rv3790, dprE1, epimerase"
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>

            <div className="group">
              <p className="lab">Rings, inner to outer</p>
              <p className="ringkey">
                the discovery pipeline: what a gene is, then whether it can be lost, seen,
                measured, hit, and taken to the clinic. Pick one to bring it forward.
              </p>
              <div className="seg rings">
                {COLOUR_MODES.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={colourBy === key}
                    onClick={() => setColourBy(key)}
                  >
                    <span className="name">{label}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="group">
              <p className="lab">Restrict to</p>
              <div className="seg">
                {FLAGS.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={flags.has(key)}
                    onClick={() => toggleIn(flags, key, setFlags)}
                  >
                    <span className="name">{label}</span>
                    <span className="c">{counted((g) => Boolean(g[key]))}</span>
                  </button>
                ))}
                <button
                  type="button"
                  aria-pressed={hideHumanHomologs}
                  onClick={() => setHideHumanHomologs((v) => !v)}
                  title="Hide genes with a human homolog at 30% identity or more"
                >
                  <span className="name">No close human homolog</span>
                  <span className="c">{counted((g) => !g.close_human_homolog)}</span>
                </button>
              </div>
            </div>

            <div className="group">
              <p className="lab">Essentiality</p>
              <div className="seg">
                {ESSENTIALITY.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={essentiality.has(key)}
                    onClick={() => toggleIn(essentiality, key, setEssentiality)}
                  >
                    <span className="name">
                      <i className="sw" style={{ background: `var(--ess-${key})` }} />
                      {label}
                    </span>
                    <span className="c">{counted((g) => g.essentiality === key)}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="group">
              <p className="lab">Functional category</p>
              <div className="seg">
                {CATEGORIES.map((name) => (
                  <button
                    key={name}
                    type="button"
                    aria-pressed={category.has(name)}
                    onClick={() => toggleIn(category, name, setCategory)}
                    title={name}
                  >
                    <span className="name" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                      {name}
                    </span>
                    <span className="c">{counted((g) => g.category === name)}</span>
                  </button>
                ))}
              </div>
            </div>

            {meta && (
              <div className="group sources">
                <p className="lab">Sources</p>
                {meta.sources.map((s, index) => (
                  <div key={`${s.name}-${s.version}-${index}`}>
                    <b>{s.name}</b> {s.version} · {s.licence}
                  </div>
                ))}
              </div>
            )}
          </aside>

          <main className="col canvascol">
            <div className="listhead">
              <h2>
                {flags.size || essentiality.size || category.size || query
                  ? "Matching genes"
                  : "All genes"}
              </h2>
              {/* "All genes" used to sit above a table holding the first 300
                  of them. All of them are in here now, so the heading is the
                  whole truth and the count has nothing left to qualify. */}
              <span className="count">
                {sorted.length.toLocaleString()} of {all.length.toLocaleString()}
              </span>
            </div>
            <div
              className="scroller"
              style={{ flex: 1, minHeight: 0 }}
              ref={scroller}
              onScroll={(event) =>
                setViewport({
                  top: event.currentTarget.scrollTop,
                  height: event.currentTarget.clientHeight,
                })
              }
            >
              <table>
                <thead>
                  <tr>
                    {columns.map(([key, label, numeric]) => (
                      <th
                        key={key}
                        className={numeric ? "n" : undefined}
                        aria-sort={
                          sort.key === key
                            ? sort.order === "asc"
                              ? "ascending"
                              : "descending"
                            : undefined
                        }
                        onClick={() =>
                          setSort((current) =>
                            current.key === key
                              ? { key, order: current.order === "asc" ? "desc" : "asc" }
                              : {
                                  key,
                                  order: !numeric || LOWER_IS_BETTER.has(key) ? "asc" : "desc",
                                },
                          )
                        }
                      >
                        {label}
                        {sort.key === key ? (sort.order === "asc" ? " ↑" : " ↓") : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <Spacer rows={firstRow} height={rowHeight} columns={columns.length} />
                  {sorted.slice(firstRow, lastRow).map((gene) => (
                    <GeneRow
                      key={gene.rv_id}
                      gene={gene}
                      columns={columns}
                      selected={gene.rv_id === selected}
                      onSelect={setSelected}
                    />
                  ))}
                  <Spacer
                    rows={sorted.length - lastRow}
                    height={rowHeight}
                    columns={columns.length}
                  />
                </tbody>
              </table>
            </div>
          </main>

          <aside className="col detailcol">
            {/* Closing returns the table to its full width, which is the other
                half of the trade: browse wide, or read wide. */}
            <button
              className="closedetail"
              type="button"
              title="Close and widen the gene table (Esc)"
              aria-label="Close gene detail"
              onClick={() => setSelected(null)}
            >
              ×
            </button>
            {detailError ? (
              <div className="errbox">{detailError}</div>
            ) : detail ? (
              <TargetDetailPanel detail={detail} meta={meta} onOpen={openClinical} />
            ) : (
              <div className="empty">Loading {selected}…</div>
            )}
          </aside>
        </div>
      )}

      {zoomed && (
        <GenomeOverlay
          genes={all}
          matching={matching}
          colourBy={colourBy}
          setColourBy={setColourBy}
          selected={selected}
          theme={theme}
          onSelect={(rv) => {
            setSelected(rv);
            setZoomed(false);
          }}
          onClose={() => setZoomed(false)}
        />
      )}
    </div>
  );
}

/** The same rings, as large as the window allows.
 *
 * In the rail the ring is a locator; here it is the thing you are reading, so
 * the legend comes with it and each entry says how many genes reach that
 * stage. Clicking a gene selects it and closes, because the point of finding
 * one on the ring is to read its page.
 */
function GenomeOverlay({
  genes,
  matching,
  colourBy,
  setColourBy,
  selected,
  theme,
  onSelect,
  onClose,
}: {
  genes: TargetSummary[];
  matching: Set<string>;
  colourBy: ColourBy;
  setColourBy: (by: ColourBy) => void;
  selected: string | null;
  theme: string;
  onSelect: (rv: string) => void;
  onClose: () => void;
}) {
  const reaching = (key: ColourBy) => {
    const ring = RINGS.find((r) => r.key === key);
    return ring ? genes.filter((g) => ring.on(g) && matching.has(g.rv_id)).length : 0;
  };
  return (
    <div className="zoomscrim" role="dialog" aria-modal="true" aria-label="Genome" onClick={onClose}>
      <div className="zoompanel" onClick={(event) => event.stopPropagation()}>
        <div className="zoomring">
          <GenomeCanvas
            genes={genes}
            matching={matching}
            colourBy={colourBy}
            selected={selected}
            onSelect={onSelect}
            theme={theme}
            maxSize={1100}
          />
        </div>
        <div className="zoomlegend">
          <p className="lab">Rings, inner to outer</p>
          <div className="seg rings">
            {COLOUR_MODES.map(([key, label]) => (
              <button
                key={key}
                type="button"
                aria-pressed={colourBy === key}
                onClick={() => setColourBy(key)}
              >
                <span className="name">{label}</span>
                <span className="c">{reaching(key).toLocaleString()}</span>
              </button>
            ))}
          </div>
          <p className="ringkey">
            Counts are genes matching the current filters that reach that stage. A gene draws
            nothing on a ring it does not reach, so the narrowing outward is the funnel.
          </p>
        </div>
        <button className="closedetail" type="button" aria-label="Close" onClick={onClose}>
          ×
        </button>
      </div>
    </div>
  );
}
