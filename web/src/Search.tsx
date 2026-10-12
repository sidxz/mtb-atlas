/**
 * One box over everything the atlas holds.
 *
 * A gene, a drug, a trial or a compound, found by id, name, synonym or the
 * text around it, and opened wherever it lives. The alternative was a search
 * box per view, which makes the user know in advance which kind of thing they
 * are looking for.
 */

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { InterfaceIcon } from "./InterfaceIcon";
import { api, type Hit, type SearchResults } from "./api";

type Kind = keyof SearchResults;

const KINDS: [Kind, string][] = [
  ["genes", "Genes"],
  ["drugs", "Drugs & candidates"],
  ["trials", "Trials"],
  ["compounds", "Compounds"],
  ["screens", "Screening campaigns"],
];

const EMPTY: SearchResults = { genes: [], drugs: [], trials: [], compounds: [], screens: [] };

export function Search({
  onPick,
}: {
  onPick: (kind: Kind, id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults>(EMPTY);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const dropdown = useRef<HTMLDivElement>(null);
  const listId = useId();
  const visible = open && query.trim().length >= 2;

  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) {
      setResults(EMPTY);
      return;
    }
    // Typing is faster than the round trip; only the last request counts.
    let current = true;
    const timer = setTimeout(() => {
      api
        .search(text)
        .then((found) => current && setResults(found))
        .catch(() => current && setResults(EMPTY));
    }, 150);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    const away = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const flat: [Kind, Hit][] = KINDS.flatMap(([kind]) =>
    results[kind].map((hit) => [kind, hit] as [Kind, Hit]),
  );
  const activeIndex = Math.min(active, flat.length - 1);

  useEffect(() => {
    const list = dropdown.current;
    const option = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!list || !option) return;
    const bounds = list.getBoundingClientRect();
    const item = option.getBoundingClientRect();
    if (item.top < bounds.top) list.scrollTop -= bounds.top - item.top;
    else if (item.bottom > bounds.bottom) list.scrollTop += item.bottom - bounds.bottom;
  }, [activeIndex, visible, results]);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setResults(EMPTY);
  }, []);
  const pick = useCallback(
    (kind: Kind, id: string) => {
      onPick(kind, id);
      close();
    },
    [onPick, close],
  );
  // Shift+Enter on a gene opens it in the map: the keyboard route to the Map link.
  const navigate = useNavigate();
  const mapPath = (rv: string) => `/map/${encodeURIComponent(rv)}`;

  return (
    <div className="globalsearch" ref={box}>
      <InterfaceIcon name="search" />
      <input
        className="search"
        type="search"
        role="combobox"
        value={query}
        placeholder="Search the atlas…"
        aria-label="Search genes, drugs, trials, compounds and screening campaigns"
        aria-autocomplete="list"
        aria-expanded={visible}
        aria-controls={visible ? listId : undefined}
        aria-activedescendant={visible && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            setOpen(false);
            return;
          }
          if (!visible) {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              setOpen(true);
            }
            return;
          }
          if (!flat.length) return;
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setActive((i) => (i + 1) % flat.length);
          }
          if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((i) => (i - 1 + flat.length) % flat.length);
          }
          if (event.key === "Enter") {
            const [kind, hit] = flat[Math.min(active, flat.length - 1)];
            if (event.shiftKey && kind === "genes") {
              navigate(mapPath(hit.id));
              close();
            } else pick(kind, hit.id);
          }
        }}
      />
      {visible && (
        <div className="searchdrop" ref={dropdown} id={listId} role="listbox" aria-label="Search results">
          {flat.length === 0 ? (
            <p className="absent">No results found.</p>
          ) : (
            KINDS.map(([kind, label]) =>
              results[kind].length ? (
                <div key={kind} role="group" aria-label={label}>
                  <p className="lab">{label}</p>
                  {results[kind].map((hit) => {
                    const index = flat.findIndex(([k, h]) => k === kind && h.id === hit.id);
                    const option = (
                      <button
                        key={hit.id}
                        id={`${listId}-${index}`}
                        type="button"
                        role="option"
                        aria-selected={index === activeIndex}
                        title={[hit.label, hit.id, hit.detail].filter(Boolean).join(" · ")}
                        onMouseEnter={() => setActive(index)}
                        onClick={() => pick(kind, hit.id)}
                      >
                        <span className="search-result-title">{hit.label || hit.id}</span>
                        {(hit.label !== hit.id || hit.detail) && (
                          <span className="search-result-meta">
                            {hit.label !== hit.id && <span className="id">{hit.id}</span>}
                            {hit.detail && <span className="search-result-detail">{hit.detail}</span>}
                          </span>
                        )}
                      </button>
                    );
                    // Genes also open in Targets and the map. A sibling, not a child: a button
                    // cannot sit inside the option button.
                    return kind === "genes" ? (
                      <div className="search-row" key={hit.id}>
                        {option}
                        <Link className="search-map" to={`/targets/${encodeURIComponent(hit.id)}`} tabIndex={-1} onClick={close}
                          title="Open in Targets" aria-label={`Open ${hit.label || hit.id} in Targets`}>
                          <InterfaceIcon name="targets" />
                        </Link>
                        <Link className="search-map" to={mapPath(hit.id)} tabIndex={-1} onClick={close}
                          title="Open in map (Shift+Enter)" aria-label={`Open ${hit.label || hit.id} in the map`}>
                          <InterfaceIcon name="map" />
                        </Link>
                      </div>
                    ) : option;
                  })}
                </div>
              ) : null,
            )
          )}
        </div>
      )}
    </div>
  );
}
