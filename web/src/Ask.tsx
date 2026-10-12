/**
 * Natural-language questions over the store.
 *
 * The answer takes the full width. The SQL behind it still comes back from
 * /ask (`queries`) and is not drawn here.
 */

import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router";
import { InterfaceIcon } from "./InterfaceIcon";
import type { Hit, SearchResults } from "./api";

const EXAMPLES = [
  "Which essential genes have a structure, no ligands, and no close human homolog?",
  "What is known about Rv0206c, and what is missing?",
  "Which genes are most vulnerable by CRISPRi but have no chemical matter at all?",
  "Compare dprE1 and inhA on every kind of evidence the atlas holds.",
  "Which essential, confidently vulnerable genes have no TB drug or candidate acting on them?",
  "Which phase 2 or 3 trials test a drug that acts on dprE1 or mmpL3, and are they recruiting?",
];

interface Result {
  answer: string;
  queries: { tool: string; sql: string | null; rows: number | null; error: string | null }[];
  /** The store's own objects the answer names; only exact ids and gene names. */
  references?: SearchResults;
}

const at = (...parts: string[]) => "/" + parts.map(encodeURIComponent).join("/");

/** Where each kind of reference opens; a gene opens in every view that has one. */
const OPENS: Record<keyof SearchResults, [string, (id: string) => string][]> = {
  genes: [["Genome", (id) => at("genome", id)], ["Targets", (id) => at("targets", id)], ["Map", (id) => at("map", id)]],
  drugs: [["Drug", (id) => at("clinical", "drug", id)]],
  trials: [["Trial", (id) => at("clinical", "trial", id)]],
  compounds: [["Compound", (id) => at("clinical", "compound", id)]],
  screens: [["Screen", (id) => at("screens", id)]],
};
const KIND_LABEL: Record<keyof SearchResults, string> = {
  genes: "Genes", drugs: "Drugs", trials: "Trials", compounds: "Compounds", screens: "Screens",
};

function References({ refs, onGeneScreens, onFollow }: {
  refs: SearchResults;
  onGeneScreens: (rv: string) => void;
  /** A followed link folds the answer away, so the page it opened is in view. */
  onFollow: () => void;
}) {
  const kinds = (Object.keys(OPENS) as (keyof SearchResults)[]).filter((k) => refs[k]?.length);
  if (!kinds.length) return null;
  return (
    <section className="askrefs" aria-label="Referenced in this answer" onClick={(e) => { if ((e.target as HTMLElement).closest("a")) onFollow(); }}>
      <h4>Referenced</h4>
      {kinds.map((kind) => (
        <div className="askrefs-kind" key={kind}>
          <span className="askrefs-label">{KIND_LABEL[kind]}</span>
          {refs[kind].map((hit: Hit) => (
            <span className="askref" key={hit.id} title={hit.detail ?? undefined}>
              <strong>{hit.label !== hit.id ? `${hit.label} · ${hit.id}` : hit.id}</strong>
              {OPENS[kind].map(([label, to]) => <Link key={label} to={to(hit.id)}>{label}</Link>)}
              {kind === "genes" && <Link to="/screens" onClick={() => onGeneScreens(hit.id)}>Screens</Link>}
            </span>
          ))}
        </div>
      ))}
    </section>
  );
}

export function Ask({ base, onGeneScreens }: { base: string; onGeneScreens: (rv: string) => void }) {
  const [question, setQuestion] = useState("");
  // The question the panel answers; the input may have moved on since.
  const [asked, setAsked] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [state, setState] = useState<"idle" | "asking" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(true);
  const [seconds, setSeconds] = useState(0);
  const inflight = useRef<AbortController | null>(null);
  // The examples are onboarding. Shown always they cost 85px of every session
  // forever, which on a laptop is three rows of the gene table.
  const [focused, setFocused] = useState(false);

  // A broad question runs for a minute of model turns; a static "querying" line
  // for that long reads as a hang. Frozen when the answer lands, so it doubles as
  // the time taken.
  useEffect(() => {
    if (state !== "asking") return;
    const start = Date.now();
    setSeconds(0);
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [state]);

  const submit = async (text: string) => {
    if (!text.trim()) return;
    const controller = new AbortController();
    inflight.current = controller;
    setAsked(text);
    setOpen(true);
    setState("asking");
    setResult(null);
    setError(null);
    try {
      const response = await fetch(`${base}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
        signal: controller.signal,
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? `${response.status}`);
      setResult(body as Result);
      setState("idle");
    } catch (caught: unknown) {
      if (controller.signal.aborted) return;
      setError(String(caught instanceof Error ? caught.message : caught));
      setState("error");
    }
  };

  // Cancels a question still running too, or its answer would reappear after
  // the panel was cleared. The server finishes the call regardless.
  const clear = () => {
    inflight.current?.abort();
    setAsked(null);
    setResult(null);
    setError(null);
    setState("idle");
    setQuestion("");
  };

  return (
    <div className="ask">
      <form
        className="askbar"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
      >
        <label className="ask-label" htmlFor="atlas-question"><InterfaceIcon name="ask" />Ask the atlas</label>
        <input
          id="atlas-question"
          className="search"
          value={question}
          placeholder="Ask a research question · answers link to evidence"
          onChange={(event) => setQuestion(event.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
        />
        <button className="iconbtn" type="submit" disabled={state === "asking"}>
          {state === "asking" ? "Asking…" : "Ask"}
        </button>
      </form>

      {focused && !result && state === "idle" && !error && (
        <div className="askexamples">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              // Before blur, so clicking an example does not first close the list.
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                setQuestion(example);
                void submit(example);
              }}
            >
              {example}
            </button>
          ))}
        </div>
      )}

      {asked !== null && (
        <section className="askpanel" aria-label="Answer">
          <div className="askpanel-head">
            <button
              type="button"
              className="askpanel-toggle"
              aria-expanded={open}
              aria-controls="ask-answer"
              title={asked}
              onClick={() => setOpen(!open)}
            >
              <span className="chev" aria-hidden="true" />
              <span className="askpanel-question">{asked}</span>
            </button>
            <span className="faint askpanel-time">
              {state === "asking" ? `${seconds} s` : result ? `took ${seconds} s` : ""}
            </span>
            <button type="button" className="iconbtn" onClick={clear}>
              Clear
            </button>
          </div>
          {open && (
            <div id="ask-answer" className="askpanel-body">
              {state === "asking" && (
                <div className="askloading">
                  <span className="spinner" aria-hidden="true" />
                  <div>
                    <span role="status">Querying the store</span>
                    <span aria-hidden="true"> · {seconds} s</span>
                    <p className="note">Broad questions take up to a minute.</p>
                  </div>
                </div>
              )}

              {error && (
                <div className="caveat">
                  {error.includes("credentials")
                    ? "The agent needs Anthropic credentials. Set ANTHROPIC_API_KEY where the API runs; everything else in the atlas works without it."
                    : error}
                </div>
              )}

              {result && (
                <div className="askresult">
                  {/* The model answers in markdown, tables included (GFM). No raw HTML is rendered. */}
                  <div className="answer">
                    <Markdown remarkPlugins={[remarkGfm]}>{result.answer}</Markdown>
                  </div>
                  {result.references && <References refs={result.references} onGeneScreens={onGeneScreens} onFollow={() => setOpen(false)} />}
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
