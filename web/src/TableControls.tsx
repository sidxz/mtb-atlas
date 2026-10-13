import { useEffect, useRef, useState, type ReactNode } from "react";
import { InterfaceIcon } from "./InterfaceIcon";
import { EMPTY_PREFERENCES, FORMAT_COLORS, OPERATORS, PALETTES, parsePreferences, type Formatting, type Preferences, type Rule, type Scale } from "./table-formatting";

export type Column = [string, string, boolean];
type Group = { label: string; keys: string[] };
const STORAGE_KEY = "atlas.gene-table.v1";

export function useTablePreferences(columns: Column[], storageKey = STORAGE_KEY, identity = "rv_id") {
  const [state, setState] = useState(() => {
    try {
      return { preferences: parsePreferences(JSON.parse(localStorage.getItem(storageKey) ?? "null"), columns.map(c => c[0]), columns.filter(c => c[2]).map(c => c[0]), identity), saved: true };
    } catch { return { preferences: EMPTY_PREFERENCES, saved: false }; }
  });
  function change(preferences: Preferences) {
    let saved = true;
    try { localStorage.setItem(storageKey, JSON.stringify(preferences)); } catch { saved = false; }
    setState({ preferences, saved });
  }
  return { ...state, change };
}

function SettingsDialog({ title, compact, onClose, children }: { title: string; compact?: boolean; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement as HTMLElement | null;
    dialog.showModal();
    return () => { dialog.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} className={`table-settings${compact ? " settings-compact" : ""}`} aria-label={title}
    onCancel={event => { event.preventDefault(); onClose(); }}
    onKeyDown={event => { if (event.key === "Escape") event.stopPropagation(); }}
    onClick={event => {
      if (event.target !== event.currentTarget) return;
      const box = event.currentTarget.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) onClose();
    }}>
    <div className="settings-heading"><h2>{title}</h2><button type="button" className="minibtn" aria-label={`Close ${title.toLowerCase()}`} onClick={onClose}>×</button></div>
    {children}
  </dialog>;
}

type RuleDraft = Omit<Rule, "value" | "upper"> & { value: string; upper: string };
type ScaleDraft = Omit<Scale, "minimum" | "maximum"> & { minimum: string; maximum: string };
function FormattingEditor({ columns, formatting, saved, onApply, onClose, recordLabel }: {
  recordLabel: string; columns: Column[]; formatting: Formatting; saved: boolean; onApply: (next: Formatting) => void; onClose: () => void;
}) {
  const numeric = columns.filter(c => c[2]);
  const [rules, setRules] = useState<RuleDraft[]>(formatting.rules.map(r => ({ ...r, value: String(r.value), upper: r.upper === null ? "" : String(r.upper) })));
  const [scales, setScales] = useState<ScaleDraft[]>(formatting.scales.map(s => ({ ...s, minimum: s.minimum === null ? "" : String(s.minimum), maximum: s.maximum === null ? "" : String(s.maximum) })));
  const [error, setError] = useState("");
  const updateRule = (index: number, patch: Partial<RuleDraft>) => { setRules(rules.map((r, i) => i === index ? { ...r, ...patch } : r)); setError(""); };
  const updateScale = (index: number, patch: Partial<ScaleDraft>) => { setScales(scales.map((s, i) => i === index ? { ...s, ...patch } : s)); setError(""); };
  function move(index: number, direction: number) {
    const next = [...rules];
    [next[index], next[index + direction]] = [next[index + direction], next[index]];
    setRules(next);
  }
  function apply() {
    if (rules.some(r => !r.value.trim() || !Number.isFinite(Number(r.value)) || (r.operator === "between" && (!r.upper.trim() || !Number.isFinite(Number(r.upper)) || Number(r.upper) < Number(r.value))))) {
      setError("Enter a valid number for each rule. A range’s upper value must be greater than or equal to its lower value."); return;
    }
    if (scales.some(s => (s.minimum.trim() || s.maximum.trim()) && (!s.minimum.trim() || !s.maximum.trim() || !Number.isFinite(Number(s.minimum)) || !Number.isFinite(Number(s.maximum)) || Number(s.minimum) >= Number(s.maximum)))) {
      setError("Enter a minimum and maximum, with the minimum lower than the maximum. Leave both blank to use the data range."); return;
    }
    if (new Set(scales.map(s => s.column)).size !== scales.length) { setError("Use only one color scale or data bar per column."); return; }
    onApply({
      rules: rules.map(r => ({ ...r, value: Number(r.value), upper: r.operator === "between" ? Number(r.upper) : null })),
      scales: scales.map(s => ({ ...s, minimum: s.minimum.trim() ? Number(s.minimum) : null, maximum: s.maximum.trim() ? Number(s.maximum) : null })),
    });
    onClose();
  }
  const options = numeric.map(([key, label]) => <option key={key} value={key}>{label}</option>);
  return <SettingsDialog title="Conditional formatting" onClose={onClose}>
    <div className="settings-body">
      <p className="settings-help">Highlight cells or rows with rules, color scales or data bars.</p>
      {rules.map((rule, index) => <fieldset className="format-card" key={rule.id}>
        <legend>Rule {index + 1}</legend>
        <div className="format-card-tools">
          <button className="minibtn" type="button" aria-label={`Move rule ${index + 1} up`} disabled={!index} onClick={() => move(index, -1)}>↑</button>
          <button className="minibtn" type="button" aria-label={`Move rule ${index + 1} down`} disabled={index === rules.length - 1} onClick={() => move(index, 1)}>↓</button>
          <button className="minibtn" type="button" aria-label={`Remove rule ${index + 1}`} onClick={() => { setRules(rules.filter((_, i) => i !== index)); setError(""); }}>Remove</button>
        </div>
        <div className="format-fields">
          <label>Column<select aria-label={`Column for rule ${index + 1}`} value={rule.column} onChange={e => updateRule(index, { column: e.target.value })}>{options}</select></label>
          <label>Condition<select aria-label={`Condition for rule ${index + 1}`} value={rule.operator} onChange={e => updateRule(index, { operator: e.target.value as Rule["operator"] })}>{Object.entries(OPERATORS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label>{rule.operator === "between" ? "Lower value" : "Value"}<input aria-label={`Value for rule ${index + 1}`} inputMode="decimal" value={rule.value} onChange={e => updateRule(index, { value: e.target.value })} /></label>
          {rule.operator === "between" && <label>Upper value<input aria-label={`Upper value for rule ${index + 1}`} inputMode="decimal" value={rule.upper} onChange={e => updateRule(index, { upper: e.target.value })} /></label>}
          <label>Highlight<select aria-label={`Highlight for rule ${index + 1}`} value={rule.target} onChange={e => updateRule(index, { target: e.target.value as Rule["target"] })}><option value="cell">This cell</option><option value="row">Entire row</option></select></label>
          <label>Color<select aria-label={`Color for rule ${index + 1}`} value={rule.color} onChange={e => updateRule(index, { color: e.target.value as Rule["color"] })}>{Object.keys(FORMAT_COLORS).map(key => <option key={key} value={key}>{key[0].toUpperCase() + key.slice(1)}</option>)}</select></label>
        </div>
        <div className="format-preview" style={{ background: `color-mix(in srgb, ${FORMAT_COLORS[rule.color]} 22%, var(--surface))` }}>Preview · {rule.target === "cell" ? "Matching cell" : "Matching row"}</div>
      </fieldset>)}
      {scales.map((scale, index) => <fieldset className="format-card" key={scale.id}>
        <legend>{scale.mode === "bar" ? "Data bar" : "Color scale"} {index + 1}</legend>
        <div className="format-card-tools"><button className="minibtn" type="button" aria-label={`Remove scale ${index + 1}`} onClick={() => { setScales(scales.filter((_, i) => i !== index)); setError(""); }}>Remove</button></div>
        <div className="format-fields">
          <label>Column<select aria-label={`Column for scale ${index + 1}`} value={scale.column} onChange={e => updateScale(index, { column: e.target.value })}>{options}</select></label>
          <label>Display<select aria-label={`Display for scale ${index + 1}`} value={scale.mode} onChange={e => updateScale(index, { mode: e.target.value as Scale["mode"] })}><option value="scale">Color scale</option><option value="bar">Data bar</option></select></label>
          <label className="format-wide">Colors · low to high<select aria-label={`Palette for scale ${index + 1}`} value={scale.palette} onChange={e => updateScale(index, { palette: e.target.value as Scale["palette"] })}>{Object.entries(PALETTES).map(([key, p]) => <option key={key} value={key}>{p.label}</option>)}</select></label>
          <label>Minimum<input aria-label={`Minimum for scale ${index + 1}`} inputMode="decimal" placeholder="Automatic" value={scale.minimum} onChange={e => updateScale(index, { minimum: e.target.value })} /></label>
          <label>Maximum<input aria-label={`Maximum for scale ${index + 1}`} inputMode="decimal" placeholder="Automatic" value={scale.maximum} onChange={e => updateScale(index, { maximum: e.target.value })} /></label>
        </div>
        <div className="scale-preview" style={{ background: `linear-gradient(to right, ${PALETTES[scale.palette].colors.join(", ")})` }} aria-hidden="true" />
        <p className="settings-help">{scale.minimum || scale.maximum ? "Fixed bounds keep this scale consistent across filters." : `Automatic range uses all filtered ${recordLabel}. Equal values use the midpoint.`}{scale.mode === "bar" && " Bar length shows position from minimum to maximum."}</p>
      </fieldset>)}
      <div className="format-add">
        <button className="minibtn" type="button" disabled={rules.length >= 12} onClick={() => { setRules([...rules, { id: crypto.randomUUID(), column: numeric[0][0], operator: "gte", value: "", upper: "", target: "cell", color: "green" }]); setError(""); }}>+ Add rule</button>
        <button className="minibtn" type="button" disabled={scales.length >= numeric.length} onClick={() => { setScales([...scales, { id: crypto.randomUUID(), column: numeric.find(c => !scales.some(s => s.column === c[0]))![0], palette: "blue", mode: "scale", minimum: "", maximum: "" }]); setError(""); }}>+ Add color scale / bar</button>
        {(rules.length > 0 || scales.length > 0) && <button className="minibtn" type="button" onClick={() => { setRules([]); setScales([]); setError(""); }}>Clear all</button>}
      </div>
      <p className="settings-help">Missing values never trigger a rule or scale. Cell rules override scales; scales override row rules. The first matching rule wins. Formatting does not change the data.</p>
      {error && <p className="format-error" role="alert">{error}</p>}
    </div>
    <div className="settings-footer"><span>{saved ? "Saved in this browser" : "Browser storage is unavailable; settings will not be saved"}</span><button className="minibtn" type="button" onClick={onClose}>Cancel</button><button className="minibtn settings-apply" type="button" onClick={apply}>Apply formatting</button></div>
  </SettingsDialog>;
}

export function TableControls({ columns, groups, visible, preferences, saved, onChange, sortLabel, leading, identity = "rv_id", recordLabel = "genes", defaultNote = "Default shows fewer columns when a gene is open." }: {
  columns: Column[]; groups: Group[]; visible: Column[]; preferences: Preferences; saved: boolean;
  onChange: (next: Preferences) => void; sortLabel?: string; leading?: ReactNode; identity?: string; recordLabel?: string; defaultNote?: string;
}) {
  const [open, setOpen] = useState<"columns" | "formatting" | null>(null);
  const shown = new Set(visible.map(c => c[0]));
  const [search, setSearch] = useState("");
  function toggle(key: string) {
    const next = new Set(shown); next.has(key) ? next.delete(key) : next.add(key);
    next.add(identity); onChange({ ...preferences, visible: columns.filter(c => next.has(c[0])).map(c => c[0]) });
  }
  const count = preferences.rules.length + preferences.scales.length;
  return <div className="table-controls">
    {leading && <div className="table-toolbar-context">{leading}</div>}
    {sortLabel && <span className="table-sort-note">Sorted by {sortLabel}</span>}
    <button className="minibtn" type="button" aria-haspopup="dialog" aria-expanded={open === "columns"} onClick={() => { setSearch(""); setOpen("columns"); }}><InterfaceIcon name="columns" /><span className="table-control-label">Columns</span> <span className="table-control-count">{visible.length}</span></button>
    <button className="minibtn" type="button" aria-haspopup="dialog" aria-expanded={open === "formatting"} onClick={() => setOpen("formatting")}><InterfaceIcon name="format" /><span className="table-control-label">Formatting</span>{count > 0 && <span className="table-control-count">{count}</span>}</button>
    {open === "columns" && <SettingsDialog title="Show / hide columns" compact onClose={() => setOpen(null)}>
      <div className="settings-body">
        <input className="search" aria-label="Search columns" placeholder="Find a column…" value={search} onChange={e => setSearch(e.target.value)} />
        {groups.map(group => {
          const items = columns.filter(c => group.keys.includes(c[0]) && `${group.label} ${c[1]}`.toLowerCase().includes(search.toLowerCase()));
          return items.length ? <fieldset className="column-choices" key={group.label}><legend>{group.label}</legend>{items.map(([key, label]) => <label key={key}><input type="checkbox" checked={shown.has(key)} disabled={key === identity} onChange={() => toggle(key)} />{label}{key === identity && <span>Always shown</span>}</label>)}</fieldset> : null;
        })}
        {!groups.some(g => columns.some(c => g.keys.includes(c[0]) && `${g.label} ${c[1]}`.toLowerCase().includes(search.toLowerCase()))) && <p className="settings-help">No matching columns.</p>}
      </div>
      <div className="settings-footer"><button className="minibtn" type="button" onClick={() => onChange({ ...preferences, visible: columns.map(c => c[0]) })}>Show all</button><button className="minibtn" type="button" onClick={() => onChange({ ...preferences, visible: null })}>Reset default</button><button className="minibtn settings-apply" type="button" onClick={() => setOpen(null)}>Done</button></div>
      <p className="settings-storage">{saved ? `Saved in this browser. ${columns.find(c => c[0] === identity)?.[1] ?? "Identity"} always stays visible.` : "Browser storage is unavailable; settings will not be saved."} {defaultNote}</p>
    </SettingsDialog>}
    {open === "formatting" && <FormattingEditor recordLabel={recordLabel} columns={columns} formatting={preferences} saved={saved} onApply={formatting => onChange({ ...preferences, ...formatting })} onClose={() => setOpen(null)} />}
  </div>;
}
