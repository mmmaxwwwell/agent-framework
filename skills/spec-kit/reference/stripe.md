# Stripe / Payment Integration Reference

Stripe is a **first-class project dependency** in spec-kit, treated the same way we treat a platform target (Android/iOS/web) — it changes the scaffolding, tasks, and runbook materially. This file is the full knowledge base the interview, plan, and tasks phases use when the user opts into Stripe.

> The initial implementation is Stripe-specific because that's the pattern proven in production. If the project later swaps to a different payment processor (Braintree, Adyen, Paddle), the **shape** documented here — webhook-listener lifecycle scripts, publishable-key dual delivery, env sync, live-key guardrails — transfers directly. Only the SDK names change.

---

## 1. When to scaffold Stripe

### Auto-detection keywords

During the interview phase, scan the user's project description for any of these signals:

- **Commerce**: `ecommerce`, `marketplace`, `storefront`, `shop`, `sell`, `for profit`, `checkout`, `cart`, `order`, `one-time purchase`
- **Subscription / SaaS**: `subscription`, `SaaS`, `paid tier`, `pro plan`, `premium`, `monthly`, `annual`
- **Payments generic**: `payments`, `revenue`, `charge customers`, `billing`, `invoice`
- **Donations / tips**: `donations`, `tips`, `patronage`, `support creators`

If ANY keyword appears, the interview MUST explicitly ask:

> "This project mentions revenue/payments — do you want Stripe integration scaffolded? [y/N]"

Default: **No**. Do not scaffold Stripe by inference — always require explicit confirmation. Record the answer in `interview-notes.md` under `Payment integration: stripe | none`.

### What "yes" means

The user is opting into all of the following at once:
- Scripts, flake entry, env scaffolding, webhook handler contract docs, publishable-key delivery contract, CLAUDE.md stanza, test/e2e README stanza, RUNBOOK stanza, task-deps registration, live-key guardrails.

There is no partial Stripe integration. If the user wants something smaller (e.g., "just list prices, no server-side payments") the interview should still ask — then scaffold the full pattern anyway so the webhook secret rotation doesn't bite them later. It costs almost nothing and the alternative is scattered half-implementations.

---

## 2. The mental model

Stripe integration has **three moving pieces** that every agent needs to understand:

1. **Secret key** (`sk_test_…`/`sk_live_…`) — server-side only. Never in client bundles. Used by the API to call Stripe's REST API.
2. **Publishable key** (`pk_test_…`/`pk_live_…`) — safe to embed in web/mobile clients. Used by Stripe.js / Stripe Mobile SDKs to tokenize cards before they hit your server.
3. **Webhook signing secret** (`whsec_…`) — rotates **per dev session**. Stripe uses it to sign webhook payloads; your API uses it to verify signatures. **In dev, this is ephemeral** — every time you run `stripe listen` you get a new one. In prod, you register an endpoint in the Stripe dashboard and get one persistent `whsec_…` per endpoint.

Because the dev webhook secret rotates every session, we manage it with scripts rather than expecting the user to copy-paste from CLI output. The lifecycle scripts below are the operational discipline that makes this automation reliable.

---

## 3. Generated bundle

When the user says yes to Stripe, generate **all of these** into the project. Do not pick and choose — the bundle is one indivisible pattern.

### 3.1 Scripts directory (all chmod +x'd on generation)

Generate the following files under `scripts/` (or the project's conventional scripts directory). All scripts must be stack-agnostic bash — no Node/Python/etc. dependencies beyond the stripe CLI, `awk`, `grep`, standard POSIX tools.

#### `scripts/stripe-listen-start.sh`

Idempotent start script. Contract:

- Accepts `--forward-to URL` flag (default: `localhost:3000/webhooks/stripe` — adjust to the project's API port/route at generation time).
- Verifies `stripe` CLI is on PATH; errors with a clear "enter nix develop first" message.
- Verifies `stripe login` has been completed (runs `stripe config --list` and checks for configured keys).
- **Reuse path**: if `.dev/stripe-listen.pid` exists and the PID is a live `stripe listen` process (verified via `/proc/<pid>/cmdline` when available), re-fetch the secret, update `.env`, return `"reused": true`.
- **Stale cleanup**: if the PID file exists but the process is dead or isn't a stripe listener, remove the stale file and start fresh.
- **Fresh start**: call `stripe listen --print-secret` to get the session's whsec, write it to root `.env` as `STRIPE_WEBHOOK_SECRET` (create `.env` from `.env.example` if it doesn't exist, replace the line in place if it exists), then start `stripe listen --forward-to <URL>` via `nohup` with output redirected to `.dev/stripe-listen.log`.
- After start, sleep 1s and verify the process is still alive and is actually a stripe listener — abort with logs on failure.
- Prints a single JSON line to stdout: `{"pid": N, "secret": "whsec_...", "forward_to": "...", "log": "/abs/path/to/log", "reused": bool}`.
- Reference implementation: `scripts/stripe-listen-start.sh` (the kanix project has the canonical version — if regenerating for a new project, copy its structure exactly).

#### `scripts/stripe-listen-stop.sh`

Safe stop script. Contract:

- Reads `.dev/stripe-listen.pid`. If missing, exit 0 with "no listener tracked".
- **Safety check**: verify the PID is actually a `stripe listen` process via `/proc/<pid>/cmdline` before sending SIGTERM. If it's not, refuse to kill it (a PID may have been recycled by an unrelated process).
- SIGTERM, wait up to ~1s for graceful exit, then SIGKILL if still alive.
- Always remove the PID file before attempting the kill so a crashed script doesn't leave a stale reference.

#### `scripts/stripe-webhook-secret.sh`

One-shot secret fetch without starting a background process. Useful when the listener is running elsewhere (e.g., a prod-like dev env) and you just need the secret refreshed in `.env`.

- Same prereq checks as `stripe-listen-start.sh`.
- Runs `stripe listen --print-secret`, writes to `.env` as `STRIPE_WEBHOOK_SECRET`.
- Prints a reminder that the API must be restarted to pick up the new value.

#### `scripts/sync-env.sh`

Single-source-of-truth env copier. Contract:

- Source: root `.env`.
- Destination: the web frontend's `.env` (e.g., `site/.env` for Astro, `web/.env.local` for Next.js, `frontend/.env` for Vite — adjust at generation time).
- Copies only variables matching `^PUBLIC_[A-Z0-9_]+=` (the prefix web bundlers expose to client code). Everything else stays in the root `.env` and the frontend cannot access it.
- Overwrites the destination with a clear "auto-generated" banner.
- Wire this into the frontend's `predev` / `prebuild` npm scripts so developers never run it manually.

**Why two `.env` files?** Web bundlers (Astro, Vite, Next.js, etc.) only read env vars from the frontend's own directory. Running two separate `.env` files quickly diverges (rotate secret in root, forget to update frontend, payments silently break in dev). `sync-env.sh` keeps root canonical and generates the frontend's view of it.

### 3.2 Flake.nix additions

Add `stripe-cli` to the devShell packages list in `flake.nix`:

```nix
devShells.default = pkgs.mkShell {
  packages = with pkgs; [
    # ... existing packages ...
    stripe-cli
  ];
};
```

This ensures every developer and every CI/sandbox environment has the same stripe CLI version. The listen scripts will fail loudly if `stripe-cli` isn't available, directing the user to `nix develop`.

### 3.3 Environment scaffolding (`.env.example`)

Top-of-file banner (prepend if missing):

```
# ==============================================================================
# ENVIRONMENT VARIABLES — NEVER COMMIT .env
#
# This file (.env.example) is committed as a template. Copy it to .env and fill
# in real values. .env is gitignored and MUST stay that way.
#
# For Stripe: use TEST keys only (sk_test_..., pk_test_...) in development.
# LIVE keys (sk_live_..., pk_live_...) belong only in production secrets
# management, never in a developer's .env file and never in a git-tracked file.
# A pre-commit hook blocks commits containing live keys — do not bypass it.
# ==============================================================================
```

Stripe-specific entries (add to the Stripe section):

```
# --- Stripe -------------------------------------------------------------------

# Secret key: server-side only, NEVER in client bundles.
# Dashboard: https://dashboard.stripe.com/test/apikeys
# Use sk_test_... in dev. sk_live_... only in production secret stores.
STRIPE_SECRET_KEY=sk_test_REPLACE_ME

# Publishable key: safe to expose to web/mobile clients. The PUBLIC_ prefix
# tells the bundler (Astro/Vite/Next.js) to ship this to client code. Flows
# to frontends via scripts/sync-env.sh and via the API's /stripe/config endpoint.
PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_REPLACE_ME

# Webhook signing secret: managed by scripts/stripe-listen-start.sh. Rotates
# per `stripe listen` session. Do NOT set this by hand in development —
# the start script will overwrite it. In production, copy the whsec_... from
# the dashboard's endpoint configuration into your secret manager.
STRIPE_WEBHOOK_SECRET=whsec_REPLACE_ME

# Stripe Tax: set to true to have Stripe calculate and collect tax on
# checkouts. Requires Stripe Tax configuration in the dashboard.
STRIPE_TAX_ENABLED=false
```

### 3.4 Webhook handler contract (stack-agnostic)

Write this into `docs/stripe-integration.md` as the webhook contract. Do NOT commit to a specific framework — the agent writing the handler will match it to their stack.

**Endpoint**: `POST /webhooks/stripe`

**Requirements**:

1. **Raw body**: the handler must receive the **unparsed request body** (Buffer/bytes). Signature verification is done over the raw bytes — any JSON parsing, re-serialization, or whitespace normalization breaks the signature.
   - Fastify: register `fastify-raw-body` or set `config: { rawBody: true }` on the route.
   - Express: `app.post('/webhooks/stripe', express.raw({ type: 'application/json' }), handler)` — do NOT apply global `express.json()` before this route.
   - Next.js (pages router): export `config = { api: { bodyParser: false } }`, read with `micro.buffer` or similar.
   - Next.js (app router): call `await request.text()` and pass to `constructEvent`.
   - FastAPI: `await request.body()` in the handler.
   - Other frameworks: research how to disable body parsing for this route.

2. **Signature verification**: extract the `stripe-signature` header, then call the Stripe SDK:
   ```
   event = stripe.webhooks.constructEvent(rawBody, signature, STRIPE_WEBHOOK_SECRET)
   ```
   On failure, return 400 immediately. Do NOT trust any data from the request on failure.

3. **Event handling by type**. Typical commerce events and the actions they trigger:

   | Event | Typical action |
   |-------|---------------|
   | `payment_intent.succeeded` | Transition order from `pending_payment` to `paid`; trigger fulfillment; send receipt email |
   | `payment_intent.payment_failed` | Transition order to `payment_failed`; notify customer; surface retry UI |
   | `payment_intent.requires_action` | Mark order `awaiting_customer_action` (3DS, etc.) |
   | `charge.refunded` | Transition order (or line items) to `refunded` / `partially_refunded`; audit log entry; notify customer |
   | `charge.dispute.created` | Flag order for review; alert admin; preserve all evidence |
   | `charge.dispute.closed` | Update order dispute outcome; reconcile balance |
   | `checkout.session.completed` | If using Stripe Checkout: same effect as `payment_intent.succeeded` at the checkout layer |
   | `customer.subscription.*` | Subscription lifecycle (created, updated, deleted, trial ending) — update customer entitlements |
   | `invoice.payment_failed` | Subscription dunning — notify customer, pause entitlement after retry policy exhausted |

   For each event type the project handles, define an idempotent handler function. Unhandled event types must **log at DEBUG and return 200** — Stripe will otherwise retry indefinitely.

4. **Return 200 quickly** (< 5s). Stripe treats longer responses as failures and retries with exponential backoff, which causes duplicate event delivery. Do heavy work in an async queue (BullMQ, SQS, Pub/Sub, Celery, etc.) and 200 from the webhook immediately after enqueuing.

5. **Idempotency**. The same `event.id` may be delivered multiple times. The handler MUST be idempotent:
   - **Recommended**: a `processed_stripe_events` table with `event_id` as primary key. Insert before handling; if the insert raises a unique-constraint violation, the event was already processed — return 200 without re-running side effects.
   - Alternative: check mutation state before applying (e.g., "is this order already paid? if so, skip"). Harder to reason about in edge cases — prefer the dedupe table.

6. **Error handling within the handler**. If handling fails for a transient reason (DB down, queue full), return **500** so Stripe retries. If it fails for a deterministic reason (malformed event, no such customer), log at ERROR and return 200 — retries won't help and Stripe's retry buffer will back up.

### 3.5 Publishable key delivery contract

Document in `docs/stripe-integration.md`:

**Server endpoint**: `GET /api/<client>/stripe/config` returning `{ "publishableKey": "pk_test_..." }`
- No auth required (the key is public by design — safe to serve to any client)
- Served to both web and mobile clients at runtime
- Same endpoint for admin and customer API surfaces (conventionally `/api/admin/stripe/config` and `/api/customer/stripe/config`, both returning the same key — or share one `/api/stripe/config`)
- Rate-limit at a sane level (it's an unauthenticated endpoint)

**Web frontend fallback**: reads `import.meta.env.PUBLIC_STRIPE_PUBLISHABLE_KEY` (Astro/Vite) or `process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` (Next.js) at build time, flowing from root `.env` via `sync-env.sh`. Runtime fetch is preferred (allows key rotation without redeploys) but build-time is a valid fallback if the fetch fails or the app is offline-capable.

**Mobile fallback**: Flutter uses `--dart-define=STRIPE_PUBLISHABLE_KEY=...` at build time AND fetches `/api/customer/stripe/config` at runtime on app launch. Prefer runtime, fall back to build-time if the server is unreachable (offline mode). Native iOS/Android follow the same dual-path pattern with their respective build-config mechanisms.

**Why dual-path?** Runtime fetch means you can rotate the publishable key without a mobile app store re-release. Build-time fallback means the app still works for offline-first flows and first launches before the server is reached.

### 3.6 CLAUDE.md stanza

Template to append to the project's `CLAUDE.md`:

```markdown
## Stripe integration

### Keys

- Test keys: https://dashboard.stripe.com/test/apikeys (use `sk_test_...` / `pk_test_...`)
- Live keys: only via production secret manager — NEVER in a local `.env` or git-tracked file.
- A pre-commit hook blocks `sk_live_` / `pk_live_` patterns in staged files.

### Dev webhook forwarding workflow

The Stripe CLI signs and forwards webhook events to your local API. The signing secret
rotates per session, so always use the scripts below — never hand-edit
`STRIPE_WEBHOOK_SECRET`.

```bash
# Start listener. Prints JSON {pid, secret, forward_to, log, reused}. Writes
# STRIPE_WEBHOOK_SECRET into root .env. Idempotent — safe to call repeatedly.
scripts/stripe-listen-start.sh

# Restart the API so it reads the new webhook secret from .env.

# ... run tests / exercise flows ...

scripts/stripe-listen-stop.sh
```

See `test/e2e/README.md` for the E2E agent usage pattern.

### Test vs live mode

Always work in test mode locally. The Stripe dashboard has a test/live toggle
in the top navbar — staying in test mode is your guardrail against accidentally
running test flows against real customers.
```

### 3.7 test/e2e/README.md stanza

Template (the kanix `test/e2e/README.md` is the canonical reference — use its structure):

```markdown
## Stripe webhook forwarding

Tests that drive real Stripe payments need `stripe listen` running so webhook
events reach the local API. Orders otherwise stay in `pending_payment` forever
and state assertions fail.

### Agent usage pattern

```bash
RESULT=$(scripts/stripe-listen-start.sh)
PID=$(echo "$RESULT" | jq -r .pid)
SECRET=$(echo "$RESULT" | jq -r .secret)

# (restart API so it reads the new secret from .env)

# ... drive tests ...

scripts/stripe-listen-stop.sh
```

The start script is idempotent — calling it twice detects the existing
listener, re-fetches its secret into `.env`, and returns `"reused": true`.

### First-time setup

1. Stripe account + test API keys from https://dashboard.stripe.com/test/apikeys
2. Copy `sk_test_...` → `STRIPE_SECRET_KEY` in root `.env`
3. Copy `pk_test_...` → `PUBLIC_STRIPE_PUBLISHABLE_KEY` in root `.env`
4. `stripe login` (one-time browser pairing)

`STRIPE_WEBHOOK_SECRET` is managed by the scripts — don't set it manually.

### Scripts reference

| Script | Purpose |
|--------|---------|
| `scripts/stripe-listen-start.sh` | Start `stripe listen`, write secret to `.env`, print JSON |
| `scripts/stripe-listen-stop.sh` | Kill tracked listener, clean PID file |
| `scripts/stripe-webhook-secret.sh` | One-shot: fetch secret into `.env`, no background process |
| `scripts/sync-env.sh` | Copy `PUBLIC_*` vars from root `.env` to frontend `.env` |
```

### 3.8 RUNBOOK.md stanza

Generate a `RUNBOOK.md` (or append a `## Stripe` section to an existing one) covering **all eight** areas below. This is operational documentation for humans running the system in production and incident response, not agent-facing docs.

#### 1. Dev webhook forwarding lifecycle

- `stripe-listen-start.sh` writes `STRIPE_WEBHOOK_SECRET` per session; API restart required after.
- `stripe-listen-stop.sh` safely tears down.
- Each session gets a new `whsec_...` — don't treat it as persistent.
- Leaving the listener running across sessions is fine; the start script will reuse a live one.

#### 2. Test vs live mode identification and guardrails

- `sk_test_…` / `pk_test_…` / dashboard URL `/test/` = safe.
- `sk_live_…` / `pk_live_…` / dashboard URL without `/test/` = production.
- Pre-commit hook blocks `sk_live_` / `pk_live_` in staged files.
- Security scan rule (gitleaks) blocks the same patterns in CI.
- Startup assertion in the API in non-prod env: if a key starts with `sk_live_` / `pk_live_` but the environment is `development` or `test`, refuse to boot.

#### 3. Production webhook endpoint setup

- Register an endpoint in https://dashboard.stripe.com/webhooks pointing at `https://<prod-domain>/webhooks/stripe`.
- Select the exact event types the handler processes (don't subscribe to everything — increases surface area and rate limit consumption).
- Copy the persistent `whsec_...` from the endpoint detail page into the production secret manager as `STRIPE_WEBHOOK_SECRET`.
- Deploy — verify signature verification works with a test Event replay from the dashboard.

#### 4. Webhook delivery failure recovery

- Stripe dashboard → Developers → Events shows every event with delivery status.
- Failed deliveries can be replayed individually (Event detail → "Resend to endpoint").
- Handler MUST be idempotent — replays may duplicate an event already delivered.
- Add a dashboard alert on "high rate of failed webhook deliveries" (Stripe Radar can do this).

#### 5. Secret rotation

- Generate new keys in the dashboard (create new, don't immediately revoke old).
- Roll through the "dual-key window" — deploy new key, verify requests are signing, then revoke old key.
- `STRIPE_WEBHOOK_SECRET`: create a new endpoint with the new URL path, migrate event subscriptions, then delete the old endpoint once confirmed no events are arriving at it.
- After rotation, run a verification test charge in test mode and confirm the webhook handler processes it.

#### 6. Fraud / dispute response

- Dashboard → Payments for charge-level review.
- Disputes: dashboard → Disputes → respond within the window (typically 7 days) with evidence (receipt, IP, shipping confirmation, customer communications).
- Refunds: full or partial via dashboard or API. Full refund reverses the charge; partial leaves remainder intact.
- Suspicious patterns (high card testing volume, many declines from one IP): enable Stripe Radar rules or call `radar.value_lists` to block.

#### 7. Monitoring

- Payment success rate — dashboard's default chart; alert on sustained dips.
- Dispute rate — dashboard default; alert if >1% (card network thresholds).
- Failed webhook deliveries — dashboard + your own logs (the handler should log every event's processing outcome at INFO).
- Structured logging: include `stripe_event_id`, `stripe_event_type`, outcome (`handled` / `skipped` / `deferred` / `failed`) on every handler log line.
- Tax calculation failures (if `STRIPE_TAX_ENABLED=true`): alert on `tax.calculation` errors — these cause checkout abandonment.

#### 8. Common errors

- `ERR_EXTERNAL_SERVICE_UNAVAILABLE` — Stripe API unreachable or rate-limited. Retry with backoff; circuit-break after N failures so the UI fails fast.
- `PaymentIntent` state machine — once `succeeded`, a PaymentIntent is immutable; don't try to `confirm` it again. Check `status` before every operation.
- `idempotency_key` reuse with different payloads — Stripe rejects this with a distinct error. Use fresh keys per logical operation.
- Tax calculation failures — `STRIPE_TAX_ENABLED=true` with missing customer address or unsupported jurisdiction. Handle by downgrading to a no-tax checkout and flagging for manual review.
- Signature verification failures — usually caused by body parsing middleware running before the webhook route. See webhook handler contract above.

### 3.9 `.claude/task-deps.json`

Include a `stripe-listen` entry so the run-tasks runner knows how to satisfy `[needs: stripe-listen]` tags:

```json
{
  "version": 1,
  "deps": {
    "stripe-listen": {
      "description": "Stripe CLI webhook forwarder. Writes ephemeral STRIPE_WEBHOOK_SECRET to root .env on start.",
      "start": "scripts/stripe-listen-start.sh",
      "stop": "scripts/stripe-listen-stop.sh",
      "prereqs": [
        "stripe CLI must be on PATH (nix develop)",
        "stripe login must have been completed once",
        "root .env must have STRIPE_SECRET_KEY and PUBLIC_STRIPE_PUBLISHABLE_KEY set to non-placeholder values"
      ],
      "start_output_format": "json",
      "start_output_schema": {
        "pid": "number",
        "secret": "string",
        "forward_to": "string",
        "log": "string",
        "reused": "boolean"
      },
      "post_start_requires_api_restart": true,
      "post_start_notes": "API must be (re)started after start so it reads the new STRIPE_WEBHOOK_SECRET from .env"
    }
  }
}
```

Merge with any existing `deps` rather than overwriting.

### 3.10 Live-key guardrails (generate all three)

#### 3.10.1 Pre-commit hook

Generate `.git/hooks/pre-commit` (or register via husky if the project uses it):

```bash
#!/usr/bin/env bash
# Block commits containing Stripe live keys.
set -euo pipefail

STAGED="$(git diff --cached --name-only --diff-filter=ACM)"
[ -z "$STAGED" ] && exit 0

VIOLATIONS=$(git diff --cached -U0 -- $STAGED | grep -E '^\+' | grep -E '(sk_live_|pk_live_)[A-Za-z0-9]+' || true)
if [ -n "$VIOLATIONS" ]; then
  echo "ERROR: staged changes contain Stripe LIVE keys:" >&2
  echo "$VIOLATIONS" >&2
  echo "" >&2
  echo "Live keys must NEVER be committed. Use sk_test_/pk_test_ in .env and" >&2
  echo "production secrets in your deployment secret manager." >&2
  exit 1
fi
```

Make it executable and document in CLAUDE.md. If the project uses husky, register the same logic as a husky pre-commit hook instead so it's tracked in the repo.

#### 3.10.2 gitleaks rule

Add to the project's `.gitleaks.toml` (create if missing, or append to `scripts/security-scan.sh`'s gitleaks invocation):

```toml
[[rules]]
id = "stripe-live-secret-key"
description = "Stripe live secret key"
regex = '''sk_live_[A-Za-z0-9]{20,}'''
tags = ["key", "stripe"]

[[rules]]
id = "stripe-live-publishable-key"
description = "Stripe live publishable key"
regex = '''pk_live_[A-Za-z0-9]{20,}'''
tags = ["key", "stripe"]
```

#### 3.10.3 .env.example warning comment

Already covered in §3.3 — the `.env.example` banner and the per-key comments explicitly warn against live keys.

---

## 4. Task-list integration

When generating `tasks.md`, every task that drives a real Stripe flow (checkout, refund, webhook verification, tax calculation, subscription lifecycle E2E) MUST:

1. Carry the `[needs: stripe-listen]` tag in the needs list.
2. Include a `Prereq:` line referencing the start/stop scripts and `test/e2e/README.md`.

Example:

```markdown
- [ ] T042 E2E: guest checkout end-to-end [SC-001] [needs: mcp-browser, stripe-listen]
  Prereq: `scripts/stripe-listen-start.sh` before running (see test/e2e/README.md); tear down with `stripe-listen-stop.sh` after.
  Done when: guest completes checkout with test card 4242424242424242; `payment_intent.succeeded` webhook received; order transitions to `paid`; confirmation page renders with order id.
```

The parallel runner reads `[needs: stripe-listen]`, looks up the dep in `.claude/task-deps.json`, and manages the listener **phase-scoped**: the start script fires once per runner session before the first task that needs it, and the stop script fires once at teardown. The start script's own idempotency handles the case where a listener is already running from a previous session (it detects the live PID, re-reads the secret into `.env`, and returns `"reused": true`).

Phase-scoped lifecycle matters because:
- Each `stripe listen` session rotates the webhook signing secret. If the runner started/stopped per task, the API would need to restart between every Stripe E2E task to pick up the new secret.
- The listener is a long-lived subprocess; starting and stopping it N times across N tasks wastes ~2-3s per task and is a bug surface (race conditions around PID file cleanup).

See `parallel_runner.py` → `TaskDepManager` for the implementation. No additional agent boilerplate needed.

**Task categories that typically need `stripe-listen`** (include all that apply to the project):

- Guest checkout E2E (web, mobile)
- Authenticated checkout E2E (web, mobile)
- Subscription signup / upgrade / downgrade E2E
- Refund (full, partial) E2E — driven from admin UI
- Dispute flow E2E (if the project handles disputes UI)
- Tax calculation E2E (if `STRIPE_TAX_ENABLED=true`)
- Webhook handler integration tests (if the test sends real events from the CLI)

Unit tests for the webhook handler that stub Stripe SDK calls do NOT need `stripe-listen` — they don't touch the CLI.

---

## 5. Design rationale (for skill maintainers)

### Single-source-of-truth `.env` + sync-env

Every project that has both a backend and a web frontend hits the split-env problem: web bundlers only read env files in their own directory, so you end up maintaining two copies, they diverge, and dev breaks silently. `sync-env.sh` with a `PUBLIC_` prefix convention means:

- Root `.env` is canonical — one place to rotate any variable.
- Frontend `.env` is derived — regenerated on every `dev`/`build` automatically via `predev`/`prebuild`.
- Secrets physically cannot leak to the frontend because the sync script filters them out.

### Runtime fetch + build-time fallback for publishable keys

- Runtime fetch enables key rotation without app store re-releases. Critical for mobile where the review cycle is days.
- Build-time fallback keeps first launches working before the app reaches the server.
- Both paths use the same key — no split-brain.

### Why the webhook secret rotates per session

Stripe CLI's `stripe listen` issues a fresh signing secret every time to prevent replay attacks across sessions. Accepting this as a feature (rather than fighting it) means:

- Every dev session starts with a verifiable, isolated signing key.
- Leaked secrets from old sessions can't be used to forge events to a current listener.
- The lifecycle scripts trade one-time complexity (writing robust start/stop) for eliminating an entire class of "my webhook doesn't work, why?" debugging sessions.

### Live-key guardrails are three-layered

A single check isn't enough. Developers will bypass a pre-commit hook (`git commit --no-verify`) under deadline pressure. CI catches it on push. Both fail closed to make bypass visible. The `.env.example` comment is the first line of defense: telling the user at `cp .env.example .env` time that live keys don't belong there.

---

## 6. What to probe during the Stripe interview

If the user says yes to Stripe, follow up with:

1. **"What are you selling?"** — one-time purchases, subscriptions, donations/tips, marketplace (multi-seller), something else. This determines which webhook events matter and what the handler's state machines look like.
2. **"Multi-currency?"** — if yes, the handler must read `event.data.object.currency` and not assume USD.
3. **"Stripe Tax?"** — `STRIPE_TAX_ENABLED` and the tax calculation failure handling plan.
4. **"Stripe Connect (marketplace)?"** — if yes, this is a much larger surface (Express/Standard/Custom accounts, transfers, application fees) and the interview needs a dedicated Connect pass. Flag it as a scope expansion.
5. **"Refund policy?"** — full only? partial allowed? admin-driven or customer-driven? Time-boxed? This drives the admin UI and refund webhook handling.
6. **"Dispute handling?"** — auto-accept? always contest? manual triage? This drives the `charge.dispute.created` handler.
7. **"Subscription dunning?"** (if subscriptions) — how many retry attempts, what's the grace period, when do entitlements get paused.

Record all answers in `interview-notes.md` under `## Stripe integration`.
