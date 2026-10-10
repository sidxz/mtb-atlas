/**
 * The whole chromosome on one canvas: 4,031 genes at their real coordinates.
 *
 * Four concentric rings, outermost first: the gene itself coloured by whichever
 * evidence you are asking about, then structure, chemical matter and
 * resistance as presence rings. Genes filtered out are drawn faint rather than
 * removed, so a filter reads as a pattern on the genome instead of an
 * unrelated shorter list.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { TargetSummary } from "./api";

export type ColourBy =
  | "category"
  | "essentiality"
  | "vulnerability"
  | "structure"
  | "assay"
  | "chemistry"
  | "clinical"
  | "resistance";

/** NC_000962.3, M. tuberculosis H37Rv. */
export const GENOME_LENGTH = 4_411_532;

export const CATEGORIES = [
  "cell wall and cell processes",
  "intermediary metabolism and respiration",
  "lipid metabolism",
  "information pathways",
  "regulatory proteins",
  "virulence, detoxification, adaptation",
  "PE/PPE",
  "insertion seqs and phages",
  "conserved hypotheticals",
  "stable RNAs",
  "unknown",
];
const CATEGORY_COLOURS = [
  "#c21f68", "#1f4e9c", "#1f8a7a", "#8a5cc2", "#c08a2e", "#b8452e",
  "#2e7fb8", "#6b7280", "#9aa3b8", "#4a6ea8", "#868ea3",
];

const token = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function colourOf(gene: TargetSummary, by: ColourBy): string {
  switch (by) {
    case "essentiality":
      return gene.essentiality ? token(`--ess-${gene.essentiality}`) : token("--ess-none");
    case "vulnerability": {
      // Negative scale: -12 is highly vulnerable, 0 is not. Only genes with the
      // study's own `certain` flag get a colour; the rest stay grey rather than
      // implying a measurement the paper does not stand behind.
      const vi = gene.vulnerability_index;
      if (vi === null || !gene.vulnerability_certain) return token("--ess-none");
      if (vi <= -9) return token("--accent");
      if (vi <= -6) return token("--ess-ESD");
      if (vi <= -3) return token("--ess-GD");
      return token("--ess-GA");
    }
    case "structure":
      if (gene.n_pdb >= 5) return token("--accent");
      if (gene.n_pdb > 0) return token("--ess-NE");
      return gene.has_predicted ? token("--ess-none") : token("--line");
    case "assay":
      // Whether the protein can be measured at all, which is a different
      // question from whether anyone has hit it.
      if (!gene.n_protein_assays) return token("--ess-none");
      return gene.n_protein_assays >= 5 ? token("--accent") : token("--ess-NE");
    case "chemistry":
      if (!gene.has_ligands) return token("--ess-none");
      return gene.chembl_evidence === "direct" ? token("--accent") : token("--counter");
    case "resistance":
      if (gene.n_variants_associated >= 5) return token("--accent");
      if (gene.n_variants_associated > 0) return token("--warn");
      return gene.in_who_catalogue ? token("--ess-NE") : token("--ess-none");
    case "clinical":
      // Best phase *for TB* among drugs a source says act on this gene's own
      // protein. Complex membership alone gets the faintest mark, not a colour.
      if (gene.best_drug_phase != null && gene.best_drug_phase >= 4) return token("--accent");
      if (gene.best_drug_phase != null && gene.best_drug_phase >= 2) return token("--ess-ESD");
      if (gene.best_drug_phase != null) return token("--counter");
      return gene.n_complex_drugs ? token("--line-strong") : token("--ess-none");
    case "category": {
      const index = CATEGORIES.indexOf(gene.category ?? "");
      return index < 0 ? token("--ess-none") : CATEGORY_COLOURS[index];
    }
  }
}

/**
 * The rings are the discovery pipeline, innermost first.
 *
 * Reading outward is reading a target's progress: what the gene is, whether
 * the organism can lose it, how much it has to lose, whether you can see the
 * protein, whether you can measure it, whether anyone has hit it, whether it
 * reached the clinic, and whether resistance came back from patients. The
 * order is fixed so the picture means the same thing every time, and the
 * control beside it is the legend — picking an axis brings that ring forward
 * rather than recolouring the whole genome.
 *
 * A gene with nothing on a ring draws nothing there, so the funnel is the
 * absence: 489 essential, 885 with a structure, 103 with an assay, 13 with a
 * drug. `on` is "does this gene reach this stage at all"; `colourOf` grades it.
 */
export const RINGS: { key: ColourBy; label: string; on: (g: TargetSummary) => boolean }[] = [
  { key: "category", label: "What it is", on: (g) => Boolean(g.category) },
  { key: "essentiality", label: "Essential", on: (g) => Boolean(g.essentiality) },
  {
    key: "vulnerability",
    label: "Vulnerable",
    on: (g) => g.vulnerability_index != null && g.vulnerability_certain,
  },
  { key: "structure", label: "Structure", on: (g) => g.n_pdb > 0 || g.has_predicted },
  { key: "assay", label: "Assay", on: (g) => g.n_protein_assays > 0 },
  { key: "chemistry", label: "Chemical matter", on: (g) => g.has_ligands },
  {
    key: "clinical",
    // Loose `!= null`, which is false for undefined as well as null. An older
    // API that does not serve this field at all would otherwise light the ring
    // for all 4,173 genes -- `undefined !== null` is true. Caught exactly that
    // way: a stale server made every structural-gap gene look clinical.
    label: "Clinical",
    on: (g) => g.best_drug_phase != null || (g.n_complex_drugs ?? 0) > 0,
  },
  {
    key: "resistance",
    label: "Resistance",
    on: (g) => g.in_who_catalogue || g.n_variants_associated > 0,
  },
];

// Above this a highlight is not a highlight. Glowing 3,000 genes costs the
// frames and says nothing a plain colour would not.
const GLOW_LIMIT = 1200;

const angleOf = (g: TargetSummary) =>
  (((g.start + g.stop) / 2 / GENOME_LENGTH) * Math.PI * 2) - Math.PI / 2;

/** Where the rings sit, shared by the base canvas and the hover overlay.
 *
 * The outer ring has to leave room for the Mb labels, which sit beyond it and
 * are centred: at 3 and 9 o'clock half the text runs outward, so a ring any
 * further out puts the label past the canvas edge.
 */
const layout = (size: number) => {
  const inner = size * 0.185;
  const outer = size * 0.42;
  return { inner, outer, pitch: (outer - inner) / (RINGS.length - 1) };
};

const phase = (n: number) => (n >= 4 ? "approved" : n < 1 ? "early phase 1" : `phase ${n}`);

/**
 * What the rings say about one gene, in ring order.
 *
 * `null` is a stage the gene does not reach, and the tooltip shows it as a
 * dash rather than dropping the row — the gaps are the point, and they are
 * the same gaps the ring draws nothing for.
 */
export function pipelineOf(g: TargetSummary): { label: string; value: string | null }[] {
  return [
    { label: "What it is", value: g.category ?? null },
    { label: "Essential", value: g.essentiality_label ?? g.essentiality ?? null },
    {
      label: "Vulnerable",
      value:
        g.vulnerability_index != null && g.vulnerability_certain
          ? g.vulnerability_index.toFixed(1)
          : null,
    },
    {
      label: "Structure",
      value: g.n_pdb > 0 ? `${g.n_pdb} in the PDB` : g.has_predicted ? "predicted only" : null,
    },
    {
      label: "Protein assay",
      value: g.n_protein_assays ? `${g.n_protein_assays} published` : null,
    },
    {
      label: "Chemical matter",
      value: g.n_compounds
        ? `${g.n_compounds} compound${g.n_compounds === 1 ? "" : "s"}` +
          (g.chembl_evidence === "orthologue" ? ", orthologue only" : "")
        : null,
    },
    {
      label: "Clinical",
      value:
        g.best_drug_phase != null
          ? phase(g.best_drug_phase)
          : (g.n_complex_drugs ?? 0) > 0
            ? "complex member only"
            : null,
    },
    {
      label: "Resistance",
      value: g.n_variants_associated
        ? `${g.n_variants_associated} graded variant${g.n_variants_associated === 1 ? "" : "s"}`
        : g.in_who_catalogue
          ? "in the catalogue, none graded"
          : null,
    },
  ];
}

interface Props {
  genes: TargetSummary[];
  matching: Set<string>;
  colourBy: ColourBy;
  selected: string | null;
  onSelect: (rvId: string) => void;
  theme: string;
  /** The overlay draws the same rings far larger; the rail is capped small. */
  maxSize?: number;
}

export function GenomeCanvas({
  genes,
  matching,
  colourBy,
  selected,
  onSelect,
  theme,
  maxSize = 680,
}: Props) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const trace = useRef<HTMLCanvasElement | null>(null);
  const wrap = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState(520);
  const [hover, setHover] = useState<{ gene: TargetSummary; x: number; y: number } | null>(null);

  useEffect(() => {
    const element = wrap.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const box = entry.contentRect;
      // The floor is low enough for the rail, where the ring sits beside the
      // colour control it is the legend for. Everything below scales off
      // `size`, so the only thing that breaks small is the Mb axis text.
      setSize(Math.max(180, Math.min(box.width - 16, box.height - 16, maxSize)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [maxSize]);

  const nearest = useCallback(
    (clientX: number, clientY: number): TargetSummary | null => {
      const element = canvas.current;
      if (!element || !genes.length) return null;
      const rect = element.getBoundingClientRect();
      const x = ((clientX - rect.left) / rect.width) * size - size / 2;
      const y = ((clientY - rect.top) / rect.height) * size - size / 2;
      const radius = Math.hypot(x, y);
      if (radius < size * 0.165 || radius > size * 0.45) return null;
      let angle = Math.atan2(y, x) + Math.PI / 2;
      if (angle < 0) angle += Math.PI * 2;
      const bp = (angle / (Math.PI * 2)) * GENOME_LENGTH;
      let best: TargetSummary | null = null;
      let bestDistance = Infinity;
      for (const gene of genes) {
        const distance = Math.abs((gene.start + gene.stop) / 2 - bp);
        if (distance < bestDistance) {
          bestDistance = distance;
          best = gene;
        }
      }
      return bestDistance < (GENOME_LENGTH / genes.length) * 2 ? best : null;
    },
    [genes, size],
  );

  useEffect(() => {
    const element = canvas.current;
    if (!element || !genes.length) return;
    const context = element.getContext("2d");
    if (!context) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    element.width = size * dpr;
    element.height = size * dpr;
    element.style.width = `${size}px`;
    element.style.height = `${size}px`;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, size, size);

    const cx = size / 2;
    const cy = size / 2;
    // The pipeline laid out radially: innermost is what the gene is,
    // outermost is resistance seen in patients. Evenly pitched so the order
    // reads as a sequence rather than a hierarchy of importance.
    const { inner, outer, pitch } = layout(size);
    const geometry = RINGS.map((ring, index) => ({
      ...ring,
      r: inner + pitch * index,
      // The focused ring is thicker as well as brighter, because at rail size
      // alpha alone is not enough to pick one of eight out.
      h: pitch * (ring.key === colourBy ? 0.95 : 0.6),
    }));

    context.strokeStyle = token("--line");
    context.lineWidth = 1;
    for (const ring of geometry) {
      context.beginPath();
      context.arc(cx, cy, ring.r, 0, Math.PI * 2);
      context.stroke();
    }

    const filtered = matching.size !== genes.length;
    const glowing = filtered && matching.size <= GLOW_LIMIT;
    const width = Math.max(1, ((Math.PI * 2 * outer) / genes.length) * 0.95);
    const radial = (angle: number, r0: number, r1: number) => {
      context.beginPath();
      context.moveTo(cx + Math.cos(angle) * r0, cy + Math.sin(angle) * r0);
      context.lineTo(cx + Math.cos(angle) * r1, cy + Math.sin(angle) * r1);
      context.stroke();
    };

    /** One gene's marks across every ring it reaches. */
    const draw = (gene: TargetSummary, dim: boolean) => {
      const angle = angleOf(gene);
      for (const ring of geometry) {
        if (!ring.on(gene)) continue;
        const focused = ring.key === colourBy;
        context.globalAlpha = dim ? 0.08 : focused ? 1 : 0.45;
        context.lineWidth = dim ? width : width * (focused ? 1.3 : 1);
        context.strokeStyle = colourOf(gene, ring.key);
        if (!dim && glowing) context.shadowColor = context.strokeStyle;
        radial(angle, ring.r - ring.h / 2, ring.r + ring.h / 2);
      }
    };

    // Two passes so the matches are painted over the background rather than
    // under it, and so the blur is configured once instead of per gene.
    context.shadowBlur = 0;
    if (filtered) for (const gene of genes) if (!matching.has(gene.rv_id)) draw(gene, true);
    if (glowing) context.shadowBlur = Math.max(3, size * 0.014);
    for (const gene of genes) if (!filtered || matching.has(gene.rv_id)) draw(gene, false);
    context.shadowBlur = 0;
    context.globalAlpha = 1;

    // Below this the Mb labels render at under 6px, which is noise rather than
    // an axis. The ticks stay; only the text goes.
    const roomForAxis = size >= 320;
    context.font = `500 ${Math.round(size * 0.019)}px ${token("--mono")}`;
    context.fillStyle = token("--fg-faint");
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.strokeStyle = token("--line-strong");
    context.lineWidth = 1;
    for (let bp = 0; bp < GENOME_LENGTH; bp += 500_000) {
      const angle = (bp / GENOME_LENGTH) * Math.PI * 2 - Math.PI / 2;
      radial(angle, outer + pitch * 0.5, outer + pitch * 0.5 + size * 0.012);
      if (!roomForAxis) continue;
      const labelRadius = outer + pitch * 0.5 + size * 0.026;
      context.fillText(
        `${bp / 1e6} Mb`,
        cx + Math.cos(angle) * labelRadius,
        cy + Math.sin(angle) * labelRadius,
      );
    }

    const chosen = genes.find((g) => g.rv_id === selected);
    if (chosen) {
      context.strokeStyle = token("--fg");
      context.lineWidth = 2;
      radial(angleOf(chosen), inner - pitch * 0.5, outer + pitch * 0.5 + size * 0.015);
    }

    context.textAlign = "center";
    context.fillStyle = token("--fg");
    // Floored: the centre readout is the one thing that must stay legible when
    // the ring is small, since it carries the live match count.
    context.font = `600 ${Math.max(11, Math.round(size * 0.052))}px ${token("--mono")}`;
    context.fillText(
      chosen ? chosen.rv_id : matching.size.toLocaleString("en-US"),
      cx,
      cy - size * 0.012,
    );
    context.fillStyle = token("--fg-dim");
    context.font = `400 ${Math.max(9, Math.round(size * 0.025))}px ${token("--sans")}`;
    context.fillText(
      chosen ? (chosen.gene_name ?? "unnamed") : filtered ? "genes match" : "genes",
      cx,
      cy + size * 0.032,
    );
  }, [genes, matching, colourBy, selected, size, theme]);

  /** The hover trace, on its own canvas.
   *
   * Redrawing the base means 4,173 genes across eight rings, which is tens of
   * thousands of strokes and nowhere near a pointer-move budget. This layer
   * holds one spoke and one label, so it can be cleared and redrawn freely.
   */
  useEffect(() => {
    const element = trace.current;
    if (!element) return;
    const context = element.getContext("2d");
    if (!context) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    element.width = size * dpr;
    element.height = size * dpr;
    element.style.width = `${size}px`;
    element.style.height = `${size}px`;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, size, size);

    const gene = hover?.gene;
    if (!gene) return;
    const { inner, outer, pitch } = layout(size);
    const cx = size / 2;
    const cy = size / 2;
    const angle = angleOf(gene);
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const at = (r: number) => [cx + cos * r, cy + sin * r] as const;

    // Core outward: the spoke starts clear of the centre readout and runs past
    // the last ring, so you can follow one gene through every stage at once.
    const tail = outer + pitch * 0.5 + size * 0.03;
    context.strokeStyle = token("--fg");
    context.globalAlpha = 0.5;
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(...at(size * 0.135));
    context.lineTo(...at(tail));
    context.stroke();

    // The gene's own marks, redrawn solid, so the spoke visibly passes through
    // the stages it reaches and skips the ones it does not.
    context.globalAlpha = 1;
    const markWidth = Math.max(2.5, size * 0.006);
    context.lineWidth = markWidth;
    for (const [index, ring] of RINGS.entries()) {
      if (!ring.on(gene)) continue;
      const r = inner + pitch * index;
      const h = pitch * 0.95;
      context.strokeStyle = colourOf(gene, ring.key);
      context.beginPath();
      context.moveTo(...at(r - h / 2));
      context.lineTo(...at(r + h / 2));
      context.stroke();
    }

    const name =
      gene.gene_name && gene.gene_name !== gene.rv_id
        ? `${gene.rv_id} · ${gene.gene_name}`
        : gene.rv_id;
    const fontSize = Math.max(9, Math.round(size * 0.023));
    context.font = `600 ${fontSize}px ${token("--mono")}`;
    const padX = fontSize * 0.5;
    const padY = fontSize * 0.34;
    const boxWidth = context.measureText(name).width + padX * 2;
    const boxHeight = fontSize + padY * 2;
    const [ex, ey] = at(tail + size * 0.022);
    // Centred on the end of the spoke, then pulled back inside the canvas:
    // at 3 and 9 o'clock a long name would otherwise run off the edge.
    const bx = Math.max(1, Math.min(ex - boxWidth / 2, size - boxWidth - 1));
    const by = Math.max(1, Math.min(ey - boxHeight / 2, size - boxHeight - 1));
    context.fillStyle = token("--fg");
    context.beginPath();
    context.roundRect(bx, by, boxWidth, boxHeight, 3);
    context.fill();
    context.fillStyle = token("--bg");
    context.textAlign = "left";
    context.textBaseline = "middle";
    context.fillText(name, bx + padX, by + boxHeight / 2);
  }, [hover, size, theme]);

  const detailed = size >= 320;

  return (
    <div className="canvaswrap" ref={wrap}>
      <canvas
        ref={canvas}
        onPointerMove={(event) => {
          const gene = nearest(event.clientX, event.clientY);
          const rect = canvas.current?.getBoundingClientRect();
          if (!gene || !rect) {
            setHover(null);
            return;
          }
          setHover({ gene, x: event.clientX - rect.left, y: event.clientY - rect.top });
        }}
        onPointerLeave={() => setHover(null)}
        onClick={(event) => {
          const gene = nearest(event.clientX, event.clientY);
          if (gene) onSelect(gene.rv_id);
        }}
        aria-label="Circular map of the H37Rv chromosome; each tick is one gene"
      />
      {/* Purely decorative: the spoke repeats what the tooltip says in words. */}
      <canvas className="tracelayer" ref={trace} aria-hidden="true" />
      {hover && (
        <div
          className={`tooltip${detailed ? " pipeline" : ""}`}
          // Placed on the inward side of the cursor, which is the one side the
          // spoke's end label can never be on: the label sits beyond the last
          // ring, so anything toward the centre is clear of it.
          style={{
            left: (canvas.current?.offsetLeft ?? 0) + hover.x,
            top: (canvas.current?.offsetTop ?? 0) + hover.y,
            transform: `translate(${
              Math.cos(angleOf(hover.gene)) >= 0 ? "calc(-100% - 12px)" : "12px"
            }, ${Math.sin(angleOf(hover.gene)) >= 0 ? "calc(-100% - 12px)" : "12px"})`,
          }}
        >
          <div className="who">
            {hover.gene.rv_id}
            {hover.gene.gene_name && hover.gene.gene_name !== hover.gene.rv_id
              ? ` · ${hover.gene.gene_name}`
              : ""}
          </div>
          {detailed && (
            <>
              {hover.gene.product && <div className="what">{hover.gene.product}</div>}
              {/* The same eight stages the rings draw, in the same order, so
                  the tooltip reads as the spoke it is attached to. */}
              <dl>
                {pipelineOf(hover.gene).map(({ label, value }) => (
                  <div key={label} className={value ? undefined : "absent"}>
                    <dt>{label}</dt>
                    <dd>{value ?? "—"}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </div>
      )}
    </div>
  );
}
