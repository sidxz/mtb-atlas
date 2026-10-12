# `/ask` on a public site — design

_2026-10-12. Decided with Sid in conversation before hosting at TAMU: anonymous
asks are rate-limited per IP behind a CAPTCHA, ORCID sign-in raises the limit,
and a site-wide ceiling bounds the bill whatever happens._

## Why

`/ask` is the only route that costs money. Today it is an unauthenticated POST
that spends the server's Anthropic key on whatever arrives, with the effort level
chosen by the caller. On a public URL that is an open tab on the bill. Every
other route reads the store and costs nothing, and none of them changes here.

## The rules

| Who | Limit | Window | CAPTCHA |
|---|---|---|---|
| Anonymous | 5 asks per IP | rolling 1 h | Cloudflare Turnstile, every ask |
| Signed in with ORCID | 20 asks per ORCID iD | rolling 24 h | none — ORCID is the proof |
| Everyone together | 500 asks | rolling 24 h | — |

- The ORCID limit **replaces** the IP limit; it does not stack. A lab behind one
  NAT address must not block itself.
- **Effort is fixed at `high`** on the server. `Question.effort` is removed, so a
  direct API caller cannot buy `xhigh`. The UI never sent it, so the page
  behaves exactly as before.
- An ask is counted when it is **admitted**, before the model is called. A model
  error does not refund it; a refusal (CAPTCHA failed, over a limit) never
  counts.
- Over any limit is **429** with a `Retry-After` header and a body naming which
  limit (`ip`, `orcid` or `global`) and when the next ask is admitted.

## Components

### `atlas/ask_access.py` — the limiter, the CAPTCHA check, the session

One module, three small jobs, no FastAPI imports in the counting so it can be
tested on its own.

**Usage store.** SQLite (`sqlite3`, stdlib) at `data/ask_usage.sqlite`, gitignored,
one table:

```sql
CREATE TABLE IF NOT EXISTS asks (key TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS asks_key_at ON asks (key, at);
```

`key` is `ip:<hex HMAC-SHA256(ATLAS_SECRET, ip)>` or `orcid:<iD>`. **An IP is
never written in clear.** `admit(key, limit, window, now)` runs in one
`BEGIN IMMEDIATE` transaction: delete rows older than 24 h, count the key's rows
inside its window and all rows inside 24 h, and insert only if both are under
their limits. `BEGIN IMMEDIATE` takes SQLite's write lock up front, so two
workers racing on the last slot cannot both get it. The clock is a parameter so
tests do not sleep.

The store is not the Parquet store and is not written by the pipeline;
`make build`, `check`, `refresh` and `diff` never touch it.

**Turnstile.** `verify_turnstile(token, ip)` POSTs to
`https://challenges.cloudflare.com/turnstile/v0/siteverify` with the secret,
the token and `remoteip`, through `httpx` (already a dependency) with a 5 s
timeout. Any failure — bad token, network error, Cloudflare down — is a refusal
(403), never an admission. Tokens are single-use, so each anonymous ask carries
a fresh one and **anonymous users get no cookie**.

**Session.** A cookie `atlas_session` = `<orcid>|<expiry epoch>|<hex HMAC>`,
signed with `hmac` (stdlib) under `ATLAS_SECRET`; `HttpOnly`, `Secure`,
`SameSite=Lax`, `Path=/`, 30 days. No server-side session table. The only thing
held about a person is the ORCID iD: no name, no email, no token. A cookie whose
HMAC fails or whose expiry has passed is treated as absent, not as an error.

### ORCID sign-in — three routes in `atlas/api.py`

- `GET /auth/orcid/login` — sets a short-lived signed `atlas_oauth_state`
  cookie (CSRF state, 10 min) and redirects to
  `https://orcid.org/oauth/authorize?client_id=…&response_type=code&scope=/authenticate&redirect_uri=<ATLAS_PUBLIC_URL>/api/auth/orcid/callback&state=…`.
- `GET /auth/orcid/callback` — checks `state` against the cookie, POSTs the code
  to `https://orcid.org/oauth/token`, reads `orcid` from the response, discards
  the access token and the name, sets `atlas_session`, and redirects to
  `<ATLAS_PUBLIC_URL>/ask`. A failed exchange redirects to `/ask?signin=failed`.
- `POST /auth/logout` — clears the cookie.
- `GET /auth/me` — `{orcid: str | null, remaining: int, limit: int, window: "1h" | "24h",
  global_remaining: int, turnstile_site_key: str | null, signin_available: bool,
  limits: bool}`, so the page can show "3 of 5 left this hour" and knows what to render.

`ORCID_BASE` defaults to `https://orcid.org` and can point at
`https://sandbox.orcid.org` for testing against ORCID's sandbox.

### `/ask` itself

Order of checks, cheapest and most decisive first:

1. Limits switched off (`ATLAS_ASK_LIMITS=off`) → straight to the model, as today.
2. Configuration incomplete for this caller → **503**, never an unprotected ask.
3. Valid session → `admit("orcid:<iD>", 20, 24 h)`.
4. Otherwise → `verify_turnstile(header X-Turnstile-Token)` (403 on failure),
   then `admit("ip:<hash>", 5, 1 h)`.
5. Admitted → `agent.ask(question, effort="high")`.

The client IP is `request.client.host`. Behind TAMU's reverse proxy, uvicorn
must run with `--proxy-headers --forwarded-allow-ips=<proxy address>` so that
is the visitor and not the proxy; otherwise every visitor shares one bucket of
5. That is deployment configuration and goes in the README's hosting notes, not
in code.

CORS stays `GET` only. `/ask` is a same-origin POST from the page; the
`SameSite=Lax` session cookie is not sent on a cross-site POST, so another site
cannot spend a signed-in user's allowance.

### Configuration

| Variable | Needed for | If missing |
|---|---|---|
| `ANTHROPIC_API_KEY` | any ask | 503, as today |
| `ATLAS_SECRET` | IP hashing, cookie signing | 503 for every ask |
| `TURNSTILE_SITE_KEY` | the page's widget (served by `/auth/me`) | anonymous asks 503 |
| `TURNSTILE_SECRET_KEY` | siteverify | anonymous asks 503 |
| `ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET` | sign-in | sign-in link hidden; anonymous still works |
| `ATLAS_PUBLIC_URL` | ORCID redirect URI | sign-in hidden |
| `ATLAS_ASK_LIMITS=off` | local development | — (default is on) |

**Missing configuration fails closed.** A deploy that forgot the Turnstile
secret must refuse anonymous asks, not serve them unprotected. For local
development Cloudflare publishes always-pass test keys
(`1x00000000000000000000AA` / `1x0000000000000000000000000000000AA`), or
`ATLAS_ASK_LIMITS=off` skips the whole layer.

The ORCID public API client is registered by a person (Sid), free, at
orcid.org → Developer tools, with the redirect URI above. It cannot be done
from code.

### `web/src/Ask.tsx`

- On mount, `GET /auth/me` for the counter, the site key and whether sign-in is
  available.
- Anonymous: load `https://challenges.cloudflare.com/turnstile/v0/api.js` on
  first open of the view (not in `index.html`, the same lazy rule as RDKit and
  igv), render the widget in invisible/managed mode, and send its token as
  `X-Turnstile-Token`. Reset the widget after each ask, because a token is
  single-use.
- A "Sign in with ORCID for 20 a day" link to `/api/auth/orcid/login`; signed
  in, the iD and a sign-out button.
- "N left this hour / today" beside the input. On 429, the time of the next
  admitted ask and, if anonymous, the sign-in link. On a global 429, say it is
  the site-wide limit, so nobody thinks it is theirs.

No new npm dependency: the Turnstile script is loaded by URL and driven through
its `window.turnstile` API.

## Privacy consequences

These go into the privacy notice (open point 8 of the release checklist):

- Turnstile sends browser signals to **Cloudflare** when an anonymous user opens
  the Ask view. Nothing loads from Cloudflare on any other view.
- Signing in goes through **ORCID**; the atlas keeps the iD only.
- `atlas_session` is a **strictly necessary** cookie, set only on sign-in, so no
  consent banner is required. Anonymous users get no cookie.
- Usage rows keep an **HMAC of the IP**, never the IP, and are deleted after
  24 h.
- Questions go to **Anthropic** to be answered; the atlas does not log them.

## Testing

`tests/test_ask_access.py`, fixtures only, no network (Turnstile and ORCID's
token endpoint are monkeypatched):

- 5 anonymous asks in an hour admitted, the 6th is 429 `ip`; at +61 min admitted again.
- A signed-in iD gets 20 in 24 h regardless of IP; the 21st is 429 `orcid`.
- The 501st ask in 24 h is 429 `global` for a signed-in user too.
- A failed or missing Turnstile token is 403 and **is not counted**.
- Two threads racing on the last slot: exactly one is admitted.
- A tampered, expired or wrongly-signed cookie is anonymous, not an error.
- The OAuth callback rejects a `state` that does not match its cookie.
- Missing `TURNSTILE_SECRET_KEY` with limits on: anonymous ask is 503.
- A request body carrying `"effort": "xhigh"` runs at `high`.
- The usage file holds no IP in clear.
- `ATLAS_ASK_LIMITS=off` admits without touching the store.

The agent's own sandbox tests are untouched.

## Not in this design

- Per-user history of questions, accounts beyond ORCID, an admin page. Read the
  SQLite file if a number is needed.
- Refunding an ask on a model error. Add it if failures turn out to be common.
- Any change to the non-`/ask` routes; their rate limiting belongs at the
  reverse proxy.
