/**
 * Natural-language questions over the store.
 *
 * The answer takes the full width. The SQL behind it still comes back from
 * /ask (`queries`) and is not drawn here.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link, useLocation } from "react-router";
import { InterfaceIcon } from "./InterfaceIcon";
import { api, type Hit, type Me, type SearchResults } from "./api";
import { allowanceLabel, captchaUnavailableMessage, refusalMessage, signInOffer } from "./askAccess";

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

declare global {
  interface Window {
    turnstile?: {
      render(element: HTMLElement, options: Record<string, unknown>): string;
      reset(widget?: string): void;
      remove(widget?: string): void;
    };
  }
}

// Loaded on the first focus of the Ask input, never in index.html: nobody who
// does not ask sends anything to Cloudflare. A failed load can be retried.
let turnstileScript: Promise<void> | null = null;
function loadTurnstile(): Promise<void> {
  turnstileScript ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      turnstileScript = null;
      reject(new Error("turnstile"));
    };
    document.head.appendChild(script);
  });
  return turnstileScript;
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

  const location = useLocation();
  const [me, setMe] = useState<Me | null>(null);
  const [captchaFailed, setCaptchaFailed] = useState(false);
  const widgetHost = useRef<HTMLDivElement | null>(null);
  const widget = useRef<string | null>(null);
  const token = useRef<string | null>(null);

  const refreshMe = useCallback(() => api.me().then(setMe).catch(() => setMe(null)), []);
  useEffect(() => { void refreshMe(); }, [refreshMe]);

  const needsCaptcha = Boolean(me?.limits && !me.orcid && me.turnstile_site_key);

  const startCaptcha = useCallback(() => {
    if (!needsCaptcha || widget.current || !widgetHost.current) return;
    loadTurnstile()
      .then(() => {
        if (!window.turnstile || !widgetHost.current || widget.current) return;
        widget.current = window.turnstile.render(widgetHost.current, {
          sitekey: me!.turnstile_site_key,
          // Shown only when Cloudflare needs the visitor to do something.
          appearance: "interaction-only",
          callback: (value: string) => { token.current = value; },
          "expired-callback": () => { token.current = null; },
          "error-callback": () => { token.current = null; setCaptchaFailed(true); },
        });
        setCaptchaFailed(false);
      })
      .catch(() => setCaptchaFailed(true));
  }, [needsCaptcha, me]);

  // A first-focus race: focus can precede /auth/me, and /auth/me can fail and arrive later.
  useEffect(() => { if (focused) startCaptcha(); }, [focused, startCaptcha]);

  // `next` must not carry signin=failed, or a successful retry lands on a page still saying it failed.
  const nextParams = new URLSearchParams(location.search);
  const signinFailed = nextParams.get("signin") === "failed";
  nextParams.delete("signin");
  const nextSearch = nextParams.toString();
  const signInHref = `${base}/auth/orcid/login?next=${encodeURIComponent(location.pathname + (nextSearch ? `?${nextSearch}` : ""))}`;
  const signOut = async () => {
    await fetch(`${base}/auth/logout`, { method: "POST" });
    void refreshMe();
  };

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
    let sent = false;
    try {
      if (needsCaptcha && !token.current) {
        throw new Error(captchaFailed ? captchaUnavailableMessage(Boolean(me?.signin_available)) : "One moment: the human check is still running. Ask again in a few seconds.");
      }
      sent = true;
      const response = await fetch(`${base}/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token.current ? { "X-Turnstile-Token": token.current } : {}),
        },
        body: JSON.stringify({ question: text }),
        signal: controller.signal,
      });
      let body: { detail?: unknown };
      try {
        body = await response.json();
      } catch {
        throw new Error(`The atlas could not answer (HTTP ${response.status}). Try again shortly.`);
      }
      if (!response.ok) {
        throw new Error(response.status === 429 ? refusalMessage(body.detail, new Date(), me) : (typeof body.detail === "string" ? body.detail : `${response.status}`));
      }
      setResult(body as Result);
      setState("idle");
    } catch (caught: unknown) {
      if (controller.signal.aborted) return;
      setError(String(caught instanceof Error ? caught.message : caught));
      setState("error");
    } finally {
      // A token is single-use: whatever happened, the next ask needs a fresh one.
      if (sent) {
        token.current = null;
        if (widget.current) window.turnstile?.reset(widget.current);
        void refreshMe();
      }
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
          onFocus={() => { setFocused(true); startCaptcha(); }}
          onBlur={() => setFocused(false)}
        />
        <button className="iconbtn" type="submit" disabled={state === "asking"}>
          {state === "asking" ? "Asking…" : "Ask"}
        </button>
      </form>

      {me && (needsCaptcha || allowanceLabel(me) || me.orcid || me.signin_available || signinFailed) && (
      <div className="askaccess">
        {needsCaptcha && <div ref={widgetHost} className="askaccess-captcha" />}
        {me && allowanceLabel(me) && <span className="faint">{allowanceLabel(me)}</span>}
        {me?.orcid ? (
          <>
            <a href={`https://orcid.org/${me.orcid}`} target="_blank" rel="noreferrer">{me.orcid}</a>
            <button type="button" className="linkbtn" onClick={() => void signOut()}>Sign out</button>
          </>
        ) : me?.signin_available ? (
          <a href={signInHref}>{signInOffer(me)}</a>
        ) : null}
        {signinFailed && (
          <span className="caveat-inline">ORCID sign-in did not complete.</span>
        )}
      </div>
      )}

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
                <div className="caveat">{error}</div>
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
