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
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


# ── Exceptions ─────────────────────────────────────────────────────────


class AgentAuthError(RuntimeError):
    """Raised when a sub-agent fails due to authentication (401/expired token)."""
    pass


# ── Build result ──────────────────────────────────────────────────────

class BuildResult(Enum):
    """Result of a build_and_install() call.

    OK            — build succeeded and app was installed.
    BUILD_FAILED  — compilation/build step failed (code issue).
    INSTALL_FAILED — build succeeded but install failed (infra issue,
                     e.g. emulator crashed, adb not connected).
    NOT_READY     — runtime not booted / not available.
    """
    OK = "ok"
    BUILD_FAILED = "build_failed"
    INSTALL_FAILED = "install_failed"
    NOT_READY = "not_ready"


# ── Data model ──────────────────────────────────────────────────────────

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    REWORK = "rework"
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
    capabilities: set[str] = field(default_factory=set)  # e.g. {"gh"} from [needs: gh]


@dataclass
class Phase:
    name: str
    slug: str
    tasks: list[Task] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # phase slugs this depends on


@dataclass
class SubAgentRecord:
    """Token/time snapshot of a completed sub-agent inside a CI loop."""
    agent_id: int
    label: str          # e.g. "fix-1-2", "validate-1-1", "diag-1"
    input_tokens: int
    output_tokens: int
    elapsed_s: int
    status: str         # "done" or "failed"


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
    attempt: int = 1  # which attempt this is for the task (1 = first try)
    input_tokens: int = 0     # cumulative input tokens (including cache)
    output_tokens: int = 0    # cumulative output tokens
    model: str = "opus"       # model requested at spawn time (for cost accounting)
    is_ci_loop: bool = False  # True for the virtual CI loop orchestrator slot
    sub_agent_history: list[SubAgentRecord] = field(default_factory=list)
    active_sub_agent_id: Optional[int] = None  # agent_id of currently running sub-agent


# ── Task file parser ───────────────────────────────────────────────────

TASK_RE = re.compile(
    r'^- \[(?P<check>[ x~?!])\]\s+'
    r'(?:(?P<id>[A-Za-z0-9_-]+(?:-fix\d+)?)\s+)?'
    r'(?:\[P\]\s+)?'
    r'(?P<desc>.+)$'
)
PARALLEL_RE = re.compile(r'\[P\]')
NEEDS_RE = re.compile(r'\[needs:\s*([^\]]+)\]')
PHASE_HEADING_RE = re.compile(r'^##\s+Phase\s*(?::?\s*\d*\s*[-–—:]?\s*)?(.+)$', re.IGNORECASE)
DEPENDENCY_SECTION_RE = re.compile(r'^##\s+(?:Phase\s+)?Dependencies', re.IGNORECASE)
# Phase reference: "Phase 2b (Retro Wiring)" → captures "2b"
_PHASE_REF_RE = re.compile(r'Phase\s+(\d+[a-zA-Z]?|[A-Za-z][\w-]*)(?:\s*\([^)]*\))?')
_ARROW_RE = re.compile(r'\s*(?:──?▶|->|→)\s*')
# Task ID reference: "T019" or "T019-T027" — captures the first task ID
_TASK_REF_RE = re.compile(r'T(\d+)(?:-T\d+)?')



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
    last_dep_dst: Optional[str] = None  # for continuation lines

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
                # Skip code fence markers, blank lines, and non-dependency subsections
                stripped = line.strip()
                if stripped.startswith('```') or not stripped:
                    continue
                # Stop parsing at non-dependency subsections (e.g. "Parallel Agent Strategy")
                if re.match(r'^###\s', line) and 'depend' not in line.lower():
                    in_dep_section = False
                    continue
                # Only parse lines that contain Phase references or look like
                # dep declarations (have parens with Phase labels).
                # Skip lines that are just task ID chains without Phase labels
                # (e.g., "Agent A: T001→T006 → T007→T011")
                if 'Phase' not in line and '(' not in line:
                    continue
                # Split line on arrows to get segments, then extract phase refs
                # Handles: Phase 1 ──▶ Phase 2 (foo) ──▶ Phase 3
                # Handles: Phase 6 + Phase 7 + Phase 8 ──▶ Phase 9
                # Handles: continuation lines like "                → Phase 5"
                #   (empty src → use last_dep_dst as source)
                # Handles: task ID refs like "T019-T027 → T045 (Phase 10)"
                #   (resolve task IDs to their phase)
                segments = _ARROW_RE.split(line)
                if len(segments) >= 2:
                    for j in range(len(segments) - 1):
                        src_segment = segments[j]
                        dst_segment = segments[j + 1]

                        # Extract phase refs from source — try Phase N first,
                        # then fall back to task ID → phase lookup
                        src_ids = _PHASE_REF_RE.findall(src_segment)
                        if not src_ids:
                            # Try task IDs: "T019-T027 + T039-T044"
                            task_ids = _TASK_REF_RE.findall(src_segment)
                            src_ids = [f"__task__T{tid}" for tid in task_ids]
                        if not src_ids and last_dep_dst:
                            # Continuation line: empty src → use last destination
                            src_ids = [last_dep_dst]

                        dst_ids = _PHASE_REF_RE.findall(dst_segment)
                        if not dst_ids:
                            task_ids = _TASK_REF_RE.findall(dst_segment)
                            dst_ids = [f"__task__T{tid}" for tid in task_ids]

                        if dst_ids:
                            dst = dst_ids[0]
                            last_dep_dst = dst
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
            elif check == '!':
                status = TaskStatus.REWORK
            else:
                status = TaskStatus.PENDING

            # Parse [needs: gh, ...] capability annotations
            caps: set[str] = set()
            needs_match = NEEDS_RE.search(line)
            if needs_match:
                caps = {c.strip().lower() for c in needs_match.group(1).split(',')}

            task = Task(
                id=task_id,
                description=desc,
                phase=current_phase.slug,
                parallel=is_parallel,
                status=status,
                line_num=i + 1,
                capabilities=caps,
            )
            current_phase.tasks.append(task)

    # Build lookup: phase number -> actual slug, and raw key -> actual slug
    num_to_slug: dict[str, str] = {}
    key_to_slug: dict[str, str] = {}
    task_to_phase: dict[str, str] = {}  # task ID -> phase slug
    for p in phases:
        num = _extract_phase_number(p.slug)
        if num:
            num_to_slug[num] = p.slug
        key_to_slug[p.slug] = p.slug
        for t in p.tasks:
            task_to_phase[t.id] = p.slug

    def resolve_key(key: str) -> Optional[str]:
        """Resolve a dependency key (e.g. '2', 'phase2', 'phase-2-core', '__task__T019') to an actual phase slug."""
        # Task ID reference from dep parsing
        if key.startswith("__task__"):
            tid = key[len("__task__"):]
            return task_to_phase.get(tid)
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

    # Resolve raw deps into actual phase slugs (deduplicate, remove self-deps)
    phase_deps: dict[str, list[str]] = {}
    for src_key, dst_key in raw_deps:
        src_slug = resolve_key(src_key)
        dst_slug = resolve_key(dst_key)
        if src_slug and dst_slug and src_slug != dst_slug:
            deps = phase_deps.setdefault(dst_slug, [])
            if src_slug not in deps:
                deps.append(src_slug)

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
        """A phase is complete when validated and review is clean.

        CI-loop phases are implicitly validated — CI passing IS the
        validation, so no validate/<phase>/ files are needed.
        """
        if not self.phase_tasks_complete(slug):
            return False
        # CI-loop phases: all tasks have ci-loop capability and are complete.
        # CI passing is the validation — no separate validate+review needed.
        phase = self.phase_map.get(slug)
        if phase and all("ci-loop" in t.capabilities for t in phase.tasks):
            return True
        state = self._get_state(slug)
        return state.complete or slug in self.validated_phases

    def phase_needs_validate_review(self, slug: str) -> bool:
        """Phase tasks are done and needs a combined validate+review agent."""
        if not self.phase_tasks_complete(slug):
            return False
        if slug in self.validated_phases:
            return False  # Legacy: already fully complete
        # CI-loop phases are self-validating — no VR agent needed
        phase = self.phase_map.get(slug)
        if phase and all("ci-loop" in t.capabilities for t in phase.tasks):
            return False
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

            # Within a phase, find ready tasks.
            # Rules:
            #   - [P] tasks can run concurrently with each other
            #   - A sequential task (no [P]) must wait for ALL preceding
            #     tasks (both [P] and sequential) to complete
            #   - A [P] task must wait for all preceding sequential tasks
            #     to complete, but can run alongside other [P] tasks
            has_incomplete_above = False
            has_incomplete_sequential_above = False
            for task in phase.tasks:
                if task.status in (TaskStatus.COMPLETE, TaskStatus.SKIPPED):
                    continue

                is_incomplete = (
                    task.id in running_ids
                    or task.status in (TaskStatus.PENDING, TaskStatus.REWORK)
                    or task.status == TaskStatus.BLOCKED
                )

                if is_incomplete and task.id in running_ids:
                    # Running — track it as incomplete but don't add to ready
                    has_incomplete_above = True
                    if not task.parallel:
                        has_incomplete_sequential_above = True
                    continue

                if task.status not in (TaskStatus.PENDING, TaskStatus.REWORK):
                    # Blocked or other non-ready state
                    has_incomplete_above = True
                    if not task.parallel:
                        has_incomplete_sequential_above = True
                    continue

                # Task is PENDING/REWORK and not running
                if not task.parallel:
                    # Sequential task: must wait for ALL preceding tasks
                    if has_incomplete_above:
                        break  # can't go past — blocks everything below
                    ready.append(task)
                    has_incomplete_above = True
                    has_incomplete_sequential_above = True
                else:
                    # [P] task: can run if no incomplete sequential task above
                    if not has_incomplete_sequential_above:
                        ready.append(task)
                        has_incomplete_above = True

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
            if t.status in (TaskStatus.PENDING, TaskStatus.REWORK)
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

    Pipeline: tasks done → validate+review(1) → validate+review(2) → runner-verify → complete.
    Each combined agent runs tests, then reviews the diff if tests pass.
    Cycle repeats if review applied fixes (need to re-validate those fixes).
    After review is clean, the runner independently executes test commands.
    """
    validated: bool = False         # Tests passed (at least once)
    review_cycle: int = 0           # How many review cycles have completed
    review_clean: bool = False      # Latest review found nothing to fix
    runner_verified: bool = False   # Runner independently re-ran tests

    @property
    def complete(self) -> bool:
        """Phase is complete when validated AND review clean AND runner verified."""
        return self.validated and self.review_clean and self.runner_verified

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

        # Check for runner-verified file (runner independently ran tests)
        runner_verified_file = phase_dir / "runner-verified.json"
        if runner_verified_file.exists():
            try:
                rv_data = json.loads(runner_verified_file.read_text())
                state.runner_verified = rv_data.get("passed", False)
            except (json.JSONDecodeError, OSError):
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
    TaskStatus.REWORK:   "↻",
}

STATUS_COLORS = {
    TaskStatus.PENDING:  "\033[37m",      # white
    TaskStatus.RUNNING:  "\033[33;1m",    # bold yellow
    TaskStatus.COMPLETE: "\033[32m",      # green
    TaskStatus.SKIPPED:  "\033[90m",      # gray
    TaskStatus.BLOCKED:  "\033[31m",      # red
    TaskStatus.FAILED:   "\033[31;1m",    # bold red
    TaskStatus.REWORK:   "\033[35m",      # magenta
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
    rework_tasks = sum(1 for p in phases for t in p.tasks if t.status == TaskStatus.REWORK)

    summary_parts = [f"{BOLD}TASKS{RESET} {done_tasks}/{total_tasks}"]
    if draining:
        summary_parts.append(f"\033[33;1m⏻ DRAINING — no new tasks, waiting for agents to finish{RESET}")
    if running_tasks:
        summary_parts.append(f"{STATUS_COLORS[TaskStatus.RUNNING]}◉ {running_tasks} running{RESET}")
    if rework_tasks:
        summary_parts.append(f"{STATUS_COLORS[TaskStatus.REWORK]}↻ {rework_tasks} rework{RESET}")
    if failed_tasks:
        summary_parts.append(f"{STATUS_COLORS[TaskStatus.FAILED]}✗ {failed_tasks} failed{RESET}")
    if blocked_tasks:
        summary_parts.append(f"{STATUS_COLORS[TaskStatus.BLOCKED]}⊗ {blocked_tasks} blocked{RESET}")
    header.append(" " + "  ".join(summary_parts))

    # Legend (compact)
    legend_parts = []
    for s in [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.COMPLETE,
              TaskStatus.SKIPPED, TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.REWORK]:
        legend_parts.append(f"{STATUS_COLORS[s]}{STATUS_SYMBOLS[s]} {s.value}{RESET}")
    header.append(" " + " ".join(legend_parts))

    # Running agents
    if agents:
        agent_strs = []
        for a in agents:
            elapsed = int(time.time() - a.start_time) if a.start_time else 0
            att = f" att#{a.attempt}" if a.attempt > 1 else ""
            tok = ""
            total_tok = a.input_tokens + a.output_tokens
            if total_tok > 0:
                tok = f" {total_tok // 1000}k tok"
            prefix = "CI Loop" if a.is_ci_loop else f"Agent {a.agent_id}"
            sub_info = ""
            if a.is_ci_loop and a.active_sub_agent_id is not None:
                sub_info = f" → Agent {a.active_sub_agent_id}"
            agent_strs.append(
                f"{STATUS_COLORS[TaskStatus.RUNNING]}{prefix}: {a.task.id}{att}{sub_info} ({elapsed}s{tok}){RESET}"
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
        att = f" att#{agent.attempt}" if agent.attempt > 1 else ""
        total_tok = agent.input_tokens + agent.output_tokens
        tok = f", {total_tok // 1000}k tok" if total_tok > 0 else ""
        prefix = "CI Loop" if agent.is_ci_loop else f"Agent {agent.agent_id}"
        sub_info = ""
        if agent.is_ci_loop and agent.active_sub_agent_id is not None:
            sub_info = f" → Agent {agent.active_sub_agent_id}"
        header = f"{prefix}: {agent.task.id}{att}{sub_info} ({agent.status}, {elapsed}s{tok})"
        pane_lines.append(f"{BOLD}{header[:pane_width]}{RESET}")

        # For CI loop slots, show sub-agent history as a compact breakdown
        if agent.is_ci_loop and agent.sub_agent_history:
            parts = []
            for rec in agent.sub_agent_history[-6:]:  # last 6 sub-agents
                rtok = (rec.input_tokens + rec.output_tokens) // 1000
                mark = "✓" if rec.status == "done" else "✗"
                parts.append(f"{mark} {rec.label} {rtok}k")
            hist_line = " │ ".join(parts)
            pane_lines.append(f"{hist_line[:pane_width]}")
        else:
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
            att = f" att#{a.attempt}" if a.attempt > 1 else ""
            total_tok = a.input_tokens + a.output_tokens
            tok = f", {total_tok // 1000}k tok" if total_tok > 0 else ""
            prefix = "CI Loop" if a.is_ci_loop else f"Agent {a.agent_id}"
            lines.append(f"  {prefix}: {a.task.id}{att} ({a.status}, {elapsed}s{tok})")
            if a.is_ci_loop and a.sub_agent_history:
                for rec in a.sub_agent_history:
                    rtok = (rec.input_tokens + rec.output_tokens) // 1000
                    mark = "✓" if rec.status == "done" else "✗"
                    lines.append(f"    {mark} Agent {rec.agent_id}: {rec.label} ({rec.elapsed_s}s, {rtok}k tok)")

        with open(status_file, "w") as f:
            f.write("\n".join(lines) + "\n")


# ── Context extraction helpers ───────────────────────────────────────

def _extract_phase_block(task_file: str, task: Task, all_phases: list[Phase]) -> str:
    """Extract only the task's phase block from tasks.md, plus a summary of other phases.

    Returns a trimmed version of tasks.md containing:
    - The approach line (first non-blank content line)
    - A compact summary of completed tasks in other phases (just IDs)
    - The full phase block for the task's phase
    """
    lines = Path(task_file).read_text().splitlines()
    result_lines = []
    current_phase_slug = None
    in_target_phase = False
    target_slug = task.phase

    # Find approach line (first content after the title)
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("**Approach**") or stripped.startswith("*Approach*"):
            result_lines.append(line)
            break
        # Also grab the title
        if stripped.startswith("# ") and not stripped.startswith("## "):
            result_lines.append(line)

    result_lines.append("")

    # Build compact summary of other phases
    for phase in all_phases:
        if phase.slug == target_slug:
            continue
        complete = [t for t in phase.tasks if t.status == TaskStatus.COMPLETE]
        pending = [t for t in phase.tasks if t.status == TaskStatus.PENDING]
        if complete and not pending:
            result_lines.append(f"## {phase.name} — all {len(complete)} tasks complete")
        elif complete:
            complete_ids = ", ".join(t.id for t in complete)
            pending_ids = ", ".join(t.id for t in pending)
            result_lines.append(f"## {phase.name} — done: {complete_ids} | pending: {pending_ids}")
        else:
            result_lines.append(f"## {phase.name} — not started ({len(phase.tasks)} tasks)")

    result_lines.append("")

    # Include full phase block for the target phase
    for line in lines:
        pm = PHASE_HEADING_RE.match(line)
        if pm:
            slug = slugify_phase(line.lstrip('#').strip())
            if slug == target_slug:
                in_target_phase = True
                result_lines.append(line)
                continue
            elif in_target_phase:
                break  # hit next phase heading
            continue
        if in_target_phase:
            result_lines.append(line)

    return "\n".join(result_lines)


def _extract_task_block(task_file: str, task_id: str) -> str:
    """Extract the full block for a single task from tasks.md.

    Returns the task header line plus all indented continuation lines
    (e.g., 'Done when:' criteria).  Returns empty string if not found.
    """
    lines = Path(task_file).read_text().splitlines()
    result: list[str] = []
    capturing = False
    task_re = re.compile(rf"^\s*-\s*\[.\]\s*{re.escape(task_id)}\b")

    for line in lines:
        if task_re.match(line):
            capturing = True
            result.append(line)
            continue
        if capturing:
            # Continuation lines are indented deeper than the task bullet
            if line.startswith("  ") and not re.match(r"^\s*-\s*\[.\]\s*T\d+", line):
                result.append(line)
            else:
                break

    return "\n".join(result)


def _extract_relevant_learnings(learnings_file: str, task: Task,
                                 all_phases: list[Phase],
                                 phase_deps: dict[str, list[str]]) -> str:
    """Extract only learnings sections relevant to the current task.

    Includes learnings from:
    - Tasks in the same phase (sibling context)
    - Tasks in upstream dependency phases
    Skips learnings from unrelated phases to reduce context.
    """
    path = Path(learnings_file)
    if not path.exists():
        return ""

    text = path.read_text()
    if not text.strip():
        return ""

    # Find which phases are relevant: current phase + upstream deps
    relevant_phases = {task.phase}
    # Walk dependency chain upward
    to_visit = list(phase_deps.get(task.phase, []))
    while to_visit:
        dep = to_visit.pop()
        if dep not in relevant_phases:
            relevant_phases.add(dep)
            to_visit.extend(phase_deps.get(dep, []))

    # Collect task IDs in relevant phases
    relevant_task_ids: set[str] = set()
    for phase in all_phases:
        if phase.slug in relevant_phases:
            for t in phase.tasks:
                relevant_task_ids.add(t.id)

    # Parse learnings by section (## T0XX — ...)
    sections = []
    current_section: list[str] = []
    current_task_id: Optional[str] = None
    header_line = None

    for line in text.splitlines():
        # Match section headers like "## T019 — SSH agent handler"
        if line.startswith("## T") or line.startswith("## t"):
            # Save previous section
            if current_task_id and current_section:
                sections.append((current_task_id, header_line, current_section))
            # Extract task ID
            parts = line.split("—")[0].split("–")[0].split("-")[0]
            tid_match = re.search(r'T\d+', parts, re.IGNORECASE)
            current_task_id = tid_match.group().upper() if tid_match else None
            header_line = line
            current_section = []
        elif current_task_id is not None:
            current_section.append(line)
        # Keep the file header
        elif line.startswith("# ") and not sections:
            pass  # skip the main title

    # Save last section
    if current_task_id and current_section:
        sections.append((current_task_id, header_line, current_section))

    if not sections:
        return text  # no structured sections, return as-is

    # Filter to relevant sections
    result_lines = ["# Learnings (filtered for your task)\n"]
    included = 0
    for tid, header, body in sections:
        if tid in relevant_task_ids:
            result_lines.append(header)
            result_lines.extend(body)
            included += 1

    if included == 0:
        return ""  # no relevant learnings

    skipped = len(sections) - included
    if skipped > 0:
        result_lines.append(f"\n*({skipped} learning sections from unrelated phases omitted)*\n")

    return "\n".join(result_lines)


def _prune_completed_learnings(learnings_file: str,
                               all_phases: list[Phase],
                               phase_deps: dict[str, list[str]],
                               validated_phases: set[str]) -> int:
    """Remove learnings for tasks in fully-validated phases with no pending dependents.

    A phase's learnings are pruned when:
    1. The phase itself is fully validated (tasks done + review clean)
    2. All phases that depend on it are also fully validated

    Returns the number of sections removed.
    """
    path = Path(learnings_file)
    if not path.exists():
        return 0

    text = path.read_text()
    if not text.strip():
        return 0

    # Build reverse dependency map: phase -> set of phases that depend on it
    downstream: dict[str, set[str]] = defaultdict(set)
    for slug, deps in phase_deps.items():
        for dep in deps:
            downstream[dep].add(slug)

    # A phase is prunable when it AND all its downstream dependents are validated
    prunable_phases: set[str] = set()
    for phase in all_phases:
        if phase.slug not in validated_phases:
            continue
        # Check all downstream phases are also validated
        all_downstream_done = all(
            d in validated_phases for d in downstream.get(phase.slug, set())
        )
        if all_downstream_done:
            prunable_phases.add(phase.slug)

    if not prunable_phases:
        return 0

    # Collect prunable task IDs
    prunable_task_ids: set[str] = set()
    for phase in all_phases:
        if phase.slug in prunable_phases:
            for t in phase.tasks:
                prunable_task_ids.add(t.id)

    if not prunable_task_ids:
        return 0

    # Parse and filter sections
    lines = text.splitlines()
    output_lines: list[str] = []
    current_section_lines: list[str] = []
    current_task_id: str | None = None
    in_header = True  # True until we see the first ## section
    pruned = 0

    for line in lines:
        if line.startswith("## T") or line.startswith("## t"):
            # Flush previous section
            if current_task_id is not None:
                if current_task_id in prunable_task_ids:
                    pruned += 1
                else:
                    output_lines.extend(current_section_lines)
            in_header = False
            # Start new section
            tid_match = re.search(r'T\d+', line.split("—")[0].split("–")[0].split("-")[0], re.IGNORECASE)
            current_task_id = tid_match.group().upper() if tid_match else None
            current_section_lines = [line]
        elif line.startswith("## "):
            # Non-task section header (e.g. "## phase6-pairing-flow-fix1")
            # Flush previous
            if current_task_id is not None:
                if current_task_id in prunable_task_ids:
                    pruned += 1
                else:
                    output_lines.extend(current_section_lines)
            # Treat as non-task section — always keep
            current_task_id = "__keep__"
            current_section_lines = [line]
        elif in_header:
            output_lines.append(line)
        else:
            current_section_lines.append(line)

    # Flush last section
    if current_task_id is not None:
        if current_task_id in prunable_task_ids:
            pruned += 1
        else:
            output_lines.extend(current_section_lines)

    if pruned > 0:
        # Clean up trailing blank lines, ensure file ends with newline
        result = "\n".join(output_lines).rstrip() + "\n"
        path.write_text(result)

    return pruned


# ── Claude agent spawner ─────────────────────────────────────────────

def build_prompt(task_file: str, spec_dir: str, learnings_file: str,
                 constitution: str, reference_files: list[str],
                 task: Task, attempt_history: Optional[list[dict]] = None,
                 all_phases: Optional[list[Phase]] = None,
                 phase_deps: Optional[dict[str, list[str]]] = None,
                 blocked_answer: Optional[str] = None) -> str:
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

    # ── Inline context: tasks (phase-filtered) and learnings ────────
    if all_phases:
        inline_tasks = _extract_phase_block(task_file, task, all_phases)
    else:
        inline_tasks = Path(task_file).read_text()

    if all_phases and phase_deps is not None:
        inline_learnings = _extract_relevant_learnings(
            learnings_file, task, all_phases, phase_deps
        )
    else:
        inline_learnings = ""
        if Path(learnings_file).exists():
            inline_learnings = Path(learnings_file).read_text()

    prompt = f"""You are an implementation agent for a spec-kit project. Your job is to execute exactly ONE task from the task list, then stop.
{nix_note}
## Your assigned task

You are assigned task **{task.id}**: {task.description}

This task is in phase **{task.phase}**.

## Step 1: Read context

Read `CLAUDE.md` (if it exists) for build/test commands and project conventions.

**Your task list** (phase-filtered — other phases shown as summaries):

<task-list>
{inline_tasks}
</task-list>
"""

    if inline_learnings.strip():
        prompt += f"""
**Learnings from prior tasks** (filtered to your phase and its dependencies):

<learnings>
{inline_learnings}
</learnings>
"""

    prompt += f"""
**Validation state directory**: `{spec_dir}/validate/` — if a task has failed validation before, its history is in `{spec_dir}/validate/<TASK_ID>/`.

## Step 1b: Load only the context you need

**Do NOT read `{task_file}` or `{learnings_file}`** — the relevant content is already included above.

Below is a manifest of available reference files. **Do NOT read these unless your task specifically requires them.** Most tasks only need the source files they're modifying plus `CLAUDE.md`.

{manifest}

**When to read a reference file** (be selective — each file read adds to your context):
- Tasks referencing data models or schemas → `data-model.md`
- Tasks implementing API endpoints → the relevant contract file
- Tasks requiring architectural context → `plan.md`
- Tasks referencing feature behavior → `spec.md`
- Phase-fix tasks → ALL files in `{spec_dir}/validate/<phase>/` plus `test-logs/`
- **Most implementation tasks do NOT need spec.md, plan.md, or data-model.md** — the task description contains what you need

## Step 2: Execute your assigned task ({task.id})

You have been assigned **{task.id}**. Do not pick a different task.

### If the task is a phase-fix task (e.g., `phase3-fix1`, `phase3-fix2`)

Phase-fix tasks are generated by the phase validation agent. They reference a validation history directory:

1. Read ALL files in the referenced `{spec_dir}/validate/<phase>/` directory — start with the LATEST validation record (highest number). Check the **Failure categories** section to see exactly which steps failed (build/test/lint/security).
2. Read `test-logs/` for the latest structured failure output.
3. **Check prior fix attempts**: If `{spec_dir}/validate/<phase>/` contains earlier FAIL records AND earlier fix tasks exist in the task list, read them to understand what was already tried. Do NOT repeat an approach that already failed — try a different strategy.
4. Diagnose ALL root causes — there may be multiple independent failures across different categories (e.g. 2 test failures + 3 lint errors). List every distinct failure before you start fixing.
5. Fix ALL failures, not just the first one. **Tests are the spec** — fix the code, not the tests. Exception: if a test is genuinely wrong, fix it with a comment.
6. **Run the full validation sequence locally before marking complete**: build, then test, then lint. Run all three (not just the one that failed) — a test fix can introduce a lint error, a lint fix can break a build. Iterate locally until all three pass. If any still fail after your fixes, fix those too.
7. Each fix→verify cycle costs a full agent spawn if you miss something — be thorough in a single pass.

### Otherwise (normal implementation task)

- Read any source files referenced in the task description
- Implement exactly what the task describes — follow the spec, plan, contracts, and data-model
- If the task says to write tests, write them and verify they FAIL before writing any implementation
- If the constitution exists, ensure your implementation complies with all principles
- If something is unclear or you need a design decision, write the question to `BLOCKED.md` (include your task ID in the heading, e.g. `# BLOCKED: {task.id}`) and STOP immediately

**CRITICAL — Spec conformance rules:**

1. **Pin exact names from the task description.** If the task says to add a "STATUS" column, use the exact string `"STATUS"` — not `"STATE"`, `"SOURCE"`, or any synonym. Same for JSON keys, log messages, field names, UI labels, error messages, and column headers. When the task specifies a name, use that name verbatim.
2. **Implement the specified mechanism, not just the behavior.** If the task says "validate using struct tags + custom validation," you MUST implement BOTH mechanisms — struct tags AND custom validation. A custom-only approach that produces correct results is still a spec violation.
3. **Count all specified steps.** If the task describes a 5-step sequence (e.g., "log initiated → stop accepting → drain → hooks → flush"), implement ALL 5 steps. Before marking complete, count the steps in your implementation and compare against the task description.
4. **No stubs in production code.** If the task says "implement X using library Y," your production code MUST import and call library Y. Returning hardcoded values (e.g., `"100.100.100.100"` where a real IP is needed) is a stub, not an implementation. Test doubles in test directories are fine — stubs in `src/main/`, `internal/`, `pkg/`, `cmd/` are not.
5. **Cross-boundary data contracts.** If the task involves one system writing data that another reads (Nix→Go, Go→Kotlin, API→frontend), verify both sides agree on the exact field names, key casing, and types. Read the producer's format and ensure your consumer's struct tags / deserialization matches. If the task has `[consumes: IC-xxx]` or `[produces: IC-xxx]` tags, read the interface contract in `plan.md`.
6. **"Done when" is your stop signal.** Read the `Done when:` line in your task description carefully. It contains exact assertions you must satisfy. If it says 'output includes column headed "STATUS"', verify the literal string `STATUS` appears in your output.
7. **Fix failures — don't rationalize them.** If a required command fails, your job is to make it pass, not to explain why it's OK that it failed. "Environment issue," "infrastructure concern," "CI-only problem," and "known limitation" are not valid reasons to skip a gate that the task says must pass. Try to fix the root cause. If a tool conflict is blocking you (e.g., signature mismatch), resolve it (uninstall/reinstall, clear caches, reconfigure). If you genuinely cannot fix it after multiple attempts, write BLOCKED.md — do NOT mark the task complete with a "Partial" result. A task with a failing gate is not done.

**Note**: Phase validation (build/test at phase boundaries) is handled automatically by the runner — you do NOT need to run it.

## Step 3: Self-review

Before marking complete, review your own changes:
1. Run `git diff` to see everything you changed
2. Check for leftover debug code, missing error handling, security issues
3. Fix anything you find

## Step 4: Record learnings

Append any useful discoveries to `{learnings_file}`. Keep entries concise — max 3 bullet points per task, focusing only on non-obvious gotchas that would save a future agent time. Skip obvious things (API signatures, standard patterns, what was already documented).

## Step 5: Write completion claim and commit

1. Create `{spec_dir}/claims/` directory if it doesn't exist: `mkdir -p {spec_dir}/claims`
2. Write your completion claim to `{spec_dir}/claims/completion-{task.id}.json` with this exact format:
```json
{{{{
  "task_id": "{task.id}",
  "status": "complete",
  "summary": "One-line description of what you did",
  "commands_run": [
    {{{{"command": "the command you ran", "exit_code": 0}}}}
  ],
  "files_created": ["list/of/new/files.kt"],
  "files_modified": ["list/of/changed/files.kt"],
  "screenshots": ["path/to/any/screenshots.png"],
  "mcp_interactions": 0
}}}}
```
3. Mark this task complete in `{task_file}`: change `- [ ] {task.id}` to `- [x] {task.id}`. This is mandatory.
4. Commit all changes (including the claim file and updated task list) with a conventional commit message including the task ID (e.g., `feat({task.id}): ...`)

"""

    # ── Prior attempt history ──────────────────────────────────────────
    if attempt_history:
        prompt += f"\n## Prior attempts for {task.id}\n\n"
        prompt += f"This task has been attempted **{len(attempt_history)} time(s)** before by other agents that crashed (usually API connection errors). Learn from their progress:\n\n"

        # Summarize patterns
        wrote_code = [a for a in attempt_history if a.get("progress") == "wrote_code"]
        conn_errors = [a for a in attempt_history if "API Error" in a.get("error", "") or "connect" in a.get("error", "").lower()]

        if wrote_code:
            all_written = []
            for a in wrote_code:
                all_written.extend(a.get("files_written", []))
            unique_written = list(dict.fromkeys(all_written))
            prompt += f"**Code was already written** by prior agents: {', '.join(unique_written)}. Check if these files exist and are complete before rewriting.\n\n"

        if conn_errors:
            # Find the tool that was running when connection died
            crash_tools = [a.get("last_tool", "?") for a in conn_errors if a.get("last_tool")]
            prompt += f"**Connection errors killed prior agents.** They crashed during: {', '.join(crash_tools[-5:])}. "
            # Check if they all crash during network-heavy ops
            network_ops = [t for t in crash_tools if any(kw in t.lower() for kw in ["go test", "go build", "git clone", "go mod", "npm", "cargo"])]
            if len(network_ops) > len(crash_tools) // 2:
                prompt += "Most crashes happened during network-dependent build/test commands. "
                prompt += "If builds fail due to missing deps, try `go mod vendor` or equivalent offline strategies. "
                prompt += "If the task code is already written and tests can't run due to connection issues, verify the code compiles (`go vet`, `go build`) and mark the task complete — phase validation will run the full test suite later. Note: this exception is ONLY for transient network/connection errors. If tests can't run because a toolchain is missing (SDK, emulator, runtime), that is NOT a connection issue — fix the toolchain or write BLOCKED.md.\n\n"
            else:
                prompt += "\n\n"

        prompt += "**Last 3 attempts:**\n"
        for a in attempt_history[-3:]:
            prompt += f"- Agent {a['agent']}: {a['progress']}, {a['tool_count']} tools, {a['duration_s']}s"
            if a.get("files_written"):
                prompt += f", wrote: {', '.join(a['files_written'])}"
            if a.get("error"):
                prompt += f", died: {a['error'][:80]}"
            prompt += "\n"

        prompt += f"""
**If you determine this task cannot complete right now** (e.g., network deps unavailable, resource contention with concurrent agents), write a short explanation to `DEFER-{task.id}.md` and stop. The runner will retry this task when fewer agents are running.

"""

    # ── Include verification rejection if a prior attempt was rejected ──
    rejection_path = Path(spec_dir) / "claims" / f"rejection-{task.id}.md"
    if rejection_path.exists():
        rejection_text = rejection_path.read_text()
        prompt += f"""## Previous attempt REJECTED by verifier

A previous agent completed this task, but the independent verifier rejected it. You MUST address the rejection reason before claiming completion again.

```
{rejection_text}
```

**Do NOT repeat the same approach that was rejected.** Fix the specific issue identified above.

"""

    if blocked_answer:
        prompt += f"""## Previous blocker — user response

A previous agent working on this task wrote BLOCKED.md requesting human input. The user has responded. Here is the full BLOCKED.md content (including the original question and the user's edits):

```
{blocked_answer}
```

Use this information to proceed with the task. Do NOT write BLOCKED.md again for the same issue.

"""

    prompt += f"""## Rules

- Execute your assigned task ({task.id}) ONLY, then stop
- Do NOT skip ahead to later phases
- Do NOT refactor unrelated code
- Do NOT read ROUTER.md or load any skills
- Do NOT use the Skill tool
- If you need user input, write to BLOCKED.md and stop immediately. ALWAYS include your task ID (e.g. `# BLOCKED: T075`) in the first heading so the runner knows which task to retry.
- If you need a tool that requires authentication (e.g. `gh` CLI), write `[needs: gh]` in BLOCKED.md with your task ID — the runner will auto-grant it and retry your task
- SECURITY: If your task has `gh` access, you MUST NOT run any package installation commands (npm install, pip install, go install, cargo install, etc.) — these execute untrusted code that could exfiltrate credentials
- GIT PUSH: Always push via HTTPS, never SSH. SSH remotes trigger hardware key (YubiKey) prompts that hang in headless mode. Use: `git push https://github.com/<owner>/<repo>.git <branch>` — the `GH_TOKEN` env var handles auth.
- Prefer minimal changes that satisfy the task description
- If a task is unnecessary (already done, obsolete), mark it `- [~]` with a reason and move to the next task
- ALWAYS update `{learnings_file}` if you discovered anything non-obvious (max 3 concise bullets per task)
- When your task is complete, mark it `[x]` in tasks.md by changing `- [ ]` to `- [x]`. This is mandatory — if you don't mark it, the runner will re-spawn you.
- NEVER write a completion claim if any required command from the task description did not exit 0. If a command fails and you cannot fix it, write BLOCKED.md — do not claim a "Partial" result
"""
    return prompt


def build_vr_fix_prompt(spec_dir: str, task_file: str, learnings_file: str,
                        phase: Phase, failure_file: Path) -> str:
    """Build a prompt for a fix agent dispatched after a phase VR failure.

    The fix agent reads the VR failure report, diagnoses the root cause,
    and fixes the code. The runner then re-runs VR automatically.
    """
    phase_slug = phase.slug
    task_ids = ", ".join(t.id for t in phase.tasks)
    validate_dir = f"{spec_dir}/validate/{phase_slug}"

    # Read the failure report
    try:
        failure_text = failure_file.read_text()
    except OSError:
        failure_text = "(could not read failure report)"

    # Collect all prior failure files for context
    prior_failures = []
    vdir = Path(validate_dir)
    if vdir.exists():
        for f in sorted(vdir.glob("*.md")):
            if not f.name.startswith("review-"):
                try:
                    header = f.read_text().splitlines()[0] if f.stat().st_size > 0 else ""
                    prior_failures.append(f"{f.name}: {header}")
                except OSError:
                    pass

    prior_section = ""
    if len(prior_failures) > 1:
        prior_section = "## Prior validation attempts\n" + "\n".join(f"- {p}" for p in prior_failures) + "\n"

    nix_note = ""
    if (Path.cwd() / "flake.nix").exists():
        nix_note = (
            "\n**Environment**: This project uses Nix (`flake.nix`). Your PATH "
            "already includes all tools from the nix devshell — run commands "
            "directly. Do NOT prefix commands with `nix develop --command`.\n"
        )

    return f"""You are a fix agent for phase **{phase.name}** ({phase_slug}). A validation agent
ran tests/linting and found failures. Your job is to fix them.
{nix_note}
## Context

- **Phase**: {phase.name} ({phase_slug})
- **Tasks in this phase**: {task_ids}
- **Task file**: `{task_file}`
- **Learnings file**: `{learnings_file}`
- **Validation directory**: `{validate_dir}/`

{prior_section}
## Latest validation failure

{failure_text}

## Instructions

1. Read the failure report above carefully. Identify every distinct failure.
2. Read the relevant source files to understand the root cause of each failure.
3. Read `{task_file}` to understand what each task in this phase was supposed to do.
4. Read `{learnings_file}` for any prior context or gotchas.
5. Fix each failure with minimal, targeted changes. Do not refactor unrelated code.
6. After fixing, run the same commands that failed to verify your fixes work:
   - If tests failed, re-run the test command
   - If lint failed, re-run the lint command
   - If build failed, re-run the build command
7. Update `{learnings_file}` with any new discoveries relevant to future phases.
8. Commit your fixes with a descriptive commit message.

**Do NOT modify the task list** — the runner manages task status.
**Do NOT write validation files** — the runner will re-run VR after you finish.
"""


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

**Nix sandbox commands**: You are inside a sandbox. For nix commands:
- Set `NIX_REMOTE=daemon` and pass `--extra-experimental-features 'nix-command flakes'`
- Write output to a file: `NIX_REMOTE=daemon nix --extra-experimental-features 'nix-command flakes' flake check --print-build-logs > /tmp/nix-flake-check.log 2>&1; echo "EXIT_CODE=$?" >> /tmp/nix-flake-check.log`
- Never pipe through `head`/`tail` — write to file and read what you need after
- VM tests take 10-20 min — use timeout ≥1800s, run in background with TaskOutput
- On failure, read the last 200 lines and grep for `FTL`, `FAIL`, `error:` to find root cause
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
        skill_section = f"""## Review checklist (compact — see prior reviews for full context)

Check the diff for: bugs, security vulnerabilities, incorrect logic, broken error handling, missing input validation, race conditions, resource leaks, spec-conformance violations, and anything causing runtime failures or data loss.

**Spec-conformance (quick check)**: Read each task's description in `{task_file}`. Verify: exact names match (column headers, JSON keys, log messages), all specified steps are present (count them), no stubs in production code (hardcoded values where dynamic values expected), cross-boundary field names agree between producer and consumer.

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

### Run validation (four-step sequence)

Run these steps **in order**, stopping at the first failure category. Do NOT skip steps — every step that has a command must run.

**Step 1 — Build**: Compile/transpile the project. If there's no explicit build step, skip.
**Step 2 — Test**: Run the full test suite. Capture all output.
**Step 3 — Lint**: Run the project's linter(s) (e.g. `eslint`, `golangci-lint`, `ruff`, `clippy`). Check `CLAUDE.md`, `package.json` scripts, and `Makefile` for the lint command. If a linter is configured but not in CLAUDE.md, still run it.
**Step 4 — Security scan**: Run any security scanners configured in the project (e.g. `npm audit`, `trivy`, `semgrep`, `bandit`). Write results to `test-logs/security/`. If no scanners are configured, skip.

**Short-circuit rule**: If Step 1 (build) fails, skip Steps 2-4. If Step 2 (test) fails, still run Step 3 (lint) — lint errors are cheap to find and the fix agent can address both in one pass. Skip Step 4 (security) if build or test failed.

**Code coverage is mandatory for every test suite in the project.** If the project's test commands do not already collect coverage, fix them — add the standard coverage tool for that language/framework (every mainstream ecosystem has one) and wire it into the test command. Coverage MUST produce both terminal output and a file report in `coverage/` (JSON, XML, LCOV, or equivalent). See `reference/testing.md` § Code coverage collection for details.

**Detect hung tests — don't wait forever on a deadlocked test runner.** Whole-suite test invocations sometimes deadlock on a single bad test file (unawaited futures in `setUp`, platform-channel calls without mocks, coverage-collector deadlocks). Use these rules:

1. When a test suite has more than ~4 test files, **run them individually in sequence** rather than as one `<runner> test` invocation. Example (Flutter): `for f in test/*.dart; do flutter test --coverage "$f" > "logs/$(basename $f).log" 2>&1 || echo "FAIL: $f"; done`. Individual runs fail fast and isolate hanging files.
2. When you must run the whole suite in background, wrap the runner in `timeout`: `timeout 600 flutter test --coverage 2>&1`. Never use `TaskOutput` with a 600s timeout on an unbounded test process — the outer runner has its own watchdog and will kill you if your background task stops making progress.
3. If a prior attempt wrote `agent-<id>-<task>-*.hang.md` in `logs/`, read it first — it identifies exactly which command hung on the previous run. Don't repeat the same invocation.
4. If any single test file hangs (no output for 60 seconds), it's a bug in that test. Record it in the FAIL output with file path and append a fix task — don't keep retrying the whole suite.

**Fix missing tools before reporting failure.** If a build/test command fails because a tool is not installed (e.g. `eslint: command not found`, `tsc: not found`, missing npm packages), YOU MUST install it — do not skip it or call it a "pre-existing issue":
- Missing npm package (referenced in scripts but not in devDependencies) → `npm install --save-dev <package> --ignore-scripts` to add it, then `npm rebuild <pkg>` only if native compilation needed
- Already in devDependencies but not installed → `npm install --ignore-scripts`
- Missing Python package → `uv add --dev <pkg>` or `uv sync --dev`
- Missing system tool (not an npm/pip package) → add it to `flake.nix` devShell and commit the change. The runner detects flake.nix modifications and automatically restarts inside the updated `nix develop` shell.
- Then re-run the command. Only report a failure if the command fails AFTER dependencies are installed.

**Step 5 — CI workflow verification** (if `.github/workflows/` files were modified in this phase):
Check if any workflow files were modified:
```bash
git diff {base_sha}...HEAD --name-only -- .github/workflows/
```
If any were modified:
1. Parse the modified workflow files and extract every `run:` command from added/changed steps
2. Run each command locally (e.g., `./gradlew assembleDebug`, `nix build`, `go test ...`)
3. For each `actions/upload-artifact` step, verify the `path:` file exists after the build
4. For non-vacuous verification steps (counting JUnit XML, parsing summary.json), verify the
   expected output files exist and contain valid data (>0 tests, >0 bytes)
5. For multi-build-system projects: verify EVERY build system produced results, not just one.
   A project with `go.mod` and `android/build.gradle.kts` must pass both Go and Gradle builds.
Report any missing artifacts or failed commands as FAIL (same as test failure).

**Early phase exception (narrow):** A phase may pass with minimal validation ONLY if it modified no source code files — meaning every changed file has an extension like `.nix`, `.yml`, `.yaml`, `.toml`, `.json`, `.md`, `.lock`, `Makefile`, `.envrc`, or `.gitignore`. If the phase changed ANY source code (`.go`, `.kt`, `.java`, `.ts`, `.tsx`, `.js`, `.py`, `.rs`, `.c`, `.cpp`, `.swift`, etc.), the corresponding build system MUST be tested. This is a checkable condition, not a judgment call.

**CRITICAL — unable to validate = FAIL:** If a phase modifies source code in a build system but you cannot run that build system's tests (toolchain missing, SDK not available, emulator won't boot), that is a **FAIL**. Either fix the environment or write FAIL. A validation that only tests Go when the phase modified Kotlin is incomplete and MUST be FAIL.

**CRITICAL — zero test results = FAIL:** If you run a test command and it reports 0 passed, 0 failed, 0 skipped, that means the test runner found nothing to execute. This is NOT a pass — it means test discovery is broken (wrong directory, missing wrapper script, `| tee` swallowing exit codes). Zero results from a build system with changed source files is FAIL.

**Step 6 — Stub detection** (if the phase implements interfaces, integrations, or external library wrappers):
Check DI modules, factory methods, and provider functions for implementations that return hardcoded values, only set boolean flags, or contain no calls to the external library they claim to wrap. Specifically:
- Grep production code (`src/main/`, `internal/`, `pkg/`, `cmd/`) for hardcoded sentinel values (e.g., `"100.100.100.100"`, `"TODO"`, `"stub"`, `"fake"`)
- If a task says "implement X using library Y," verify that library Y's package is imported AND its functions are called in production code — not just in the interface definition
- Test code (test doubles, mocks, fakes in test directories like `androidTest/`, `*_test.go`, `__tests__/`) is exempt — stubs there are expected
- A stub in production code is a FAIL, same as a test failure

**Step 7 — Cross-boundary contract verification** (if the phase has tasks with `[produces:]`/`[consumes:]` tags, or any code where one system writes data another reads):
For each cross-boundary seam (e.g., Nix module writes JSON that Go reads, Go server exposes API that Kotlin calls):
1. Read the producer's output format (struct JSON tags, proto field names, config keys, CLI output columns)
2. Read the consumer's input format (struct JSON tags, data class fields, parser keys)
3. Verify EVERY field name matches exactly between producer and consumer. A mismatch (e.g., Nix writes `clientCertPath` but Go reads `clientCert`) is a FAIL
4. If no integration test exercises the cross-boundary path, flag this as a coverage gap

### If ANY step FAILS — stop here

1. Create `{validate_dir}/{attempt_num}.md` with:
   ```
   # Phase {phase_slug} — Validation #{attempt_num}: FAIL

   **Date**: (current timestamp)

   ## Failure categories
   - **Build**: PASS | FAIL | SKIPPED
   - **Test**: PASS | FAIL | SKIPPED (N passed, M failed, K skipped)
   - **Lint**: PASS | FAIL | SKIPPED (N errors, M warnings)
   - **Security**: PASS | FAIL | SKIPPED (N findings)
   - **Coverage**: COMPLETE | INCOMPLETE (list unvalidated build systems)

   ## Coverage proof
   **Files changed**: N files
   **Build systems modified**:
   - [Build system]: N files changed → [command] → N passed, N failed
   **Unvalidated build systems**:
   - [Build system]: N files changed, NOT TESTED — [reason]

   ## Failed steps detail

   ### [Step name, e.g. "Test" or "Lint" or "Coverage"]
   **Command**: (exact command run, or "N/A — toolchain unavailable" for coverage failures)
   **Exit code**: (exit code)
   **Root cause summary**: (1-2 sentence diagnosis — what is actually wrong, not just "tests failed")
   **Failures**:
   - (each distinct failure: file, line if available, what's wrong)

   ## Full output
   (relevant portions of stdout/stderr, organized by step)
   ```
   Fill in PASS/FAIL/SKIPPED for every category based on what you ran. Include Coverage: INCOMPLETE if any modified build system was not tested. This lets fix agents immediately see which steps failed without parsing raw output.
2. **Do NOT modify `{task_file}`** — the runner dispatches fix agents automatically.
3. If {attempt_num} >= 10: write `BLOCKED.md` with the full failure history.
4. **Do NOT proceed to Part 2.** Exit now.

### If tests PASS — write PASS record, then continue to Part 2

Before writing PASS, produce a **coverage proof**. This is mandatory — a PASS record without it is invalid.

1. Run `git diff {base_sha}...HEAD --name-only` to list all files changed in this phase.
2. Map each changed file to a build system by extension/directory (`.go` → Go, `.kt`/`.java` under `android/` → Android/Gradle, `.ts`/`.tsx`/`.js` → Node, `.py` → Python, `.rs` → Rust, `.nix` → Nix, `.yml` under `.github/workflows/` → CI).
3. For each build system with changed source files, confirm you ran its tests and got non-zero results.
4. If any build system has changed source files but was NOT tested, this is a FAIL — do not write PASS. Go back to the FAIL section above.

Create `{validate_dir}/{attempt_num}.md` with:
```
# Phase {phase_slug} — Validation #{attempt_num}: PASS

**Date**: (current timestamp)
**Commands run**: (list every command)
**Result**: All checks passed.

## Coverage proof
**Files changed**: N files
**Build systems modified**:
- [Build system]: N files changed → [command] → N passed, N failed
- [Build system]: N files changed → [command] → N passed, N failed

**Unvalidated build systems**: None
```

If you cannot write "Unvalidated build systems: None" — if ANY modified build system was not tested — do NOT write PASS. Write FAIL instead.

## Part 2: Code Review (only if tests passed)

### Diff scope

{diff_section}
{prior_section}
### Review and fix

Scan the ENTIRE diff systematically and find ALL issues that MUST be fixed: bugs, security vulnerabilities, correctness issues, broken error handling, missing input validation, and anything that would cause runtime failures or data loss. Fix each one directly in the code and commit with a conventional commit message.

**Spec-conformance check (MANDATORY — do this BEFORE the bug scan):**

Read `{task_file}` and for each task completed in this phase, cross-reference the implementation against the task description and "Done when" criteria:

1. **Exact names**: If the task says a CLI should show a `STATUS` column, verify the code uses the exact string `"STATUS"` — not `"STATE"`, `"SOURCE"`, or any synonym. Check struct field names, JSON tags, config keys, error messages, log messages, UI labels, and table column headers.
2. **All specified steps**: If the task describes a multi-step sequence (e.g., "5 log messages: initiated, stop, drain, hooks, complete"), count the steps in the implementation. If any are missing, that is a bug — fix it.
3. **Mechanism, not just behavior**: If the task says "validate using struct tags + custom validation," verify BOTH mechanisms exist. A custom-only approach that produces correct behavior is still a spec violation — the task specified the mechanism.
4. **Cross-boundary data contracts**: If the task involves one system writing data that another reads (Nix config → Go struct, Go API → Kotlin client), verify the field names match on BOTH sides. Read the producer's output format (JSON tags, proto fields) and the consumer's input format. Every key name must agree exactly.
5. **No stubs in production code**: If the task says "implement X using library Y," verify production code actually imports and calls library Y. Hardcoded return values where dynamic values are expected (e.g., returning `"100.100.100.100"` for a Tailscale IP) are stubs, not implementations — fix them.
6. **UI completeness**: If the task says "add loading states to screens X, Y, Z," verify ALL named screens have the loading state — not just some. Cross-reference the enumerated list in the task description against the actual code.

Any spec-conformance violation is a bug — fix it the same way you'd fix a null pointer or missing error check.

**Be exhaustive in a single pass.** Each review cycle costs a full agent spawn — finding one issue per pass wastes tokens. Review every file in the diff before committing any fixes, so you have the full picture.

**Only fix things that are clearly wrong.** Do not refactor, rename, reorganize, or improve code style. Do not add tests beyond what the task specified. Do not add comments or documentation. The bar is: "would this cause a bug, security issue, data loss, or spec-conformance violation in production?"

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




# ── Sandbox ────────────────────────────────────────────────────────────

# Resolved once at import time; overwritten by main() after arg parsing.
_sandbox_enabled: bool = True
_bwrap_path: Optional[str] = None


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


# ── GitHub token acquisition ──────────────────────────────────────────

_gh_token_cache: Optional[str] = None
_gh_token_expires: float = 0.0
_GH_TOKEN_TTL = 300  # 5 minutes — short-lived to limit exposure window


def _acquire_gh_token() -> Optional[str]:
    """Get a GitHub token via `gh auth token`, cached for 5 minutes.

    Returns None if `gh` is not installed or not authenticated.
    The token is passed as an env var to sandboxed agents — never written
    to the filesystem inside the sandbox.
    """
    global _gh_token_cache, _gh_token_expires

    now = time.time()
    if _gh_token_cache and now < _gh_token_expires:
        return _gh_token_cache

    gh_bin = shutil.which("gh")
    if not gh_bin:
        return None

    try:
        result = subprocess.run(
            [gh_bin, "auth", "token"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            _gh_token_cache = result.stdout.strip()
            _gh_token_expires = now + _GH_TOKEN_TTL
            return _gh_token_cache
    except (subprocess.TimeoutExpired, OSError):
        pass

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
      - Credentials         (env) — CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY

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

    # KVM: bwrap's --dev creates a synthetic /dev without host devices.
    # Bind-mount /dev/kvm so Android emulator / QEMU can use hardware
    # acceleration instead of falling back to slow software emulation.
    kvm_dev = Path("/dev/kvm")
    if kvm_dev.exists() and os.access(kvm_dev, os.W_OK):
        cmd += ["--dev-bind", "/dev/kvm", "/dev/kvm"]

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

    # Android emulator console auth token — needed for `adb emu finger touch`
    # (fingerprint simulation) and other console commands.
    emu_auth = home / ".emulator_console_auth_token"
    if emu_auth.is_file():
        cmd += ["--ro-bind", str(emu_auth), str(emu_auth)]

    # Claude CLI auth: if a long-lived token exists in ~/.claude/token or
    # CLAUDE_CODE_OAUTH_TOKEN env, it's passed via env var in _build_sandbox_env()
    # and no credentials file mount is needed.  Otherwise fall back to mounting
    # .credentials.json (read-only) for the short-lived OAuth flow.
    token_file = home / ".claude" / "token"
    has_long_lived_token = (
        os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        or (token_file.is_file() and token_file.read_text().strip())
    )
    if not has_long_lived_token:
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

def _build_sandbox_env(capabilities: set[str] | None = None) -> dict[str, str]:
    """Build a minimal environment for sandboxed agents.

    Credentials are passed here (via Popen env=) instead of bwrap --setenv
    so they don't appear in /proc/*/cmdline of the bwrap process.

    If capabilities includes "gh", a short-lived GH_TOKEN is injected so
    the agent can use `gh` CLI commands.  Tasks without this capability
    (e.g. npm install, pip install) never see the token.
    """
    capabilities = capabilities or set()
    home = Path.home()
    # Inherit PATH from the parent process so nix develop tools (node,
    # python, npm, pytest, etc.) are available inside the sandbox.  Fall
    # back to a minimal system PATH if PATH is somehow unset.
    env: dict[str, str] = {
        "HOME": str(home),
        "USER": os.environ.get("USER", "sandbox"),
        "PATH": os.environ.get("PATH", "/run/current-system/sw/bin:/usr/bin:/bin"),
    }

    # Auth: prefer a long-lived OAuth token from ~/.claude/token (generated
    # by `claude setup-token`).  This avoids the short-lived credentials.json
    # token that expires mid-run inside sandboxes that can't refresh it.
    token_file = home / ".claude" / "token"
    claude_oauth = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if not claude_oauth and token_file.is_file():
        try:
            claude_oauth = token_file.read_text().strip()
        except OSError:
            pass
    if claude_oauth:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = claude_oauth

    # API key fallback (alternative auth path).
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key

    # SSL certs for Node/Python HTTPS.
    for var in ["SSL_CERT_FILE", "NIX_SSL_CERT_FILE"]:
        val = os.environ.get(var)
        if val:
            env[var] = val

    # Build toolchain env vars from nix develop (paths to SDKs, not secrets).
    for var in ["ANDROID_HOME", "ANDROID_SDK_ROOT", "JAVA_HOME",
                "GRADLE_USER_HOME", "GOPATH", "GOROOT", "CARGO_HOME",
                "RUSTUP_HOME", "NODE_PATH"]:
        val = os.environ.get(var)
        if val:
            env[var] = val

    # Capability-gated credentials: only inject when the task declares it.
    # This keeps tokens away from tasks that run untrusted code (npm/pip install).
    if "gh" in capabilities:
        token = _acquire_gh_token()
        if token:
            env["GH_TOKEN"] = token

    return env


def spawn_agent(task: Task, prompt: str, log_path: Path,
                stderr_path: Path,
                extra_capabilities: set[str] | None = None,
                mcp_config_paths: list[Path] | None = None,
                model: str = "opus") -> subprocess.Popen:
    """Spawn a claude CLI process for the given task.

    Capabilities from task.capabilities (parsed from [needs: gh] etc.) plus
    any extra_capabilities (e.g. granted after a BLOCKED.md request) control
    which credentials are injected into the sandbox environment.

    mcp_config_paths: list of JSON config files to pass via --mcp-config.
    These provide MCP server definitions (e.g. mcp-android for E2E tasks).

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
        "--model", model,
        "--verbose",
        "--output-format", "stream-json",
    ]

    # Inject MCP server config files for platform runtime capabilities
    if mcp_config_paths:
        for config_path in mcp_config_paths:
            if config_path.exists():
                claude_cmd += ["--mcp-config", str(config_path)]

    # Write prompt to a file to avoid ARG_MAX limits (large prompts +
    # bwrap args can exceed Linux's ~2MB argv+envp budget).  The file is
    # placed next to the agent log so it's inside the project directory
    # (visible inside the bwrap sandbox, unlike host /tmp).
    prompt_file = log_path.with_suffix(".prompt.md")
    prompt_file.write_text(prompt)
    claude_cmd += ["-p", f"Follow the instructions in {prompt_file} exactly. Read that file now with the Read tool and do what it says."]

    cmd = claude_cmd

    env = None

    # Merge task-declared capabilities with any extras (e.g. from BLOCKED.md retry)
    all_caps = set(task.capabilities)
    if extra_capabilities:
        all_caps |= extra_capabilities

    # SECURITY: strip credential-bearing capabilities from tasks that may
    # execute untrusted code (npm install, pip install, etc.).  This is a
    # hard block — even if [needs: gh] is declared, the token is NOT injected
    # when the task description contains package-install patterns.
    if _check_untrusted_code_risk(task):
        stripped = all_caps & {"gh"}
        if stripped:
            import sys as _sys
            print(f"[SECURITY] Stripping capabilities {stripped} from {task.id} — "
                  f"task runs untrusted code", file=_sys.stderr)
        all_caps -= {"gh"}

    if _sandbox_enabled and _bwrap_path:
        project_dir = Path.cwd()
        cmd = _build_sandbox_cmd(project_dir, cmd)
        env = _build_sandbox_env(capabilities=all_caps)
    else:
        # Not sandboxed — still need a clean env to avoid CLAUDECODE
        # detection which makes the CLI refuse to start.
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        # Auth: prefer long-lived token from ~/.claude/token, fall back
        # to short-lived credentials.json access token.
        token_file = Path.home() / ".claude" / "token"
        claude_oauth = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        if not claude_oauth and token_file.is_file():
            try:
                claude_oauth = token_file.read_text().strip()
            except OSError:
                pass
        if claude_oauth:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = claude_oauth
        else:
            claude_creds = Path.home() / ".claude" / ".credentials.json"
            if claude_creds.is_file():
                try:
                    creds = json.loads(claude_creds.read_text())
                    tok = creds.get("claudeAiOauth", {}).get("accessToken", "")
                    if tok and "ANTHROPIC_AUTH_TOKEN" not in env:
                        env["ANTHROPIC_AUTH_TOKEN"] = tok
                except (json.JSONDecodeError, OSError):
                    pass
        # Inject GH_TOKEN for non-sandboxed mode too (capability-gated).
        if "gh" in all_caps and "GH_TOKEN" not in env:
            token = _acquire_gh_token()
            if token:
                env["GH_TOKEN"] = token

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


def extract_usage_breakdown(log_path: Path) -> dict:
    """Scan a complete stream-json log and return a detailed token breakdown.

    Returns dict with keys:
      input_tokens_fresh        — non-cached input tokens
      input_tokens_cache_read   — cache hits (cheap)
      input_tokens_cache_create — cache writes (1.25x input cost)
      output_tokens
      model                     — last observed assistant model id (e.g. "claude-sonnet-4-6")

    Prefers the authoritative `result` entry usage; falls back to the latest
    non-synthetic assistant message.  Missing / unreadable logs return zeros.
    """
    out = {
        "input_tokens_fresh": 0,
        "input_tokens_cache_read": 0,
        "input_tokens_cache_create": 0,
        "output_tokens": 0,
        "model": "",
    }
    try:
        with open(log_path, "r") as f:
            lines = f.read().splitlines()
    except OSError:
        return out

    result_usage: dict | None = None
    last_assistant_usage: dict | None = None
    last_model = ""
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "result":
            u = msg.get("usage") or {}
            if u.get("input_tokens", 0) or u.get("output_tokens", 0):
                result_usage = u
        elif msg.get("type") == "assistant":
            m = msg.get("message", {}) or {}
            model = m.get("model", "")
            if model == "<synthetic>":
                continue
            u = m.get("usage") or {}
            if u.get("input_tokens", 0) or u.get("output_tokens", 0):
                last_assistant_usage = u
            if model:
                last_model = model

    usage = result_usage or last_assistant_usage or {}
    out["input_tokens_fresh"] = usage.get("input_tokens", 0)
    out["input_tokens_cache_read"] = usage.get("cache_read_input_tokens", 0)
    out["input_tokens_cache_create"] = usage.get("cache_creation_input_tokens", 0)
    out["output_tokens"] = usage.get("output_tokens", 0)
    out["model"] = last_model
    return out


def read_stream_output(log_path: Path, last_pos: int) -> tuple[list[str], int, Optional[int], tuple[int, int]]:
    """Read new JSON lines from a stream-json log file.
    Returns (display_lines, new_position, exit_code_if_result, (input_tokens, output_tokens))."""
    lines = []
    exit_code = None
    input_tokens = 0
    output_tokens = 0
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

            if msg.get("type") == "result":
                # The result entry has authoritative cumulative usage — prefer it
                usage = msg.get("usage", {})
                if usage:
                    result_in = (
                        usage.get("input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                    )
                    result_out = usage.get("output_tokens", 0)
                    # Only use if non-zero (avoid synthetic error zeroing)
                    if result_in > 0 or result_out > 0:
                        input_tokens = result_in
                        output_tokens = result_out
                # Also extract display text and exit code from result
                if msg.get("result"):
                    lines.append(msg["result"])
                exit_code = 1 if msg.get("is_error") else 0
            elif msg.get("type") == "assistant":
                # Extract token usage from assistant messages.
                # Each message reports cumulative usage, so we overwrite (not add).
                # Skip synthetic messages (model == "<synthetic>") which have zeroed usage.
                model = msg.get("message", {}).get("model", "")
                if model == "<synthetic>":
                    pass  # Don't let synthetic error messages zero out real counts
                else:
                    usage = msg.get("message", {}).get("usage", {})
                    if usage:
                        msg_in = (
                            usage.get("input_tokens", 0)
                            + usage.get("cache_creation_input_tokens", 0)
                            + usage.get("cache_read_input_tokens", 0)
                        )
                        msg_out = usage.get("output_tokens", 0)
                        if msg_in > 0 or msg_out > 0:
                            input_tokens = msg_in
                            output_tokens = msg_out

                if msg.get("message", {}).get("content"):
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
            elif msg.get("type") == "error":
                err_msg = msg.get("error", {}).get("message", str(msg))
                lines.append(f"ERROR: {err_msg}")
                exit_code = 2

        return lines, new_pos, exit_code, (input_tokens, output_tokens)
    except FileNotFoundError:
        return [], last_pos, None, (0, 0)


def check_rate_limited(stderr_path: Path, log_path: Optional[Path] = None) -> Optional[float]:
    """Check if the agent hit a rate limit.

    Returns the resetsAt epoch timestamp if found, or True-ish 1.0 if rate
    limited but no timestamp available, or None if not rate limited.
    """
    # Check JSONL log for rate_limit_event with status "rejected" and resetsAt
    if log_path:
        try:
            for raw_line in reversed(log_path.read_text().splitlines()):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    msg = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "rate_limit_event":
                    info = msg.get("rate_limit_info", {})
                    if info.get("status") == "rejected" or info.get("overageDisabledReason") == "out_of_credits":
                        resets_at = info.get("resetsAt")
                        if resets_at:
                            return float(resets_at)
                        return 1.0  # rate limited but no timestamp
        except Exception:
            pass
    # Fallback: check stderr for rate limit keywords
    try:
        text = stderr_path.read_text()
        if re.search(r'rate.?limit|usage.?limit|429|quota|capacity', text, re.IGNORECASE):
            return 1.0
    except Exception:
        pass
    return None


def check_overloaded(log_path: Path) -> bool:
    """Check if the agent died from a 529 overloaded error."""
    try:
        for raw_line in reversed(log_path.read_text().splitlines()):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                msg = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "result" and msg.get("is_error"):
                result = str(msg.get("result", ""))
                if "529" in result or "overloaded" in result.lower():
                    return True
            if msg.get("type") == "assistant":
                for block in msg.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if "529" in text and "overloaded" in text.lower():
                            return True
    except Exception:
        pass
    return False


def check_auth_error(log_path: Path) -> Optional[str]:
    """Check if the agent died from a permanent auth error (not retryable).

    Returns the error string if found, None otherwise.
    """
    try:
        for raw_line in reversed(log_path.read_text().splitlines()):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                msg = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "result" and msg.get("is_error"):
                result_text = msg.get("result", "")
                if re.search(r'authentication_error|401|OAuth token has expired|Failed to authenticate', result_text):
                    return result_text
        return None
    except Exception:
        return None


def check_connection_error(log_path: Path) -> Optional[str]:
    """Check if the agent died from an API connection error.

    Returns the error string if found, None otherwise.
    Reads the jsonl result line — these errors appear there, not in stderr.
    """
    try:
        for raw_line in reversed(log_path.read_text().splitlines()):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                msg = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "result" and msg.get("is_error"):
                result_text = msg.get("result", "")
                if re.search(r'UND_ERR_SOCKET|ECONNRESET|ECONNREFUSED|ETIMEDOUT|Unable to connect to API', result_text):
                    return result_text
        return None
    except Exception:
        return None


def _find_prior_hang_diagnoses(log_dir: Path, task_id_prefix: str,
                               *, limit: int = 2) -> list[Path]:
    """Return up to `limit` most-recent hang.md files for a task id prefix.

    Files are named `agent-<id>-<task>-<ts>.hang.md`. We glob by the task prefix
    (e.g. 'VR-phase12-flutter-customer-app') so every retry for the same phase
    picks up diagnoses from earlier agents in this session or previous ones.
    Newest-first by filename (the timestamp sorts lexicographically).
    """
    if not log_dir.exists():
        return []
    # Glob pattern intentionally broad — agent-id may differ across runs.
    # Normalize trailing dashes so callers can pass either 'VR-phase12-' or
    # 'VR-phase12' without changing the match.
    prefix = task_id_prefix.rstrip("-")
    matches = sorted(log_dir.glob(f"agent-*-{prefix}-*.hang.md"))
    return matches[-limit:] if matches else []


def _format_hang_diagnoses_for_prompt(diag_files: list[Path]) -> str:
    """Read diagnosis files and return a prompt-ready section.

    Empty string when no files. Each file is truncated to ~3000 chars so the
    prompt doesn't balloon when many retries accumulate.
    """
    if not diag_files:
        return ""
    chunks = []
    for p in diag_files:
        try:
            text = p.read_text()
        except OSError:
            continue
        if len(text) > 3000:
            text = text[:3000] + "\n... (truncated)\n"
        chunks.append(f"### {p.name}\n\n{text}")
    if not chunks:
        return ""
    body = "\n\n".join(chunks)
    return (
        "## PRIOR HANG DIAGNOSES — READ BEFORE RUNNING ANYTHING\n\n"
        "One or more previous attempts on this task hung and were killed by "
        "the watchdog. The diagnoses below record the exact command that "
        "deadlocked and its process state at kill time. **Do not repeat that "
        "invocation.** If a whole-suite test command hung, run test files "
        "individually with a per-file `timeout` wrapper. If the hang was in a "
        "bwrap/fontconfig workaround, that workaround is not the root cause "
        "— stop iterating on it.\n\n"
        f"{body}\n\n"
        "---\n\n"
    )


def _count_prior_hangs(log_dir: Path, task_id_prefix: str) -> int:
    """Count how many hang.md files already exist for this task prefix."""
    if not log_dir.exists():
        return 0
    prefix = task_id_prefix.rstrip("-")
    return len(list(log_dir.glob(f"agent-*-{prefix}-*.hang.md")))


def _task_idle_budget_s(task) -> int:
    """Return the idle-log timeout for this agent in seconds.

    Long-running task categories get a larger budget because the inner agent
    legitimately waits on tool results (e.g. `flutter test`, `nix flake check`)
    without emitting stream-json events for many minutes.
    """
    tid = getattr(task, "id", "") or ""
    # VR / validation agents block on full build+test suites
    if tid.startswith("VR-"):
        return 30 * 60
    # E2E loops drive long MCP browser/simulator sessions
    if tid.startswith("e2e-") or tid.startswith("E2E-"):
        return 45 * 60
    return AGENT_IDLE_TIMEOUT_S


def _read_last_bash_bg_task(log_path: Path) -> Optional[dict]:
    """Find the most recent `run_in_background=true` Bash tool_use in the log.

    Returns a dict with `tool_use_id`, `command`, `started_at` (ts of the line),
    or None if no such call exists. The started_at is derived from the file's
    structure — we just use the line's position as a proxy since stream-json
    doesn't timestamp individual messages reliably.
    """
    try:
        content = log_path.read_text()
    except OSError:
        return None
    last: Optional[dict] = None
    for raw in content.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if msg.get("type") != "assistant":
            continue
        for block in msg.get("message", {}).get("content", []) or []:
            if (isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == "Bash"
                    and block.get("input", {}).get("run_in_background")):
                last = {
                    "tool_use_id": block.get("id"),
                    "command": block.get("input", {}).get("command", ""),
                    "description": block.get("input", {}).get("description", ""),
                }
    return last


def _find_bg_bash_pids(agent_pid: int, command_snippet: str) -> list[int]:
    """Find pids of the background bash descendant matching the command.

    Walks `ps --ppid` transitively from agent_pid. The command_snippet is a
    short prefix of the Bash `command` field; we grep each child's cmdline for
    it. Returns all matching pids (including children of the matched bash, so
    callers can measure cumulative CPU activity).
    """
    if agent_pid <= 0 or not command_snippet:
        return []
    try:
        # BFS over descendants via `pgrep -P` repeatedly (portable enough).
        all_desc: list[int] = []
        frontier = [agent_pid]
        seen = {agent_pid}
        while frontier:
            next_frontier = []
            for ppid in frontier:
                r = subprocess.run(
                    ["pgrep", "-P", str(ppid)],
                    capture_output=True, text=True, timeout=5,
                )
                for ln in r.stdout.splitlines():
                    try:
                        cpid = int(ln.strip())
                    except ValueError:
                        continue
                    if cpid in seen:
                        continue
                    seen.add(cpid)
                    all_desc.append(cpid)
                    next_frontier.append(cpid)
            frontier = next_frontier
    except (subprocess.SubprocessError, OSError):
        return []
    # Filter to processes whose cmdline contains a distinctive fragment of the
    # background command. Use up to the first 40 chars after skipping common
    # prefixes (bash -c, bwrap flags). Cheap substring match is sufficient.
    probe = command_snippet.strip()[:40]
    matched: list[int] = []
    if not probe:
        return []
    for cpid in all_desc:
        try:
            with open(f"/proc/{cpid}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode("utf-8", "ignore")
            if probe in cmd:
                matched.append(cpid)
                # Include the matched bash's entire subtree — that's where the
                # actual work (flutter_tester etc.) runs.
                try:
                    r2 = subprocess.run(
                        ["pgrep", "-P", str(cpid)],
                        capture_output=True, text=True, timeout=5,
                    )
                    for ln in r2.stdout.splitlines():
                        try:
                            matched.append(int(ln.strip()))
                        except ValueError:
                            continue
                except (subprocess.SubprocessError, OSError):
                    pass
        except (OSError, IOError):
            continue
    return matched


def _cumulative_cpu_ticks(pids: list[int]) -> int:
    """Sum user+system jiffies for the given pids. 0 if none exist."""
    total = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat", "rb") as f:
                parts = f.read().split()
            # fields 14 (utime) + 15 (stime) — 1-indexed per procfs docs,
            # 0-indexed here means parts[13] and parts[14]
            total += int(parts[13]) + int(parts[14])
        except (OSError, IOError, IndexError, ValueError):
            continue
    return total


def _write_hang_diagnosis(
    log_dir: Path, agent_id: int, task_id: str, timestamp: str,
    *, reason: str, log_path: Optional[Path], agent_pid: Optional[int],
    bg_info: Optional[dict], bg_pids: list[int],
) -> Path:
    """Write a markdown diagnosis file for a killed agent.

    The next attempt's prompt can reference this to avoid repeating the hang.
    """
    diag_path = log_dir / f"agent-{agent_id}-{task_id}-{timestamp}.hang.md"
    lines = [
        f"# Hang diagnosis — agent {agent_id} ({task_id})",
        "",
        f"**Killed reason:** {reason}",
        f"**Agent pid:** {agent_pid}",
        "",
    ]
    # Last 30 non-empty lines of stream-json log (raw, truncated)
    if log_path and log_path.exists():
        try:
            raw = log_path.read_text().splitlines()
            tail = [ln for ln in raw if ln.strip()][-30:]
            lines.append("## Last 30 log lines")
            lines.append("```")
            for ln in tail:
                lines.append(ln[:500])
            lines.append("```")
            lines.append("")
        except OSError:
            pass
    # Background bash info
    if bg_info:
        lines.append("## Last background Bash call")
        lines.append(f"- **description:** {bg_info.get('description', '')}")
        lines.append(f"- **command:** `{bg_info.get('command', '')[:500]}`")
        lines.append(f"- **tool_use_id:** {bg_info.get('tool_use_id', '')}")
        lines.append("")
    # Process snapshot
    if bg_pids:
        lines.append("## Background process snapshot at kill")
        lines.append("```")
        for pid in bg_pids[:20]:
            try:
                with open(f"/proc/{pid}/stat", "rb") as f:
                    parts = f.read().split()
                state = parts[2].decode("ascii", "ignore") if len(parts) > 2 else "?"
                utime = int(parts[13]) if len(parts) > 13 else 0
                stime = int(parts[14]) if len(parts) > 14 else 0
                with open(f"/proc/{pid}/wchan", "rb") as f:
                    wchan = f.read().decode("ascii", "ignore").strip() or "-"
                with open(f"/proc/{pid}/comm", "rb") as f:
                    comm = f.read().decode("ascii", "ignore").strip()
                lines.append(
                    f"pid={pid} comm={comm} state={state} wchan={wchan} "
                    f"utime={utime} stime={stime}"
                )
            except (OSError, IOError, IndexError, ValueError):
                lines.append(f"pid={pid} (gone)")
        lines.append("```")
        lines.append("")
    try:
        diag_path.write_text("\n".join(lines) + "\n")
    except OSError:
        pass
    return diag_path


def extract_attempt_summary(log_path: Path) -> dict:
    """Extract a structured summary of what an agent attempted from its jsonl log.

    Returns a dict suitable for writing to the attempt log:
      tool_sequence, files_written, files_read, last_tool, error, progress_stage
    """
    tools: list[str] = []
    files_written: list[str] = []
    files_read: list[str] = []
    last_tool = ""
    error = ""
    num_tool_calls = 0

    try:
        for raw_line in log_path.read_text().splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                msg = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "assistant":
                content = msg.get("message", {}).get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        name = block.get("name", "?")
                        inp = block.get("input", {})
                        num_tool_calls += 1
                        if name in ("Write",):
                            fp = inp.get("file_path", "")
                            files_written.append(fp.split("/")[-1])
                            last_tool = f"Write({fp.split('/')[-1]})"
                        elif name == "Edit":
                            fp = inp.get("file_path", "")
                            files_written.append(fp.split("/")[-1])
                            last_tool = f"Edit({fp.split('/')[-1]})"
                        elif name == "Read":
                            fp = inp.get("file_path", "")
                            files_read.append(fp.split("/")[-1])
                            last_tool = f"Read({fp.split('/')[-1]})"
                        elif name == "Bash":
                            cmd = inp.get("command", "")[:80]
                            last_tool = f"Bash({cmd})"
                        else:
                            last_tool = name
                        tools.append(last_tool)
                    elif block.get("type") == "text":
                        text = block.get("text", "")
                        if re.search(r'Error|error', text) and "API Error" in text:
                            error = text[:200]

            elif msg.get("type") == "result" and msg.get("is_error"):
                error = msg.get("result", "")[:200]

    except Exception:
        pass

    # Determine progress stage
    if files_written:
        progress = "wrote_code"
    elif num_tool_calls > 15:
        progress = "exploring"
    elif num_tool_calls > 5:
        progress = "reading_context"
    else:
        progress = "startup"

    return {
        "tool_count": num_tool_calls,
        "files_written": list(dict.fromkeys(files_written)),  # dedupe, preserve order
        "files_read": list(dict.fromkeys(files_read)),
        "last_tool": last_tool,
        "error": error,
        "progress": progress,
    }


def write_attempt_record(spec_dir: str, task_id: str, agent_id: int,
                         duration_s: int, summary: dict,
                         session_id: str | None = None):
    """Append an attempt record to {spec_dir}/attempts/{task_id}.jsonl."""
    attempts_dir = Path(spec_dir) / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "agent": agent_id,
        "timestamp": datetime.now().isoformat(),
        "duration_s": duration_s,
        **summary,
    }
    if session_id:
        record["session_id"] = session_id
    with open(attempts_dir / f"{task_id}.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")


def read_attempt_history(spec_dir: str, task_id: str,
                         session_id: str | None = None) -> list[dict]:
    """Read attempt records for a task.

    If *session_id* is given, only return records from that session.
    This prevents old failures from a previous runner invocation from
    poisoning retry/failure decisions after the user intervenes.
    """
    path = Path(spec_dir) / "attempts" / f"{task_id}.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rec = json.loads(line)
                if session_id and rec.get("session_id") != session_id:
                    continue
                records.append(rec)
            except json.JSONDecodeError:
                pass
    return records


def check_deferred(task_id: str) -> bool:
    """Check if a DEFER file exists for this task."""
    return Path(f"DEFER-{task_id}.md").exists()


def clear_deferred(task_id: str):
    """Remove the DEFER file for a task."""
    p = Path(f"DEFER-{task_id}.md")
    if p.exists():
        p.unlink()


def _mark_task_done(task_file: Path, task_id: str):
    """Mark a task as complete in tasks.md by changing `- [ ]` to `- [x]`."""
    content = task_file.read_text()
    # Match the task line and flip the checkbox
    pattern = re.compile(
        r'^(- \[) \](\s+' + re.escape(task_id) + r'\s)',
        re.MULTILINE,
    )
    new_content = pattern.sub(r'\1x]\2', content)
    if new_content != content:
        task_file.write_text(new_content)


def _write_e2e_completion_claim(spec_dir: str, task_id: str, e2e_dir: Path,
                                findings: Optional[dict] = None):
    """Write a completion claim for an E2E loop task.

    The e2e-loop marks tasks done via _mark_task_done(), but the main loop's
    verification step expects a claims/completion-{task_id}.json with MCP
    evidence (screenshots, mcp_interactions).  Without this claim the
    verifier rejects the task with "no live evidence".
    """
    claim_dir = Path(spec_dir) / "claims"
    claim_dir.mkdir(parents=True, exist_ok=True)

    # Gather screenshot paths from the e2e screenshots directory
    screenshots_dir = e2e_dir / "screenshots"
    screenshot_paths = []
    if screenshots_dir.exists():
        screenshot_paths = sorted(
            str(p) for p in screenshots_dir.iterdir()
            if p.suffix.lower() in (".png", ".jpg", ".jpeg")
        )

    # Count MCP interactions from findings entries that have screenshot evidence
    mcp_count = 0
    if findings:
        all_entries = findings.get("findings", []) + findings.get("validations", [])
        mcp_count = len(all_entries)  # each finding required MCP interaction

    claim = {
        "task_id": task_id,
        "screenshots": screenshot_paths,
        "mcp_interactions": max(mcp_count, len(screenshot_paths)),
    }
    claim_path = claim_dir / f"completion-{task_id}.json"
    claim_path.write_text(json.dumps(claim, indent=2))


def _discover_test_commands() -> list[tuple[str, str]]:
    """Discover build/test/lint commands from CLAUDE.md and Makefile.

    Returns a list of (command, label) tuples. These are the commands the
    runner executes independently to verify phase completion.
    """
    commands: list[tuple[str, str]] = []

    # Check for Makefile targets
    makefile = Path("Makefile")
    if makefile.exists():
        content = makefile.read_text()
        # Look for common test/lint/build targets
        for target in ["test", "test-unit", "lint", "build"]:
            if re.search(rf'^{re.escape(target)}\s*:', content, re.MULTILINE):
                commands.append((f"make {target}", f"make {target}"))

    # Check for Gradle (Android/JVM)
    gradlew = Path("gradlew")
    android_dir = Path("android")
    if gradlew.exists() or (android_dir / "gradlew").exists():
        gw = "./gradlew" if gradlew.exists() else "cd android && ./gradlew"
        # Only add if android dir has source changes
        if android_dir.exists():
            commands.append((f"{gw} ktlintCheck", "Kotlin lint"))

    # Check for package.json scripts
    pkg_json = Path("package.json")
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            scripts = pkg.get("scripts", {})
            for name in ["test", "lint", "build", "check", "typecheck"]:
                if name in scripts:
                    commands.append((f"npm run {name}", f"npm run {name}"))
        except (json.JSONDecodeError, OSError):
            pass

    # Check for Cargo.toml (Rust)
    if Path("Cargo.toml").exists():
        commands.append(("cargo test", "cargo test"))
        commands.append(("cargo clippy -- -D warnings", "cargo clippy"))

    # Check for pyproject.toml / pytest
    if Path("pyproject.toml").exists() or Path("setup.py").exists():
        commands.append(("pytest", "pytest"))

    return commands


# ── Capability request parsing ────────────────────────────────────────

# Allowed capabilities that can be auto-granted from BLOCKED.md requests.
# Anything not in this set requires manual user intervention.
_AUTO_GRANTABLE_CAPS = {"gh", "e2e-loop"}

# Capabilities that are NEVER allowed alongside untrusted code execution.
# If a task's description matches any of these patterns, the capability is
# stripped even if declared, to prevent supply-chain exfiltration.
_UNTRUSTED_CODE_PATTERNS = re.compile(
    r'npm\s+install|pip\s+install|pip3\s+install|poetry\s+install|'
    r'yarn\s+install|pnpm\s+install|cargo\s+install|go\s+install|'
    r'bundle\s+install|gem\s+install|composer\s+install|'
    r'apt\s+install|apt-get\s+install|brew\s+install',
    re.IGNORECASE,
)

# Credentials that must be stripped when untrusted code patterns are detected.
_SENSITIVE_ENV_KEYS = {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"}


def _parse_capability_request(blocked_text: str) -> set[str]:
    """Parse a BLOCKED.md for capability requests like `[needs: gh]`.

    Returns the set of auto-grantable capabilities requested, or empty set
    if this is a regular block (needs human input).
    """
    # Look for [needs: X] or [capability: X] or "needs gh" patterns
    caps: set[str] = set()
    for m in re.finditer(r'\[(?:needs|capability|cap):\s*([^\]]+)\]', blocked_text, re.IGNORECASE):
        for c in m.group(1).split(','):
            c = c.strip().lower()
            if c in _AUTO_GRANTABLE_CAPS:
                caps.add(c)

    # Also match "gh CLI is not authenticated" or similar natural language
    if not caps and re.search(r'gh\s+(?:cli|auth|token|command).*(?:not\s+(?:authenticated|available|found)|fail)', blocked_text, re.IGNORECASE):
        caps.add("gh")

    return caps


def _extract_blocked_task_id(blocked_text: str) -> Optional[str]:
    """Try to extract the task ID from a BLOCKED.md file."""
    m = re.search(r'\b(T\d{3,4})\b', blocked_text)
    return m.group(1) if m else None


def _check_untrusted_code_risk(task: Task) -> bool:
    """Return True if a task is likely to execute untrusted code (package installs etc).

    When True, sensitive credentials (GH_TOKEN etc) MUST NOT be injected,
    regardless of declared capabilities.
    """
    return bool(_UNTRUSTED_CODE_PATTERNS.search(task.description))


# ── Platform runtime management ────────────────────────────────────────
#
# Built-in knowledge of platform runtimes (Android, Browser, iOS).
# Each platform defines how to boot, check readiness, build + install,
# generate MCP server config, and teardown.  Tasks declare platform
# needs via [needs: mcp-android], [needs: mcp-browser], [needs: mcp-ios].

# MCP capabilities that map to platform runtimes.
_MCP_CAPABILITIES = {"mcp-android", "mcp-browser", "mcp-ios"}

# These are auto-grantable (no user intervention needed).
_AUTO_GRANTABLE_CAPS |= _MCP_CAPABILITIES


# ── Platform drivers ───────────────────────────────────────────────────
#
# A PlatformDriver encapsulates everything the runner needs to know about
# a given MCP capability that ISN'T lifecycle (boot/teardown lives on
# PlatformRuntime).  The split: PlatformRuntime runs processes,
# PlatformDriver answers questions about *evidence* and *prompt content*.
#
# This is the registry the validator and prompt builder consult so that
# adding iOS (or any new platform) is a single class + one registry line,
# not a scavenger hunt through if/elif chains.


class PlatformDriver:
    """Per-capability knowledge used by the validator and prompt builder.

    Subclasses must set `capability` and `tool_prefix`, and should override
    `interactive_tools`, `tools_prompt_section`, and `screenshot_prompt_section`.
    The base class's `has_live_evidence` works for any driver whose
    `interactive_tools` list is populated — override only for unusual cases.
    """

    capability: str = ""
    tool_prefix: str = ""          # e.g. "mcp__mcp-android__"
    interactive_tools: tuple[str, ...] = ()  # unqualified names that count as live interaction

    def mcp_tool_calls_in_log(self, log_text: str) -> int:
        """Count interactive MCP tool calls for this platform in an agent log."""
        if not self.tool_prefix:
            return 0
        if not self.interactive_tools:
            # Fall back to any tool call with the platform prefix.
            return log_text.count(f'"name":"{self.tool_prefix}')
        total = 0
        for name in self.interactive_tools:
            total += log_text.count(f'"{self.tool_prefix}{name}"')
        return total

    def has_live_evidence(self, findings: dict, log_path: Optional[Path]) -> int:
        """Count live-evidence signals across findings + agent log.

        Returns the number of live-evidence signals (0 means blocked).
        """
        all_entries = (findings.get("findings") or []) + (findings.get("validations") or [])
        score = 0
        for f in all_entries:
            if f.get("screenshot_path") or f.get("screenshot"):
                score += 1
                continue
            shots = f.get("screenshots")
            if isinstance(shots, list) and shots:
                score += 1
                continue
            if "live" in (f.get("verification") or "").lower():
                score += 1
                continue
            if "live" in (f.get("result") or "").lower():
                score += 1
        if score == 0 and log_path and log_path.exists():
            try:
                score = self.mcp_tool_calls_in_log(log_path.read_text())
            except OSError:
                pass
        return score

    def read_mcp_init_status(self, log_path: Path) -> Optional[str]:
        """Return the MCP server status ('connected', 'failed', ...) for this
        driver's capability as reported in the agent's init record, or None
        if the log or record is unavailable.
        """
        if not log_path.exists():
            return None
        try:
            with log_path.open() as fh:
                first_line = fh.readline()
            init = json.loads(first_line)
        except (OSError, json.JSONDecodeError):
            return None
        for s in init.get("mcp_servers", []) or []:
            if s.get("name") == self.capability:
                return s.get("status")
        return None

    def tools_prompt_section(self, e2e_dir: Path) -> str:
        """Return the `## Available MCP tools` section for agent prompts."""
        return ""

    def screenshot_prompt_section(self, e2e_dir: Path) -> str:
        """Return the `## Saving screenshots` section for agent prompts (may be empty)."""
        return ""

    # ── Verify-agent prompt parts ────────────────────────────────────
    # These slot into _build_e2e_verify_prompt so adding iOS doesn't
    # require editing that builder.
    def verify_tools_section(self, e2e_dir: Path) -> str:
        """Terser tool-list for the verify agent (explore prompt has the full version)."""
        # Default: reuse tools_prompt_section. Subclasses can override
        # for a shorter restatement if desired.
        return self.tools_prompt_section(e2e_dir)

    def verify_screenshot_save_hint(self, e2e_dir: Path) -> str:
        """One-line 'how to save a screenshot on this platform' hint for the verify agent."""
        return ""

    def verify_evidence_observed_hint(self) -> str:
        """Platform-specific description for the `## Observed state` section of the evidence file."""
        return ("[Snapshot / hierarchy / accessibility-tree excerpt showing the relevant UI "
                "element(s). Paste the exact output — do not summarize or paraphrase it.]")

    # ── Fix-agent prompt parts ───────────────────────────────────────
    def fix_regression_test_hint(self) -> str:
        """Platform-specific hint about what makes a regression test 'behavioral'."""
        return (
            "**Regression test quality**: If the task says to write regression tests, they MUST "
            "be behavioral — test state transitions, side effects, and data flows, NOT just that "
            "text renders on screen. Call real functions with real inputs and assert real state."
        )


class AndroidDriver(PlatformDriver):
    capability = "mcp-android"
    tool_prefix = "mcp__mcp-android__"
    interactive_tools = (
        "State-Tool", "Click-Tool", "Long-Click-Tool", "Swipe-Tool",
        "Type-Tool", "Drag-Tool", "Press-Tool", "Notification-Tool",
    )

    def tools_prompt_section(self, e2e_dir: Path) -> str:
        return """## Available MCP tools

Tools are namespaced as `mcp__mcp-android__<name>`. Call them directly — do NOT use ToolSearch to discover them.

- **mcp__mcp-android__State-Tool**: Get device state. Pass `{"use_vision": true}` to include a screenshot image (**prefer this — cheaper than hierarchy dumps**). Without `use_vision`, returns the UI element tree as text.
- **mcp__mcp-android__Click-Tool**: Tap at coordinates `{"x": 540, "y": 1200}`
- **mcp__mcp-android__Long-Click-Tool**: Long-press at coordinates `{"x": 540, "y": 1200}`
- **mcp__mcp-android__Swipe-Tool**: Swipe from one point to another `{"x1": 540, "y1": 1600, "x2": 540, "y2": 400}` (for scrolling)
- **mcp__mcp-android__Type-Tool**: Type text at coordinates `{"text": "hello", "x": 540, "y": 600, "clear": true}` (set `clear: true` to replace existing text)
- **mcp__mcp-android__Drag-Tool**: Drag and drop `{"x1": 100, "y1": 200, "x2": 300, "y2": 400}`
- **mcp__mcp-android__Press-Tool**: Press a button `{"button": "back"}` (also: "home", "enter", "recent")
- **mcp__mcp-android__Notification-Tool**: Open the notification shade (no parameters)
- **mcp__mcp-android__Wait-Tool**: Pause for N **seconds** `{"duration": 2}` — NEVER pass more than 5

## Do NOT use curl / adb shell am start as a substitute

E2E validation means driving the *UI* — not hitting the app's internal
APIs or launching intents from shell. `curl`, `adb shell am start`,
and direct HTTP calls to the app's backend do not prove the user
experience works. Use the MCP tools above for every interaction.

The only legitimate non-MCP uses are:

- `adb shell screencap` / `adb pull` for saving screenshots (see below).
- `curl http://127.0.0.1:<port>/health` for verifying a backend service
  is up before you start driving the UI.
- Reading logs via `adb logcat` for debugging a finding.
"""

    def screenshot_prompt_section(self, e2e_dir: Path) -> str:
        return f"""## CRITICAL: Saving screenshots to disk

The MCP State-Tool returns screenshots as inline images in the conversation — they are NOT saved to disk. You MUST save screenshots to disk yourself using `adb screencap`, because the runner verifies that screenshot files exist on disk as proof of live MCP interaction.

**Every time you take a screenshot with State-Tool, ALSO save it to disk:**
```bash
mkdir -p {e2e_dir}/screenshots/ && adb shell screencap -p /sdcard/nk_screen.png && adb pull /sdcard/nk_screen.png {e2e_dir}/screenshots/<name>.png
```

Use a descriptive `<name>` like `T302-auth-screen`, `T302-error-invalid-key`, `T302-connected`. Then reference that path in findings.json `screenshot_path` field.

Do this at least once per screen you validate and once per bug you find. Without screenshots on disk, the runner will reject your work.
"""

    def verify_tools_section(self, e2e_dir: Path) -> str:
        return """## Available MCP tools

Same MCP tools as the explore agent (call directly, no ToolSearch needed):
`State-Tool`, `Click-Tool`, `Long-Click-Tool`, `Swipe-Tool`, `Type-Tool`, `Drag-Tool`, `Press-Tool`, `Notification-Tool`, `Wait-Tool` (duration in **seconds**, max 5).
All namespaced as `mcp__mcp-android__<name>`.

**Prefer `State-Tool` (no vision) over State-Tool with `use_vision=true`** to conserve context — only add vision when you genuinely need to *see* the screen.
"""

    def verify_screenshot_save_hint(self, e2e_dir: Path) -> str:
        return (f"Save screenshots to disk via `adb shell screencap -p /sdcard/nk_screen.png && "
                f"adb pull /sdcard/nk_screen.png {e2e_dir}/screenshots/<name>.png` — one per bug "
                f"max. The State-Tool shows you the screen inline but does NOT save to disk.")

    def verify_evidence_observed_hint(self) -> str:
        return ("[Raw DumpHierarchy XML snippet showing the relevant UI element(s). "
                "Copy the EXACT XML — do not summarize or paraphrase it. "
                "Include attribute values: class, text, content-desc, checkable, clickable, etc.]")

    def fix_regression_test_hint(self) -> str:
        return (
            "**Regression test quality**: Regression tests MUST be behavioral — test state "
            "transitions, side effects, and data flows, NOT just that text renders on screen. "
            "A test that mocks a ViewModel with a pre-set error string and asserts the string "
            "is displayed tests nothing useful. Instead: call the real validation function with "
            "invalid input and assert it returns false/throws. Call a ViewModel method and assert "
            "the state changes correctly. Use real Android context (InstrumentationRegistry) for "
            "persistence tests. See the task's \"Done when\" for specific behavioral assertions."
        )


class BrowserDriver(PlatformDriver):
    capability = "mcp-browser"
    tool_prefix = "mcp__mcp-browser__"
    # Interactive tools — snapshot counts because the prompt explicitly
    # tells agents to prefer it over screenshots for context efficiency.
    interactive_tools = (
        "browser_navigate", "browser_navigate_back", "browser_click",
        "browser_type", "browser_fill_form", "browser_snapshot",
        "browser_take_screenshot", "browser_press_key", "browser_hover",
        "browser_select_option", "browser_drag", "browser_evaluate",
        "browser_wait_for", "browser_file_upload", "browser_handle_dialog",
    )

    def tools_prompt_section(self, e2e_dir: Path) -> str:
        return f"""## Available MCP tools

You have `mcp-browser` (Playwright). Tools are namespaced as
`mcp__mcp-browser__<name>`. Call them directly — do NOT use ToolSearch
to discover them.

Common tools (the exact menu depends on server version — the runtime
expose function schemas; read those, don't guess):

- **browser_navigate** — go to a URL. `{{"url": "http://127.0.0.1:4321/kanix/"}}`.
- **browser_snapshot** — return the accessibility tree of the current
  page. **Prefer this over screenshots** — it's cheaper, and it gives
  you the exact `ref` IDs you need for click/type.
- **browser_click** — click an element by `ref` from the snapshot.
- **browser_type** — type into an input (also by `ref`).
- **browser_fill_form** — fill multiple fields at once (cheaper than
  one `browser_type` per field).
- **browser_take_screenshot** — PNG snapshot. Use sparingly; screenshots
  are expensive in context.
- **browser_wait_for** — wait for text/selector. Prefer this over sleeps.
- **browser_evaluate** — run JS in the page. Use for reading computed
  state that isn't in the accessibility tree.
- **browser_network_requests** / **browser_console_messages** — capture
  requests or console output when debugging.

**Do NOT call `browser_install`.** The browser is pre-provisioned by
Nix (`mcp-browser` wrapper points at Nix's chromium via
`--executable-path`). `browser_install` triggers a Google-Chrome
download that hangs forever inside the agent sandbox. If a tool error
claims the browser is missing, that's a configuration bug — file it as
a finding and stop; do NOT try to "fix" it by downloading.

## Do NOT use curl / wget / fetch as a substitute

The whole point of an E2E run is to exercise the app through a real
browser: JS executes, cookies persist across requests, Astro's client
islands hydrate, SuperTokens sets session headers, Stripe loads in an
iframe, etc.

- `curl`, `wget`, `http`, `fetch`, `node -e "fetch(...)"` and similar
  **do not count as E2E validation** and must not be used to exercise
  the app. If you catch yourself reaching for curl, switch to the
  browser tools.
- The **only** legitimate curl uses during an E2E run are: checking
  that a backend service is up (`curl -sf http://127.0.0.1:3000/health`)
  or reading a raw API response for cross-checking what the UI
  displayed. Never as a replacement for a navigation flow.
- If the browser tools aren't working, record that as a finding and
  stop — do not fall back to curl to claim you validated the flow.

## Saving screenshots to disk

When you need a screenshot (use sparingly), call `browser_take_screenshot`
with a full path in the `filename` parameter so it lands on disk — the
runner verifies screenshot files exist as proof of live MCP interaction.

```
browser_take_screenshot {{
  "filename": "{e2e_dir}/screenshots/T096-cart.png",
  "fullPage": true
}}
```

Use descriptive names like `T096-home`, `T096-cart`, `T096-checkout-error`.
Reference the path in `findings.json` as `screenshot_path`.
"""

    def verify_tools_section(self, e2e_dir: Path) -> str:
        return """## Available MCP tools

Same `mcp-browser` (Playwright) tools as the explore agent — call directly, no ToolSearch needed. Key ones:
`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_fill_form`, `browser_take_screenshot`, `browser_wait_for`, `browser_evaluate`, `browser_network_requests`.

**Prefer `browser_snapshot` over `browser_take_screenshot`** — the accessibility tree is cheaper in context and gives you exact `ref` IDs. Reserve screenshots for visual-only evidence.
"""

    def verify_screenshot_save_hint(self, e2e_dir: Path) -> str:
        return (f"Save screenshots by passing `filename` to `browser_take_screenshot`, "
                f"e.g. `{{\"filename\": \"{e2e_dir}/screenshots/<name>.png\", \"fullPage\": true}}`. "
                f"One per bug max.")

    def verify_evidence_observed_hint(self) -> str:
        return ("[Accessibility-tree excerpt from `browser_snapshot` showing the relevant "
                "element(s). Paste the exact ref + role + name lines — do not paraphrase. "
                "If the bug is a network/data issue, include the relevant "
                "`browser_network_requests` entry or `browser_console_messages` line instead.]")

    def fix_regression_test_hint(self) -> str:
        return (
            "**Regression test quality**: Regression tests MUST be behavioral. Prefer Playwright "
            "tests that drive the real page (`page.goto`, `page.getByRole`, assert network calls "
            "or final DOM state). A unit test that asserts a mocked handler was called with "
            "stubbed inputs proves nothing. If the bug was in server/API logic, add an "
            "integration test that hits the real endpoint end-to-end."
        )


class IOSDriver(PlatformDriver):
    """iOS driver — stub until the mcp-ios integration lands.

    This exists so the registry has an entry and adding iOS support is a
    matter of filling in `interactive_tools` + `tools_prompt_section`
    rather than wiring new dispatch sites. `has_live_evidence` still
    returns screenshot-based evidence from findings, which is enough to
    catch obvious no-ops; a task that lists `[needs: mcp-ios]` today will
    fail the MCP-server readiness check before evidence evaluation runs.
    """

    capability = "mcp-ios"
    tool_prefix = "mcp__mcp-ios__"
    interactive_tools = ()  # TODO: fill in when mcp-ios tool surface is finalized

    def tools_prompt_section(self, e2e_dir: Path) -> str:
        return """## Available MCP tools

You have `mcp-ios` (via `xcrun simctl` / XCTest bridge). Tools are
namespaced as `mcp__mcp-ios__<name>`. Call them directly — do NOT use
ToolSearch to discover them. Read the function schemas to see the exact
tool menu your runtime exposes.

## Do NOT use curl or shell commands as a substitute

E2E validation means driving the *UI* through simulator input. `curl`,
direct HTTP calls, and shell intents do not prove the user experience
works. Use the MCP tools for every interaction.
"""


_PLATFORM_DRIVERS: dict[str, PlatformDriver] = {
    d.capability: d for d in (AndroidDriver(), BrowserDriver(), IOSDriver())
}


def _pick_driver(caps: set[str]) -> Optional[PlatformDriver]:
    """Pick the primary driver for a task's capability set.

    Browser wins over Android wins over iOS when a task declares multiple
    (rare). Returns None when no MCP capability is declared.
    """
    for c in ("mcp-browser", "mcp-android", "mcp-ios"):
        if c in caps:
            return _PLATFORM_DRIVERS[c]
    return None


@dataclass
class PlatformRuntime:
    """Manages lifecycle for a single platform runtime (emulator/browser/sim)."""

    name: str           # "android", "browser", "ios"
    capability: str     # "mcp-android", "mcp-browser", "mcp-ios"
    _booted: bool = False
    _mcp_process: Optional[subprocess.Popen] = None
    _mcp_config_path: Optional[Path] = None

    def boot(self, project_dir: Path, log_fn=None) -> bool:
        """Boot the platform runtime. Returns True on success."""
        _log = log_fn or (lambda msg: print(f"[platform:{self.name}] {msg}", file=sys.stderr))

        if self._booted:
            _log(f"{self.name} already booted")
            return True

        if self.name == "android":
            return self._boot_android(project_dir, _log)
        elif self.name == "browser":
            return self._boot_browser(project_dir, _log)
        elif self.name == "ios":
            return self._boot_ios(project_dir, _log)
        return False

    def readiness_check(self, log_fn=None) -> bool:
        """Check if the runtime is ready to accept commands."""
        _log = log_fn or (lambda msg: print(f"[platform:{self.name}] {msg}", file=sys.stderr))

        if self.name == "android":
            return self._check_android_ready(_log)
        elif self.name == "browser":
            return True  # Browser MCP server handles its own readiness
        elif self.name == "ios":
            return self._check_ios_ready(_log)
        return False

    def build_and_install(self, project_dir: Path, log_fn=None,
                          build_log_path: Optional[Path] = None) -> BuildResult:
        """Build and install the app for this platform.

        Returns a BuildResult enum indicating success, build failure (code
        issue), or install failure (infrastructure issue like dead emulator).

        If build_log_path is provided, the full build output (stdout+stderr) is
        written there so agents can inspect failures without loading the entire
        output into their context window.
        """
        _log = log_fn or (lambda msg: print(f"[platform:{self.name}] {msg}", file=sys.stderr))

        if self.name == "android":
            return self._build_install_android(project_dir, _log, build_log_path)
        elif self.name == "browser":
            return BuildResult.OK
        elif self.name == "ios":
            return self._build_install_ios(project_dir, _log)
        return BuildResult.NOT_READY

    @staticmethod
    def _has_debugkit_flake_input(project_dir: Path) -> bool:
        """Check if the project's flake.nix has nix-mcp-debugkit as an input."""
        flake_path = project_dir / "flake.nix"
        if not flake_path.exists():
            return False
        try:
            content = flake_path.read_text()
            return "nix-mcp-debugkit" in content
        except OSError:
            return False

    def _mcp_run_args(self, server_name: str, project_dir: Path) -> list[str]:
        """Return the nix run args for an MCP server using the project's flake input."""
        base = ["run", f".#mcp-{self.name}", "--"]
        # Android MCP needs --emulator to connect via adb to emulator-5554
        if self.name == "android":
            base.append("--emulator")
        return base

    def _resolve_mcp_binary(self, server_name: str, project_dir: Path) -> Optional[str]:
        """Try to resolve the MCP server to a direct nix store binary path.

        Using the store path directly avoids nix run's flake evaluation overhead,
        which can cause the Claude CLI's MCP init to time out.
        """
        nix_args = ["nix", "build", "--no-link", "--print-out-paths", f".#mcp-{self.name}"]
        try:
            result = subprocess.run(
                nix_args, capture_output=True, text=True, timeout=120,
                cwd=str(project_dir),
            )
            if result.returncode == 0:
                store_path = result.stdout.strip()
                binary = Path(store_path) / "bin" / server_name
                if binary.exists():
                    return str(binary)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None

    def get_mcp_config(self, project_dir: Optional[Path] = None) -> dict:
        """Return the MCP server configuration JSON for this platform.

        Resolves the nix store path at config time so the Claude CLI can start
        the MCP server instantly without nix run's flake evaluation overhead.
        Falls back to nix run if resolution fails.
        """
        _dir = project_dir or Path.cwd()
        server_name = f"mcp-{self.name}"
        if self.name in ("android", "browser", "ios"):
            # Try direct store path first (fast startup)
            binary = self._resolve_mcp_binary(server_name, _dir)
            if binary:
                args = []
                if self.name == "android":
                    args.append("--emulator")
                return {
                    server_name: {
                        "command": binary,
                        "args": args,
                    }
                }
            # Fall back to nix run (slow but always works)
            return {
                server_name: {
                    "command": "nix",
                    "args": self._mcp_run_args(server_name, _dir),
                }
            }
        return {}

    def start_mcp_server(self, project_dir: Path, log_fn=None) -> bool:
        """Start the MCP server process and write config file. Returns True on success."""
        _log = log_fn or (lambda msg: print(f"[platform:{self.name}] {msg}", file=sys.stderr))

        # Write MCP config to a temp file for --mcp-config.
        # Claude CLI expects {"mcpServers": {<server-name>: {command, args}}}.
        config = {"mcpServers": self.get_mcp_config(project_dir)}
        config_dir = project_dir / ".specify" / "mcp"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"{self.name}.json"
        config_path.write_text(json.dumps(config, indent=2))
        self._mcp_config_path = config_path

        _log(f"MCP config written to {config_path}")
        return True

    def teardown(self, log_fn=None):
        """Stop the runtime and MCP server."""
        _log = log_fn or (lambda msg: print(f"[platform:{self.name}] {msg}", file=sys.stderr))

        if self._mcp_process and self._mcp_process.poll() is None:
            self._mcp_process.terminate()
            try:
                self._mcp_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._mcp_process.kill()
            _log(f"MCP server stopped")
            self._mcp_process = None

        if self._mcp_config_path and self._mcp_config_path.exists():
            self._mcp_config_path.unlink()
            self._mcp_config_path = None

        if self.name == "android":
            subprocess.run(["adb", "emu", "kill"], capture_output=True, timeout=30)
            _log("Android emulator stopped")
        elif self.name == "ios":
            subprocess.run(["xcrun", "simctl", "shutdown", "booted"], capture_output=True, timeout=30)
            _log("iOS simulator stopped")

        self._booted = False

    @property
    def mcp_config_path(self) -> Optional[Path]:
        return self._mcp_config_path

    # ── Android internals ──

    def _boot_android(self, project_dir: Path, log) -> bool:
        """Boot Android emulator. Looks for project-provided start-emulator or uses adb."""
        log("Booting Android emulator...")

        # Check for project-provided emulator script (e.g. nix-key's start-emulator)
        start_script = None
        for candidate in [
            project_dir / "scripts" / "start-emulator.sh",
            project_dir / "scripts" / "start-emulator",
        ]:
            if candidate.exists():
                start_script = candidate
                break

        # Try nix-provided start-emulator (from devshell)
        if not start_script and shutil.which("start-emulator"):
            start_script = Path(shutil.which("start-emulator"))

        if start_script:
            log(f"Using emulator script: {start_script}")
            result = subprocess.run(
                [str(start_script)],
                capture_output=True, timeout=300,
                cwd=str(project_dir),
            )
            if result.returncode != 0:
                log(f"Emulator script failed: {result.stderr.decode()[:300]}")
                return False
        else:
            # Fallback: try nix develop --command start-emulator if a flake exists
            flake_nix = project_dir / "flake.nix"
            if flake_nix.exists():
                log("start-emulator not in PATH — trying via nix develop")
                result = subprocess.run(
                    ["nix", "develop", str(project_dir), "--command",
                     "start-emulator"],
                    capture_output=True, timeout=300,
                    cwd=str(project_dir),
                )
                if result.returncode == 0:
                    log("Emulator started via nix develop")
                else:
                    log(f"nix develop start-emulator failed: {result.stderr.decode()[:300]}")
                    return False
            else:
                # Last resort: try emulator command directly
                avd_list = subprocess.run(
                    ["emulator", "-list-avds"], capture_output=True, timeout=10
                )
                avds = avd_list.stdout.decode().strip().splitlines()
                if not avds:
                    log("No AVDs found and no nix flake. Cannot boot emulator.")
                    return False
                avd = avds[0]
                log(f"Booting AVD: {avd}")
                subprocess.Popen(
                    ["emulator", f"@{avd}", "-no-window", "-gpu", "swiftshader_indirect", "-no-audio"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )

        # Wait for boot
        if not self._wait_for("boot_completed",
                              ["adb", "shell", "getprop", "sys.boot_completed"],
                              expected="1", timeout=180, log=log):
            return False

        # Wait for package manager (important for install)
        log("Waiting for package manager...")
        deadline = time.time() + 120
        while time.time() < deadline:
            pm = subprocess.run(
                ["adb", "shell", "pm", "list", "packages"],
                capture_output=True, timeout=10,
            )
            if pm.returncode == 0 and len(pm.stdout.decode().splitlines()) > 30:
                break
            time.sleep(3)
        else:
            log("Package manager not ready after 120s")
            return False

        self._booted = True
        log("Android emulator ready")
        return True

    def _check_android_ready(self, log) -> bool:
        try:
            result = subprocess.run(
                ["adb", "shell", "getprop", "sys.boot_completed"],
                capture_output=True, timeout=5,
            )
            return result.stdout.decode().strip() == "1"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _build_install_android(self, project_dir: Path, log,
                               build_log_path: Optional[Path] = None) -> BuildResult:
        """Build debug APK and install on emulator.

        Returns BuildResult.OK on success, BUILD_FAILED if compilation fails,
        or INSTALL_FAILED if the build succeeds but adb install fails (e.g.
        emulator crashed).

        If build_log_path is provided, the full build stdout+stderr is written
        there so that agents can read the tail on failure without loading the
        entire output into context.
        """
        log("Building Android APK...")

        def _write_build_log(result: subprocess.CompletedProcess, phase: str):
            if not build_log_path:
                return
            with open(build_log_path, "a") as f:
                f.write(f"\n{'=' * 60}\n")
                f.write(f"Phase: {phase}\n")
                f.write(f"Exit code: {result.returncode}\n")
                f.write(f"{'=' * 60}\n")
                if result.stdout:
                    f.write("--- stdout ---\n")
                    f.write(result.stdout.decode(errors="replace"))
                if result.stderr:
                    f.write("\n--- stderr ---\n")
                    f.write(result.stderr.decode(errors="replace"))
                f.write("\n")

        # Detect build system
        gradle_dir = None
        for candidate in [project_dir / "android", project_dir]:
            if (candidate / "gradlew").exists():
                gradle_dir = candidate
                break

        if not gradle_dir:
            # Try make target
            if (project_dir / "Makefile").exists():
                result = subprocess.run(
                    ["make", "android-apk"], capture_output=True, timeout=600,
                    cwd=str(project_dir),
                )
                _write_build_log(result, "make android-apk")
                if result.returncode != 0:
                    log(f"make android-apk failed (full log: {build_log_path})")
                    return BuildResult.BUILD_FAILED
            else:
                log("No Gradle or Makefile found for Android build")
                return BuildResult.BUILD_FAILED
        else:
            result = subprocess.run(
                [str(gradle_dir / "gradlew"), "assembleDebug"],
                capture_output=True, timeout=600,
                cwd=str(gradle_dir),
            )
            _write_build_log(result, "gradlew assembleDebug")
            if result.returncode != 0:
                log(f"Gradle assembleDebug failed (full log: {build_log_path})")
                return BuildResult.BUILD_FAILED

        # Find and install APK
        apk_candidates = list(project_dir.rglob("*-debug.apk")) + list(project_dir.rglob("app-debug.apk"))
        if not apk_candidates:
            log("No debug APK found after build")
            return BuildResult.BUILD_FAILED

        apk = sorted(apk_candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        log(f"Installing APK: {apk}")
        install = subprocess.run(
            ["adb", "install", "-r", "-t", str(apk)],
            capture_output=True, timeout=120,
        )
        _write_build_log(install, "adb install")
        if install.returncode != 0:
            stderr_text = install.stderr.decode(errors="replace")
            if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in stderr_text:
                # Signing key changed — uninstall old app and retry
                pkg = "com.nixkey"
                # Try to extract package name from APK
                try:
                    aapt = subprocess.run(
                        ["adb", "shell", "pm", "list", "packages"],
                        capture_output=True, timeout=10,
                    )
                    # Use a broad match from the stderr message
                    import re as _re
                    m = _re.search(r"package (\S+) ", stderr_text)
                    if m:
                        pkg = m.group(1)
                except Exception:
                    pass
                log(f"Signature mismatch — uninstalling {pkg} and retrying")
                subprocess.run(
                    ["adb", "uninstall", pkg],
                    capture_output=True, timeout=30,
                )
                install = subprocess.run(
                    ["adb", "install", "-r", "-t", str(apk)],
                    capture_output=True, timeout=120,
                )
                _write_build_log(install, "adb install (retry after uninstall)")
            if install.returncode != 0:
                log(f"APK install failed (full log: {build_log_path})")
                return BuildResult.INSTALL_FAILED

        log("APK installed successfully")
        return BuildResult.OK

    # ── iOS internals ──

    def _boot_ios(self, project_dir: Path, log) -> bool:
        log("Booting iOS simulator...")
        # List available simulators
        result = subprocess.run(
            ["xcrun", "simctl", "list", "devices", "--json"],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            log("xcrun simctl not available")
            return False

        try:
            devices = json.loads(result.stdout)
            # Find first available iPhone simulator
            for runtime, devs in devices.get("devices", {}).items():
                if "iOS" not in runtime:
                    continue
                for dev in devs:
                    if dev.get("isAvailable") and "iPhone" in dev.get("name", ""):
                        udid = dev["udid"]
                        log(f"Booting simulator: {dev['name']} ({udid})")
                        subprocess.run(["xcrun", "simctl", "boot", udid], capture_output=True, timeout=30)
                        self._booted = True
                        return self._check_ios_ready(log)
        except (json.JSONDecodeError, KeyError):
            pass

        log("No available iOS simulator found")
        return False

    def _check_ios_ready(self, log) -> bool:
        try:
            result = subprocess.run(
                ["xcrun", "simctl", "list", "devices"],
                capture_output=True, timeout=10,
            )
            return b"Booted" in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _build_install_ios(self, project_dir: Path, log) -> BuildResult:
        log("Building iOS app...")
        # Find .xcodeproj or .xcworkspace
        xcworkspaces = list(project_dir.rglob("*.xcworkspace"))
        xcprojects = list(project_dir.rglob("*.xcodeproj"))
        target = xcworkspaces[0] if xcworkspaces else (xcprojects[0] if xcprojects else None)

        if not target:
            log("No Xcode project found")
            return BuildResult.BUILD_FAILED

        flag = "-workspace" if target.suffix == ".xcworkspace" else "-project"
        result = subprocess.run(
            ["xcodebuild", flag, str(target), "-scheme", target.stem,
             "-sdk", "iphonesimulator", "-destination", "platform=iOS Simulator,name=iPhone 15",
             "-configuration", "Debug", "build"],
            capture_output=True, timeout=600,
            cwd=str(project_dir),
        )
        if result.returncode != 0:
            log(f"xcodebuild failed: {result.stderr.decode()[:300]}")
            return BuildResult.BUILD_FAILED

        # Find and install .app
        apps = list(project_dir.rglob("Debug-iphonesimulator/*.app"))
        if apps:
            install = subprocess.run(
                ["xcrun", "simctl", "install", "booted", str(apps[0])],
                capture_output=True, timeout=30,
            )
            if install.returncode != 0:
                log(f"simctl install failed: {install.stderr.decode()[:300]}")
                return BuildResult.INSTALL_FAILED
            log(f"Installed {apps[0].name} on simulator")

        self._booted = True
        return BuildResult.OK

    # ── Browser internals ──

    def _boot_browser(self, project_dir: Path, log) -> bool:
        # Browser MCP server bundles Chromium — no separate boot needed
        self._booted = True
        log("Browser runtime ready (Chromium bundled with MCP server)")
        return True

    # ── Shared helpers ──

    def _wait_for(self, name: str, cmd: list[str], expected: str,
                  timeout: int, log, interval: int = 3) -> bool:
        """Poll a command until output matches expected or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=5)
                if result.stdout.decode().strip() == expected:
                    log(f"{name} ready ({int(time.time() - (deadline - timeout))}s)")
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
            time.sleep(interval)
        log(f"{name} not ready after {timeout}s")
        return False


class PlatformManager:
    """Manages all platform runtimes for a runner session.

    In addition to MCP platform runtimes (emulator, browser, simulator), this
    manager supports **backend E2E services** via a project-level setup/teardown
    script convention. If the project has a `test/e2e/setup.sh`, the manager
    runs it once before the first runtime boots to start backend services
    (databases, API servers, mesh networks, daemons, etc.). On teardown, it
    runs `test/e2e/teardown.sh` if present.

    This is project-agnostic: any project declares its own infrastructure needs
    in its setup script. The runner doesn't need to know what the services are.
    """

    def __init__(self, log_fn=None):
        self._runtimes: dict[str, PlatformRuntime] = {}
        self._log = log_fn or (lambda msg: print(f"[platforms] {msg}", file=sys.stderr))
        self._e2e_services_started = False

    def _start_e2e_services(self, project_dir: Path) -> bool:
        """Run the project's E2E setup script to start backend services.

        Convention: if test/e2e/setup.sh exists, it starts all backend services
        needed for E2E testing (headscale, tailscale, daemon, database, etc.).
        The script should:
        - Be idempotent (safe to call if services already running)
        - Write PIDs to a known location for teardown
        - Exit 0 when all services are ready
        - Exit non-zero on failure

        The script is called every time because it handles its own idempotency
        (checking PIDs, restarting dead services).  This makes the system
        resilient to machine sleep, process crashes, or any other interruption
        that kills backend services between tasks.
        """
        # Always store the canonical project_dir for teardown
        self._e2e_project_dir = project_dir

        setup_script = project_dir / "test" / "e2e" / "setup.sh"
        if not setup_script.exists():
            self._log("No test/e2e/setup.sh found — skipping backend service setup")
            self._e2e_services_started = True
            return True

        self._log(f"Running E2E backend services setup: {setup_script}")
        setup_log = project_dir / "test" / "e2e" / ".state" / "setup-failure.log"
        setup_log.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                ["bash", str(setup_script)],
                capture_output=True, text=True, timeout=300,
                cwd=str(project_dir),
                env={**os.environ, "E2E_PROJECT_DIR": str(project_dir)},
            )
            if result.returncode != 0:
                self._log(f"E2E setup failed (exit {result.returncode}):")
                self._log(f"  stdout (last 2000 chars): {result.stdout[-2000:]}")
                self._log(f"  stderr (last 2000 chars): {result.stderr[-2000:]}")
                setup_log.write_text(
                    f"=== exit code: {result.returncode} ===\n"
                    f"=== stdout ===\n{result.stdout}\n"
                    f"=== stderr ===\n{result.stderr}\n"
                )
                self._log(f"  Full output written to {setup_log}")
                return False
            self._log("E2E backend services started successfully")
            if result.stdout.strip():
                self._log(f"  setup output: {result.stdout.strip()[:200]}")
            self._e2e_services_started = True
            return True
        except subprocess.TimeoutExpired as e:
            # Capture partial output from the killed process so the fix-agent
            # has something to debug.
            partial_stdout = (e.stdout or b"")
            partial_stderr = (e.stderr or b"")
            if isinstance(partial_stdout, bytes):
                partial_stdout = partial_stdout.decode("utf-8", errors="replace")
            if isinstance(partial_stderr, bytes):
                partial_stderr = partial_stderr.decode("utf-8", errors="replace")
            self._log("E2E setup timed out after 300s")
            if partial_stdout.strip():
                self._log(f"  stdout (last 2000 chars): {partial_stdout[-2000:]}")
            if partial_stderr.strip():
                self._log(f"  stderr (last 2000 chars): {partial_stderr[-2000:]}")
            setup_log.write_text(
                f"=== timed out after 300s ===\n"
                f"=== stdout ===\n{partial_stdout}\n"
                f"=== stderr ===\n{partial_stderr}\n"
            )
            self._log(f"  Full output written to {setup_log}")
            return False
        except Exception as e:
            self._log(f"E2E setup error: {e}")
            try:
                setup_log.write_text(f"=== exception: {e!r} ===\n")
            except OSError:
                pass
            return False

    def _stop_e2e_services(self, project_dir: Path):
        """Run the project's E2E teardown script to stop backend services."""
        if not self._e2e_services_started:
            return

        teardown_script = project_dir / "test" / "e2e" / "teardown.sh"
        if not teardown_script.exists():
            self._e2e_services_started = False
            return

        self._log(f"Running E2E backend services teardown: {teardown_script}")
        try:
            subprocess.run(
                ["bash", str(teardown_script)],
                capture_output=True, text=True, timeout=60,
                cwd=str(project_dir),
            )
            self._log("E2E backend services stopped")
        except Exception as e:
            self._log(f"E2E teardown error: {e}")
        self._e2e_services_started = False

    def ensure_runtime(self, capability: str, project_dir: Path) -> Optional[PlatformRuntime]:
        """Boot a platform runtime if not already running. Returns the runtime or None on failure."""
        if capability not in _MCP_CAPABILITIES:
            return None

        name = capability.replace("mcp-", "")  # "mcp-android" -> "android"

        if name in self._runtimes and self._runtimes[name]._booted:
            return self._runtimes[name]

        # Start backend services before first runtime boot
        if not self._start_e2e_services(project_dir):
            self._log("Backend E2E services failed to start — cannot proceed")
            return None

        runtime = PlatformRuntime(name=name, capability=capability)
        self._log(f"Initializing {name} platform runtime...")

        if not runtime.boot(project_dir, self._log):
            self._log(f"Failed to boot {name} runtime")
            return None

        if not runtime.readiness_check(self._log):
            self._log(f"{name} runtime failed readiness check")
            return None

        # Register early so build_and_install can find the runtime
        self._runtimes[name] = runtime

        build_result = self.build_and_install(capability, project_dir)
        if build_result != BuildResult.OK:
            self._log(f"Failed to build/install for {name} ({build_result.value})")
            del self._runtimes[name]
            return None

        if not runtime.start_mcp_server(project_dir, self._log):
            self._log(f"Failed to start MCP server for {name}")
            del self._runtimes[name]
            return None

        self._log(f"{name} platform runtime fully initialized")
        return runtime

    def build_and_install(self, capability: str, project_dir: Path,
                          build_log_path: Optional[Path] = None) -> BuildResult:
        """Build and install app on a running runtime. Idempotent."""
        name = capability.replace("mcp-", "")
        runtime = self._runtimes.get(name)
        if not runtime or not runtime._booted:
            self._log(f"Cannot build — {name} runtime not running")
            return BuildResult.NOT_READY

        return runtime.build_and_install(project_dir, self._log, build_log_path)

    def restart_runtime(self, capability: str, project_dir: Path) -> bool:
        """Restart a platform runtime (e.g. reboot a crashed emulator).

        Tears down the existing runtime, then boots + readiness-checks it
        fresh.  Does NOT rebuild/reinstall — caller should follow up with
        build_and_install() after a successful restart.

        Returns True if the runtime came back up, False otherwise.
        """
        name = capability.replace("mcp-", "")
        runtime = self._runtimes.get(name)
        if not runtime:
            self._log(f"Cannot restart — no {name} runtime registered")
            return False

        self._log(f"Restarting {name} runtime...")
        try:
            runtime.teardown(self._log)
        except Exception as e:
            self._log(f"Error tearing down {name} during restart: {e}")

        runtime._booted = False
        if not runtime.boot(project_dir, self._log):
            self._log(f"Failed to reboot {name} runtime")
            return False

        if not runtime.readiness_check(self._log):
            self._log(f"{name} runtime failed readiness check after restart")
            return False

        if not runtime.start_mcp_server(project_dir, self._log):
            self._log(f"Failed to restart MCP server for {name}")
            return False

        self._log(f"{name} runtime restarted successfully")
        return True

    def get_mcp_config_paths(self, capabilities: set[str]) -> list[Path]:
        """Get MCP config file paths for the given capabilities."""
        paths = []
        for cap in capabilities & _MCP_CAPABILITIES:
            name = cap.replace("mcp-", "")
            runtime = self._runtimes.get(name)
            if runtime and runtime.mcp_config_path:
                paths.append(runtime.mcp_config_path)
        return paths

    def _detect_android_package(self, project_dir: Path) -> Optional[str]:
        """Detect the Android app package name from build.gradle or manifest."""
        # Try build.gradle.kts first
        for gradle_path in [
            project_dir / "android" / "app" / "build.gradle.kts",
            project_dir / "android" / "app" / "build.gradle",
            project_dir / "app" / "build.gradle.kts",
            project_dir / "app" / "build.gradle",
        ]:
            if gradle_path.exists():
                content = gradle_path.read_text()
                m = re.search(r'applicationId\s*[=:]\s*["\']([^"\']+)["\']', content)
                if m:
                    return m.group(1)

        # Try AndroidManifest.xml
        for manifest_path in [
            project_dir / "android" / "app" / "src" / "main" / "AndroidManifest.xml",
            project_dir / "app" / "src" / "main" / "AndroidManifest.xml",
        ]:
            if manifest_path.exists():
                content = manifest_path.read_text()
                m = re.search(r'package\s*=\s*"([^"]+)"', content)
                if m:
                    return m.group(1)

        return None

    def teardown_all(self, project_dir: Optional[Path] = None):
        """Stop all runtimes and backend services."""
        for name, runtime in self._runtimes.items():
            try:
                runtime.teardown(self._log)
            except Exception as e:
                self._log(f"Error tearing down {name}: {e}")
        self._runtimes.clear()

        # Stop backend E2E services — use the canonical project_dir
        # stored during _start_e2e_services, since callers often pass
        # spec_dir.parent which resolves to the wrong path.
        effective_dir = getattr(self, '_e2e_project_dir', None) or project_dir
        if effective_dir:
            self._stop_e2e_services(effective_dir)

    @property
    def active_runtimes(self) -> dict[str, PlatformRuntime]:
        return dict(self._runtimes)


# ── E2E Explore-Fix-Verify findings format ────────────────────────────

E2E_FINDINGS_SCHEMA = {
    "version": 2,
    "findings": [
        {
            "id": "BUG-001",
            "severity": "critical|high|medium|low",
            "screen": "screen name from UI_FLOW.md",
            "flow": "which user flow this was found in",
            "summary": "one-line description",
            "steps_to_reproduce": ["step 1", "step 2"],
            "expected": "what should happen",
            "actual": "what actually happens",
            "screenshot_path": "path to screenshot if taken",
            "view_tree_path": "path to view tree dump if taken",
            "status": "new|fixed|verified_fixed|verified_broken|wont_fix",
            "bug_dir": "validate/e2e/bugs/BUG-001",
        }
    ],
}


# ── Per-bug file management for E2E research/supervisor loop ─────────

def _prepare_findings_context(findings_file: Path, e2e_dir: Path,
                              max_inline_bytes: int = 20_000) -> tuple[str, str]:
    """Prepare findings for prompt embedding with size management.

    Returns (inline_text, overflow_note).

    - Strips 'pass' entries (validation noise — not useful for agents).
    - If remaining findings fit within max_inline_bytes, returns them inline.
    - Otherwise, writes the full filtered findings to a separate overflow
      file and returns a compact summary inline + a note pointing to the
      overflow file.  Agents should only read the overflow file if they
      need more detail than the summary provides.
    """
    if not findings_file.exists():
        return "", ""

    try:
        data = json.loads(findings_file.read_text())
    except (json.JSONDecodeError, OSError):
        return "", ""

    all_findings = data.get("findings", [])
    if not all_findings:
        return "", ""

    # Filter out pass entries — they're validation noise
    actionable = [f for f in all_findings if f.get("status") != "pass"]
    pass_count = len(all_findings) - len(actionable)

    if not actionable:
        return f"All {pass_count} prior findings were passing validations — no bugs found yet.", ""

    # Build the filtered payload
    filtered_data = dict(data)
    filtered_data["findings"] = actionable
    filtered_json = json.dumps(filtered_data, indent=2)

    if len(filtered_json) <= max_inline_bytes:
        note = ""
        if pass_count > 0:
            note = f"\n({pass_count} passing validations omitted)"
        return filtered_json + note, ""

    # Over budget — write full filtered findings to overflow file, inline a summary
    overflow_path = e2e_dir / "findings-full.json"
    overflow_path.write_text(filtered_json)

    # Build compact summary
    by_status: dict[str, list[dict]] = {}
    for f in actionable:
        by_status.setdefault(f.get("status", "unknown"), []).append(f)

    lines = [f"**{len(actionable)} actionable findings** ({pass_count} passing validations omitted):"]
    for status, bugs in sorted(by_status.items()):
        lines.append(f"- {status}: {len(bugs)}")
        for b in bugs[:5]:  # Show first 5 per status
            lines.append(f"  - {b.get('id', '?')}: {b.get('summary', '?')}")
        if len(bugs) > 5:
            lines.append(f"  - ... and {len(bugs) - 5} more")

    summary = "\n".join(lines)
    overflow_note = (
        f"\nFull findings at `{overflow_path}` — only read this file if "
        f"you need more detail (steps to reproduce, expected/actual, etc.). "
        f"Do NOT read it by default."
    )
    return summary, overflow_note


def _prepare_progress_context(progress_file: Path, e2e_dir: Path,
                              max_inline_bytes: int = 8_000) -> tuple[str, str]:
    """Prepare progress.md for prompt embedding with size management.

    Returns (inline_text, overflow_note).

    If progress fits within max_inline_bytes, returns it inline.
    Otherwise writes the full content to an overflow file and returns
    only the last section inline (most recent progress) with a pointer.
    """
    if not progress_file.exists():
        return "", ""

    content = progress_file.read_text()
    if not content.strip():
        return "", ""

    if len(content) <= max_inline_bytes:
        return content, ""

    # Over budget — write full progress to overflow, inline the tail
    overflow_path = e2e_dir / "progress-full.md"
    overflow_path.write_text(content)

    # Keep the last ~max_inline_bytes of content (most recent progress)
    tail = content[-max_inline_bytes:]
    # Try to start at a line boundary
    first_newline = tail.find("\n")
    if first_newline > 0:
        tail = tail[first_newline + 1:]

    overflow_note = (
        f"\nFull progress history at `{overflow_path}` — only read this "
        f"file if you need to check whether a specific screen was already "
        f"validated. Do NOT read it by default."
    )
    return f"(showing most recent progress only)\n{tail}", overflow_note


def _bug_dir(e2e_dir: Path, bug_id: str) -> Path:
    """Return the per-bug directory, creating it if needed."""
    d = e2e_dir / "bugs" / bug_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_bug_history(e2e_dir: Path, bug_id: str) -> dict:
    """Read a bug's fix history from disk. Returns empty structure if none."""
    history_file = _bug_dir(e2e_dir, bug_id) / "history.json"
    if history_file.exists():
        try:
            return json.loads(history_file.read_text())
        except json.JSONDecodeError:
            pass
    return {"bug_id": bug_id, "fix_attempts": [], "supervisor_runs": 0}


def _write_bug_history(e2e_dir: Path, bug_id: str, history: dict):
    """Persist a bug's fix history to disk."""
    history_file = _bug_dir(e2e_dir, bug_id) / "history.json"
    history_file.write_text(json.dumps(history, indent=2))


def _read_supervisor_summaries(e2e_dir: Path, bug_id: str) -> list[str]:
    """Read all supervisor summary files for a bug, in order."""
    bug_d = _bug_dir(e2e_dir, bug_id)
    summaries = []
    n = 1
    while True:
        f = bug_d / f"supervisor-{n}-summary.md"
        if not f.exists():
            break
        summaries.append(f.read_text())
        n += 1
    return summaries


def _read_latest_research(e2e_dir: Path, bug_id: str) -> tuple[str, int]:
    """Read the most recent research file for a bug. Returns (content, index)."""
    bug_d = _bug_dir(e2e_dir, bug_id)
    n = 1
    latest = ("", 0)
    while True:
        f = bug_d / f"research-{n}.md"
        if not f.exists():
            break
        latest = (f.read_text(), n)
        n += 1
    return latest


def _count_fix_attempts(history: dict) -> int:
    """Count total fix attempts from a bug's history."""
    return len(history.get("fix_attempts", []))


def _record_fix_attempt(e2e_dir: Path, bug_id: str, approach: str,
                        verify_status: str, verify_evidence: str):
    """Record a fix attempt in the bug's history file."""
    history = _read_bug_history(e2e_dir, bug_id)
    history["fix_attempts"].append({
        "attempt": len(history["fix_attempts"]) + 1,
        "approach": approach,
        "verify_status": verify_status,
        "verify_evidence": verify_evidence,
        "timestamp": datetime.now().isoformat(),
    })
    _write_bug_history(e2e_dir, bug_id, history)


# ── Planner/executor helpers ───────────────────────────────────────────
# Two-tier explore phase: Opus planner writes plan.md, Sonnet executor
# walks it and writes handoff.md (resume marker) or blocker.md (stuck).
# On blocker, a small Opus diagnostic writes unblock.md; executor retries.

EXECUTOR_MAX_SPAWNS_PER_ITER = 5
BLOCKER_MAX_RETRIES_PER_STEP = 3


def _executor_dir(e2e_dir: Path) -> Path:
    d = e2e_dir / "executor"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _blocker_step_dir(e2e_dir: Path, step_id: str) -> Path:
    """Return per-step blocker dir. step_id is e.g. 'step-6' — caller sanitizes."""
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in step_id)[:64] or "step-unknown"
    d = e2e_dir / "blockers" / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _count_blocker_attempts(e2e_dir: Path, step_id: str) -> int:
    """Count how many blocker-N.md files exist for a step."""
    d = _blocker_step_dir(e2e_dir, step_id)
    return len(list(d.glob("blocker-*.md")))


def _list_prior_executor_attempts(e2e_dir: Path, step_id: str) -> list[Path]:
    """Return summary paths for prior executor attempts on this step, in order."""
    d = _blocker_step_dir(e2e_dir, step_id)
    return sorted(d.glob("executor-summary-*.md"))


def _list_prior_unblocks(e2e_dir: Path, step_id: str) -> list[Path]:
    """Return unblock-N.md paths for this step, in order."""
    d = _blocker_step_dir(e2e_dir, step_id)
    return sorted(d.glob("unblock-*.md"))


def _extract_executor_summary(log_path: Path, max_entries: int = 50) -> str:
    """Build a mechanical summary of an executor session from its JSONL log.

    Zero-LLM: just extracts tool calls, findings deltas, and final result.
    Matches the existing "truncate, inline, overflow to disk" paradigm.
    """
    if not log_path.exists():
        return "(no log)"
    try:
        lines = log_path.read_text().splitlines()
    except OSError:
        return "(log unreadable)"

    tool_calls: list[str] = []
    result_info = ""
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        etype = entry.get("type", "")
        if etype == "assistant":
            msg = entry.get("message", {})
            for block in msg.get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "?")
                    inp = block.get("input", {}) or {}
                    # Keep inputs terse — first ~80 chars of the string repr
                    inp_str = json.dumps(inp, default=str)[:120]
                    tool_calls.append(f"{name} {inp_str}")
        elif etype == "result":
            result_info = (
                f"result: is_error={entry.get('is_error')} "
                f"num_turns={entry.get('num_turns')} "
                f"duration_ms={entry.get('duration_ms')}"
            )

    # Keep last max_entries tool calls
    tool_calls = tool_calls[-max_entries:]
    parts = [f"## Tool calls (last {len(tool_calls)})"]
    parts.extend(f"- {c}" for c in tool_calls)
    if result_info:
        parts.append(f"\n## Result\n{result_info}")
    return "\n".join(parts)


def _write_executor_summary(e2e_dir: Path, step_id: str, attempt: int,
                             log_path: Path):
    """Extract + persist a mechanical summary of the executor's session."""
    d = _blocker_step_dir(e2e_dir, step_id)
    summary = _extract_executor_summary(log_path)
    (d / f"executor-summary-{attempt}.md").write_text(summary)


def check_circuit_breaker(spec_dir: str, window_minutes: int = 10,
                          threshold: int = 3) -> Optional[int]:
    """Check if recent attempts across all tasks are all connection errors.

    Returns seconds to wait if circuit is tripped, None otherwise.
    Looks at the last `threshold` attempts within `window_minutes` across
    ALL tasks. If all of them are connection errors, trip the breaker.
    """
    attempts_dir = Path(spec_dir) / "attempts"
    if not attempts_dir.is_dir():
        return None

    cutoff = datetime.now().timestamp() - (window_minutes * 60)
    recent: list[dict] = []

    for f in attempts_dir.glob("*.jsonl"):
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                # Parse timestamp
                ts = datetime.fromisoformat(record.get("timestamp", "")).timestamp()
                if ts >= cutoff:
                    recent.append(record)
            except (json.JSONDecodeError, ValueError):
                pass

    if len(recent) < threshold:
        return None

    # Sort by timestamp descending, check last N
    recent.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    last_n = recent[:threshold]

    all_conn_errors = all(
        re.search(r'UND_ERR_SOCKET|ECONNRESET|ECONNREFUSED|ETIMEDOUT|Unable to connect to API',
                  r.get("error", ""))
        for r in last_n
    )

    if all_conn_errors:
        return 300  # wait 5 minutes
    return None


def should_use_retry_prompt(history: list[dict]) -> bool:
    """Determine if a task should get a lightweight retry prompt.

    True when: code was already written by a prior agent AND
    the last 2+ failures were connection errors (not code bugs).
    """
    if len(history) < 2:
        return False

    # Check if any attempt wrote code
    any_wrote_code = any(h.get("progress") == "wrote_code" for h in history)
    if not any_wrote_code:
        return False

    # Check last 2 attempts were connection errors
    last_two = history[-2:]
    return all(
        re.search(r'UND_ERR_SOCKET|ECONNRESET|ECONNREFUSED|ETIMEDOUT|Unable to connect to API',
                  h.get("error", ""))
        for h in last_two
    )


def build_retry_prompt(task_file: str, spec_dir: str, learnings_file: str,
                       task: Task, history: list[dict]) -> str:
    """Build a minimal prompt for retrying a task where code is already written.

    Skips the full context-reading phase. Tells the agent to verify existing
    code compiles/passes and mark the task complete.
    """
    # Collect files written by prior agents
    all_written = []
    for h in history:
        all_written.extend(h.get("files_written", []))
    unique_written = list(dict.fromkeys(all_written))

    nix_note = ""
    if (Path.cwd() / "flake.nix").exists():
        nix_note = """
**Environment**: This project uses Nix (`flake.nix`). Your PATH already includes all tools from the nix devshell — run commands directly. Do NOT prefix commands with `nix develop --command`.
"""

    prompt = f"""You are a retry agent. A prior agent already implemented task **{task.id}** but crashed from an API connection error before it could verify and mark complete.
{nix_note}
## Your job

1. Check that the implementation files exist: {', '.join(unique_written) if unique_written else '(check git diff or git status for recent changes)'}
2. Read `CLAUDE.md` for build/test commands
3. Try to compile: `go build ./...` or equivalent
4. If it compiles, run a quick test: `go test -short ./...` or equivalent for the relevant package
5. If tests pass (or the only failures are unrelated to this task), mark the task complete
6. If the code is broken or incomplete, fix it

## Marking complete

1. In `{task_file}`, change task {task.id}'s `- [ ]` to `- [x]`
2. Commit with: `feat({task.id}): ...`
3. Append any discoveries to `{learnings_file}` (max 3 concise bullets)

## If build/test can't run

If dependencies can't be fetched (network issues), but the code looks correct:
- Verify with `go vet ./...` (no network needed)
- If vet passes and the code looks complete, mark complete — phase validation will run full tests later

## Do NOT

- Re-read the spec, plan, or data-model — you don't need them
- Rewrite code that already exists
- Explore the codebase extensively
- Write to `DEFER-{task.id}.md` unless the code genuinely doesn't exist

**This is attempt #{len(history) + 1}.** Prior agents crashed from connection errors, not code bugs. Be fast and focused.
"""
    return prompt


# ── CI debug loop ─────────────────────────────────────────────────────
#
# Tasks marked [needs: gh, ci-loop] use a runner-managed debug cycle
# instead of a single long-running agent.  The runner:
#
#   1. Spawns a "push" sub-agent to push current code
#   2. Polls CI in the main thread (no agent context burned)
#   3. On failure: downloads logs, spawns a "diagnose" sub-agent that
#      writes a diagnosis file, then spawns a "fix" sub-agent that
#      reads the diagnosis and applies the fix
#   4. Repeats until CI passes or the attempt cap is hit
#
# All artifacts go to ci-debug/<task_id>/ so agents can read prior
# history without inflating their own context.

CI_LOOP_MAX_ATTEMPTS = 50
CI_LOCAL_MAX_ITERATIONS = 20
CI_REPEAT_FAILURE_THRESHOLD = 5  # Stop if same job fails this many consecutive times
CI_LOOP_DIR = "ci-debug"
# Watchdog: kill a sub-agent if its JSONL log goes idle.
CI_AGENT_IDLE_TIMEOUT_S = 15 * 60   # kill after 15 min of log silence
CI_AGENT_HARD_TIMEOUT_S = 60 * 60   # absolute cap as a safety net

# Main-loop watchdog: kill VR / task agents if they go idle.
# VR agents legitimately wait on long tool results (flutter test, nix build) so
# the default idle budget is generous. The hard cap prevents runaway loops.
AGENT_IDLE_TIMEOUT_S = 20 * 60      # default: kill after 20 min of log silence
AGENT_HARD_TIMEOUT_S = 90 * 60      # absolute wall-clock cap per agent
# When a background bash task has 0 CPU while its owner agent is log-silent,
# treat that as a deadlock after this window (shorter than AGENT_IDLE_TIMEOUT_S
# because a CPU-idle background task is unambiguous evidence of a hang).
AGENT_BG_DEADLOCK_S = 5 * 60


def _get_https_remote_url() -> Optional[str]:
    """Convert the origin remote URL to HTTPS form for GH_TOKEN auth.

    SSH remotes (git@github.com:user/repo.git) trigger hardware key prompts
    (YubiKey etc.), so we always push via HTTPS with GH_TOKEN instead.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
        )
        url = result.stdout.strip()
        # Convert SSH URL to HTTPS
        m = re.match(r'git@github\.com:(.+?)(?:\.git)?$', url)
        if m:
            return f"https://github.com/{m.group(1)}.git"
        if url.startswith("https://"):
            return url
    except Exception:
        pass
    return None


def _gh_push(branch: str, log_fn=None) -> bool:
    """Push to origin using GH_TOKEN over HTTPS (avoids SSH/YubiKey prompts).

    Returns True on success.
    """
    token = _acquire_gh_token()
    if not token:
        if log_fn:
            log_fn("No GH_TOKEN available for push")
        return False

    https_url = _get_https_remote_url()
    if not https_url:
        if log_fn:
            log_fn("Could not determine HTTPS remote URL")
        return False

    # Use token in the URL for auth (git strips it from logs)
    auth_url = https_url.replace("https://", f"https://x-access-token:{token}@")

    env = dict(os.environ)
    # Disable SSH agent to prevent YubiKey prompts
    env.pop("SSH_AUTH_SOCK", None)

    result = subprocess.run(
        ["git", "push", auth_url, branch],
        capture_output=True, text=True, timeout=60, env=env,
    )
    if result.returncode != 0:
        if log_fn:
            log_fn(f"Push failed: {result.stderr.strip()}")
        return False
    return True


def _ci_debug_dir(task_id: str) -> Path:
    """Return (and create) the ci-debug directory for a task."""
    d = Path(CI_LOOP_DIR) / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _poll_ci_run(branch: str, timeout_minutes: int = 30,
                 stop_event: Optional[threading.Event] = None,
                 skip_run_ids: Optional[set[int]] = None) -> dict:
    """Poll GitHub Actions for the latest run on `branch` until it completes.

    Returns a dict with keys: status ("pass"|"fail"|"cancelled"|"timeout"|"error"),
    run_id, conclusion, url, and failed_jobs (list of job names).

    If stop_event is set during polling, returns early with status "interrupted".
    skip_run_ids: set of run IDs to ignore (e.g. previously cancelled runs).
    """
    import time as _time

    if skip_run_ids is None:
        skip_run_ids = set()

    def _should_stop() -> bool:
        return stop_event is not None and stop_event.is_set()

    # Get the current local HEAD so we can match against the right CI run
    try:
        local_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        local_head = None

    # Wait a moment for GitHub to register the push
    for _ in range(10):
        if _should_stop():
            return {"status": "interrupted", "error": "drain/shutdown requested"}
        _time.sleep(1)

    # Find the latest run for this branch that matches our HEAD
    run_id = None
    find_deadline = _time.time() + 120  # wait up to 2 min for GitHub to create the run
    while _time.time() < find_deadline:
        if _should_stop():
            return {"status": "interrupted", "error": "drain/shutdown requested"}
        try:
            result = subprocess.run(
                ["gh", "run", "list", "--branch", branch, "--limit", "5", "--json",
                 "databaseId,status,conclusion,url,headSha"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                for _ in range(10):
                    if _should_stop():
                        return {"status": "interrupted", "error": "drain/shutdown requested"}
                    _time.sleep(1)
                continue

            runs = json.loads(result.stdout)
            for run in runs:
                rid = run["databaseId"]
                if rid in skip_run_ids:
                    continue
                # If we know local HEAD, prefer the run that matches it
                if local_head and run.get("headSha", "").startswith(local_head[:12]):
                    run_id = rid
                    break
                # Otherwise take the first non-skipped run
                if not local_head:
                    run_id = rid
                    break

            if run_id is not None:
                break
        except Exception:
            pass

        # GitHub hasn't created the run yet — wait and retry
        for _ in range(10):
            if _should_stop():
                return {"status": "interrupted", "error": "drain/shutdown requested"}
            _time.sleep(1)

    if run_id is None:
        # Fallback: take whatever is latest (even if HEAD doesn't match)
        try:
            result = subprocess.run(
                ["gh", "run", "list", "--branch", branch, "--limit", "1", "--json",
                 "databaseId,status,conclusion,url,headSha"],
                capture_output=True, text=True, timeout=30,
            )
            runs = json.loads(result.stdout)
            if runs and runs[0]["databaseId"] not in skip_run_ids:
                run_id = runs[0]["databaseId"]
            else:
                return {"status": "error", "error": f"No matching CI run found for branch {branch} (HEAD: {local_head[:8] if local_head else '?'})"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # Poll until complete
    deadline = _time.time() + timeout_minutes * 60
    while _time.time() < deadline:
        if _should_stop():
            return {"status": "interrupted", "run_id": run_id, "error": "drain/shutdown requested"}
        try:
            result = subprocess.run(
                ["gh", "run", "view", str(run_id), "--json",
                 "status,conclusion,url,jobs"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                # Sleep in small increments to stay responsive to stop_event
                for _ in range(30):
                    if _should_stop():
                        return {"status": "interrupted", "run_id": run_id, "error": "drain/shutdown requested"}
                    _time.sleep(1)
                continue

            data = json.loads(result.stdout)
            if data.get("status") == "completed":
                conclusion = data.get("conclusion", "unknown")
                failed_jobs = [
                    j["name"] for j in data.get("jobs", [])
                    if j.get("conclusion") not in ("success", "skipped", None)
                ]
                if conclusion == "success":
                    status = "pass"
                elif conclusion == "cancelled":
                    status = "cancelled"
                else:
                    status = "fail"
                return {
                    "status": status,
                    "run_id": run_id,
                    "conclusion": conclusion,
                    "url": data.get("url", ""),
                    "failed_jobs": failed_jobs,
                }
        except Exception:
            pass
        # Sleep in small increments to stay responsive to stop_event
        for _ in range(30):
            if _should_stop():
                return {"status": "interrupted", "run_id": run_id, "error": "drain/shutdown requested"}
            _time.sleep(1)

    return {"status": "timeout", "run_id": run_id}


def _download_ci_logs(run_id: int, output_path: Path) -> bool:
    """Download failed job logs from a CI run to a file.

    Returns True if logs were written successfully.
    """
    try:
        result = subprocess.run(
            ["gh", "run", "view", str(run_id), "--log-failed"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            output_path.write_text(result.stdout)
            return True
        # Fallback: try full log
        result = subprocess.run(
            ["gh", "run", "view", str(run_id), "--log"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            # Truncate to last 500 lines to keep it manageable
            lines = result.stdout.splitlines()
            output_path.write_text("\n".join(lines[-500:]))
            return True
    except Exception:
        pass
    return False


def _download_ci_artifact(run_id: int, artifact_name: str, output_dir: Path) -> Optional[Path]:
    """Download a specific artifact from a CI run. Returns path or None."""
    try:
        result = subprocess.run(
            ["gh", "run", "download", str(run_id), "-n", artifact_name, "-D", str(output_dir)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            # Find the downloaded file
            for f in output_dir.iterdir():
                return f
    except Exception:
        pass
    return None


def build_ci_diagnose_prompt(task_id: str, attempt: int, debug_dir: Path,
                             ci_result: dict, learnings_file: str) -> str:
    """Build prompt for the CI diagnosis sub-agent.

    This agent reads CI logs + prior history and writes a diagnosis file.
    It does NOT fix code — just analyzes and recommends.
    """
    log_file = debug_dir / f"attempt-{attempt}-logs.txt"
    history_files = sorted(debug_dir.glob("attempt-*-diagnosis.md"))
    sanity_files = sorted(debug_dir.glob("attempt-*-sanity-check-fail.md"))
    prior_section = ""
    if history_files or sanity_files:
        prior_section = f"""## Prior diagnosis history

These files contain diagnoses from previous CI attempts. Read them to understand
what was already tried and avoid repeating failed fixes:

"""
        for hf in history_files:
            prior_section += f"- `{hf}`\n"
        for sf in sanity_files:
            prior_section += f"- `{sf}` (**sanity-check failure** — CI passed but results were suspicious)\n"
        prior_section += "\n"

    nix_note = ""
    if (Path.cwd() / "flake.nix").exists():
        nix_note = "**Environment**: This project uses Nix. Your PATH includes all devshell tools.\n\n"

    return f"""You are a CI failure diagnosis agent for task **{task_id}**, attempt #{attempt}.

{nix_note}## Your job

Analyze the CI failure and write a diagnosis to `{debug_dir}/attempt-{attempt}-diagnosis.md`.

**You MUST NOT modify any source code, config files, or CI workflows.**
Your only output is the diagnosis file.

## CI result

- **Status**: {ci_result.get('conclusion', 'unknown')}
- **URL**: {ci_result.get('url', 'N/A')}
- **Failed jobs**: {', '.join(ci_result.get('failed_jobs', [])) or 'unknown'}
- **Run ID**: {ci_result.get('run_id', 'N/A')}

## Input files

1. **CI failure logs**: `{log_file}` — raw output from failed CI jobs
2. **Learnings**: `{learnings_file}` — project-specific gotchas

{prior_section}## Diagnosis file format

Write `{debug_dir}/attempt-{attempt}-diagnosis.md` with this structure:

```markdown
# CI Diagnosis — Attempt {attempt}

## Root cause
[One paragraph: what exactly failed and why]

## Failed jobs
[List each failed job with its specific error]

## Recommended fix
[Specific files to change and what to change — be precise with line numbers]

## Risk assessment
[What might break if this fix is applied naively]

## Files to modify
[Bulleted list of exact file paths that need changes]
```

## Rules

- Read the CI logs thoroughly before writing
- Pay special attention to `##[warning]` lines in CI logs — these reveal silent
  misconfigurations (wrong input names, deprecated features, ignored parameters)
  that cause actions to fall back to broken defaults. A warning like
  "Unexpected input(s) 'trivy_version'" IS the root cause, not a side effect.
- If prior diagnoses exist, note what changed since the last attempt
- Be specific: "line 42 of .github/workflows/ci.yml references a nonexistent action" not "CI config is wrong"
- If the same root cause repeats across attempts, flag it as a deeper issue
- Do NOT modify any files other than the diagnosis file
- Do NOT read ROUTER.md or use the Skill tool
"""


def build_ci_fix_prompt(task_id: str, attempt: int, debug_dir: Path,
                        task_file: str, learnings_file: str) -> str:
    """Build prompt for the CI fix sub-agent.

    This agent reads the diagnosis, applies the fix, and runs local validation.
    It does NOT push — the runner manages the push after local validation passes.
    """
    diagnosis_file = debug_dir / f"attempt-{attempt}-diagnosis.md"
    history_files = sorted(debug_dir.glob("attempt-*-diagnosis.md"))

    nix_note = ""
    nix_commands_note = ""
    if (Path.cwd() / "flake.nix").exists():
        nix_note = "**Environment**: This project uses Nix. Your PATH includes all devshell tools.\n\n"
        nix_commands_note = """
### Nix note

You are inside a sandbox. Do NOT run `nix develop --command` (fails on store writes).
Do NOT run `nix flake check` — it runs VM tests that take 10-20 min and the validate agent
handles that. For `nixfmt --check`, run it directly (it's already in PATH).

"""

    return f"""You are a CI fix agent for task **{task_id}**, attempt #{attempt}.

{nix_note}## Your job

1. Read `CLAUDE.md` for the project's build, lint, and test commands
2. Read the diagnosis at `{diagnosis_file}`
3. Read the latest local validation result in `{debug_dir}/` (the most recent `attempt-*-local-*.md` file)
4. Apply the recommended fix
5. Run **fast checks only** to verify your fix doesn't break the basics (see below)
6. Commit your changes (but do NOT push — the runner handles pushing)

## Context files

- **CLAUDE.md** — read this FIRST for build/test/lint commands
- **CI workflow**: `.github/workflows/ci.yml` (or equivalent) — reference for what CI runs
- **Diagnosis**: `{diagnosis_file}` — read this to understand what to fix
- **Prior attempts**: `{debug_dir}/` — contains logs, diagnoses, and validation results from all attempts
- **Learnings**: `{learnings_file}` — project-specific gotchas

## Fast checks (MANDATORY after applying fix)

After applying your fix, run ONLY fast commands to sanity-check your changes. The runner has
a separate validate agent that runs the full suite (including slow commands) — you do NOT
need to duplicate that work.

**Fast commands** (run these — typically <60s each):
- Lint: `golangci-lint run`, `eslint`, `ruff check`, `nixfmt --check`, etc.
- Build: `go build ./...`, `npm run build`, `cargo build`, etc.
- Unit tests: `go test -short ./...`, `npm test`, `pytest -x`, etc.
  - Use `-short` flag or equivalent to skip integration tests
  - For Go: `go test -short ./...` (NOT `-race -count=1` — that's for the full suite)

**Slow commands** (do NOT run these — the validate agent handles them):
- `nix flake check` / `nix build` (NixOS VM tests — 10-20 min)
- Docker-based integration tests
- E2E tests that boot infrastructure
- Full test suites with `-race -count=1` (use `-short` instead)
- Any command that takes more than ~60 seconds

If a fast check fails after your fix, fix it and re-run. You have up to **3 iterations** of
fast checks. If fast checks still fail after 3 tries, commit what you have and document the
remaining issues in `{debug_dir}/attempt-{attempt}-fix-notes.md`.
{nix_commands_note}
## GitHub Actions: verify inputs before modifying

When fixing a GitHub Actions `with:` block, do NOT guess input names from memory.
Fetch the action's `action.yml` to confirm valid input names:

    gh api repos/OWNER/REPO/contents/action.yml --jq .content | base64 -d | head -50

For example, `aquasecurity/trivy-action` uses `version`, not `trivy_version`.
Wrong input names are silently ignored and the action falls back to defaults,
wasting an entire CI round-trip to discover the mistake.

## Rules

- Fix ONLY what the diagnosis identifies — do not refactor or improve other code
- Commit with message: `fix({task_id}): [description of CI fix]`
- Do NOT push — the runner validates your fix and pushes after confirming local validation passed
- Do NOT run slow commands (VM tests, nix flake check, E2E tests) — the validate agent does that
- If the diagnosis is unclear or you disagree with it, write your reasoning to
  `{debug_dir}/attempt-{attempt}-fix-notes.md` before applying an alternative fix
- Do NOT create PRs or merge anything — the runner handles that after CI passes
- Do NOT read ROUTER.md or use the Skill tool
- Do NOT truncate command output — write to files and read what you need
- Append any CI-specific discoveries to `{learnings_file}`
"""


def build_ci_local_validate_prompt(task_id: str, attempt: int, local_iteration: int,
                                   debug_dir: Path, learnings_file: str,
                                   prior_output: str = "") -> str:
    """Build prompt for the local validation sub-agent.

    This agent runs the same commands CI would run and reports pass/fail.
    It does NOT fix anything — just validates and reports.
    """
    nix_note = ""
    nix_commands_note = ""
    if (Path.cwd() / "flake.nix").exists():
        nix_note = "**Environment**: This project uses Nix. Your PATH includes all devshell tools.\n\n"
        nix_commands_note = """
### Nix-specific command instructions

You are running inside a sandbox. To run nix commands that need the daemon:

- **ALWAYS** set `NIX_REMOTE=daemon` when running nix commands
- **ALWAYS** pass `--extra-experimental-features 'nix-command flakes'` to nix
- **NEVER** pipe nix output through `head`, `tail`, or any truncation
- **NEVER** use `nix develop --command` inside the sandbox — it will fail on store writes
- `nix flake check --print-build-logs` runs NixOS VM tests that take **10-20 minutes**. Use a timeout of at least 1800 seconds (30 min). Run it in the background and use TaskOutput to wait for it.
- **Write output to a file** so you can examine any portion after the command finishes:
  ```
  NIX_REMOTE=daemon nix --extra-experimental-features 'nix-command flakes' flake check --print-build-logs > /tmp/nix-flake-check.log 2>&1; echo "EXIT_CODE=$?" >> /tmp/nix-flake-check.log
  ```
- After the command finishes, read the exit code and the **last 200 lines** of `/tmp/nix-flake-check.log` — the critical errors (service crashes, test assertion failures, FTL messages) are always at the end.
- If it failed, also search the log file for `FTL`, `FAIL`, `error:`, and `failed with` to find the root cause.
- Include the relevant error output in your report — the fix agent needs to see the actual error messages, not just "exit code 1".

"""

    prior_section = ""
    if prior_output:
        prior_section = f"""## Prior validation output (iteration {local_iteration - 1})

The previous local validation failed with this output — the fix agent has attempted to
address these failures. Re-run everything from scratch to verify.

```
{prior_output[-3000:]}
```

"""

    return f"""You are a local validation agent for task **{task_id}**, CI attempt #{attempt}, local iteration #{local_iteration}.

{nix_note}## Your job

Run the SAME commands that CI runs and report the results. You do NOT fix anything.
{nix_commands_note}
### Step 1: Discover CI commands

Read `.github/workflows/ci.yml` (or scan `.github/workflows/` for the CI workflow). For each
job, extract every `run:` command. Skip only:
- GitHub Actions `uses:` steps that have no local equivalent (checkout, upload-artifact, setup-java, install-nix, cachix, etc.)
- Steps gated on CI-only secrets (`SNYK_TOKEN`, `SONAR_TOKEN`, `CACHIX_AUTH_TOKEN`)
- SARIF uploads, artifact uploads, job summary generation
- Steps in `if: always()` blocks that only generate reports

**IMPORTANT**: For `uses:` steps that DO have local equivalents, run the local equivalent:
- Security scanners (Trivy, Semgrep, etc.) → run `make security-scan` or the equivalent local command
- Check the project's Makefile or CLAUDE.md for local equivalents of CI-only actions

Everything else MUST run — do NOT skip build steps. Pay special attention to:
- `nix flake check --print-build-logs` — this runs NixOS VM tests
- `go test -json -race -count=1 ./...` — full test suite, not just `-short`
- Linters: `golangci-lint run`, `nixfmt --check`, etc.
- Build steps like `gomobile bind` — these MUST run even if a later step also builds (e.g., Gradle)

### Step 2: Run ALL commands in order

Run them in CI order (lint, build, test, integration/VM tests). For each command:
- Run it and capture the **full output** (NEVER truncate with head/tail/pipes)
- If it fails, continue to the next command (so we collect ALL failures in one pass,
  just like CI would)

### Step 3: Report results

After running all commands, write a validation result file to:
`{debug_dir}/attempt-{attempt}-local-{local_iteration}.md`

Format:
```markdown
# Local Validation — Attempt {attempt}, Iteration {local_iteration}

## Result: PASS or FAIL

## Commands run
| Command | Exit code | Status |
|---------|-----------|--------|
| `go build ./...` | 0 | PASS |
| `golangci-lint run` | 0 | PASS |
| `go test -json -race ./...` | 1 | FAIL |
| `nix flake check` | 1 | FAIL |

## Failure details
(For each failed command: the key error output, file paths, line numbers.
 Be specific — a fix agent will read this to understand what to fix.)

### Command: `go test -json -race ./...`
(relevant error output)

### Command: `nix flake check --print-build-logs`
(relevant error output — include systemd unit failures, service crash logs, etc.)
```

{prior_section}## Critical: reading output carefully

- A systemd unit that starts and then exits with status 1 is a **FAILURE** — report it
- A process that logs `FTL` (fatal) or `ERR` (error) before exiting is a **FAILURE**
- Do not confuse a user-cancelled run with a genuine test failure
- Include the actual error messages, not just "exit code 1"

## Sanity check: results must make sense

After running all commands, sanity-check the results **semantically** before writing your report.
A command can exit 0 but still indicate a broken setup. Treat ALL of the following as **FAIL**:

- **Zero tests ran**: a test runner exits 0 but reports 0 passed / 0 failed — something is misconfigured
  (missing test runner binary, wrong working directory, no test files found, build failed silently before tests)
- **Phantom passes**: test count is dramatically lower than the number of test files/functions on disk
  (e.g., 50 test functions exist but only 2 ran — likely a filter or compilation error hiding tests)
- **Missing artifacts**: a build or test step claims success but expected output files are absent
  (e.g., no JUnit XML in `build/test-results/`, no binary produced by `go build`, no coverage data)
- **Silent tool failures**: a tool like `./gradlew`, `cargo`, or `npm` was not found or crashed on
  startup — even if the pipeline continued, this is a FAIL
- **Empty output**: a step that normally produces substantial output produced nothing (e.g., linter
  ran in 0.01s with no output — it likely didn't find any files to lint)

To verify: cross-reference the number of tests reported against the actual test source files on disk.
Use `find` or `glob` to count test files/functions, then compare with the runner's reported count.
If they diverge significantly, investigate and report it as a failure with details.

- **Exit code swallowed by pipe**: a command like `cmd 2>&1 | tee log.txt` exits 0 even if `cmd` failed,
  unless `set -o pipefail` is set. Check CI workflow steps that pipe output — if the pipe target
  (`tee`, `head`, etc.) succeeds, the step succeeds regardless of the source command's exit code.
  Treat this as a FAIL if the source command's output shows errors.
- **Multi-build-system blind spot**: if the project has multiple build systems (e.g., Go + Gradle,
  Rust + npm), verify EACH one produced results. A project with `go.mod` and `android/build.gradle.kts`
  must have Go test results AND Android test results. If only one build system reported results,
  the other likely failed silently.

## CI workflow change detection

Check if any files in `.github/workflows/` were modified in this phase's commits:
```bash
git diff --name-only HEAD~$(number of commits in this phase) -- .github/workflows/
```

If ANY workflow files were modified:

1. **Parse the modified workflow files** and extract every `run:` command from added or changed steps
2. **Run each command locally** in the project's dev environment. If a command references
   `./gradlew assembleDebug`, run it. If it references `nix build`, run it. If it references
   `jq '.passed' summary.json`, first run the test suite to produce summary.json, then run jq.
3. **For each `actions/upload-artifact` step**, check the `path:` value — after running the
   producing build command, verify the file exists at that path. If the step uploads
   `android/app/build/outputs/apk/debug/app-debug.apk`, that file MUST exist.
4. **For non-vacuous verification steps** (counting JUnit XML, parsing summary.json), run
   the test suite and confirm the verification logic would pass (files exist, counts > 0)
5. Report any failures as FAIL with the specific command and missing artifact

**Why**: If this phase only edited YAML files (no source code changes), the standard
build+test+lint sequence sees "nothing changed" and passes. But the YAML changes may
reference build commands (`./gradlew`, `nix build`) that have never been run or are broken.
This check catches that gap.

**IMPORTANT**: This is NOT report-only. If a referenced command fails, treat it as a
validation FAIL with the same severity as a test failure. The runner will spawn a fix agent
to diagnose and fix the issue (add missing dep, fix build config, correct artifact path),
then re-validate. Same fix-validate loop as test failures — 20-iteration cap.

## Rules

- Do NOT fix any code — just run commands and report
- Do NOT push, commit, or modify source files
- Do NOT read ROUTER.md or use the Skill tool
- Do NOT truncate command output — capture it fully so failures can be diagnosed
- Read `CLAUDE.md` for any project-specific commands
- Read `{learnings_file}` for known gotchas
"""


def build_ci_finalize_prompt(task_id: str, task_file: str, debug_dir: Path,
                             learnings_file: str) -> str:
    """Build prompt for the CI finalization sub-agent.

    Runs after CI passes: creates PR, marks task complete.
    """
    nix_note = ""
    if (Path.cwd() / "flake.nix").exists():
        nix_note = "**Environment**: This project uses Nix. Your PATH includes all devshell tools.\n\n"

    return f"""You are a CI finalization agent for task **{task_id}**.

{nix_note}CI has passed. Before finalizing, you MUST sanity-check the results.

## Step 0: Sanity-check CI results

Download the CI run summary and job details:
```bash
gh run list --branch "$(git branch --show-current)" --limit 1 --json databaseId,conclusion --jq '.[0]'
# then for each job:
gh run view <run_id> --json jobs --jq '.jobs[] | {{name, conclusion, status}}'
```

Then read `.github/workflows/ci.yml` to understand what each job SHOULD produce.

For every job that runs tests, verify the results are plausible:
- **Download the job logs**: `gh run view <run_id> --log` and search for test counts,
  "0 passed", "0 tests", "no such file", "not found", or empty output sections
- **Cross-reference test counts against source**: count the test files/functions on disk
  (e.g. `find . -name '*_test.go' | wc -l`, `find . -name '*Test.kt' | wc -l`) and compare
  with the number of tests the CI runner reported. If CI reports 0 tests but test files exist,
  or reports dramatically fewer tests than exist, something is broken.
- **Check for silent failures**: a job can exit 0 while its key step failed if the step output
  is piped (e.g. `cmd | tee`), if errors are swallowed by `|| true`, or if a `continue-on-error`
  masks the failure. Look at the actual step output, not just the job conclusion.
- **Check for missing artifacts**: if a test step should produce XML results, coverage reports,
  or binaries, verify they appear in the logs or artifact list.

**If any sanity check fails**: do NOT finalize. Instead:
1. Write a diagnosis to `{debug_dir}/sanity-check-fail.md` explaining what's wrong
2. Do NOT mark the task complete — leave `- [ ]` unchanged in `{task_file}`
3. Do NOT commit
4. Exit — the runner will re-schedule the task for fixing

**If all sanity checks pass**: proceed to observable output validation.

## Step 1: Observable output validation

After sanity checks pass, validate the **observable outputs** before finalizing.

### 1a. Badge validation (if README.md has badges)

Read `README.md` and extract every badge URL (both `img.shields.io` and GitHub Actions badge URLs).
For each badge:
- Fetch with `curl -sL <url>` and check HTTP status
- For shields.io SVGs: check the response body does NOT contain error text:
  `not found`, `not specified`, `invalid`, `no releases`, `inaccessible`
- For GitHub Actions badges (`/actions/workflows/.../badge.svg`): check the response is a valid SVG (not 404)

**If a badge is broken**:
- Workflow badge 404 → check if the workflow file exists on the default branch:
  `gh api repos/{{owner}}/{{repo}}/contents/.github/workflows/{{file}}?ref={{default_branch}}`
  If 404, the workflow needs to reach the default branch via PR merge.
- License badge "not specified" → check if LICENSE exists on default branch:
  `gh api repos/{{owner}}/{{repo}}/contents/LICENSE?ref={{default_branch}}`
- Release badge "no releases" → check `gh api repos/{{owner}}/{{repo}}/releases --jq 'length'`
  If 0, this is expected for a new project and will self-heal after first release.

Document broken badges and their causes in the finalization notes. If the cause is fixable (missing
file that should be in the PR), do NOT finalize — write a diagnosis and exit.

### 1b. Artifact validation

List artifacts from the CI run:
```bash
gh run view <run_id> --json artifacts --jq '.artifacts[].name'
```

Cross-reference against `actions/upload-artifact` steps in `.github/workflows/ci.yml`.
For each expected artifact not in the list, check if the upload step has `if:` conditions
that prevented it from running.

Download at least one artifact and verify it's non-empty:
```bash
gh run download <run_id> -n <artifact-name> -D /tmp/artifact-check/
ls -la /tmp/artifact-check/
```

### 1c. Default branch readiness (if PR is being created)

Before creating the PR, check what's on the default branch:
```bash
gh api repos/{{owner}}/{{repo}}/git/trees/{{default_branch}}?recursive=1 --jq '.tree[].path'
```

Verify the PR will bring:
- All workflow files (`.github/workflows/*.yml`)
- LICENSE file
- README.md
- Release config files (if release automation is configured)

For `workflow_run` triggers: verify each referenced workflow name matches a workflow
that will exist on the default branch after merge. GitHub uses the default branch's
version of the workflow file for `workflow_run` events.

### 1d. Acceptance scenario spot-check

Read the spec file (find it in `specs/*/spec.md`) and extract acceptance scenarios.
For any that are automatically verifiable (URL fetches, CLI commands, file checks, API calls),
execute them and verify PASS. Do NOT fix code at this point — if a scenario fails,
write the failure to `{debug_dir}/observable-validation-fail.md` and exit without finalizing.

**If all observable checks pass**: proceed to finalization below.

## Steps 2-6: Finalize

1. Read the task description in `{task_file}` for {task_id}
2. If the task says to create a PR: create it with `gh pr create`
3. If the task describes additional post-CI steps (verify release, merge, etc.), do those
4. Mark {task_id} as complete: change `- [ ]` to `- [x]` in `{task_file}`
5. Commit: `feat({task_id}): CI/CD validation complete`
6. Append a summary of the CI debug process AND observable validation results to `{learnings_file}`

## CI debug history

The full history of CI attempts is in `{debug_dir}/`. Reference it for the learnings entry.

## Rules

- Do NOT read ROUTER.md or use the Skill tool
- Do NOT re-push code — CI already passed on the current HEAD
"""


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
        self._blocked_answers: dict[str, str] = {}  # task_id -> user's answer from BLOCKED.md
        self._amendment_dir: Optional[Path] = None  # set per-feature to specs/<feature>/
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        self.timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session_id = uuid.uuid4().hex[:12]
        self._shutdown = threading.Event()
        self._draining = threading.Event()  # First Ctrl-C: finish running agents, don't spawn new ones
        self.agents: list[AgentSlot] = []
        self.agent_counter = self._find_max_agent_id()
        self._lock = threading.Lock()

        self.logger: Optional[HeadlessLogger] = None
        self.tui: Optional[TUI] = None

        if headless:
            self.logger = HeadlessLogger(self.log_dir / f"parallel-{self.timestamp}")
        else:
            pass  # TUI created per-feature

    def _find_max_agent_id(self) -> int:
        """Resume agent numbering from the highest existing ID in the logs dir."""
        max_id = 0
        try:
            for f in self.log_dir.iterdir():
                m = re.match(r"agent-(\d+)-", f.name)
                if m:
                    max_id = max(max_id, int(m.group(1)))
        except OSError:
            pass
        return max_id

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        if self.logger:
            self.logger.log(msg)
        elif self.tui:
            pass  # TUI handles display
        else:
            print(line, flush=True)

    def _write_event(self, event_type: str, spec_dir: str, **fields):
        """Append a structured event to {spec_dir}/run-log.jsonl."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "session": self.session_id,
            "event": event_type,
            **fields,
        }
        log_path = Path(spec_dir) / "run-log.jsonl"
        try:
            with open(log_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            pass  # Don't crash the runner over a log write failure

    def _cleanup_stale_run(self):
        """Kill any orphaned agents from a previous runner that crashed.

        Uses a pidfile to find the old runner's process group and kill it.
        """
        pidfile = self.log_dir / "runner.pid"
        if pidfile.exists():
            try:
                old_pid = int(pidfile.read_text().strip())
                if old_pid == os.getpid():
                    pass  # That's us (re-exec'd) — don't self-kill
                else:
                    # Check if the old process is still running.
                    os.kill(old_pid, 0)
                    # It's alive — kill its entire process group.
                    self.log(f"Killing stale runner (PID {old_pid}) from previous run")
                    try:
                        old_pgid = os.getpgid(old_pid)
                        my_pgid = os.getpgrp()
                        if old_pgid == my_pgid:
                            # PID recycled into our group — just kill it directly
                            os.kill(old_pid, signal.SIGTERM)
                            time.sleep(2)
                            os.kill(old_pid, signal.SIGKILL)
                        else:
                            os.killpg(old_pgid, signal.SIGTERM)
                            time.sleep(2)
                            os.killpg(old_pgid, signal.SIGKILL)
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
        self.log(f"Session {self.session_id} — prior failures from other sessions will be ignored")

        # Check for leftover BLOCKED.md — if the user edited it with an answer, consume and continue
        if self.blocked_file.exists():
            blocked_text = self.blocked_file.read_text()
            # Try auto-grant first (capability requests like [needs: gh])
            requested_caps = _parse_capability_request(blocked_text)
            blocked_task_id = _extract_blocked_task_id(blocked_text)
            if requested_caps:
                if blocked_task_id:
                    if not hasattr(self, '_granted_capabilities'):
                        self._granted_capabilities: dict[str, set[str]] = {}
                    self._granted_capabilities.setdefault(blocked_task_id, set()).update(requested_caps)
                    self.log(f"Auto-granted capabilities {requested_caps} for {blocked_task_id}")
                self.blocked_file.unlink()
            elif blocked_task_id:
                # User edited the file with their answer — consume it and retry the task
                self._blocked_answers[blocked_task_id] = blocked_text
                self.blocked_file.unlink()
                self.log(f"Consumed user answer from BLOCKED.md for {blocked_task_id}")
            else:
                # Can't determine which task this is for — ask the user
                print("=== BLOCKED ===")
                print(f"BLOCKED.md exists but no task ID (e.g. T075) was found in it:")
                print(blocked_text)
                print("\nEnsure BLOCKED.md contains a task ID, then re-run. The runner will clean up the file.")
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
            self._teardown_platform_runtimes()
            self._remove_pidfile()

        self._print_summary()

    def _handle_signal(self, sig, frame):
        import signal as _signal
        sig_name = _signal.Signals(sig).name if hasattr(_signal, 'Signals') else str(sig)
        if not self._draining.is_set():
            # First signal → drain: finish running agents, don't spawn new ones
            self._draining.set()
            self.log(f"Signal {sig_name} — draining: waiting for running agents to finish, no new tasks")
            return
        # Second Ctrl-C → hard shutdown
        self._shutdown.set()
        self._kill_all_agents()
        self._teardown_platform_runtimes()
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
        my_pgid = os.getpgrp()
        for agent in live:
            try:
                pgid = os.getpgid(agent.process.pid)
                if pgid == my_pgid:
                    # PID was recycled into our process group — don't self-signal.
                    # Just kill the individual process.
                    agent.process.terminate()
                else:
                    os.killpg(pgid, signal.SIGTERM)
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
                    pgid = os.getpgid(agent.process.pid)
                    if pgid == my_pgid:
                        agent.process.kill()
                    else:
                        os.killpg(pgid, signal.SIGKILL)
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

    def _teardown_platform_runtimes(self):
        """Kill any emulators/simulators/runtimes started by the platform manager."""
        if hasattr(self, '_platform_manager'):
            try:
                self._platform_manager.teardown_all(project_dir=Path.cwd())
            except Exception:
                pass

        # Belt-and-suspenders: kill any Android emulator even if the platform
        # manager didn't track it (e.g. agent spawned one inside its sandbox).
        try:
            result = subprocess.run(
                ["adb", "devices"], capture_output=True, timeout=5,
            )
            if b"emulator-" in result.stdout:
                self.log("Killing leftover Android emulator(s)")
                subprocess.run(
                    ["adb", "emu", "kill"], capture_output=True, timeout=30,
                )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    def _run_feature(self, spec_dir: str):
        self._current_spec_dir = spec_dir  # for _poll_agents attempt tracking
        self._amendment_dir = Path(spec_dir)
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
        # Track which phases need a fix agent after VR failure
        vr_fix_phases: set[str] = set()

        # Setup TUI for this feature
        if not self.headless:
            self.tui = TUI(phases, phase_deps, layout=self.layout, draining=self._draining)
            self.tui.start()

        self.log(f"=== Feature: {Path(spec_dir).name} ===")
        self.log(f"Remaining: {scheduler.remaining_count()} | Completed: {scheduler.completed_count()}")
        self._write_event("session_start", spec_dir,
                          feature=Path(spec_dir).name,
                          remaining=scheduler.remaining_count(),
                          completed=scheduler.completed_count())
        if validated_phases:
            self.log(f"Already validated: {', '.join(sorted(validated_phases))}")

        consecutive_noop = 0
        max_consecutive_noop = 20
        total_runs = 0

        # Track tasks that were already [x] before this run started,
        # so we don't re-verify them on every iteration.
        previously_complete: set[str] = set()
        for phase in phases:
            for t in phase.tasks:
                if t.status == TaskStatus.COMPLETE:
                    previously_complete.add(t.id)

        # Track flake.nix hash so we can re-exec if an agent modifies it
        flake_path = Path.cwd() / "flake.nix"
        def _flake_hash() -> str:
            try:
                return hashlib.sha256(flake_path.read_bytes()).hexdigest()
            except FileNotFoundError:
                return ""
        flake_hash_at_start = _flake_hash()

        while not self._shutdown.is_set() and total_runs < self.max_runs:
            # If an agent modified flake.nix, drain running agents and
            # re-exec inside the new nix develop shell so updated tools
            # are on PATH for subsequent agents.
            if flake_path.exists() and _flake_hash() != flake_hash_at_start:
                self.log("flake.nix changed — draining agents before re-exec into new nix develop shell")
                self._draining.set()
                self._drain_agents()
                self._draining.clear()
                if self.tui:
                    self.tui.stop()
                # Test that the new flake evaluates before committing to re-exec.
                nix_cmd = ["nix", "develop", "--command"]
                if os.environ.get("NIXPKGS_ALLOW_UNFREE") == "1":
                    nix_cmd = ["nix", "develop", "--impure", "--command"]
                probe = subprocess.run(
                    nix_cmd + ["true"],
                    capture_output=True, timeout=120,
                )
                if probe.returncode != 0 and b"unfree" in probe.stderr:
                    self.log("Flake contains unfree packages — retrying with --impure")
                    os.environ["NIXPKGS_ALLOW_UNFREE"] = "1"
                    nix_cmd = ["nix", "develop", "--impure", "--command"]
                    probe = subprocess.run(
                        nix_cmd + ["true"],
                        capture_output=True, timeout=120,
                    )
                if probe.returncode == 0:
                    self.log("Re-execing into new nix develop shell...")
                    os.execvp("nix", nix_cmd + [sys.executable, *sys.argv])
                    # execvp replaces the process — this line is never reached
                else:
                    self.log(
                        f"nix develop failed (exit {probe.returncode}) — "
                        f"continuing with current shell. stderr: {probe.stderr.decode()[:200]}"
                    )
                    flake_hash_at_start = _flake_hash()

            # Re-parse task file to pick up changes from agents
            phases, phase_deps = parse_task_file(task_file)

            # Safety net: if an agent completed successfully but didn't
            # mark the task [x], the runner marks it. Without this,
            # the task stays [ ] and gets re-spawned forever.
            marked_any = False
            if hasattr(self, '_agent_done_tasks'):
                for done_id in list(self._agent_done_tasks):
                    for phase in phases:
                        for t in phase.tasks:
                            if t.id == done_id and t.status != TaskStatus.COMPLETE:
                                self.log(f"Runner marking {t.id} [x] (agent completed but didn't mark)")
                                _mark_task_done(task_file, t.id)
                                marked_any = True
                    self._agent_done_tasks.discard(done_id)
                if marked_any:
                    phases, phase_deps = parse_task_file(task_file)

            # Accept task completions — verification happens at phase level (VR agents)
            for phase in phases:
                for t in phase.tasks:
                    if t.status == TaskStatus.COMPLETE and t.id not in previously_complete:
                        self.log(f"Task {t.id} marked complete by agent")
                        previously_complete.add(t.id)

            # Re-scan phase validation states (validation/review/re-validation lifecycle)
            phase_states = scan_phase_validation_states(spec_dir)

            # Reset failed runner verifications when a fix agent has since
            # completed.  A failed runner-verified.json is a dead end: the
            # review is still marked clean, so phase_needs_validate_review()
            # returns False and no VR agent spawns.  Deleting the runner
            # verified file + review files sends the phase back through VR.
            for phase in phases:
                slug = phase.slug
                state = phase_states.get(slug, PhaseValidationState())
                if not state.validated or state.runner_verified:
                    continue
                rv_file = Path(spec_dir) / "validate" / slug / "runner-verified.json"
                if not rv_file.exists():
                    continue
                try:
                    rv_data = json.loads(rv_file.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                if rv_data.get("passed", False):
                    continue  # Passed — nothing to reset

                # Runner verification failed. Check if any agent completed
                # for this phase AFTER the rv file was written (fix agent).
                rv_mtime = rv_file.stat().st_mtime
                fix_ran_since = False
                if hasattr(self, '_agent_done_tasks'):
                    # _agent_done_tasks tracks recently completed task IDs
                    for p in phases:
                        if p.slug == slug:
                            for t in p.tasks:
                                if t.status == TaskStatus.COMPLETE and t.id not in previously_complete:
                                    fix_ran_since = True
                                    break
                            break
                # Also check if any VR-fix agent completed since the rv file
                with self._lock:
                    for a in self.agents:
                        if a.task.phase == slug and a.task.id.startswith("VR-fix-") and a.status == "done":
                            fix_ran_since = True
                if not fix_ran_since:
                    # Check file mtime as fallback — any validation/review
                    # file newer than rv_file means work happened
                    phase_vdir = Path(spec_dir) / "validate" / slug
                    for f in phase_vdir.iterdir():
                        if f.name != "runner-verified.json" and f.stat().st_mtime > rv_mtime:
                            fix_ran_since = True
                            break
                if not fix_ran_since:
                    continue

                # Reset: delete runner-verified.json and review files so
                # phase_needs_validate_review() returns True again
                self.log(f"Resetting failed runner verification for {phase.name} — fix applied, re-validating")
                rv_file.unlink(missing_ok=True)
                phase_vdir = Path(spec_dir) / "validate" / slug
                for rf in phase_vdir.glob("review-*.md"):
                    rf.unlink(missing_ok=True)
                    self.log(f"  Deleted {rf.name} to trigger re-validation")

            # Re-scan after potential resets
            phase_states = scan_phase_validation_states(spec_dir)
            validated_phases = {s for s, st in phase_states.items() if st.complete}
            scheduler = Scheduler(phases, phase_deps, validated_phases, phase_states)

            # Auto-prune learnings for fully-validated phases with no pending dependents
            pruned = _prune_completed_learnings(
                str(learnings_file), phases, phase_deps, validated_phases
            )
            if pruned > 0:
                self.log(f"Pruned {pruned} learnings section(s) from fully-validated phases")

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
                        remaining = scheduler.remaining_count()
                        if remaining > 0:
                            self.log(f"Drain complete — all agents finished, {remaining} task(s) still pending")
                            pending_ids = [
                                t.id for p in phases for t in p.tasks
                                if t.status in (TaskStatus.PENDING, TaskStatus.REWORK)
                            ]
                            if pending_ids:
                                self.log(f"  Unfinished: {', '.join(pending_ids)}")
                        else:
                            self.log("Drain complete — all agents finished")
                        break
                self._poll_agents()
                time.sleep(1)
                continue

            # Check BLOCKED.md — auto-grant capability requests, pause for everything else
            if self.blocked_file.exists():
                blocked_text = self.blocked_file.read_text()
                requested_caps = _parse_capability_request(blocked_text)
                if requested_caps:
                    # Auto-grant: remove BLOCKED.md, record granted caps for the task
                    blocked_task_id = _extract_blocked_task_id(blocked_text)
                    self.blocked_file.unlink()
                    if blocked_task_id:
                        if not hasattr(self, '_granted_capabilities'):
                            self._granted_capabilities: dict[str, set[str]] = {}
                        self._granted_capabilities.setdefault(blocked_task_id, set()).update(requested_caps)
                        self.log(f"Auto-granted capabilities {requested_caps} for {blocked_task_id} — will retry with them")
                    else:
                        self.log(f"Capability request found but no task ID in BLOCKED.md — granting broadly")
                else:
                    self.log("BLOCKED — agent needs input")
                    if self.tui:
                        self.tui.stop()
                    print(f"\n=== BLOCKED ===\n{blocked_text}")
                    print("Edit BLOCKED.md with your answer, then re-run. The runner will clean up the file.")
                    sys.exit(2)

            # Check for AMENDMENT-*.md files — pause and prompt for human approval
            if self._amendment_dir:
                amendments = list(self._amendment_dir.glob("AMENDMENT-*.md"))
                if amendments:
                    amend_file = amendments[0]
                    amend_text = amend_file.read_text()
                    self.log(f"AMENDMENT found: {amend_file.name}")
                    if self.tui:
                        self.tui.stop()
                    print(f"\n=== SPEC AMENDMENT ===\n{amend_text}")
                    print("\nReview the amendment above. To approve:")
                    print("  1. Update spec.md with the amendment (append to ## Amendments section)")
                    print("  2. Update tasks.md — mark affected completed tasks with [!] for rework if needed")
                    print(f"  3. Delete {amend_file.name}")
                    print("  4. Re-run the runner")
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

            # ── Circuit breaker ────────────────────────────────────────
            # If recent attempts are all connection errors, pause instead
            # of burning through agents for nothing.
            breaker_wait = check_circuit_breaker(spec_dir)
            if breaker_wait and available_slots > 0:
                with self._lock:
                    if not self.agents:  # only pause when no agents running
                        self.log(f"Circuit breaker tripped — last 3 attempts were connection errors. Waiting {breaker_wait // 60}m...")
                        # Sleep in small increments so we can respond to shutdown
                        for _ in range(breaker_wait):
                            if self._shutdown.is_set():
                                break
                            time.sleep(1)
                        self.log("Circuit breaker cooldown complete, resuming")
                        continue  # re-enter main loop

            # Spawn new agents for ready tasks
            spawned = 0
            for task in ready:
                if available_slots <= 0:
                    break
                if task.id in running_ids:
                    continue

                # Check if task is deferred — only run when it's the sole agent
                if check_deferred(task.id):
                    with self._lock:
                        other_running = len([a for a in self.agents if a.task.id != task.id])
                    if other_running > 0:
                        continue  # skip until we're the only agent
                    else:
                        clear_deferred(task.id)
                        self.log(f"Running deferred task {task.id} (solo slot)")

                # ── CI loop tasks get a dedicated runner-managed cycle ──
                if "ci-loop" in task.capabilities:
                    # Guard against infinite respawn: if the CI loop thread
                    # keeps returning immediately (drain, error, etc.), don't
                    # keep re-launching it.
                    if not hasattr(self, '_ci_loop_spawns'):
                        self._ci_loop_spawns: dict[str, int] = {}
                    spawn_count = self._ci_loop_spawns.get(task.id, 0)
                    if spawn_count >= 3:
                        self.log(f"Task {task.id} CI loop spawned {spawn_count} times — giving up")
                        task.status = TaskStatus.FAILED
                        continue
                    self._ci_loop_spawns[task.id] = spawn_count + 1

                    self.log(f"Task {task.id} is a [ci-loop] task — running CI debug loop")
                    # Run in a thread so the main loop can continue managing other agents
                    ci_thread = threading.Thread(
                        target=self._run_ci_loop,
                        args=(task, spec_dir, task_file, str(learnings_file)),
                        daemon=True,
                        name=f"ci-loop-{task.id}",
                    )
                    ci_thread.start()
                    running_ids.add(task.id)
                    # Track as a virtual CI loop slot for TUI display
                    self.agent_counter += 1
                    slot = AgentSlot(
                        agent_id=self.agent_counter,
                        task=task,
                        start_time=time.time(),
                        status="running",
                        is_ci_loop=True,
                    )
                    with self._lock:
                        self.agents.append(slot)
                    # Store thread reference for cleanup
                    if not hasattr(self, '_ci_threads'):
                        self._ci_threads: dict[str, threading.Thread] = {}
                    self._ci_threads[task.id] = ci_thread
                    available_slots -= 1
                    spawned += 1
                    total_runs += 1
                    continue

                # ── E2E loop tasks get a dedicated runner-managed cycle ──
                if task.capabilities & _MCP_CAPABILITIES and "e2e-loop" in task.capabilities:
                    if not hasattr(self, '_e2e_loop_spawns'):
                        self._e2e_loop_spawns: dict[str, int] = {}
                    spawn_count = self._e2e_loop_spawns.get(task.id, 0)
                    if spawn_count >= 5:
                        self.log(f"Task {task.id} E2E loop spawned {spawn_count} times — giving up")
                        task.status = TaskStatus.FAILED
                        continue
                    self._e2e_loop_spawns[task.id] = spawn_count + 1

                    self.log(f"Task {task.id} is an [e2e-loop] task — running E2E explore-fix-verify loop")
                    e2e_thread = threading.Thread(
                        target=self._run_e2e_loop,
                        args=(task, spec_dir, task_file, str(learnings_file)),
                        daemon=True,
                        name=f"e2e-loop-{task.id}",
                    )
                    e2e_thread.start()
                    running_ids.add(task.id)
                    self.agent_counter += 1
                    slot = AgentSlot(
                        agent_id=self.agent_counter,
                        task=task,
                        start_time=time.time(),
                        status="running",
                        is_ci_loop=True,  # reuse TUI display logic
                    )
                    with self._lock:
                        self.agents.append(slot)
                    if not hasattr(self, '_e2e_threads'):
                        self._e2e_threads: dict[str, threading.Thread] = {}
                    self._e2e_threads[task.id] = e2e_thread
                    available_slots -= 1
                    spawned += 1
                    total_runs += 1
                    continue

                history = read_attempt_history(spec_dir, task.id, session_id=self.session_id)

                # Use lightweight retry prompt when code exists but agents
                # keep dying from connection errors
                if history and should_use_retry_prompt(history):
                    prompt = build_retry_prompt(
                        str(task_file), spec_dir, str(learnings_file),
                        task, history
                    )
                    self.log(f"Using lightweight retry prompt for {task.id} (code already written)")
                else:
                    prompt = build_prompt(
                        str(task_file), spec_dir, str(learnings_file),
                        str(constitution), reference_files, task,
                        attempt_history=history if history else None,
                        all_phases=phases,
                        phase_deps=phase_deps,
                        blocked_answer=self._blocked_answers.pop(task.id, None),
                    )

                self.agent_counter += 1
                agent_id = self.agent_counter

                log_path = self.log_dir / f"agent-{agent_id}-{task.id}-{self.timestamp}.jsonl"
                stderr_path = self.log_dir / f"agent-{agent_id}-{task.id}-{self.timestamp}.stderr"

                attempt_num = len(history) + 1 if history else 1
                att_str = f" (attempt #{attempt_num})" if attempt_num > 1 else ""
                self.log(f"Spawning Agent {agent_id} for task {task.id}{att_str}: {task.description[:60]}")
                self._write_event("task_spawn", spec_dir,
                                  task_id=task.id, agent_id=agent_id,
                                  attempt=attempt_num, phase=task.phase,
                                  description=task.description[:120])

                # Pass any capabilities granted via BLOCKED.md auto-retry
                extra_caps = None
                if hasattr(self, '_granted_capabilities'):
                    extra_caps = self._granted_capabilities.get(task.id)

                # Resolve MCP config paths for tasks with platform capabilities
                task_mcp_configs = None
                task_mcp_caps = task.capabilities & _MCP_CAPABILITIES
                if task_mcp_caps:
                    if not hasattr(self, '_platform_manager'):
                        self._platform_manager = PlatformManager(log_fn=self.log)
                    for cap in task_mcp_caps:
                        self._platform_manager.ensure_runtime(cap, Path.cwd())
                    task_mcp_configs = self._platform_manager.get_mcp_config_paths(task_mcp_caps)

                proc = spawn_agent(task, prompt, log_path, stderr_path,
                                   extra_capabilities=extra_caps,
                                   mcp_config_paths=task_mcp_configs)

                slot = AgentSlot(
                    agent_id=agent_id,
                    task=task,
                    process=proc,
                    pid=proc.pid,
                    start_time=time.time(),
                    log_file=log_path,
                    status="running",
                    attempt=attempt_num,
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
            # Stop respawning VR agents after this many consecutive watchdog
            # kills on the same phase. The deadlock is external to the agent
            # (toolchain bug, infinite-loop test); further retries waste tokens.
            MAX_VR_HANGS = 3
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

                # Stopgap: if this phase has hung and been killed >= MAX_VR_HANGS
                # times, stop respawning. The deadlock is unfixable from inside
                # the agent (likely a toolchain bug) and further retries just
                # burn tokens.
                vr_task_prefix = f"VR-{phase.slug}-"
                prior_hangs = _count_prior_hangs(self.log_dir, vr_task_prefix)
                if prior_hangs >= MAX_VR_HANGS:
                    fail_file = phase_vdir / f"{cycle}.md"
                    if not fail_file.exists():
                        fail_file.write_text(
                            f"# Phase {phase.slug} — Validation #{cycle}: FAIL (HANG CAP)\n\n"
                            f"**Date**: {datetime.now().isoformat()}\n"
                            f"**Assessment**: {prior_hangs} prior VR agents for this "
                            f"phase were killed by the watchdog for deadlocked "
                            f"background tasks. Not spawning further VR agents. "
                            f"Review `logs/agent-*-{vr_task_prefix}*.hang.md` to "
                            f"identify the hanging command and fix the underlying "
                            f"test/toolchain issue before re-running the runner.\n"
                        )
                    self.log(
                        f"VR hang cap ({MAX_VR_HANGS}) reached for {phase.name} — "
                        f"not spawning (see {fail_file})"
                    )
                    continue

                prompt = build_validate_review_prompt(
                    spec_dir, str(task_file), phase, str(learnings_file),
                    str(self.skills_dir), review_cycle=cycle
                )

                # Prepend prior hang diagnoses so this retry knows exactly what
                # not to run. The VR prompt body also tells agents to check
                # logs/*.hang.md, but an explicit prepend is load-bearing — the
                # file-read instruction alone is unreliable.
                diag_files = _find_prior_hang_diagnoses(
                    self.log_dir, vr_task_prefix, limit=2
                )
                diag_section = _format_hang_diagnoses_for_prompt(diag_files)
                if diag_section:
                    prompt = diag_section + prompt
                    self.log(
                        f"VR cycle {cycle} for {phase.name}: prepending "
                        f"{len(diag_files)} prior hang diagnosis file(s)"
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
                self._write_event("vr_spawn", spec_dir,
                                  phase=phase.slug, agent_id=agent_id,
                                  cycle=cycle)

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

            # Also clean up vr_fix_phases: remove phases whose fix agent finished
            with self._lock:
                running_fix_slugs = {
                    a.task.phase for a in self.agents
                    if a.task.id.startswith("VR-fix-")
                }
            vr_fix_phases &= running_fix_slugs

            # ── Dispatch fix agents for VR failures ───────────────────
            # When a VR agent finished with FAIL and no fix agent is
            # running, spawn one to address the failures.
            MAX_VR_FIX_ATTEMPTS = 5
            for phase in phases:
                slug = phase.slug
                if slug in vr_phases or slug in vr_fix_phases:
                    continue  # VR or fix still running
                if not scheduler.phase_tasks_complete(slug):
                    continue  # Tasks not done yet

                state = phase_states.get(slug, PhaseValidationState())
                if state.complete or slug in validated_phases:
                    continue  # Already fully validated

                # Check if latest validation file is a FAIL
                phase_vdir = Path(spec_dir) / "validate" / slug
                if not phase_vdir.is_dir():
                    continue
                validation_files = sorted(
                    f for f in phase_vdir.glob("*.md")
                    if not f.name.startswith("review-")
                )
                if not validation_files:
                    continue  # No validation yet — VR will be spawned

                latest = validation_files[-1]
                try:
                    first_line = latest.read_text().splitlines()[0]
                except (OSError, IndexError):
                    continue
                if "FAIL" not in first_line.upper():
                    continue  # Latest validation passed — no fix needed

                # Guard against infinite fix loops
                fix_attempt = len(validation_files)
                if fix_attempt > MAX_VR_FIX_ATTEMPTS:
                    self.log(f"VR fix cap ({MAX_VR_FIX_ATTEMPTS}) reached for {phase.name} — skipping fix")
                    continue

                if available_slots <= 0:
                    break

                # Build and spawn a fix agent
                prompt = build_vr_fix_prompt(
                    spec_dir, str(task_file), str(learnings_file),
                    phase, latest,
                )

                fix_task_id = f"VR-fix-{slug}-{fix_attempt}"
                fix_task = Task(
                    id=fix_task_id,
                    description=f"Fix VR failure #{fix_attempt}: {phase.name}",
                    phase=slug,
                    parallel=False,
                    status=TaskStatus.RUNNING,
                    line_num=0,
                )

                self.agent_counter += 1
                agent_id = self.agent_counter

                log_path = self.log_dir / f"agent-{agent_id}-{fix_task_id}-{self.timestamp}.jsonl"
                stderr_path = self.log_dir / f"agent-{agent_id}-{fix_task_id}-{self.timestamp}.stderr"

                self.log(f"Spawning VR fix Agent {agent_id} (attempt {fix_attempt}) for {phase.name}")
                self._write_event("vr_fix_spawn", spec_dir,
                                  phase=slug, agent_id=agent_id,
                                  attempt=fix_attempt,
                                  failure_file=str(latest))

                proc = spawn_agent(fix_task, prompt, log_path, stderr_path)

                slot = AgentSlot(
                    agent_id=agent_id,
                    task=fix_task,
                    process=proc,
                    pid=proc.pid,
                    start_time=time.time(),
                    log_file=log_path,
                    status="running",
                )

                with self._lock:
                    self.agents.append(slot)

                vr_fix_phases.add(slug)
                available_slots -= 1
                spawned += 1
                total_runs += 1

            # ── Runner-side independent verification ──────────────────
            # After VR agents finish and a phase has validated + review_clean,
            # the runner independently re-runs test commands before accepting.
            # This is deterministic — no LLM involved.
            runner_verified_any = False
            for phase in phases:
                slug = phase.slug
                state = phase_states.get(slug, PhaseValidationState())
                if not (state.validated and state.review_clean):
                    continue  # Not ready for runner verification
                if state.runner_verified:
                    continue  # Already verified
                if slug in vr_phases:
                    continue  # VR still running

                phase_vdir = Path(spec_dir) / "validate" / slug
                rv_file = phase_vdir / "runner-verified.json"
                if rv_file.exists():
                    # If verification previously passed, skip.
                    # If it failed, check if any agent has since completed
                    # for this phase (fix agent, VR agent, etc.) by comparing
                    # file mtimes. If newer work exists, retry verification.
                    try:
                        rv_data = json.loads(rv_file.read_text())
                        if rv_data.get("passed", False):
                            continue  # Already passed
                        # Failed — check if anything changed since the failure
                        rv_mtime = rv_file.stat().st_mtime
                        # Check for newer validation/review files OR newer
                        # source code changes (git tracks this)
                        any_newer = False
                        for f in phase_vdir.iterdir():
                            if f.name != "runner-verified.json" and f.stat().st_mtime > rv_mtime:
                                any_newer = True
                                break
                        if not any_newer:
                            continue  # Nothing changed since failure
                        self.log(f"Retrying runner verification for {phase.name} (prior attempt failed, newer files found)")
                        rv_file.unlink()
                    except (json.JSONDecodeError, OSError):
                        continue

                try:
                    self.log(f"Runner verification for phase {phase.name}...")

                    # Discover test commands from CLAUDE.md or Makefile
                    test_cmds = _discover_test_commands()
                    if not test_cmds:
                        self.log(f"  No test commands discovered — accepting VR result")
                        rv_file.write_text(json.dumps({
                            "passed": True,
                            "reason": "no test commands discovered",
                            "commands": [],
                        }, indent=2))
                        runner_verified_any = True
                        continue

                    all_passed = True
                    results = []
                    for cmd, label in test_cmds:
                        self.log(f"  Running: {label}")
                        try:
                            result = subprocess.run(
                                cmd, shell=True, capture_output=True, text=True,
                                timeout=600,
                            )
                            passed = result.returncode == 0
                            results.append({
                                "command": cmd, "label": label,
                                "exit_code": result.returncode,
                                "passed": passed,
                            })
                            if not passed:
                                self.log(f"  FAILED (exit {result.returncode}): {label}")
                                self.log(f"  stderr: {result.stderr[:300]}")
                                all_passed = False
                            else:
                                self.log(f"  PASSED: {label}")
                        except subprocess.TimeoutExpired:
                            results.append({
                                "command": cmd, "label": label,
                                "exit_code": -1, "passed": False,
                                "error": "timeout after 600s",
                            })
                            self.log(f"  TIMEOUT: {label}")
                            all_passed = False

                    rv_file.write_text(json.dumps({
                        "passed": all_passed,
                        "reason": "all commands passed" if all_passed else "some commands failed",
                        "commands": results,
                    }, indent=2))
                    runner_verified_any = True

                    if all_passed:
                        self.log(f"Runner verification PASSED for {phase.name}")
                    else:
                        self.log(f"Runner verification FAILED for {phase.name} — phase NOT complete")
                    self._write_event("runner_verify", spec_dir,
                                      phase=slug, passed=all_passed,
                                      commands=[r["label"] for r in results],
                                      failed=[r["label"] for r in results if not r["passed"]])
                except Exception as exc:
                    self.log(f"Runner verification CRASHED for {phase.name}: {exc}")
                    rv_file.write_text(json.dumps({
                        "passed": False,
                        "reason": f"runner verification crashed: {exc}",
                        "commands": [],
                    }, indent=2))
                    runner_verified_any = True

            # Update TUI
            if self.tui:
                with self._lock:
                    self.tui.update_agents(list(self.agents))
            if self.logger:
                with self._lock:
                    self.logger.write_status(phases, phase_deps, list(self.agents))

            # If nothing is running and nothing was spawned, we might be stuck.
            # Runner verification counts as progress — it writes runner-verified.json
            # which unlocks dependent phases on the next iteration.
            with self._lock:
                nothing_happening = len(self.agents) == 0 and spawned == 0 and not runner_verified_any

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
                        and any(t.status in (TaskStatus.PENDING, TaskStatus.REWORK) for t in p.tasks)
                    ]
                    if unmet:
                        self.log(f"  Blocked by unmet deps: {', '.join(unmet)}")
                    break
                self.log(f"No tasks ready ({consecutive_noop}/{max_consecutive_noop} before exit). Waiting...")
                self._poll_agents()
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

    def _check_agent_hang(self, agent) -> Optional[str]:
        """Return a reason string if the agent should be killed, else None.

        Three independent signals:
          1. wall-clock exceeded AGENT_HARD_TIMEOUT_S
          2. JSONL log idle for longer than the task's idle budget
          3. background-bash deadlock: log stale AND the agent's most recent
             run_in_background Bash command has a process subtree with 0 CPU
             ticks accumulated over AGENT_BG_DEADLOCK_S

        When killing, this method also writes a hang-diagnosis file that the
        next attempt's prompt may reference.
        """
        now = time.time()
        wall_s = now - (agent.start_time or now)
        if wall_s > AGENT_HARD_TIMEOUT_S:
            return self._finalize_hang(agent, f"wall-clock {int(wall_s)}s exceeded {AGENT_HARD_TIMEOUT_S}s")

        try:
            log_mtime = agent.log_file.stat().st_mtime
        except OSError:
            return None  # log not yet flushed; wait
        idle_s = now - log_mtime

        budget = _task_idle_budget_s(agent.task)
        if idle_s > budget:
            return self._finalize_hang(agent, f"log idle {int(idle_s)}s > budget {budget}s")

        # Background-bash deadlock detection. Only probes when the log has been
        # quiet for at least half the budget — avoids noisy ps/pgrep calls on
        # healthy agents.
        if idle_s < 60 or idle_s < AGENT_BG_DEADLOCK_S // 2:
            return None

        if not hasattr(self, "_hang_probes"):
            self._hang_probes: dict[int, dict] = {}
        probe = self._hang_probes.get(agent.agent_id)

        bg_info = _read_last_bash_bg_task(agent.log_file)
        if not bg_info:
            # No background task outstanding; idle budget alone governs.
            self._hang_probes.pop(agent.agent_id, None)
            return None

        # Identify the subtree running this bg command.
        agent_pid = agent.pid or (agent.process.pid if agent.process else 0)
        pids = _find_bg_bash_pids(agent_pid, bg_info.get("command", ""))
        if not pids:
            # Background task is recorded in log but process is gone (already
            # finished) — the agent should pick up the result shortly. Skip.
            self._hang_probes.pop(agent.agent_id, None)
            return None

        cpu_ticks = _cumulative_cpu_ticks(pids)
        if probe is None or probe.get("tool_use_id") != bg_info.get("tool_use_id"):
            # First time we see this bg task — record baseline and wait.
            self._hang_probes[agent.agent_id] = {
                "tool_use_id": bg_info.get("tool_use_id"),
                "ticks": cpu_ticks,
                "first_seen": now,
                "pids": pids,
                "bg_info": bg_info,
            }
            return None

        # Same bg task as last probe: check if CPU advanced.
        if cpu_ticks > probe["ticks"]:
            # Making progress (CPU time accumulating). Refresh baseline.
            probe["ticks"] = cpu_ticks
            probe["first_seen"] = now
            probe["pids"] = pids
            return None

        stuck_s = now - probe["first_seen"]
        if stuck_s > AGENT_BG_DEADLOCK_S:
            return self._finalize_hang(
                agent,
                f"background bash '{bg_info.get('description') or bg_info.get('command', '')[:60]}' "
                f"had 0 CPU for {int(stuck_s)}s (pids={pids[:6]})",
                bg_info=bg_info,
                bg_pids=pids,
            )
        return None

    def _finalize_hang(self, agent, reason: str,
                       *, bg_info: Optional[dict] = None,
                       bg_pids: Optional[list] = None) -> str:
        """Emit diagnostic artifacts for a hanging agent, return the reason."""
        agent_pid = agent.pid or (agent.process.pid if agent.process else None)
        try:
            _write_hang_diagnosis(
                self.log_dir, agent.agent_id, agent.task.id, self.timestamp,
                reason=reason, log_path=agent.log_file,
                agent_pid=agent_pid,
                bg_info=bg_info, bg_pids=bg_pids or [],
            )
        except Exception as e:
            self.log(f"hang diagnosis write failed: {e}")
        spec_dir = getattr(self, "_current_spec_dir", "")
        if spec_dir:
            try:
                self._write_event(
                    "agent_hang_kill", spec_dir,
                    task_id=agent.task.id, agent_id=agent.agent_id,
                    reason=reason,
                )
            except Exception:
                pass
        # Kill the background bash subtree too, so flutter_tester etc. go with
        # the agent and don't linger as zombies for the next attempt.
        for pid in (bg_pids or []):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        self._hang_probes.pop(agent.agent_id, None)
        return reason

    def _poll_agents(self):
        """Poll running agents, read output, detect completion."""
        # Track file read positions
        if not hasattr(self, '_read_positions'):
            self._read_positions = {}

        while not self._shutdown.is_set():
            # Check for completed CI loop threads (must be inside the
            # while loop so we detect threads that finish while we're polling)
            if hasattr(self, '_ci_threads'):
                for task_id, thread in list(self._ci_threads.items()):
                    if not thread.is_alive():
                        self.log(f"CI loop thread for {task_id} completed")
                        del self._ci_threads[task_id]
                        # Remove the virtual agent slot
                        with self._lock:
                            self.agents = [a for a in self.agents if a.task.id != task_id]

            # Check for completed E2E loop threads
            if hasattr(self, '_e2e_threads'):
                for task_id, thread in list(self._e2e_threads.items()):
                    if not thread.is_alive():
                        self.log(f"E2E loop thread for {task_id} completed")
                        del self._e2e_threads[task_id]
                        with self._lock:
                            self.agents = [a for a in self.agents if a.task.id != task_id]

            with self._lock:
                if not self.agents:
                    break

            finished = []
            with self._lock:
                agents_snapshot = list(self.agents)

            for agent in agents_snapshot:
                if agent.log_file:
                    pos = self._read_positions.get(agent.agent_id, 0)
                    new_lines, new_pos, exit_code, (in_tok, out_tok) = read_stream_output(agent.log_file, pos)
                    self._read_positions[agent.agent_id] = new_pos

                    if new_lines:
                        agent.output_lines.extend(new_lines)
                        # Keep only last 200 lines
                        if len(agent.output_lines) > 200:
                            agent.output_lines = agent.output_lines[-200:]

                    # Update token counts (latest usage from stream replaces prior)
                    if in_tok > 0:
                        agent.input_tokens = in_tok
                    if out_tok > 0:
                        agent.output_tokens = out_tok

                    if exit_code is not None:
                        agent.exit_code = exit_code

                # Watchdog: kill agents that are idle or deadlocked.
                # Only probe while the process is still alive — the completion
                # branch below handles normal exits.
                if (agent.process
                        and agent.process.poll() is None
                        and agent.log_file
                        and not agent.is_ci_loop):
                    killed_reason = self._check_agent_hang(agent)
                    if killed_reason:
                        self.log(
                            f"Agent {agent.agent_id} ({agent.task.id}) "
                            f"killed by watchdog: {killed_reason}"
                        )
                        try:
                            agent.process.kill()
                        except OSError:
                            pass
                        # Let the next iteration observe process exit and the
                        # normal completion path handle status/recording.

                # Check process status
                if agent.process and agent.process.poll() is not None:
                    rc = agent.process.returncode
                    stderr_path = self.log_dir / f"agent-{agent.agent_id}-{agent.task.id}-{self.timestamp}.stderr"

                    if rc == 0:
                        # Check if agent wrote a DEFER file instead of completing
                        if check_deferred(agent.task.id):
                            agent.status = "deferred"
                            self.log(f"Agent {agent.agent_id} ({agent.task.id}) deferred — will retry when solo")
                        else:
                            agent.status = "done"
                            self.log(f"Agent {agent.agent_id} ({agent.task.id}) completed successfully")
                            # Track for safety-net checkbox marking
                            if not agent.task.id.startswith(("VR-", "verify-")):
                                if not hasattr(self, '_agent_done_tasks'):
                                    self._agent_done_tasks: set[str] = set()
                                self._agent_done_tasks.add(agent.task.id)
                    elif (_rl := check_rate_limited(stderr_path, agent.log_file)):
                        agent.status = "rate_limited"
                        agent._resets_at = _rl
                        self.log(f"Agent {agent.agent_id} ({agent.task.id}) rate limited — will retry")
                    elif agent.log_file and check_auth_error(agent.log_file):
                        agent.status = "auth_error"
                        auth_err = check_auth_error(agent.log_file)
                        self.log(f"Agent {agent.agent_id} ({agent.task.id}) auth error (permanent): {auth_err[:80]}")
                    elif agent.log_file and check_connection_error(agent.log_file):
                        agent.status = "connection_error"
                        conn_err = check_connection_error(agent.log_file)
                        self.log(f"Agent {agent.agent_id} ({agent.task.id}) connection error: {conn_err[:60]}")
                    else:
                        agent.status = "failed"
                        self.log(f"Agent {agent.agent_id} ({agent.task.id}) failed (exit {rc})")

                    # Write attempt record for non-VR tasks
                    spec_dir = getattr(self, '_current_spec_dir', '')
                    if spec_dir and not agent.task.id.startswith("VR-"):
                        duration_s = int(time.time() - agent.start_time)
                        summary = extract_attempt_summary(agent.log_file) if agent.log_file else {}
                        write_attempt_record(spec_dir, agent.task.id, agent.agent_id, duration_s, summary,
                                             session_id=self.session_id)

                    # Structured event log
                    _sd = getattr(self, '_current_spec_dir', '')
                    if _sd:
                        evt_type = "vr_complete" if agent.task.id.startswith("VR-") else "task_complete"
                        # Extract detailed usage breakdown from the agent's log.
                        # This gives us cache read/create separately + observed model id.
                        breakdown = extract_usage_breakdown(agent.log_file) if agent.log_file else {}
                        observed_model = breakdown.get("model", "") or agent.model
                        self._write_event(evt_type, _sd,
                                          task_id=agent.task.id,
                                          agent_id=agent.agent_id,
                                          status=agent.status,
                                          exit_code=rc,
                                          duration_s=int(time.time() - agent.start_time),
                                          input_tokens=agent.input_tokens,
                                          output_tokens=agent.output_tokens,
                                          model=observed_model,
                                          input_tokens_fresh=breakdown.get("input_tokens_fresh", 0),
                                          input_tokens_cache_read=breakdown.get("input_tokens_cache_read", 0),
                                          input_tokens_cache_create=breakdown.get("input_tokens_cache_create", 0))

                    finished.append(agent)

            # Remove finished agents
            if finished:
                with self._lock:
                    self.agents = [a for a in self.agents if a not in finished]

                # Handle retryable agents
                for agent in finished:
                    if agent.status == "auth_error":
                        # Auth errors are permanent — stop the entire run
                        agent.task.status = TaskStatus.FAILED
                        self.log(f"FATAL: Auth error on {agent.task.id} — stopping all tasks. Re-authenticate and re-run.")
                        self._shutdown.set()
                    elif agent.status == "rate_limited":
                        resets_at = getattr(agent, '_resets_at', None)
                        if resets_at and resets_at > 1.0:
                            wait_secs = max(0, resets_at - time.time()) + 10  # 10s buffer
                            reset_time = datetime.fromtimestamp(resets_at).strftime("%H:%M:%S")
                            self.log(f"Rate limited on {agent.task.id}. Waiting until {reset_time} ({int(wait_secs)}s)...")
                            time.sleep(wait_secs)
                        else:
                            self.log(f"Rate limited on {agent.task.id}. Waiting 60s before retry...")
                            time.sleep(60)
                        # Task stays PENDING, will be picked up next iteration
                    elif agent.status == "connection_error":
                        # Task stays PENDING — attempt history will guide the next agent
                        self.log(f"Connection error on {agent.task.id} — will retry with attempt history")
                    elif agent.status == "deferred":
                        # Task stays PENDING — defer check in spawn loop will hold it
                        pass

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

    def __run_ci_loop_inner(self, task: Task, spec_dir: str, task_file: Path,
                            learnings_file: str):
        """Inner CI debug loop — called by _run_ci_loop which catches auth errors.

        Uses separate sub-agents for diagnosis and fixing, with the runner
        polling CI in the main thread. All artifacts written to ci-debug/<task_id>/.

        This method blocks until CI passes or the attempt cap is hit.
        """
        debug_dir = _ci_debug_dir(task.id)
        ci_log_path = debug_dir / "ci-loop.log"

        def ci_log(msg: str):
            """Log to both the runner and the CI loop's own log file."""
            ts = datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] {msg}"
            # Write to ci-loop.log for file-based visibility
            with open(ci_log_path, "a") as f:
                f.write(line + "\n")
            # Update the virtual agent slot's output_lines for TUI display
            with self._lock:
                for agent in self.agents:
                    if agent.task.id == task.id:
                        agent.output_lines.append(line)
                        if len(agent.output_lines) > 200:
                            agent.output_lines = agent.output_lines[-200:]
                        break
            # Also log to runner (works in headless mode)
            self.log(msg)

        def _wait_for_subagent(sub_task: Task, prompt: str, label: str,
                               caps: set[str] | None = None) -> int:
            """Spawn a sub-agent, track it in the TUI, and wait for completion.

            Returns the process exit code.
            """
            self.agent_counter += 1
            aid = self.agent_counter
            log_p = self.log_dir / f"agent-{aid}-{sub_task.id}-{self.timestamp}.jsonl"
            stderr_p = self.log_dir / f"agent-{aid}-{sub_task.id}-{self.timestamp}.stderr"
            proc = spawn_agent(sub_task, prompt, log_p, stderr_p,
                               extra_capabilities=caps)

            # Create a visible agent slot so TUI shows the sub-agent
            slot = AgentSlot(
                agent_id=aid, task=sub_task, process=proc,
                pid=proc.pid, start_time=time.time(),
                log_file=log_p, status="running",
            )
            with self._lock:
                self.agents.append(slot)

            # Track active sub-agent on the parent CI loop slot
            with self._lock:
                for a in self.agents:
                    if a.task.id == task.id and a.is_ci_loop:
                        a.active_sub_agent_id = aid
                        break

            ci_log(f"Spawned {label} (Agent {aid}, pid {proc.pid})")
            # Watchdog: poll every 60s, kill if the JSONL log goes idle.
            timeout_killed = False
            kill_reason = ""
            agent_start = time.time()
            while proc.poll() is None:
                time.sleep(60)
                now = time.time()
                try:
                    last_activity = log_p.stat().st_mtime
                except OSError:
                    last_activity = agent_start
                idle_s = now - last_activity
                wall_s = now - agent_start
                if idle_s > CI_AGENT_IDLE_TIMEOUT_S:
                    kill_reason = (
                        f"idle for {int(idle_s)}s (no log output) — killing"
                    )
                elif wall_s > CI_AGENT_HARD_TIMEOUT_S:
                    kill_reason = (
                        f"exceeded {CI_AGENT_HARD_TIMEOUT_S}s hard wall-clock limit — killing"
                    )
                if kill_reason:
                    ci_log(
                        f"{label} (Agent {aid}, pid {proc.pid}) {kill_reason}"
                    )
                    proc.kill()
                    proc.wait()
                    timeout_killed = True
                    break
            if timeout_killed:
                sub_status = "timeout"
            else:
                sub_status = "done" if proc.returncode == 0 else "failed"
            slot.status = sub_status
            sub_elapsed = int(time.time() - slot.start_time)

            # Read final token counts from sub-agent log
            sub_in_tok, sub_out_tok = 0, 0
            if log_p and log_p.exists():
                _, _, _, (sub_in_tok, sub_out_tok) = read_stream_output(log_p, 0)

            # Record sub-agent in parent's history and update aggregate totals
            record = SubAgentRecord(
                agent_id=aid, label=sub_task.id,
                input_tokens=sub_in_tok, output_tokens=sub_out_tok,
                elapsed_s=sub_elapsed, status=sub_status,
            )
            with self._lock:
                for a in self.agents:
                    if a.task.id == task.id and a.is_ci_loop:
                        a.sub_agent_history.append(record)
                        a.input_tokens += sub_in_tok
                        a.output_tokens += sub_out_tok
                        a.active_sub_agent_id = None
                        break
                self.agents = [a for a in self.agents if a.agent_id != aid]

            ci_log(f"{label} completed (exit {proc.returncode}, {(sub_in_tok + sub_out_tok) // 1000}k tok)")

            # Detect auth failures — abort early instead of looping uselessly
            if proc.returncode != 0:
                auth_err = check_auth_error(log_p)
                if auth_err:
                    raise AgentAuthError(
                        f"Sub-agent authentication failed (401). "
                        f"Claude Code session may have expired — "
                        f"re-authenticate and restart."
                    )

            return proc.returncode

        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()

        # Write initial state file for resumability
        state_file = debug_dir / "state.json"
        state = {"task_id": task.id, "branch": branch, "attempts": []}
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
            except (json.JSONDecodeError, KeyError):
                pass

        # Only count attempts from the current session for retry/stuck decisions
        session_attempts = [
            a for a in state["attempts"]
            if a.get("session_id") == self.session_id
        ]
        start_attempt = len(session_attempts) + 1
        # Track cancelled run IDs so the poller skips them instead of re-finding them
        skip_run_ids: set[int] = set()
        ci_log(f"Starting CI loop for {task.id} on branch {branch} (attempt {start_attempt})")

        for attempt in range(start_attempt, CI_LOOP_MAX_ATTEMPTS + 1):
            if self._shutdown.is_set():
                ci_log(f"CI loop interrupted by shutdown")
                return
            if self._draining.is_set():
                ci_log(f"CI loop stopping — drain requested (will resume on next run, attempt {attempt})")
                return

            attempt_record = {"attempt": attempt, "started": datetime.now().isoformat(), "session_id": self.session_id}

            # ── Step 1: Local validation BEFORE pushing ──
            # Always validate locally first — even on the first attempt. The task
            # agent may have left broken code. Each wasted CI cycle costs 10-30 min.
            if attempt == start_attempt:
                ci_log(f"Attempt {attempt}: running local validation before first push")
                prior_validate_output = ""
                local_passed = False

                for local_iter in range(1, CI_LOCAL_MAX_ITERATIONS + 1):
                    if self._shutdown.is_set() or self._draining.is_set():
                        ci_log(f"CI loop stopping during initial validation — drain/shutdown")
                        attempt_record["status"] = "interrupted_during_local_fix"
                        state["attempts"].append(attempt_record)
                        state_file.write_text(json.dumps(state, indent=2))
                        return

                    # Validate
                    ci_log(f"Attempt {attempt}, initial validation {local_iter}/{CI_LOCAL_MAX_ITERATIONS}")
                    validate_prompt = build_ci_local_validate_prompt(
                        task.id, attempt, local_iter, debug_dir, learnings_file,
                        prior_output=prior_validate_output,
                    )
                    validate_task = Task(
                        id=f"{task.id}-init-validate-{local_iter}",
                        description=f"Initial validation #{local_iter}",
                        phase=task.phase, parallel=False,
                        status=TaskStatus.RUNNING, line_num=0,
                    )
                    _wait_for_subagent(validate_task, validate_prompt,
                                       f"Initial validation (iter {local_iter})")

                    validate_file = debug_dir / f"attempt-{attempt}-local-{local_iter}.md"
                    if validate_file.exists():
                        content = validate_file.read_text()
                        prior_validate_output = content
                        if "## Result: PASS" in content:
                            ci_log(f"Initial validation PASSED on iteration {local_iter}")
                            local_passed = True
                            break
                        else:
                            ci_log(f"Initial validation FAILED on iteration {local_iter} — spawning fix agent")
                    else:
                        ci_log(f"Validation agent didn't write result — treating as failure")
                        prior_validate_output = "(no validation output)"

                    if not local_passed and local_iter < CI_LOCAL_MAX_ITERATIONS:
                        # Spawn fix agent to address validation failures
                        fix_prompt = build_ci_fix_prompt(
                            task.id, attempt, debug_dir, str(task_file), learnings_file,
                        )
                        fix_task = Task(
                            id=f"{task.id}-init-fix-{local_iter}",
                            description=f"Fix initial validation failure #{local_iter}",
                            phase=task.phase, parallel=False,
                            status=TaskStatus.RUNNING, line_num=0,
                            capabilities=task.capabilities,
                        )
                        _wait_for_subagent(fix_task, fix_prompt,
                                           f"Initial fix agent (iter {local_iter})",
                                           caps=task.capabilities)

                if not local_passed:
                    ci_log(f"Initial validation failed after {CI_LOCAL_MAX_ITERATIONS} iterations — pushing anyway")

                ci_log(f"Attempt {attempt}: pushing to {branch}")
                try:
                    push_ok = _gh_push(branch, ci_log)
                    if not push_ok:
                        attempt_record["status"] = "push_failed"
                        state["attempts"].append(attempt_record)
                        state_file.write_text(json.dumps(state, indent=2))
                        continue
                except subprocess.TimeoutExpired:
                    ci_log("Push timed out")
                    continue

            # ── Step 2: Poll CI (no agent context burned) ──
            # Combine shutdown + draining into a single stop event for the poller
            stop_event = threading.Event()
            def _watch_stop():
                while not stop_event.is_set():
                    if self._shutdown.is_set() or self._draining.is_set():
                        stop_event.set()
                        return
                    time.sleep(1)
            watcher = threading.Thread(target=_watch_stop, daemon=True)
            watcher.start()

            ci_log(f"Attempt {attempt}: polling CI on {branch}...")
            ci_result = _poll_ci_run(branch, stop_event=stop_event, skip_run_ids=skip_run_ids)
            stop_event.set()  # stop the watcher thread
            attempt_record["ci_result"] = ci_result

            ci_result_file = debug_dir / f"attempt-{attempt}-ci-result.json"
            ci_result_file.write_text(json.dumps(ci_result, indent=2))

            if ci_result["status"] == "interrupted":
                ci_log(f"CI polling interrupted by drain/shutdown")
                attempt_record["status"] = "interrupted"
                state["attempts"].append(attempt_record)
                state_file.write_text(json.dumps(state, indent=2))
                return

            if ci_result["status"] == "pass":
                ci_log(f"CI passed on attempt {attempt}!")
                attempt_record["status"] = "pass"
                state["attempts"].append(attempt_record)
                state_file.write_text(json.dumps(state, indent=2))

                # ── Finalize: sanity-check CI results, then create PR + mark complete ──
                prompt = build_ci_finalize_prompt(
                    task.id, str(task_file), debug_dir, learnings_file
                )
                finalize_task = Task(
                    id=f"{task.id}-finalize",
                    description=f"Finalize CI task {task.id}",
                    phase=task.phase, parallel=False,
                    status=TaskStatus.RUNNING, line_num=0,
                    capabilities=task.capabilities,
                )
                _wait_for_subagent(finalize_task, prompt, "Finalize agent",
                                   caps=task.capabilities)

                # Check if sanity-check failed — finalize agent writes this file
                # instead of marking the task complete when CI results look wrong
                sanity_fail = debug_dir / "sanity-check-fail.md"
                if sanity_fail.exists():
                    ci_log(f"Sanity check failed — CI passed but results are suspicious. "
                           f"See {sanity_fail}")
                    # Treat as a CI failure: enter the diagnosis/fix loop
                    # Rewrite the attempt status so the fix loop picks it up
                    attempt_record["status"] = "sanity_check_fail"
                    attempt_record["sanity_fail"] = sanity_fail.read_text()[:2000]
                    state["attempts"][-1] = attempt_record
                    state_file.write_text(json.dumps(state, indent=2))
                    # Rename so the next finalize attempt gets a clean slate
                    sanity_fail.rename(
                        debug_dir / f"attempt-{attempt}-sanity-check-fail.md"
                    )
                    # Fall through to diagnosis/fix below instead of returning
                else:
                    return

            if ci_result["status"] in ("error", "timeout"):
                ci_log(f"CI {ci_result['status']}: {ci_result.get('error', 'timed out')}")
                attempt_record["status"] = ci_result["status"]
                state["attempts"].append(attempt_record)
                state_file.write_text(json.dumps(state, indent=2))
                if ci_result["status"] == "timeout":
                    return
                continue

            if ci_result["status"] == "cancelled":
                cancelled_rid = ci_result.get("run_id")
                ci_log(f"CI run {cancelled_rid} was cancelled (attempt {attempt}) — skipping, will re-poll")
                if cancelled_rid:
                    skip_run_ids.add(cancelled_rid)
                attempt_record["status"] = "cancelled"
                state["attempts"].append(attempt_record)
                state_file.write_text(json.dumps(state, indent=2))
                # Don't push or create empty commits — just skip this run and
                # re-poll to find the actual latest non-cancelled run.
                # If there's no non-cancelled run, _poll_ci_run will return error
                # and the loop will continue to the next attempt.
                continue

            # ── Step 3: CI failed (or sanity check failed) — check for repeated failures ──
            is_sanity_fail = attempt_record.get("status") == "sanity_check_fail"
            failed_jobs = ', '.join(ci_result.get('failed_jobs', [])) or ('sanity-check' if is_sanity_fail else 'unknown')
            if is_sanity_fail:
                ci_log(f"Sanity check failed (attempt {attempt}): CI passed but results are suspicious")
            else:
                ci_log(f"CI failed (attempt {attempt}): {failed_jobs}")

            # Check if the same jobs have been failing consecutively (current session only)
            recent_failures = []
            session_attempts_for_stuck = [
                a for a in state.get("attempts", [])
                if a.get("session_id") == self.session_id
            ]
            for prev in reversed(session_attempts_for_stuck):
                prev_ci = prev.get("ci_result", {})
                prev_status = prev.get("status", "")
                if prev_ci.get("status") == "fail" or prev_status == "sanity_check_fail":
                    fail_key = frozenset(["sanity-check"]) if prev_status == "sanity_check_fail" \
                        else frozenset(prev_ci.get("failed_jobs", []))
                    recent_failures.append(fail_key)
                elif prev_ci.get("status") in ("pass", None) and prev_status != "sanity_check_fail":
                    break  # stop at last clean pass or non-CI attempt
                # skip cancelled/interrupted — they don't count
            current_failed = frozenset(["sanity-check"]) if is_sanity_fail \
                else frozenset(ci_result.get("failed_jobs", []))
            consecutive_same = sum(
                1 for rf in recent_failures if rf == current_failed
            )
            if consecutive_same >= CI_REPEAT_FAILURE_THRESHOLD:
                ci_log(
                    f"STUCK: same jobs ({failed_jobs}) failed {consecutive_same} "
                    f"consecutive times — stopping CI loop"
                )
                attempt_record["status"] = "stuck_repeated_failure"
                state["attempts"].append(attempt_record)
                state_file.write_text(json.dumps(state, indent=2))
                self.blocked_file.write_text(
                    f"# BLOCKED: {task.id} — stuck on repeated CI failure\n\n"
                    f"The same CI jobs ({failed_jobs}) have failed {consecutive_same} "
                    f"consecutive times with fixes applied between each attempt.\n\n"
                    f"## What I need\n\nHuman review — the automated fix loop is not "
                    f"converging on a solution.\n\n"
                    f"## Context\n\nAll diagnosis and log files are in `{debug_dir}/`.\n"
                    f"Most recent CI run: {ci_result.get('url', 'N/A')}\n"
                )
                return

            if is_sanity_fail:
                # Sanity-check failures already have a diagnosis (the sanity-check-fail file).
                # The finalize agent already analyzed the CI results semantically.
                # Skip log download and diagnosis agent — go straight to fix-validate.
                ci_log(f"Using sanity-check diagnosis as basis for fix (skipping CI log download)")
                # Write a diagnosis file so the fix agent can read it
                sanity_diag = debug_dir / f"attempt-{attempt}-sanity-check-fail.md"
                diag_file = debug_dir / f"attempt-{attempt}-diagnosis.md"
                if sanity_diag.exists() and not diag_file.exists():
                    diag_file.write_text(sanity_diag.read_text())
            else:
                log_file = debug_dir / f"attempt-{attempt}-logs.txt"
                if not _download_ci_logs(ci_result["run_id"], log_file):
                    ci_log("Failed to download CI logs")
                    log_file.write_text(f"Failed to download logs for run {ci_result['run_id']}")

                _download_ci_artifact(ci_result["run_id"], "ci-summary", debug_dir)

                # ── Step 4: Diagnose ──
                diag_prompt = build_ci_diagnose_prompt(
                    task.id, attempt, debug_dir, ci_result, learnings_file,
                )
                diag_task = Task(
                    id=f"{task.id}-diag-{attempt}",
                    description=f"Diagnose CI failure #{attempt}",
                    phase=task.phase, parallel=False,
                    status=TaskStatus.RUNNING, line_num=0,
                )
                _wait_for_subagent(diag_task, diag_prompt, f"Diagnosis agent (attempt {attempt})")

            diag_file = debug_dir / f"attempt-{attempt}-diagnosis.md"
            if not diag_file.exists():
                ci_log("Diagnosis agent didn't write diagnosis file — skipping fix")
                attempt_record["status"] = "diag_failed"
                state["attempts"].append(attempt_record)
                state_file.write_text(json.dumps(state, indent=2))
                continue

            # Check drain/shutdown between diagnose and fix
            if self._shutdown.is_set() or self._draining.is_set():
                ci_log(f"CI loop stopping after diagnosis — drain/shutdown requested")
                attempt_record["status"] = "interrupted_after_diag"
                state["attempts"].append(attempt_record)
                state_file.write_text(json.dumps(state, indent=2))
                return

            # ── Step 5: Local fix-validate loop ──
            # Run fix → validate → fix → validate locally up to CI_LOCAL_MAX_ITERATIONS
            # times before pushing. This catches failures that would waste CI cycles.
            prior_validate_output = ""
            local_passed = False

            for local_iter in range(1, CI_LOCAL_MAX_ITERATIONS + 1):
                if self._shutdown.is_set() or self._draining.is_set():
                    ci_log(f"CI loop stopping during local fix-validate — drain/shutdown")
                    attempt_record["status"] = "interrupted_during_local_fix"
                    state["attempts"].append(attempt_record)
                    state_file.write_text(json.dumps(state, indent=2))
                    return

                # ─��� 5a: Fix agent (applies fix, does NOT push) ──
                ci_log(f"Attempt {attempt}, local iteration {local_iter}/{CI_LOCAL_MAX_ITERATIONS}: spawning fix agent")
                fix_prompt = build_ci_fix_prompt(
                    task.id, attempt, debug_dir, str(task_file), learnings_file,
                )
                fix_task = Task(
                    id=f"{task.id}-fix-{attempt}-{local_iter}",
                    description=f"Fix CI failure #{attempt} (local iter {local_iter})",
                    phase=task.phase, parallel=False,
                    status=TaskStatus.RUNNING, line_num=0,
                    capabilities=task.capabilities,
                )
                _wait_for_subagent(fix_task, fix_prompt,
                                   f"Fix agent (attempt {attempt}, local {local_iter})",
                                   caps=task.capabilities)

                if self._shutdown.is_set() or self._draining.is_set():
                    ci_log(f"CI loop stopping after fix — drain/shutdown")
                    attempt_record["status"] = "interrupted_during_local_fix"
                    state["attempts"].append(attempt_record)
                    state_file.write_text(json.dumps(state, indent=2))
                    return

                # ── 5b: Validate agent (runs CI commands locally, does NOT fix) ──
                ci_log(f"Attempt {attempt}, local iteration {local_iter}/{CI_LOCAL_MAX_ITERATIONS}: spawning validation agent")
                validate_prompt = build_ci_local_validate_prompt(
                    task.id, attempt, local_iter, debug_dir, learnings_file,
                    prior_output=prior_validate_output,
                )
                validate_task = Task(
                    id=f"{task.id}-validate-{attempt}-{local_iter}",
                    description=f"Local validation #{attempt}.{local_iter}",
                    phase=task.phase, parallel=False,
                    status=TaskStatus.RUNNING, line_num=0,
                )
                _wait_for_subagent(validate_task, validate_prompt,
                                   f"Validation agent (attempt {attempt}, local {local_iter})")

                # Check validation result
                validate_file = debug_dir / f"attempt-{attempt}-local-{local_iter}.md"
                if validate_file.exists():
                    content = validate_file.read_text()
                    prior_validate_output = content
                    # Check for PASS in the result heading
                    if "## Result: PASS" in content:
                        ci_log(f"Local validation PASSED on iteration {local_iter}")
                        local_passed = True
                        break
                    else:
                        ci_log(f"Local validation FAILED on iteration {local_iter} — looping")
                else:
                    ci_log(f"Validation agent didn't write result file — treating as failure")
                    prior_validate_output = "(no validation output — agent didn't write result file)"

            # ── 5c: Push only after local validation passes ──
            if local_passed:
                ci_log(f"Local validation passed — pushing to {branch}")
                try:
                    push_ok = _gh_push(branch, ci_log)
                    if not push_ok:
                        ci_log("Push failed after local validation")
                        attempt_record["status"] = "push_failed_after_local"
                        state["attempts"].append(attempt_record)
                        state_file.write_text(json.dumps(state, indent=2))
                        continue
                except subprocess.TimeoutExpired:
                    ci_log("Push timed out after local validation")
                    continue
                attempt_record["status"] = "fix_applied"
                attempt_record["local_iterations"] = local_iter
            else:
                ci_log(f"Local validation failed after {CI_LOCAL_MAX_ITERATIONS} iterations — pushing anyway (CI will catch remaining issues)")
                try:
                    _gh_push(branch, ci_log)
                except subprocess.TimeoutExpired:
                    ci_log("Push timed out")
                attempt_record["status"] = "fix_applied_local_incomplete"
                attempt_record["local_iterations"] = CI_LOCAL_MAX_ITERATIONS

            state["attempts"].append(attempt_record)
            state_file.write_text(json.dumps(state, indent=2))

        # Exhausted attempts
        ci_log(f"CI loop exhausted after {CI_LOOP_MAX_ATTEMPTS} attempts")
        self.blocked_file.write_text(
            f"# BLOCKED: {task.id} — CI loop exhausted\n\n"
            f"CI failed {CI_LOOP_MAX_ATTEMPTS} times. See `{debug_dir}/` for full history.\n\n"
            f"## What I need\n\nHuman review of the CI failures — the automated loop couldn't resolve them.\n\n"
            f"## Context\n\nAll diagnosis and log files are in `{debug_dir}/`.\n"
        )

    # ── E2E Explore-Fix-Verify loop ──────────────────────────────────────

    def _run_e2e_loop(self, task: Task, spec_dir: str, task_file: Path,
                      learnings_file: str):
        """Run the E2E explore-fix-verify loop, catching auth failures."""
        e2e_dir = Path(spec_dir) / "validate" / "e2e"
        e2e_dir.mkdir(parents=True, exist_ok=True)

        try:
            return self._run_e2e_loop_inner(task, spec_dir, task_file, learnings_file)
        except AgentAuthError as e:
            self.log(f"FATAL: Auth error in E2E loop for {task.id}")
            self._shutdown.set()
            self.blocked_file.write_text(
                f"# BLOCKED: {task.id} — Authentication expired during E2E loop\n\n"
                f"Re-authenticate Claude Code and restart.\n\n"
                f"## Context\n\nE2E findings and logs are in `{e2e_dir}/`.\n"
            )

    def _run_e2e_loop_inner(self, task: Task, spec_dir: str, task_file: Path,
                            learnings_file: str):
        """Inner E2E loop: explore → fix → rebuild → verify, with supervisor.

        The loop uses three agent types:
        1. EXPLORE agent (with MCP): walks the app via UI_FLOW.md, takes
           screenshots, reads view trees, discovers bugs in batches.
           Writes findings to validate/e2e/findings.json.
        2. FIX agent (no MCP): reads findings.json, fixes all reported
           bugs in a single batch pass. Commits changes.
        3. VERIFY agent (with MCP): re-tests each bug from findings.json,
           marks fixed/still-broken, discovers new bugs during re-testing.

        Between fix and verify, the runner rebuilds + reinstalls the app.

        A SUPERVISOR agent runs every N iterations to assess progress and
        either redirect strategy, stop the loop, or continue.
        """
        e2e_dir = Path(spec_dir) / "validate" / "e2e"
        e2e_dir.mkdir(parents=True, exist_ok=True)
        findings_file = e2e_dir / "findings.json"
        e2e_log_path = e2e_dir / "e2e-loop.log"
        project_dir = Path.cwd()

        # ── Clean stale state from prior runs ──
        # Remove progress/findings files so the explore agent starts
        # fresh instead of reading old data and skipping MCP exploration.
        for stale in [
            e2e_dir / "progress.md",
            e2e_dir / "progress-full.md",
            e2e_dir / "findings.json",
            e2e_dir / "findings-full.json",
            e2e_dir / "state.json",
            e2e_dir / "guidance.md",
            e2e_dir / "supervisor-decision.md",
        ]:
            if stale.exists():
                stale.unlink()

        # Supervisor interval: every N iterations, assess progress
        SUPERVISOR_INTERVAL = 10
        # Watchdog: kill an agent if its JSONL log goes idle (no new
        # entries).  MCP-heavy E2E tasks legitimately run for 45+ min with
        # hundreds of tool calls, so a wall-clock cap is wrong — we only
        # want to kill agents that have stopped producing output.
        # Builds (e.g. `make gomobile`) can go 10 min without log output,
        # so the idle threshold is generous.
        AGENT_IDLE_TIMEOUT_S = 15 * 60   # kill after 15 min of log silence
        AGENT_HARD_TIMEOUT_S = 120 * 60  # absolute cap as a safety net

        def e2e_log(msg: str):
            ts = datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] {msg}"
            with open(e2e_log_path, "a") as f:
                f.write(line + "\n")
            with self._lock:
                for agent in self.agents:
                    if agent.task.id == task.id:
                        agent.output_lines.append(line)
                        if len(agent.output_lines) > 200:
                            agent.output_lines = agent.output_lines[-200:]
                        break
            self.log(msg)

        def _wait_for_subagent(sub_task: Task, prompt: str, label: str,
                               caps: set[str] | None = None,
                               mcp_configs: list[Path] | None = None,
                               model: str = "opus") -> int:
            """Spawn a sub-agent, track it, wait for completion. Returns exit code."""
            self.agent_counter += 1
            aid = self.agent_counter
            log_p = self.log_dir / f"agent-{aid}-{sub_task.id}-{self.timestamp}.jsonl"
            stderr_p = self.log_dir / f"agent-{aid}-{sub_task.id}-{self.timestamp}.stderr"
            proc = spawn_agent(sub_task, prompt, log_p, stderr_p,
                               extra_capabilities=caps,
                               mcp_config_paths=mcp_configs,
                               model=model)

            slot = AgentSlot(
                agent_id=aid, task=sub_task, process=proc,
                pid=proc.pid, start_time=time.time(),
                log_file=log_p, status="running",
            )
            with self._lock:
                self.agents.append(slot)
                for a in self.agents:
                    if a.task.id == task.id and a.is_ci_loop:
                        a.active_sub_agent_id = aid
                        break

            e2e_log(f"Spawned {label} (Agent {aid}, pid {proc.pid})")
            # Watchdog: poll every 60s, kill if the JSONL log file hasn't
            # been updated in AGENT_IDLE_TIMEOUT_S.  Active agents write a
            # new line for every tool call / response, so a stale log means
            # the agent is stuck.  A hard wall-clock cap remains as a safety net.
            timeout_killed = False
            kill_reason = ""
            agent_start = time.time()
            while proc.poll() is None:
                time.sleep(60)
                now = time.time()
                # Check log file freshness
                try:
                    last_activity = log_p.stat().st_mtime
                except OSError:
                    last_activity = agent_start
                idle_s = now - last_activity
                wall_s = now - agent_start
                if idle_s > AGENT_IDLE_TIMEOUT_S:
                    kill_reason = (
                        f"idle for {int(idle_s)}s (no log output) — killing"
                    )
                elif wall_s > AGENT_HARD_TIMEOUT_S:
                    kill_reason = (
                        f"exceeded {AGENT_HARD_TIMEOUT_S}s hard wall-clock limit — killing"
                    )
                if kill_reason:
                    e2e_log(
                        f"{label} (Agent {aid}, pid {proc.pid}) {kill_reason}"
                    )
                    proc.kill()
                    proc.wait()
                    timeout_killed = True
                    break
            if timeout_killed:
                sub_status = "timeout"
            else:
                sub_status = "done" if proc.returncode == 0 else "failed"
            slot.status = sub_status

            sub_in_tok, sub_out_tok = 0, 0
            if log_p and log_p.exists():
                _, _, _, (sub_in_tok, sub_out_tok) = read_stream_output(log_p, 0)

            record = SubAgentRecord(
                agent_id=aid, label=sub_task.id,
                input_tokens=sub_in_tok, output_tokens=sub_out_tok,
                elapsed_s=int(time.time() - slot.start_time), status=sub_status,
            )
            with self._lock:
                for a in self.agents:
                    if a.task.id == task.id and a.is_ci_loop:
                        a.sub_agent_history.append(record)
                        a.input_tokens += sub_in_tok
                        a.output_tokens += sub_out_tok
                        a.active_sub_agent_id = None
                        break
                self.agents = [a for a in self.agents if a.agent_id != aid]

            e2e_log(f"{label} completed (exit {proc.returncode}, {(sub_in_tok + sub_out_tok) // 1000}k tok)")

            if proc.returncode != 0:
                auth_err = check_auth_error(log_p)
                if auth_err:
                    raise AgentAuthError("Sub-agent authentication failed (401)")

            return proc.returncode

        def _wait_for_subagents_parallel(items, max_concurrency: int = 10,
                                          caps: set[str] | None = None,
                                          mcp_configs: list[Path] | None = None,
                                          model: str = "opus") -> list[int]:
            """Run multiple sub-agents in parallel, up to max_concurrency at a
            time. `items` is a list of (sub_task, prompt, label) tuples.
            Returns exit codes in input order. Applies the same idle/wall-clock
            watchdogs as _wait_for_subagent. Raises AgentAuthError if any
            agent hits a 401."""
            @dataclass
            class _Running:
                idx: int
                sub_task: Task
                label: str
                proc: subprocess.Popen
                slot: AgentSlot
                log_p: Path
                aid: int
                start: float
                timeout_killed: bool = False

            exit_codes: list[int | None] = [None] * len(items)
            queue = list(enumerate(items))
            running: list[_Running] = []

            def _spawn_one(idx: int, sub_task: Task, prompt: str, label: str) -> _Running:
                self.agent_counter += 1
                aid = self.agent_counter
                log_p = self.log_dir / f"agent-{aid}-{sub_task.id}-{self.timestamp}.jsonl"
                stderr_p = self.log_dir / f"agent-{aid}-{sub_task.id}-{self.timestamp}.stderr"
                proc = spawn_agent(sub_task, prompt, log_p, stderr_p,
                                   extra_capabilities=caps,
                                   mcp_config_paths=mcp_configs,
                                   model=model)
                slot = AgentSlot(
                    agent_id=aid, task=sub_task, process=proc,
                    pid=proc.pid, start_time=time.time(),
                    log_file=log_p, status="running",
                )
                with self._lock:
                    self.agents.append(slot)
                e2e_log(f"Spawned {label} (Agent {aid}, pid {proc.pid})")
                return _Running(idx=idx, sub_task=sub_task, label=label,
                                proc=proc, slot=slot, log_p=log_p, aid=aid,
                                start=time.time())

            # Prime the pool
            while queue and len(running) < max_concurrency:
                idx, (sub_task, prompt, label) = queue.pop(0)
                running.append(_spawn_one(idx, sub_task, prompt, label))

            # Poll loop: wait for any to finish, then refill from queue
            while running:
                time.sleep(60)
                now = time.time()
                still_running: list[_Running] = []
                for r in running:
                    if r.proc.poll() is not None:
                        # finished
                        exit_codes[r.idx] = r.proc.returncode
                        _finalize_subagent(r)
                        continue
                    # still alive — check watchdogs
                    try:
                        last_activity = r.log_p.stat().st_mtime
                    except OSError:
                        last_activity = r.start
                    idle_s = now - last_activity
                    wall_s = now - r.start
                    kill_reason = ""
                    if idle_s > AGENT_IDLE_TIMEOUT_S:
                        kill_reason = f"idle for {int(idle_s)}s (no log output) — killing"
                    elif wall_s > AGENT_HARD_TIMEOUT_S:
                        kill_reason = f"exceeded {AGENT_HARD_TIMEOUT_S}s hard wall-clock limit — killing"
                    if kill_reason:
                        e2e_log(f"{r.label} (Agent {r.aid}, pid {r.proc.pid}) {kill_reason}")
                        r.proc.kill()
                        r.proc.wait()
                        r.timeout_killed = True
                        exit_codes[r.idx] = r.proc.returncode
                        _finalize_subagent(r)
                        continue
                    still_running.append(r)
                running = still_running
                # refill
                while queue and len(running) < max_concurrency:
                    idx, (sub_task, prompt, label) = queue.pop(0)
                    running.append(_spawn_one(idx, sub_task, prompt, label))

            return [ec if ec is not None else 1 for ec in exit_codes]

        def _finalize_subagent(r) -> None:
            """Shared post-exit bookkeeping for a finished sub-agent."""
            sub_status = "timeout" if r.timeout_killed else (
                "done" if r.proc.returncode == 0 else "failed"
            )
            r.slot.status = sub_status
            sub_in_tok, sub_out_tok = 0, 0
            if r.log_p and r.log_p.exists():
                _, _, _, (sub_in_tok, sub_out_tok) = read_stream_output(r.log_p, 0)
            record = SubAgentRecord(
                agent_id=r.aid, label=r.sub_task.id,
                input_tokens=sub_in_tok, output_tokens=sub_out_tok,
                elapsed_s=int(time.time() - r.slot.start_time), status=sub_status,
            )
            with self._lock:
                for a in self.agents:
                    if a.task.id == task.id and a.is_ci_loop:
                        a.sub_agent_history.append(record)
                        a.input_tokens += sub_in_tok
                        a.output_tokens += sub_out_tok
                        break
                self.agents = [a for a in self.agents if a.agent_id != r.aid]
            e2e_log(f"{r.label} completed (exit {r.proc.returncode}, {(sub_in_tok + sub_out_tok) // 1000}k tok)")
            if r.proc.returncode != 0:
                auth_err = check_auth_error(r.log_p)
                if auth_err:
                    raise AgentAuthError("Sub-agent authentication failed (401)")

        # ── Initialize platform runtime ──
        mcp_caps = task.capabilities & _MCP_CAPABILITIES
        if not mcp_caps:
            e2e_log(f"Task {task.id} has no MCP capabilities — cannot run E2E loop")
            return

        # Create PlatformManager with a log function that writes to BOTH
        # the runner's main log and e2e-loop.log, so boot diagnostics
        # are visible when debugging failures.
        def platform_log(msg):
            self.log(msg)
            e2e_log(f"[platform] {msg}")

        if not hasattr(self, '_platform_manager'):
            self._platform_manager = PlatformManager(log_fn=platform_log)
        else:
            # Update log function so it writes to this task's e2e-loop.log
            self._platform_manager._log = platform_log

        PLATFORM_INIT_MAX_ATTEMPTS = 10
        fix_history_path = project_dir / "test" / "e2e" / ".state" / "fix-history.md"
        playbook_path = self.script_dir / "reference" / "fix-agent-playbook.md"
        patterns_path = self.script_dir / "reference" / "e2e-failure-patterns.md"

        def _load_reference(path: Path) -> str:
            try:
                return path.read_text()
            except OSError:
                return ""

        def _parse_setup_failure(setup_log: Path) -> dict:
            """Extract the failing service + port from setup-failure.log.

            Returns a dict with optional keys: timed_out (bool), exit_code (int),
            failed_service (str), failed_port (int), error_line (str),
            full_text (str).
            """
            out: dict = {"full_text": ""}
            if not setup_log.exists():
                return out
            try:
                text = setup_log.read_text()
            except OSError:
                return out
            out["full_text"] = text
            if "timed out after" in text.split("\n", 2)[0]:
                out["timed_out"] = True
            m = re.search(r"===\s*exit code:\s*(-?\d+)\s*===", text)
            if m:
                out["exit_code"] = int(m.group(1))
            # Match the e2e-setup ERROR line that says which service+port timed out.
            # Examples:
            #   "ERROR: API server did not start within 30s on port 3000"
            #   "ERROR: Astro site did not start within 30s on port 4321"
            #   "ERROR: SuperTokens did not respond at http://127.0.0.1:3567/hello within 60s"
            m = re.search(
                r"ERROR:\s*(.+?)\s+did not (?:start|respond).*?(?:port\s+(\d+)|:(\d+)/)",
                text,
            )
            if m:
                out["error_line"] = m.group(0)
                out["failed_service"] = m.group(1).strip()
                port = m.group(2) or m.group(3)
                if port:
                    out["failed_port"] = int(port)
            else:
                # Fallback: last non-empty line that contains "ERROR"
                for line in reversed([l for l in text.splitlines() if l.strip()]):
                    if "ERROR" in line.upper():
                        out["error_line"] = line.strip()
                        break
            return out

        def _service_log_for(service: str) -> Optional[Path]:
            """Map the service name from setup-failure.log to its log file."""
            if not service:
                return None
            s = service.lower()
            candidates = {
                "api server": "api.log",
                "api": "api.log",
                "astro site": "astro.log",
                "astro": "astro.log",
                "postgresql": "postgres.log",
                "postgres": "postgres.log",
                "supertokens": "supertokens.log",
            }
            for key, fname in candidates.items():
                if key in s:
                    return project_dir / ".dev" / "e2e-state" / fname
            # Fallback: <service-slug>.log
            slug = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
            return project_dir / ".dev" / "e2e-state" / f"{slug}.log"

        def _port_binding(port: int) -> str:
            """Run `ss -tlnp` for the port. Returns its output or a note."""
            try:
                r = subprocess.run(
                    ["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
                matches = [l for l in r.stdout.splitlines() if f":{port} " in l or f":{port}\t" in l]
                if matches:
                    return "\n".join(matches)
                return f"(no listener on port {port})"
            except Exception as e:
                return f"(ss failed: {e})"

        def _match_patterns(failure: dict, service_log_tail: str) -> list[str]:
            """Match the failure signature against the pattern library.

            Returns a list of pattern *names* whose signature matches. The runner
            then extracts just those sections from e2e-failure-patterns.md.
            """
            matched: list[str] = []
            if failure.get("timed_out") or "did not start" in failure.get("error_line", "") \
                    or "did not respond" in failure.get("error_line", ""):
                # If the service log mentions "ready" / "listening" / "started"
                # but wait_for_port still failed, it's the IPv6/IPv4 pattern.
                tail_lc = service_log_tail.lower()
                if any(k in tail_lc for k in ["ready", "listening", "started", "accepting connections"]):
                    matched.append("port-timeout-but-service-ready")
                else:
                    matched.append("service-crash-on-boot")
            log_lc = service_log_tail.lower()
            if "config validation failed" in log_lc or "missing required config" in log_lc:
                matched.append("config-validation-missing-required")
            if any(k in log_lc for k in [
                "duplicate key", "already exists", "unexpected checksum",
            ]) and "migrate" in service_log_tail.lower():
                matched.append("migration-already-applied")
            if "emulator" in failure.get("error_line", "").lower() or \
               (failure.get("failed_service") or "").lower().startswith("emulator"):
                matched.append("emulator-boot-timeout")
            # Stale process heuristic: if service log is older than ~2 minutes
            # but the current attempt is happening now, caller should inject this.
            return matched

        def _extract_pattern_sections(names: list[str]) -> str:
            """Pull just the matching `## Signature: <name>` sections from the
            pattern library, so the fix-agent gets only relevant hints."""
            if not names:
                return ""
            library = _load_reference(patterns_path)
            if not library:
                return ""
            # Split on the `## Signature:` boundaries.
            parts = re.split(r"(?m)^##\s+Signature:\s*", library)
            sections: list[str] = []
            for part in parts[1:]:  # parts[0] is the preamble
                first_line, _, rest = part.partition("\n")
                name = first_line.strip()
                if name in names:
                    sections.append(f"## Signature: {name}\n{rest.rstrip()}")
            if not sections:
                return ""
            return "\n\n---\n\n".join(sections)

        def _prior_attempts_summary() -> str:
            """Read fix-history.md — a rolling log of prior fix-agent attempts."""
            if not fix_history_path.exists():
                return ""
            try:
                return fix_history_path.read_text()
            except OSError:
                return ""

        def _prior_attempts_diff(since_attempt: int) -> str:
            """Show what previous fix-agents changed, so this one doesn't repeat."""
            if since_attempt < 1:
                return ""
            try:
                # Look back a generous number of commits in case fix-agents
                # made multiple commits per attempt, then filter to those that
                # touched e2e / .env / api config.
                r = subprocess.run(
                    ["git", "log", "--oneline", "-30", "--",
                     "test/", ".env", "api/src/config/", "site/", "admin/", "customer/"],
                    capture_output=True, text=True, timeout=10, cwd=str(project_dir))
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip()
            except Exception:
                pass
            return ""

        def _record_attempt(attempt: int, failure: dict, matched: list[str]):
            """Append a terse line to fix-history.md so the next fix-agent
            sees prior attempts at a glance."""
            try:
                fix_history_path.parent.mkdir(parents=True, exist_ok=True)
                line = (
                    f"- attempt {attempt}: service={failure.get('failed_service', '?')} "
                    f"port={failure.get('failed_port', '?')} "
                    f"patterns={','.join(matched) or 'none'} "
                    f"at={datetime.now().isoformat(timespec='seconds')}"
                )
                with open(fix_history_path, "a") as f:
                    f.write(line + "\n")
            except OSError:
                pass

        def _build_platform_diag(cap: str, attempt: int) -> str:
            """Build a focused diagnostic. Instead of dumping every log, this
            identifies the failing service and attaches only its tail + port
            binding + matched failure patterns."""
            import shutil as _sh
            lines: list[str] = [f"Could not boot `{cap}` runtime.\n", "## Platform diagnostics\n"]
            lines.append(f"- start-emulator in PATH: {bool(_sh.which('start-emulator'))}")
            lines.append(f"- emulator in PATH: {bool(_sh.which('emulator'))}")
            lines.append(f"- adb in PATH: {bool(_sh.which('adb'))}")
            lines.append(f"- flake.nix exists: {(project_dir / 'flake.nix').exists()}")
            lines.append(f"- project_dir: {project_dir}")
            try:
                adb_result = subprocess.run(
                    ["adb", "devices"], capture_output=True, text=True, timeout=5)
                lines.append(f"- adb devices: {adb_result.stdout.strip()}")
            except Exception as e:
                lines.append(f"- adb devices: error ({e})")
            lines.append(f"- _e2e_services_started: {self._platform_manager._e2e_services_started}")
            lines.append(f"- _booted runtimes: {list(self._platform_manager._runtimes.keys())}")

            setup_log = project_dir / "test" / "e2e" / ".state" / "setup-failure.log"
            failure = _parse_setup_failure(setup_log)

            if failure.get("error_line"):
                lines.append(f"\n## Failing step\n\n`{failure['error_line']}`")
            if failure.get("timed_out"):
                lines.append("\n*setup.sh was killed by the runner after 300s (timeout).*")

            service_log_tail = ""
            if failure.get("failed_service"):
                svc_log = _service_log_for(failure["failed_service"])
                if svc_log and svc_log.exists():
                    try:
                        raw = svc_log.read_text().splitlines()
                        service_log_tail = "\n".join(raw[-80:])
                        lines.append(
                            f"\n## Tail of `{svc_log.relative_to(project_dir)}` "
                            f"(last 80 lines — this is the service that failed)\n"
                        )
                        lines.append("```")
                        lines.append(service_log_tail)
                        lines.append("```")
                        try:
                            mtime = datetime.fromtimestamp(svc_log.stat().st_mtime)
                            lines.append(f"\n*log mtime: {mtime.isoformat(timespec='seconds')}"
                                         f" — if this is stale vs. now, a prior broken process "
                                         f"may still be running (see stale-process pattern).*")
                        except OSError:
                            pass
                    except OSError:
                        pass

            if failure.get("failed_port"):
                binding = _port_binding(failure["failed_port"])
                lines.append(
                    f"\n## Port binding for {failure['failed_port']}\n\n"
                    f"```\n{binding}\n```"
                )

            matched = _match_patterns(failure, service_log_tail)
            pattern_section = _extract_pattern_sections(matched)
            if pattern_section:
                lines.append(
                    f"\n## Matching failure patterns\n\n"
                    f"The runner's pattern library matched **{', '.join(matched)}**. "
                    f"Use the guidance below before exploring other hypotheses.\n"
                )
                lines.append(pattern_section)

            prior = _prior_attempts_summary()
            if prior:
                lines.append("\n## Prior fix-agent attempts for this boot\n")
                lines.append("```")
                lines.append(prior.rstrip())
                lines.append("```")

            prior_diff = _prior_attempts_diff(attempt)
            if prior_diff:
                lines.append("\n## Recent git commits touching E2E-relevant paths\n")
                lines.append("```")
                lines.append(prior_diff)
                lines.append("```")
                lines.append(
                    "\n*If one of the commits above matches what you were about to try, "
                    "pick a different approach — it already failed.*"
                )

            # Always include the raw tail of setup-failure.log as a last resort,
            # but shorter now that we've already extracted the salient parts.
            if failure.get("full_text"):
                lines.append("\n## Raw setup-failure.log (last 1500 chars — context only)\n")
                lines.append("```")
                lines.append(failure["full_text"][-1500:])
                lines.append("```")

            # Stash for the caller so _record_attempt can use the same parse.
            self._last_platform_failure = {"failure": failure, "matched": matched}
            return "\n".join(lines)

        _PLATFORM_FIX_PLAYBOOK = _load_reference(playbook_path)

        def _repeat_failure_section(attempt: int) -> str:
            """If this attempt's failure signature (service + matched patterns)
            matches a prior recorded attempt, the previous hypothesis did not
            work. Tell the new agent explicitly so it drops that hypothesis
            instead of re-trying it with a fresh face. This breaks the
            pattern-lock-in loop where each agent re-derives the same wrong
            answer from the same pattern match."""
            parsed = getattr(self, "_last_platform_failure", {}) or {}
            cur_service = (parsed.get("failure") or {}).get("failed_service") or ""
            cur_patterns = set(parsed.get("matched") or [])
            if not cur_service or not cur_patterns:
                return ""
            if not fix_history_path.exists():
                return ""
            try:
                history = fix_history_path.read_text()
            except OSError:
                return ""
            # Parse prior lines:
            #   - attempt N: service=X port=P patterns=a,b at=...
            # Skip the current attempt's own line (already appended).
            prior_matches: list[str] = []
            for line in history.splitlines():
                m = re.match(
                    r"-\s+attempt\s+(\d+):\s+service=(\S+)\s+port=\S+\s+patterns=(\S+)",
                    line,
                )
                if not m:
                    continue
                prior_attempt_n = int(m.group(1))
                prior_service = m.group(2)
                prior_patterns = set(p for p in m.group(3).split(",") if p and p != "none")
                if prior_attempt_n >= attempt:
                    continue  # skip current + future
                if prior_service != cur_service:
                    continue
                if not (prior_patterns & cur_patterns):
                    continue
                prior_matches.append(line)
            if not prior_matches:
                return ""
            shared = ", ".join(sorted(cur_patterns))
            return (
                "\n## STOP — your predecessors already tried the obvious fix\n\n"
                "This is not the first attempt at this exact failure. Prior fix-agents "
                f"saw the same service (`{cur_service}`) hit the same pattern(s) "
                f"(`{shared}`) and their fixes did not work — the boot is still failing.\n\n"
                "Prior attempts with the same signature:\n\n"
                "```\n" + "\n".join(prior_matches) + "\n```\n\n"
                "**Falsification rule:** The hypothesis implied by the matched pattern is "
                "now suspect. Do NOT re-apply it or a close variant. Before writing any "
                "code, spend your first few actions *disproving the obvious hypothesis*:\n\n"
                "- Run the diagnostic commands from the pattern section yourself and "
                "  paste their output into your reasoning. Don't assume — verify.\n"
                "- Check whether the tools the setup script depends on are actually in "
                "  PATH (`command -v lsof`, `command -v ss`, etc.). Scripts that guard "
                "  errors with `2>/dev/null || true` fail silently when a tool is missing.\n"
                "- Check whether the 'ready' log line in the service log came from *this* "
                "  run or a ghost process from a previous run (compare log mtime and pid "
                "  against the pid file, and confirm the pid is actually alive).\n"
                "- Inspect the setup script's actual behavior on *this* machine — do the "
                "  kill paths it claims to use actually find and kill anything?\n\n"
                "If the diagnostics contradict the matched pattern, state that explicitly "
                "and pursue a different hypothesis. Exit 0 from a guarded shell script is "
                "not proof of a fix.\n"
            )

        def _build_platform_fix_prompt(cap: str, attempt: int, diag: str) -> str:
            playbook_section = ""
            if _PLATFORM_FIX_PLAYBOOK:
                playbook_section = (
                    "\n## Fix-agent playbook (general debugging heuristics)\n\n"
                    "These apply to every fix-agent. Read them before diving in.\n\n"
                    + _PLATFORM_FIX_PLAYBOOK
                )
            repeat_section = _repeat_failure_section(attempt)
            return f"""You are fixing a platform runtime initialization failure for task {task.id}.

The runner tried to boot the `{cap}` platform runtime so it could run an E2E
test loop, but the boot failed. This is attempt **{attempt}/{PLATFORM_INIT_MAX_ATTEMPTS}**.
If you don't fix it, the runner will spawn another fix-agent with updated
diagnostics. After {PLATFORM_INIT_MAX_ATTEMPTS} failed attempts, the runner
writes BLOCKED.md and stops.

## What "boot the runtime" means

- `mcp-browser`: the runner runs `test/e2e/setup.sh` to start backend services
  (Postgres, SuperTokens, API, Astro, etc.). Chromium is bundled with the MCP
  server — no separate browser boot. A `mcp-browser` failure almost always
  means `test/e2e/setup.sh` failed or timed out (cap 300s).
- `mcp-android`: runs `test/e2e/setup.sh`, then boots the Android emulator
  via `start-emulator` / `emulator -list-avds`.
- `mcp-ios`: uses `xcrun simctl`.

{diag}
{repeat_section}
{playbook_section}

## Your job

1. **Read the diagnostics above first.** The runner has already identified
   the failing service, attached its log tail, shown the port binding, and
   matched the failure against known patterns. Use that — don't re-explore
   the repo from scratch.
2. If a pattern matched, its "Fix options" section lists ranked preferences.
   Start there.
3. Form a hypothesis, apply the smallest fix that addresses it, then
   **verify by reproducing from a clean state** (kill stale processes,
   remove `.dev/e2e-state/*.pid`, re-run `bash test/e2e/setup.sh`, confirm
   exit 0). Verification is required — "exit 0 from the guarded happy path"
   is not the same as a real fix.
4. On your final message, follow the "Finishing" section of the playbook
   (root cause / fix / verification / residual risk).

## Constraints

- Do NOT write `BLOCKED.md`, `DEFER-*.md`, or any "skip this" file. The
  runner decides when to give up.
- Do NOT disable tests, mark them `.skip`, or add long sleeps to mask races.
- Do NOT modify `specs/` or mark tasks complete.
- Do NOT expand scope — if the bug is in setup.sh, fix setup.sh and stop.
- If a fix requires a real user secret (e.g. a real Stripe live key),
  prefer a test-mode default or an E2E-optional config path. Only if
  that's impossible, document it clearly in your final message.

Succeed = exit 0 from a cold re-run of setup.sh (or the relevant boot step).
"""

        mcp_config_paths = []
        platform_init_failed = False
        for cap in mcp_caps:
            attempt = 0
            runtime = None
            last_diag = ""
            while attempt < PLATFORM_INIT_MAX_ATTEMPTS:
                if self._shutdown.is_set() or self._draining.is_set():
                    e2e_log("Shutdown/drain requested during platform init — aborting retry loop")
                    platform_init_failed = True
                    break
                attempt += 1
                e2e_log(f"Platform runtime init for {cap}: attempt {attempt}/{PLATFORM_INIT_MAX_ATTEMPTS}")
                runtime = self._platform_manager.ensure_runtime(cap, project_dir)
                if runtime:
                    e2e_log(f"Platform runtime {cap} initialized on attempt {attempt}")
                    break

                last_diag = _build_platform_diag(cap, attempt)
                e2e_log(f"Failed to initialize platform runtime for {cap} (attempt {attempt}/{PLATFORM_INIT_MAX_ATTEMPTS})")
                e2e_log(last_diag)
                # Persist a terse line to fix-history.md for the next fix-agent.
                parsed = getattr(self, "_last_platform_failure", {}) or {}
                _record_attempt(attempt, parsed.get("failure", {}), parsed.get("matched", []))
                self._write_event(
                    "platform_init_fail", spec_dir,
                    task_id=task.id, capability=cap, attempt=attempt,
                    failed_service=(parsed.get("failure") or {}).get("failed_service"),
                    failed_port=(parsed.get("failure") or {}).get("failed_port"),
                    patterns=parsed.get("matched") or [],
                )

                if attempt >= PLATFORM_INIT_MAX_ATTEMPTS:
                    break

                # Spawn a fix agent to diagnose and repair the runtime boot.
                fix_task = Task(
                    id=f"{task.id}-platform-fix-{attempt}",
                    description=f"Fix platform runtime init failure for {cap} (attempt {attempt})",
                    phase=task.phase, parallel=False,
                    status=TaskStatus.RUNNING, line_num=0,
                    capabilities=task.capabilities,
                )
                fix_prompt = _build_platform_fix_prompt(cap, attempt, last_diag)
                self._write_event(
                    "platform_fix_spawn", spec_dir,
                    task_id=task.id, capability=cap, attempt=attempt,
                )
                try:
                    _wait_for_subagent(
                        fix_task, fix_prompt,
                        f"Platform fix agent ({cap}, attempt {attempt})",
                        caps=task.capabilities,
                    )
                except AgentAuthError:
                    # Auth errors are fatal — let the outer handler surface them.
                    raise
                except Exception as exc:
                    e2e_log(f"Platform fix agent raised {exc!r} — continuing retry loop")

            if not runtime:
                platform_init_failed = True
                diag_msg = (
                    f"# BLOCKED: {task.id} — Platform runtime initialization failed\n\n"
                    f"Gave up after {PLATFORM_INIT_MAX_ATTEMPTS} fix attempts.\n\n"
                    + last_diag
                )
                e2e_log(f"Platform runtime {cap} still failing after {PLATFORM_INIT_MAX_ATTEMPTS} attempts — writing BLOCKED.md")
                self.blocked_file.write_text(diag_msg + "\n")
                break

            paths = self._platform_manager.get_mcp_config_paths({cap})
            mcp_config_paths.extend(paths)

        if platform_init_failed:
            return

        e2e_log(f"Platform runtimes initialized: {', '.join(c.replace('mcp-', '') for c in mcp_caps)}")

        # ── Initial build from current source ──
        # Always rebuild before the first explore to ensure we're testing
        # the current code, not a stale APK from a previous run.
        e2e_log("Building and installing app from current source...")
        for cap in mcp_caps:
            build_log = e2e_dir / f"build-initial.log"
            result = self._platform_manager.build_and_install(cap, project_dir, build_log)
            if result != BuildResult.OK:
                e2e_log(f"Initial build failed ({result.value}) — see {build_log}")
                # Don't block — the build-fix loop in the main cycle will handle it

        # ── Read context files for prompts ──
        ui_flow_content = ""
        for candidate in [
            Path(spec_dir) / "UI_FLOW.md",
            Path(spec_dir) / "ui_flow.md",
        ]:
            if candidate.exists():
                ui_flow_content = candidate.read_text()
                break

        spec_content = ""
        spec_path = Path(spec_dir) / "spec.md"
        if spec_path.exists():
            # Read first 10000 chars to avoid blowing up the prompt
            spec_content = spec_path.read_text()[:10000]

        # ── State tracking ──
        state_file = e2e_dir / "state.json"
        state = {
            "task_id": task.id,
            "iteration": 0,
            "total_bugs_found": 0,
            "total_bugs_fixed": 0,
            "history": [],
        }
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
            except (json.JSONDecodeError, KeyError):
                pass

        iteration = state.get("iteration", 0)
        consecutive_explore_failures = 0
        MAX_CONSECUTIVE_EXPLORE_FAILURES = 3
        e2e_loop_succeeded = False
        fix_agent_ran = False

        # ── Pre-loop: rejection research ──
        # If a prior attempt was rejected by the verifier, spawn a research
        # agent to investigate the specific blockers BEFORE re-running the
        # explore loop.  This gives the next explore agent concrete solutions
        # instead of blindly retrying the same approach.
        rejection_path = Path(spec_dir) / "claims" / f"rejection-{task.id}.md"
        if rejection_path.exists():
            rejection_text = rejection_path.read_text()
            e2e_log(f"Prior attempt rejected — spawning rejection-research agent")
            research_prompt = f"""A previous E2E exploration agent completed task {task.id}, but the verifier rejected it. Your job is to investigate the specific blockers and produce actionable fixes.

## Rejection details

```
{rejection_text}
```

## What to do

1. Read the rejection carefully — identify each specific blocker.
2. For each blocker, investigate the root cause:
   - If it's an environment issue (e.g. emulator auth token, fingerprint simulation), find the fix and apply it.
   - If it's a missing test, write the test.
   - If it's a code issue, fix the code.
3. Write a summary of what you fixed to `{e2e_dir}/rejection-fixes.md`.
4. If any blocker is genuinely unfixable, explain why in the summary.

## Important

- You have access to the codebase, adb, and the emulator (if running).
- Focus on making the NEXT explore agent succeed — remove the obstacles.
- Do NOT mark the task as done or write completion claims.
"""
            research_task = Task(
                id=f"E2E-rejection-research-{task.id}",
                description=f"Research rejection blockers for {task.id}",
                phase=task.phase, parallel=False,
                status=TaskStatus.RUNNING, line_num=0,
            )
            _wait_for_subagent(research_task, research_prompt,
                               f"E2E-rejection-research-{task.id}")
            e2e_log("Rejection research complete")

        # ── Main loop ──
        while not self._shutdown.is_set():
            iteration += 1
            e2e_log(f"=== E2E iteration {iteration} ===")

            # ── Supervisor check every N iterations ──
            if iteration > 1 and (iteration - 1) % SUPERVISOR_INTERVAL == 0:
                e2e_log(f"Supervisor check at iteration {iteration}")
                supervisor_prompt = self._build_e2e_supervisor_prompt(
                    spec_dir, e2e_dir, state, ui_flow_content
                )
                sup_task = Task(
                    id=f"E2E-supervisor-{iteration}",
                    description=f"E2E supervisor check at iteration {iteration}",
                    phase=task.phase, parallel=False,
                    status=TaskStatus.RUNNING, line_num=0,
                )
                _wait_for_subagent(sup_task, supervisor_prompt, f"E2E-supervisor-{iteration}")

                # Read supervisor decision
                decision_file = e2e_dir / "supervisor-decision.md"
                if decision_file.exists():
                    decision = decision_file.read_text()
                    if "STOP" in decision.upper() and "HUMAN" in decision.upper():
                        e2e_log("Supervisor says: STOP — human intervention needed")
                        self.blocked_file.write_text(
                            f"# BLOCKED: {task.id} — E2E supervisor requested human review\n\n"
                            f"{decision}\n\n"
                            f"## Context\n\nFindings: `{findings_file}`\nLogs: `{e2e_dir}/`\n"
                        )
                        break
                    elif "STOP" in decision.upper():
                        e2e_log("Supervisor says: STOP — checking MCP engagement before accepting")
                        # Verify the explore agent actually used MCP tools
                        # before accepting the supervisor's STOP verdict.
                        if findings_file.exists():
                            try:
                                sup_findings = json.loads(findings_file.read_text())
                                sup_driver = _pick_driver(mcp_caps)
                                sup_live = sup_driver.has_live_evidence(sup_findings, None) if sup_driver else 0
                                if sup_live > 0:
                                    e2e_log(f"MCP engagement confirmed ({sup_live} live findings) — accepting STOP")
                                    e2e_loop_succeeded = True
                                else:
                                    e2e_log("MCP engagement check FAILED — no live evidence despite supervisor STOP")
                            except json.JSONDecodeError:
                                e2e_log("Could not parse findings — rejecting supervisor STOP")
                        break
                    else:
                        e2e_log(f"Supervisor says: CONTINUE")
                        # Supervisor may have written guidance to e2e_dir/guidance.md

            # ── Phase 0: App health check ──────────────────────────
            # Before exploring, verify the app is alive. If it crashes
            # on startup, spawn a fix agent with the crash log instead
            # of wasting an explore agent on a dead app.
            APP_CRASH_FIX_MAX = 5
            app_healthy = False
            for crash_fix_attempt in range(APP_CRASH_FIX_MAX):
                # Launch the app and check if it survives 5 seconds
                app_package = None
                for cap in mcp_caps:
                    if cap == "mcp-android":
                        app_package = self._platform_manager._detect_android_package(project_dir)
                        break
                if not app_package:
                    e2e_log("Could not detect app package — skipping health check")
                    app_healthy = True
                    break

                # Launch the app
                subprocess.run(
                    f"adb -s emulator-5554 shell am start -n {app_package}/.MainActivity "
                    f"--activity-clear-task",
                    shell=True, capture_output=True, timeout=15,
                )
                time.sleep(5)

                # Check if the process is alive
                pid_result = subprocess.run(
                    f"adb -s emulator-5554 shell pidof {app_package}",
                    shell=True, capture_output=True, text=True, timeout=10,
                )
                if pid_result.returncode == 0 and pid_result.stdout.strip():
                    e2e_log(f"App health check: alive (pid {pid_result.stdout.strip()})")
                    app_healthy = True
                    break

                # App crashed — pull the crash log
                e2e_log(f"App health check: CRASHED (attempt {crash_fix_attempt + 1}/{APP_CRASH_FIX_MAX})")
                crash_log_result = subprocess.run(
                    "adb -s emulator-5554 logcat -d -t 200 '*:E' 2>/dev/null",
                    shell=True, capture_output=True, text=True, timeout=15,
                )
                crash_lines = crash_log_result.stdout if crash_log_result.returncode == 0 else "(could not read logcat)"
                # Filter to relevant lines
                relevant = "\n".join(
                    l for l in crash_lines.splitlines()
                    if any(k in l.lower() for k in ["panic", "fatal", "crash", "exception", app_package.lower(), "go  :", "runtime"])
                )
                if not relevant:
                    relevant = crash_lines[-3000:]  # last 3KB as fallback

                crash_log_file = e2e_dir / f"app-crash-{iteration}-{crash_fix_attempt}.log"
                crash_log_file.write_text(relevant)

                # Spawn a fix agent with the crash log
                crash_fix_prompt = f"""The Android app is crashing on startup. Fix the crash so the app can launch.

## Crash log (from adb logcat)

```
{relevant[:5000]}
```

The crash log is also saved at `{crash_log_file}`.

## What to do

1. Read the crash log to identify the panic/exception.
2. Read the source files involved (likely in `pkg/tsbridge/`, `android/app/src/main/java/com/nixkey/`).
3. Fix the root cause. Common Android/gomobile crash causes:
   - Go panic in AAR code (look for "panic:" in logcat with tag "Go")
   - Missing directory permissions (app data dir not writable)
   - Hilt/DI initialization failure
   - Missing native library
4. If you modified Go code in `pkg/`, the AAR needs to be rebuilt.
   Do NOT run `make android-apk` yourself — the runner handles rebuilds.
   Just fix the source code and note what you changed.
5. If you modified Kotlin/Android code, just fix the source files.

## Rules
- Fix the crash. That's it.
- Do not refactor unrelated code.
- Do not modify test files.
- In your final response, state what you fixed and whether Go code was changed
  (so the runner knows to rebuild the AAR).
"""
                crash_fix_task = Task(
                    id=f"E2E-crash-fix-{iteration}-{crash_fix_attempt}",
                    description=f"Fix app startup crash (attempt {crash_fix_attempt + 1})",
                    phase=task.phase, parallel=False,
                    status=TaskStatus.RUNNING, line_num=0,
                )
                _wait_for_subagent(crash_fix_task, crash_fix_prompt,
                                   f"E2E-crash-fix-{iteration}-{crash_fix_attempt}",
                                   model="opus")

                # Rebuild and reinstall after fix
                e2e_log("Rebuilding after crash fix...")
                for cap in mcp_caps:
                    build_log = e2e_dir / f"build-crash-fix-{iteration}-{crash_fix_attempt}.log"
                    build_result = self._platform_manager.build_and_install(cap, project_dir, build_log)
                    if build_result != BuildResult.OK:
                        e2e_log(f"Rebuild failed after crash fix — entering build-fix loop")
                        # Use existing build-fix loop logic
                        break

                # Clear logcat for next attempt
                subprocess.run("adb -s emulator-5554 logcat -c", shell=True, timeout=5)

            if not app_healthy:
                e2e_log(f"App still crashing after {APP_CRASH_FIX_MAX} fix attempts — BLOCKED")
                self.blocked_file.write_text(
                    f"# BLOCKED: {task.id} — app crashes on startup\n\n"
                    f"The app crashed on every launch attempt ({APP_CRASH_FIX_MAX} "
                    f"fix cycles). See crash logs in `{e2e_dir}/`.\n\n"
                    f"## Latest crash log\n\n```\n{relevant[:2000]}\n```\n"
                )
                task.status = TaskStatus.FAILED
                if hasattr(self, '_platform_manager'):
                    self._platform_manager.teardown_all(
                        project_dir=Path(spec_dir).parent if spec_dir else None)
                return

            # ── Resume check: skip explore if prior-run research is unfinished ──
            # If findings.json already has open bugs and at least one lacks a
            # research file, we were killed mid-cycle. Skip explore and let
            # the existing research phase pick up only the un-researched bugs.
            # This preserves research work already done for other bugs.
            skipped_explore_for_resume = False
            if findings_file.exists():
                try:
                    prior_findings = json.loads(findings_file.read_text())
                    prior_open = [
                        f for f in prior_findings.get("findings", [])
                        if f.get("status") in ("new", "verified_broken")
                    ]
                    prior_missing_research = [
                        b for b in prior_open
                        if b.get("id") and _read_latest_research(e2e_dir, b["id"])[1] == 0
                    ]
                    if prior_open and prior_missing_research:
                        e2e_log(
                            f"RESUME: {len(prior_open)} open bugs from prior run, "
                            f"{len(prior_missing_research)} lack research — "
                            f"skipping explore, resuming at research phase"
                        )
                        findings = prior_findings
                        skipped_explore_for_resume = True
                except (json.JSONDecodeError, OSError):
                    pass

            # ── Phase 1: EXPLORE — planner (Opus) → executor loop (Sonnet) ──
            # Planner writes plan.md. Executor walks it, writing findings
            # incrementally. On blocker, Opus diagnostic writes unblock;
            # executor retries. Up to EXECUTOR_MAX_SPAWNS_PER_ITER respawns.
            if skipped_explore_for_resume:
                e2e_log(f"Phase 1: Explore SKIPPED (resume)")
            else:
                e2e_log(f"Phase 1: Explore (planner + executor loop)")
            explore_exit = 0
            if not skipped_explore_for_resume:
                try:
                    task_block = _extract_task_block(str(task_file), task.id)
                except Exception as exc:
                    import traceback
                    e2e_log(f"DEBUG: task_block extract FAILED: {exc}")
                    e2e_log(f"DEBUG: {traceback.format_exc()}")
                    break

                # Clean up stale exit files from prior iteration
                exec_d = _executor_dir(e2e_dir)
                for stale in (exec_d / "handoff.md", exec_d / "blocker.md",
                              e2e_dir / "plan.md"):
                    if stale.exists():
                        stale.unlink()

                # ── Phase 1a: Planner (Opus) ──
                try:
                    planner_prompt = self._build_e2e_planner_prompt(
                        spec_dir, findings_file, ui_flow_content, spec_content,
                        iteration, e2e_dir, task, task_block,
                    )
                except Exception as exc:
                    import traceback
                    e2e_log(f"DEBUG: planner prompt build FAILED: {exc}")
                    e2e_log(f"DEBUG: {traceback.format_exc()}")
                    break

                planner_task = Task(
                    id=f"E2E-planner-{iteration}",
                    description=f"E2E planner iteration {iteration}",
                    phase=task.phase, parallel=False,
                    status=TaskStatus.RUNNING, line_num=0,
                    capabilities=set(),  # no MCP for planner
                )
                try:
                    planner_exit = _wait_for_subagent(
                        planner_task, planner_prompt,
                        f"E2E-planner-{iteration}",
                        model="opus")
                    e2e_log(f"Planner exit={planner_exit}")
                except Exception as exc:
                    import traceback
                    e2e_log(f"Planner spawn FAILED: {exc}")
                    e2e_log(f"DEBUG: {traceback.format_exc()}")
                    break

                plan_file = e2e_dir / "plan.md"
                if not plan_file.exists() or not plan_file.read_text().strip():
                    e2e_log("Planner did not produce plan.md — treating as explore failure")
                    explore_exit = 1
                else:
                    # ── Phase 1b: Executor loop (Sonnet) ──
                    prior_handoff = ""
                    prior_handoff_path: Path | None = None
                    unblock_context = ""
                    explore_exit = 0
                    for spawn_num in range(1, EXECUTOR_MAX_SPAWNS_PER_ITER + 1):
                        try:
                            executor_prompt = self._build_e2e_executor_prompt(
                                spec_dir, findings_file, ui_flow_content,
                                e2e_dir, iteration, spawn_num,
                                prior_handoff=prior_handoff,
                                prior_handoff_path=prior_handoff_path,
                                unblock_context=unblock_context,
                                mcp_caps=mcp_caps,
                            )
                        except Exception as exc:
                            import traceback
                            e2e_log(f"Executor prompt build FAILED: {exc}")
                            e2e_log(f"DEBUG: {traceback.format_exc()}")
                            explore_exit = 1
                            break

                        executor_task = Task(
                            id=f"E2E-executor-{iteration}-{spawn_num}",
                            description=f"E2E executor iter {iteration} spawn {spawn_num}",
                            phase=task.phase, parallel=False,
                            status=TaskStatus.RUNNING, line_num=0,
                            capabilities=mcp_caps,
                        )
                        try:
                            exec_exit = _wait_for_subagent(
                                executor_task, executor_prompt,
                                f"E2E-executor-{iteration}-{spawn_num}",
                                mcp_configs=mcp_config_paths,
                                model="sonnet")
                        except Exception as exc:
                            import traceback
                            e2e_log(f"Executor spawn FAILED: {exc}")
                            e2e_log(f"DEBUG: {traceback.format_exc()}")
                            explore_exit = 1
                            break

                        # Reset unblock_context — it's only for the spawn after a diagnostic
                        unblock_context = ""

                        exec_dir_p = _executor_dir(e2e_dir)
                        handoff_p = exec_dir_p / "handoff.md"
                        blocker_p = exec_dir_p / "blocker.md"

                        if blocker_p.exists():
                            blocker_content = blocker_p.read_text()
                            # Extract step_id — first line matching "Blocked step: step-N"
                            step_id = "unknown"
                            for line in blocker_content.splitlines():
                                if "Blocked step:" in line:
                                    step_id = line.split("Blocked step:", 1)[1].strip().split()[0]
                                    break
                            e2e_log(f"Executor {spawn_num} BLOCKED on {step_id}")

                            # Persist the blocker into its step dir
                            step_dir = _blocker_step_dir(e2e_dir, step_id)
                            blocker_attempt = _count_blocker_attempts(e2e_dir, step_id) + 1
                            (step_dir / f"blocker-{blocker_attempt}.md").write_text(blocker_content)

                            # Write mechanical executor summary for lazy-loading
                            exec_log_p = self.log_dir / f"agent-{self.agent_counter}-E2E-executor-{iteration}-{spawn_num}-{self.timestamp}.jsonl"
                            _write_executor_summary(e2e_dir, step_id, blocker_attempt, exec_log_p)

                            blocker_p.unlink()  # consume

                            if blocker_attempt > BLOCKER_MAX_RETRIES_PER_STEP:
                                e2e_log(f"Step {step_id} exceeded {BLOCKER_MAX_RETRIES_PER_STEP} blocker retries — giving up on step, ending iteration")
                                break

                            # Spawn Opus diagnostic
                            plan_content = plan_file.read_text()
                            prior_unblocks = _list_prior_unblocks(e2e_dir, step_id)
                            prior_summaries = _list_prior_executor_attempts(e2e_dir, step_id)
                            try:
                                diag_prompt = self._build_e2e_diagnostic_prompt(
                                    e2e_dir, step_id, blocker_content, plan_content,
                                    ui_flow_content, prior_unblocks, prior_summaries,
                                    blocker_attempt,
                                )
                            except Exception as exc:
                                import traceback
                                e2e_log(f"Diagnostic prompt build FAILED: {exc}")
                                e2e_log(f"DEBUG: {traceback.format_exc()}")
                                break

                            diag_task = Task(
                                id=f"E2E-diagnostic-{iteration}-{spawn_num}",
                                description=f"E2E diagnostic iter {iteration} step {step_id} attempt {blocker_attempt}",
                                phase=task.phase, parallel=False,
                                status=TaskStatus.RUNNING, line_num=0,
                                capabilities=set(),
                            )
                            try:
                                _wait_for_subagent(
                                    diag_task, diag_prompt,
                                    f"E2E-diagnostic-{iteration}-{spawn_num}",
                                    model="opus")
                            except Exception as exc:
                                import traceback
                                e2e_log(f"Diagnostic spawn FAILED: {exc}")
                                e2e_log(f"DEBUG: {traceback.format_exc()}")
                                break

                            unblock_file = step_dir / f"unblock-{blocker_attempt}.md"
                            if unblock_file.exists():
                                unblock_context = unblock_file.read_text()
                            else:
                                e2e_log(f"Diagnostic did not produce unblock file — skipping step {step_id}")
                                # Continue to next spawn without unblock; executor will move past the step

                            # Loop back — next spawn retries the step with unblock inline
                            continue

                        if handoff_p.exists():
                            handoff_content = handoff_p.read_text()
                            if "Status: COMPLETE" in handoff_content:
                                e2e_log(f"Executor {spawn_num} completed plan")
                                break
                            # PARTIAL — hand off to next spawn
                            # Archive so next spawn can reference path
                            archive_p = exec_dir_p / f"handoff-spawn-{spawn_num}.md"
                            archive_p.write_text(handoff_content)
                            prior_handoff = handoff_content
                            prior_handoff_path = archive_p
                            handoff_p.unlink()
                            e2e_log(f"Executor {spawn_num} PARTIAL — continuing")
                            continue

                        # Neither file — treat as a crash
                        e2e_log(f"Executor {spawn_num} exited without handoff/blocker (exit {exec_exit})")
                        explore_exit = exec_exit if exec_exit != 0 else 1
                        break
                    else:
                        e2e_log(f"Executor loop hit max spawns ({EXECUTOR_MAX_SPAWNS_PER_ITER}) — ending iteration")

            # ── Overload detection is handled at the per-spawn level inside
            # the executor loop. The prior whole-phase retry relied on a single
            # explore_prompt; under the planner/executor split there's no
            # single prompt to replay. If 529s become common, add per-spawn
            # retry inside the executor loop instead.

            # ── Crash detection: non-zero exit → immediate supervisor ──
            if explore_exit != 0:
                e2e_log(f"Explore agent crashed (exit {explore_exit}) — invoking supervisor")
                # Collect stderr for the supervisor
                crash_stderr = ""
                explore_stderr_path = self.log_dir / f"agent-{self.agent_counter}-E2E-explore-{iteration}-{self.timestamp}.stderr"
                if explore_stderr_path.exists():
                    crash_stderr = explore_stderr_path.read_text()[-2000:]  # last 2KB

                # Also extract the JSONL result entry — it often has the real
                # error message (e.g. API errors) that doesn't appear in stderr
                crash_result_info = ""
                explore_log_path = self.log_dir / f"agent-{self.agent_counter}-E2E-explore-{iteration}-{self.timestamp}.jsonl"
                if explore_log_path.exists():
                    try:
                        # Read the last few lines to find the result entry
                        log_lines = explore_log_path.read_text().splitlines()
                        for raw_line in reversed(log_lines[-10:]):
                            raw_line = raw_line.strip()
                            if not raw_line:
                                continue
                            entry = json.loads(raw_line)
                            if entry.get("type") == "result":
                                crash_result_info = (
                                    f"Result message: {entry.get('result', '(none)')}\n"
                                    f"is_error: {entry.get('is_error', False)}\n"
                                    f"num_turns: {entry.get('num_turns', '?')}\n"
                                    f"duration_ms: {entry.get('duration_ms', '?')}\n"
                                    f"total_cost_usd: {entry.get('total_cost_usd', '?')}"
                                )
                                break
                            elif entry.get("type") == "assistant":
                                # Check for synthetic error messages
                                model = entry.get("message", {}).get("model", "")
                                if model == "<synthetic>":
                                    content = entry.get("message", {}).get("content", [])
                                    for block in content:
                                        if block.get("type") == "text":
                                            crash_result_info = f"Synthetic error: {block['text']}"
                                    break
                    except Exception:
                        pass  # Best-effort — don't crash the runner

                state["history"].append({
                    "iteration": iteration, "phase": "explore",
                    "result": "crash", "exit_code": explore_exit,
                    "stderr_tail": crash_stderr[:500],
                    "result_info": crash_result_info[:500],
                })
                state_file.write_text(json.dumps(state, indent=2))

                # Build a crash-specific supervisor prompt
                crash_supervisor_prompt = self._build_e2e_crash_supervisor_prompt(
                    spec_dir, e2e_dir, state, ui_flow_content,
                    explore_exit, crash_stderr, crash_result_info, iteration,
                )
                sup_task = Task(
                    id=f"E2E-crash-supervisor-{iteration}",
                    description=f"E2E crash supervisor after explore exit {explore_exit}",
                    phase=task.phase, parallel=False,
                    status=TaskStatus.RUNNING, line_num=0,
                )
                _wait_for_subagent(sup_task, crash_supervisor_prompt,
                                   f"E2E-crash-supervisor-{iteration}")

                # Read supervisor decision — same handling as periodic supervisor
                decision_file = e2e_dir / "supervisor-decision.md"
                if decision_file.exists():
                    decision = decision_file.read_text()
                    if "STOP" in decision.upper():
                        reason = "human intervention needed" if "HUMAN" in decision.upper() else "unrecoverable"
                        e2e_log(f"Crash supervisor says: STOP — {reason}")
                        self.blocked_file.write_text(
                            f"# BLOCKED: {task.id} — explore agent crashed\n\n"
                            f"{decision}\n\n"
                            f"## Crash details\n\n"
                            f"Exit code: {explore_exit}\n"
                            f"```\n{crash_stderr[-1000:]}\n```\n"
                        )
                        break
                    else:
                        e2e_log("Crash supervisor says: CONTINUE (retrying)")
                        continue
                else:
                    # Supervisor didn't write a decision — treat as stop
                    e2e_log("Crash supervisor produced no decision — stopping")
                    break

            # Read findings (explore exited 0 but may not have produced output).
            # Skipped when resuming — `findings` was already loaded from prior_findings.
            if not skipped_explore_for_resume:
                if not findings_file.exists():
                    e2e_log("No findings file produced — explore agent may have failed")
                    consecutive_explore_failures += 1
                    state["history"].append({
                        "iteration": iteration, "phase": "explore",
                        "result": "no_findings",
                    })
                    state_file.write_text(json.dumps(state, indent=2))
                    if consecutive_explore_failures >= MAX_CONSECUTIVE_EXPLORE_FAILURES:
                        e2e_log(
                            f"Explore produced no findings {consecutive_explore_failures} "
                            f"consecutive times — stopping"
                        )
                        self.blocked_file.write_text(
                            f"# BLOCKED: {task.id} — explore agent not producing findings\n\n"
                            f"Explore agent exited 0 but produced no findings.json "
                            f"{consecutive_explore_failures} times in a row.\n"
                            f"Check agent logs in `{self.log_dir}/`\n"
                        )
                        break
                    continue

                try:
                    findings = json.loads(findings_file.read_text())
                except json.JSONDecodeError:
                    e2e_log("Invalid findings.json — skipping this iteration")
                    consecutive_explore_failures += 1
                    if consecutive_explore_failures >= MAX_CONSECUTIVE_EXPLORE_FAILURES:
                        e2e_log(f"Explore failed {consecutive_explore_failures} consecutive times — stopping")
                        break
                    continue

            # Reset on successful explore
            consecutive_explore_failures = 0

            # ── MCP engagement check ──
            # If this is an MCP task, verify the explore agent actually
            # interacted with the app via MCP tools (screenshots, clicks,
            # etc.) rather than falling back to code review.  An explore
            # agent that can't get past the first screen is blocked, not
            # done — no matter what it writes to findings.json.
            #
            # Dispatched through the PlatformDriver for this task so the
            # browser path counts `browser_*` calls, Android counts
            # `mcp__mcp-android__*`, and iOS can be plugged in without
            # editing this site.
            driver = _pick_driver(mcp_caps)
            explore_log = self.log_dir / f"agent-{self.agent_counter}-E2E-explore-{iteration}-{self.timestamp}.jsonl"
            if driver is not None:
                live_evidence = driver.has_live_evidence(findings, explore_log)
            else:
                live_evidence = 0
            all_entries = (findings.get("findings") or []) + (findings.get("validations") or [])
            blocked_findings = sum(1 for f in all_entries if f.get("status") == "blocked")
            total_findings = len(all_entries)

            # On resume, the current-iteration log doesn't exist, so live_evidence
            # will be 0 even for valid prior findings. The original run already
            # passed this check (otherwise no research files would exist), so skip.
            if live_evidence == 0 and not skipped_explore_for_resume:
                cap_label = driver.capability if driver else "unknown"
                mcp_status = driver.read_mcp_init_status(explore_log) if driver else None
                status_note = (
                    f" (MCP server `{cap_label}` init status: **{mcp_status}**)"
                    if mcp_status else ""
                )
                e2e_log(
                    f"MCP engagement check FAILED ({cap_label}){status_note}: "
                    f"{total_findings} findings, 0 with live evidence "
                    f"(screenshots or live-mcp verification). "
                    f"{blocked_findings} blocked."
                )
                status_line = (
                    f"MCP server `{cap_label}` init status reported by agent: **{mcp_status}**.\n\n"
                    if mcp_status else ""
                )
                self.blocked_file.write_text(
                    f"# BLOCKED: {task.id} — explore agent produced no live evidence\n\n"
                    f"Platform: `{cap_label}`. {status_line}"
                    f"The explore agent produced {total_findings} findings with "
                    f"0 screenshots and 0 `{driver.tool_prefix if driver else 'mcp__'}*` "
                    f"tool calls in its log. {blocked_findings} findings marked "
                    f"'blocked'.\n\n"
                    f"This means the agent did not interact with the app via MCP "
                    f"(no screenshots taken, no UI elements tapped). "
                    f"Code review alone does not satisfy E2E validation.\n\n"
                    f"## Likely causes\n\n"
                    f"- MCP server for `{cap_label}` failed to connect (check the "
                    f"  agent log's `mcp_servers` init block for `status: failed`)\n"
                    f"- App/site crashed on startup (check platform-specific logs)\n"
                    f"- Runtime not ready (emulator not booted / browser process "
                    f"  not launched / simulator not booted)\n"
                    f"- Agent ignored MCP tools and only read source code\n\n"
                    f"## To unblock\n\n"
                    f"Check the explore agent's log in `logs/` to see what it "
                    f"actually did. Fix the root cause, delete this file, then re-run.\n"
                )
                task.status = TaskStatus.FAILED
                if hasattr(self, '_platform_manager'):
                    self._platform_manager.teardown_all(
                        project_dir=Path(spec_dir).parent if spec_dir else None)
                return

            open_bugs = [f for f in findings.get("findings", [])
                         if f.get("status") in ("new", "verified_broken")]
            e2e_log(f"Open bugs: {len(open_bugs)}")

            if not open_bugs:
                e2e_log("No open bugs found — E2E exploration complete!")
                state["history"].append({
                    "iteration": iteration, "phase": "explore",
                    "result": "clean", "open_bugs": 0,
                })
                state_file.write_text(json.dumps(state, indent=2))
                e2e_loop_succeeded = True
                break

            state["total_bugs_found"] = len(findings.get("findings", []))

            # ── Phase 1.5: RESEARCH new bugs ──
            # For any bug that doesn't have a research file yet, spawn a research
            # agent to investigate before the fix agent runs.
            new_bugs_needing_research = []
            for bug in open_bugs:
                bug_id = bug.get("id", "")
                if not bug_id:
                    continue
                _, research_idx = _read_latest_research(e2e_dir, bug_id)
                if research_idx == 0:  # No research yet
                    new_bugs_needing_research.append(bug)

            if new_bugs_needing_research:
                e2e_log(
                    f"Phase 1.5: Research ({len(new_bugs_needing_research)} new bugs, "
                    f"up to 10 in parallel)"
                )
                research_items = []
                for bug in new_bugs_needing_research:
                    bug_id = bug["id"]
                    e2e_log(f"  Researching {bug_id}: {bug.get('summary', '')[:60]}")
                    research_prompt = self._build_e2e_research_prompt(
                        bug, e2e_dir, spec_dir, ui_flow_content
                    )
                    research_task = Task(
                        id=f"E2E-research-{bug_id}-{iteration}",
                        description=f"Research {bug_id}",
                        phase=task.phase, parallel=False,
                        status=TaskStatus.RUNNING, line_num=0,
                    )
                    research_items.append((
                        research_task, research_prompt,
                        f"E2E-research-{bug_id}-{iteration}",
                    ))
                _wait_for_subagents_parallel(research_items, max_concurrency=10)

            # ── Per-bug supervisor check ──
            # For bugs that have hit 3+ fix attempts since last supervisor,
            # run the bug supervisor before the fix agent.
            MAX_FIX_ATTEMPTS_BEFORE_SUPERVISOR = 3
            MAX_SUPERVISOR_RUNS = 5
            bugs_to_escalate = []
            bugs_for_fix = list(open_bugs)  # start with all open bugs

            for bug in open_bugs:
                bug_id = bug.get("id", "")
                if not bug_id:
                    continue
                history = _read_bug_history(e2e_dir, bug_id)
                total_attempts = _count_fix_attempts(history)
                sup_runs = history.get("supervisor_runs", 0)

                # Calculate attempts since last supervisor
                # Each supervisor resets the counter (supervisor fires after 3,
                # then 1 more attempt per supervisor cycle)
                if sup_runs == 0:
                    attempts_since_sup = total_attempts
                    threshold = MAX_FIX_ATTEMPTS_BEFORE_SUPERVISOR
                else:
                    # After first supervisor, only 1 attempt per cycle
                    attempts_since_sup = total_attempts - (MAX_FIX_ATTEMPTS_BEFORE_SUPERVISOR + sup_runs)
                    threshold = 1

                if attempts_since_sup >= threshold and total_attempts > 0:
                    if sup_runs >= MAX_SUPERVISOR_RUNS:
                        # Exhausted all supervisor runs — escalate
                        e2e_log(f"  {bug_id}: {sup_runs} supervisor runs exhausted — escalating")
                        bugs_to_escalate.append(bug)
                        bugs_for_fix = [b for b in bugs_for_fix if b.get("id") != bug_id]
                        continue

                    e2e_log(f"  {bug_id}: {total_attempts} fix attempts, running supervisor #{sup_runs + 1}")
                    sup_prompt = self._build_e2e_bug_supervisor_prompt(
                        bug, e2e_dir, ui_flow_content
                    )
                    sup_task = Task(
                        id=f"E2E-bug-supervisor-{bug_id}-{iteration}",
                        description=f"Supervisor for {bug_id} (run #{sup_runs + 1})",
                        phase=task.phase, parallel=False,
                        status=TaskStatus.RUNNING, line_num=0,
                    )
                    _wait_for_subagent(sup_task, sup_prompt,
                                       f"E2E-bug-supervisor-{bug_id}-{iteration}")

                    # Update supervisor run count
                    history["supervisor_runs"] = sup_runs + 1
                    _write_bug_history(e2e_dir, bug_id, history)

                    # Read the supervisor's decision
                    bug_d = _bug_dir(e2e_dir, bug_id)
                    decision_file = bug_d / f"supervisor-{sup_runs + 1}-decision.md"
                    if decision_file.exists():
                        decision = decision_file.read_text()
                        if "ESCALATE" in decision.upper():
                            # Determine category from decision
                            category = "code"
                            for cat in ("spec", "infra"):
                                if cat in decision.lower():
                                    category = cat
                                    break
                            bugs_to_escalate.append(bug)
                            bugs_for_fix = [b for b in bugs_for_fix if b.get("id") != bug_id]
                            e2e_log(f"  {bug_id}: supervisor says ESCALATE ({category})")
                        elif "REDIRECT_RESEARCH" in decision.upper():
                            e2e_log(f"  {bug_id}: supervisor says REDIRECT_RESEARCH")
                            # Extract the research directive from the decision
                            research_prompt = self._build_e2e_research_prompt(
                                bug, e2e_dir, spec_dir, ui_flow_content,
                                supervisor_directive=decision,
                            )
                            research_task = Task(
                                id=f"E2E-research-{bug_id}-sup{sup_runs + 1}",
                                description=f"Redirected research for {bug_id}",
                                phase=task.phase, parallel=False,
                                status=TaskStatus.RUNNING, line_num=0,
                            )
                            _wait_for_subagent(research_task, research_prompt,
                                               f"E2E-research-{bug_id}-sup{sup_runs + 1}")
                        else:
                            # DIRECT_FIX — supervisor guidance will be included in fix prompt
                            e2e_log(f"  {bug_id}: supervisor says DIRECT_FIX")

            # ── Escalation for exhausted bugs ──
            for bug in bugs_to_escalate:
                bug_id = bug.get("id", "")
                history = _read_bug_history(e2e_dir, bug_id)

                # Determine category from latest supervisor decision
                sup_runs = history.get("supervisor_runs", 0)
                category = "code"
                if sup_runs > 0:
                    bug_d = _bug_dir(e2e_dir, bug_id)
                    latest_decision = bug_d / f"supervisor-{sup_runs}-decision.md"
                    if latest_decision.exists():
                        dec_text = latest_decision.read_text().lower()
                        for cat in ("spec", "infra"):
                            if cat in dec_text:
                                category = cat
                                break

                e2e_log(f"  Escalating {bug_id} (category: {category})")
                esc_prompt = self._build_e2e_escalation_prompt(bug, e2e_dir, category)
                esc_task = Task(
                    id=f"E2E-escalate-{bug_id}",
                    description=f"Escalate {bug_id}",
                    phase=task.phase, parallel=False,
                    status=TaskStatus.RUNNING, line_num=0,
                )
                _wait_for_subagent(esc_task, esc_prompt, f"E2E-escalate-{bug_id}")

                # Update findings status to wont_fix for escalated bugs
                try:
                    current_findings = json.loads(findings_file.read_text())
                    for f in current_findings.get("findings", []):
                        if f.get("id") == bug_id:
                            f["status"] = "wont_fix"
                            f["escalation_category"] = category
                            f["bug_dir"] = str(_bug_dir(e2e_dir, bug_id))
                    findings_file.write_text(json.dumps(current_findings, indent=2))
                except (json.JSONDecodeError, OSError):
                    pass

            # Refresh open bugs list after escalations
            if bugs_to_escalate:
                open_bugs = [b for b in open_bugs if b.get("id") not in
                             {eb.get("id") for eb in bugs_to_escalate}]
                if not open_bugs:
                    e2e_log("All remaining bugs escalated — no fixable bugs left")
                    state["history"].append({
                        "iteration": iteration,
                        "result": "all_escalated",
                        "escalated": [b.get("id") for b in bugs_to_escalate],
                    })
                    state_file.write_text(json.dumps(state, indent=2))
                    break

            # ── Phase 2: FIX (no MCP needed) ──
            fix_agent_ran = True
            e2e_log(f"Phase 2: Fix ({len(open_bugs)} bugs)")

            # Snapshot HEAD before fix agent runs so we can detect if it changed anything
            pre_fix_head = ""
            try:
                git_cwd = str(Path(spec_dir).parent) if spec_dir else None
                pre_fix_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True, text=True, timeout=10, cwd=git_cwd,
                )
                pre_fix_head = pre_fix_result.stdout.strip()
            except Exception:
                pass

            fix_prompt = self._build_e2e_fix_prompt(
                spec_dir, findings_file, open_bugs, learnings_file,
                e2e_dir=e2e_dir,
                mcp_caps=mcp_caps,
            )
            fix_task = Task(
                id=f"E2E-fix-{iteration}",
                description=f"E2E fix iteration {iteration} ({len(open_bugs)} bugs)",
                phase=task.phase, parallel=False,
                status=TaskStatus.RUNNING, line_num=0,
            )
            _wait_for_subagent(fix_task, fix_prompt, f"E2E-fix-{iteration}")

            # ── Check if fix agent actually changed anything ──
            # Compare current HEAD and working tree against the commit before fix ran
            try:
                git_cwd = str(Path(spec_dir).parent) if spec_dir else None
                # Check for uncommitted changes (staged or unstaged)
                diff_result = subprocess.run(
                    ["git", "diff", "--stat", "HEAD"],
                    capture_output=True, text=True, timeout=10, cwd=git_cwd,
                )
                has_changes = bool(diff_result.stdout.strip())
                # Check if fix agent made new commits (compare HEAD to pre-fix snapshot)
                if not has_changes:
                    head_result = subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        capture_output=True, text=True, timeout=10, cwd=git_cwd,
                    )
                    has_changes = head_result.stdout.strip() != pre_fix_head
            except Exception:
                has_changes = True  # Assume changes on error — safe fallback

            if not has_changes:
                e2e_log("Fix agent made no code changes — skipping rebuild and verify")
                state["history"].append({
                    "iteration": iteration,
                    "bugs_found": len(open_bugs),
                    "bugs_fixed": 0,
                    "bugs_remaining": len(open_bugs),
                    "note": "fix agent made no changes",
                })
                state_file.write_text(json.dumps(state, indent=2))
                continue

            # ── Phase 3: Rebuild + reinstall (with build-fix loop) ──
            e2e_log("Phase 3: Rebuild and reinstall")
            BUILD_FIX_MAX_ATTEMPTS = 10
            INSTALL_RETRY_MAX = 2  # max emulator restart attempts for install failures
            rebuild_ok = True
            for cap in mcp_caps:
                build_log = e2e_dir / f"build-{cap.replace('mcp-', '')}-iter{iteration}.log"
                # Clear any previous build log for this iteration
                if build_log.exists():
                    build_log.unlink()

                result = self._platform_manager.build_and_install(cap, project_dir, build_log)
                if result == BuildResult.OK:
                    e2e_log(f"Rebuild succeeded for {cap}")
                    continue

                # ── Install failure → infrastructure recovery (no agent needed) ──
                if result == BuildResult.INSTALL_FAILED:
                    e2e_log(f"Install failed for {cap} — build succeeded but device unreachable, attempting runtime restart")
                    install_recovered = False
                    for retry in range(1, INSTALL_RETRY_MAX + 1):
                        e2e_log(f"  Install recovery attempt {retry}/{INSTALL_RETRY_MAX}: restarting {cap} runtime...")
                        if not self._platform_manager.restart_runtime(cap, project_dir):
                            e2e_log(f"  Runtime restart failed on attempt {retry}")
                            continue
                        # Runtime is back — retry install (build already succeeded)
                        if build_log.exists():
                            build_log.unlink()
                        retry_result = self._platform_manager.build_and_install(cap, project_dir, build_log)
                        if retry_result == BuildResult.OK:
                            e2e_log(f"  Install succeeded after runtime restart (attempt {retry})")
                            install_recovered = True
                            break
                        elif retry_result == BuildResult.BUILD_FAILED:
                            e2e_log(f"  Build now failing after runtime restart — falling through to build-fix loop")
                            result = BuildResult.BUILD_FAILED
                            break
                        else:
                            e2e_log(f"  Install still failing after restart attempt {retry}")

                    if install_recovered:
                        continue
                    if result == BuildResult.INSTALL_FAILED:
                        # All restart attempts exhausted
                        e2e_log(f"Install recovery exhausted ({INSTALL_RETRY_MAX} restart attempts) for {cap} — skipping verify")
                        rebuild_ok = False
                        continue

                # ── Build failure → code-fix loop (spawn agents) ──
                e2e_log(f"Build failed for {cap} — entering build-fix loop (up to {BUILD_FIX_MAX_ATTEMPTS} attempts)")
                build_fixed = False
                prev_fix_summaries: list[str] = []

                for attempt in range(1, BUILD_FIX_MAX_ATTEMPTS + 1):
                    e2e_log(f"  Build-fix attempt {attempt}/{BUILD_FIX_MAX_ATTEMPTS}")

                    # Spawn a fix agent with the build log path
                    prev_attempts_text = ""
                    if prev_fix_summaries:
                        prev_attempts_text = (
                            "\n## Previous fix attempts\n"
                            + "\n".join(f"- Attempt {i+1}: {s}" for i, s in enumerate(prev_fix_summaries))
                        )

                    build_fix_prompt = f"""You are fixing a build failure. The build command failed and the full output has been written to a log file.

## Build log file
`{build_log}`

## How to read the log
1. **Start by reading the last 300 lines** of the file — the error is usually near the end.
2. If the error references earlier output (e.g. "see above"), use Grep or Read with offset to find the relevant section.
3. Do NOT read the entire file at once — it may be very large.

## What to do
1. Read the tail of the build log to identify the error(s).
2. Read the source files referenced in the errors.
3. Fix ALL errors — grep the codebase for similar patterns and fix them in one pass.
4. Do NOT run the build command yourself — the runner will do that after you finish.
5. In your final response, state a one-line summary of what you changed.
{prev_attempts_text}

## Iteration
This is build-fix attempt {attempt} of {BUILD_FIX_MAX_ATTEMPTS}.
"""
                    bfix_task = Task(
                        id=f"E2E-build-fix-{iteration}-{attempt}",
                        description=f"Fix build failure (attempt {attempt})",
                        phase=task.phase, parallel=False,
                        status=TaskStatus.RUNNING, line_num=0,
                    )
                    bfix_exit = _wait_for_subagent(
                        bfix_task, build_fix_prompt,
                        f"E2E-build-fix-{iteration}-{attempt}",
                    )

                    # Read what the fix agent said it did (last line of its log)
                    bfix_log = self.log_dir / f"agent-{self.agent_counter}-{bfix_task.id}-{self.timestamp}.jsonl"
                    fix_summary = "(fix agent exited)"
                    if bfix_log.exists():
                        try:
                            lines, _, _, _ = read_stream_output(bfix_log, 0)
                            if lines:
                                fix_summary = lines[-1][:200]
                        except Exception:
                            pass
                    prev_fix_summaries.append(fix_summary)
                    e2e_log(f"  Build-fix {attempt}: {fix_summary}")

                    if bfix_exit != 0:
                        e2e_log(f"  Build-fix agent exited {bfix_exit} — continuing to retry build")

                    # Clear build log and retry build
                    if build_log.exists():
                        build_log.unlink()
                    retry_result = self._platform_manager.build_and_install(cap, project_dir, build_log)
                    if retry_result == BuildResult.OK:
                        e2e_log(f"  Build succeeded on attempt {attempt}")
                        build_fixed = True
                        break
                    elif retry_result == BuildResult.INSTALL_FAILED:
                        # Code fix resolved the build error but now install is broken
                        e2e_log(f"  Build now succeeds but install failed — attempting runtime restart")
                        if self._platform_manager.restart_runtime(cap, project_dir):
                            if build_log.exists():
                                build_log.unlink()
                            if self._platform_manager.build_and_install(cap, project_dir, build_log) == BuildResult.OK:
                                e2e_log(f"  Build succeeded after runtime restart on attempt {attempt}")
                                build_fixed = True
                                break
                        e2e_log(f"  Install still failing after runtime restart on attempt {attempt}")
                    else:
                        e2e_log(f"  Build still failing after attempt {attempt}")

                if not build_fixed:
                    e2e_log(f"Build-fix loop exhausted ({BUILD_FIX_MAX_ATTEMPTS} attempts) for {cap} — skipping verify")
                    rebuild_ok = False

            if not rebuild_ok:
                state["history"].append({
                    "iteration": iteration, "phase": "rebuild",
                    "result": "failed",
                    "note": f"Build-fix loop failed after {BUILD_FIX_MAX_ATTEMPTS} attempts",
                })
                state_file.write_text(json.dumps(state, indent=2))
                e2e_log("Rebuild failed — skipping verify, continuing to next iteration")
                continue

            # ── Phase 4: VERIFY (with MCP) ──
            e2e_log(f"Phase 4: Verify fixes")
            verify_prompt = self._build_e2e_verify_prompt(
                spec_dir, findings_file, ui_flow_content, e2e_dir,
                mcp_caps=mcp_caps,
            )
            verify_task = Task(
                id=f"E2E-verify-{iteration}",
                description=f"E2E verify iteration {iteration}",
                phase=task.phase, parallel=False,
                status=TaskStatus.RUNNING, line_num=0,
                capabilities=mcp_caps,
            )
            _wait_for_subagent(verify_task, verify_prompt,
                               f"E2E-verify-{iteration}",
                               mcp_configs=mcp_config_paths,
                               model="sonnet")

            # Re-read findings after verify
            try:
                findings = json.loads(findings_file.read_text())
            except json.JSONDecodeError:
                e2e_log("Invalid findings.json after verify")
                continue

            # ── Record per-bug fix attempts from verify evidence ──
            for finding in findings.get("findings", []):
                bug_id = finding.get("id", "")
                status = finding.get("status", "")
                if not bug_id:
                    continue
                # Only record for bugs we tried to fix this iteration
                if bug_id not in {b.get("id") for b in open_bugs}:
                    continue

                # Read the fix approach the fix agent wrote
                bug_d = _bug_dir(e2e_dir, bug_id)
                approach = "(no approach recorded)"
                approach_file = bug_d / "fix-approach-latest.md"
                if approach_file.exists():
                    approach = approach_file.read_text()[:500]

                # Read verify evidence
                evidence = "(no evidence recorded)"
                evidence_files = sorted(bug_d.glob(f"verify-evidence-*.md"))
                if evidence_files:
                    evidence = evidence_files[-1].read_text()[:1000]

                if status in ("verified_broken", "new"):
                    _record_fix_attempt(e2e_dir, bug_id, approach, "failed", evidence)
                elif status == "fixed":
                    _record_fix_attempt(e2e_dir, bug_id, approach, "fixed", evidence)

            # Phase 4.5 (instrumented test writing) omitted — the emulator
            # verify phase already confirms fixes; regression tests can be
            # batch-written after all E2E exploration is complete.

            still_open = [f for f in findings.get("findings", [])
                          if f.get("status") in ("new", "verified_broken")]
            fixed = [f for f in findings.get("findings", [])
                     if f.get("status") in ("fixed", "verified_fixed")]

            state["total_bugs_fixed"] = len(fixed)
            state["iteration"] = iteration
            state["history"].append({
                "iteration": iteration,
                "bugs_found": len(open_bugs),
                "bugs_fixed": len(fixed),
                "bugs_remaining": len(still_open),
            })
            state_file.write_text(json.dumps(state, indent=2))

            e2e_log(f"Iteration {iteration} complete: {len(fixed)} fixed, {len(still_open)} remaining")

            if not still_open:
                e2e_log("All bugs fixed — E2E loop complete!")
                e2e_loop_succeeded = True
                break

        # ── Check if explore loop actually succeeded ──
        # The loop exits via break for multiple reasons: all bugs fixed,
        # supervisor said stop, crash supervisor gave up, or prompt build failed.
        # Only run regression check and mark done if we actually had a successful run.
        e2e_succeeded = e2e_loop_succeeded

        if not e2e_succeeded:
            e2e_log("E2E loop did not complete successfully — task NOT marked done")
            task.status = TaskStatus.FAILED
            # Teardown platform runtimes and backend services
            if hasattr(self, '_platform_manager'):
                self._platform_manager.teardown_all(project_dir=Path(spec_dir).parent if spec_dir else None)
            return

        # ── Post-loop: full test suite validation ──
        # Only run regression check if the fix agent actually modified code.
        # Clean exploration passes (0 bugs) don't need regression checks.
        if not fix_agent_ran:
            e2e_log("No fixes applied — skipping regression check")
            # Read latest findings for the completion claim
            final_findings = None
            if findings_file.exists():
                try:
                    final_findings = json.loads(findings_file.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
            _write_e2e_completion_claim(spec_dir, task.id, e2e_dir, final_findings)
            _mark_task_done(task_file, task.id)
            if hasattr(self, '_platform_manager'):
                self._platform_manager.teardown_all(project_dir=Path(spec_dir).parent if spec_dir else None)
            return

        e2e_log("Phase 5: Post-E2E regression check — running full test suite")
        regression_prompt = self._build_e2e_regression_prompt(spec_dir, e2e_dir)
        regression_task = Task(
            id=f"E2E-regression-check",
            description="Post-E2E full test suite validation",
            phase=task.phase, parallel=False,
            status=TaskStatus.RUNNING, line_num=0,
        )
        regression_exit = _wait_for_subagent(
            regression_task, regression_prompt, "E2E-regression-check"
        )

        regression_passed = False
        if regression_exit != 0:
            e2e_log("Regression check agent failed (non-zero exit) — task NOT marked done")
        else:
            regression_report = e2e_dir / "regression-report.md"
            if regression_report.exists():
                report = regression_report.read_text()
                # Parse the ## Result section for structured verdict
                result_match = re.search(
                    r'##\s*Result\s*\n+(.+?)(?:\n\n|\n##|\Z)',
                    report, re.DOTALL
                )
                result_text = result_match.group(1).strip() if result_match else report
                # Check for explicit failure indicators
                fail_indicators = ["FAIL", "BROKEN", "REGRESSION", "STILL FAILING"]
                has_failure = any(ind in result_text.upper() for ind in fail_indicators)
                # Check for explicit pass indicators
                pass_indicators = ["ALL TESTS PASSED", "REGRESSIONS FIXED", "NO REGRESSIONS"]
                has_pass = any(ind in result_text.upper() for ind in pass_indicators)
                if has_failure and not has_pass:
                    e2e_log(f"Regression check: FAILED — {result_text[:200]}")
                elif has_pass:
                    e2e_log("Regression check: all tests passed")
                    regression_passed = True
                else:
                    e2e_log(f"Regression check: ambiguous result — {result_text[:200]}")
            else:
                e2e_log("Regression check: no report produced — task NOT marked done")

        if not regression_passed:
            e2e_log("Regression check did not pass — task NOT marked done")
            task.status = TaskStatus.FAILED
            if hasattr(self, '_platform_manager'):
                self._platform_manager.teardown_all(project_dir=Path(spec_dir).parent if spec_dir else None)
            return

        # Read latest findings for the completion claim
        final_findings = None
        if findings_file.exists():
            try:
                final_findings = json.loads(findings_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        _write_e2e_completion_claim(spec_dir, task.id, e2e_dir, final_findings)
        _mark_task_done(task_file, task.id)

        # Teardown platform runtimes and backend services
        if hasattr(self, '_platform_manager'):
            self._platform_manager.teardown_all(project_dir=Path(spec_dir).parent if spec_dir else None)

    def _build_e2e_explore_prompt(self, spec_dir: str, findings_file: Path,
                                   ui_flow: str, spec_content: str,
                                   iteration: int, e2e_dir: Path,
                                   parent_task: "Task | None" = None,
                                   task_block: str = "",
                                   mcp_caps: set[str] | None = None) -> str:
        """Build the prompt for the E2E explore agent.

        When parent_task and task_block are provided, the agent is scoped to
        just the screens/flows specified by that task.  Otherwise it falls
        back to a full-app sweep (legacy behaviour).
        """
        findings_inline, findings_overflow = _prepare_findings_context(
            findings_file, e2e_dir)

        guidance = ""
        guidance_file = e2e_dir / "guidance.md"
        if guidance_file.exists():
            guidance = guidance_file.read_text()

        progress_inline, progress_overflow = _prepare_progress_context(
            e2e_dir / "progress.md", e2e_dir)

        # Load backend service connection info if available
        backend_env = ""
        project_dir = Path.cwd()
        env_file = project_dir / "test" / "e2e" / ".state" / "env"
        if env_file.exists():
            backend_env = env_file.read_text()

        # ── Task-scoped vs full-sweep mission ──
        if parent_task and task_block:
            mission = f"""You are scoped to a single task. Focus ONLY on what this task requires — do not explore unrelated screens or flows.

## Your task

**{parent_task.id}**: {parent_task.description}

```
{task_block}
```

Validate every element, flow, and error path described in the task above. When the task says "Done when", those are your exit criteria. Once you have validated (or filed bugs for) every item, write your findings and stop."""
        else:
            mission = """Explore the running app systematically, comparing actual behavior against the specification. Find bugs in this run. Do not stop after finding one bug — keep exploring every screen, every flow, every edge case."""

        # ── Capability-specific tool + screenshot guidance ──
        # Dispatched through the PlatformDriver registry so adding iOS
        # (or any new platform) is a one-class change, not an edit here.
        driver = _pick_driver(mcp_caps or set())
        if driver is not None:
            tools_section = driver.tools_prompt_section(e2e_dir)
            screenshot_section = driver.screenshot_prompt_section(e2e_dir)
        else:
            tools_section = """## Available MCP tools

No platform-specific MCP capability was declared for this task. Read
the function schemas to see what tools are exposed. Do NOT fall back to
curl/wget/fetch to drive the app — if no UI-driving tools are available
stop and file a finding.
"""
            screenshot_section = ""

        # ── Include verification rejection from prior attempt ──
        rejection_context = ""
        if parent_task:
            rejection_path = Path(spec_dir) / "claims" / f"rejection-{parent_task.id}.md"
            if rejection_path.exists():
                rejection_text = rejection_path.read_text()
                rejection_context = f"""

## PREVIOUS ATTEMPT REJECTED BY VERIFIER

A previous agent completed this task, but the independent verifier rejected it. You MUST address every rejection reason below. Do NOT repeat the same approach that was rejected — solve the underlying blockers.

```
{rejection_text}
```

**Your priority is to fix the specific issues above.** If a blocker is environmental (e.g. emulator auth token missing for fingerprint simulation), investigate and fix the environment first, then proceed with the task. If you cannot fix it, file it as a BLOCKED bug with the root cause and what you tried.

"""

        return f"""You are an E2E exploration agent with access to MCP tools that let you interact with a running app.

## Your mission

{mission}
{rejection_context}
## CRITICAL: Context window management

You are running inside a context window with limited capacity. Accumulating too many screenshots will crash you mid-session. Follow these rules strictly:

1. **Prefer structured state (snapshot/hierarchy) over screenshots** for decisions — screenshots are useful for human review and bug evidence, not for tree traversal. For browser MCP, `browser_snapshot` is the cheap path; for Android MCP, prefer a no-vision `State-Tool` call and only add `use_vision` when you need to *see* something.
2. **Maximum 20 screenshots per session** — count them. Always save screenshots to disk (see your platform's section below) and reference paths in findings rather than re-reading images.
3. **Don't re-read screenshots you've already analyzed.**
4. **Write findings incrementally** — update `{findings_file}` after each screen/flow you complete, not just at the end. If you crash, the next agent can pick up from your partial findings.
5. **Write a progress checkpoint** — after completing each screen or flow, append a line to `{e2e_dir}/progress.md` noting what you covered (e.g., "Cart screen: validated add/remove, coupon errors"). The next iteration reads this to skip already-validated areas.
6. **If you're running low on context** (10+ screenshots or 100+ tool calls), write your current findings and progress immediately, then stop gracefully.

{tools_section}
{screenshot_section}
## How to explore

1. **Check progress first** — read `{e2e_dir}/progress.md` if it exists. Skip screens/flows already marked as validated.
2. Open the app using the platform's MCP tools (for browser: `browser_navigate` to the appropriate URL from the backend env; for Android: launch via `adb shell am start` or the intent helper).
3. **Inspect the current screen** using the cheapest structured tool available (`browser_snapshot` for web, `State-Tool` without vision for Android). Only take a screenshot when you need visual evidence or when the structured state is insufficient.
4. Compare what you see against the UI_FLOW.md specification below.
5. Try both happy paths AND error paths for each flow.
6. When you find a bug, document it with:
   - Steps to reproduce (exact tool calls and inputs)
   - Expected vs actual behavior
   - Screenshot path under `{e2e_dir}/screenshots/`
7. **Update findings and progress files after each screen.**
8. Navigate to the next screen/flow and repeat.
9. **NEVER run interactive or long-lived commands** via Bash (e.g. `nix-key pair`, `nix-key daemon`, servers, watchers). These hang forever and block the entire session. Always set `"timeout": 10000` (10s) on any Bash call. If you need to test a CLI command, use a non-interactive flag or just verify the binary exists.

## Flows to test (from UI_FLOW.md)

<ui_flow>
{ui_flow}
</ui_flow>

## Specification context (key requirements)

<spec>
{spec_content}
</spec>

{f'''## Supervisor guidance

The supervisor has provided the following guidance for this iteration:

<guidance>
{guidance}
</guidance>
''' if guidance else ''}

{f'''## Previous exploration progress

These screens/flows have already been validated by previous iterations. **Skip them** unless you have reason to believe they regressed:

<progress>
{progress_inline}
</progress>
{progress_overflow}
''' if progress_inline else '## No previous progress — this is the first exploration. Start from the beginning.'}

{f'''## Backend service connection info

The following backend services are running. Use these values to connect the app to real infrastructure (e.g., inject auth keys, verify daemon connectivity, test pairing/signing flows):

```
{backend_env}
```

Read `test/e2e/setup.sh` in the project to understand what each service does and how to interact with it.
''' if backend_env else ''}

{f'''## Previous findings

These bugs have already been found. Look for NEW bugs, and also verify whether previously fixed bugs have regressed:

<existing_findings>
{findings_inline}
</existing_findings>
{findings_overflow}
''' if findings_inline else '## No previous findings — this is the first exploration run.'}

## Output format

Write your findings to `{findings_file}` as JSON:

```json
{{
  "version": 1,
  "iteration": {iteration},
  "findings": [
    {{
      "id": "BUG-001",
      "severity": "critical|high|medium|low",
      "screen": "screen name from UI_FLOW.md",
      "flow": "which user flow",
      "summary": "one-line description",
      "steps_to_reproduce": ["step 1", "step 2"],
      "expected": "what should happen per spec",
      "actual": "what actually happens",
      "screenshot_path": "path to screenshot",
      "status": "new"
    }}
  ]
}}
```

**IMPORTANT**: Preserve any findings from previous iterations that have status "fixed" or "verified_broken". Only add new findings or update statuses.

## Rules

- {'Focus on the screens/flows specified in your task above' if parent_task else f'Explore EVERY screen and flow not already covered in `{e2e_dir}/progress.md`'}
- **Inspect with the cheapest structured tool first** — accessibility snapshot / no-vision state-tool; reserve screenshots for visual-only checks or bug evidence
- **Drive the app via MCP tools only** — never use `curl`, `wget`, `fetch`, or direct HTTP calls as a substitute for a real click/navigate. See the "Do NOT use curl" section above
- Test error paths: invalid inputs, back navigation, interruptions
- Test state persistence: navigate away and back
- Do NOT fix bugs — only document them
- Do NOT modify source code
- Create directories: `mkdir -p {e2e_dir}/screenshots/`
- **Update findings and progress after each screen** — don't wait until the end
- If you feel you're running low on context (many tool calls), save your work and stop gracefully
"""

    # ── Planner / executor / diagnostic prompts ────────────────────────
    # Opus planner decomposes the task into an ordered step list.
    # Sonnet executor walks the plan, handing off between spawns.
    # Opus diagnostic resolves blockers.

    def _build_e2e_planner_prompt(self, spec_dir: str, findings_file: Path,
                                   ui_flow: str, spec_content: str,
                                   iteration: int, e2e_dir: Path,
                                   parent_task: "Task | None" = None,
                                   task_block: str = "") -> str:
        """Opus planner: reads spec + progress, writes plan.md (ordered steps)."""
        findings_inline, findings_overflow = _prepare_findings_context(
            findings_file, e2e_dir)
        progress_inline, progress_overflow = _prepare_progress_context(
            e2e_dir / "progress.md", e2e_dir)

        task_section = ""
        if parent_task and task_block:
            task_section = f"""## Your task scope

**{parent_task.id}**: {parent_task.description}

```
{task_block}
```

Plan ONLY the exploration needed to satisfy this task's "Done when" criteria. Do not plan work outside this scope."""

        plan_file = e2e_dir / "plan.md"

        return f"""You are an E2E test planner. You produce an ordered step list for a Sonnet executor to walk through. You do NOT interact with the app — you only plan.

## Your job

Read the spec, UI flow, prior progress, and prior findings. Produce a concrete ordered list of test steps for THIS iteration. The executor will follow your plan step-by-step with MCP tools.

{task_section}

## Plan scope per iteration

Plan ~10-20 steps — roughly one executor session. Do not try to plan every screen in one go; the loop runs many iterations. Prioritize:

1. Screens/flows NOT already covered in `progress.md`
2. Regressions to re-check (prior fixed bugs — have they stayed fixed?)
3. Error paths within screens already touched

Skip screens marked validated in progress unless you have reason to believe they regressed.

## UI_FLOW.md (what should be tested)

<ui_flow>
{ui_flow}
</ui_flow>

## Specification (key requirements)

<spec>
{spec_content}
</spec>

{f'''## Previous exploration progress (what's already been validated)

<progress>
{progress_inline}
</progress>
{progress_overflow}
''' if progress_inline else '## No previous progress — this is the first iteration.'}

{f'''## Existing findings (bugs already found)

<findings>
{findings_inline}
</findings>
{findings_overflow}
''' if findings_inline else '## No existing findings yet.'}

## Output

Write your plan to `{plan_file}` with this EXACT format:

```markdown
# E2E Plan — iteration {iteration}

## Intent
[2-3 sentences: what this iteration is focused on and why]

## Steps

### step-1: <short action phrase>
- intent: [what outcome this step validates]
- preconditions: [what state must exist before — "none" if fresh]
- actions: [1-3 concrete MCP-tool-level actions, e.g. "browser_navigate to /checkout; browser_fill_form with test data; browser_click Continue"]
- expected: [observable result — status code, visible element, URL, etc.]
- on_mismatch: [what to write as a finding, or "skip if page is 500 — likely BUG-XXX"]

### step-2: ...
(repeat for each step)

## Notes for executor
[Any cross-step gotchas, e.g. "steps 3-5 share cart state — do not reset between them"]
```

## Rules

- Each step must be independently skippable — if step 3 blocks, executor can move to step 4 without failing the iteration
- Use `step-N` ids sequentially (step-1, step-2, ...) so blockers can reference them
- Be specific about selectors/URLs/inputs — the executor is Sonnet and benefits from concreteness
- Do NOT use MCP tools yourself — you are planning only
- Do NOT write findings — that's the executor's job
- Keep step count ~10-20; if more is needed, leave a note that another iteration is required
- If you notice UI_FLOW.md has gaps (screens/flows not fully specified), add them to a "Spec gaps" section at the end
"""

    def _build_e2e_executor_prompt(self, spec_dir: str, findings_file: Path,
                                    ui_flow: str, e2e_dir: Path, iteration: int,
                                    spawn_num: int,
                                    prior_handoff: str = "",
                                    prior_handoff_path: Path | None = None,
                                    unblock_context: str = "",
                                    mcp_caps: set[str] | None = None) -> str:
        """Sonnet executor: reads plan.md, walks steps, writes findings/handoff/blocker."""
        plan_file = e2e_dir / "plan.md"
        handoff_file = _executor_dir(e2e_dir) / "handoff.md"
        blocker_file = _executor_dir(e2e_dir) / "blocker.md"

        # Platform tool sections — reuse the same driver registry as explore
        driver = _pick_driver(mcp_caps or set())
        if driver is not None:
            tools_section = driver.tools_prompt_section(e2e_dir)
            screenshot_section = driver.screenshot_prompt_section(e2e_dir)
        else:
            tools_section = ("## Available MCP tools\n\n"
                             "Read the function schemas to see what tools are exposed.\n")
            screenshot_section = ""

        # Backend env for connecting to services
        backend_env = ""
        project_dir = Path.cwd()
        env_file = project_dir / "test" / "e2e" / ".state" / "env"
        if env_file.exists():
            backend_env = env_file.read_text()

        # Prior handoff section
        handoff_section = ""
        if prior_handoff:
            handoff_section = f"""## Resuming from prior executor spawn

A previous executor spawn completed some steps and handed off. Continue from where it left off.

<handoff>
{prior_handoff}
</handoff>

Full handoff at `{prior_handoff_path}` if you need more detail."""

        # Unblock context (only on retry after blocker)
        unblock_section = ""
        if unblock_context:
            unblock_section = f"""## Unblock guidance (from diagnostic)

A previous attempt on the current step got stuck. A diagnostic agent analyzed it and produced the following guidance. Apply it and retry the step.

<unblock>
{unblock_context}
</unblock>"""

        return f"""You are an E2E test executor. You follow a pre-written plan step-by-step and interact with the app via MCP tools. You do NOT improvise beyond the plan.

## Your job

1. Read the plan at `{plan_file}`
2. Resume from wherever the last spawn left off (see handoff below, if any)
3. For each remaining step: perform the actions, observe the result, compare to expected
4. Write findings to `{findings_file}` for any observed ≠ expected
5. When you complete a step, append a one-line progress note to `{e2e_dir}/progress.md`
6. Exit gracefully — do NOT try to do the whole plan in one session if it's long

## Exit protocol

You have three ways to exit. Choose exactly ONE before you stop:

**(A) Plan complete** — all steps in the plan are finished. Write `{handoff_file}` with:
```markdown
# Executor handoff (spawn {spawn_num})

## Status: COMPLETE

## Steps completed this spawn
- step-N: [short result]
...

## Findings written
[BUG-IDs added to findings.json this spawn, or "none"]
```

**(B) Partial — ready to hand off** — you've done useful work but feel you should stop (tool-call budget getting high, context feels loaded, etc.). Write `{handoff_file}`:
```markdown
# Executor handoff (spawn {spawn_num})

## Status: PARTIAL

## Steps completed this spawn
- step-N: [short result]
...

## Next step to resume at: step-M

## State left behind
[Anything the next spawn needs to know — e.g. "cart has 2 items", "logged in as admin", "on /checkout page"]

## Findings written
[BUG-IDs added this spawn]
```

**(C) Blocked — cannot proceed on current step** — you tried a step, it didn't produce the expected result, you tried ONE alternate approach (different selector / waited and retried), and it still didn't work, AND you cannot tell if the mismatch is a bug to file or a precondition you got wrong. Write `{blocker_file}`:
```markdown
# Executor blocker (spawn {spawn_num})

## Blocked step: step-N
## Step intent: [from plan]

## What I tried
1. [exact tool call + result]
2. [alternate attempt + result]

## What I observed
[snapshot / network / console excerpts — concrete]

## What I expected per plan
[from the step's `expected` field]

## Why I'm blocked
[one sentence: what decision you can't make — e.g. "Don't know if this 500 is BUG-015 resurfacing or a new bug; need to check if API was restarted after BUG-015 fix"]

## Steps completed before blocking
- step-N: [result]
...
```

**IMPORTANT about option (C)**: a mismatch between observed and expected is usually a BUG, not a blocker. Write a finding and continue to the next step. Only write a blocker when you genuinely cannot determine whether to proceed or what to file. Blockers trigger an Opus diagnostic — use them sparingly.

## Inline retry guidance

Before declaring a blocker, on any failed step try ONCE more with:
- A different selector (if element not found)
- A `wait` + retry (if timing flake suspected)
- Reading the console/network log to understand what's happening

If the second attempt also fails in a way you can't classify, THEN write the blocker.

{handoff_section}

{unblock_section}

{tools_section}
{screenshot_section}

## Plan (read with Read tool)

Your plan is at `{plan_file}`. Read it first. Do not try to replan.

## UI_FLOW.md (reference)

<ui_flow>
{ui_flow}
</ui_flow>

{f'''## Backend service connection info

```
{backend_env}
```

''' if backend_env else ''}

## Rules

- Follow the plan — do NOT invent new steps or explore outside it
- Inline retry once before blocking; continue past bugs (they are findings, not blockers)
- Update `{findings_file}` incrementally, after each finding
- Append to `{e2e_dir}/progress.md` after each completed step
- Exactly ONE exit file: `{handoff_file}` OR `{blocker_file}`, never both
- Do NOT modify source code
- Do NOT use curl/wget/fetch as a substitute for MCP tool calls
"""

    def _build_e2e_diagnostic_prompt(self, e2e_dir: Path, step_id: str,
                                      blocker_content: str, plan_content: str,
                                      ui_flow: str,
                                      prior_unblocks: list[Path],
                                      prior_summaries: list[Path],
                                      attempt: int) -> str:
        """Opus diagnostic: reads blocker + plan + prior attempts, writes unblock-N.md."""
        blocker_dir = _blocker_step_dir(e2e_dir, step_id)
        unblock_file = blocker_dir / f"unblock-{attempt}.md"

        prior_unblock_lines = "\n".join(
            f"- {p} (unblock-{i+1})" for i, p in enumerate(prior_unblocks)
        ) or "(none — this is the first diagnostic for this step)"
        prior_summary_lines = "\n".join(
            f"- {p} (executor summary for attempt {i+1})" for i, p in enumerate(prior_summaries)
        ) or "(none)"

        return f"""You are an E2E diagnostic agent. An executor got blocked on a specific step. Your job is to figure out why and write concrete instructions so the next executor spawn can unblock.

## Blocker (from executor)

<blocker>
{blocker_content}
</blocker>

## Plan step definition

<plan>
{plan_content}
</plan>

## Prior attempts on this step (lazy-load — read if you need more context)

Prior unblock guidance files:
{prior_unblock_lines}

Prior executor session summaries (mechanical tool-call extracts):
{prior_summary_lines}

You MAY use the Read tool to open any of these files if the current blocker suggests the prior attempts are relevant. Do NOT read them by default.

## UI_FLOW.md

<ui_flow>
{ui_flow}
</ui_flow>

## Your job

1. Diagnose the root cause. The executor says it can't classify the observed state. You have more context — figure out what's actually happening.
2. If the step is testing something that's legitimately broken in the app: tell the executor to **file it as a bug and skip the step**.
3. If the step's expected state was wrong or the preconditions weren't met: tell the executor **exactly what to do differently**.
4. If this is genuinely a spec ambiguity: tell the executor to **skip the step and flag it as a spec gap**.

## Output

Write your guidance to `{unblock_file}` with this format:

```markdown
# Unblock guidance — {step_id}, attempt {attempt}

## Diagnosis
[One paragraph: what's actually going on]

## Action for next executor spawn
[ONE of:]
- FILE_AND_SKIP: File the blocker as a finding with summary "<short>" severity <critical|high|medium|low>, then skip this step.
- RETRY_WITH: Try the step again, but [concrete modification — new selector, different preconditions, specific waits].
- SKIP_SPEC_GAP: Skip the step. Note in progress.md: "step-N skipped — spec unclear about <aspect>".

## Why
[One sentence: why this is the right action]
```

## Rules

- Be decisive — the executor needs one clear action, not a menu of options
- Do NOT try to fix source code — you are diagnosing only
- If you genuinely cannot diagnose, pick SKIP_SPEC_GAP (the planner will route around next iteration)
- Keep it short — the executor reads this inline
"""

    def _build_e2e_fix_prompt(self, spec_dir: str, findings_file: Path,
                               open_bugs: list[dict], learnings_file: str,
                               e2e_dir: Path = None,
                               mcp_caps: set[str] | None = None) -> str:
        """Build the prompt for the E2E fix agent.

        When e2e_dir is provided, includes per-bug research reports and
        supervisor guidance in the prompt.
        """
        bugs_summary = json.dumps(open_bugs, indent=2)
        driver = _pick_driver(mcp_caps or set())
        regression_hint = (driver.fix_regression_test_hint() if driver
                           else "**Regression test quality**: Regression tests MUST be behavioral "
                                "— test real state transitions and side effects, not mocked outputs.")

        # Build per-bug research and guidance sections
        research_sections = ""
        if e2e_dir:
            sections = []
            for bug in open_bugs:
                bug_id = bug.get("id", "")
                if not bug_id:
                    continue
                bug_d = _bug_dir(e2e_dir, bug_id)

                parts = [f"### {bug_id}: {bug.get('summary', '')}"]

                # Include latest research
                research_content, research_idx = _read_latest_research(e2e_dir, bug_id)
                if research_content:
                    parts.append(f"**Research report** (research-{research_idx}.md):\n{research_content}")

                # Include supervisor guidance if any
                history = _read_bug_history(e2e_dir, bug_id)
                sup_runs = history.get("supervisor_runs", 0)
                if sup_runs > 0:
                    decision_file = bug_d / f"supervisor-{sup_runs}-decision.md"
                    if decision_file.exists():
                        decision = decision_file.read_text()
                        parts.append(f"**Supervisor guidance** (run #{sup_runs}):\n{decision}")

                # Include fix attempt history so agent knows what NOT to do
                attempts = history.get("fix_attempts", [])
                if attempts:
                    attempt_lines = []
                    for a in attempts:
                        attempt_lines.append(
                            f"- Attempt {a['attempt']}: {a['approach']} → {a['verify_status']}"
                        )
                    parts.append(
                        "**Previous fix attempts (all failed — do NOT repeat these)**:\n"
                        + "\n".join(attempt_lines)
                    )

                # Include latest verify evidence
                # Find the most recent verify-evidence file
                evidence_files = sorted(bug_d.glob("verify-evidence-*.md"))
                if evidence_files:
                    latest_evidence = evidence_files[-1].read_text()
                    parts.append(f"**Latest verify evidence**:\n{latest_evidence}")

                if len(parts) > 1:  # more than just the header
                    sections.append("\n\n".join(parts))

            if sections:
                research_sections = f"""## Per-bug research and guidance

The following research, supervisor guidance, and fix history is available for each bug.
**Read this carefully before attempting fixes** — it tells you what approaches have
already failed and what the research agent recommends.

{chr(10).join(sections)}
"""

        return f"""You are an E2E fix agent. Your job is to fix ALL reported bugs in a single batch pass.

## Bugs to fix ({len(open_bugs)} total)

<findings>
{bugs_summary}
</findings>

{research_sections}

## Instructions

1. Read `CLAUDE.md` for project conventions and build commands
2. **Read all per-bug research and guidance above** before writing any code
3. For each bug:
   a. If research/guidance exists: follow the recommended fix strategy
   b. If previous fix attempts exist: ensure your approach is DIFFERENT from all of them
   c. Read the steps to reproduce and the expected vs actual behavior
   d. Find the relevant source code
   e. Fix the root cause (not just the symptom)
4. Fix ALL bugs before stopping — do not fix one and then quit
5. **Run the project's test suite** to make sure your fixes don't break existing functionality:
   - Read `CLAUDE.md` or `Makefile` to find the test command (e.g., `make test`, `./gradlew test`, `npm test`, `go test ./...`)
   - Run **all** test suites, not just the ones related to your changes — E2E fixes often touch shared code
   - If tests fail, fix them before committing. If a test failure is pre-existing (not caused by your changes), note it but don't block on it.
6. Commit all changes with a conventional commit message
7. **For each bug you fix**, write a brief description of your approach to
   `{e2e_dir}/bugs/<BUG-ID>/fix-approach-latest.md` — one paragraph describing
   what you changed and why. This is used by the verify agent and supervisor.

## Rules

- Fix ALL {len(open_bugs)} bugs, not just the first one
- Do NOT modify `{findings_file}` — the verify agent will update it
- Do NOT skip bugs — if you can't fix one, add a comment in the code explaining why
- **Do NOT repeat failed approaches** — check the per-bug fix history above
- Prefer fixing the app code over fixing tests (tests are the spec)
- **Do NOT skip tests** — if you can't find a test command, look harder (CLAUDE.md, Makefile, package.json, build.gradle)
- Record any non-obvious learnings to `{learnings_file}`
- {regression_hint}
"""

    def _build_e2e_verify_prompt(self, spec_dir: str, findings_file: Path,
                                  ui_flow: str, e2e_dir: Path,
                                  mcp_caps: set[str] | None = None) -> str:
        """Build the prompt for the E2E verify agent."""
        # Verify agent needs bug details but not pass entries.
        # Higher inline limit since it needs steps-to-reproduce etc.
        findings_inline, findings_overflow = _prepare_findings_context(
            findings_file, e2e_dir, max_inline_bytes=40_000)

        driver = _pick_driver(mcp_caps or set())
        if driver is not None:
            tools_section = driver.verify_tools_section(e2e_dir)
            screenshot_hint = driver.verify_screenshot_save_hint(e2e_dir)
            observed_hint = driver.verify_evidence_observed_hint()
        else:
            tools_section = ("## Available MCP tools\n\n"
                             "No platform capability declared — read the function schemas to "
                             "see what tools are exposed.\n")
            screenshot_hint = "Save screenshots alongside findings when your platform supports it."
            observed_hint = ("[Snapshot / hierarchy / tree excerpt showing the relevant UI "
                             "element(s). Paste the exact output.]")

        return f"""You are an E2E verify agent with access to MCP tools. Your job is to verify bug fixes, produce structured evidence, and find new bugs.

## CRITICAL: Context window management

Follow these rules to avoid crashing from context overflow:

1. **Prefer structured state (snapshot / hierarchy tree) over screenshots** — structured output is far cheaper in context. Reserve screenshots for visual-only checks.
2. **Maximum 15 screenshots per session** — one per bug being verified is enough.
3. **Avoid re-reading screenshots** you've already analyzed.
4. **Update findings incrementally** — write to `{findings_file}` after verifying each bug, not all at once at the end.

{tools_section}

## Previous findings to verify

<findings>
{findings_inline}
</findings>
{findings_overflow}

## Instructions

1. For each bug with status "new" or "verified_broken" in the findings:
   a. Follow the steps to reproduce exactly
   b. **Capture structured state first** (snapshot / hierarchy), screenshot only if visual evidence is needed
   c. If the bug is fixed: update status to "fixed"
   d. If the bug still exists: update status to "verified_broken"
   e. **Write structured evidence** to the bug's directory (see below)
2. **Update `{findings_file}` after EACH bug** — don't wait until the end
3. While re-testing, if you discover NEW bugs, add them with status "new"

## CRITICAL: Structured evidence output

For EVERY bug you verify (whether fixed or still broken), you MUST write a
structured evidence file to `{e2e_dir}/bugs/<BUG-ID>/verify-evidence-<iteration>.md`.

Create the directory if it doesn't exist: `mkdir -p {e2e_dir}/bugs/<BUG-ID>/`

The evidence file MUST contain:

```markdown
# Verify evidence: <BUG-ID> — iteration N

## Status: FIXED | STILL_BROKEN

## Actions taken
1. [exact MCP tool call and parameters]
2. [next action...]

## Observed state
{observed_hint}

## Expected state
[What the state SHOULD look like per the spec, with specific attribute values.]

## Delta
[Concrete difference: "Element has aria-disabled=true, expected aria-disabled=false"
or "Node missing entirely from tree" — NOT "the UI is broken"]

## Screenshot
[Path to screenshot file, or "not needed — structured state sufficient"]
```

**Why this matters**: The fix agent and supervisor use this evidence to understand
exactly what failed. "Bug still broken" is useless. Concrete deltas tell the fix agent
exactly what to fix.

Also update the finding in `{findings_file}` to include a `bug_dir` field pointing
to the bug's evidence directory: `"bug_dir": "{e2e_dir}/bugs/<BUG-ID>"`

## UI_FLOW.md for reference

<ui_flow>
{ui_flow}
</ui_flow>

## Rules

- Test EVERY bug in the findings — do not skip any
- {screenshot_hint}
- Add any newly discovered bugs (with `bug_dir` field)
- **Always write structured evidence** — no exceptions
- Do NOT modify source code — only update `{findings_file}` and write evidence files
"""

    def _build_e2e_supervisor_prompt(self, spec_dir: str, e2e_dir: Path,
                                      state: dict, ui_flow: str) -> str:
        """Build the prompt for the E2E supervisor agent."""
        state_json = json.dumps(state, indent=2)
        findings_file = e2e_dir / "findings.json"
        findings_inline, findings_overflow = _prepare_findings_context(
            findings_file, e2e_dir)

        return f"""You are an E2E supervisor agent. Review the progress of the E2E testing loop and decide whether to continue, redirect, or stop.

## Current state

<state>
{state_json}
</state>

## Current findings

<findings>
{findings_inline}
</findings>
{findings_overflow}

## UI_FLOW.md (what should be tested)

<ui_flow>
{ui_flow}
</ui_flow>

## Your decision

Analyze the progress:

1. **Are we making progress?** Compare bugs found/fixed across iterations. If the same bugs keep appearing, we're stuck.
2. **Is coverage improving?** Check which screens/flows from UI_FLOW.md have been tested vs which haven't.
3. **Are we stuck in a loop?** If the fix agent keeps "fixing" the same bugs but they come back, the approach needs to change.

Write your decision to `{e2e_dir}/supervisor-decision.md`:

### If progress is being made:
```
# CONTINUE

[Brief assessment of progress]
[Any strategic guidance for the next explore agent — e.g., "focus on error paths in the pairing flow" or "the sign request timeout handling hasn't been tested yet"]
```

Also write any strategic guidance to `{e2e_dir}/guidance.md` (the explore agent reads this).

### If stuck but fixable:
```
# REDIRECT

[What's going wrong]
[New strategy to try]
```

Write the new strategy to `{e2e_dir}/guidance.md`.

### If human intervention is needed:
```
# STOP — HUMAN INTERVENTION NEEDED

[What's wrong]
[What the human should look at]
[Specific files/screens/logs to check]
```

## Rules

- Be decisive — don't hedge
- If the same bug has been "fixed" and "verified_broken" more than 3 times, that's a sign the fix approach is wrong
- If total iterations > 30 with diminishing returns, suggest stopping
- Consider token cost: each iteration is ~100k tokens. Is continued exploration worth it?
"""

    def _build_e2e_regression_prompt(self, spec_dir: str, e2e_dir: Path) -> str:
        """Build prompt for the post-E2E regression check agent."""
        return f"""You are a regression check agent. The E2E bug-fix loop just completed — multiple rounds of fixes were applied to resolve UI/behavioral bugs found during E2E exploration. Your job is to run the project's FULL test suite to make sure nothing was broken.

## Instructions

1. Read `CLAUDE.md` in the project root to find ALL test commands. Look for:
   - `make test`, `make validate`, or similar Makefile targets
   - `go test ./...` or language-specific test runners
   - `./gradlew test` or `./gradlew testDebugUnitTest` for Android
   - `npm test`, `pytest`, `cargo test`, etc.
   - Any other test commands documented in the project

2. Run EVERY test suite you find — not just one. Projects often have multiple:
   - Host/backend tests (Go, Rust, Python, etc.)
   - Android/iOS unit tests (Gradle, Xcode)
   - Lint checks (`make lint`, `golangci-lint`, `ktlint`)
   - Type checks, format checks

3. For each test suite:
   - Run it and capture the output
   - If it PASSES: note it in your report
   - If it FAILS: analyze the failures. Determine if they were caused by E2E fixes (check `git log` for recent commits) or pre-existing.
     - If caused by E2E fixes: **fix the regression**, run tests again to confirm, commit the fix
     - If pre-existing: note it but don't block on it

4. Write your results to `{e2e_dir}/regression-report.md`:

```markdown
# Post-E2E Regression Report

## Test suites run

- [PASS/FAIL] <test command> — <summary>
- [PASS/FAIL] <test command> — <summary>

## Regressions found and fixed
- <description of regression and fix, if any>

## Pre-existing failures (not caused by E2E fixes)
- <description, if any>

## Result
ALL TESTS PASSED / REGRESSIONS FIXED / FAILURES REMAIN
```

## Rules

- Run ALL test suites, not just the obvious ones
- Do NOT skip tests because they're slow — run everything
- If you fix regressions, commit them with a descriptive message
- Be thorough — this is the last check before the task is marked done
"""

    def _build_e2e_crash_supervisor_prompt(self, spec_dir: str, e2e_dir: Path,
                                            state: dict, ui_flow: str,
                                            exit_code: int, stderr: str,
                                            result_info: str,
                                            iteration: int) -> str:
        """Build a supervisor prompt specifically for an explore agent crash."""
        state_json = json.dumps(state, indent=2)
        return f"""You are an E2E supervisor agent. The explore agent just **crashed** (non-zero exit). Diagnose the failure and decide whether retrying could help or if human intervention is needed.

## Crash details

- **Exit code**: {exit_code}
- **Iteration**: {iteration}
- **Stderr output**:
```
{stderr if stderr else "(empty — no stderr captured)"}
```

{f'''- **JSONL result/error info** (from the agent's log — this is often more informative than stderr):
```
{result_info}
```
''' if result_info else '- **JSONL result info**: (none extracted)'}

## Loop state

<state>
{state_json}
</state>

## Your job

Analyze ALL available crash information to determine the root cause. **Check the JSONL result info first** — it often contains the real error when stderr is empty.

Common crash causes:
- **MCP config invalid**: "Does not adhere to MCP server configuration schema" → config file format is wrong. STOP.
- **MCP server not running**: connection refused, timeout → emulator/browser not booted. STOP.
- **MCP server status "failed"**: The MCP server failed to initialize — check if the emulator/service is running. STOP.
- **Auth failure**: API key expired or missing → credential issue. STOP.
- **API image limit**: "image in the conversation exceeds the dimension limit" → agent accumulated too many screenshots and hit the Claude API multi-image limit. This is a **context overflow**, not an infra issue. The agent was working but ran out of context. CONTINUE (the next iteration will pick up from progress.md).
- **OOM / timeout**: resource exhaustion → may be transient, CONTINUE to retry once.
- **Emulator died**: adb device not found → emulator crashed mid-test. May be transient.

Write your decision to `{e2e_dir}/supervisor-decision.md`:

### If the crash is an infrastructure/config issue (not transient):
```
# STOP — HUMAN INTERVENTION NEEDED

[Root cause diagnosis]
[What the human needs to fix]
```

### If the crash is a context overflow (too many images/tokens):
```
# CONTINUE

Agent hit context window limits after doing real work. The next iteration will resume from progress.md.
```

### If the crash looks transient (OOM, timeout, flaky emulator):
```
# CONTINUE

[Why you think a retry will succeed]
```

## Rules

- **Read ALL crash info before deciding** — empty stderr does NOT mean the agent did nothing. Check the JSONL result info.
- Be decisive — if the error clearly shows a config/setup issue, say STOP immediately
- A crash that happened once might be transient. The same crash twice is a pattern — check state.history for prior crashes
- Don't suggest retrying if the error message indicates a deterministic failure (bad config, missing binary, schema error)
- Context overflow crashes (image limits, token limits) are expected and recoverable — always CONTINUE
"""

    # ── Per-bug research / supervisor / escalation prompt builders ──────

    def _build_e2e_research_prompt(self, bug: dict, e2e_dir: Path,
                                    spec_dir: str, ui_flow: str,
                                    supervisor_directive: str = "") -> str:
        """Build prompt for a research agent investigating a specific bug."""
        bug_id = bug["id"]
        bug_d = _bug_dir(e2e_dir, bug_id)
        history = _read_bug_history(e2e_dir, bug_id)

        # Load previous research if any
        prev_research, prev_idx = _read_latest_research(e2e_dir, bug_id)
        prev_research_section = ""
        if prev_research:
            prev_research_section = f"""## Previous research (research-{prev_idx}.md)

The following research was done previously for this bug. It may be incomplete or
have led the fix agent in the wrong direction. Build on what's useful, discard what's not.

<previous_research>
{prev_research}
</previous_research>
"""

        # Load supervisor summaries if this is a redirected research
        supervisor_section = ""
        if supervisor_directive:
            summaries = _read_supervisor_summaries(e2e_dir, bug_id)
            summaries_text = ""
            if summaries:
                summaries_text = "\n\n---\n\n".join(
                    f"### Supervisor run #{i+1}\n{s}" for i, s in enumerate(summaries)
                )
                summaries_text = f"""### Previous supervisor assessments (summaries)

{summaries_text}
"""
            supervisor_section = f"""## Supervisor directive

The bug supervisor has reviewed failed fix attempts and is redirecting research.
Follow the supervisor's guidance on what to investigate.

<directive>
{supervisor_directive}
</directive>

{summaries_text}"""

        # Build fix attempt history summary
        attempts_section = ""
        attempts = history.get("fix_attempts", [])
        if attempts:
            lines = []
            for a in attempts:
                lines.append(
                    f"- **Attempt {a['attempt']}**: {a['approach']}\n"
                    f"  Result: {a['verify_status']}\n"
                    f"  Evidence: {a['verify_evidence'][:300]}"
                )
            attempts_section = f"""## Previous fix attempts (all failed)

These approaches have already been tried and failed. Do NOT recommend any of them.

{chr(10).join(lines)}
"""

        next_idx = (prev_idx or 0) + 1

        return f"""You are a research agent investigating a specific bug before a fix agent attempts to resolve it.

## Bug details

- **ID**: {bug["id"]}
- **Screen**: {bug.get("screen", "unknown")}
- **Summary**: {bug.get("summary", "")}
- **Expected**: {bug.get("expected", "")}
- **Actual**: {bug.get("actual", "")}
- **Steps to reproduce**: {json.dumps(bug.get("steps_to_reproduce", []))}

{attempts_section}
{prev_research_section}
{supervisor_section}

## Your mission

Investigate this bug thoroughly and produce a research report that gives the fix
agent a clear, evidence-based strategy. Do NOT guess — find real answers.

### Research steps

1. **Search the codebase** — find the relevant source files for this screen/component.
   Grep for class names, composable function names, view model references.
2. **Read the code** — understand the current implementation. What does it do now?
   What's the gap between current behavior and the spec?
3. **Search the web** — look up documentation, Stack Overflow answers, and official
   guides for the specific API/framework behavior involved. For Compose accessibility,
   search for the exact Modifier or API that's relevant.
4. **Find working examples** — search the codebase for similar patterns that already
   work correctly. If another screen handles the same concern (e.g., accessibility,
   navigation, validation), show how it does it.
5. **Synthesize a fix strategy** — based on your research, recommend a specific
   approach. Include the exact API calls, modifier chains, or code patterns to use.
   Be concrete: "use X with parameters Y" not "consider using X".

## UI_FLOW.md (specification)

<ui_flow>
{ui_flow}
</ui_flow>

## Output

Write your research report to `{bug_d}/research-{next_idx}.md` with this structure:

```markdown
# Research: {bug["id"]} — {bug.get("summary", "")}

## Root cause analysis
[What's actually wrong in the code and why]

## Evidence
[Code snippets, documentation quotes, working examples found in codebase]

## Recommended fix strategy
[Concrete approach — exact API calls, code patterns, file paths to modify]

## What NOT to do
[Approaches already tried that failed, and why they failed]

## Confidence
[High/Medium/Low — and what would increase confidence if Low]
```

## Rules

- Do NOT modify any source code — research only
- Do NOT modify findings.json
- Be specific — "add Modifier.semantics(mergeDescendants = true)" is good,
  "improve accessibility" is useless
- If you find contradictory information, note both sides and recommend the
  approach with stronger evidence
- If your confidence is Low, say so — it's better to admit uncertainty than
  to send the fix agent down a wrong path
"""

    def _build_e2e_bug_supervisor_prompt(self, bug: dict, e2e_dir: Path,
                                          ui_flow: str) -> str:
        """Build prompt for a per-bug supervisor that reviews fix attempts."""
        bug_id = bug["id"]
        bug_d = _bug_dir(e2e_dir, bug_id)
        history = _read_bug_history(e2e_dir, bug_id)
        supervisor_run = history.get("supervisor_runs", 0) + 1

        # Load all previous supervisor summaries
        prev_summaries = _read_supervisor_summaries(e2e_dir, bug_id)
        summaries_section = ""
        if prev_summaries:
            lines = []
            for i, s in enumerate(prev_summaries):
                lines.append(f"### Supervisor run #{i+1}\n{s}")
            summaries_section = f"""## Previous supervisor assessments

Read these carefully — they contain what was already tried and what conclusions
were reached. Do NOT repeat strategies that previous supervisors already rejected.

{chr(10).join(lines)}
"""

        # Load fix attempt history
        attempts = history.get("fix_attempts", [])
        attempts_lines = []
        for a in attempts:
            attempts_lines.append(
                f"### Attempt {a['attempt']}\n"
                f"- **Approach**: {a['approach']}\n"
                f"- **Result**: {a['verify_status']}\n"
                f"- **Evidence**: {a['verify_evidence'][:500]}\n"
                f"- **Timestamp**: {a.get('timestamp', 'unknown')}"
            )
        attempts_section = "\n\n".join(attempts_lines) if attempts_lines else "(no attempts recorded)"

        # Load latest research
        research_content, research_idx = _read_latest_research(e2e_dir, bug_id)
        research_section = ""
        if research_content:
            research_section = f"""## Latest research (research-{research_idx}.md)

<research>
{research_content}
</research>
"""

        return f"""You are a bug supervisor agent. A specific bug has failed to be fixed after multiple attempts. Review the history and decide the next action.

## Bug details

- **ID**: {bug["id"]}
- **Screen**: {bug.get("screen", "unknown")}
- **Summary**: {bug.get("summary", "")}
- **Expected**: {bug.get("expected", "")}
- **Actual**: {bug.get("actual", "")}

## Fix attempt history

{attempts_section}

{research_section}
{summaries_section}

## UI_FLOW.md (relevant specification)

<ui_flow>
{ui_flow}
</ui_flow>

## Your decision

This is supervisor run #{supervisor_run} for this bug (max 5 before human escalation).

Analyze the fix history and determine:

1. **Is the current approach viable?** Look at whether recent attempts are making
   progress (getting closer to the right state) or oscillating (alternating between
   two failed approaches).
2. **Is the research accurate?** Compare what the research recommended against what
   the verify evidence shows. If the research was wrong, new research is needed.
3. **Is this a code problem, spec problem, or infra problem?**
   - Code: the implementation approach is wrong, need a different strategy
   - Spec: the spec requires something the platform genuinely can't do
   - Infra: the test tooling can't verify this properly

### Decision: DIRECT_FIX

If you have a concrete fix strategy based on the evidence (not a guess):

```markdown
# DIRECT_FIX

## Strategy
[Exact approach — specific API calls, code changes, file paths]

## Why this will work
[Evidence from the history/research that supports this approach]

## What's different from previous attempts
[How this differs from what was already tried]
```

### Decision: REDIRECT_RESEARCH

If the current research was wrong or incomplete and new investigation is needed:

```markdown
# REDIRECT_RESEARCH

## What went wrong with current approach
[Why the research/fix direction isn't working]

## Research directive
Question: [specific question the research agent should answer]

Context: [what's been ruled out and why]

Leads to investigate:
- [specific search leads — APIs to look up, code to examine, docs to read]
```

### Decision: ESCALATE

If this bug is fundamentally stuck (supervisor run 4+ or clearly unsolvable):

```markdown
# ESCALATE

## Category
[code | spec | infra]

## Why we're stuck
[Summary of what's been tried and why nothing works]

## What a human could provide
[Specific guidance or decision needed]
```

Write your decision to `{bug_d}/supervisor-{supervisor_run}-decision.md`.

Also write a SHORT summary (under 15 lines) to `{bug_d}/supervisor-{supervisor_run}-summary.md`.
The summary should contain:
- Approach evaluated
- Why it failed (one line)
- Decision taken (DIRECT_FIX / REDIRECT_RESEARCH / ESCALATE)
- Key insight for next supervisor (one line)

This summary is what future supervisors and research agents will see — make it count.

## Rules

- Do NOT modify source code
- Do NOT modify findings.json
- Be decisive — pick one decision, don't hedge
- If you see oscillation (approach A → fail → approach B → fail → approach A again),
  that's a strong signal for REDIRECT_RESEARCH with new questions
- ESCALATE is not failure — it's the right call when the evidence shows the bug
  can't be resolved without human input
"""

    def _build_e2e_escalation_prompt(self, bug: dict, e2e_dir: Path,
                                      category: str) -> str:
        """Build prompt for the synthesis agent that produces BLOCKED.md."""
        bug_id = bug["id"]
        bug_d = _bug_dir(e2e_dir, bug_id)
        history = _read_bug_history(e2e_dir, bug_id)

        # Collect all artifacts
        summaries = _read_supervisor_summaries(e2e_dir, bug_id)
        research_content, research_idx = _read_latest_research(e2e_dir, bug_id)

        attempts = history.get("fix_attempts", [])
        attempts_text = json.dumps(attempts, indent=2)

        summaries_text = "\n\n---\n\n".join(
            f"### Supervisor #{i+1}\n{s}" for i, s in enumerate(summaries)
        )

        # List all files in the bug directory for linking
        files_list = ""
        if bug_d.exists():
            files = sorted(bug_d.iterdir())
            files_list = "\n".join(f"- `{f.relative_to(e2e_dir.parent)}`" for f in files if f.is_file())

        return f"""You are an escalation synthesis agent. A bug has exhausted all automated fix attempts and needs human intervention. Produce a clear, actionable BLOCKED.md.

## Bug details

- **ID**: {bug["id"]}
- **Screen**: {bug.get("screen", "unknown")}
- **Summary**: {bug.get("summary", "")}
- **Expected**: {bug.get("expected", "")}
- **Actual**: {bug.get("actual", "")}
- **Escalation category**: {category}

## Fix attempt history

<attempts>
{attempts_text}
</attempts>

## Supervisor summaries

{summaries_text if summaries_text else "(none)"}

## Latest research

<research>
{research_content if research_content else "(none)"}
</research>

## Files in bug directory

{files_list}

## Your mission

Write `{bug_d}/BLOCKED.md` with a synthesis that a human (or a future agent
parsing BLOCKED.md) can act on immediately.

### For category: code
- Summarize what was tried and why each approach failed
- Identify the core technical question that needs answering
- Suggest what a human with domain expertise should look at
- Link to all relevant bug directory files

### For category: spec
- Explain what the spec requires
- Provide evidence that the platform can't satisfy it
- Propose a specific spec revision
- Analyze impact on other bugs/requirements

### For category: infra
- Explain what verification was attempted
- Show why the tooling can't verify the expected behavior
- Propose alternative verification approaches
- Link to relevant evidence files

## Output format

```markdown
# BLOCKED: {bug["id"]} — {bug.get("summary", "")}

**Category**: {category}
**Fix attempts**: {{count}}
**Supervisor runs**: {{count}}

## Summary
[2-3 sentence synthesis of the entire investigation]

## What was tried
[Bulleted list of approaches with one-line failure reasons]

## Root cause assessment
[Why automated fixing couldn't resolve this]

## Recommended human action
[Specific, actionable next step]

## Evidence files
[Links to all files in the bug directory]
```

## Rules

- Be concise — the human should understand the situation in 30 seconds
- Link to files, don't paste their full contents
- The "Recommended human action" must be specific enough to act on immediately
- Do NOT modify source code or findings.json
"""

    # _build_e2e_test_writer_prompt removed — instrumented test writing is
    # deferred to a batch step after all E2E exploration completes, to avoid
    # burning tokens on per-bug test-fix retry loops during exploration.

    def _run_ci_loop(self, task: Task, spec_dir: str, task_file: Path,
                     learnings_file: str):
        """Run the CI debug loop, catching auth failures."""
        debug_dir = _ci_debug_dir(task.id)
        ci_log_path = debug_dir / "ci-loop.log"

        def _ci_log_to_file(msg: str):
            ts = datetime.now().strftime("%H:%M:%S")
            with open(ci_log_path, "a") as f:
                f.write(f"[{ts}] {msg}\n")

        try:
            return self.__run_ci_loop_inner(task, spec_dir, task_file, learnings_file)
        except AgentAuthError as e:
            _ci_log_to_file(f"FATAL: {e}")
            self.log(f"FATAL: Auth error in CI loop for {task.id} — stopping all tasks. Re-authenticate and re-run.")
            self._shutdown.set()
            self.blocked_file.write_text(
                f"# BLOCKED: {task.id} — Claude Code authentication expired\n\n"
                f"Sub-agent failed with a 401 authentication error. "
                f"The Claude Code session has likely expired.\n\n"
                f"## What to do\n\n"
                f"1. Re-authenticate Claude Code (run `claude` and log in)\n"
                f"2. Restart the runner\n\n"
                f"## Context\n\nAll diagnosis and log files are in `{debug_dir}/`.\n"
            )
            return

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
    parser.add_argument("--and-later", action="store_true",
                        help="After the specified spec_dir completes, also run all later specs (sorted alphabetically)")

    args = parser.parse_args()

    # ── Sandbox setup ──
    global _sandbox_enabled, _bwrap_path
    if args.no_sandbox:
        _sandbox_enabled = False
        print("⚠ Sandbox DISABLED by --no-sandbox flag", file=sys.stderr)
    else:
        _bwrap_path = _detect_bwrap()
        if _bwrap_path:
            _sandbox_enabled = True
            print(
                f"🔒 Sandbox enabled (bwrap: {_bwrap_path})",
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
                "  Re-entering inside nix develop shell...",
                file=sys.stderr,
            )
            # Probe first — if the flake has unfree packages, retry with --impure
            nix_cmd = ["nix", "develop", "--command"]
            probe = subprocess.run(
                nix_cmd + ["true"],
                capture_output=True, timeout=120,
            )
            if probe.returncode != 0 and b"unfree" in probe.stderr:
                print(
                    "  Flake contains unfree packages — re-entering with NIXPKGS_ALLOW_UNFREE=1 --impure...",
                    file=sys.stderr,
                )
                os.environ["NIXPKGS_ALLOW_UNFREE"] = "1"
                nix_cmd = ["nix", "develop", "--impure", "--command"]
            elif probe.returncode != 0:
                print(
                    f"  ⚠ nix develop failed (exit {probe.returncode}), continuing without nix shell.\n"
                    f"  stderr: {probe.stderr.decode()[:300]}",
                    file=sys.stderr,
                )
                nix_cmd = None
            if nix_cmd is not None:
                os.execvp("nix", nix_cmd + [sys.executable, *sys.argv])

    # Resolve spec dirs
    if args.spec_dir:
        if args.and_later:
            # Run the specified spec and all alphabetically-later specs
            if not Path("specs").is_dir():
                print("Error: No specs/ directory found. Are you in a spec-kit project root?")
                sys.exit(1)
            all_specs = sorted(str(d) for d in Path("specs").iterdir() if d.is_dir())
            # Normalize the user-provided path for comparison
            target = str(Path(args.spec_dir))
            spec_dirs = [s for s in all_specs if s >= target]
            if not spec_dirs:
                print(f"Error: No spec directories found at or after {args.spec_dir}")
                sys.exit(1)
        else:
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
