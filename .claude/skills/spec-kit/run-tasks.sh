#!/usr/bin/env bash
# run-tasks.sh — Autonomously implement spec-kit tasks via Claude Code
#
# Run this from the root of a spec-kit project (where .specify/ and specs/ live).
#
# Usage:
#   ./run-tasks.sh [spec-dir] [max-runs]
#
# Examples:
#   ./run-tasks.sh                                          # auto-detect spec dir
#   ./run-tasks.sh specs/001-agent-runner-server-pwa        # specific spec
#   ./run-tasks.sh specs/001-agent-runner-server-pwa 50     # with run limit
#
# Stopping:
#   The agent writes BLOCKED.md in the repo root when it needs your input.
#   The script detects this and stops. Edit BLOCKED.md with your answer,
#   then delete it and re-run the script.
#
# Requires: claude CLI (Claude Code) with Max subscription
# Run in tmux/screen so it survives terminal disconnects.

set -uo pipefail

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

# --- Auto-detect spec directory ---
if [ -z "$SPEC_DIR" ]; then
  if [ ! -d "specs" ]; then
    echo "Error: No specs/ directory found. Are you in a spec-kit project root?"
    exit 1
  fi
  SPEC_DIRS=($(find specs -maxdepth 1 -mindepth 1 -type d 2>/dev/null))
  if [ ${#SPEC_DIRS[@]} -eq 0 ]; then
    echo "Error: No feature directories found in specs/"
    exit 1
  elif [ ${#SPEC_DIRS[@]} -eq 1 ]; then
    SPEC_DIR="${SPEC_DIRS[0]}"
  else
    echo "Multiple spec directories found:"
    for i in "${!SPEC_DIRS[@]}"; do
      echo "  [$i] ${SPEC_DIRS[$i]}"
    done
    echo ""
    echo "Specify one: $0 <spec-dir>"
    exit 1
  fi
fi

TASK_FILE="$SPEC_DIR/tasks.md"
CONSTITUTION=".specify/memory/constitution.md"

if [ ! -f "$TASK_FILE" ]; then
  echo "Error: Task file not found: $TASK_FILE"
  echo "Run /speckit.tasks first to generate it."
  exit 1
fi

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

# --- Build the context file list ---
# Order matters: constitution first (governance), then spec (what), then plan (how),
# then supporting docs, then tasks (what to do now)
CONTEXT_FILES=""
if [ -f "$CONSTITUTION" ]; then
  CONTEXT_FILES="$CONSTITUTION"
fi
for f in spec.md plan.md data-model.md research.md quickstart.md; do
  if [ -f "$SPEC_DIR/$f" ]; then
    CONTEXT_FILES="$CONTEXT_FILES $SPEC_DIR/$f"
  fi
done
if [ -d "$SPEC_DIR/contracts" ]; then
  for f in "$SPEC_DIR/contracts/"*.md; do
    [ -f "$f" ] && CONTEXT_FILES="$CONTEXT_FILES $f"
  done
fi

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
  cat <<'PROMPT'
You are an implementation agent for a spec-kit project. Your job is to execute exactly ONE task from the task list, then stop.

## Step 1: Read all context

Read these files IN ORDER to understand the project:
PROMPT

  # List context files
  for f in $CONTEXT_FILES; do
    echo "- \`$f\`"
  done

  cat <<PROMPT

Then read the task list:
- \`$TASK_FILE\`

Also read \`CLAUDE.md\` if it exists — it contains build/test commands and project conventions.

## Step 2: Understand the task structure

The task file is organized into PHASES. Each phase has a checkpoint that must pass before the next phase begins. Within a phase, tasks are ordered by dependency:
- Tasks marked \`[P]\` can run in parallel (they touch different files)
- Tasks WITHOUT \`[P]\` must run in order
- Test tasks come BEFORE their corresponding implementation tasks (TDD — constitution principle VII)
- The Dependencies section at the bottom of tasks.md defines phase ordering

## Step 3: Find the next task

Scan the task file and find the FIRST unchecked task (\`- [ ]\`) that is READY to execute:

1. All tasks in previous phases must be complete (\`- [x]\`) or skipped (\`- [~]\`)
2. All non-\`[P]\` tasks earlier in the current phase must be complete
3. The task's dependencies (if any) must be complete

If there are no unchecked tasks → say "ALL TASKS COMPLETE" and stop.
If the next task is blocked by incomplete prerequisites → say "BLOCKED: waiting on [task IDs]" and stop.

## Step 4: Execute the task

- Read any source files referenced in the task description
- Implement exactly what the task describes — follow the spec, plan, contracts, and data-model
- If the task says to write tests, write them and verify they FAIL before writing any implementation
- If the constitution exists, ensure your implementation complies with all principles
- If something is unclear or you need a design decision, write the question to \`BLOCKED.md\` and STOP immediately

## Step 5: Verify your work

After implementing, run the project's build and test commands to verify:
- Check CLAUDE.md for the exact commands (typically \`npm run build\` and \`npm test\` or similar)
- If no CLAUDE.md, check package.json scripts or the equivalent for the project's tech stack
- Fix any errors before proceeding
- If you cannot fix a build/test failure, write the issue to \`BLOCKED.md\` and stop

For early tasks (e.g., Phase 1 Setup), the build/test commands may not exist yet — that's fine, verify what you can.

## Step 6: Mark complete and commit

1. In \`$TASK_FILE\`, change the task's \`- [ ]\` to \`- [x]\`
2. If you're at a phase checkpoint, note whether the checkpoint criteria are met
3. Commit all changes with a conventional commit message (\`feat:\`, \`test:\`, \`fix:\`, \`refactor:\`, \`docs:\`)
   - Include the task ID in the commit message, e.g.: \`feat(T008): implement HTTP server entry point\`

## Rules

- Execute ONE task only, then stop
- Do NOT skip ahead to later phases
- Do NOT refactor unrelated code
- Do NOT read ROUTER.md or load any skills
- Do NOT use the Skill tool
- If you need user input, write to BLOCKED.md and stop immediately
- Prefer minimal changes that satisfy the task description
- If a task is unnecessary (already done, obsolete), mark it \`- [~]\` with a reason and move to the next task
PROMPT
}

log "=== Spec-Kit Task Runner Started ==="
log "Spec dir:  $SPEC_DIR"
log "Tasks:     $TASK_FILE"
log "Max runs:  $MAX_RUNS"
log "Log:       $LOG_FILE"
log "Remaining: $(count_remaining) tasks"
log ""

RUN_NUM=0
while [ $RUN_NUM -lt "$MAX_RUNS" ]; do
  RUN_NUM=$((RUN_NUM + 1))
  REMAINING=$(count_remaining)
  COMPLETED=$(count_completed)
  BLOCKED=$(count_blocked)

  if [ "$REMAINING" = "0" ] 2>/dev/null; then
    log ""
    log "=== ALL TASKS COMPLETE ==="
    log "Completed: $COMPLETED | Blocked: $BLOCKED"
    exit 0
  fi

  log "--- Run $RUN_NUM/$MAX_RUNS (remaining: $REMAINING, completed: $COMPLETED, blocked: $BLOCKED) ---"

  RUN_START=$(date +%s)

  > "$STDERR_FILE"
  > "$RATE_LIMIT_FILE"
  FIFO=$(mktemp -u)
  mkfifo "$FIFO"

  PROMPT_TEXT=$(build_prompt)

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

log ""
log "=== Runner finished after $RUN_NUM runs ==="
log "Remaining: $(count_remaining) | Completed: $(count_completed) | Blocked: $(count_blocked)"
