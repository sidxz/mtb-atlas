# Public release — design

_2026-10-12. Decided with Sid in conversation before hosting the atlas publicly
(first at TAMU, on the `ned` swarm). Three parts: `/ask` gets an allowance
instead of an open tab on the bill; the atlas ships as **one universal image**
that anyone can run, with nothing site-specific baked in; and the site says
plainly what it stores, what it sends where, and whose data it shows._

## Part 1 — `/ask` access

### Why

`/ask` is the only route that costs money. Today it is an unauthenticated POST
that spends the server's Anthropic key on whatever arrives, with the effort level
chosen by the caller. On a public URL that is an open tab on the bill. Every
other route reads the store and costs nothing, and none of them changes here.

### The rules

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

### `atlas/ask_access.py` — the limiter, the CAPTCHA check, the session

One module, three small jobs, no FastAPI imports in the counting so it can be
tested on its own.

**Usage store.** SQLite (`sqlite3`, stdlib) at `ATLAS_USAGE_DB`, default
`data/ask_usage.sqlite` (gitignored), one table:

```sql
CREATE TABLE IF NOT EXISTS asks (key TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS asks_key_at ON asks (key, at);
```

`key` is `ip:<hex HMAC-SHA256(ATLAS_SECRET, ip)>` or `orcid:<iD>`. **An IP is
never written in clear.** `admit(key, limit, window, now)` runs in one
`BEGIN IMMEDIATE` transaction: delete rows older than 24 h, count the key's rows
inside its window and all rows inside 24 h, and insert only if both are under
their limits. `BEGIN IMMEDIATE` takes SQLite's write lock up front, so two
threads racing on the last slot cannot both get it. The clock is a parameter so
tests do not sleep.

In the container the file is container-local, not on a shared volume: a
redeploy resets the counts, the global 500 included. For 24 h windows that is
harmless, and it keeps SQLite off NFS, where its locking is not to be trusted.
Marked in code with a `ponytail:` comment naming that ceiling.

The usage store is not the Parquet store and is not written by the pipeline;
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

### ORCID sign-in — routes in `atlas/api.py`

- `GET /auth/orcid/login?next=<path>` — sets a short-lived signed
  `atlas_oauth_state` cookie (CSRF state plus the return path, 10 min) and
  redirects to
  `<ORCID_BASE>/oauth/authorize?client_id=…&response_type=code&scope=/authenticate&redirect_uri=<ATLAS_PUBLIC_URL>/api/auth/orcid/callback&state=…`.
  `next` must be a relative path starting with a single `/`; anything else
  becomes `/`, so the sign-in cannot be used as an open redirect.
- `GET /auth/orcid/callback` — checks `state` against the cookie, POSTs the code
  to `<ORCID_BASE>/oauth/token`, reads `orcid` from the response, discards the
  access token and the name, sets `atlas_session`, and redirects to the saved
  path. A failed exchange redirects there with `?signin=failed`.
- `POST /auth/logout` — clears the cookie.
- `GET /auth/me` — `{orcid: str | null, remaining: int, limit: int,
  window: "1h" | "24h", global_remaining: int, turnstile_site_key: str | null,
  signin_available: bool, limits: bool}`, so the page can show "3 of 5 left this
  hour" and knows what to render.

`ORCID_BASE` defaults to `https://orcid.org` and can point at
`https://sandbox.orcid.org`.

### `/ask` itself

Order of checks, cheapest and most decisive first:

1. Limits switched off (`ATLAS_ASK_LIMITS=off`) → straight to the model, as today.
2. Configuration incomplete for this caller → **503**, never an unprotected ask.
3. Valid session → `admit("orcid:<iD>", 20, 24 h)`.
4. Otherwise → `verify_turnstile(header X-Turnstile-Token)` (403 on failure),
   then `admit("ip:<hash>", 5, 1 h)`.
5. Admitted → `agent.ask(question, effort="high")`.

The client IP is `request.client.host`, which is the visitor only if uvicorn
trusts the proxy in front of it. uvicorn reads proxy headers by default and
takes the list of trusted proxies from `FORWARDED_ALLOW_IPS` (its own env var,
CIDR ranges accepted; the plan pins a uvicorn version that supports them). Set
wrong, every visitor shares one bucket of 5 — so the deployment docs say so.

CORS stays `GET` only. `/ask` is a same-origin POST from the page; the
`SameSite=Lax` session cookie is not sent on a cross-site POST, so another site
cannot spend a signed-in user's allowance.

### `web/src/Ask.tsx`

- On mount, `GET /auth/me` for the counter, the site key and whether sign-in is
  available.
- Anonymous: load `https://challenges.cloudflare.com/turnstile/v0/api.js` on the
  **first focus of the Ask input** (not in `index.html`; the same lazy rule as
  RDKit and igv), render the widget in managed mode, and send its token as
  `X-Turnstile-Token`. Reset the widget after each ask, because a token is
  single-use.
- A "Sign in with ORCID for 20 a day" link to
  `/api/auth/orcid/login?next=<current path>`; signed in, the iD (linked to
  `https://orcid.org/<iD>`) and a sign-out button.
- "N left this hour / today" beside the input. On 429, the time of the next
  admitted ask and, if anonymous, the sign-in link. On a global 429, say it is
  the site-wide limit, so nobody thinks it is theirs.

No new npm dependency: the Turnstile script is loaded by URL and driven through
its `window.turnstile` API.

## Part 2 — one universal image

### Shape

**One container** serves the API and the built frontend. A new entry point,
`atlas/serve.py`, is an ASGI app that mounts the existing `atlas.api:app` at
`/api` and serves `web/dist` at `/`, with a fallback to `index.html` for any
path that is not a file, so React Router's paths (`/genome/Rv3790`) survive a
reload. Hashed files under `/assets/` get a one-year immutable cache header;
`index.html` gets `no-cache`. `GZipMiddleware` compresses.

The frontend already calls the relative `/api`, so **no host name is compiled
into the bundle**. Everything site-specific reaches the browser at runtime
through `/auth/me`.

Development does not change: `make api` + `make web`, with Vite's proxy.

### Nothing site-specific in the image

| Variable | Purpose | Default |
|---|---|---|
| `ATLAS_STORE` | where the Parquet store is mounted | `data/store` (as today) |
| `ATLAS_USAGE_DB` | the `/ask` counters | `data/ask_usage.sqlite` |
| `FORWARDED_ALLOW_IPS` | uvicorn's trusted proxies | `127.0.0.1` (uvicorn's) |
| `ANTHROPIC_API_KEY` | any ask | none → `/ask` 503 |
| `ATLAS_SECRET` | IP hashing, cookie signing | none → every ask 503 |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | anonymous asks | none → anonymous 503 |
| `ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET`, `ORCID_BASE` | sign-in | none → sign-in hidden |
| `ATLAS_PUBLIC_URL` | ORCID redirect URI | none → sign-in hidden |
| `ATLAS_ASK_LIMITS` | `off` for local development | on |
| `ATLAS_OPERATOR` | who runs this instance, shown on the privacy page | none → "the operator of this site" |
| `ATLAS_CONTACT` | a contact address, shown on the privacy page | none → omitted |

`ATLAS_STORE` is new: `atlas/fetch.py` fixes `STORE` at `ROOT / "data" / "store"`
today, and it becomes `Path(os.environ.get("ATLAS_STORE", ROOT / "data" / "store"))`.
The pipeline keeps writing where it always has.

**Missing configuration fails closed.** A deploy that forgot the Turnstile
secret refuses anonymous asks rather than serving them unprotected. For local
work Cloudflare publishes always-pass test keys (`1x00000000000000000000AA` /
`1x0000000000000000000000000000000AA`), or `ATLAS_ASK_LIMITS=off` skips the
layer.

### The store is never in the image

The image holds code only. The store is mounted read-only at `ATLAS_STORE`.

- **Licensing.** A public image with the store inside would publish the whole
  store as Parquet to anyone who pulls it — Mycobrowser's loci and PubChem's
  per-compound results among it. Serving records one page at a time is a
  narrower act than handing out the database, and two of those licence
  questions are still open.
- **The update policy.** A store built in CI is a store nobody read the diff
  of. `atlas refresh` + `atlas diff` stay on a machine with a person at it; the
  store travels separately and a data refresh never needs a new image.

### Image and CI

- `Dockerfile` at the repo root, two stages: `node:22-alpine` builds `web/`,
  then `python:3.12-slim` with `uv` installs the package (no dev extras) and
  copies `web/dist`. Runs as a non-root user, `EXPOSE 8099`, `HEALTHCHECK` on
  `/api/meta` (python, since the slim image has no curl), `CMD uvicorn
  atlas.serve:app --host 0.0.0.0 --port 8099`. One uvicorn process: the API's
  DuckDB instance and hit-profile cache are per process by design (CLAUDE.md,
  "The agent").
- `.dockerignore` keeps `data/`, `.venv`, `node_modules`, `poc/` and `tests/`
  out of the build context.
- `.github/workflows/publish-image.yml`, after chem-cellar's: `linux/amd64`,
  GHCR via `GITHUB_TOKEN`, `docker/metadata-action` tags — `latest` and
  `sha-<sha>` on `main`, `X.Y.Z`/`X.Y`/`X` on a `vX.Y.Z` tag, a GitHub Release
  on a tag. GHA layer cache. One image, one version: the API and the page are
  released together from one repo, so chem-cellar's per-component namespaces
  are not needed.
- `docker-compose.prod.yml` + `.env.example` in the repo: one service, the store
  bind-mounted read-only, port 8099. Anyone's deploy is
  `make build && docker compose -f docker-compose.prod.yml up`.

### On ned — `149-atlas/` in `snet2-infrastructure`

Not in this repo; written alongside it, following `147-prot-cellar`.

- `atlas.yml`: one service, `ghcr.io/sidxz/mtb-atlas:${VERSION}`, on
  `traefik-public`, standard on-premises worker placement, Traefik routers for
  `Host(\`atlas.snet.biobio.tamu.edu\`)` (http → https redirect, TLS), port
  8099, memory limit 3 G. The store mounted read-only from
  `/net-fs-ins/docker-vols/atlas/store`. `FORWARDED_ALLOW_IPS=172.16.50.0/24`,
  the `traefik-public` subnet: Traefik binds 80/443 in host mode, so it sees
  the real visitor and passes it on.
- `.env.enc` (SOPS): `VERSION`, `ATLAS_PUBLIC_URL`, the Anthropic, Turnstile and
  ORCID credentials, `ATLAS_SECRET`, `ATLAS_OPERATOR`, `ATLAS_CONTACT`.
- `atlas_deploy.sh deploy | remove | store <local store dir>`. `store` copies a
  locally built and diffed store to NFS through a throwaway container, keeps
  the previous one as `store.prev` (the same convention as `atlas refresh`),
  and forces a service update so the API reopens it.
- Before launch, confirm with TAMU IT that `*.snet.biobio.tamu.edu` is reachable
  from outside the campus network; "open to all" depends on it.

## Part 3 — what the site tells its visitors

### Cookies and storage, as they will be

| What | Set when | Why | Kind |
|---|---|---|---|
| `atlas_session` cookie | signing in with ORCID | keeps you signed in, 30 days | strictly necessary |
| `atlas_oauth_state` cookie | during sign-in only, 10 min | protects the sign-in from forgery | strictly necessary |
| `localStorage` table preferences | changing a table's columns | remembers your columns | your own setting |
| `localStorage` notice dismissal | dismissing the notice below | not showing it again | your own setting |

No analytics, no advertising, no tracking cookie. Under the ePrivacy rules
strictly necessary cookies and a visitor's own settings need no consent, so
there is **no consent banner** — a banner that asks permission for nothing
would teach people to click through banners.

### The notice

A one-line, non-blocking notice at the foot of the page on first visit:

> This site sets no cookies unless you sign in with ORCID, and has no analytics.
> Asking a question sends it to Anthropic, and anonymous questions are checked by
> Cloudflare. [Privacy & cookies] [OK]

Dismissal is remembered in `localStorage` (in `try/catch`; if storage is
blocked the notice just comes back). It is information, not a consent gate:
the site works the same whether or not it is dismissed.

### A footer and three pages

A small footer on every view: **Sources & licences · Privacy & cookies · Terms
& disclaimer**, plus the code licence (MIT) and the repository link. Each page
gets a path, as every "thing open" does: `/about/sources`, `/about/privacy`,
`/about/terms` (`about` joins `VIEWS` in `parseRoute`).

- **Sources & licences** — rendered from `/meta`, which already carries each
  source's version and licence from `LICENCES` in `atlas/api.py`, plus a static
  list of the citation each source asks for (Kapopoulou 2011 for Mycobrowser,
  and the papers behind each screen). States that ChEMBL-derived content is
  CC BY-SA 3.0 and is shared under the same licence, that ClinicalTrials.gov
  data is shown as retrieved on its stated date without NLM endorsement, and
  that PubChem results carry their depositor.
- **Privacy & cookies** — the table above; server logs (IP, path, time, kept by
  the operator's web server); what Cloudflare sees (anonymous asks only); what
  ORCID sees and what the atlas keeps (the iD only); that questions go to
  Anthropic and are not logged by the atlas; the HMAC of the IP and its 24 h
  life; that the structure viewer fetches coordinate files from RCSB in the
  browser; and `ATLAS_OPERATOR` / `ATLAS_CONTACT`. Written so any operator can
  run it unchanged.
- **Terms & disclaimer** — research use; not medical or clinical advice;
  provided as is, without warranty; an absent record is a statement about the
  public record, not about the biology (the atlas's own first rule, stated to
  the reader); `/ask` answers are generated and must be checked against the
  rows it cites.

An institution's own required links (TAMU's site policies, accessibility
statement and the like) are not baked in; `ATLAS_FOOTER_LINKS`, a JSON list of
`{label, url}`, adds them at runtime through `/meta`.

### Housekeeping that ships with it

- **Inter is self-hosted.** `index.html` stops loading Google Fonts, which sent
  every visitor's IP to Google; the font files come from `@fontsource/inter`
  and are served by the atlas itself.
- **`LICENSE`** (MIT) at the repo root, which the README already claims.

## Testing

`tests/test_ask_access.py`, fixtures only, no network (Turnstile and ORCID's
token endpoint are monkeypatched):

- 5 anonymous asks in an hour admitted, the 6th is 429 `ip`; at +61 min admitted again.
- A signed-in iD gets 20 in 24 h regardless of IP; the 21st is 429 `orcid`.
- The 501st ask in 24 h is 429 `global` for a signed-in user too.
- A failed or missing Turnstile token is 403 and **is not counted**.
- Two threads racing on the last slot: exactly one is admitted.
- A tampered, expired or wrongly-signed cookie is anonymous, not an error.
- The OAuth callback rejects a `state` that does not match its cookie, and a
  `next` of `//evil.example` or `https://…` returns to `/`.
- Missing `TURNSTILE_SECRET_KEY` with limits on: anonymous ask is 503.
- A request body carrying `"effort": "xhigh"` runs at `high`.
- The usage file holds no IP in clear.
- `ATLAS_ASK_LIMITS=off` admits without touching the store.

`tests/test_serve.py`: `/api/meta` reaches the API; `/genome/Rv3790` returns
`index.html`; `/assets/<hashed file>` carries the immutable cache header;
`ATLAS_STORE` moves where the API reads.

CI smoke-tests the built image before pushing it: started with an empty store,
`/` must return `index.html` and `/api/auth/me` must answer (`/api/meta` needs a
store, so it is the container's healthcheck instead). The API's behaviour is
pytest's job, not the smoke test's.

The agent's sandbox tests are untouched.

## Not in this design

- Per-user history of questions, accounts beyond ORCID, an admin page. Read the
  SQLite file if a number is needed.
- Refunding an ask on a model error. Add it if failures turn out to be common.
- Rate limiting the free routes; that belongs at the proxy if it is ever needed.
- chem-cellar's Trivy gate and `/version` endpoint; add them with the first
  tagged release that wants them.
- An accessibility audit (WCAG 2.1 AA) of the genome canvas, igv and the Map.
  It is a release blocker at TAMU and its own piece of work.
- The PubChem depositor-terms review and the Mycobrowser permission email —
  open licence questions, not code.
