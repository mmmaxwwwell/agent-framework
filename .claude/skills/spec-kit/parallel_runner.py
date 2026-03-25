#!/usr/bin/env python3
"""
parallel_runner.py — Parallel spec-kit task runner with TUI dashboard.

Parses tasks.md for phases, [P] markers, and dependency graphs.
Spawns multiple claude agents in parallel where safe, renders a live
ASCII dependency diagram and split-pane agent output.

Modes:
  --tui       Interactive terminal with live diagram + agent output panes (default)
  --headless  No terminal I/O; all output written to log files

Usage:
  python3 parallel_runner.py [--headless] [spec-dir] [max-runs]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


# ── Data model ──────────────────────────────────────────────────────────

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    description: str
    phase: str
    parallel: bool  # marked [P]
    status: TaskStatus
    line_num: int
    dependencies: list[str] = field(default_factory=list)


@dataclass
class Phase:
    name: str
    slug: str
    tasks: list[Task] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # phase slugs this depends on


@dataclass
class AgentSlot:
    """Tracks a running claude agent."""
    agent_id: int
    task: Task
    process: Optional[subprocess.Popen] = None
    pid: Optional[int] = None
    start_time: float = 0.0
    output_lines: list[str] = field(default_factory=list)
    log_file: Optional[Path] = None
    exit_code: Optional[int] = None
    status: str = "starting"  # starting, running, done, failed, rate_limited


# ── Task file parser ───────────────────────────────────────────────────

TASK_RE = re.compile(
    r'^- \[(?P<check>[ x~?])\]\s+'
    r'(?:(?P<id>[A-Za-z0-9_-]+(?:-fix\d+)?)\s+)?'
    r'(?:\[P\]\s+)?'
    r'(?P<desc>.+)$'
)
PARALLEL_RE = re.compile(r'\[P\]')
PHASE_HEADING_RE = re.compile(r'^##\s+Phase\s*(?::?\s*\d*\s*[-–—:]?\s*)?(.+)$', re.IGNORECASE)
DEPENDENCY_SECTION_RE = re.compile(r'^##\s+(?:Phase\s+)?Dependencies', re.IGNORECASE)
DEP_ARROW_RE = re.compile(r'Phase\s+(\d+|[A-Za-z][\w-]*)\s*(?:──?▶|->|→)\s*Phase\s+(\d+|[A-Za-z][\w-]*)')
REVIEW_RE = re.compile(r'^- \[ \] REVIEW')


def slugify_phase(name: str) -> str:
    """Convert phase heading to a slug like 'phase1', 'phase2-core'."""
    # Try to extract phase number
    m = re.match(r'(?:Phase\s*)?(\d+)', name, re.IGNORECASE)
    if m:
        rest = name[m.end():].strip().strip(':').strip('-').strip('—').strip()
        slug = f"phase{m.group(1)}"
        if rest:
            rest_slug = re.sub(r'[^a-z0-9]+', '-', rest.lower()).strip('-')[:20]
            slug += f"-{rest_slug}"
        return slug
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:30] or "unknown"


def _extract_phase_number(slug: str) -> Optional[str]:
    """Extract the numeric part from a phase slug, e.g. 'phase2-core' -> '2'."""
    m = re.match(r'phase[- ]?(\d+)', slug, re.IGNORECASE)
    return m.group(1) if m else None


def parse_task_file(path: Path) -> tuple[list[Phase], dict[str, list[str]]]:
    """Parse tasks.md into phases and a phase dependency graph."""
    lines = path.read_text().splitlines()

    phases: list[Phase] = []
    raw_deps: list[tuple[str, str]] = []  # (src_key, dst_key) from dep section
    current_phase: Optional[Phase] = None
    in_dep_section = False

    for i, line in enumerate(lines):
        # Detect dependency section
        if DEPENDENCY_SECTION_RE.match(line):
            in_dep_section = True
            continue

        # Parse dependency arrows in dep section
        if in_dep_section:
            if line.startswith('##'):
                in_dep_section = False
            else:
                for m in DEP_ARROW_RE.finditer(line):
                    raw_deps.append((m.group(1), m.group(2)))
                continue

        # Phase heading
        pm = PHASE_HEADING_RE.match(line)
        if pm:
            phase_name = pm.group(1).strip()
            slug = slugify_phase(line.lstrip('#').strip())
            current_phase = Phase(name=phase_name, slug=slug)
            phases.append(current_phase)
            continue

        # Task line
        tm = TASK_RE.match(line)
        if tm and current_phase is not None:
            check = tm.group('check')
            task_id = tm.group('id') or f"T{i+1}"
            desc = tm.group('desc')
            is_parallel = bool(PARALLEL_RE.search(line))

            if check == 'x':
                status = TaskStatus.COMPLETE
            elif check == '~':
                status = TaskStatus.SKIPPED
            elif check == '?':
                status = TaskStatus.BLOCKED
            else:
                status = TaskStatus.PENDING

            task = Task(
                id=task_id,
                description=desc,
                phase=current_phase.slug,
                parallel=is_parallel,
                status=status,
                line_num=i + 1,
            )
            current_phase.tasks.append(task)

    # Build lookup: phase number -> actual slug, and raw key -> actual slug
    num_to_slug: dict[str, str] = {}
    key_to_slug: dict[str, str] = {}
    for p in phases:
        num = _extract_phase_number(p.slug)
        if num:
            num_to_slug[num] = p.slug
        key_to_slug[p.slug] = p.slug

    def resolve_key(key: str) -> Optional[str]:
        """Resolve a dependency key (e.g. '2', 'phase2', 'phase-2-core') to an actual phase slug."""
        if key in key_to_slug:
            return key
        # Try as a bare number
        if key in num_to_slug:
            return num_to_slug[key]
        # Try prefixing with 'phase'
        prefixed = f"phase{key}"
        if prefixed in key_to_slug:
            return prefixed
        num = _extract_phase_number(key)
        if num and num in num_to_slug:
            return num_to_slug[num]
        return None

    # Resolve raw deps into actual phase slugs
    phase_deps: dict[str, list[str]] = {}
    for src_key, dst_key in raw_deps:
        src_slug = resolve_key(src_key)
        dst_slug = resolve_key(dst_key)
        if src_slug and dst_slug:
            phase_deps.setdefault(dst_slug, []).append(src_slug)

    # Infer phase dependencies from ordering if no explicit dep section
    if not phase_deps and len(phases) > 1:
        for i in range(1, len(phases)):
            phase_deps[phases[i].slug] = [phases[i - 1].slug]

    # Attach to phase objects
    for p in phases:
        p.dependencies = phase_deps.get(p.slug, [])

    return phases, phase_deps


# ── Scheduler ──────────────────────────────────────────────────────────

class Scheduler:
    """Determines which tasks are ready to run given current state."""

    def __init__(self, phases: list[Phase], phase_deps: dict[str, list[str]]):
        self.phases = phases
        self.phase_deps = phase_deps
        self.phase_map = {p.slug: p for p in phases}
        self.task_map = {}
        for p in phases:
            for t in p.tasks:
                self.task_map[t.id] = t

    def phase_complete(self, slug: str) -> bool:
        phase = self.phase_map.get(slug)
        if not phase:
            return True
        return all(t.status in (TaskStatus.COMPLETE, TaskStatus.SKIPPED) for t in phase.tasks)

    def phase_deps_met(self, slug: str) -> bool:
        deps = self.phase_deps.get(slug, [])
        return all(self.phase_complete(d) for d in deps)

    def get_ready_tasks(self, running_ids: set[str]) -> list[Task]:
        """Return tasks that are ready to execute right now."""
        ready = []

        for phase in self.phases:
            if not self.phase_deps_met(phase.slug):
                continue

            # Within a phase, find ready tasks
            sequential_blocked = False
            for task in phase.tasks:
                if task.status in (TaskStatus.COMPLETE, TaskStatus.SKIPPED):
                    continue
                if task.id in running_ids:
                    if not task.parallel:
                        sequential_blocked = True
                    continue
                if task.status != TaskStatus.PENDING:
                    if not task.parallel:
                        sequential_blocked = True
                    continue

                # Sequential task: only ready if no prior sequential task is incomplete
                if not task.parallel:
                    if sequential_blocked:
                        break  # can't go past an incomplete sequential task
                    ready.append(task)
                    sequential_blocked = True  # block subsequent sequential tasks
                else:
                    # Parallel task: ready if sequential deps before it are done
                    if not sequential_blocked:
                        ready.append(task)
                    # Even with sequential_blocked, [P] tasks can run if they
                    # were listed after the blocking task but are marked parallel.
                    # The spec says [P] tasks touch different files.
                    elif task.parallel:
                        ready.append(task)

        return ready

    def all_complete(self) -> bool:
        return all(
            t.status in (TaskStatus.COMPLETE, TaskStatus.SKIPPED)
            for p in self.phases
            for t in p.tasks
        )

    def remaining_count(self) -> int:
        return sum(
            1 for p in self.phases for t in p.tasks
            if t.status == TaskStatus.PENDING
        )

    def completed_count(self) -> int:
        return sum(
            1 for p in self.phases for t in p.tasks
            if t.status == TaskStatus.COMPLETE
        )

    def blocked_count(self) -> int:
        return sum(
            1 for p in self.phases for t in p.tasks
            if t.status == TaskStatus.BLOCKED
        )


# ── ASCII dependency graph renderer ───────────────────────────────────

STATUS_SYMBOLS = {
    TaskStatus.PENDING:  "○",
    TaskStatus.RUNNING:  "◉",
    TaskStatus.COMPLETE: "●",
    TaskStatus.SKIPPED:  "⊘",
    TaskStatus.BLOCKED:  "⊗",
    TaskStatus.FAILED:   "✗",
}

STATUS_COLORS = {
    TaskStatus.PENDING:  "\033[37m",      # white
    TaskStatus.RUNNING:  "\033[33;1m",    # bold yellow
    TaskStatus.COMPLETE: "\033[32m",      # green
    TaskStatus.SKIPPED:  "\033[90m",      # gray
    TaskStatus.BLOCKED:  "\033[31m",      # red
    TaskStatus.FAILED:   "\033[31;1m",    # bold red
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def render_dependency_graph(phases: list[Phase], phase_deps: dict[str, list[str]],
                             agents: list[AgentSlot], width: int,
                             max_height: int = 0) -> list[str]:
    """Render an ASCII art dependency diagram showing phase/task status.

    If max_height > 0, the output is capped to that many lines. A sticky header
    (title + legend + running agents + summary) is always shown. The task list
    scrolls to keep running/active tasks visible.
    """
    running_ids = {a.task.id for a in agents}

    # ── Build header (always visible) ────────────────────────────────────
    header: list[str] = []
    header.append(f"{BOLD}{'─' * width}{RESET}")

    # Summary counts
    total_tasks = sum(len(p.tasks) for p in phases)
    done_tasks = sum(1 for p in phases for t in p.tasks
                     if t.status in (TaskStatus.COMPLETE, TaskStatus.SKIPPED))
    running_tasks = sum(1 for p in phases for t in p.tasks if t.id in running_ids)
    failed_tasks = sum(1 for p in phases for t in p.tasks if t.status == TaskStatus.FAILED)
    blocked_tasks = sum(1 for p in phases for t in p.tasks if t.status == TaskStatus.BLOCKED)

    summary_parts = [f"{BOLD}TASKS{RESET} {done_tasks}/{total_tasks}"]
    if running_tasks:
        summary_parts.append(f"{STATUS_COLORS[TaskStatus.RUNNING]}◉ {running_tasks} running{RESET}")
    if failed_tasks:
        summary_parts.append(f"{STATUS_COLORS[TaskStatus.FAILED]}✗ {failed_tasks} failed{RESET}")
    if blocked_tasks:
        summary_parts.append(f"{STATUS_COLORS[TaskStatus.BLOCKED]}⊗ {blocked_tasks} blocked{RESET}")
    header.append(" " + "  ".join(summary_parts))

    # Legend (compact)
    legend_parts = []
    for s in [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.COMPLETE,
              TaskStatus.SKIPPED, TaskStatus.BLOCKED, TaskStatus.FAILED]:
        legend_parts.append(f"{STATUS_COLORS[s]}{STATUS_SYMBOLS[s]} {s.value}{RESET}")
    header.append(" " + " ".join(legend_parts))

    # Running agents
    if agents:
        agent_strs = []
        for a in agents:
            elapsed = int(time.time() - a.start_time) if a.start_time else 0
            agent_strs.append(
                f"{STATUS_COLORS[TaskStatus.RUNNING]}Agent {a.agent_id}: {a.task.id} ({elapsed}s){RESET}"
            )
        header.append(f" Running: {' │ '.join(agent_strs)}")

    header.append(f"{BOLD}{'─' * width}{RESET}")

    # ── Build full task list ─────────────────────────────────────────────
    task_lines: list[str] = []
    # Track which line indices correspond to running/active tasks
    active_line_indices: list[int] = []

    for i, phase in enumerate(phases):
        dep_str = ""
        if phase.dependencies:
            dep_names = []
            for d in phase.dependencies:
                dp = next((p for p in phases if p.slug == d), None)
                if dp:
                    dep_names.append(dp.name[:15])
            dep_str = f" {DIM}← {', '.join(dep_names)}{RESET}"

        done = sum(1 for t in phase.tasks if t.status in (TaskStatus.COMPLETE, TaskStatus.SKIPPED))
        total = len(phase.tasks)
        running = sum(1 for t in phase.tasks if t.id in running_ids)

        if done == total and total > 0:
            phase_color = STATUS_COLORS[TaskStatus.COMPLETE]
            phase_sym = "●"
        elif running > 0:
            phase_color = STATUS_COLORS[TaskStatus.RUNNING]
            phase_sym = "◉"
        elif done > 0:
            phase_color = "\033[33m"
            phase_sym = "◐"
        else:
            phase_color = STATUS_COLORS[TaskStatus.PENDING]
            phase_sym = "○"

        task_lines.append(f" {phase_color}{phase_sym} {phase.name} [{done}/{total}]{RESET}{dep_str}")
        if running > 0:
            active_line_indices.append(len(task_lines) - 1)

        for task in phase.tasks:
            effective_status = task.status
            if task.id in running_ids:
                effective_status = TaskStatus.RUNNING
            color = STATUS_COLORS[effective_status]
            sym = STATUS_SYMBOLS[effective_status]
            p_marker = " [P]" if task.parallel else "    "
            desc = task.description[:width - 20]
            task_lines.append(f"   {color}{sym}{RESET}{p_marker} {DIM}{task.id}{RESET} {desc}")
            if effective_status == TaskStatus.RUNNING:
                active_line_indices.append(len(task_lines) - 1)

        if i < len(phases) - 1:
            task_lines.append(f"   {DIM}│{RESET}")

    # ── Apply height cap with scrolling ──────────────────────────────────
    footer = [f"{BOLD}{'─' * width}{RESET}"]
    total_fixed = len(header) + len(footer)

    if max_height <= 0 or total_fixed + len(task_lines) <= max_height:
        return header + task_lines + footer

    available = max_height - total_fixed - 1  # -1 for the "... N more" indicator
    if available < 3:
        available = 3

    # Scroll to keep active tasks visible: center the first active line
    if active_line_indices:
        center_line = active_line_indices[0]
        scroll_start = max(0, center_line - available // 3)
    else:
        # No active tasks — show the end (most recently completed)
        scroll_start = max(0, len(task_lines) - available)

    scroll_end = min(scroll_start + available, len(task_lines))
    # Adjust start if we hit the bottom
    if scroll_end == len(task_lines):
        scroll_start = max(0, scroll_end - available)

    visible_lines = task_lines[scroll_start:scroll_end]
    hidden = len(task_lines) - len(visible_lines)
    if hidden > 0:
        above = scroll_start
        below = len(task_lines) - scroll_end
        scroll_hint_parts = []
        if above > 0:
            scroll_hint_parts.append(f"↑{above} above")
        if below > 0:
            scroll_hint_parts.append(f"↓{below} below")
        visible_lines.append(f" {DIM}… {', '.join(scroll_hint_parts)}{RESET}")

    return header + visible_lines + footer


# ── TUI renderer ──────────────────────────────────────────────────────

class TUI:
    """Terminal UI with top graph pane and bottom agent output panes."""

    def __init__(self, phases: list[Phase], phase_deps: dict[str, list[str]], layout: str = "vertical"):
        self.phases = phases
        self.phase_deps = phase_deps
        self.layout = layout
        self.agents: list[AgentSlot] = []
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def update_agents(self, agents: list[AgentSlot]):
        with self.lock:
            self.agents = list(agents)

    def _get_terminal_size(self) -> tuple[int, int]:
        try:
            cols, rows = shutil.get_terminal_size()
            return cols, rows
        except Exception:
            return 120, 40

    def _render_loop(self):
        while not self._stop.is_set():
            try:
                self._render_frame()
            except Exception:
                pass
            self._stop.wait(0.5)

    def _render_frame(self):
        cols, rows = self._get_terminal_size()
        with self.lock:
            agents = list(self.agents)

        # Clear screen and move cursor to top
        output = "\033[2J\033[H"

        # Budget: give graph ~40% of terminal height, agents get the rest
        graph_budget = max(rows * 2 // 5, 8)
        graph_lines = render_dependency_graph(
            self.phases, self.phase_deps, agents, cols, max_height=graph_budget
        )
        graph_height = len(graph_lines)

        for line in graph_lines:
            output += line + "\n"

        # Bottom section: agent output panes
        if not agents:
            output += f"\n {DIM}No agents running. Waiting for ready tasks...{RESET}\n"
        else:
            remaining_rows = max(rows - graph_height - 2, 8)
            num_agents = len(agents)

            if self.layout == "vertical":
                # ── Vertical (stacked) layout ────────────────────────────
                pane_width = cols
                hsep_height = 1
                usable_height = remaining_rows - (num_agents - 1) * hsep_height
                pane_height = max(usable_height // num_agents, 4)

                for idx, agent in enumerate(agents):
                    pane_lines = self._build_pane(agent, pane_width, pane_height)
                    for pl in pane_lines:
                        output += pl + "\n"
                    if idx < num_agents - 1:
                        output += f"{DIM}{'─' * pane_width}{RESET}\n"
            else:
                # ── Grid layout ──────────────────────────────────────────
                if num_agents <= 2:
                    grid_cols = num_agents
                elif num_agents <= 4:
                    grid_cols = 2
                elif num_agents <= 9:
                    grid_cols = 3
                else:
                    grid_cols = 4
                grid_rows = math.ceil(num_agents / grid_cols)

                vsep_width = 1
                hsep_height = 1
                usable_width = cols - (grid_cols - 1) * vsep_width
                pane_width = max(usable_width // grid_cols, 20)
                usable_height = remaining_rows - (grid_rows - 1) * hsep_height
                pane_height = max(usable_height // grid_rows, 5)

                pane_contents = [self._build_pane(a, pane_width, pane_height) for a in agents]

                for gr in range(grid_rows):
                    start_idx = gr * grid_cols
                    end_idx = min(start_idx + grid_cols, num_agents)
                    row_panes = pane_contents[start_idx:end_idx]

                    while len(row_panes) < grid_cols:
                        row_panes.append([" " * pane_width] * pane_height)

                    for line_idx in range(pane_height):
                        row_parts = []
                        for pane in row_panes:
                            if line_idx < len(pane):
                                row_parts.append(pane[line_idx])
                            else:
                                row_parts.append(" " * pane_width)
                        output += f"{DIM}│{RESET}".join(row_parts) + "\n"

                    if gr < grid_rows - 1:
                        sep_line = f"{DIM}┼{RESET}".join(
                            [f"{DIM}{'─' * pane_width}{RESET}"] * grid_cols
                        )
                        output += sep_line + "\n"

        sys.stdout.write(output)
        sys.stdout.flush()

    @staticmethod
    def _build_pane(agent: AgentSlot, pane_width: int, pane_height: int) -> list[str]:
        """Build rendered lines for a single agent pane."""
        pane_lines = []
        elapsed = int(time.time() - agent.start_time) if agent.start_time else 0
        header = f"Agent {agent.agent_id}: {agent.task.id} ({agent.status}, {elapsed}s)"
        pane_lines.append(f"{BOLD}{header[:pane_width]}{RESET}")
        pane_lines.append("─" * pane_width)

        tail = agent.output_lines[-(pane_height - 3):]
        for oline in tail:
            visible = re.sub(r'\033\[[0-9;]*m', '', oline)
            if len(visible) > pane_width:
                pane_lines.append(oline[:pane_width + (len(oline) - len(visible))])
            else:
                pad = pane_width - len(visible)
                pane_lines.append(oline + " " * pad)

        while len(pane_lines) < pane_height:
            pane_lines.append(" " * pane_width)
        return pane_lines[:pane_height]


# ── Headless logger ───────────────────────────────────────────────────

class HeadlessLogger:
    """Writes all output to files instead of terminal."""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.main_log = self.log_dir / "runner.log"
        self._lock = threading.Lock()

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        with self._lock:
            with open(self.main_log, "a") as f:
                f.write(line)

    def agent_log_path(self, agent_id: int, task_id: str) -> Path:
        return self.log_dir / f"agent-{agent_id}-{task_id}.log"

    def write_status(self, phases: list[Phase], phase_deps: dict[str, list[str]],
                      agents: list[AgentSlot]):
        """Write a plain-text status snapshot."""
        status_file = self.log_dir / "status.txt"
        lines = []
        lines.append(f"Status as of {datetime.now().isoformat()}")
        lines.append("=" * 60)
        for phase in phases:
            done = sum(1 for t in phase.tasks if t.status in (TaskStatus.COMPLETE, TaskStatus.SKIPPED))
            total = len(phase.tasks)
            lines.append(f"\n{phase.name} [{done}/{total}]")
            running_ids = {a.task.id for a in agents}
            for task in phase.tasks:
                s = task.status.value
                if task.id in running_ids:
                    s = "running"
                p = " [P]" if task.parallel else ""
                lines.append(f"  [{s:>8}]{p} {task.id} {task.description}")

        lines.append(f"\nRunning agents: {len(agents)}")
        for a in agents:
            elapsed = int(time.time() - a.start_time) if a.start_time else 0
            lines.append(f"  Agent {a.agent_id}: {a.task.id} ({a.status}, {elapsed}s)")

        with open(status_file, "w") as f:
            f.write("\n".join(lines) + "\n")


# ── Claude agent spawner ─────────────────────────────────────────────

def build_prompt(task_file: str, spec_dir: str, learnings_file: str,
                 constitution: str, reference_files: list[str],
                 task: Task) -> str:
    """Build the agent prompt, targeting a specific task."""

    manifest_lines = []
    for f in reference_files:
        try:
            p = Path(f)
            line_count = sum(1 for _ in p.open())
            heading = ""
            with p.open() as fh:
                for l in fh:
                    if l.startswith('#'):
                        heading = l.lstrip('#').strip()
                        break
            if not heading:
                with p.open() as fh:
                    heading = fh.readline().strip() or "(no heading)"
            manifest_lines.append(f"- `{f}` ({line_count} lines) — {heading}")
        except Exception:
            manifest_lines.append(f"- `{f}` — (unreadable)")

    manifest = "\n".join(manifest_lines)

    prompt = f"""You are an implementation agent for a spec-kit project. Your job is to execute exactly ONE task from the task list, then stop.

## Your assigned task

You are assigned task **{task.id}**: {task.description}

This task is in phase **{task.phase}**.

## Step 1: Read context

Read these files first — they are small and always needed:
- `{task_file}` — the task list (your assigned task is {task.id})
- `CLAUDE.md` (if it exists) — build/test commands and project conventions

**Validation state directory**: `{spec_dir}/validate/` — if a task has failed validation before, its history is in `{spec_dir}/validate/<TASK_ID>/`.
"""

    if Path(learnings_file).exists():
        prompt += f"- `{learnings_file}` — discoveries from previous runs (read this to avoid repeating mistakes)\n"

    prompt += f"""
## Step 1b: Load only the context you need

Below is a manifest of available reference files with summaries. **Do NOT read all of them.** Based on your specific task, select and read ONLY the files relevant to what you need to implement:

{manifest}

**Selection guide:**
- Setup/config tasks → usually just `CLAUDE.md` is enough
- Tasks referencing data models or schemas → read `data-model.md`
- Tasks implementing API endpoints → read the relevant contract file
- Tasks requiring architectural context → read `constitution.md` and/or `plan.md`
- Tasks referencing feature behavior → read `spec.md`
- Phase-fix tasks → read ALL files in the referenced `{spec_dir}/validate/<phase>/` directory plus `test-logs/`
- When in doubt, read `plan.md` — it's the most useful general reference

## Step 2: Execute your assigned task ({task.id})

You have been assigned **{task.id}**. Do not pick a different task.

### If the task is a phase-fix task (e.g., `phase3-fix1`, `phase3-fix2`)

Phase-fix tasks are generated by the phase validation loop. They reference a validation history directory:

1. Read ALL files in the referenced `{spec_dir}/validate/<phase>/` directory
2. Read `test-logs/` for the latest structured failure output
3. Diagnose the root cause. **Tests are the spec** — fix the code, not the tests. Exception: if a test is genuinely wrong, fix it with a comment.
4. Fix the code, then proceed to Step 3 (phase validation).

### Otherwise (normal implementation task)

- Read any source files referenced in the task description
- Implement exactly what the task describes — follow the spec, plan, contracts, and data-model
- If the task says to write tests, write them and verify they FAIL before writing any implementation
- If the constitution exists, ensure your implementation complies with all principles
- If something is unclear or you need a design decision, write the question to `BLOCKED.md` and STOP immediately

## Step 3: Phase validation (only at phase boundaries)

Check whether this task is the **last unchecked task in its phase**. If it is NOT the last task, skip to Step 4.

If this IS the last task in the phase (or a phase-fix task), run the project's build and test commands:
- Check CLAUDE.md for the exact commands
- For early phases, the build/test infrastructure may not exist yet — verify what you can

### If validation passes
Continue to Step 4.

### If validation fails — write state and append a phase-fix task

Do NOT attempt to fix failures yourself. Instead:

1. Create a validation run file at `{spec_dir}/validate/<phase>/<N>.md`
2. If fewer than 10 attempts: append a fix task to `{task_file}` at the end of the current phase
3. If 10 attempts already: write `BLOCKED.md` and stop

## Step 4: Self-review

Before marking complete, review your own changes:
1. Run `git diff` to see everything you changed
2. Check for leftover debug code, missing error handling, security issues
3. Fix anything you find

## Step 5: Record learnings

Append any useful discoveries to `{learnings_file}`.

## Step 6: Mark complete and commit

1. In `{task_file}`, change task {task.id}'s `- [ ]` to `- [x]`
2. Commit all changes with a conventional commit message including the task ID (e.g., `feat({task.id}): ...`)
3. If this was the LAST unchecked task, append a REVIEW phase

## Rules

- Execute your assigned task ({task.id}) ONLY, then stop
- Do NOT skip ahead to later phases
- Do NOT refactor unrelated code
- Do NOT read ROUTER.md or load any skills
- Do NOT use the Skill tool
- If you need user input, write to BLOCKED.md and stop immediately
- Prefer minimal changes that satisfy the task description
- If a task is unnecessary (already done, obsolete), mark it `- [~]` with a reason and move to the next task
- ALWAYS update `{learnings_file}` if you discovered anything non-obvious
"""
    return prompt


def build_review_prompt(spec_dir: str, task_file: str, skills_dir: str) -> str:
    """Build the review prompt (mirrors original run-tasks.sh logic)."""
    # Find base SHA
    try:
        result = subprocess.run(
            ["git", "log", "--all", "--oneline",
             "--grep=feat(T0\\|test(T0\\|fix(T0\\|refactor(T0\\|docs(T0",
             "--reverse", "--format=%H"],
            capture_output=True, text=True, timeout=10
        )
        commits = result.stdout.strip().split("\n")
        if commits and commits[0]:
            base_sha = commits[0] + "~1"
        else:
            raise ValueError("no commits")
    except Exception:
        try:
            result = subprocess.run(
                ["git", "merge-base", "HEAD", "main"],
                capture_output=True, text=True, timeout=10
            )
            base_sha = result.stdout.strip() or "HEAD~20"
        except Exception:
            base_sha = "HEAD~20"

    # Pick review skill
    review_skill = Path(skills_dir) / "code-review" / "SKILL.md"
    pkg = Path("package.json")
    if pkg.exists():
        pkg_text = pkg.read_text()
        if '"react"' in pkg_text:
            review_skill = Path(skills_dir) / "code-review-react" / "SKILL.md"
        elif Path("tsconfig.json").exists() or Path("src/index.ts").exists():
            review_skill = Path(skills_dir) / "code-review-node" / "SKILL.md"

    skill_content = ""
    if review_skill.exists():
        text = review_skill.read_text()
        # Skip YAML frontmatter
        parts = text.split("---", 2)
        if len(parts) >= 3:
            skill_content = parts[2]
        else:
            skill_content = text

    return f"""You are a code review agent. All implementation tasks for this feature are complete.

## Base commit
```
{base_sha}
```

Run: `git diff {base_sha}...HEAD`

## Review instructions

Follow the code review skill instructions below. Your review is a 4-step process:

### Step 1: Auto-implement necessary fixes
Review the diff and **fix directly in the code**: bugs, security vulnerabilities, correctness issues, broken error handling, missing input validation, and anything that would cause runtime failures or data loss. Commit each fix.

### Step 2: Write REVIEW-TODO.md
Write `{spec_dir}/REVIEW-TODO.md` with optional improvements that are helpful but not necessary: refactoring suggestions, performance optimizations, better naming, additional test coverage, documentation gaps, code style. Each item includes: file, line range, what to improve, and why.

### Step 3: Write REVIEW.md
Write `{spec_dir}/REVIEW.md` with a summary of all findings: what was auto-fixed (with commit refs), what was deferred to REVIEW-TODO.md, and overall assessment.

### Step 4: Fix-validate loop
After applying fixes, run the project's test suite. If tests fail (your review fixes broke something), enter the fix-validate loop: read `test-logs/` (if available) or test output, diagnose, fix, re-run. Tests MUST pass before marking the review complete. After 10 failed attempts, write `BLOCKED.md`.

When all steps are done and tests pass, mark the REVIEW task complete in `{task_file}` and commit with: `docs: code review for {Path(spec_dir).name}`

---

{skill_content}
"""


def spawn_agent(task: Task, prompt: str, log_path: Path,
                stderr_path: Path) -> subprocess.Popen:
    """Spawn a claude CLI process for the given task."""
    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--model", "opus",
        "--verbose",
        "--output-format", "stream-json",
        "-p", prompt,
    ]

    log_path.parent.mkdir(parents=True, exist_ok=True)

    stdout_file = open(log_path, "w")
    stderr_file = open(stderr_path, "w")

    proc = subprocess.Popen(
        cmd,
        stdout=stdout_file,
        stderr=stderr_file,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc


def read_stream_output(log_path: Path, last_pos: int) -> tuple[list[str], int, Optional[int]]:
    """Read new JSON lines from a stream-json log file.
    Returns (display_lines, new_position, exit_code_if_result)."""
    lines = []
    exit_code = None
    try:
        with open(log_path, "r") as f:
            f.seek(last_pos)
            new_data = f.read()
            new_pos = f.tell()

        for raw_line in new_data.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                msg = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "assistant" and msg.get("message", {}).get("content"):
                for block in msg["message"]["content"]:
                    if block.get("type") == "text" and block.get("text"):
                        for tl in block["text"].splitlines():
                            lines.append(tl)
                    elif block.get("type") == "tool_use":
                        inp = block.get("input", {})
                        name = block.get("name", "?")
                        detail = ""
                        if name == "Bash":
                            detail = inp.get("command", "")[:60]
                        elif name in ("Read", "Write", "Edit"):
                            detail = inp.get("file_path", "")
                        elif name in ("Glob", "Grep"):
                            detail = inp.get("pattern", "")
                        elif name == "Agent":
                            detail = inp.get("description", "")
                        else:
                            detail = json.dumps(inp)[:60]
                        lines.append(f"[{name}] {detail}")
            elif msg.get("type") == "result":
                if msg.get("result"):
                    lines.append(msg["result"])
                exit_code = 1 if msg.get("is_error") else 0
            elif msg.get("type") == "error":
                err_msg = msg.get("error", {}).get("message", str(msg))
                lines.append(f"ERROR: {err_msg}")
                exit_code = 2

        return lines, new_pos, exit_code
    except FileNotFoundError:
        return [], last_pos, None


def check_rate_limited(stderr_path: Path) -> bool:
    """Check if the agent hit a rate limit."""
    try:
        text = stderr_path.read_text()
        return bool(re.search(r'rate.?limit|usage.?limit|429|quota|capacity', text, re.IGNORECASE))
    except Exception:
        return False


# ── Main orchestrator ─────────────────────────────────────────────────

class Runner:
    def __init__(self, spec_dirs: list[str], max_runs: int, headless: bool, max_parallel: int, layout: str = "vertical"):
        self.spec_dirs = spec_dirs
        self.max_runs = max_runs
        self.headless = headless
        self.max_parallel = max_parallel
        self.layout = layout
        self.script_dir = Path(__file__).parent
        self.skills_dir = self.script_dir.parent
        self.blocked_file = Path("BLOCKED.md")
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        self.timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._shutdown = threading.Event()
        self.agents: list[AgentSlot] = []
        self.agent_counter = 0
        self._lock = threading.Lock()

        self.logger: Optional[HeadlessLogger] = None
        self.tui: Optional[TUI] = None

        if headless:
            self.logger = HeadlessLogger(self.log_dir / f"parallel-{self.timestamp}")
        else:
            pass  # TUI created per-feature

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        if self.logger:
            self.logger.log(msg)
        elif self.tui:
            pass  # TUI handles display
        else:
            print(line, flush=True)

    def run(self):
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        # Check for leftover BLOCKED.md
        if self.blocked_file.exists():
            print("=== BLOCKED ===")
            print(f"The agent has a pending question in {self.blocked_file}:")
            print(self.blocked_file.read_text())
            print("Edit the file with your answer, then delete it and re-run.")
            sys.exit(2)

        for spec_dir in self.spec_dirs:
            if self._shutdown.is_set():
                break
            self._run_feature(spec_dir)

        self._print_summary()

    def _handle_signal(self, sig, frame):
        self._shutdown.set()
        # Kill all running agents
        with self._lock:
            for agent in self.agents:
                if agent.process and agent.process.poll() is None:
                    try:
                        os.killpg(os.getpgid(agent.process.pid), signal.SIGTERM)
                    except Exception:
                        try:
                            agent.process.kill()
                        except Exception:
                            pass
        if self.tui:
            self.tui.stop()
        print("\nInterrupted.")
        sys.exit(130)

    def _run_feature(self, spec_dir: str):
        task_file = Path(spec_dir) / "tasks.md"
        learnings_file = Path(spec_dir) / "learnings.md"
        constitution = Path(".specify/memory/constitution.md")

        if not task_file.exists():
            self.log(f"Skipping {spec_dir} — no tasks.md")
            return

        # Parse tasks
        phases, phase_deps = parse_task_file(task_file)
        scheduler = Scheduler(phases, phase_deps)

        if scheduler.all_complete():
            self.log(f"Skipping {spec_dir} — all tasks complete")
            return

        # Initialize learnings
        if not learnings_file.exists():
            learnings_file.write_text(
                "# Learnings\n\nDiscoveries, gotchas, and decisions recorded by the implementation agent across runs.\n\n---\n\n"
            )

        # Build reference file list
        reference_files = []
        if constitution.exists():
            reference_files.append(str(constitution))
        for f in ["spec.md", "plan.md", "data-model.md", "research.md", "quickstart.md"]:
            p = Path(spec_dir) / f
            if p.exists():
                reference_files.append(str(p))
        contracts_dir = Path(spec_dir) / "contracts"
        if contracts_dir.is_dir():
            reference_files.extend(str(f) for f in sorted(contracts_dir.glob("*.md")))

        # Ensure validate dir
        (Path(spec_dir) / "validate").mkdir(parents=True, exist_ok=True)

        # Setup TUI for this feature
        if not self.headless:
            self.tui = TUI(phases, phase_deps, layout=self.layout)
            self.tui.start()

        self.log(f"=== Feature: {Path(spec_dir).name} ===")
        self.log(f"Remaining: {scheduler.remaining_count()} | Completed: {scheduler.completed_count()}")

        consecutive_noop = 0
        max_consecutive_noop = 5
        total_runs = 0

        while not self._shutdown.is_set() and total_runs < self.max_runs:
            # Re-parse task file to pick up changes from agents
            phases, phase_deps = parse_task_file(task_file)
            scheduler = Scheduler(phases, phase_deps)

            if self.tui:
                self.tui.phases = phases
                self.tui.phase_deps = phase_deps

            if scheduler.all_complete():
                self.log("All tasks complete!")
                break

            # Check BLOCKED.md
            if self.blocked_file.exists():
                self.log("BLOCKED — agent needs input")
                if self.tui:
                    self.tui.stop()
                print(f"\n=== BLOCKED ===\n{self.blocked_file.read_text()}")
                print("Edit the file with your answer, delete it, then re-run.")
                sys.exit(2)

            # Get running task IDs
            with self._lock:
                running_ids = {a.task.id for a in self.agents}

            # Find ready tasks
            ready = scheduler.get_ready_tasks(running_ids)

            # How many slots available?
            with self._lock:
                current_running = len(self.agents)
            available_slots = self.max_parallel - current_running

            # Spawn new agents for ready tasks
            spawned = 0
            for task in ready:
                if available_slots <= 0:
                    break
                if task.id in running_ids:
                    continue

                # Check if it's a REVIEW task
                is_review = task.id == "REVIEW" or "REVIEW" in task.description

                if is_review:
                    prompt = build_review_prompt(spec_dir, str(task_file), str(self.skills_dir))
                else:
                    prompt = build_prompt(
                        str(task_file), spec_dir, str(learnings_file),
                        str(constitution), reference_files, task
                    )

                self.agent_counter += 1
                agent_id = self.agent_counter

                log_path = self.log_dir / f"agent-{agent_id}-{task.id}-{self.timestamp}.jsonl"
                stderr_path = self.log_dir / f"agent-{agent_id}-{task.id}-{self.timestamp}.stderr"

                self.log(f"Spawning Agent {agent_id} for task {task.id}: {task.description[:60]}")

                proc = spawn_agent(task, prompt, log_path, stderr_path)

                slot = AgentSlot(
                    agent_id=agent_id,
                    task=task,
                    process=proc,
                    pid=proc.pid,
                    start_time=time.time(),
                    log_file=log_path,
                    status="running",
                )

                with self._lock:
                    self.agents.append(slot)
                    running_ids.add(task.id)

                available_slots -= 1
                spawned += 1
                total_runs += 1

            # Update TUI
            if self.tui:
                with self._lock:
                    self.tui.update_agents(list(self.agents))
            if self.logger:
                with self._lock:
                    self.logger.write_status(phases, phase_deps, list(self.agents))

            # If nothing is running and nothing was spawned, we might be stuck
            with self._lock:
                nothing_happening = len(self.agents) == 0 and spawned == 0

            if nothing_happening:
                consecutive_noop += 1
                if consecutive_noop >= max_consecutive_noop:
                    self.log(f"Stopped — {max_consecutive_noop} iterations with no progress")
                    break
                self.log(f"No tasks ready (noop {consecutive_noop}/{max_consecutive_noop}). Waiting...")
                time.sleep(5)
                continue
            else:
                consecutive_noop = 0

            # Poll running agents
            self._poll_agents()

        # Wait for remaining agents to finish
        self._drain_agents()

        if self.tui:
            self.tui.stop()

    def _poll_agents(self):
        """Poll running agents, read output, detect completion."""
        # Track file read positions
        if not hasattr(self, '_read_positions'):
            self._read_positions = {}

        while not self._shutdown.is_set():
            with self._lock:
                if not self.agents:
                    break

            finished = []
            with self._lock:
                agents_snapshot = list(self.agents)

            for agent in agents_snapshot:
                if agent.log_file:
                    pos = self._read_positions.get(agent.agent_id, 0)
                    new_lines, new_pos, exit_code = read_stream_output(agent.log_file, pos)
                    self._read_positions[agent.agent_id] = new_pos

                    if new_lines:
                        agent.output_lines.extend(new_lines)
                        # Keep only last 200 lines
                        if len(agent.output_lines) > 200:
                            agent.output_lines = agent.output_lines[-200:]

                    if exit_code is not None:
                        agent.exit_code = exit_code

                # Check process status
                if agent.process and agent.process.poll() is not None:
                    rc = agent.process.returncode
                    stderr_path = self.log_dir / f"agent-{agent.agent_id}-{agent.task.id}-{self.timestamp}.stderr"

                    if rc == 0:
                        agent.status = "done"
                        self.log(f"Agent {agent.agent_id} ({agent.task.id}) completed successfully")
                    elif check_rate_limited(stderr_path):
                        agent.status = "rate_limited"
                        self.log(f"Agent {agent.agent_id} ({agent.task.id}) rate limited — will retry")
                    else:
                        agent.status = "failed"
                        self.log(f"Agent {agent.agent_id} ({agent.task.id}) failed (exit {rc})")

                    finished.append(agent)

            # Remove finished agents
            if finished:
                with self._lock:
                    self.agents = [a for a in self.agents if a not in finished]

                # Handle rate-limited agents — wait and re-queue
                for agent in finished:
                    if agent.status == "rate_limited":
                        self.log(f"Rate limited on {agent.task.id}. Waiting 60s before retry...")
                        time.sleep(60)
                        # Task stays PENDING, will be picked up next iteration

                # Update TUI
                if self.tui:
                    with self._lock:
                        self.tui.update_agents(list(self.agents))
                break  # Go back to main loop to re-parse and re-schedule

            # Update TUI with latest output
            if self.tui:
                with self._lock:
                    self.tui.update_agents(list(self.agents))

            time.sleep(1)

    def _drain_agents(self):
        """Wait for all running agents to finish."""
        while True:
            with self._lock:
                if not self.agents:
                    break
            self._poll_agents()
            time.sleep(1)

    def _print_summary(self):
        if self.tui:
            self.tui.stop()
            # Clear screen for final summary
            sys.stdout.write("\033[2J\033[H")

        print("\n" + "=" * 60)
        print("=== All features processed ===")
        print("=" * 60)

        for spec_dir in self.spec_dirs:
            task_file = Path(spec_dir) / "tasks.md"
            name = Path(spec_dir).name
            if not task_file.exists():
                print(f"  {name}: no tasks.md")
                continue
            phases, _ = parse_task_file(task_file)
            remaining = sum(1 for p in phases for t in p.tasks if t.status == TaskStatus.PENDING)
            completed = sum(1 for p in phases for t in p.tasks if t.status == TaskStatus.COMPLETE)
            blocked = sum(1 for p in phases for t in p.tasks if t.status == TaskStatus.BLOCKED)
            if remaining == 0:
                print(f"  {name}: COMPLETE ({completed} done, {blocked} blocked)")
            else:
                print(f"  {name}: {remaining} remaining, {completed} done, {blocked} blocked")


# ── Entry point ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Parallel spec-kit task runner with TUI dashboard"
    )
    parser.add_argument("spec_dir", nargs="?", default="",
                        help="Specific spec directory (default: all in specs/)")
    parser.add_argument("max_runs", nargs="?", type=int, default=100,
                        help="Max agent spawns per feature (default: 100)")
    parser.add_argument("--headless", action="store_true",
                        help="No terminal UI; write all output to log files")
    parser.add_argument("--max-parallel", type=int, default=3,
                        help="Max concurrent agents (default: 3)")
    parser.add_argument("--layout", choices=["vertical", "grid"], default="vertical",
                        help="Agent pane layout: vertical (stacked, default) or grid (side-by-side)")

    args = parser.parse_args()

    # Resolve spec dirs
    if args.spec_dir:
        spec_dirs = [args.spec_dir]
    else:
        if not Path("specs").is_dir():
            print("Error: No specs/ directory found. Are you in a spec-kit project root?")
            sys.exit(1)
        spec_dirs = sorted(str(d) for d in Path("specs").iterdir() if d.is_dir())
        if not spec_dirs:
            print("Error: No feature directories found in specs/")
            sys.exit(1)

    runner = Runner(
        spec_dirs=spec_dirs,
        max_runs=args.max_runs,
        headless=args.headless,
        max_parallel=args.max_parallel,
        layout=args.layout,
    )
    runner.run()


if __name__ == "__main__":
    main()
