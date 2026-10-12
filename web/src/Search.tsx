/**
 * One box over everything the atlas holds.
 *
 * A gene, a drug, a trial or a compound, found by id, name, synonym or the
 * text around it, and opened wherever it lives. The alternative was a search
 * box per view, which makes the user know in advance which kind of thing they
 * are looking for.
 */

import { useCallback, useEffect, useRef, useState } from "react";
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

  const pick = useCallback(
    (kind: Kind, id: string) => {
      onPick(kind, id);
      setOpen(false);
      setQuery("");
      setResults(EMPTY);
    },
    [onPick],
  );

  return (
    <div className="globalsearch" ref={box}>
      <InterfaceIcon name="search" />
      <input
        className="search"
        type="search"
        value={query}
        placeholder="Search the atlas…"
        aria-label="Search genes, drugs, trials, compounds and screening campaigns"
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
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
            pick(kind, hit.id);
          }
        }}
      />
      {open && query.trim().length >= 2 && (
        <div className="searchdrop" role="listbox">
          {flat.length === 0 ? (
            <p className="absent">Nothing in the atlas matches that.</p>
          ) : (
            KINDS.map(([kind, label]) =>
              results[kind].length ? (
                <div key={kind}>
                  <p className="lab">{label}</p>
                  {results[kind].map((hit) => {
                    const index = flat.findIndex(([k, h]) => k === kind && h.id === hit.id);
                    return (
                      <button
                        key={hit.id}
                        type="button"
                        role="option"
                        aria-selected={index === active}
                        onMouseEnter={() => setActive(index)}
                        onClick={() => pick(kind, hit.id)}
                      >
                        <span className="id">{hit.id}</span>
                        <b>{hit.label === hit.id ? "" : hit.label}</b>
                        <span className="dim">{hit.detail}</span>
                      </button>
                    );
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
