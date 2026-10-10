import { useId, useState, type ReactNode } from "react";
import { InterfaceIcon } from "./InterfaceIcon";

/** Keep filters available on phones without placing them ahead of every result. */
export function FilterRail({ children, label = "Filters and genome" }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <aside className={`col col-pad filter-rail${open ? " rail-open" : ""}`}>
      <button className="rail-toggle" type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        <InterfaceIcon name="filter" />{label}<span aria-hidden="true">{open ? "−" : "+"}</span>
      </button>
      <div id={id} className="rail-content">{children}</div>
    </aside>
  );
}
