/**
 * The words around /ask's allowance. Pure, so the sentences are tested rather
 * than eyeballed; Ask.tsx only places them.
 */
import type { Me } from "./api";

export function allowanceLabel(me: Me): string | null {
  if (!me.limits || me.remaining === null) return null;
  return `${me.remaining} of ${me.limit} left ${me.window === "1h" ? "this hour" : "today"}`;
}

const clock = (at: Date) => at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** A 429's `detail` as a sentence. Anything unexpected still reads as text. */
export function refusalMessage(detail: unknown, now: Date): string {
  if (typeof detail === "string") return detail;
  const d = (detail ?? {}) as { limit?: unknown; retry_after?: unknown };
  const seconds = typeof d.retry_after === "number" ? d.retry_after : 0;
  const when = clock(new Date(now.getTime() + seconds * 1000));
  switch (d.limit) {
    case "global":
      return `The atlas has answered its 500 questions for today, across everyone. The next is admitted at ${when}.`;
    case "orcid":
      return `You have used your 20 questions for today. The next is admitted at ${when}.`;
    case "ip":
      return `You have used the 5 questions an hour allowed without signing in. The next is admitted at ${when}, or sign in with ORCID for 20 a day.`;
    default:
      return "The question was not admitted. Try again shortly.";
  }
}

export function captchaUnavailableMessage(signinAvailable: boolean): string {
  const base =
    "The human check could not load, so questions cannot be asked anonymously from this browser. A privacy extension blocking challenges.cloudflare.com is the usual cause.";
  return signinAvailable ? `${base} Signing in with ORCID skips the check.` : base;
}
