/** The atlas as a graph: walk from any object to everything a source joins it to.
 *
 * A line is drawn only where a record joins two things, and it carries that
 * record's claim. Dashed lines are shown and not counted, the same rule the rest
 * of the atlas follows: complex membership, WHO resistance, a bound ligand, an
 * orthologue's structure. Empty groups stay on the map, because an absent record
 * is an answer. */
import { useEffect, useMemo, useRef, useState } from "react";
import { FilterRail } from "./FilterRail";
import { InterfaceIcon } from "./InterfaceIcon";
import { api, type ConceptKind, type DrugLink, type TargetSummary } from "./api";

type EntityKind = "gene" | "drug" | "compound" | "screen" | ConceptKind;
type Kind = EntityKind | "target" | "structure" | "trial" | "human" | "group" | "more";
export type MapOpenKind = "gene" | "drug" | "compound" | "screen" | "trial";

interface MapNode {
  key: string;
  kind: Kind;
  id: string;
  label: string;
  sub?: string | null;
  /** The claim on the line into this node. */
  edge?: string;
  /** Shown, not counted: drawn dashed. */
  weak?: boolean;
  children?: MapNode[];
  open?: boolean;
  loading?: boolean;
  error?: boolean;
  /** Group members drawn so far. */
  shown?: number;
  /** Already on the path from the root: drawn, never expanded again. */
  cycle?: boolean;
  /** A group's basis, for its tooltip. */
  basis?: string;
  /** A drug's highest TB phase, which picks the path opened by default. */
  phase?: number | null;
}

type Item = Omit<MapNode, "key">;

const ENTITY = new Set<Kind>(["gene", "drug", "compound", "screen", "pfam", "go", "pathway", "condition"]);
const PAGE = 12;
const COL = 230;
const ROW = 60;
const NODE_W = 206;

const KIND_LABEL: Record<Kind, string> = {
  gene: "Gene", drug: "Drug", compound: "Compound", screen: "Screen", pfam: "Pfam domain", go: "GO term",
  pathway: "Pathway", condition: "TnSeq condition", target: "ChEMBL target", structure: "Structure",
  trial: "Trial", human: "Human homologue", group: "", more: "",
};

// `mechanism` and `bosch_2021` are the two links that say a drug acts on the protein.
const LINK_LABEL: Record<DrugLink, string> = {
  mechanism: "ChEMBL mechanism",
  bosch_2021: "Bosch 2021",
  mechanism_complex: "complex member",
  structure: "bound in a structure",
  who_resistance: "WHO resistance, not a target claim",
};
const COUNTED: DrugLink[] = ["mechanism", "bosch_2021"];

const pct = (v: number | null | undefined) => (v == null ? "?" : `${Math.round(v * 100)}%`);
const num = (v: number | null | undefined) => (v == null ? null : v.toLocaleString());

function group(label: string, items: Item[], basis: string): Item {
  return { kind: "group", id: label, label, children: items as MapNode[], shown: PAGE, basis };
}

function drugItems(links: { molecule_chembl_id: string; pref_name: string | null; link: DrugLink; max_phase_tb?: number | null }[]): Item[] {
  const byId = new Map<string, { name: string; links: Set<DrugLink>; phase: number | null }>();
  for (const l of links) {
    const entry = byId.get(l.molecule_chembl_id) ?? { name: l.pref_name ?? l.molecule_chembl_id, links: new Set(), phase: l.max_phase_tb ?? null };
    entry.links.add(l.link);
    byId.set(l.molecule_chembl_id, entry);
  }
  return [...byId].map(([id, d]) => ({
    kind: "drug" as const, id, label: d.name,
    sub: d.phase == null ? null : d.phase >= 4 ? "approved for TB" : `TB phase ${d.phase}`,
    phase: d.phase,
    edge: [...d.links].map(l => LINK_LABEL[l]).join(" · "),
    weak: ![...d.links].some(l => COUNTED.includes(l)),
  })).sort((a, b) => Number(a.weak) - Number(b.weak) || (b.phase ?? -1) - (a.phase ?? -1));
}

async function neighbours(kind: EntityKind, id: string, byName: Map<string, string>): Promise<Item[]> {
  if (kind === "gene") {
    const d = await api.target(id);
    const potency = new Map<string, { best: number | null; evidence: string }>();
    for (const a of d.activities) {
      if (!a.molecule_chembl_id) continue;
      const seen = potency.get(a.molecule_chembl_id);
      const best = Math.max(seen?.best ?? -Infinity, a.pchembl_value ?? -Infinity);
      potency.set(a.molecule_chembl_id, { best: best === -Infinity ? null : best, evidence: seen?.evidence === "direct" ? "direct" : a.evidence });
    }
    const related: Item[] = [
      ...d.shares_accession_with.map(rv => ({ kind: "gene" as const, id: rv, label: rv, edge: "same UniProt accession" })),
      ...(d.closest_paralog_gene && byName.has(d.closest_paralog_gene)
        ? [{ kind: "gene" as const, id: byName.get(d.closest_paralog_gene)!, label: d.closest_paralog_gene, edge: `closest paralogue · ${pct(d.closest_paralog_identity)}` }]
        : []),
      ...(d.nearest_relative_gene && d.nearest_relative_gene !== d.closest_paralog_gene && byName.has(d.nearest_relative_gene)
        ? [{ kind: "gene" as const, id: byName.get(d.nearest_relative_gene)!, label: d.nearest_relative_gene, edge: "nearest relative, any coverage", weak: true }]
        : []),
      ...(d.human_homolog_gene
        ? [{ kind: "human" as const, id: d.human_homolog_acc ?? d.human_homolog_gene, label: d.human_homolog_gene, edge: `human · ${pct(d.human_homolog_identity)} identity` }]
        : []),
    ];
    const ortho = new Map(d.orthologue_structures.map(o => [o.pdb_id, o]));
    return [
      group("ChEMBL targets", d.chembl_targets.map(t => ({
        kind: "target", id: t.target_id, label: t.pref_name ?? t.target_id, sub: t.target_type,
        edge: t.evidence === "direct" ? "direct" : `orthologue · ${t.via_organism ?? "?"}${t.identity_level ? ` · ${t.identity_level}` : ""}`,
        weak: t.evidence !== "direct",
      })), "ChEMBL targets on this protein, or on an orthologue where there is no direct target."),
      group("Drugs", drugItems(d.drugs), "Solid: a source says the drug acts on this protein. Dashed: complex membership, a bound ligand or WHO resistance, shown and never counted."),
      group("Compounds", d.compounds.map(c => {
        const p = potency.get(c.molecule_chembl_id);
        return {
          kind: "compound" as const, id: c.molecule_chembl_id, label: c.pref_name ?? c.molecule_chembl_id,
          sub: p?.best == null ? null : `best pChEMBL ${p.best.toFixed(2)}`,
          edge: p?.evidence === "orthologue" ? "orthologue potency" : "protein potency", weak: p?.evidence === "orthologue",
          best: p?.best ?? -1,
        };
      }).sort((a, b) => b.best - a.best).map(({ best: _best, ...item }) => item), "Compounds with a protein-level measurement, best potency first."),
      group("Screens", d.screens.map(s => ({
        kind: "screen", id: s.screen_id, label: s.title ?? s.screen_id,
        sub: [s.depositor ?? s.source, s.year, s.n_tested == null ? null : `${num(s.n_tested)} tested`].filter(Boolean).join(" · "),
        edge: s.own ? "stage on this protein" : "stage on its complex", weak: !s.own,
      })), "Campaigns with a stage on this protein. Dashed: the stage is on a complex it belongs to."),
      group("STRING partners", d.partners.map(p => ({
        kind: "gene", id: p.rv_id, label: p.gene_name ?? p.rv_id, edge: `STRING ${(p.combined_score / 1000).toFixed(2)}`,
      })), "STRING functional association, combined score. Association is not physical binding."),
      group("Homologues", related, "Shared accession, closest paralogue (30% identity over 70% of the query), nearest relative at any coverage (dashed, not redundancy), and the closest human protein."),
      group("Structures", d.structures.map(s => ({
        kind: "structure", id: s.pdb_id, label: s.pdb_id,
        sub: [s.resolution == null ? null : `${s.resolution.toFixed(2)} Å`, s.method].filter(Boolean).join(" · "),
      })), "Experimental structures on this gene's own accession."),
      group("Orthologue structures", [...ortho.values()].map(o => ({
        kind: "structure", id: o.pdb_id, label: o.pdb_id, sub: o.via_organism,
        edge: o.relation === "same_sequence" ? "same sequence, other accession" : `${o.via_gene ?? o.via_acc} · ${pct(o.identity)} over ${pct(o.coverage)}`,
        weak: o.relation !== "same_sequence",
      })), "Structures of another accession. Same sequence is this protein; an orthologue is a relative, never one of the gene's own."),
      group("Pfam domains", d.pfam_ids.map(p => ({ kind: "pfam", id: p, label: p, edge: "UniProt" })), "Sharing a domain is not sharing a binding site."),
      group("GO terms", [...d.go_process, ...d.go_function].map(g => ({ kind: "go", id: g, label: g, edge: "UniProt GO" })), "Biological process and molecular function, as UniProt annotates them."),
      group("Pathways", d.pathways.map(p => ({ kind: "pathway", id: p, label: p, edge: "UniProt" })), "UniProt pathway annotation."),
      group("TnSeq conditions", d.conditions.map(c => ({
        kind: "condition", id: c.screen_id, label: c.description ?? c.screen_id, sub: c.study,
        edge: `log2FC ${c.log2fc?.toFixed(2) ?? "?"}${c.cross_study ? " · cross-study control" : ""}`,
      })), "Measured and significant at q < 0.05 (this atlas's cut) in an annotated MtbTnDB screen."),
    ];
  }
  if (kind === "drug") {
    const d = await api.drug(id);
    const genes = new Map<string, { name: string; links: Set<DrugLink> }>();
    for (const g of d.genes) {
      const entry = genes.get(g.rv_id) ?? { name: g.gene_name ?? g.rv_id, links: new Set() };
      entry.links.add(g.link);
      genes.set(g.rv_id, entry);
    }
    return [
      group("Genes", [...genes].map(([rv, g]) => ({
        kind: "gene" as const, id: rv, label: g.name, sub: rv,
        edge: [...g.links].map(l => LINK_LABEL[l]).join(" · "), weak: ![...g.links].some(l => COUNTED.includes(l)),
      })).sort((a, b) => Number(a.weak) - Number(b.weak)), "Solid: the drug acts on this gene's protein. Dashed: shown, not counted."),
      group("Trials", d.trials.map(t => ({
        kind: "trial", id: t.nct_id, label: t.nct_id, sub: t.brief_title,
        edge: [t.phase_max == null ? null : `phase ${t.phase_max}`, t.status?.toLowerCase().replaceAll("_", " ")].filter(Boolean).join(" · "),
      })), "Interventional trials linked through ChEMBL's reference or an exact intervention name."),
    ];
  }
  if (kind === "compound") {
    const d = await api.compound(id);
    const screens = new Map(d.tested_in.map(t => [t.screen_id, t]));
    return [
      group("Genes", d.genes.map(g => ({
        kind: "gene", id: g.rv_id, label: g.gene_name ?? g.rv_id,
        sub: g.best_pchembl == null ? g.rv_id : `best pChEMBL ${g.best_pchembl.toFixed(2)}`,
        edge: g.evidence === "direct" ? "direct" : `orthologue · ${g.via_organism ?? "?"}`, weak: g.evidence !== "direct",
      })), "Protein-level activity on the gene, or on an orthologue where it has no direct target."),
      group("Drug", d.drug ? [{ kind: "drug", id: d.drug.molecule_chembl_id, label: d.drug.pref_name ?? d.drug.molecule_chembl_id, edge: "same molecule" }] : [], "The compound is itself a TB-indication drug in ChEMBL."),
      group("Screens", [...screens.values()].map(t => ({
        kind: "screen", id: t.screen_id, label: t.screen_title ?? t.screen_id,
        sub: [t.screen_source, t.year].filter(Boolean).join(" · "), edge: "tested in",
      })), "Every campaign that tested it. Being tested is not being a hit."),
    ];
  }
  if (kind === "screen") {
    const d = await api.screen(id);
    return [group("Genes", d.genes.map(g => ({
      kind: "gene", id: g.rv_id, label: g.gene_name ?? g.rv_id, sub: g.rv_id,
      edge: g.own ? "stage on this protein" : "stage on a complex", weak: !g.own,
    })), "Genes a stage of this campaign is run on. A phenotypic screen reaches none.")];
  }
  const d = await api.concept(kind, id);
  return [group("Genes", d.genes.map(g => ({
    kind: "gene", id: g.rv_id, label: g.gene_name ?? g.rv_id, sub: g.product,
    edge: g.log2fc == null ? "shares it" : `log2FC ${g.log2fc.toFixed(2)}`,
  })), d.basis)];
}

const entityKey = (n: { kind: Kind; id: string }) => `${n.kind}:${n.id}`;

function keyed(item: Item, parent: string, path: Set<string>): MapNode {
  const key = `${parent}/${item.kind}:${encodeURIComponent(item.id)}`;
  return {
    ...item,
    key,
    cycle: ENTITY.has(item.kind) && path.has(entityKey(item)),
    children: item.children?.map(c => keyed(c, key, path)),
  };
}

function update(node: MapNode, key: string, change: (n: MapNode) => MapNode): MapNode {
  if (node.key === key) return change(node);
  if (!node.children || !key.startsWith(`${node.key}/`)) return node;
  return { ...node, children: node.children.map(c => update(c, key, change)) };
}

function visible(node: MapNode): MapNode[] {
  if (!node.open || !node.children) return [];
  if (node.kind !== "group") return node.children;
  const shown = node.shown ?? PAGE;
  const rest = node.children.length - shown;
  return rest > 0
    ? [...node.children.slice(0, shown), { key: `${node.key}/more`, kind: "more", id: node.key, label: `+${rest.toLocaleString()} more` }]
    : node.children;
}

interface Placed { node: MapNode; x: number; y: number; path: Set<string> }

function layout(root: MapNode) {
  const placed: Placed[] = [];
  const links: { x1: number; y1: number; x2: number; y2: number; weak: boolean; key: string }[] = [];
  let row = 0;
  const place = (node: MapNode, depth: number, path: Set<string>): number => {
    const here = ENTITY.has(node.kind) ? new Set([...path, entityKey(node)]) : path;
    const kids = visible(node);
    let y: number;
    if (kids.length) {
      const ys = kids.map(k => place(k, depth + 1, here));
      // Keep a branch on the same reading line as its first child. This also
      // keeps ancestors steady as deeper branches expand beneath them.
      y = ys[0];
      kids.forEach((k, i) => links.push({ x1: depth * COL + NODE_W, y1: y, x2: (depth + 1) * COL, y2: ys[i], weak: !!k.weak, key: k.key }));
    } else {
      y = row++ * ROW + ROW / 2;
    }
    placed.push({ node, x: depth * COL, y, path: here });
    return y;
  };
  place(root, 0, new Set());
  const width = Math.max(...placed.map(p => p.x)) + NODE_W + 24;
  return { placed, links, width, height: row * ROW + 8 };
}

const START = ["dprE1", "inhA", "mmpL3", "groEL2", "trpS"];

export function AtlasMap({ all, root: rootGene, onPick, onOpen }: {
  all: TargetSummary[];
  /** The gene the map is rooted at, from the URL. */
  root: string | null;
  /** Re-root the map: the parent puts it in the URL, which comes back as `root`. */
  onPick: (rv: string) => void;
  onOpen: (kind: MapOpenKind, id: string) => void;
}) {
  const genes = useMemo(() => all.filter(g => g.feature === "CDS"), [all]);
  const byName = useMemo(() => new Map(genes.flatMap(g => [[g.rv_id.toLowerCase(), g.rv_id], ...(g.gene_name ? [[g.gene_name.toLowerCase(), g.rv_id] as const] : [])])), [genes]);
  const resolveName = useMemo(() => new Map(genes.filter(g => g.gene_name).map(g => [g.gene_name!, g.rv_id])), [genes]);
  const [root, setRoot] = useState<MapNode | null>(null);
  const [query, setQuery] = useState("");
  const [missing, setMissing] = useState(false);
  const canvas = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [focusedKey, setFocusedKey] = useState<string | null>(null);
  const [startingKey, setStartingKey] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const motion = (): ScrollBehavior => window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  const scrollToNode = (selector: string, center = false) => requestAnimationFrame(() => {
    const el = canvas.current;
    const node = el?.querySelector(selector);
    if (!el || !node) return;
    const box = node.getBoundingClientRect();
    const view = el.getBoundingClientRect();
    const delta = (start: number, end: number, low: number, high: number) =>
      center ? (start + end - low - high) / 2 : start < low ? start - low : end > high ? end - high : 0;
    el.scrollTo({
      left: el.scrollLeft + delta(box.left, box.right, view.left + 16, view.right - 16),
      top: el.scrollTop + delta(box.top, box.bottom, view.top + 16, view.bottom - 16),
      behavior: motion(),
    });
  });
  const focusNode = (key: string) => {
    setFocusedKey(key);
    scrollToNode(`[data-key="${CSS.escape(key)}"]`, true);
  };

  // Scroll only the canvas, never the surrounding page or a hidden workspace.
  const reveal = (key: string) => scrollToNode(`[data-parent="${CSS.escape(key)}"]`);

  const expand = async (node: MapNode, path: Set<string>) => {
    setFocusedKey(node.kind === "more" ? node.id : node.key);
    if (node.kind === "more") {
      setRoot(r => r && update(r, node.id, g => ({ ...g, shown: (g.shown ?? PAGE) + PAGE })));
      return;
    }
    if (node.cycle || node.loading) return;
    if (node.kind === "group") {
      if (node.children?.length) {
        setRoot(r => r && update(r, node.key, g => ({ ...g, open: !g.open })));
        if (!node.open) reveal(node.key);
      }
      return;
    }
    if (!ENTITY.has(node.kind)) return;
    if (node.children) {
      setRoot(r => r && update(r, node.key, n => ({ ...n, open: !n.open })));
      if (!node.open) reveal(node.key);
      return;
    }
    const token = current.current;
    setRoot(r => r && update(r, node.key, n => ({ ...n, loading: true, error: false })));
    try {
      const items = await neighbours(node.kind as EntityKind, node.id, resolveName);
      if (token !== current.current) return;
      setRoot(r => r && update(r, node.key, n => ({ ...n, loading: false, open: true, children: items.map(i => keyed(i, n.key, path)) })));
      reveal(node.key);
    } catch {
      if (token !== current.current) return;
      setRoot(r => r && update(r, node.key, n => ({ ...n, loading: false, error: true })));
    }
  };

  // The latest start wins: a slow load from an earlier pick must not replace it.
  const current = useRef(0);
  const [opened, setOpened] = useState<string | null>(null);

  /** Open the gene along its furthest record, in validation_status order. */
  const start = async (rv: string) => {
    const token = ++current.current;
    const gene = genes.find(g => g.rv_id === rv);
    const node: MapNode = { key: `gene:${rv}`, kind: "gene", id: rv, label: gene?.gene_name ?? rv, sub: gene?.product ?? rv };
    const path = new Set([entityKey(node)]);
    setRoot({ ...node, loading: true });
    setOpened(null);
    setZoom(1);
    setFocusedKey(node.key);
    setStartingKey(null);
    setMissing(false);
    canvas.current?.scrollTo(0, 0);
    try {
      const groups = (await neighbours("gene", rv, resolveName)).map(i => keyed(i, node.key, path));
      const find = (label: string) => groups.find(g => g.label === label);
      let deepest = node.key;
      let note = "No drug, compound, ChEMBL target or screen reaches this protein itself, so nothing is opened. Dashed links, such as an orthologue's, never choose the path.";
      // Only a drug a source says acts on the protein picks the path; resistance
      // and complex links are drawn but never chosen. Drugs arrive phase-first.
      const drugs = find("Drugs");
      const counted = drugs?.children?.filter(d => !d.weak) ?? [];
      // Every drug tied at the top phase opens: inhA's isoniazid and ethionamide
      // are both approved, and choosing one would be an order this map invented.
      const tops = counted.filter(d => (d.phase ?? -1) === (counted[0]?.phase ?? -1));
      if (drugs && tops.length) {
        const loaded = await Promise.all(tops.map(async top => {
          const drugPath = new Set([...path, entityKey(top)]);
          const items = (await neighbours("drug", top.id, resolveName)).map(i => keyed(i, top.key, drugPath));
          const trials = items.find(g => g.label === "Trials");
          const leaf = trials?.children?.length ? trials : items.find(g => g.label === "Genes");
          if (leaf) leaf.open = true;
          return { top, items, leaf };
        }));
        drugs.open = true;
        drugs.children = drugs.children!.map(d => {
          const hit = loaded.find(l => l.top === d);
          return hit ? { ...d, open: true, children: hit.items } : d;
        });
        deepest = loaded[0].leaf?.key ?? drugs.key;
        const names = tops.map(t => t.label);
        const list = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0];
        note = `Opened along ${list}, ${tops[0].sub ?? "no TB phase recorded"}: the furthest record on this protein${names.length > 1 ? ", tied" : ""}.`;
      } else {
        // A group made only of dashed links (an orthologue target, a complex's
        // screen) is not a record on this protein, so it does not open.
        const next = ["Compounds", "ChEMBL targets", "Screens"].map(find).find(g => g?.children?.some(c => !c.weak));
        if (next) {
          next.open = true;
          deepest = next.key;
          note = `No drug acts on this protein; opened ${next.label}, the furthest record on it.`;
        }
      }
      if (token !== current.current) return;
      setRoot({ ...node, open: true, children: groups });
      setOpened(note);
      setStartingKey(deepest);
      setFocusedKey(deepest);
      reveal(deepest);
    } catch {
      if (token === current.current) setRoot({ ...node, error: true });
    }
  };
  // Start only when the URL names a different gene: coming back to the map, or
  // Back to the same root, keeps the walk as it was.
  const started = useRef<string | null>(null);
  useEffect(() => {
    if (!rootGene) {
      ++current.current;
      started.current = null;
      setRoot(null);
      setOpened(null);
      setStartingKey(null);
      setFocusedKey(null);
      return;
    }
    if (!genes.length || rootGene === started.current) return;
    started.current = rootGene;
    void start(rootGene);
  }, [rootGene, genes.length]);

  const submit = () => {
    const rv = byName.get(query.trim().toLowerCase());
    if (rv) { onPick(rv); setQuery(""); }
    else setMissing(true);
  };

  const { placed, links, width, height } = useMemo(() => (root ? layout(root) : { placed: [], links: [], width: 0, height: 0 }), [root]);

  const trail = placed.filter(p => focusedKey === p.node.key || focusedKey?.startsWith(`${p.node.key}/`)).sort((a, b) => a.x - b.x);
  const changeZoom = (value: number) => {
    const el = canvas.current;
    const next = Math.max(0.4, Math.min(1.5, Math.round(value * 100) / 100));
    const x = el ? (el.scrollLeft + el.clientWidth / 2 - 24) / zoom : 0;
    const y = el ? (el.scrollTop + el.clientHeight / 2 - 24) / zoom : 0;
    setZoom(next);
    requestAnimationFrame(() => el?.scrollTo({ left: x * next + 24 - el.clientWidth / 2, top: y * next + 24 - el.clientHeight / 2 }));
  };
  const fit = () => {
    const el = canvas.current;
    if (!el) return;
    setZoom(Math.max(0.4, Math.min(1, (el.clientWidth - 48) / width, (el.clientHeight - 48) / height)));
    requestAnimationFrame(() => el.scrollTo(0, 0));
  };
  const returnToStart = () => {
    if (!startingKey) return;
    // Restore the initial path's visibility without discarding the rest of the walk.
    setRoot(r => {
      if (!r) return r;
      const reopen = (n: MapNode): MapNode => startingKey === n.key || startingKey.startsWith(`${n.key}/`)
        ? { ...n, open: true, children: n.children?.map(reopen) } : n;
      return reopen(r);
    });
    setZoom(1);
    setFocusedKey(startingKey);
    reveal(startingKey);
  };
  const pickExample = (name: string) => {
    const rv = byName.get(name.toLowerCase());
    if (rv) { onPick(rv); setQuery(""); setMissing(false); }
  };

  return (
    <div className="body map-body">
      <FilterRail label="Map · search and guide">
        <div className="rail-heading">
          <InterfaceIcon name="map" />
          <h2>Relationship map</h2>
        </div>
        <form className="group" onSubmit={event => { event.preventDefault(); submit(); }}>
          <label className="lab" htmlFor="map-start">Start from a gene</label>
          <div className="map-search-field">
            <input id="map-start" className="search" value={query} placeholder="Gene name or Rv ID" list="map-genes"
              aria-invalid={missing || undefined} aria-describedby={missing ? "map-search-error" : undefined}
              onChange={event => { setQuery(event.target.value); setMissing(false); }} />
            <button type="submit" aria-label="Explore gene" disabled={!query.trim() || !genes.length} title="Explore gene"><InterfaceIcon name="search" /></button>
          </div>
          <datalist id="map-genes">{genes.map(g => <option key={g.rv_id} value={g.gene_name ?? g.rv_id}>{g.rv_id}</option>)}</datalist>
          {missing && <p className="note map-search-error" id="map-search-error" role="status">No gene found. Try a gene name such as inhA or an Rv ID.</p>}
        </form>
        <div className="group">
          <p className="lab">Quick starts</p>
          <div className="map-starts">
            {START.map(name => <button type="button" className="chip" key={name} disabled={!byName.has(name.toLowerCase())} aria-pressed={root?.id === byName.get(name.toLowerCase())} onClick={() => pickExample(name)}>{name}</button>)}
          </div>
        </div>
        {root && <div className="group map-origin">
          <span className="lab">Starting gene</span>
          <button type="button" onClick={() => focusNode(root.key)} title="Locate the starting gene"><strong>{root.label}</strong><span>{root.id}</span><span aria-hidden="true">⌖</span></button>
          <p>{root.sub}</p>
          <button className="map-text-button" type="button" onClick={() => onOpen("gene", root.id)}>Open gene details ↗</button>
        </div>}
        {opened && <div className="group map-opened" role="status"><span className="lab">Why this path?</span><p>{opened}</p><button type="button" className="map-text-button" onClick={returnToStart}>Return to starting path →</button></div>}
        <div className="group map-legend">
          <p className="lab">Reading the map</p>
          <p><svg width="28" height="8" aria-hidden="true"><path d="M0 4h28" className="map-link" /></svg>A source joins the two</p>
          <p><svg width="28" height="8" aria-hidden="true"><path d="M0 4h28" className="map-link weak" /></svg>Shown, not counted</p>
          <p>Each card names its relationship. Expand a card to follow it; ↗ opens its details. A group with 0 means no record in the atlas.</p>
        </div>
      </FilterRail>
      <main className="col canvascol map-canvas" aria-label="Relationship map">
        <div className="map-toolbar">
          <div className="map-heading"><InterfaceIcon name="map" /><div><h2>{root ? root.label : "Relationship map"}</h2><span>{root ? `${root.id} · relationship map` : "Genes, drugs, compounds, screens and trials"}</span></div></div>
          {root && <div className="map-tools" aria-label="Map controls">
            <button type="button" onClick={returnToStart} disabled={!startingKey} title="Return to the evidence path opened at the start">Starting path</button>
            <button type="button" onClick={fit} title="Fit the map in view (minimum 40%)">Fit map</button>
            <div className="map-zoom" role="group" aria-label="Zoom">
              <button type="button" aria-label="Zoom out" disabled={zoom <= 0.4} onClick={() => changeZoom(zoom - 0.1)}>−</button>
              <button type="button" className="map-zoom-value" aria-label="Reset zoom to 100%" onClick={() => changeZoom(1)}>{Math.round(zoom * 100)}%</button>
              <button type="button" aria-label="Zoom in" disabled={zoom >= 1.5} onClick={() => changeZoom(zoom + 0.1)}>+</button>
            </div>
          </div>}
        </div>
        {root && <nav className="map-breadcrumb" aria-label="Current map path">
          <span className="map-path-label">Following</span>
          {trail.map(({ node }, i) => <span key={node.key}>{i > 0 && <span className="map-crumb-separator" aria-hidden="true">/</span>}<button type="button" aria-current={node.key === focusedKey ? "location" : undefined} onClick={() => focusNode(node.key)} title={node.label}>{node.label}</button></span>)}
        </nav>}
        <div className="map-viewport" ref={canvas} tabIndex={0} role="region" aria-label="Map canvas. Scroll to navigate or drag the background." aria-busy={root?.loading || false}
          onPointerDown={event => {
            if (event.button !== 0 || event.pointerType === "touch" || (event.target as HTMLElement).closest("button, a")) return;
            const el = event.currentTarget;
            drag.current = { x: event.clientX, y: event.clientY, left: el.scrollLeft, top: el.scrollTop };
            el.setPointerCapture(event.pointerId);
            el.classList.add("is-dragging");
          }}
          onPointerMove={event => {
            if (!drag.current) return;
            event.currentTarget.scrollLeft = drag.current.left - (event.clientX - drag.current.x);
            event.currentTarget.scrollTop = drag.current.top - (event.clientY - drag.current.y);
          }}
          onPointerUp={event => { drag.current = null; event.currentTarget.classList.remove("is-dragging"); if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
          onLostPointerCapture={event => { drag.current = null; event.currentTarget.classList.remove("is-dragging"); }}>
          {!root ? <div className="map-empty">
            <div className="map-empty-icon"><InterfaceIcon name="map" /></div>
            <h2>Choose a gene</h2>
            <p>Search by gene name or Rv ID in the sidebar, or select a gene below.</p>
            <div className="map-examples">{START.slice(0, 3).map(name => <button type="button" key={name} disabled={!byName.has(name.toLowerCase())} onClick={() => pickExample(name)}><span><strong>{name}</strong><span>{byName.get(name.toLowerCase()) ?? "Gene"}</span></span><span aria-hidden="true">→</span></button>)}</div>
          </div> : root.loading ? <div className="map-message" role="status"><span className="map-loading-dot" /><h3>Loading map for {root.label}</h3><p>Loading connected records…</p></div>
          : root.error && !root.children ? <div className="map-message" role="alert"><h3>Couldn’t load this map</h3><p>The records for {root.label} could not be retrieved. Try again.</p><button className="iconbtn" type="button" onClick={() => void start(root.id)}>Retry map</button></div>
          : <div className="map-space" style={{ width: width * zoom + 48, height: height * zoom + 48 }}>
            <div className="map-plane" style={{ width, height, transform: `scale(${zoom})` }}>
              <svg width={width} height={height} aria-hidden="true">
                {links.map(l => {
                  const bend = (l.x2 - l.x1) / 2;
                  const onPath = focusedKey === l.key || focusedKey?.startsWith(`${l.key}/`);
                  return <path key={l.key} className={`map-link${l.weak ? " weak" : ""}${onPath ? " on-path" : ""}`} d={`M${l.x1} ${l.y1}C${l.x1 + bend} ${l.y1} ${l.x2 - bend} ${l.y2} ${l.x2} ${l.y2}`} />;
                })}
              </svg>
              {placed.map(({ node, x, y, path }) => {
                const empty = node.kind === "group" && !node.children?.length;
                const expandable = !node.cycle && (ENTITY.has(node.kind) || node.kind === "more" || (node.kind === "group" && !empty));
                const opens = (["gene", "drug", "compound", "screen", "trial"] as Kind[]).includes(node.kind);
                const onPath = focusedKey === node.key || focusedKey?.startsWith(`${node.key}/`);
                return (
                  <div key={node.key} className={`map-node${node.weak ? " weak" : ""}${empty ? " absent" : ""}${node.cycle ? " cycle" : ""}${onPath ? " on-path" : ""}${focusedKey === node.key ? " is-focused" : ""}`}
                    data-kind={node.kind} data-key={node.key} data-parent={node.key.slice(0, node.key.lastIndexOf("/"))} style={{ left: x, top: y - 27, width: NODE_W }}>
                    <button type="button" className="map-node-main" disabled={!expandable || node.loading} aria-expanded={expandable && node.kind !== "more" ? !!node.open : undefined}
                      aria-label={`${node.label}${node.kind === "group" ? `, ${node.children?.length ?? 0} records` : ""}${node.error ? ", could not load. Click to retry" : ""}`}
                      title={[node.label, node.edge, node.sub, node.basis, node.cycle ? "Already on this path" : null].filter(Boolean).join("\n")} onClick={() => void expand(node, path)}>
                      {node.edge && <span className="map-edge">{node.edge}</span>}
                      <span className="map-title">
                        {node.kind !== "group" && node.kind !== "more" && <span className="map-dot" aria-hidden="true" />}
                        <span className="map-node-label">{node.label}</span>
                        {node.kind === "group" && <span className="map-count">{(node.children?.length ?? 0).toLocaleString()}</span>}
                        {expandable && !node.loading && <span className="map-chevron" aria-hidden="true">{node.open ? "−" : "+"}</span>}
                      </span>
                      {node.loading ? <span className="map-state" role="status">Loading connections…</span> : node.error ? <span className="map-state map-node-error" role="status">Couldn’t load · click to retry</span> : node.kind === "group" ? <span className="map-sub">{empty ? "No records in the atlas" : node.open ? `${Math.min(node.shown ?? PAGE, node.children?.length ?? 0)} shown · click to collapse` : "Click to explore"}</span> : node.kind !== "more" && <span className="map-sub">{KIND_LABEL[node.kind]}{node.sub ? ` · ${node.sub}` : ""}{node.cycle ? " · on this path" : ""}</span>}
                    </button>
                    {opens && <button type="button" className="map-open" title={`Open this ${KIND_LABEL[node.kind].toLowerCase()} in its view`} aria-label={`Open ${node.label}`} onClick={() => onOpen(node.kind as MapOpenKind, node.id)}>↗</button>}
                    {node.kind === "structure" && <a className="map-open" href={`https://www.rcsb.org/structure/${node.id}`} target="_blank" rel="noreferrer" aria-label={`${node.id} at RCSB PDB`}>↗</a>}
                  </div>
                );
              })}
            </div>
          </div>}
        </div>
        {root && !root.loading && !root.error && <div className="map-footer"><span><strong>{placed.filter(p => p.node.kind !== "group" && p.node.kind !== "more").length}</strong> objects on map</span><span>Scroll or drag to move · + to expand · ↗ for details</span></div>}
      </main>
    </div>
  );
}
