# Test reporter templates

Canonical reporters that emit the spec-kit structured test output schema.
Pick the one for your test runner and drop it into your project.

- **Schema (READ THIS FIRST):** [EXAMPLE-OUTPUT.md](EXAMPLE-OUTPUT.md) — the
  contract. Every reporter produces this exact shape. Agents read the
  example to learn the schema; they should not need to read reporter source.
- **Vitest (Node/TS):** [test-reporter-vitest.ts](test-reporter-vitest.ts)
- **pytest (Python):** [test-reporter-pytest.py](test-reporter-pytest.py)
- **Go (go test -json pipe):** [test-reporter-go.go](test-reporter-go.go)

## Why use these

Every spec-kit project MUST produce structured output at `test-logs/summary.json`
(see `reference/testing.md` § Structured test output). The parallel runner
and fix-validate agents read these files directly — raw stdout is not
consulted. A divergent reporter silently breaks the fix-validate loop.

These templates are the **reference implementation**. Copy, don't fork:
extending them by adding fields is safe; renaming or dropping fields is not.

## Adding a new language

1. Read [EXAMPLE-OUTPUT.md](EXAMPLE-OUTPUT.md) end-to-end — the schema is
   the contract.
2. Match the on-disk layout exactly: `test-logs/summary.json` (latest) +
   `test-logs/<type>/<timestamp>/summary.json` + `failures/<name>.log`.
3. Use the canonical field names (`pass`/`fail`/`skip`, not `passed`/`failures`).
4. Enforce the non-vacuous assertion: if `pass + fail == 0`, exit non-zero.
5. Sanitize failure-log filenames per the rules in EXAMPLE-OUTPUT.md.
