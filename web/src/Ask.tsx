/**
 * Natural-language questions over the store.
 *
 * The SQL the agent ran is shown next to the answer, always, not behind a
 * disclosure. An answer about drug targets that cannot be checked is not worth
 * having, and the query is the shortest way to check one.
 */

import { useState } from "react";

const EXAMPLES = [
  "Which essential genes have a structure, no ligands, and no close human homolog?",
  "What is known about Rv0206c, and what is missing?",
  "Which genes are most vulnerable by CRISPRi but have no chemical matter at all?",
  "Compare dprE1 and inhA on every kind of evidence the atlas holds.",
];

interface Result {
  answer: string;
  queries: { tool: string; sql: string | null; rows: number | null; error: string | null }[];
}

export function Ask({ base }: { base: string }) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [state, setState] = useState<"idle" | "asking" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const submit = async (text: string) => {
    if (!text.trim()) return;
    setState("asking");
    setResult(null);
    setError(null);
    try {
      const response = await fetch(`${base}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? `${response.status}`);
      setResult(body as Result);
      setState("idle");
    } catch (caught: unknown) {
      setError(String(caught instanceof Error ? caught.message : caught));
      setState("error");
    }
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
        <input
          className="search"
          value={question}
          placeholder="Ask the atlas — answers cite the records they came from"
          onChange={(event) => setQuestion(event.target.value)}
        />
        <button className="iconbtn" type="submit" disabled={state === "asking"}>
          {state === "asking" ? "Asking…" : "Ask"}
        </button>
      </form>

      {!result && state === "idle" && !error && (
        <div className="askexamples">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
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

      {state === "asking" && <p className="note">Querying the store…</p>}

      {error && (
        <div className="caveat">
          {error.includes("credentials")
            ? "The agent needs Anthropic credentials. Set ANTHROPIC_API_KEY where the API runs; everything else in the atlas works without it."
            : error}
        </div>
      )}

      {result && (
        <div className="askresult">
          <div className="answer">{result.answer}</div>
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
  );
}
