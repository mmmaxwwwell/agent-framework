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
import hashlib
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
# Phase reference: "Phase 2b (Retro Wiring)" → captures "2b"
_PHASE_REF_RE = re.compile(r'Phase\s+(\d+[a-zA-Z]?|[A-Za-z][\w-]*)(?:\s*\([^)]*\))?')
_ARROW_RE = re.compile(r'\s*(?:──?▶|->|→)\s*')



def slugify_phase(name: str) -> str:
    """Convert phase heading to a slug like 'phase1', 'phase2b-core'."""
    # Try to extract phase number (including letter suffixes like 2b)
    m = re.match(r'(?:Phase\s*)?(\d+[a-zA-Z]?)', name, re.IGNORECASE)
    if m:
        phase_id = m.group(1).lower()  # e.g. "2b"
        rest = name[m.end():].strip().strip(':').strip('-').strip('—').strip()
        slug = f"phase{phase_id}"
        if rest:
            rest_slug = re.sub(r'[^a-z0-9]+', '-', rest.lower()).strip('-')[:20]
            slug += f"-{rest_slug}"
        return slug
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:30] or "unknown"


def _extract_phase_number(slug: str) -> Optional[str]:
    """Extract the numeric part from a phase slug, e.g. 'phase2-core' -> '2', 'phase2b-foo' -> '2b'."""
    m = re.match(r'phase[- ]?(\d+[a-zA-Z]?)', slug, re.IGNORECASE)
    return m.group(1).lower() if m else None


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
            # Exit dep section only on a same-level or higher heading (## but not ###)
            if re.match(r'^##(?!#)\s', line):
                in_dep_section = False
            else:
                # Split line on arrows to get segments, then extract phase refs
                # Handles: Phase 1 ──▶ Phase 2 (foo) ──▶ Phase 3
                # Handles: Phase 6 + Phase 7 + Phase 8 ──▶ Phase 9
                segments = _ARROW_RE.split(line)
                if len(segments) >= 2:
                    for j in range(len(segments) - 1):
                        # Source segment may have "+" joined phases
                        src_ids = _PHASE_REF_RE.findall(segments[j])
                        dst_ids = _PHASE_REF_RE.findall(segments[j + 1])
                        # Each dst is the first phase ref in the next segment
                        if dst_ids:
                            dst = dst_ids[0]
                            for src in src_ids:
                                raw_deps.append((src, dst))
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
    """Determines which tasks are ready to run given current state.

    Phase lifecycle: tasks done → validate → review → re-validate → complete.
    A phase blocks downstream until the full lifecycle is done.
    """

    def __init__(self, phases: list[Phase], phase_deps: dict[str, list[str]],
                 validated_phases: Optional[set[str]] = None,
                 phase_states: Optional[dict[str, PhaseValidationState]] = None):
        self.phases = phases
        self.phase_deps = phase_deps
        self.phase_map = {p.slug: p for p in phases}
        self.task_map = {}
        for p in phases:
            for t in p.tasks:
                self.task_map[t.id] = t
        # Full lifecycle state per phase.
        self.phase_states: dict[str, PhaseValidationState] = phase_states or {}
        # Legacy compat: fully completed phases.
        self.validated_phases: set[str] = validated_phases or set()

    def _get_state(self, slug: str) -> PhaseValidationState:
        return self.phase_states.get(slug, PhaseValidationState())

    def phase_tasks_complete(self, slug: str) -> bool:
        """All tasks in a phase are done (ignoring validation)."""
        phase = self.phase_map.get(slug)
        if not phase:
            return True
        return all(t.status in (TaskStatus.COMPLETE, TaskStatus.SKIPPED) for t in phase.tasks)

    def phase_complete(self, slug: str) -> bool:
        """A phase is complete when validated and review is clean."""
        if not self.phase_tasks_complete(slug):
            return False
        state = self._get_state(slug)
        return state.complete or slug in self.validated_phases

    def phase_needs_validate_review(self, slug: str) -> bool:
        """Phase tasks are done and needs a combined validate+review agent."""
        if not self.phase_tasks_complete(slug):
            return False
        if slug in self.validated_phases:
            return False  # Legacy: already fully complete
        state = self._get_state(slug)
        if state.complete:
            return False
        return state.needs_validate_review

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
        """All tasks done AND all phases fully validated+reviewed."""
        tasks_done = all(
            t.status in (TaskStatus.COMPLETE, TaskStatus.SKIPPED)
            for p in self.phases
            for t in p.tasks
        )
        if not tasks_done:
            return False
        return all(self.phase_complete(p.slug) for p in self.phases)

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

    def phases_needing_validate_review(self) -> list[Phase]:
        """Return phases that need a combined validate+review agent."""
        return [p for p in self.phases if self.phase_needs_validate_review(p.slug)]


@dataclass
class PhaseValidationState:
    """Tracks the combined validate+review lifecycle for a phase.

    Pipeline: tasks done → validate+review(1) → validate+review(2) → complete.
    Each combined agent runs tests, then reviews the diff if tests pass.
    Cycle repeats if review applied fixes (need to re-validate those fixes).
    """
    validated: bool = False         # Tests passed (at least once)
    review_cycle: int = 0           # How many review cycles have completed
    review_clean: bool = False      # Latest review found nothing to fix

    @property
    def complete(self) -> bool:
        """Phase is complete when validated AND review is clean."""
        return self.validated and self.review_clean

    @property
    def needs_validate_review(self) -> bool:
        """Needs a combined validate+review agent."""
        if not self.validated:
            return True  # Never validated
        if self.review_clean:
            return False  # Already clean — done
        # Validated but never reviewed (review_cycle=0), or reviewed with
        # fixes (review_cycle>0, review_clean=False) — either way, need
        # a VR cycle.
        return True


def scan_phase_validation_states(spec_dir: str) -> dict[str, PhaseValidationState]:
    """Scan validate/ directory for the combined validate+review lifecycle.

    Pipeline: tasks done → validate+review(1) → validate+review(2) → complete.
    The combined agent writes both N.md (validation) and review-N.md (review)
    in a single pass.

    File conventions in validate/<phase>/:
      N.md              — validation attempt N (heading contains PASS or FAIL)
      review-N.md       — review cycle N (heading: REVIEW-CLEAN or REVIEW-FIXES)
    """
    states: dict[str, PhaseValidationState] = {}
    validate_dir = Path(spec_dir) / "validate"
    if not validate_dir.is_dir():
        return states
    for phase_dir in validate_dir.iterdir():
        if not phase_dir.is_dir():
            continue
        slug = phase_dir.name
        state = PhaseValidationState()

        # Collect all files
        review_files = sorted(phase_dir.glob("review-*.md"))
        validation_files = sorted(
            f for f in phase_dir.glob("*.md")
            if not f.name.startswith("review-")
        )

        # Check if any validation has passed
        for md_file in validation_files:
            try:
                text = md_file.read_text()
                for line in text.splitlines():
                    if line.startswith('#'):
                        if 'PASS' in line.upper():
                            state.validated = True
                        break
            except OSError:
                continue

        # Count review cycles and check if latest was clean
        state.review_cycle = len(review_files)
        if review_files:
            latest_review = review_files[-1]
            try:
                text = latest_review.read_text()
                for line in text.splitlines():
                    if line.startswith('#'):
                        if 'REVIEW-CLEAN' in line.upper():
                            state.review_clean = True
                        break
            except OSError:
                pass

        states[slug] = state
    return states


def scan_validated_phases(spec_dir: str) -> set[str]:
    """Return phases that have completed the full validation lifecycle."""
    states = scan_phase_validation_states(spec_dir)
    return {slug for slug, state in states.items() if state.complete}


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
                             max_height: int = 0,
                             draining: bool = False) -> list[str]:
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
    if draining:
        summary_parts.append(f"\033[33;1m⏻ DRAINING — no new tasks, waiting for agents to finish{RESET}")
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
    # Track line index for each running task, keyed by task ID
    active_lines_by_id: dict[str, int] = {}

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
                active_lines_by_id[task.id] = len(task_lines) - 1

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

    # Scroll to keep the most recently started task visible
    if active_lines_by_id:
        # Find the task that was started most recently
        latest_id = max(
            active_lines_by_id,
            key=lambda tid: next(
                (a.start_time for a in agents if a.task.id == tid), 0
            ),
        )
        center_line = active_lines_by_id[latest_id]
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

    def __init__(self, phases: list[Phase], phase_deps: dict[str, list[str]],
                 layout: str = "vertical", draining: Optional[threading.Event] = None):
        self.phases = phases
        self.phase_deps = phase_deps
        self.layout = layout
        self._draining = draining or threading.Event()
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
            self.phases, self.phase_deps, agents, cols, max_height=graph_budget,
            draining=self._draining.is_set(),
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

    # Detect nix environment
    nix_note = ""
    if (Path.cwd() / "flake.nix").exists():
        nix_note = """
**Environment**: This project uses Nix (`flake.nix`). Your PATH already includes all tools from the nix devshell — run commands directly (e.g. `node`, `npm`, `python3`, `pytest`, `uv`). Do NOT prefix commands with `nix develop --command`. Do NOT work around missing native deps with lazy imports or try/except — they are available. If a native dep is genuinely missing, it's a flake.nix issue, not a code issue.
"""

    prompt = f"""You are an implementation agent for a spec-kit project. Your job is to execute exactly ONE task from the task list, then stop.
{nix_note}
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

Phase-fix tasks are generated by the phase validation agent. They reference a validation history directory:

1. Read ALL files in the referenced `{spec_dir}/validate/<phase>/` directory
2. Read `test-logs/` for the latest structured failure output
3. Diagnose ALL root causes — there may be multiple independent failures. List every distinct failure before you start fixing.
4. Fix ALL failures, not just the first one. **Tests are the spec** — fix the code, not the tests. Exception: if a test is genuinely wrong, fix it with a comment.
5. After fixing, run the same test command that failed to verify ALL failures are resolved. If any remain, fix those too before marking complete.
6. Each fix→verify cycle costs a full agent spawn if you miss something — be thorough in a single pass.

### Otherwise (normal implementation task)

- Read any source files referenced in the task description
- Implement exactly what the task describes — follow the spec, plan, contracts, and data-model
- If the task says to write tests, write them and verify they FAIL before writing any implementation
- If the constitution exists, ensure your implementation complies with all principles
- If something is unclear or you need a design decision, write the question to `BLOCKED.md` and STOP immediately

**Note**: Phase validation (build/test at phase boundaries) is handled automatically by the runner — you do NOT need to run it.

## Step 3: Self-review

Before marking complete, review your own changes:
1. Run `git diff` to see everything you changed
2. Check for leftover debug code, missing error handling, security issues
3. Fix anything you find

## Step 4: Record learnings

Append any useful discoveries to `{learnings_file}`.

## Step 5: Mark complete and commit

1. In `{task_file}`, change task {task.id}'s `- [ ]` to `- [x]`
2. Commit all changes with a conventional commit message including the task ID (e.g., `feat({task.id}): ...`)

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


def build_validate_review_prompt(spec_dir: str, task_file: str, phase: Phase,
                                  learnings_file: str, skills_dir: str,
                                  review_cycle: int = 1) -> str:
    """Build a combined validate+review prompt.

    Single agent runs tests, then (if they pass) reviews the diff for bugs
    and fixes them.  Merges what used to be two separate agents (validate +
    review) into one spawn, halving the per-phase agent cost.

    If tests fail, the agent writes a FAIL record and appends a fix task
    (same as the old standalone validation agent).
    """
    phase_slug = phase.slug
    task_ids = ", ".join(t.id for t in phase.tasks)
    validate_dir = f"{spec_dir}/validate/{phase_slug}"

    # Count existing validation attempts (only non-review files)
    vdir = Path(validate_dir)
    existing_attempts = sorted(
        f for f in vdir.glob("*.md")
        if not f.name.startswith("review-")
    ) if vdir.exists() else []
    attempt_num = len(existing_attempts) + 1

    # Detect nix environment
    nix_note = ""
    if (Path.cwd() / "flake.nix").exists():
        nix_note = """
**Environment**: This project uses Nix (`flake.nix`). Your PATH already includes all tools from the nix devshell — run commands directly (e.g. `node`, `npm`, `python3`, `pytest`, `uv`). Do NOT prefix commands with `nix develop --command`. If tests fail due to missing native libraries (e.g. `libstdc++.so.6`, shared objects), that is a `flake.nix` issue — report it as an environment problem, not a code bug. Do NOT create fix tasks for environment-only failures.
"""

    # Determine diff scope for the review portion
    try:
        task_id_list = [t.id for t in phase.tasks]
        grep_pattern = "\\|".join(rf"\({tid}\)" for tid in task_id_list)
        result = subprocess.run(
            ["git", "log", "--all", "--oneline",
             f"--grep={grep_pattern}",
             "--reverse", "--format=%H"],
            capture_output=True, text=True, timeout=10
        )
        commits = [c for c in result.stdout.strip().split("\n") if c]
        if commits:
            base_sha = commits[0] + "~1"
        else:
            raise ValueError("no phase commits found")
    except Exception:
        try:
            result = subprocess.run(
                ["git", "merge-base", "HEAD", "main"],
                capture_output=True, text=True, timeout=10
            )
            base_sha = result.stdout.strip() or "HEAD~20"
        except Exception:
            base_sha = "HEAD~20"

    # For cycle 2+, find delta diff base from previous review commit
    full_base_sha = base_sha
    delta_mode = False
    if review_cycle > 1:
        try:
            prev_review = f"review #{review_cycle - 1} for {phase_slug}"
            result = subprocess.run(
                ["git", "log", "--all", "--oneline",
                 f"--grep={prev_review}", "-1", "--format=%H"],
                capture_output=True, text=True, timeout=10
            )
            prev_sha = result.stdout.strip()
            if prev_sha:
                base_sha = prev_sha
                delta_mode = True
        except Exception:
            pass

    # Build review skill content (full for cycle 1, compact for 2+)
    if review_cycle > 1:
        skill_section = """## Review checklist (compact — see prior reviews for full context)

Check the diff for: bugs, security vulnerabilities, incorrect logic, broken error handling, missing input validation, race conditions, resource leaks, and anything causing runtime failures or data loss.

**Only fix things that are clearly wrong.** No refactoring, renaming, style, tests, comments, or docs."""
    else:
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
            parts = text.split("---", 2)
            if len(parts) >= 3:
                skill_content = parts[2]
            else:
                skill_content = text

        skill_section = f"""## Review skill reference

Follow the code review skill instructions below.

---

{skill_content}"""

    # Build diff instructions
    if delta_mode:
        diff_section = f"""**Delta** (changes since your last review — start here):
```
git diff {base_sha}...HEAD
```

**Full phase diff** (for context on how new changes interact with earlier code):
```
git diff {full_base_sha}...HEAD
```

Run the delta diff first. Only consult the full diff if you need to understand how a fix interacts with surrounding phase code."""
    else:
        diff_section = f"""```
git diff {base_sha}...HEAD
```

Run that command to see the changes for this phase."""

    # Read prior review findings for context (cycle 2+)
    prior_section = ""
    if review_cycle > 1:
        review_dir = Path(spec_dir) / "validate" / phase_slug
        prior_reviews = ""
        if review_dir.exists():
            for rf in sorted(review_dir.glob("review-*.md")):
                try:
                    prior_reviews += f"\n### {rf.name}\n{rf.read_text()}\n"
                except OSError:
                    pass
        if prior_reviews:
            prior_section = f"""
## Prior review findings

Check if your prior fixes were applied correctly and look for any NEW issues — do not re-report issues that were already fixed.

{prior_reviews}
"""

    review_file = f"{validate_dir}/review-{review_cycle}.md"

    return f"""You are a phase validate+review agent for **{phase.name}** ({phase_slug}). Review cycle #{review_cycle}.

Your job has two parts: (1) run tests, (2) if tests pass, review the diff for bugs and fix them.
{nix_note}
## Context

- **Phase**: {phase.name} ({phase_slug})
- **Tasks completed in this phase**: {task_ids}
- **Task file**: `{task_file}`
- **Validation directory**: `{validate_dir}/`
- **Validation attempt**: #{attempt_num}

## Part 1: Validate

### Determine build/test commands

Read `CLAUDE.md` (if it exists) for the project's build and test commands. Common patterns:
- Node.js: `npm run build && npm test` or `npm run check`
- Python: `uv run pytest` or `pytest`
- Multi-language: check for phase-specific checkpoint commands in `{task_file}`

Also check for a **Checkpoint** line at the end of the phase in `{task_file}`.

### Run validation

Run the build/test commands. Capture all output.

**Code coverage is mandatory.** The test command MUST collect coverage (e.g. `c8` for Node native runner, `--coverage` for Jest/Vitest, `--cov` for pytest). If the project's test command does not include coverage flags, fix the test script in `package.json`/`CLAUDE.md`/equivalent to add them before running. Coverage output must appear in the terminal so it's visible in logs.

**Fix missing tools before reporting failure.** If a build/test command fails because a tool is not installed (e.g. `eslint: command not found`, `tsc: not found`, missing npm packages), YOU MUST install it — do not skip it or call it a "pre-existing issue":
- Missing npm package (referenced in scripts but not in devDependencies) → `npm install --save-dev <package> --ignore-scripts` to add it, then `npm rebuild <pkg>` only if native compilation needed
- Already in devDependencies but not installed → `npm install --ignore-scripts`
- Missing Python package → `uv add --dev <pkg>` or `uv sync --dev`
- Missing system tool (not an npm/pip package) → add it to `flake.nix` devShell and commit the change. The runner detects flake.nix modifications and automatically restarts inside the updated `nix develop` shell.
- Then re-run the command. Only report a failure if the command fails AFTER dependencies are installed.

**Important**: For early phases, the build/test infrastructure may not exist yet or may only cover a subset. Run what's available. If literally nothing can be validated yet, note this and pass.

### If tests FAIL — stop here

1. Create `{validate_dir}/{attempt_num}.md` with:
   ```
   # Phase {phase_slug} — Validation #{attempt_num}: FAIL

   **Date**: (current timestamp)
   **Commands run**: (what you ran)
   **Exit code**: (exit code)
   **Failures**: (summary of what failed)
   **Full output**: (relevant portions of stdout/stderr)
   ```
2. If {attempt_num} < 10: append a fix task to `{task_file}` at the end of phase "{phase.name}":
   `- [ ] {phase_slug}-fix{attempt_num} Fix phase validation failure: read {validate_dir}/ for failure history`
3. If {attempt_num} >= 10: write `BLOCKED.md` with the full failure history
4. **Do NOT proceed to Part 2.** Exit now.

### If tests PASS — write PASS record, then continue to Part 2

Create `{validate_dir}/{attempt_num}.md` with:
```
# Phase {phase_slug} — Validation #{attempt_num}: PASS

**Date**: (current timestamp)
**Commands run**: (what you ran)
**Result**: All checks passed.
```

## Part 2: Code Review (only if tests passed)

### Diff scope

{diff_section}
{prior_section}
### Review and fix

Scan the ENTIRE diff systematically and find ALL issues that MUST be fixed: bugs, security vulnerabilities, correctness issues, broken error handling, missing input validation, and anything that would cause runtime failures or data loss. Fix each one directly in the code and commit with a conventional commit message.

**Be exhaustive in a single pass.** Each review cycle costs a full agent spawn — finding one issue per pass wastes tokens. Review every file in the diff before committing any fixes, so you have the full picture.

**Only fix things that are clearly wrong.** Do not refactor, rename, reorganize, or improve code style. Do not add tests beyond what the task specified. Do not add comments or documentation. The bar is: "would this cause a bug, security issue, or data loss in production?"

### Re-run tests after fixes

If you made any code fixes, re-run the same test commands from Part 1 to verify your fixes don't break anything. If they do, fix the breakage before continuing.

### Write review record

Write `{review_file}` with one of two outcomes:

**If you made fixes:**
```markdown
# Phase {phase_slug} — Review #{review_cycle}: REVIEW-FIXES

**Date**: (timestamp)
**Fixes applied**:
- (list each fix: file, what was wrong, what you changed, commit SHA)

**Deferred** (optional improvements, not bugs):
- (list any nice-to-haves you noticed but did NOT fix)
```

**If you found nothing worth fixing:**
```markdown
# Phase {phase_slug} — Review #{review_cycle}: REVIEW-CLEAN

**Date**: (timestamp)
**Assessment**: Code is clean. No bugs, security issues, or correctness problems found.

**Deferred** (optional improvements, not bugs):
- (list any nice-to-haves, or "None")
```

Commit the review record: `docs: code review #{review_cycle} for {phase_slug}`

## Rules

- Do NOT read ROUTER.md or load any skills
- Do NOT use the Skill tool
- The heading of `{review_file}` MUST contain either `REVIEW-CLEAN` or `REVIEW-FIXES` — the runner parses this
- If `test-logs/` exists after running tests, include its contents in the validation record
- Run commands from the project root directory

{skill_section}
"""


# ── Network allowlist proxy ─────────────────────────────────────────────

# Default domains agents may connect to.  Everything else is blocked.
# Default domains agents may connect to.  Everything else is blocked
# at the DNS level (resolv.conf is neutered inside the sandbox).
# The CONNECT proxy resolves DNS on the host side for allowed domains.
#
# Note: Direct IP connections bypass this (can't prevent without root/eBPF).
# This stops all hostname-based exfil, which covers npm postinstall, pip
# install hooks, and any tool that uses standard DNS resolution.
_NETWORK_ALLOWLIST: list[str] = [
    # Claude API
    "api.anthropic.com",
    "claude.ai",
    # Package registries (needed for npm install, pip install, uv)
    "registry.npmjs.org",
    "pypi.org",
    "files.pythonhosted.org",
    # Nix
    "cache.nixos.org",
    # GitHub (for git clones in flake inputs, uv installs from git)
    "github.com",
    "objects.githubusercontent.com",
]

import socket as _socket


class _AllowlistProxy:
    """HTTPS CONNECT proxy on localhost with domain allowlist.

    Runs in a background thread.  Agents inside the sandbox set
    HTTPS_PROXY / HTTP_PROXY to http://127.0.0.1:<port>.  The proxy:

      1. Accepts a connection
      2. Reads the HTTP CONNECT request (e.g. "CONNECT api.anthropic.com:443")
      3. Checks the target host against the allowlist
      4. If allowed: resolves DNS dynamically on the HOST side, connects,
         replies 200, splices streams
      5. If denied: replies 403, closes

    DNS inside the sandbox is neutered (resolv.conf → 127.0.0.253), so
    direct hostname connections fail.  The only path out is through this
    proxy, which does its own resolution and enforces the allowlist.
    """

    def __init__(self, allowlist: list[str]):
        self.allowlist = set(allowlist)
        self.port: int = 0
        self._stop = threading.Event()
        self._server: Optional[_socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._server = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        self._server.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))  # OS picks a free port.
        self.port = self._server.getsockname()[1]
        self._server.listen(32)
        self._server.settimeout(1.0)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=3)

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except _socket.timeout:
                continue
            except OSError:
                break
            # Handle each connection in a thread to avoid blocking.
            threading.Thread(
                target=self._handle, args=(client,), daemon=True
            ).start()

    def _handle(self, client: _socket.socket):
        try:
            client.settimeout(30)
            # Read the CONNECT request line.
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 8192:
                chunk = client.recv(4096)
                if not chunk:
                    return
                data += chunk

            first_line = data.split(b"\r\n")[0].decode("ascii", errors="replace")
            # Expected: "CONNECT host:port HTTP/1.1"
            parts = first_line.split()
            if len(parts) < 2 or parts[0] != "CONNECT":
                client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                return

            target = parts[1]  # e.g. "api.anthropic.com:443"
            host = target.rsplit(":", 1)[0]
            port = int(target.rsplit(":", 1)[1]) if ":" in target else 443

            # Check allowlist.
            if host not in self.allowlist:
                client.sendall(
                    f"HTTP/1.1 403 Forbidden\r\nX-Blocked-Host: {host}\r\n\r\n".encode()
                )
                return

            # Resolve DNS dynamically and connect.
            try:
                upstream = _socket.create_connection((host, port), timeout=10)
            except (OSError, _socket.timeout):
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                return

            # Tell the client the tunnel is open.
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

            # Splice data in both directions.
            self._splice(client, upstream)

        except Exception:
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _splice(self, a: _socket.socket, b: _socket.socket):
        """Bidirectional data copy until either side closes."""
        import select as _sel

        a.setblocking(False)
        b.setblocking(False)
        try:
            while not self._stop.is_set():
                readable, _, _ = _sel.select([a, b], [], [], 1.0)
                for sock in readable:
                    try:
                        data = sock.recv(65536)
                    except (BlockingIOError, ConnectionResetError):
                        continue
                    if not data:
                        return
                    other = b if sock is a else a
                    try:
                        other.sendall(data)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
        finally:
            try:
                a.close()
            except OSError:
                pass
            try:
                b.close()
            except OSError:
                pass


# ── Sandbox ────────────────────────────────────────────────────────────

# Resolved once at import time; overwritten by main() after arg parsing.
_sandbox_enabled: bool = True
_bwrap_path: Optional[str] = None
_proxy: Optional[_AllowlistProxy] = None


def _detect_bwrap() -> Optional[str]:
    """Find bubblewrap binary. Claude's Nix wrapper bundles it."""
    path = shutil.which("bwrap")
    if path:
        return path
    # Claude's Nix closure includes bwrap — check its store path.
    claude_bin = shutil.which("claude")
    if claude_bin:
        resolved = Path(claude_bin).resolve()
        # Walk up to the Nix store entry and check for bwrap in PATH additions
        # from the wrapper script.  Simpler: just search common Nix bwrap paths.
        import glob as _glob
        candidates = _glob.glob("/nix/store/*-bubblewrap-*/bin/bwrap")
        if candidates:
            return candidates[0]
    return None


def _build_sandbox_cmd(project_dir: Path, inner_cmd: list[str]) -> list[str]:
    """Wrap *inner_cmd* in a bubblewrap sandbox with an allowlist filesystem.

    Mounts ONLY what is required:
      - /nix/store          (ro)  — all binaries, libs, Node runtime
      - project_dir         (rw)  — the sole mutation surface
      - /dev, /proc         (ro)  — required by processes
      - /tmp                (tmpfs) — scratch
      - ~/.gitconfig        (ro)  — author name/email for commits
      - /etc/resolv.conf    (ro)  — DNS resolution
      - /etc/hosts          (ro)  — localhost resolution (needed by test servers)
      - /etc/ssl/certs      (ro)  — TLS certificate bundle
      - /etc/static         (ro)  — NixOS resolv.conf / hosts symlink targets
      - ANTHROPIC_API_KEY   (env) — sole credential, passed as env var

    Nothing else is mounted: no home dir, no ~/.claude/, no ~/.ssh/,
    no cloud credentials, no global bin dirs outside /nix/store.
    """
    assert _bwrap_path, "bwrap not found — cannot sandbox"

    home = Path.home()
    project = str(project_dir.resolve())
    gitconfig = home / ".gitconfig"

    cmd: list[str] = [_bwrap_path, "--die-with-parent", "--unshare-pid"]

    # ── Allowlisted mounts (everything else is absent) ──

    # Nix store: all binaries, libraries, the Claude CLI, Node, git, etc.
    cmd += ["--ro-bind", "/nix/store", "/nix/store"]

    # Project directory: the ONLY writable surface.
    cmd += ["--bind", project, project]

    # Device and process filesystems.
    cmd += ["--dev", "/dev"]
    cmd += ["--proc", "/proc"]

    # Scratch space (ephemeral, vanishes on exit).
    cmd += ["--tmpfs", "/tmp"]

    # Minimal /usr and /bin so scripts with #!/usr/bin/env work.
    # These are read-only and contain only the Nix-managed symlinks.
    for d in ["/usr/bin", "/bin", "/run/current-system/sw/bin"]:
        if Path(d).is_dir():
            cmd += ["--ro-bind", d, d]

    # Git author config (name + email only, no credentials).
    if gitconfig.is_file():
        cmd += ["--ro-bind", str(gitconfig), str(gitconfig)]

    # DNS resolution — pass through real resolv.conf.
    # NOTE: Node.js built-in fetch (undici) does not honor HTTPS_PROXY,
    # so we cannot neuter DNS and rely on a proxy.  Instead we pass real
    # DNS through and rely on the filesystem sandbox + network proxy as
    # defense in depth.  The proxy is advisory (blocks hostname-based
    # connections from tools that DO honor *_PROXY env vars like curl,
    # pip, npm).
    for etc_file in ["/etc/resolv.conf", "/etc/hosts"]:
        if Path(etc_file).exists():
            cmd += ["--ro-bind", etc_file, etc_file]
    if Path("/etc/static").is_dir():
        cmd += ["--ro-bind", "/etc/static", "/etc/static"]

    # SSL/TLS certificates for HTTPS API calls (proxy connections still need TLS).
    for cert_dir in ["/etc/ssl/certs", "/etc/ssl", "/etc/pki"]:
        if Path(cert_dir).is_dir():
            cmd += ["--ro-bind", cert_dir, cert_dir]
            break

    # NSS/passwd so git and node can resolve the current user.
    for f in ["/etc/passwd", "/etc/group", "/etc/nsswitch.conf"]:
        if Path(f).exists():
            cmd += ["--ro-bind", f, f]

    # Nix daemon socket — read-only bind so agents can query the store
    # but cannot install packages to it.  `nix develop` inside the sandbox
    # will fail on store writes; agents should modify flake.nix and let
    # the runner re-enter the devShell outside the sandbox.
    nix_sock = "/nix/var/nix/daemon-socket"
    if Path(nix_sock).exists():
        cmd += ["--ro-bind", nix_sock, nix_sock]
    nix_db = "/nix/var/nix/db"
    if Path(nix_db).exists():
        cmd += ["--ro-bind", nix_db, nix_db]

    # A tmpfs home so processes that probe $HOME don't error.
    # Nothing from the real home is mounted except the explicit allowlist below.
    cmd += ["--tmpfs", str(home)]

    # Re-mount gitconfig inside the tmpfs home (the tmpfs shadows it).
    if gitconfig.is_file():
        cmd += ["--ro-bind", str(gitconfig), str(gitconfig)]
    # Re-mount project dir if it's under home (tmpfs shadows it).
    if project.startswith(str(home)):
        cmd += ["--bind", project, project]

    # Claude CLI auth: mount ONLY .credentials.json (read-only).
    # The CLI needs this for its OAuth flow (token refresh, proper headers).
    # Nothing else from ~/.claude/ is exposed.
    claude_creds = home / ".claude" / ".credentials.json"
    if claude_creds.is_file():
        claude_dir = home / ".claude"
        cmd += ["--dir", str(claude_dir)]
        cmd += ["--ro-bind", str(claude_creds), str(claude_creds)]

    # Claude CLI auth: credentials are passed via env vars set in the
    # subprocess environment (Popen env=), NOT via bwrap --setenv, to
    # avoid leaking tokens in /proc/*/cmdline.  See spawn_agent().

    # ── Environment ──
    # All env vars (credentials, PATH, HOME, SSL) are passed via Popen(env=)
    # in spawn_agent(), NOT via bwrap --setenv, to keep them out of
    # /proc/*/cmdline.  Only --chdir is set here.

    cmd += ["--chdir", project]

    cmd += ["--"]
    cmd.extend(inner_cmd)
    return cmd


# ── Agent spawning ─────────────────────────────────────────────────────

def _build_sandbox_env() -> dict[str, str]:
    """Build a minimal environment for sandboxed agents.

    Credentials are passed here (via Popen env=) instead of bwrap --setenv
    so they don't appear in /proc/*/cmdline of the bwrap process.
    """
    home = Path.home()
    # Inherit PATH from the parent process so nix develop tools (node,
    # python, npm, pytest, etc.) are available inside the sandbox.  Fall
    # back to a minimal system PATH if PATH is somehow unset.
    env: dict[str, str] = {
        "HOME": str(home),
        "USER": os.environ.get("USER", "sandbox"),
        "PATH": os.environ.get("PATH", "/run/current-system/sw/bin:/usr/bin:/bin"),
    }

    # Auth: the CLI needs ~/.claude/.credentials.json for its full OAuth
    # flow (token refresh, proper headers).  Passing the token as an env
    # var doesn't work — the API rejects bare OAuth tokens.
    # The credentials file is mounted read-only by _build_sandbox_cmd().

    # API key fallback (alternative auth path).
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key

    # SSL certs for Node/Python HTTPS.
    for var in ["SSL_CERT_FILE", "NIX_SSL_CERT_FILE"]:
        val = os.environ.get(var)
        if val:
            env[var] = val

    # Network proxy — all HTTPS traffic routed through the allowlist proxy.
    # DNS is neutered inside the sandbox, so hostname connections only work
    # through this proxy (which resolves DNS on the host side).
    if _proxy and _proxy.port:
        proxy_url = f"http://127.0.0.1:{_proxy.port}"
        env["HTTPS_PROXY"] = proxy_url
        env["HTTP_PROXY"] = proxy_url
        env["ALL_PROXY"] = proxy_url

    return env


def spawn_agent(task: Task, prompt: str, log_path: Path,
                stderr_path: Path) -> subprocess.Popen:
    """Spawn a claude CLI process for the given task.

    When sandboxing is enabled, the process runs inside bubblewrap with
    an allowlist-only filesystem.  The OAuth token is passed via a
    one-shot file descriptor:

      1. Runner creates a pipe (r_fd, w_fd)
      2. Writes token to w_fd, closes w_fd
      3. r_fd is inherited by the child (close_fds=False, pass_fds)
      4. CLI reads token from /proc/self/fd/<r_fd> — fd is now at EOF
      5. Any child process that later reads the fd gets nothing

    This means the token never appears in:
      - /proc/*/cmdline  (not a command-line arg)
      - /proc/*/environ  (not an env var)
      - The filesystem    (~/.claude/ is not mounted)

    The only window is between fork and the CLI's readFileSync — a race
    that's impractical to exploit.
    """
    claude_cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--model", "opus",
        "--verbose",
        "--output-format", "stream-json",
        "-p", prompt,
    ]

    cmd = claude_cmd

    env = None

    if _sandbox_enabled and _bwrap_path:
        project_dir = Path.cwd()
        cmd = _build_sandbox_cmd(project_dir, cmd)
        env = _build_sandbox_env()
    else:
        # Not sandboxed — still need a clean env to avoid CLAUDECODE
        # detection which makes the CLI refuse to start.
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        # Also inject auth token for non-sandbox mode.
        claude_creds = Path.home() / ".claude" / ".credentials.json"
        if claude_creds.is_file():
            try:
                creds = json.loads(claude_creds.read_text())
                tok = creds.get("claudeAiOauth", {}).get("accessToken", "")
                if tok and "ANTHROPIC_AUTH_TOKEN" not in env:
                    env["ANTHROPIC_AUTH_TOKEN"] = tok
            except (json.JSONDecodeError, OSError):
                pass

    log_path.parent.mkdir(parents=True, exist_ok=True)

    stdout_file = open(log_path, "w")
    stderr_file = open(stderr_path, "w")

    proc = subprocess.Popen(
        cmd,
        stdout=stdout_file,
        stderr=stderr_file,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
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
        self._draining = threading.Event()  # First Ctrl-C: finish running agents, don't spawn new ones
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

    def _cleanup_stale_run(self):
        """Kill any orphaned agents from a previous runner that crashed.

        Uses a pidfile to find the old runner's process group and kill it.
        """
        pidfile = self.log_dir / "runner.pid"
        if pidfile.exists():
            try:
                old_pid = int(pidfile.read_text().strip())
                # Check if the old process is still running.
                os.kill(old_pid, 0)
                # It's alive — kill its entire process group.
                self.log(f"Killing stale runner (PID {old_pid}) from previous run")
                try:
                    os.killpg(os.getpgid(old_pid), signal.SIGTERM)
                    time.sleep(2)
                    os.killpg(os.getpgid(old_pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            except (ValueError, ProcessLookupError, OSError):
                pass  # Stale pidfile, process already gone.

        # Write our own PID.
        pidfile.write_text(str(os.getpid()))

    def _remove_pidfile(self):
        pidfile = self.log_dir / "runner.pid"
        try:
            pidfile.unlink(missing_ok=True)
        except OSError:
            pass

    def run(self):
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        self._cleanup_stale_run()

        # Check for leftover BLOCKED.md
        if self.blocked_file.exists():
            print("=== BLOCKED ===")
            print(f"The agent has a pending question in {self.blocked_file}:")
            print(self.blocked_file.read_text())
            print("Edit the file with your answer, then delete it and re-run.")
            sys.exit(2)

        try:
            for spec_dir in self.spec_dirs:
                if self._shutdown.is_set() or self._draining.is_set():
                    break
                self._run_feature(spec_dir)
        finally:
            # Guarantee all agents are killed on ANY exit path:
            # normal completion, unhandled exception, KeyboardInterrupt.
            self._kill_all_agents()
            self._remove_pidfile()

        self._print_summary()

    def _handle_signal(self, sig, frame):
        if not self._draining.is_set():
            # First Ctrl-C → drain: finish running agents, don't spawn new ones
            self._draining.set()
            self.log("Ctrl-C — draining: waiting for running agents to finish, no new tasks")
            return
        # Second Ctrl-C → hard shutdown
        self._shutdown.set()
        self._kill_all_agents()
        self._remove_pidfile()
        if self.tui:
            self.tui.stop()
        print("\nInterrupted.")
        sys.exit(130)

    def _kill_all_agents(self, graceful_timeout: float = 5.0):
        """Terminate all running agents with SIGTERM → wait → SIGKILL escalation.

        Ensures no child processes leak, including bwrap sandbox children.
        """
        with self._lock:
            live = [a for a in self.agents
                    if a.process and a.process.poll() is None]

        if not live:
            return

        # Phase 1: SIGTERM to process groups (reaches bwrap children).
        for agent in live:
            try:
                os.killpg(os.getpgid(agent.process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        # Phase 2: Wait up to graceful_timeout for clean exit.
        deadline = time.monotonic() + graceful_timeout
        for agent in live:
            remaining = max(0, deadline - time.monotonic())
            try:
                agent.process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass

        # Phase 3: SIGKILL anything still alive.
        for agent in live:
            if agent.process.poll() is None:
                try:
                    os.killpg(os.getpgid(agent.process.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                try:
                    agent.process.kill()
                except (ProcessLookupError, OSError):
                    pass

        # Phase 4: Reap all zombies.
        for agent in live:
            try:
                agent.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

    def _run_feature(self, spec_dir: str):
        task_file = Path(spec_dir) / "tasks.md"
        learnings_file = Path(spec_dir) / "learnings.md"
        constitution = Path(".specify/memory/constitution.md")

        if not task_file.exists():
            self.log(f"Skipping {spec_dir} — no tasks.md")
            return

        # Parse tasks
        phases, phase_deps = parse_task_file(task_file)
        phase_states = scan_phase_validation_states(spec_dir)
        validated_phases = {s for s, st in phase_states.items() if st.complete}
        scheduler = Scheduler(phases, phase_deps, validated_phases, phase_states)

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

        # Scan for already-validated phases (from prior runs)
        validated_phases = scan_validated_phases(spec_dir)
        # Track which phases currently have a validate+review agent running
        vr_phases: set[str] = set()

        # Setup TUI for this feature
        if not self.headless:
            self.tui = TUI(phases, phase_deps, layout=self.layout, draining=self._draining)
            self.tui.start()

        self.log(f"=== Feature: {Path(spec_dir).name} ===")
        self.log(f"Remaining: {scheduler.remaining_count()} | Completed: {scheduler.completed_count()}")
        if validated_phases:
            self.log(f"Already validated: {', '.join(sorted(validated_phases))}")

        consecutive_noop = 0
        max_consecutive_noop = 5
        total_runs = 0

        # Track flake.nix hash so we can re-exec if an agent modifies it
        flake_path = Path.cwd() / "flake.nix"
        def _flake_hash() -> str:
            try:
                return hashlib.sha256(flake_path.read_bytes()).hexdigest()
            except FileNotFoundError:
                return ""
        flake_hash_at_start = _flake_hash()

        while not self._shutdown.is_set() and total_runs < self.max_runs:
            # If an agent modified flake.nix, drain and re-exec inside
            # the new nix develop shell so updated tools are on PATH.
            if flake_path.exists() and _flake_hash() != flake_hash_at_start:
                self.log("flake.nix changed — draining agents and restarting inside new nix develop shell")
                self._draining.set()
                self._drain_agents()
                if self.tui:
                    self.tui.stop()
                os.execvp("nix", [
                    "nix", "develop", "--command",
                    sys.executable, *sys.argv,
                ])
                # execvp replaces the process — this line is never reached

            # Re-parse task file to pick up changes from agents
            phases, phase_deps = parse_task_file(task_file)
            # Re-scan phase validation states (validation/review/re-validation lifecycle)
            phase_states = scan_phase_validation_states(spec_dir)
            validated_phases = {s for s, st in phase_states.items() if st.complete}
            scheduler = Scheduler(phases, phase_deps, validated_phases, phase_states)

            if self.tui:
                self.tui.phases = phases
                self.tui.phase_deps = phase_deps

            if scheduler.all_complete():
                self.log("All tasks complete!")
                break

            # Draining: don't spawn new tasks, just wait for running agents.
            if self._draining.is_set():
                with self._lock:
                    if not self.agents:
                        self.log("Drain complete — all agents finished")
                        break
                self._poll_agents()
                time.sleep(1)
                continue

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

            # ── Phase-boundary validate+review ────────────────────────
            # Single combined agent: runs tests, then reviews diff if tests
            # pass.  Replaces the old 3-section validate/review/revalidate.
            MAX_REVIEW_CYCLES = 2
            for phase in scheduler.phases_needing_validate_review():
                if phase.slug in vr_phases:
                    continue  # already has an agent running
                if available_slots <= 0:
                    break

                phase_vdir = Path(spec_dir) / "validate" / phase.slug
                phase_vdir.mkdir(parents=True, exist_ok=True)

                state = phase_states.get(phase.slug, PhaseValidationState())
                cycle = state.review_cycle + 1

                if cycle > MAX_REVIEW_CYCLES:
                    self.log(f"Review cycle cap ({MAX_REVIEW_CYCLES}) reached for {phase.name} — treating as clean")
                    review_file = phase_vdir / f"review-{cycle}.md"
                    review_file.write_text(
                        f"# Phase {phase.slug} — Review #{cycle}: REVIEW-CLEAN\n\n"
                        f"**Date**: {datetime.now().isoformat()}\n"
                        f"**Assessment**: Review cycle cap reached. Prior cycles addressed all critical issues.\n"
                    )
                    continue

                prompt = build_validate_review_prompt(
                    spec_dir, str(task_file), phase, str(learnings_file),
                    str(self.skills_dir), review_cycle=cycle
                )

                vr_task_id = f"VR-{phase.slug}-{cycle}"
                vr_task = Task(
                    id=vr_task_id,
                    description=f"Validate+review #{cycle}: {phase.name}",
                    phase=phase.slug,
                    parallel=False,
                    status=TaskStatus.RUNNING,
                    line_num=0,
                )

                self.agent_counter += 1
                agent_id = self.agent_counter

                log_path = self.log_dir / f"agent-{agent_id}-{vr_task_id}-{self.timestamp}.jsonl"
                stderr_path = self.log_dir / f"agent-{agent_id}-{vr_task_id}-{self.timestamp}.stderr"

                self.log(f"Spawning validate+review Agent {agent_id} (cycle {cycle}) for {phase.name}")

                proc = spawn_agent(vr_task, prompt, log_path, stderr_path)

                slot = AgentSlot(
                    agent_id=agent_id,
                    task=vr_task,
                    process=proc,
                    pid=proc.pid,
                    start_time=time.time(),
                    log_file=log_path,
                    status="running",
                )

                with self._lock:
                    self.agents.append(slot)

                vr_phases.add(phase.slug)
                available_slots -= 1
                spawned += 1
                total_runs += 1

            # Clean up vr_phases: remove phases whose agent has finished
            with self._lock:
                running_vr_slugs = {
                    a.task.phase for a in self.agents
                    if a.task.id.startswith("VR-")
                }
            vr_phases &= running_vr_slugs

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
                    # Diagnose why we're stuck
                    pending = scheduler.remaining_count()
                    completed = scheduler.completed_count()
                    blocked = scheduler.blocked_count()
                    unvalidated = [
                        p.slug for p in phases
                        if scheduler.phase_tasks_complete(p.slug)
                        and not scheduler.phase_complete(p.slug)
                    ]
                    self.log(f"  State: {completed} complete, {pending} pending, {blocked} blocked")
                    if unvalidated:
                        self.log(f"  Unvalidated phases (tasks done but validation missing): {', '.join(unvalidated)}")
                    unmet = [
                        f"{p.slug} (needs: {', '.join(d for d in phase_deps.get(p.slug, []) if not scheduler.phase_complete(d))})"
                        for p in phases
                        if not scheduler.phase_deps_met(p.slug)
                        and any(t.status == TaskStatus.PENDING for t in p.tasks)
                    ]
                    if unmet:
                        self.log(f"  Blocked by unmet deps: {', '.join(unmet)}")
                    break
                self.log(f"No tasks ready ({consecutive_noop}/{max_consecutive_noop} before exit). Waiting...")
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
        """Wait for all running agents to finish their current work.

        No timeout — agents doing legitimate work (long builds, large test
        suites) should not be killed arbitrarily.  The user can Ctrl-C to
        abort, which triggers _handle_signal → _kill_all_agents.
        """
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
    parser.add_argument("--no-sandbox", action="store_true",
                        help="Disable bubblewrap sandbox (not recommended)")

    args = parser.parse_args()

    # ── Sandbox setup ──
    global _sandbox_enabled, _bwrap_path, _proxy
    if args.no_sandbox:
        _sandbox_enabled = False
        print("⚠ Sandbox DISABLED by --no-sandbox flag", file=sys.stderr)
    else:
        _bwrap_path = _detect_bwrap()
        if _bwrap_path:
            _sandbox_enabled = True
            # Start the allowlist network proxy.
            _proxy = _AllowlistProxy(allowlist=_NETWORK_ALLOWLIST)
            _proxy.start()
            print(
                f"🔒 Sandbox enabled (bwrap: {_bwrap_path})\n"
                f"🌐 Network proxy on 127.0.0.1:{_proxy.port} "
                f"(allowlist: {', '.join(_NETWORK_ALLOWLIST)})",
                file=sys.stderr,
            )
        else:
            _sandbox_enabled = False
            print(
                "⚠ bubblewrap (bwrap) not found — running WITHOUT sandbox.\n"
                "  Install bwrap or use Claude's Nix package (which bundles it).",
                file=sys.stderr,
            )

    # ── Nix environment check ──
    if (Path.cwd() / "flake.nix").exists():
        in_nix = os.environ.get("IN_NIX_SHELL") or os.environ.get("DIRENV_DIR")
        if not in_nix:
            print(
                "⚠ This project has a flake.nix but you're not inside nix develop.\n"
                "  Agents will lack native dependencies (numpy, node, etc.).\n"
                "  Run: nix develop --command python3 " + " ".join(sys.argv),
                file=sys.stderr,
            )
            sys.exit(1)

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
    try:
        runner.run()
    finally:
        if _proxy:
            _proxy.stop()


if __name__ == "__main__":
    main()
