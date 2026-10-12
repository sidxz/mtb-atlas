/**
 * The one stop. Filters on the left, the whole genome in the middle, the full
 * evidence record for whatever you picked on the right -- and, one switch
 * away, the same layout for TB drugs and the trials testing them.
 */

import { FilterRail } from "./FilterRail";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Meta, type TargetDetail, type TargetSummary } from "./api";
import { CATEGORIES, GenomeCanvas, RINGS, colourOf, type ColourBy } from "./GenomeCanvas";
import { TargetDetailPanel } from "./TargetDetail";
import { Ask } from "./Ask";
import { DrugsAndTrials, phaseLabel, type Focus } from "./Clinical";
import { HitProfiling, Screens } from "./Screens";
import { Targets } from "./Targets";
import { AtlasMap, type MapOpenKind } from "./Map";
import { Search } from "./Search";
import { TableControls, useTablePreferences } from "./TableControls";
import { cellFormatting, scaleRanges, type Rule, type Range } from "./table-formatting";
import { InterfaceIcon } from "./InterfaceIcon";
import { Link, matchPath, useLocation, useNavigate } from "react-router";

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
  ["category", "Genes"],
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
  ["vulnerability_index", "Vulnerability", true],
  ["n_pdb", "PDB", true],
  ["n_orthologue_pdb", "Relative's PDB", true],
  ["plddt_mean", "pLDDT", true],
  ["n_compounds", "Compounds", true],
  ["n_protein_assays", "Assays", true],
  ["best_pchembl", "Best pChEMBL", true],
  ["best_pmic", "Best pMIC", true],
  ["best_whole_cell_pchembl", "Cell IC50", true],
  ["n_precedent_approved", "Fold precedent", true],
  ["n_close_paralogs", "Paralogs", true],
  ["n_variants_associated", "WHO", true],
  ["best_drug_phase", "TB phase", true],
  ["n_partners", "Partners", true],
  ["n_references", "References", true],
  ["product", "Product", false],
];

const COLUMN_GROUPS = [
  { label: "Gene identity", keys: ["rv_id", "gene_name"] },
  { label: "Target biology", keys: ["essentiality", "vulnerability_index", "n_close_paralogs"] },
  { label: "Structures", keys: ["n_pdb", "n_orthologue_pdb", "plddt_mean"] },
  {
    label: "Chemical evidence",
    keys: [
      "n_compounds",
      "n_protein_assays",
      "best_pchembl",
      "best_pmic",
      "best_whole_cell_pchembl",
      "n_precedent_approved",
    ],
  },
  { label: "Clinical evidence", keys: ["n_variants_associated", "best_drug_phase"] },
  { label: "Context", keys: ["n_partners", "n_references"] },
  { label: "Annotation", keys: ["product"] },
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
  rules,
  ranges,
}: {
  gene: TargetSummary;
  columns: [string, string, boolean][];
  selected: boolean;
  onSelect: (rv: string) => void;
  rules: Rule[];
  ranges: Range[];
}) {
  return (
    <tr className="generow" aria-selected={selected} onClick={() => onSelect(gene.rv_id)}>
      {columns.map(([key, , numeric]) => (
        <td key={key} data-column={key} className={cellClass(key, numeric)} style={cellFormatting(gene, key, rules, ranges)}>
          {key === "rv_id" ? (
            <button className="row-open" type="button" onClick={(event) => { event.stopPropagation(); onSelect(gene.rv_id); }} aria-label={`Inspect ${gene.rv_id}`}>
              {gene.rv_id}
            </button>
          ) : cell(gene, key)}
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
        <span className="essentiality-cell" title={gene.essentiality_label ?? undefined}>
          <i className="dot" style={{ background: colourOf(gene, "essentiality") }} />
          {gene.essentiality_label}
        </span>
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
      return gene.n_pdb ?? "—";
    // A structure to work from that is not of this protein. Separate from PDB
    // on purpose: 3,146 genes have no entry of their own, and reading a
    // borrowed one into that column would make the zero mean nothing.
    case "n_orthologue_pdb":
      return gene.n_orthologue_pdb ? (
        <span
          title={
            gene.same_sequence_structure
              ? `identical sequence deposited under another accession (${gene.closest_orthologue_organism})`
              : `closest: ${gene.closest_orthologue_gene} of ${gene.closest_orthologue_organism}, ` +
                `${Math.round((gene.closest_orthologue_identity ?? 0) * 100)}% identity over ` +
                `${Math.round((gene.closest_orthologue_coverage ?? 0) * 100)}% of the protein`
          }
        >
          {gene.n_orthologue_pdb}
          {gene.same_sequence_structure && (
            <span className="chip ok" style={{ marginLeft: 4 }}>
              =
            </span>
          )}
        </span>
      ) : (
        "—"
      );
    // Approved drugs on another protein sharing a Pfam domain. NULL means no
    // domain annotated, which is a different answer from zero, so the two do
    // not render the same.
    case "n_precedent_approved":
      if (gene.n_precedent_approved === null) return <span className="faint">n/a</span>;
      return gene.n_precedent_approved ? (
        <span
          title={
            `${gene.n_precedent_approved} approved drug(s) filed against another protein ` +
            `carrying ${gene.precedent_pfam_name} (${gene.precedent_pfam}), e.g. ` +
            `${gene.precedent_example}. ${gene.n_precedent_human_target} on a human protein. ` +
            `${gene.precedent_domain_genes} Mtb genes carry that domain, and a shared domain ` +
            `is not a shared binding site.`
          }
        >
          {gene.n_precedent_approved}
          {gene.n_precedent_human_target === gene.n_precedent_approved && (
            <span className="chip" style={{ marginLeft: 4 }} title="all of it on human proteins">
              hs
            </span>
          )}
        </span>
      ) : (
        "—"
      );
    case "plddt_mean":
      return gene.plddt_mean?.toFixed(0) ?? "—";
    case "n_compounds":
      return gene.n_compounds ?? "—";
    case "n_protein_assays":
      return gene.n_protein_assays ?? "—";
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
    // The MIC-derived number. ChEMBL leaves pchembl_value null on every MIC,
    // so "Cell IC50" beside it is a different endpoint on far fewer genes.
    case "best_pmic":
      return gene.best_pmic?.toFixed(2) ?? "—";
    case "best_whole_cell_pchembl":
      return gene.best_whole_cell_pchembl?.toFixed(2) ?? "—";
    // Full-length backup copies, not family members: a shared domain is not
    // redundancy, so this is the stricter count.
    case "n_close_paralogs":
      return gene.n_close_paralogs ? (
        <span title={`closest: ${gene.closest_paralog_gene} at ${Math.round((gene.closest_paralog_identity ?? 0) * 100)}% identity`}>
          {gene.n_close_paralogs}
        </span>
      ) : (
        "—"
      );
    case "n_variants_associated":
      return gene.n_variants_associated ?? "—";
    case "best_drug_phase":
      return gene.best_drug_phase === null ? "—" : phaseLabel(gene.best_drug_phase);
    case "n_partners":
      return gene.n_partners ?? "—";
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
              className="chip homology"
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

type View = "genome" | "targets" | "screens" | "hits" | "clinical" | "map";
const VIEWS: View[] = ["genome", "targets", "screens", "hits", "clinical", "map"];
const FOCUS_KINDS = ["drug", "trial", "compound"] as const;

/**
 * The view and the one object open in it, from the path:
 * `/genome/Rv3790`, `/targets/Rv1484`, `/screens/pubchem:1671178`, `/hits/CHEMBL64`,
 * `/clinical/drug/CHEMBL64`, `/map/Rv0206c`. `/` is the genome with nothing open.
 */
function parseRoute(pathname: string): { view: View; id: string | null; focus: Focus } {
  const clinical = matchPath("/clinical/:kind/:id", pathname);
  const kind = FOCUS_KINDS.find(k => k === clinical?.params.kind);
  if (clinical && kind) {
    const id = decode(clinical.params.id!);
    return { view: "clinical", id, focus: { kind, id } };
  }
  const match = matchPath("/:view/:id?", pathname);
  const view = VIEWS.find(v => v === match?.params.view);
  if (!view) return { view: "genome", id: null, focus: null };
  const id = match?.params.id;
  return { view, id: view === "clinical" || !id ? null : decode(id), focus: null };
}

// matchPath hands params back still encoded; `path` encodes them (screen ids carry
// colons). A malformed escape in a hand-typed URL is kept as typed, not thrown.
function decode(segment: string) {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

const path = (view: View, id?: string | null) => (id ? `/${view}/${encodeURIComponent(id)}` : `/${view}`);

export function App() {
  const { theme, toggle } = useTheme();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [all, setAll] = useState<TargetSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [essentiality, setEssentiality] = useState<Set<string>>(new Set());
  const [category, setCategory] = useState<Set<string>>(new Set());
  const [geneQuery, setGeneQuery] = useState("");
  const [flags, setFlags] = useState<Set<Flag>>(new Set());
  // Anti-target filter: hide anything sharing a UniRef cluster with a human
  // protein. Off by default, because UniRef50 co-membership is a family-level
  // flag rather than a measured identity.
  const [hideHumanHomologs, setHideHumanHomologs] = useState(false);
  const { preferences, saved, change: changePreferences } = useTablePreferences(COLUMNS);
  const [colourBy, setColourBy] = useState<ColourBy>("essentiality");
  const [zoomed, setZoomed] = useState(false);
  const zoomedRef = useRef(zoomed);
  zoomedRef.current = zoomed;
  // Kept across genes, so walking neighbours in the Locus tab stays wide.
  const [geneMaximized, setGeneMaximized] = useState(false);
  const geneMaximizedRef = useRef(geneMaximized);
  geneMaximizedRef.current = geneMaximized;
  const [sort, setSort] = useState<{ key: string; order: "asc" | "desc" }>({
    key: "start",
    order: "asc",
  });

  // The URL is the source of truth for the view and what is open in it. Each view
  // remembers its own last path, so a view kept mounted while hidden keeps what it
  // had open, and its nav link goes back to it.
  const location = useLocation();
  const navigate = useNavigate();
  const route = parseRoute(location.pathname);
  const view = route.view;
  const lastPath = useRef<Partial<Record<View, string>>>({});
  lastPath.current[view] = location.pathname;
  const routeIn = (v: View) => (v === view ? route : lastPath.current[v] ? parseRoute(lastPath.current[v]!) : null);
  const routeRef = useRef(route);
  routeRef.current = route;
  const [visitedViews, setVisitedViews] = useState<string[]>([]);
  useEffect(() => { setVisitedViews(previous => previous.includes(view) ? previous : [...previous, view]); }, [view]);
  const hitFocus = routeIn("hits")?.id ?? null;
  const setHitFocus = useCallback((id: string | null) => navigate(path("hits", id)), [navigate]);
  // A campaign opened from a gene page or the search box, so those routes reach
  // the same page rather than a second copy of it.
  const screenFocus = routeIn("screens")?.id ?? null;
  const setScreenFocus = useCallback((id: string | null) => navigate(path("screens", id)), [navigate]);
  const [screenGene, setScreenGene] = useState<{ rv: string } | null>(null);
  const mapRoot = routeIn("map")?.id ?? null;
  const targetSelected = routeIn("targets")?.id ?? null;
  const selectTarget = useCallback(
    (rv: string | null, options?: { replace?: boolean }) => navigate(path("targets", rv), options),
    [navigate],
  );
  // A campaign handed to hit profiling: its compounds, each with its own whole profile.
  const [profileScreen, setProfileScreen] = useState<{ id: string; title: string | null } | null>(null);
  const focus = routeIn("clinical")?.focus ?? null;
  const setFocus = useCallback(
    (next: Focus) => navigate(next ? `/clinical/${next.kind}/${encodeURIComponent(next.id)}` : "/clinical"),
    [navigate],
  );
  const selected = routeIn("genome")?.id ?? null;
  const setSelected = useCallback((rv: string | null) => navigate(path("genome", rv)), [navigate]);
  // Closing by any route (the ×, Esc, Back) ends maximized, or the table stays hidden.
  useEffect(() => {
    if (!selected) setGeneMaximized(false);
  }, [selected]);
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
      if (zoomedRef.current) {
        setZoomed(false);
        return;
      }
      if (geneMaximizedRef.current && routeRef.current.view === "genome") {
        setGeneMaximized(false);
        return;
      }
      const current = routeRef.current;
      if (current.view === "genome" && current.id) navigate("/genome");
      if (current.view === "clinical" && current.focus) navigate("/clinical");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

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
    const query = geneQuery.trim().toLowerCase();
    return all.filter((gene) => {
      if (query && !gene.rv_id.toLowerCase().includes(query) && !(gene.gene_name ?? "").toLowerCase().includes(query)) return false;
      if (essentiality.size && !essentiality.has(gene.essentiality ?? "")) return false;
      if (category.size && !category.has(gene.category ?? "")) return false;
      for (const flag of flags) if (!gene[flag]) return false;
      if (hideHumanHomologs && gene.close_human_homolog) return false;
      return true;
    });
  }, [all, essentiality, category, flags, hideHumanHomologs, geneQuery]);

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

  // The table holds every gene, so only the rows on screen are rendered.
  // Without this a sort reorders 4,173 keyed rows, which is half a second of
  // DOM work however well the rows themselves are memoised.
  const scroller = useRef<HTMLDivElement | null>(null);
  const [viewport, setViewport] = useState({ top: 0, height: 900 });
  const [rowHeight, setRowHeight] = useState(30);
  useEffect(() => {
    scroller.current?.scrollTo({ top: 0 });
    setViewport(current => ({ ...current, top: 0 }));
  }, [geneQuery]);
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
      preferences.visible !== null
        ? COLUMNS.filter(([key]) => preferences.visible!.includes(key))
        : selected
          ? COLUMNS.filter(([key]) => SCAN_COLUMNS.has(key) || key === sort.key)
          : COLUMNS,
    [selected, sort.key, preferences.visible],
  );
  const ranges = useMemo(() => scaleRanges(filtered, preferences.scales), [filtered, preferences.scales]);
  const counted = useCallback(
    (predicate: (gene: TargetSummary) => boolean) => all.filter(predicate).length,
    [all],
  );

  const openGene = setSelected;
  const openClinical = setFocus;
  const openMap = useCallback((rv: string) => navigate(path("map", rv)), [navigate]);

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
          <h1><i title="Mycobacterium tuberculosis">M. tuberculosis</i> Atlas</h1>
        </div>
        <div className="viewswitch" role="group" aria-label="View">
          <Link to={lastPath.current.genome ?? "/genome"} aria-current={view === "genome" ? "page" : undefined}>
            <InterfaceIcon name="genome" /> Genome
          </Link>
          {/* The nav is the early discovery pipeline, in order: target selection,
              screening, hit assessment, then the clinic. */}
          <Link to={lastPath.current.targets ?? "/targets"} aria-current={view === "targets" ? "page" : undefined}>
            <InterfaceIcon name="targets" /> Targets
          </Link>
          <Link to={lastPath.current.screens ?? "/screens"} aria-current={view === "screens" ? "page" : undefined}>
            <InterfaceIcon name="screens" /> Screens
          </Link>
          <Link to={lastPath.current.hits ?? "/hits"} aria-current={view === "hits" ? "page" : undefined}>
            <InterfaceIcon name="profiling" /> Hit profiling
          </Link>
          <Link to={lastPath.current.clinical ?? "/clinical"} aria-current={view === "clinical" ? "page" : undefined}>
            <InterfaceIcon name="clinical" /> Drugs &amp; trials
          </Link>
          <Link to={lastPath.current.map ?? "/map"} aria-current={view === "map" ? "page" : undefined}>
            <InterfaceIcon name="map" /> Map
          </Link>
        </div>
        <Search
          onPick={(kind, id) => {
            if (kind === "genes") openGene(id);
            else if (kind === "trials") openClinical({ kind: "trial", id });
            else if (kind === "compounds") openClinical({ kind: "compound", id });
            else if (kind === "screens") setScreenFocus(id);
            else openClinical({ kind: "drug", id });
          }}
        />
        <button className="iconbtn theme-toggle" type="button" onClick={toggle} title="Toggle color theme">
          <InterfaceIcon name="theme" /><span className="sr-only">Theme</span>
        </button>
      </header>

      <Ask base={import.meta.env.VITE_API_BASE ?? "/api"} />

      {(view === "screens" || visitedViews.includes("screens")) && <div className="workspace-view" hidden={view !== "screens"}>
        <Screens
          onSelectGene={openGene}
          focus={screenFocus}
          geneFocus={screenGene}
          onFocus={setScreenFocus}
          onProfile={(id, title) => { setProfileScreen({ id, title }); setHitFocus(null); }}
          onCompound={id => { setProfileScreen(null); setHitFocus(id); }}
        />
      </div>}
      {(view === "hits" || visitedViews.includes("hits")) && <div className="workspace-view" hidden={view !== "hits"}>
        <HitProfiling screen={profileScreen} onClearScreen={() => setProfileScreen(null)}
          focus={hitFocus} onFocus={setHitFocus} onSelectGene={openGene}
          onCampaign={setScreenFocus} />
      </div>}
      {/* Kept mounted, so a cohort survives a trip to Screens or Drugs and back. */}
      {(view === "targets" || visitedViews.includes("targets")) && <div className="workspace-view" hidden={view !== "targets"}>
        <Targets
          all={all}
          onOpenGene={openGene}
          onOpenScreens={rv => { setScreenGene({ rv }); setScreenFocus(null); }}
          onOpenDrug={id => openClinical({ kind: "drug", id })}
          selected={targetSelected}
          onSelect={selectTarget}
        />
      </div>}
      {/* Kept mounted too: a walk several hops deep is worth coming back to. */}
      {(view === "map" || visitedViews.includes("map")) && <div className="workspace-view" hidden={view !== "map"}>
        <AtlasMap all={all} root={mapRoot} onPick={openMap} onOpen={(kind: MapOpenKind, id) => {
          if (kind === "gene") openGene(id);
          else if (kind === "drug" || kind === "trial") openClinical({ kind, id });
          else if (kind === "screen") setScreenFocus(id);
          else { setProfileScreen(null); setHitFocus(id); }
        }} />
      </div>}
      {view === "clinical" ? (
        <DrugsAndTrials meta={meta} focus={focus} onFocus={setFocus} onSelectGene={openGene} />
      ) : view === "genome" ? (
        <div className={`body${selected ? " detail-open" : ""}`}>
          <FilterRail>
            <div className="rail-heading">
              <InterfaceIcon name="genome" />
              <h2>Genome explorer</h2>
              <button
                className="rail-expand"
                type="button"
                title="Open the genome full size"
                aria-label="Open the genome full size"
                onClick={() => setZoomed(true)}
              >
                <InterfaceIcon name="expand" />
              </button>
            </div>
            {/* Keep the genome overview compact; layer controls live in the
                maximized view, while this rail prioritizes target filters. */}
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

            <div className="rail-section">
              <InterfaceIcon name="filter" />Refine targets
              {(flags.size > 0 || essentiality.size > 0 || category.size > 0 || hideHumanHomologs || geneQuery) && (
                <button
                  className="clear-filters"
                  type="button"
                  aria-label="Clear filters"
                  onClick={() => {
                    setFlags(new Set());
                    setEssentiality(new Set());
                    setCategory(new Set());
                    setHideHumanHomologs(false);
                    setGeneQuery("");
                  }}
                >Clear</button>
              )}
            </div>
            <details className="group filtergroup" open>
              <summary>Restrict to{(flags.size + Number(hideHumanHomologs)) > 0 && <span className="filtercount">{flags.size + Number(hideHumanHomologs)} selected</span>}</summary>
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
            </details>

            <details className="group filtergroup">
              <summary>Essentiality{(essentiality.size) > 0 && <span className="filtercount">{essentiality.size} selected</span>}</summary>
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
            </details>

            <details className="group filtergroup">
              <summary>Functional category{(category.size) > 0 && <span className="filtercount">{category.size} selected</span>}</summary>
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
            </details>

            {meta && (
              <details className="group sources filtergroup">
                <summary>Sources</summary>
                {meta.sources.map((s, index) => (
                  <div key={`${s.name}-${s.version}-${index}`}>
                    <b>{s.name}</b> {s.version} · {s.licence}
                  </div>
                ))}
              </details>
            )}
          </FilterRail>

          <main className="col canvascol" aria-label="Target explorer">
            <TableControls
              leading={<>
                <span className="strain-label">H37Rv</span>
                <div className="table-gene-search" role="search" aria-label="Filter gene table">
                  <InterfaceIcon name="search" />
                  <input type="search" aria-label="Filter table by locus or gene" placeholder="Locus or gene…" value={geneQuery}
                    onChange={event => setGeneQuery(event.target.value)}
                    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); event.preventDefault(); setGeneQuery(""); } }} />
                  {geneQuery && <button type="button" aria-label="Clear gene search" onClick={() => setGeneQuery("")}>×</button>}
                </div>
              </>}
              columns={COLUMNS}
              groups={COLUMN_GROUPS}
              visible={columns}
              preferences={preferences}
              saved={saved}
              onChange={changePreferences}
              sortLabel={sort.key !== "start" && !columns.some(([key]) => key === sort.key) ? COLUMNS.find(([key]) => key === sort.key)?.[1] + (sort.order === "asc" ? " ↑" : " ↓") : undefined}
            />
            <span className="sr-only" role="status">{filtered.length.toLocaleString()} matching genes</span>
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
              <table className="gene-table">
                <thead>
                  <tr className="column-groups">
                    {COLUMN_GROUPS.map((group) => {
                      const span = columns.filter(([key]) => group.keys.includes(key)).length;
                      return span ? <th key={group.label} scope="colgroup" colSpan={span}>{group.label}</th> : null;
                    })}
                  </tr>
                  <tr>
                    {columns.map(([key, label, numeric]) => (
                      <th
                        key={key}
                        scope="col"
                        className={numeric ? "n" : undefined}
                        aria-sort={
                          sort.key === key
                            ? sort.order === "asc"
                              ? "ascending"
                              : "descending"
                            : undefined
                        }
                      >
                        <button
                          className="sortbutton"
                          type="button"
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
                          <span className="sorticon" aria-hidden="true">
                            {sort.key === key ? (sort.order === "asc" ? "↑" : "↓") : "↕"}
                          </span>
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {!sorted.length && <tr><td className="table-empty" colSpan={columns.length}>{all.length ? "No genes match the current search and filters." : "Loading genes…"}</td></tr>}
                  <Spacer rows={firstRow} height={rowHeight} columns={columns.length} />
                  {sorted.slice(firstRow, lastRow).map((gene) => (
                    <GeneRow
                      key={gene.rv_id}
                      gene={gene}
                      columns={columns}
                      selected={gene.rv_id === selected}
                      onSelect={setSelected}
                      rules={preferences.rules}
                      ranges={ranges}
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

          <aside className={`col detailcol${geneMaximized ? " is-maximized" : ""}`}>
            {/* Closing returns the table to its full width, which is the other
                half of the trade: browse wide, or read wide. */}
            {(!detail || detailError) && <button
              className="closedetail"
              type="button"
              title="Close and widen the gene table (Esc)"
              aria-label="Close gene detail"
              onClick={() => setSelected(null)}
            >
              ×
            </button>}
            {detailError ? (
              <div className="errbox">{detailError}</div>
            ) : detail ? (
              <TargetDetailPanel
                detail={detail}
                meta={meta}
                onOpen={openClinical}
                onOpenScreen={setScreenFocus}
                onClose={() => setSelected(null)}
                maximized={geneMaximized}
                onMaximize={() => setGeneMaximized((m) => !m)}
              />
            ) : (
              <div className="empty">Loading {selected}…</div>
            )}
          </aside>
        </div>
      ) : null}

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
          <p className="lab">Layers <span className="label-hint">inner → outer</span></p>
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
