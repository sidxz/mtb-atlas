import type { CSSProperties } from "react";

export const FORMAT_COLORS = { blue: "#3b82f6", green: "#16a34a", amber: "#d99a16", red: "#ef4444", purple: "#a855f7" } as const;
export const OPERATORS = { gt: "Greater than", gte: "At least", lt: "Less than", lte: "At most", eq: "Equal to", between: "Between (inclusive)" } as const;
export const PALETTES = {
  blue: { label: "Light blue → Blue", colors: ["#dbeafe", "#2563eb"] },
  red_green: { label: "Red → Yellow → Green", colors: ["#ef4444", "#facc15", "#22c55e"] },
  green_red: { label: "Green → Yellow → Red", colors: ["#22c55e", "#facc15", "#ef4444"] },
} as const;
export type Rule = {
  id: string; column: string; operator: keyof typeof OPERATORS; value: number; upper: number | null;
  target: "cell" | "row"; color: keyof typeof FORMAT_COLORS;
};
export type Scale = {
  id: string; column: string; palette: keyof typeof PALETTES; mode: "scale" | "bar";
  minimum: number | null; maximum: number | null;
};
export type Formatting = { rules: Rule[]; scales: Scale[] };
export type Preferences = Formatting & { visible: string[] | null };
export type Range = { scale: Scale; min: number; max: number };
export const EMPTY_PREFERENCES: Preferences = { visible: null, rules: [], scales: [] };

export function numericValue(row: object, column: string): number | undefined {
  const value = (row as Record<string, unknown>)[column];
  // The clinical data uses a negative phase for "unknown", not a measurement.
  if (["best_drug_phase", "max_phase_tb", "phase_max"].includes(column) && typeof value === "number" && value < 0) return undefined;
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
export function matches(value: number | undefined, rule: Rule): boolean {
  if (value === undefined) return false;
  switch (rule.operator) {
    case "gt": return value > rule.value;
    case "gte": return value >= rule.value;
    case "lt": return value < rule.value;
    case "lte": return value <= rule.value;
    case "eq": return value === rule.value;
    case "between": return rule.upper !== null && value >= rule.value && value <= rule.upper;
  }
}
export function scaleRanges(rows: object[], scales: Scale[]): Range[] {
  return scales.flatMap((scale) => {
    if (scale.minimum !== null && scale.maximum !== null) return [{ scale, min: scale.minimum, max: scale.maximum }];
    let min = Infinity, max = -Infinity;
    for (const row of rows) {
      const value = numericValue(row, scale.column);
      if (value !== undefined) { min = Math.min(min, value); max = Math.max(max, value); }
    }
    return min === Infinity ? [] : [{ scale, min, max }];
  });
}
export function position(value: number, min: number, max: number): number {
  if (min === max) return 0.5;
  const magnitude = Math.max(Math.abs(min), Math.abs(max), 1);
  return Math.max(0, Math.min(1, (value / magnitude - min / magnitude) / (max / magnitude - min / magnitude)));
}
export function scaleColor(palette: Scale["palette"], fraction: number): string {
  const colors = PALETTES[palette].colors;
  const segment = Math.max(0, Math.min(1, fraction)) * (colors.length - 1);
  const index = Math.min(Math.floor(segment), colors.length - 2);
  const rgb = (hex: string) => [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16));
  const from = rgb(colors[index]), to = rgb(colors[index + 1]);
  return `rgb(${from.map((channel, i) => Math.round(channel + (to[i] - channel) * (segment - index))).join(", ")})`;
}
const fill = (color: string, strength = 22) => `color-mix(in srgb, ${color} ${strength}%, var(--surface))`;

/** Specific cell rules win over scales, which win over row rules. Rule order is priority. */
export function cellFormatting(row: object, column: string, rules: Rule[], ranges: Range[]): CSSProperties | undefined {
  const value = numericValue(row, column);
  const cell = rules.find((rule) => rule.target === "cell" && rule.column === column && matches(value, rule));
  if (cell) return { backgroundColor: fill(FORMAT_COLORS[cell.color]) };
  const range = value === undefined ? undefined : ranges.find(({ scale }) => scale.column === column);
  if (range && value !== undefined) {
    const fraction = position(value, range.min, range.max);
    const color = scaleColor(range.scale.palette, fraction);
    if (range.scale.mode === "bar") return {
      backgroundImage: `linear-gradient(to right, ${fill(color, 38)} ${fraction * 100}%, transparent ${fraction * 100}%)`,
      backgroundSize: "100% 60%", backgroundPosition: "center", backgroundRepeat: "no-repeat",
    };
    return { backgroundColor: fill(color, 30) };
  }
  const wholeRow = rules.find((rule) => rule.target === "row" && matches(numericValue(row, rule.column), rule));
  return wholeRow ? { backgroundColor: fill(FORMAT_COLORS[wholeRow.color], 15) } : undefined;
}

/** Validate untrusted browser preferences and reject old/corrupt settings safely. */
export function parsePreferences(raw: unknown, columns: string[], numeric: string[], identity = "rv_id"): Preferences {
  if (!raw || typeof raw !== "object") return EMPTY_PREFERENCES;
  const p = raw as Partial<Preferences>;
  const validRules = Array.isArray(p.rules) && p.rules.length <= 12 && p.rules.every(r => r && typeof r.id === "string" && numeric.includes(r.column) && Object.hasOwn(OPERATORS, r.operator) && Number.isFinite(r.value) && Object.hasOwn(FORMAT_COLORS, r.color) && ["cell", "row"].includes(r.target) && (r.operator !== "between" || (typeof r.upper === "number" && Number.isFinite(r.upper) && r.upper >= r.value)));
  const validScales = Array.isArray(p.scales) && p.scales.length <= 12 && p.scales.every(s => s && typeof s.id === "string" && numeric.includes(s.column) && Object.hasOwn(PALETTES, s.palette) && ["scale", "bar"].includes(s.mode) && ((s.minimum === null && s.maximum === null) || (typeof s.minimum === "number" && typeof s.maximum === "number" && Number.isFinite(s.minimum) && Number.isFinite(s.maximum) && s.minimum < s.maximum)));
  return {
    visible: Array.isArray(p.visible) ? [...new Set([identity, ...p.visible.filter(k => typeof k === "string" && columns.includes(k))])] : null,
    rules: validRules ? p.rules! : [], scales: validScales ? p.scales! : [],
  };
}
