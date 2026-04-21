# Canonical structured test output — example

This document shows the **exact** file layout and JSON schema every spec-kit
project MUST produce. The runner (`parallel_runner.py`) and fix-validate
agents read these files directly — stdout is not consulted. If your reporter
diverges from this schema, agents fall back to parsing raw output and
regressions become invisible.

**Rule of thumb:** read this file, not the reporter source, to learn the
schema. Reporters are language-specific and noisy; this file is the contract.

## On-disk layout

```
test-logs/
  summary.json                           # latest run — always at this path
  <type>/                                # "unit" | "integration" | "e2e"
    <timestamp>/                         # ISO-8601-ish, e.g. 2026-04-20T14-03-17Z
      summary.json                       # per-run copy (for history)
      failures/
        <test-name>.log                  # one file per failing test
  security/
    summary.json                         # scanner aggregate (see security.md)
    <scanner>.json                       # raw per-scanner output
```

- **`test-logs/summary.json`** — the latest run. Always overwritten. Agents
  and the runner read this path first.
- **`test-logs/<type>/<timestamp>/`** — historical per-run record. Never
  overwritten. Lets fix-validate compare runs over time.
- **`failures/<test-name>.log`** — one plain-text file per failing test.
  Contains assertion (expected vs actual), full stack trace, captured
  stderr, and any relevant request/response context. One file per test so
  agents can load only the failing tests they need.

## `summary.json` schema (canonical)

Exact field names. The runner tolerates `skip` vs `skipped` as aliases but
**new reporters MUST use the canonical names below**.

```json
{
  "timestamp": "2026-04-20T14:03:17.412Z",
  "duration_ms": 48213,
  "type": "integration",
  "pass": 142,
  "fail": 3,
  "skip": 0,
  "total": 145,
  "command": "pnpm test",
  "failures": [
    "src/cart.integration.test.ts > cart > removes kit components when kit is removed",
    "src/checkout.integration.test.ts > checkout > applies tax when STRIPE_TAX_ENABLED=true",
    "src/auth/auth.integration.test.ts > auth > rejects expired session tokens"
  ],
  "results": [
    {
      "name": "src/cart.integration.test.ts > cart > adds item to cart",
      "file": "src/cart.integration.test.ts",
      "status": "passed",
      "duration_ms": 312
    },
    {
      "name": "src/cart.integration.test.ts > cart > removes kit components when kit is removed",
      "file": "src/cart.integration.test.ts",
      "status": "failed",
      "duration_ms": 287,
      "failure_log": "test-logs/integration/2026-04-20T14-03-17Z/failures/cart-removes-kit-components-when-kit-is-removed.log",
      "error": {
        "message": "expected 0 but got 2",
        "expected": "0",
        "actual": "2"
      }
    },
    {
      "name": "src/auth/auth.integration.test.ts > auth > skipped when auth service down",
      "file": "src/auth/auth.integration.test.ts",
      "status": "skipped",
      "duration_ms": 0,
      "reason": "auth service unavailable"
    }
  ]
}
```

### Field reference

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `timestamp` | string (ISO-8601) | yes | UTC. When the run started. |
| `duration_ms` | integer | yes | Wall-clock duration of the whole run. |
| `type` | string | yes | `"unit"`, `"integration"`, `"e2e"`, `"security"`. |
| `pass` | integer | yes | Count of passed tests. |
| `fail` | integer | yes | Count of failed tests. |
| `skip` | integer | yes | Count of skipped tests. **MUST be 0 for a run to pass.** See testing.md § Zero-skips rule. |
| `total` | integer | yes | `pass + fail + skip`. |
| `command` | string | yes | Exact command invoked (e.g. `pnpm test`). |
| `failures` | string[] | yes | Names of failing tests. Empty array if no failures. |
| `results` | object[] | yes | One entry per test. See per-result schema. |

### Per-result schema (`results[]`)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | yes | Fully-qualified test name. Include file and describe chain. |
| `file` | string | yes | Path to test file, relative to project root. |
| `status` | string | yes | `"passed"`, `"failed"`, `"skipped"`. |
| `duration_ms` | integer | yes | Per-test duration. |
| `failure_log` | string | if failed | Path to `failures/<test-name>.log`. |
| `error` | object | if failed | `{message, expected?, actual?, stack?}`. |
| `reason` | string | if skipped | Why the test was skipped. |

## `failures/<test-name>.log` format

Plain text, not JSON. Agents grep these. Example:

```
Test: src/cart.integration.test.ts > cart > removes kit components when kit is removed
File: src/cart.integration.test.ts:142
Duration: 287ms

ASSERTION FAILURE
  Expected: 0
  Actual:   2
  Message:  cart should be empty after kit removal

STACK TRACE
  at Object.<anonymous> (src/cart.integration.test.ts:158:20)
  at Promise.then.completed (node_modules/vitest/dist/...)
  ...

CAPTURED STDERR
  [2026-04-20T14:03:17Z] WARN  cart.service kit_removal partial_failure ...

CAPTURED REQUEST/RESPONSE
  DELETE /cart/items/kit-abc → 200 { removed: 1 }
  GET /cart → 200 { items: [{id: "comp-1"}, {id: "comp-2"}] }
```

## File-name sanitization for `failures/<test-name>.log`

Test names contain `/`, `>`, spaces, quotes. Canonical sanitizer:

1. Replace any char matching `[^A-Za-z0-9._-]` with `-`
2. Collapse consecutive `-` into single `-`
3. Trim leading/trailing `-`
4. Truncate to 200 chars
5. Append `.log`

Example: `src/cart.integration.test.ts > cart > removes kit components` →
`src-cart.integration.test.ts-cart-removes-kit-components.log`

## Non-vacuous assertion

The reporter (or a CI step after it) MUST verify `pass + fail > 0` before
reporting success. A summary with 0 passed / 0 failed means tests did not
run — this is a FAIL, not a PASS. See testing.md § Non-vacuous CI
validation.

## Why this schema

- **`timestamp` + `duration_ms`**: detect stale logs and timing regressions.
- **`type`**: lets the runner aggregate unit/integration/e2e separately.
- **`pass`/`fail`/`skip`/`total`**: at-a-glance counts without scanning `results`.
- **`command`**: agents can re-run failures without guessing the invocation.
- **`failures[]`**: agents see which tests to diagnose without iterating `results`.
- **`results[]`**: full per-test record; lets agents filter by file or
  describe block.
- **`failure_log` pointer**: agents load only the failing tests' logs, not
  the whole output, keeping context small.
