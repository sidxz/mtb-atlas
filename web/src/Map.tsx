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
}

type Item = Omit<MapNode, "key">;

const ENTITY = new Set<Kind>(["gene", "drug", "compound", "screen", "pfam", "go", "pathway", "condition"]);
const PAGE = 12;
const COL = 270;
const ROW = 62;
const NODE_W = 220;

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
    edge: [...d.links].map(l => LINK_LABEL[l]).join(" · "),
    weak: ![...d.links].some(l => COUNTED.includes(l)),
  })).sort((a, b) => Number(a.weak) - Number(b.weak));
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
      y = (ys[0] + ys[ys.length - 1]) / 2;
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

export function AtlasMap({ all, seed, onOpen }: {
  all: TargetSummary[];
  /** A new object re-seeds the map. */
  seed: { rv: string } | null;
  onOpen: (kind: MapOpenKind, id: string) => void;
}) {
  const genes = useMemo(() => all.filter(g => g.feature === "CDS"), [all]);
  const byName = useMemo(() => new Map(genes.flatMap(g => [[g.rv_id.toLowerCase(), g.rv_id], ...(g.gene_name ? [[g.gene_name.toLowerCase(), g.rv_id] as const] : [])])), [genes]);
  const resolveName = useMemo(() => new Map(genes.filter(g => g.gene_name).map(g => [g.gene_name!, g.rv_id])), [genes]);
  const [root, setRoot] = useState<MapNode | null>(null);
  const [query, setQuery] = useState("");
  const [missing, setMissing] = useState(false);
  const canvas = useRef<HTMLDivElement>(null);

  // A branch opens to the right, often past the edge: bring its first child into view.
  const reveal = (key: string) => requestAnimationFrame(() =>
    canvas.current?.querySelector(`[data-parent="${CSS.escape(key)}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" }));

  const expand = async (node: MapNode, path: Set<string>) => {
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
      return;
    }
    setRoot(r => r && update(r, node.key, n => ({ ...n, loading: true, error: false })));
    try {
      const items = await neighbours(node.kind as EntityKind, node.id, resolveName);
      setRoot(r => r && update(r, node.key, n => ({ ...n, loading: false, open: true, children: items.map(i => keyed(i, n.key, path)) })));
      reveal(node.key);
    } catch {
      setRoot(r => r && update(r, node.key, n => ({ ...n, loading: false, error: true })));
    }
  };

  const start = (rv: string) => {
    const gene = genes.find(g => g.rv_id === rv);
    const node: MapNode = { key: `gene:${rv}`, kind: "gene", id: rv, label: gene?.gene_name ?? rv, sub: gene?.product ?? rv };
    setRoot(node);
    setMissing(false);
    canvas.current?.scrollTo(0, 0);
    void expand(node, new Set([entityKey(node)]));
  };
  // `start` closes over state setters only, so the seed is all the effect needs.
  useEffect(() => { if (seed && genes.length) start(seed.rv); }, [seed, genes.length]);

  const submit = () => {
    const rv = byName.get(query.trim().toLowerCase());
    if (rv) start(rv);
    else setMissing(true);
  };

  const { placed, links, width, height } = useMemo(() => (root ? layout(root) : { placed: [], links: [], width: 0, height: 0 }), [root]);

  return (
    <div className="body map-body">
      <FilterRail label="Map">
        <div className="rail-heading">
          <InterfaceIcon name="map" />
          <h2>Map</h2>
        </div>
        <form className="group" onSubmit={event => { event.preventDefault(); submit(); }}>
          <label className="lab" htmlFor="map-start">Start from a gene</label>
          <input id="map-start" className="search" value={query} placeholder="Gene name or Rv ID" list="map-genes"
            onChange={event => { setQuery(event.target.value); setMissing(false); }} />
          <datalist id="map-genes">{genes.filter(g => g.gene_name).map(g => <option key={g.rv_id} value={g.gene_name!}>{g.rv_id}</option>)}</datalist>
          {missing && <p className="note" role="status">No CDS locus by that name.</p>}
        </form>
        <div className="group map-starts">
          {START.map(name => <button type="button" className="chip" key={name} onClick={() => { const rv = byName.get(name.toLowerCase()); if (rv) start(rv); }}>{name}</button>)}
        </div>
        <div className="group map-legend">
          <p className="lab">Reading the map</p>
          <p><svg width="36" height="8" aria-hidden="true"><path d="M0 4h36" className="map-link" /></svg> a source joins the two</p>
          <p><svg width="36" height="8" aria-hidden="true"><path d="M0 4h36" className="map-link weak" /></svg> shown, not counted</p>
          <p>Click a node to expand it. A group with 0 is an absent record, not a gap. The claim on each line is printed on the node it leads to.</p>
        </div>
      </FilterRail>
      <main className="col canvascol map-canvas" ref={canvas} aria-label="Relationship map">
        {!root ? (
          <p className="map-empty">Pick a gene to start. Every line on the map is a record in the atlas, and each node expands into what its own record joins it to.</p>
        ) : (
          <div className="map-plane" style={{ width, height }}>
            <svg width={width} height={height} aria-hidden="true">
              {links.map(l => {
                const bend = (l.x2 - l.x1) / 2;
                return <path key={l.key} className={`map-link${l.weak ? " weak" : ""}`} d={`M${l.x1} ${l.y1}C${l.x1 + bend} ${l.y1} ${l.x2 - bend} ${l.y2} ${l.x2} ${l.y2}`} />;
              })}
            </svg>
            {placed.map(({ node, x, y, path }) => {
              const empty = node.kind === "group" && !node.children?.length;
              const expandable = !node.cycle && (ENTITY.has(node.kind) || node.kind === "more" || (node.kind === "group" && !empty));
              const opens = (["gene", "drug", "compound", "screen", "trial"] as Kind[]).includes(node.kind);
              return (
                <div key={node.key} className={`map-node${node.weak ? " weak" : ""}${empty ? " absent" : ""}${node.cycle ? " cycle" : ""}`}
                  data-kind={node.kind} data-parent={node.key.slice(0, node.key.lastIndexOf("/"))} style={{ left: x, top: y - ROW / 2 + 4, width: NODE_W }}>
                  <button type="button" className="map-node-main" disabled={!expandable} aria-expanded={expandable && node.kind !== "more" ? !!node.open : undefined}
                    title={node.basis ?? (node.cycle ? "Already on this path" : undefined)} onClick={() => void expand(node, path)}>
                    {node.edge && <span className="map-edge" title={node.edge}>{node.edge}</span>}
                    <span className="map-title">
                      {node.kind !== "group" && node.kind !== "more" && <span className="map-dot" aria-hidden="true" />}
                      {node.kind === "group" ? <>{node.label} <span className="map-count">{(node.children?.length ?? 0).toLocaleString()}</span></> : node.label}
                      {node.loading && <span className="map-state"> loading…</span>}
                      {node.error && <span className="map-state"> could not load, click to retry</span>}
                    </span>
                    {node.kind !== "group" && node.kind !== "more" && (
                      <span className="map-sub">{KIND_LABEL[node.kind]}{node.sub ? ` · ${node.sub}` : ""}{node.cycle ? " · on this path" : ""}</span>
                    )}
                  </button>
                  {opens && <button type="button" className="map-open" title={`Open this ${KIND_LABEL[node.kind].toLowerCase()} in its view`} aria-label={`Open ${node.label}`} onClick={() => onOpen(node.kind as MapOpenKind, node.id)}>↗</button>}
                  {node.kind === "structure" && <a className="map-open" href={`https://www.rcsb.org/structure/${node.id}`} target="_blank" rel="noreferrer" aria-label={`${node.id} at RCSB PDB`}>↗</a>}
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
