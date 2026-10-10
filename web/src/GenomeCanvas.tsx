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
  | "essentiality"
  | "vulnerability"
  | "structure"
  | "chemistry"
  | "resistance"
  | "clinical"
  | "category";

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
      if (gene.best_drug_phase !== null && gene.best_drug_phase >= 4) return token("--accent");
      if (gene.best_drug_phase !== null && gene.best_drug_phase >= 2) return token("--ess-ESD");
      if (gene.best_drug_phase !== null) return token("--counter");
      return gene.n_complex_drugs > 0 ? token("--line-strong") : token("--ess-none");
    case "category": {
      const index = CATEGORIES.indexOf(gene.category ?? "");
      return index < 0 ? token("--ess-none") : CATEGORY_COLOURS[index];
    }
  }
}

interface Props {
  genes: TargetSummary[];
  matching: Set<string>;
  colourBy: ColourBy;
  selected: string | null;
  onSelect: (rvId: string) => void;
  theme: string;
}

export function GenomeCanvas({ genes, matching, colourBy, selected, onSelect, theme }: Props) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const wrap = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState(520);
  const [hover, setHover] = useState<{ gene: TargetSummary; x: number; y: number } | null>(null);

  useEffect(() => {
    const element = wrap.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const box = entry.contentRect;
      setSize(Math.max(300, Math.min(box.width - 20, box.height - 20, 680)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const nearest = useCallback(
    (clientX: number, clientY: number): TargetSummary | null => {
      const element = canvas.current;
      if (!element || !genes.length) return null;
      const rect = element.getBoundingClientRect();
      const x = ((clientX - rect.left) / rect.width) * size - size / 2;
      const y = ((clientY - rect.top) / rect.height) * size - size / 2;
      const radius = Math.hypot(x, y);
      if (radius < size * 0.2 || radius > size * 0.5) return null;
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
    const geneRadius = size * 0.452;
    const geneHeight = size * 0.055;
    const rings = [
      { r: size * 0.35, h: size * 0.028, on: (g: TargetSummary) => g.n_pdb > 0, colour: () => token("--counter") },
      {
        r: size * 0.305,
        h: size * 0.028,
        on: (g: TargetSummary) => g.has_ligands,
        colour: (g: TargetSummary) =>
          g.chembl_evidence === "direct" ? token("--accent") : token("--counter"),
      },
      {
        r: size * 0.26,
        h: size * 0.028,
        on: (g: TargetSummary) => g.n_variants_associated > 0,
        colour: () => token("--warn"),
      },
    ];

    context.strokeStyle = token("--line");
    context.lineWidth = 1;
    for (const r of [geneRadius - geneHeight / 2, ...rings.map((x) => x.r)]) {
      context.beginPath();
      context.arc(cx, cy, r, 0, Math.PI * 2);
      context.stroke();
    }

    const filtered = matching.size !== genes.length;
    const width = Math.max(1, ((Math.PI * 2 * geneRadius) / genes.length) * 0.95);
    const angleOf = (g: TargetSummary) =>
      (((g.start + g.stop) / 2) / GENOME_LENGTH) * Math.PI * 2 - Math.PI / 2;
    const radial = (angle: number, r0: number, r1: number) => {
      context.beginPath();
      context.moveTo(cx + Math.cos(angle) * r0, cy + Math.sin(angle) * r0);
      context.lineTo(cx + Math.cos(angle) * r1, cy + Math.sin(angle) * r1);
      context.stroke();
    };

    for (const gene of genes) {
      const angle = angleOf(gene);
      const dim = filtered && !matching.has(gene.rv_id);
      context.globalAlpha = dim ? 0.12 : 1;
      context.lineWidth = width;
      context.strokeStyle = colourOf(gene, colourBy);
      radial(angle, geneRadius - geneHeight / 2, geneRadius + geneHeight / 2);
      for (const ring of rings) {
        if (!ring.on(gene)) continue;
        context.globalAlpha = dim ? 0.09 : 0.9;
        context.strokeStyle = ring.colour(gene);
        radial(angle, ring.r - ring.h / 2, ring.r + ring.h / 2);
      }
    }
    context.globalAlpha = 1;

    context.font = `500 ${Math.round(size * 0.019)}px ${token("--mono")}`;
    context.fillStyle = token("--fg-faint");
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.strokeStyle = token("--line-strong");
    context.lineWidth = 1;
    for (let bp = 0; bp < GENOME_LENGTH; bp += 500_000) {
      const angle = (bp / GENOME_LENGTH) * Math.PI * 2 - Math.PI / 2;
      radial(angle, geneRadius + geneHeight / 2, geneRadius + geneHeight / 2 + size * 0.012);
      const labelRadius = geneRadius + geneHeight / 2 + size * 0.036;
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
      radial(angleOf(chosen), size * 0.225, geneRadius + geneHeight / 2 + size * 0.015);
    }

    context.textAlign = "center";
    context.fillStyle = token("--fg");
    context.font = `600 ${Math.round(size * 0.052)}px ${token("--mono")}`;
    context.fillText(
      chosen ? chosen.rv_id : matching.size.toLocaleString("en-US"),
      cx,
      cy - size * 0.012,
    );
    context.fillStyle = token("--fg-dim");
    context.font = `400 ${Math.round(size * 0.025)}px ${token("--sans")}`;
    context.fillText(
      chosen ? (chosen.gene_name ?? "unnamed") : filtered ? "genes match" : "genes",
      cx,
      cy + size * 0.032,
    );
  }, [genes, matching, colourBy, selected, size, theme]);

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
      {hover && (
        <div
          className="tooltip"
          style={{
            left: (canvas.current?.offsetLeft ?? 0) + hover.x,
            top: (canvas.current?.offsetTop ?? 0) + hover.y,
          }}
        >
          {hover.gene.rv_id}
          {hover.gene.gene_name && hover.gene.gene_name !== hover.gene.rv_id
            ? ` · ${hover.gene.gene_name}`
            : ""}
        </div>
      )}
    </div>
  );
}
