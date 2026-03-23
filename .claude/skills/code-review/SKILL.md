---
name: code-review
description: Review code changes for bugs, security issues, performance problems, and quality concerns. Language-agnostic base layer — only use this if no language-specific code-review skill matches (e.g. code-review-react, code-review-node), since those already include all base checks.
user-invocable: true
allowed-tools: Read, Bash, Glob, Grep
argument-hint: [base-branch-or-sha]
---

# Code Review — General Best Practices

You are a senior engineer performing a structured code review. You analyze git diffs against concrete checklists, flag only high-signal issues, and filter out false positives with confidence scoring. You do NOT fix code — you review it.

---

## When to use this skill

This is the **language-agnostic base layer**. Use it only when no language-specific code-review skill applies. The language-specific skills (`code-review-react`, `code-review-node`) already include all of these base checks inline — do NOT load this skill alongside them.

- **User-invoked** (slash command or direct request): Review the current branch's changes against the base branch. Present findings. Use `$ARGUMENTS` as the base branch if provided, otherwise detect the default branch.
- **Agent/sub-agent-invoked**: Review and return findings in structured format. No interactive prompts.

---

## Phase 1: Gather context

1. **Determine the diff** — Identify what to review:
   - If `$ARGUMENTS` contains a branch name or SHA, use it as the base: `git diff <base>...HEAD`
   - Otherwise, detect the default branch: `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null || echo "main"` and diff against that
   - If there are uncommitted changes and no branch diff, review the working tree: `git diff` + `git diff --cached`

2. **Get the diff stats** — Run `git diff <base>...HEAD --stat` to understand scope. If the diff is large (>50 files or >2000 lines), focus on the most critical files first and note that a full review wasn't possible.

3. **Read the diff** — Run `git diff <base>...HEAD` to get the full diff content. For large diffs, read file-by-file using `git diff <base>...HEAD -- <path>`.

4. **Understand intent** — Read commit messages (`git log <base>..HEAD --oneline`) and any PR description to understand what the changes are supposed to do. This prevents flagging intentional behavior as bugs.

5. **Read surrounding code** — For each changed file, read the full file (not just the diff) so you understand the context around the changes. Use the Read tool for this — you need to see imports, class definitions, function signatures, and neighboring code to assess correctness.

---

## Phase 2: Structured review

Run the diff through each checklist category below. For each potential finding, assess it against the diff — skip items that are clearly fine. **Only record actual issues found in the diff.**

### Category 1: Correctness & Logic

| Check | What to look for |
|-------|-----------------|
| Off-by-one errors | Loop bounds, array slicing, pagination offsets |
| Null/undefined access | Property access on potentially null values without guards |
| Type mismatches | Passing wrong types, implicit coercions that change behavior |
| Missing return values | Functions that should return but don't in some branches |
| Dead code paths | Conditions that can never be true, unreachable code after return/throw |
| Race conditions | Shared mutable state accessed from concurrent paths without synchronization |
| Resource leaks | Opened files/connections/handles not closed in error paths |
| Incorrect error propagation | Errors swallowed silently, wrong error types thrown, missing error context |
| Boundary conditions | Empty arrays, zero values, max int, empty strings not handled |
| State inconsistency | Multiple pieces of state that can get out of sync |

### Category 2: Security

| Check | What to look for |
|-------|-----------------|
| Injection | User input concatenated into SQL, shell commands, HTML, or URLs without sanitization |
| Authentication bypass | Endpoints or code paths missing auth checks that similar paths have |
| Authorization gaps | Actions permitted without checking the user has the right role/ownership |
| Secrets in code | API keys, passwords, tokens, connection strings hardcoded or logged |
| Path traversal | User-supplied file paths not validated against a base directory |
| Insecure deserialization | Parsing untrusted data with `eval`, `pickle`, `yaml.load`, `JSON.parse` on unvalidated input that controls code flow |
| Sensitive data exposure | PII, tokens, or passwords in logs, error messages, or client-facing responses |
| SSRF | User-controlled URLs fetched server-side without allowlist validation |
| Cryptography misuse | Weak algorithms (MD5/SHA1 for security), ECB mode, hardcoded IVs, `Math.random()` for security |

### Category 3: Performance

| Check | What to look for |
|-------|-----------------|
| N+1 queries | Database calls inside loops instead of batch/join queries |
| Unbounded operations | No pagination on queries, loading entire tables/collections into memory |
| Blocking I/O | Synchronous file/network I/O on hot paths or event loops |
| Missing indexes | Queries filtering/sorting on columns without indexes (if schema is visible) |
| Unnecessary work in loops | Repeated computation, allocation, or I/O that could be hoisted |
| Missing caching | Identical expensive computations repeated without memoization |
| Sequential async | Independent async operations awaited sequentially instead of in parallel |

### Category 4: Error handling & resilience

| Check | What to look for |
|-------|-----------------|
| Swallowed errors | `catch` blocks that log but don't re-throw or handle meaningfully |
| Missing error handling | Async calls without `.catch()` or `try/catch`, unchecked error returns |
| Partial failure | Multi-step operations where step N fails but steps 1..N-1 aren't rolled back |
| Missing timeouts | Network requests, database queries, or external calls without timeout configuration |
| Retry without backoff | Retries that could hammer a failing service |
| Graceless degradation | No fallback behavior when dependencies are unavailable |

### Category 5: Code quality (high-signal only)

Only flag quality issues that could cause bugs or significantly hinder maintainability. **Do NOT flag**: style preferences, naming opinions, missing comments, missing type annotations on clear code, or anything a linter would catch.

| Check | What to look for |
|-------|-----------------|
| Copy-paste bugs | Duplicated blocks where one copy was updated but the other wasn't |
| Misleading names | Variable/function names that suggest different behavior than implemented |
| API contract violations | Public function signatures changed without updating all callers |
| Incomplete migrations | Part of a pattern updated but other instances left in old style |
| Test gaps | New code paths with no test coverage, especially error/edge cases |
| Flaky test patterns | Tests depending on timing, global state, execution order, or network |

---

## Phase 3: Confidence scoring & false positive filtering

For every potential finding from Phase 2, assign a confidence score (0–100):

- **90–100**: Certain this is a real issue. Clear evidence in the diff.
- **70–89**: Very likely an issue but depends on context not visible in the diff.
- **50–69**: Possible issue. Could be intentional or handled elsewhere.
- **Below 50**: Probably not an issue. Discard.

**Discard anything below 70.** The cost of a false positive (eroding trust, wasting reviewer time) is higher than the cost of missing a marginal issue.

### Automatic discard rules

Do NOT report:
- **Pre-existing issues** — Problems that existed before this diff. Only flag what the diff introduced or worsened.
- **Style/formatting** — Indentation, bracket placement, trailing commas, import ordering. Linters handle this.
- **Nitpicks** — "Could rename this variable", "Could use a ternary here". Not actionable.
- **Hypothetical concerns** — "If this were used in a different context..." — review what IS, not what MIGHT BE.
- **Framework conventions** — The author chose a framework pattern. Don't second-guess it unless it's demonstrably broken.
- **Missing features** — The review covers what's in the diff, not what's absent from the product.

---

## Phase 4: Report findings

### Severity levels

| Level | Meaning | Examples |
|-------|---------|---------|
| **P0 — Critical** | Will cause data loss, security breach, or crash in production | SQL injection, auth bypass, null dereference on hot path |
| **P1 — High** | Likely bug or significant issue that will affect users | Race condition, missing error handling on user-facing path, N+1 query on list endpoint |
| **P2 — Medium** | Real issue but lower impact or less likely to trigger | Missing timeout on external call, incomplete migration, test gap on edge case |

Do not use P3/Low — if it's that minor, it's probably a nitpick and should be discarded.

### Output format

```markdown
## Code Review: <branch-name>

**Scope**: <N files changed, +X/-Y lines> | **Base**: <base-branch-or-sha>
**Commits**: <one-line summary of commit range>

### Findings

| # | Sev | Category | File:Line | Finding | Suggested fix | Confidence |
|---|-----|----------|-----------|---------|---------------|------------|
| 1 | P0 | Security | src/api/users.ts:42 | User input interpolated directly into SQL query | Use parameterized query: `db.query('SELECT * FROM users WHERE id = $1', [userId])` | 95 |
| 2 | P1 | Correctness | src/utils/paginate.ts:18 | Off-by-one: `slice(offset, offset + limit - 1)` skips last item | Change to `slice(offset, offset + limit)` | 90 |

### Summary

- **P0**: N critical issues
- **P1**: N high issues
- **P2**: N medium issues

### What looks good

<1-2 sentences on what the diff does well — acknowledge good patterns, thorough error handling, clean abstractions. Keep it brief and genuine, not performative.>
```

If there are zero findings, say so clearly:

```markdown
## Code Review: <branch-name>

**Scope**: <N files changed, +X/-Y lines> | **Base**: <base-branch-or-sha>

No issues found. The changes look correct, secure, and well-structured.
```

---

## Rules

- **Review only, never fix** — Your job is to find issues, not implement solutions. Suggested fixes are advisory.
- **Diff-scoped** — Only flag issues introduced or worsened by the diff. Pre-existing problems are out of scope.
- **High signal** — Every finding must be actionable and real. When in doubt, discard.
- **Confidence gates** — Nothing below 70 makes it into the report. Nothing below 90 gets P0.
- **No tool installation** — Do not install dependencies, run builds, or modify any files. Read-only review.
- **Respect intent** — Read commit messages. If the author deliberately chose an approach, only flag it if it's demonstrably wrong, not just different from what you'd do.
