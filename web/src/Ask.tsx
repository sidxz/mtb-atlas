/**
 * Natural-language questions over the store.
 *
 * The SQL the agent ran is shown next to the answer, always, not behind a
 * disclosure. An answer about drug targets that cannot be checked is not worth
 * having, and the query is the shortest way to check one.
 */

import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { InterfaceIcon } from "./InterfaceIcon";

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
}

export function Ask({ base }: { base: string }) {
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
                  <details open>
                    <summary>
                      {result.queries.length} quer{result.queries.length === 1 ? "y" : "ies"} behind this
                      answer
                    </summary>
                    {result.queries.map((query, index) => (
                      <div className="askquery" key={index}>
                        {query.sql ? <pre>{query.sql}</pre> : <span className="dim">{query.tool}</span>}
                        <span className="faint">
                          {query.error ? `error: ${query.error}` : `${query.rows ?? 0} rows`}
                        </span>
                      </div>
                    ))}
                  </details>
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
