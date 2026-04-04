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

**Note**: Phase validation (build/test at phase boundaries) is handled automatically by the runner — you do NOT need to run it.

## Step 3: Self-review

Before marking complete, review your own changes:
1. Run `git diff` to see everything you changed
2. Check for leftover debug code, missing error handling, security issues
3. Fix anything you find

## Step 4: Record learnings

Append any useful discoveries to `{learnings_file}`. Keep entries concise — max 3 bullet points per task, focusing only on non-obvious gotchas that would save a future agent time. Skip obvious things (API signatures, standard patterns, what was already documented).

## Step 5: Mark complete and commit

1. In `{task_file}`, change task {task.id}'s `- [ ]` to `- [x]`
2. Commit all changes with a conventional commit message including the task ID (e.g., `feat({task.id}): ...`)

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
                prompt += "If the task code is already written and tests can't run due to connection issues, verify the code compiles (`go vet`, `go build`) and mark the task complete — phase validation will run tests later.\n\n"
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

### Run validation (four-step sequence)

Run these steps **in order**, stopping at the first failure category. Do NOT skip steps — every step that has a command must run.

**Step 1 — Build**: Compile/transpile the project. If there's no explicit build step, skip.
**Step 2 — Test**: Run the full test suite. Capture all output.
**Step 3 — Lint**: Run the project's linter(s) (e.g. `eslint`, `golangci-lint`, `ruff`, `clippy`). Check `CLAUDE.md`, `package.json` scripts, and `Makefile` for the lint command. If a linter is configured but not in CLAUDE.md, still run it.
**Step 4 — Security scan**: Run any security scanners configured in the project (e.g. `npm audit`, `trivy`, `semgrep`, `bandit`). Write results to `test-logs/security/`. If no scanners are configured, skip.

**Short-circuit rule**: If Step 1 (build) fails, skip Steps 2-4. If Step 2 (test) fails, still run Step 3 (lint) — lint errors are cheap to find and the fix agent can address both in one pass. Skip Step 4 (security) if build or test failed.

**Code coverage is mandatory for every test suite in the project.** If the project's test commands do not already collect coverage, fix them — add the standard coverage tool for that language/framework (every mainstream ecosystem has one) and wire it into the test command. Coverage MUST produce both terminal output and a file report in `coverage/` (JSON, XML, LCOV, or equivalent). See `reference/testing.md` § Code coverage collection for details.

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

**Important**: For early phases, the build/test infrastructure may not exist yet or may only cover a subset. Run what's available. If literally nothing can be validated yet, note this and pass.

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

   ## Failed steps detail

   ### [Step name, e.g. "Test" or "Lint"]
   **Command**: (exact command run)
   **Exit code**: (exit code)
   **Root cause summary**: (1-2 sentence diagnosis — what is actually wrong, not just "tests failed")
   **Failures**:
   - (each distinct failure: file, line if available, what's wrong)

   ## Full output
   (relevant portions of stdout/stderr, organized by step)
   ```
   Fill in PASS/FAIL/SKIPPED for every category based on what you ran. This lets fix agents immediately see which steps failed without parsing raw output.
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

    # Capability-gated credentials: only inject when the task declares it.
    # This keeps tokens away from tasks that run untrusted code (npm/pip install).
    if "gh" in capabilities:
        token = _acquire_gh_token()
        if token:
            env["GH_TOKEN"] = token

    return env


def spawn_agent(task: Task, prompt: str, log_path: Path,
                stderr_path: Path,
                extra_capabilities: set[str] | None = None) -> subprocess.Popen:
    """Spawn a claude CLI process for the given task.

    Capabilities from task.capabilities (parsed from [needs: gh] etc.) plus
    any extra_capabilities (e.g. granted after a BLOCKED.md request) control
    which credentials are injected into the sandbox environment.

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

            if msg.get("type") == "assistant":
                # Extract token usage from assistant messages
                usage = msg.get("message", {}).get("usage", {})
                if usage:
                    input_tokens = (
                        usage.get("input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                    )
                    output_tokens = usage.get("output_tokens", 0)

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
            elif msg.get("type") == "result":
                if msg.get("result"):
                    lines.append(msg["result"])
                exit_code = 1 if msg.get("is_error") else 0
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


# ── Capability request parsing ────────────────────────────────────────

# Allowed capabilities that can be auto-granted from BLOCKED.md requests.
# Anything not in this set requires manual user intervention.
_AUTO_GRANTABLE_CAPS = {"gh"}

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

        # Setup TUI for this feature
        if not self.headless:
            self.tui = TUI(phases, phase_deps, layout=self.layout, draining=self._draining)
            self.tui.start()

        self.log(f"=== Feature: {Path(spec_dir).name} ===")
        self.log(f"Remaining: {scheduler.remaining_count()} | Completed: {scheduler.completed_count()}")
        if validated_phases:
            self.log(f"Already validated: {', '.join(sorted(validated_phases))}")

        consecutive_noop = 0
        max_consecutive_noop = 20
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
            # Re-scan phase validation states (validation/review/re-validation lifecycle)
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

                # Pass any capabilities granted via BLOCKED.md auto-retry
                extra_caps = None
                if hasattr(self, '_granted_capabilities'):
                    extra_caps = self._granted_capabilities.get(task.id)

                proc = spawn_agent(task, prompt, log_path, stderr_path,
                                   extra_capabilities=extra_caps)

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
                        and any(t.status in (TaskStatus.PENDING, TaskStatus.REWORK) for t in p.tasks)
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
            proc.wait()
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
