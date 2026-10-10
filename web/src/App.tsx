/**
 * The one stop. Filters on the left, the whole genome in the middle, the full
 * evidence record for whatever you picked on the right -- and, one switch
 * away, the same layout for TB drugs and the trials testing them.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Meta, type TargetDetail, type TargetSummary } from "./api";
import { CATEGORIES, GenomeCanvas, colourOf, type ColourBy } from "./GenomeCanvas";
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

const COLOUR_MODES: [ColourBy, string][] = [
  ["essentiality", "Essentiality"],
  ["vulnerability", "Vulnerability"],
  ["structure", "Structure coverage"],
  ["chemistry", "Chemical matter"],
  ["resistance", "Resistance"],
  ["clinical", "Clinical stage"],
  ["category", "Functional category"],
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
      if (event.key === "Escape") setSelected(null);
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
              <p className="lab">Colour the genome by</p>
              <p className="ringkey">
                outer ring: {COLOUR_MODES.find(([k]) => k === colourBy)?.[1].toLowerCase()} · inner
                rings: structure, chemical matter, resistance
              </p>
              <div className="seg">
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
              <span className="count">
                {sorted.length.toLocaleString()} of {all.length.toLocaleString()}
                {sorted.length > 300 ? " · showing first 300" : ""}
              </span>
            </div>
            <div className="scroller" style={{ flex: 1, minHeight: 0 }}>
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
                  {sorted.slice(0, 300).map((gene) => (
                    <tr
                      key={gene.rv_id}
                      aria-selected={gene.rv_id === selected}
                      onClick={() => setSelected(gene.rv_id)}
                    >
                      {columns.map(([key, , numeric]) => (
                        <td key={key} className={cellClass(key, numeric)}>
                          {cell(gene, key)}
                        </td>
                      ))}
                    </tr>
                  ))}
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
    </div>
  );
}
