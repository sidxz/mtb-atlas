/**
 * The words around /ask's allowance. Pure, so the sentences are tested rather
 * than eyeballed; Ask.tsx only places them.
 */
import type { Me, Meta } from "./api";

export function allowanceLabel(me: Me): string | null {
  if (!me.limits) return null;
  if (me.global_remaining === 0) return "The atlas has reached its daily question limit. Please try again later.";
  if (me.remaining !== 0) return null;
  return `You’ve reached your question limit ${me.window === "1h" ? "for this hour" : "for today"}.`;
}

const clock = (at: Date) => at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/**
 * A 429's `detail` as a sentence. The numbers are this deployment's own (from
 * /auth/me); without them the sentence says nothing it cannot back up.
 */
export function refusalMessage(detail: unknown, now: Date, me: Me | null): string {
  if (typeof detail === "string") return detail;
  const d = (detail ?? {}) as { limit?: unknown; retry_after?: unknown };
  const seconds = typeof d.retry_after === "number" ? d.retry_after : 0;
  const when = clock(new Date(now.getTime() + seconds * 1000));
  const a = me?.allowances;
  switch (d.limit) {
    case "global":
      return `The daily limit${a ? ` of ${a.global_per_day} questions` : ""} across all visitors has been reached. Try again at ${when}.`;
    case "orcid":
      return `You have used ${a ? `your ${a.signed_in_per_day} questions` : "your questions"} for today. Try again at ${when}.`;
    case "ip": {
      const offer = me?.signin_available ? `, or ${signInOffer(me).replace("Sign in", "sign in")}` : "";
      return `You have reached the limit${a ? ` of ${a.anonymous_per_hour} questions an hour` : ""} without signing in. Try again at ${when}${offer}.`;
    }
    default:
      return "Your question could not be submitted. Try again shortly.";
  }
}

export function signInOffer(me: Me | null): string {
  return me?.allowances ? `Sign in with ORCID for ${me.allowances.signed_in_per_day} questions a day` : "Sign in with ORCID";
}

/** Where a question goes, as the deployer configured it; for the privacy page and notice. */
export function questionDestination(meta: Meta | null): string {
  return meta?.site.llm?.label ?? "this site’s configured model service";
}

export function captchaUnavailableMessage(signinAvailable: boolean): string {
  const base =
    "The browser check could not load. Check your connection or allow challenges.cloudflare.com in your browser, then try again.";
  return signinAvailable ? `${base} Signing in with ORCID skips the check.` : base;
}
