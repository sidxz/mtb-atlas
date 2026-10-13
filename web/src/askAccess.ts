/**
 * The words around /ask's allowance. Pure, so the sentences are tested rather
 * than eyeballed; Ask.tsx only places them.
 */
import type { Me, Meta } from "./api";

export function allowanceLabel(me: Me): string | null {
  if (!me.limits || me.remaining === null) return null;
  return `${me.remaining} of ${me.limit} left ${me.window === "1h" ? "this hour" : "today"}`;
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
      return `The atlas has answered ${a ? `its ${a.global_per_day} questions` : "all the questions it takes"} for today, across everyone. The next is admitted at ${when}.`;
    case "orcid":
      return `You have used ${a ? `your ${a.signed_in_per_day} questions` : "your questions"} for today. The next is admitted at ${when}.`;
    case "ip": {
      const offer = me?.signin_available ? `, or ${signInOffer(me).replace("Sign in", "sign in")}` : "";
      return `You have used the ${a ? `${a.anonymous_per_hour} questions an hour` : "questions"} allowed without signing in. The next is admitted at ${when}${offer}.`;
    }
    default:
      return "The question was not admitted. Try again shortly.";
  }
}

export function signInOffer(me: Me | null): string {
  return me?.allowances ? `Sign in with ORCID for ${me.allowances.signed_in_per_day} a day` : "Sign in with ORCID";
}

/** Where a question goes, as the deployer configured it; for the privacy page and notice. */
export function questionDestination(meta: Meta | null): string {
  return meta?.site.llm?.label ?? "the model service this site is configured with";
}

export function captchaUnavailableMessage(signinAvailable: boolean): string {
  const base =
    "The human check could not load, so questions cannot be asked anonymously from this browser. A privacy extension blocking challenges.cloudflare.com is the usual cause.";
  return signinAvailable ? `${base} Signing in with ORCID skips the check.` : base;
}
