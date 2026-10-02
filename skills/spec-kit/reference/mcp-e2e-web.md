# MCP-driven E2E — web (`mcp-browser`)

When to read: you are an E2E sub-agent on a task with `mcp-browser`
capability. Read this alongside `mcp-e2e-core.md`.

The web MCP server is Playwright-based. It drives a bundled Chromium
and exposes tools whose names begin with `browser_`.

## Cost rule (HARD — elevated after T096 post-mortem)

**Targeted `browser_evaluate` is the default page-understanding tool.
`browser_snapshot` is a fallback, not a first resort.** A single
full-page `browser_snapshot` on a real e-commerce page returned ~330 KB
of accessibility tree per call. Two such calls in one verify cycle cost
~$10 in sticky cache-read. A targeted `browser_evaluate` returning
`{heading, formFields, errors, url}` is ~500 bytes and has effectively
zero sticky cost.

| Goal | Tool |
|---|---|
| Read 1–5 specific fields/values on the page | `browser_evaluate` (returns `{field: value}`) |
| Locate a known element by role/name | `browser_evaluate` (returns `{ref}`) |
| First visit to a genuinely unfamiliar page | `browser_snapshot` (one shot, then prefer evaluate) |
| Visual evidence for a bug report | `browser_take_screenshot` |
| Network diagnostics for a 5xx response | `browser_network_requests` + `browser_console_messages` |

**Canonical evaluate pattern** — read exactly what you need, not the
whole page:

```js
await browser_evaluate({
  expression: `({
    heading: document.querySelector('h1')?.innerText,
    formFields: [...document.querySelectorAll('input,select,textarea')].map(e => ({
      name: e.name, type: e.type, required: e.required,
      value: e.value?.slice(0, 50), error: e.validationMessage
    })),
    errors: [...document.querySelectorAll('[role=alert],.error')].map(e => e.innerText),
    url: location.pathname
  })`
});
```

This returns ~500 bytes with everything a form-filling step needs.

### When `browser_snapshot` IS the right call

- First visit to a genuinely new, unfamiliar page where you don't know
  what elements exist.
- You need the full accessibility tree to report an a11y bug.

Even then, take **one** snapshot, then switch to `browser_evaluate`
for subsequent interactions on that page. Every subsequent snapshot
re-pays the full cost because the browser DOM is only incrementally
different.

## Page manifests (highest-ROI cost reduction)

For stable pages (checkout, product detail, login, etc.), author a
JSON manifest at
`specs/<feature>/validate/e2e/page-manifest/<route>.json` with stable
selectors and expected side-effects. The runner injects the manifest
into the planner + executor prompts so neither agent has to discover
selectors by snapshot.

### Manifest schema

```json
{
  "route": "/checkout",
  "title": "Checkout",
  "stable_selectors": {
    "email_input":      {"role": "textbox", "name": "Email"},
    "shipping_address": {"role": "textbox", "name": "Street address"},
    "card_number":      {"frame": "stripe-elements", "role": "textbox", "name": "Card number"},
    "submit_button":    {"role": "button",  "name": "Place order"}
  },
  "expected_state": {
    "headings": ["Checkout", "Shipping", "Payment"],
    "required_fields": ["email", "shipping_address", "card_number"],
    "side_effects_on_submit": [
      "POST /api/checkout returns 200",
      "navigation to /order/<id>"
    ]
  },
  "common_errors": {
    "card_declined":    {"selector": {"role": "alert"}, "text_pattern": "card was declined"},
    "missing_address":  {"selector": {"role": "alert"}, "text_pattern": "shipping address required"}
  },
  "regenerate_command": "node scripts/generate-page-manifest.js /checkout"
}
```

### Using a manifest in an executor

The executor reads selectors from the manifest and uses them directly
with `browser_click` / `browser_fill_form`, skipping `browser_snapshot`
entirely. If a manifest selector returns no element on the live page,
fall back to `browser_snapshot`, file a finding that the manifest is
stale, and update it.

## Regression spec writing

Use locators from `browser_snapshot` once you've validated a happy
path — the `ref` values in the snapshot map 1:1 to Playwright's
`getByRole` / `getByTestId`. Assert final DB state via `request.get`
to the same admin endpoints you used during exploration.

First line of the spec file must be `// regression for <TASK_ID>` —
without it, the runner treats the file as unrelated on next pass and
falls through to the full MCP loop.

## Browser MCP tools available

Tools whose names start with `mcp__mcp-browser__`:

| Tool | Use |
|---|---|
| `browser_navigate` | Go to a URL. Avoid — prefer staying on one page and using evaluate. |
| `browser_snapshot` | Full accessibility tree. Use sparingly — see cost rule. |
| `browser_evaluate` | Execute JS in page context; returns JSON. **Default tool.** |
| `browser_click` | Click an element (by `ref` from snapshot or evaluate) |
| `browser_fill_form` | Fill multiple fields at once |
| `browser_select_option` | Pick a dropdown option |
| `browser_take_screenshot` | PNG to disk. Only for bug evidence in findings.json. |
| `browser_console_messages` | Read browser console (with `level:"error"` filter) |
| `browser_network_requests` | Read the network log for the current page |

## Common failure patterns

| Symptom | Likely cause | Fix |
|---|---|---|
| `POST /api/<x>` returns 500 with `ERR_INTERNAL` | Backend placeholder key (Stripe, EasyPost) leaked past stub-routing | Check `test/e2e/.state/env` — real key should be sourced from root `.env` |
| Manifest selector returns no element | UI change since manifest was authored | Fall back to snapshot, file finding, update manifest |
| `browser_navigate` response >50k chars | Auto-snapshot enabled | Ensure `MCP_BROWSER_NO_AUTO_SCREENSHOT=1` is set in `get_mcp_config` env |
| Error says result exceeds max tokens and is spilled to disk | Snapshot of complex page | Switch to targeted `browser_evaluate`; one snapshot max per page |

## Platform boot

The browser runtime boots in ~3 s via the bundled MCP server. No
separate install step. The server writes its config to
`.specify/mcp/browser.json`.
