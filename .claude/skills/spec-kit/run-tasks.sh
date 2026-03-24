#!/usr/bin/env bash
# run-tasks.sh — Autonomously implement spec-kit tasks via Claude Code
#
# Run this from the root of a spec-kit project (where .specify/ and specs/ live).
#
# Usage:
#   ./run-tasks.sh [spec-dir] [max-runs]
#
# Examples:
#   ./run-tasks.sh                                          # all features sequentially
#   ./run-tasks.sh specs/001-agent-runner-server-pwa        # specific spec
#   ./run-tasks.sh specs/001-agent-runner-server-pwa 50     # with run limit
#
# When no spec-dir is given and multiple features exist, the script processes
# them in order (001, 002, 003, ...) with up to max-runs per feature.
#
# Stopping:
#   The agent writes BLOCKED.md in the repo root when it needs your input.
#   The script detects this and stops. Edit BLOCKED.md with your answer,
#   then delete it and re-run the script.
#
# Requires: claude CLI (Claude Code) with Max subscription
# Run in tmux/screen so it survives terminal disconnects.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(dirname "$SCRIPT_DIR")"
BLOCKED_FILE="BLOCKED.md"
SPEC_DIR="${1:-}"
MAX_RUNS="${2:-100}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
CONSECUTIVE_FAILURES=0
MAX_CONSECUTIVE_FAILURES=3
CONSECUTIVE_NOOP=0
MAX_CONSECUTIVE_NOOP=5
PREV_COMPLETED=""
BASE_BACKOFF=60
MAX_BACKOFF=1800
STDERR_FILE=$(mktemp)
RATE_LIMIT_FILE=$(mktemp)
CLAUDE_PID=""

cleanup() {
  rm -f "$STDERR_FILE" "$RATE_LIMIT_FILE" 2>/dev/null
}

terminate() {
  echo ""
  echo "Interrupted."
  if [ -n "$CLAUDE_PID" ] && kill -0 "$CLAUDE_PID" 2>/dev/null; then
    kill -TERM -- -"$CLAUDE_PID" 2>/dev/null || kill -TERM "$CLAUDE_PID" 2>/dev/null
    wait "$CLAUDE_PID" 2>/dev/null
  fi
  kill -- -$$ 2>/dev/null
  cleanup
  exit 130
}

trap terminate INT TERM
trap cleanup EXIT

# --- Resolve feature directories ---
ALL_FEATURES=false
if [ -z "$SPEC_DIR" ]; then
  if [ ! -d "specs" ]; then
    echo "Error: No specs/ directory found. Are you in a spec-kit project root?"
    exit 1
  fi
  SPEC_DIRS=($(find specs -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort))
  if [ ${#SPEC_DIRS[@]} -eq 0 ]; then
    echo "Error: No feature directories found in specs/"
    exit 1
  fi
  ALL_FEATURES=true
else
  SPEC_DIRS=("$SPEC_DIR")
fi

CONSTITUTION=".specify/memory/constitution.md"

# Check for leftover BLOCKED.md before starting
if [ -f "$BLOCKED_FILE" ]; then
  echo "=== BLOCKED ==="
  echo "The agent has a pending question in $BLOCKED_FILE:"
  echo ""
  cat "$BLOCKED_FILE"
  echo ""
  echo "Edit the file with your answer, then delete it and re-run."
  exit 2
fi

# --- Generate file manifest (one-line summaries for intelligent context selection) ---
build_manifest() {
  for f in $REFERENCE_FILES; do
    # Extract first heading or first non-empty line as summary, plus line count for size hint
    local lines summary
    lines=$(wc -l < "$f" 2>/dev/null || echo "?")
    summary=$(grep -m1 '^#' "$f" 2>/dev/null | sed 's/^#\+\s*//' || head -1 "$f" 2>/dev/null)
    [ -z "$summary" ] && summary="(no heading)"
    echo "- \`$f\` (${lines} lines) — $summary"
  done
}

# --- Log setup ---
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run-${TIMESTAMP}.log"

log() {
  echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

count_tasks() {
  local pattern="$1"
  if [ -f "$TASK_FILE" ]; then
    local n
    n=$(grep -c "$pattern" "$TASK_FILE" 2>/dev/null) || true
    echo "${n:-0}"
  else
    echo "?"
  fi
}

count_remaining() { count_tasks '^\- \[ \]'; }
count_completed() { count_tasks '^\- \[x\]'; }
count_blocked()   { count_tasks '^\- \[?\]'; }

# --- Build the prompt for each claude invocation ---
build_prompt() {
  cat <<PROMPT
You are an implementation agent for a spec-kit project. Your job is to execute exactly ONE task from the task list, then stop.

## Step 1: Read the task list and find your task

Read these files first — they are small and always needed:
- \`$TASK_FILE\` — the task list (find the next unchecked task)
- \`CLAUDE.md\` (if it exists) — build/test commands and project conventions
PROMPT

  if [ -f "$LEARNINGS_FILE" ]; then
    echo "- \`$LEARNINGS_FILE\` — discoveries from previous runs (read this to avoid repeating mistakes)"
  fi

  cat <<'PROMPT'

Scan the task file, find the FIRST unchecked task (`- [ ]`) that is ready (see Step 2), and note what it requires.

## Step 1b: Load only the context you need

Below is a manifest of available reference files with summaries. **Do NOT read all of them.** Based on your specific task, select and read ONLY the files relevant to what you need to implement:

PROMPT

  # Emit the manifest
  build_manifest

  cat <<'PROMPT'

**Selection guide:**
- Setup/config tasks → usually just `CLAUDE.md` is enough
- Tasks referencing data models or schemas → read `data-model.md`
- Tasks implementing API endpoints → read the relevant contract file
- Tasks requiring architectural context → read `constitution.md` and/or `plan.md`
- Tasks referencing feature behavior → read `spec.md`
- When in doubt, read `plan.md` — it's the most useful general reference

## Step 2: Find the next task

The task file is organized into PHASES. Each phase has a checkpoint that must pass before the next phase begins. Within a phase, tasks are ordered by dependency:
- Tasks marked \`[P]\` can run in parallel (they touch different files)
- Tasks WITHOUT \`[P]\` must run in order
- Test tasks come BEFORE their corresponding implementation tasks (TDD)
- The Dependencies section at the bottom of tasks.md defines phase ordering

Find the FIRST unchecked task (\`- [ ]\`) that is READY to execute:

1. All tasks in previous phases must be complete (\`- [x]\`) or skipped (\`- [~]\`)
2. All non-\`[P]\` tasks earlier in the current phase must be complete
3. The task's dependencies (if any) must be complete

If there are no unchecked tasks → say "ALL TASKS COMPLETE" and stop.
If the next task is blocked by incomplete prerequisites → say "BLOCKED: waiting on [task IDs]" and stop.

## Step 3: Execute the task

- Read any source files referenced in the task description
- Implement exactly what the task describes — follow the spec, plan, contracts, and data-model
- If the task says to write tests, write them and verify they FAIL before writing any implementation
- If the constitution exists, ensure your implementation complies with all principles
- If something is unclear or you need a design decision, write the question to \`BLOCKED.md\` and STOP immediately

## Step 4: Verify your work

After implementing, run the project's build and test commands to verify:
- Check CLAUDE.md for the exact commands (typically \`npm run build\` and \`npm test\` or similar)
- If no CLAUDE.md, check package.json scripts or the equivalent for the project's tech stack
- Fix any errors before proceeding
- If you cannot fix a build/test failure after 3 attempts, write the issue to \`BLOCKED.md\` and stop

For early tasks (e.g., Phase 1 Setup), the build/test commands may not exist yet — that's fine, verify what you can.

## Step 5: Self-review

Before marking complete, review your own changes:
1. Run \`git diff\` to see everything you changed
2. Check for:
   - Leftover debug code, console.logs, TODOs
   - Missing error handling at system boundaries (user input, external APIs)
   - Inconsistencies with patterns established in the existing codebase
   - Security issues (injection, XSS, hardcoded secrets)
3. Fix anything you find before proceeding

## Step 6: Record learnings

Append any useful discoveries to \`$LEARNINGS_FILE\`. This file persists across runs — future agents will read it. Record things like:
- Gotchas or surprises about the codebase, libraries, or APIs
- Non-obvious decisions you made and WHY (so future tasks stay consistent)
- Build/test quirks (e.g., "must run X before Y", "env var Z is required")
- Patterns you established that later tasks should follow (e.g., "error types go in src/errors.ts")

Format each entry as:
\`\`\`
### [TASK_ID] — Brief title
<what you learned>
\`\`\`

Do NOT record obvious things. Only record what would save the next agent time or prevent it from making a mistake.

## Step 7: Mark complete and commit

1. In \`$TASK_FILE\`, change the task's \`- [ ]\` to \`- [x]\`
2. If you're at a phase checkpoint, note whether the checkpoint criteria are met
3. Commit all changes (including learnings.md updates) with a conventional commit message (\`feat:\`, \`test:\`, \`fix:\`, \`refactor:\`, \`docs:\`)
   - Include the task ID in the commit message, e.g.: \`feat(T008): implement HTTP server entry point\`
4. **If this was the LAST unchecked task** (no \`- [ ]\` remaining after marking it), append a review task to \`$TASK_FILE\`:
   \`\`\`
   ## Phase: Review

   - [ ] REVIEW — Run code review on all changes from this feature branch
   \`\`\`
   This triggers an automated code review on the next runner iteration.

## Rules

- Execute ONE task only, then stop
- Do NOT skip ahead to later phases
- Do NOT refactor unrelated code
- Do NOT read ROUTER.md or load any skills
- Do NOT use the Skill tool
- If you need user input, write to BLOCKED.md and stop immediately
- Prefer minimal changes that satisfy the task description
- If a task is unnecessary (already done, obsolete), mark it \`- [~]\` with a reason and move to the next task
- ALWAYS update \`$LEARNINGS_FILE\` if you discovered anything non-obvious
PROMPT
}

# --- Detect if the next task is a REVIEW task ---
next_task_is_review() {
  grep -q '^\- \[ \] REVIEW' "$TASK_FILE" 2>/dev/null
}

# --- Build the review prompt (embeds code-review skill inline) ---
build_review_prompt() {
  # Determine the base SHA — the commit before the first spec-kit task commit
  local base_sha
  base_sha=$(git log --all --oneline --grep='feat(T0\|test(T0\|fix(T0\|refactor(T0\|docs(T0' --reverse --format='%H' 2>/dev/null | head -1)
  if [ -n "$base_sha" ]; then
    base_sha="${base_sha}~1"
  else
    base_sha=$(git merge-base HEAD "$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||' || echo main)" 2>/dev/null || echo "HEAD~20")
  fi

  # Pick the most specific review skill based on project files
  local review_skill="$SKILLS_DIR/code-review/SKILL.md"
  if [ -f "package.json" ]; then
    if grep -q '"react"' package.json 2>/dev/null; then
      review_skill="$SKILLS_DIR/code-review-react/SKILL.md"
    elif [ -f "tsconfig.json" ] || [ -f "server.js" ] || [ -f "index.ts" ] || [ -f "src/index.ts" ]; then
      review_skill="$SKILLS_DIR/code-review-node/SKILL.md"
    fi
  fi

  cat <<PROMPT
You are a code review agent. All implementation tasks for this feature are complete. Your job is to review the full set of changes.

## Base commit

Use this as the base for your diff:
\`\`\`
$base_sha
\`\`\`

Run: \`git diff ${base_sha}...HEAD\`

## Review instructions

Follow the code review skill instructions below exactly. After completing the review, write the review report to \`$SPEC_DIR/REVIEW.md\`.

Then mark the REVIEW task complete in \`$TASK_FILE\` (change \`- [ ] REVIEW\` to \`- [x] REVIEW\`) and commit with message: \`docs: code review for $(basename "$SPEC_DIR")\`

---

PROMPT

  # Embed the review skill content (skip YAML frontmatter between first two --- lines)
  if [ -f "$review_skill" ]; then
    awk 'BEGIN{skip=0} /^---$/{skip++; next} skip>=2{print}' "$review_skill"
  else
    echo "No review skill found at $review_skill — perform a general code review covering correctness, security, performance, and error handling."
  fi
}

# --- Check if a feature's tasks are all complete ---
feature_is_complete() {
  local task_file="$1"
  if [ ! -f "$task_file" ]; then
    return 1  # no task file = not complete (hasn't been generated yet)
  fi
  local remaining
  remaining=$(grep -c '^\- \[ \]' "$task_file" 2>/dev/null) || true
  [ "${remaining:-0}" -eq 0 ]
}

log "=== Spec-Kit Task Runner Started ==="
if [ "$ALL_FEATURES" = true ]; then
  log "Mode:      sequential (all features)"
  log "Features:  ${SPEC_DIRS[*]}"
else
  log "Mode:      single feature"
  log "Spec dir:  ${SPEC_DIRS[0]}"
fi
log "Max runs:  $MAX_RUNS per feature"
log "Log:       $LOG_FILE"
log ""

TOTAL_FEATURES=${#SPEC_DIRS[@]}
FEATURE_NUM=0

for CURRENT_SPEC_DIR in "${SPEC_DIRS[@]}"; do
  FEATURE_NUM=$((FEATURE_NUM + 1))
  SPEC_DIR="$CURRENT_SPEC_DIR"
  TASK_FILE="$SPEC_DIR/tasks.md"
  LEARNINGS_FILE="$SPEC_DIR/learnings.md"

  log "=============================================="
  log "=== Feature $FEATURE_NUM/$TOTAL_FEATURES: $(basename "$SPEC_DIR")"
  log "=============================================="

  # Skip features that don't have a task file yet
  if [ ! -f "$TASK_FILE" ]; then
    log "Skipping — no tasks.md found. Run /speckit.tasks first."
    log ""
    continue
  fi

  # Skip features that are already complete
  if feature_is_complete "$TASK_FILE"; then
    log "Skipping — all tasks already complete."
    log ""
    continue
  fi

  # Initialize learnings file if it doesn't exist
  if [ ! -f "$LEARNINGS_FILE" ]; then
    cat > "$LEARNINGS_FILE" <<'INIT'
# Learnings

Discoveries, gotchas, and decisions recorded by the implementation agent across runs.
Each entry should include a timestamp and the task ID that produced the learning.

---

INIT
    log "Created learnings file: $LEARNINGS_FILE"
  fi

  # Build reference files for this feature
  REFERENCE_FILES=""
  if [ -f "$CONSTITUTION" ]; then
    REFERENCE_FILES="$CONSTITUTION"
  fi
  for f in spec.md plan.md data-model.md research.md quickstart.md; do
    if [ -f "$SPEC_DIR/$f" ]; then
      REFERENCE_FILES="$REFERENCE_FILES $SPEC_DIR/$f"
    fi
  done
  if [ -d "$SPEC_DIR/contracts" ]; then
    for f in "$SPEC_DIR/contracts/"*.md; do
      [ -f "$f" ] && REFERENCE_FILES="$REFERENCE_FILES $f"
    done
  fi

  log "Tasks:     $TASK_FILE"
  log "Remaining: $(count_remaining) tasks"
  log ""

  # Reset per-feature state
  CONSECUTIVE_FAILURES=0
  CONSECUTIVE_NOOP=0
  PREV_COMPLETED=""

  RUN_NUM=0
  while [ $RUN_NUM -lt "$MAX_RUNS" ]; do
    RUN_NUM=$((RUN_NUM + 1))
    REMAINING=$(count_remaining)
    COMPLETED=$(count_completed)
    BLOCKED=$(count_blocked)

    if [ "$REMAINING" = "0" ] 2>/dev/null; then
      log ""
      log "=== ALL TASKS COMPLETE for $(basename "$SPEC_DIR") ==="
      log "Completed: $COMPLETED | Blocked: $BLOCKED"
      break
    fi

    log "--- Run $RUN_NUM/$MAX_RUNS [$(basename "$SPEC_DIR")] (remaining: $REMAINING, completed: $COMPLETED, blocked: $BLOCKED) ---"

    RUN_START=$(date +%s)

    > "$STDERR_FILE"
    > "$RATE_LIMIT_FILE"
    FIFO=$(mktemp -u)
    mkfifo "$FIFO"

    if next_task_is_review; then
      log "📋 Next task is REVIEW — switching to code review prompt"
      PROMPT_TEXT=$(build_review_prompt)
    else
      PROMPT_TEXT=$(build_prompt)
    fi

    claude --dangerously-skip-permissions --model opus --verbose --output-format stream-json \
      -p "$PROMPT_TEXT" \
      2> >(tee -a "$LOG_FILE" >> "$STDERR_FILE") > "$FIFO" &
    CLAUDE_PID=$!

    node -e '
      const rl = require("readline").createInterface({ input: process.stdin });
      const fs = require("fs");
      const logFile = process.argv[1];
      const rateLimitFile = process.argv[2];
      let gotContent = false;
      rl.on("line", (line) => {
        fs.appendFileSync(logFile, line + "\n");
        try {
          const msg = JSON.parse(line);
          if (msg.type === "rate_limit_event") {
            const info = msg.rate_limit_info || {};
            fs.writeFileSync(rateLimitFile, JSON.stringify({
              status: info.status,
              resetsAt: info.resetsAt,
              rateLimitType: info.rateLimitType,
              overageStatus: info.overageStatus,
              overageResetsAt: info.overageResetsAt,
              isUsingOverage: info.isUsingOverage
            }) + "\n");
            if (info.status && info.status !== "allowed") {
              process.stderr.write("RATE_LIMITED: resets at " + new Date(info.resetsAt * 1000).toLocaleTimeString() + "\n");
              process.exit(3);
            }
          } else if (msg.type === "assistant" && msg.message?.content) {
            gotContent = true;
            for (const block of msg.message.content) {
              if (block.type === "text" && block.text) {
                process.stdout.write(block.text);
              } else if (block.type === "tool_use") {
                const inp = block.input || {};
                let detail = "";
                if (block.name === "Bash") detail = inp.command || "";
                else if (block.name === "WebFetch") detail = inp.url || "";
                else if (block.name === "WebSearch") detail = inp.query || "";
                else if (block.name === "Read") detail = inp.file_path || "";
                else if (block.name === "Write") detail = inp.file_path || "";
                else if (block.name === "Edit") detail = inp.file_path || "";
                else if (block.name === "Glob") detail = inp.pattern || "";
                else if (block.name === "Grep") detail = inp.pattern || "";
                else if (block.name === "Agent") detail = inp.description || "";
                else detail = JSON.stringify(inp).slice(0, 120);
                process.stdout.write(`\n[${block.name}] ${detail}\n`);
              }
            }
          } else if (msg.type === "error") {
            const errMsg = msg.error?.message || msg.message || JSON.stringify(msg);
            process.stderr.write("CLAUDE_ERROR: " + errMsg + "\n");
            process.exit(2);
          } else if (msg.type === "result") {
            if (msg.result) process.stdout.write("\n" + msg.result + "\n");
            process.exit(msg.is_error ? 1 : 0);
          }
        } catch {}
      });
      rl.on("close", () => {
        if (!gotContent) process.exit(2);
        process.exit(0);
      });
    ' "$LOG_FILE" "$RATE_LIMIT_FILE" < "$FIFO"

    EXIT_CODE=$?
    # Kill the claude process if it's still running (node may exit before claude finishes)
    if [ -n "$CLAUDE_PID" ] && kill -0 "$CLAUDE_PID" 2>/dev/null; then
      kill -TERM "$CLAUDE_PID" 2>/dev/null
      # Give it a moment to exit gracefully, then force-kill
      for i in 1 2 3 4 5; do
        kill -0 "$CLAUDE_PID" 2>/dev/null || break
        sleep 1
      done
      kill -9 "$CLAUDE_PID" 2>/dev/null || true
    fi
    wait "$CLAUDE_PID" 2>/dev/null || true
    CLAUDE_PID=""
    rm -f "$FIFO"
    STDERR_CONTENT=$(cat "$STDERR_FILE" 2>/dev/null || true)

    # Parse rate limit info
    RESETS_AT=""
    if [ -s "$RATE_LIMIT_FILE" ]; then
      RESETS_AT=$(node -e '
        const fs = require("fs");
        try {
          const info = JSON.parse(fs.readFileSync(process.argv[1], "utf8").trim());
          if (info.resetsAt) process.stdout.write(String(info.resetsAt));
        } catch {}
      ' "$RATE_LIMIT_FILE" 2>/dev/null || true)
    fi

    # Determine if rate limited
    USAGE_LIMITED=false
    if [ $EXIT_CODE -eq 3 ]; then
      USAGE_LIMITED=true
    elif echo "$STDERR_CONTENT" | grep -qiE 'rate.?limit|usage.?limit|too many|429|quota|capacity|overloaded|busy|try again'; then
      USAGE_LIMITED=true
    elif [ $EXIT_CODE -eq 2 ] && [ $EXIT_CODE -ne 130 ] && ! echo "$STDERR_CONTENT" | grep -q "CLAUDE_ERROR"; then
      USAGE_LIMITED=true
    fi

    if [ $EXIT_CODE -eq 0 ]; then
      RUN_END=$(date +%s)
      RUN_DURATION=$(( RUN_END - RUN_START ))
      log "Run $RUN_NUM completed successfully (${RUN_DURATION}s)"
      CONSECUTIVE_FAILURES=0

      POST_COMPLETED=$(count_completed)
      if [ "$POST_COMPLETED" = "?" ]; then
        if [ $RUN_DURATION -lt 30 ]; then
          CONSECUTIVE_NOOP=$((CONSECUTIVE_NOOP + 1))
          log "⚠️  Fast no-op run (${RUN_DURATION}s). Consecutive: $CONSECUTIVE_NOOP/$MAX_CONSECUTIVE_NOOP"
        else
          CONSECUTIVE_NOOP=0
        fi
      elif [ -n "$PREV_COMPLETED" ] && [ "$POST_COMPLETED" = "$PREV_COMPLETED" ]; then
        CONSECUTIVE_NOOP=$((CONSECUTIVE_NOOP + 1))
        log "⚠️  No task progress (completed still $POST_COMPLETED). Consecutive: $CONSECUTIVE_NOOP/$MAX_CONSECUTIVE_NOOP"
      else
        CONSECUTIVE_NOOP=0
      fi
      PREV_COMPLETED="$POST_COMPLETED"

      if [ $CONSECUTIVE_NOOP -ge $MAX_CONSECUTIVE_NOOP ]; then
        log ""
        log "=== STOPPED — $MAX_CONSECUTIVE_NOOP consecutive runs with no task progress ==="
        log "Remaining: $(count_remaining) | Completed: $(count_completed) | Blocked: $(count_blocked)"
        exit 3
      fi
    elif [ "$USAGE_LIMITED" = true ]; then
      CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))

      if [ -n "$RESETS_AT" ]; then
        NOW=$(date +%s)
        BACKOFF=$(( RESETS_AT - NOW ))
        if [ $BACKOFF -gt 0 ]; then
          BACKOFF=$(( BACKOFF + 10 ))
        fi
        if [ $BACKOFF -lt 30 ]; then BACKOFF=30; fi
        if [ $BACKOFF -gt 21600 ]; then BACKOFF=21600; fi
        BACKOFF_MIN=$(( BACKOFF / 60 ))
        RESUME_TIME=$(date -d "@$((RESETS_AT + 10))" '+%H:%M:%S' 2>/dev/null || date -r "$((RESETS_AT + 10))" '+%H:%M:%S' 2>/dev/null || echo "~${BACKOFF_MIN}min")
        log "⏳ Rate limited (resets at $RESUME_TIME). Sleeping ${BACKOFF_MIN}min..."
      else
        BACKOFF=$(( BASE_BACKOFF * (2 ** (CONSECUTIVE_FAILURES - 1)) ))
        if [ $BACKOFF -gt $MAX_BACKOFF ]; then
          BACKOFF=$MAX_BACKOFF
        fi
        BACKOFF_MIN=$(( BACKOFF / 60 ))
        RESUME_TIME=$(date -d "+${BACKOFF} seconds" '+%H:%M:%S' 2>/dev/null || date -v+${BACKOFF}S '+%H:%M:%S' 2>/dev/null || echo "~${BACKOFF_MIN}min")
        log "⏳ Usage limit hit (attempt $CONSECUTIVE_FAILURES). Waiting ${BACKOFF_MIN}min (until ~$RESUME_TIME)..."
      fi
      if echo "$STDERR_CONTENT" | head -5 | grep -qiE 'rate|limit|usage|429|quota|capacity' ; then
        log "  Error detail: $(echo "$STDERR_CONTENT" | grep -iE 'rate|limit|usage|429|quota|capacity' | head -1)"
      fi
      SLEPT=0
      while [ $SLEPT -lt "$BACKOFF" ]; do
        sleep 1
        SLEPT=$((SLEPT + 1))
      done
      log "Resuming after backoff..."
      RUN_NUM=$((RUN_NUM - 1))
      continue
    else
      CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
      log "Run $RUN_NUM exited with code $EXIT_CODE (consecutive failures: $CONSECUTIVE_FAILURES)"
      if [ $CONSECUTIVE_FAILURES -ge $MAX_CONSECUTIVE_FAILURES ]; then
        log "⚠️  $MAX_CONSECUTIVE_FAILURES consecutive failures."
        log "Waiting ${BASE_BACKOFF}s before retrying..."
        SLEPT=0
        while [ $SLEPT -lt "$BASE_BACKOFF" ]; do
          sleep 1
          SLEPT=$((SLEPT + 1))
        done
        CONSECUTIVE_FAILURES=0
      fi
    fi

    # Check if agent wrote BLOCKED.md
    if [ -f "$BLOCKED_FILE" ]; then
      log ""
      log "=== BLOCKED — Agent needs your input ==="
      log ""
      cat "$BLOCKED_FILE" | tee -a "$LOG_FILE"
      log ""
      log "Edit $BLOCKED_FILE with your answer, delete it, then re-run."
      exit 2
    fi

    sleep 2
  done

  # If we exhausted the run limit without completing, exit
  if [ "$RUN_NUM" -ge "$MAX_RUNS" ]; then
    log ""
    log "=== Run limit ($MAX_RUNS) reached for $(basename "$SPEC_DIR") ==="
    log "Remaining: $(count_remaining) | Completed: $(count_completed) | Blocked: $(count_blocked)"
    exit 1
  fi
  log ""
done

log ""
log "=============================================="
log "=== All features processed ==="
log "=============================================="
for sd in "${SPEC_DIRS[@]}"; do
  tf="$sd/tasks.md"
  if [ ! -f "$tf" ]; then
    log "  $(basename "$sd"): no tasks.md"
  else
    r=$(grep -c '^\- \[ \]' "$tf" 2>/dev/null) || r=0
    c=$(grep -c '^\- \[x\]' "$tf" 2>/dev/null) || c=0
    b=$(grep -c '^\- \[?\]' "$tf" 2>/dev/null) || b=0
    if [ "${r:-0}" -eq 0 ]; then
      log "  $(basename "$sd"): ✅ COMPLETE ($c done, $b blocked)"
    else
      log "  $(basename "$sd"): $r remaining, $c done, $b blocked"
    fi
  fi
done
