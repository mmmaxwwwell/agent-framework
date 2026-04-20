#!/usr/bin/env python3
"""Cost + effectiveness reporter for spec-kit run-log.jsonl files.

Reads one or more run-log.jsonl files (written by parallel_runner.py's
`_write_event`), computes token usage by model, dollar cost, and prints
a detailed breakdown.  Also writes a machine-readable `cost-report.json`.

Usage:
    python3 cost_report.py <run-log.jsonl> [<run-log.jsonl> ...]
    python3 cost_report.py --all /path/to/specs   # scans specs/*/run-log.jsonl
    python3 cost_report.py --output cost-report.md <log>

Design principles:
- Any event missing `model` is assumed Opus (legacy default before we started
  tagging models on 2026-04-19).
- Input tokens are split into three buckets when available: fresh,
  cache_read, cache_create.  Old events with only `input_tokens` total are
  attributed to the `unknown` bucket (priced as fresh input — conservative).
- Costs use public Anthropic pricing as of April 2026.  Edit PRICING below
  if rates change.
- The script is read-only: it never modifies logs.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


# ── Pricing (USD per 1M tokens) ────────────────────────────────────────
# Source: Anthropic public pricing as of April 2026.  Edit if rates change.
PRICING = {
    "opus": {
        "input": 15.00,
        "cache_read": 1.50,
        "cache_create": 18.75,
        "output": 75.00,
    },
    "sonnet": {
        "input": 3.00,
        "cache_read": 0.30,
        "cache_create": 3.75,
        "output": 15.00,
    },
    "haiku": {
        "input": 0.80,
        "cache_read": 0.08,
        "cache_create": 1.00,
        "output": 4.00,
    },
}


def _pricing_family(model_id: str) -> str:
    """Map API model ids (e.g. 'claude-sonnet-4-6') → pricing key.
    Empty / unknown returns 'opus' per user's legacy-default rule."""
    m = (model_id or "").lower()
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return "opus"


# ── Event aggregation ──────────────────────────────────────────────────


@dataclass
class Bucket:
    count: int = 0
    input_tokens_fresh: int = 0
    input_tokens_cache_read: int = 0
    input_tokens_cache_create: int = 0
    output_tokens: int = 0
    duration_s: int = 0
    # Legacy events that only had a flat `input_tokens` — can't split.
    input_tokens_unknown: int = 0

    def add(self, ev: dict):
        self.count += 1
        has_breakdown = any(k in ev for k in (
            "input_tokens_fresh",
            "input_tokens_cache_read",
            "input_tokens_cache_create",
        ))
        if has_breakdown:
            self.input_tokens_fresh += int(ev.get("input_tokens_fresh", 0))
            self.input_tokens_cache_read += int(ev.get("input_tokens_cache_read", 0))
            self.input_tokens_cache_create += int(ev.get("input_tokens_cache_create", 0))
        else:
            self.input_tokens_unknown += int(ev.get("input_tokens", 0))
        self.output_tokens += int(ev.get("output_tokens", 0))
        self.duration_s += int(ev.get("duration_s", 0))

    @property
    def input_tokens_total(self) -> int:
        return (self.input_tokens_fresh + self.input_tokens_cache_read
                + self.input_tokens_cache_create + self.input_tokens_unknown)

    @property
    def tokens_total(self) -> int:
        return self.input_tokens_total + self.output_tokens

    def cost(self, family: str) -> float:
        p = PRICING.get(family, PRICING["opus"])
        return (
            self.input_tokens_fresh / 1_000_000 * p["input"]
            + self.input_tokens_unknown / 1_000_000 * p["input"]
            + self.input_tokens_cache_read / 1_000_000 * p["cache_read"]
            + self.input_tokens_cache_create / 1_000_000 * p["cache_create"]
            + self.output_tokens / 1_000_000 * p["output"]
        )


@dataclass
class Run:
    path: Path
    by_model: dict[str, Bucket] = field(default_factory=lambda: defaultdict(Bucket))
    by_task_prefix: dict[str, Bucket] = field(default_factory=lambda: defaultdict(Bucket))
    by_task_prefix_model: dict[tuple[str, str], Bucket] = field(
        default_factory=lambda: defaultdict(Bucket))
    total: Bucket = field(default_factory=Bucket)
    events: int = 0
    task_completes: int = 0
    missing_model_events: int = 0

    def add(self, ev: dict):
        self.events += 1
        if ev.get("event") not in ("task_complete", "vr_complete"):
            return
        self.task_completes += 1
        task_id = ev.get("task_id", "")
        model_id = ev.get("model", "") or ""
        if not model_id:
            self.missing_model_events += 1
        family = _pricing_family(model_id)

        self.total.add(ev)
        self.by_model[family].add(ev)

        prefix = _classify_task_prefix(task_id)
        self.by_task_prefix[prefix].add(ev)
        self.by_task_prefix_model[(prefix, family)].add(ev)


def _classify_task_prefix(task_id: str) -> str:
    """Group task_ids into readable buckets for reporting."""
    t = task_id or ""
    if t.startswith("VR-"):
        return "validate-review"
    if t.startswith("E2E-explore"):
        return "e2e-explore (legacy)"
    if t.startswith("E2E-planner"):
        return "e2e-planner"
    if t.startswith("E2E-executor"):
        return "e2e-executor"
    if t.startswith("E2E-diagnostic"):
        return "e2e-diagnostic"
    if t.startswith("E2E-verify"):
        return "e2e-verify"
    if t.startswith("E2E-fix"):
        return "e2e-fix"
    if t.startswith("E2E-research"):
        return "e2e-research"
    if t.startswith("E2E-supervisor") or t.startswith("E2E-crash-supervisor"):
        return "e2e-supervisor"
    if t.startswith("E2E-rejection-research"):
        return "e2e-rejection-research"
    if t.startswith("E2E-"):
        return "e2e-other"
    return "task"


# ── Loading ────────────────────────────────────────────────────────────


def load_run(path: Path) -> Run:
    run = Run(path=path)
    try:
        for raw in path.read_text().splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            run.add(ev)
    except OSError as e:
        print(f"warn: cannot read {path}: {e}", file=sys.stderr)
    return run


# ── Formatting ─────────────────────────────────────────────────────────


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def _fmt_money(x: float) -> str:
    if x >= 100:
        return f"${x:,.0f}"
    return f"${x:,.2f}"


def _fmt_duration(s: int) -> str:
    if s >= 3600:
        return f"{s//3600}h{(s%3600)//60}m"
    if s >= 60:
        return f"{s//60}m{s%60}s"
    return f"{s}s"


def _merge(dst: Bucket, src: Bucket):
    dst.count += src.count
    dst.input_tokens_fresh += src.input_tokens_fresh
    dst.input_tokens_cache_read += src.input_tokens_cache_read
    dst.input_tokens_cache_create += src.input_tokens_cache_create
    dst.input_tokens_unknown += src.input_tokens_unknown
    dst.output_tokens += src.output_tokens
    dst.duration_s += src.duration_s


# ── Rendering ──────────────────────────────────────────────────────────


def render_report(runs: list[Run]) -> str:
    lines: list[str] = []
    add = lines.append

    add("# Spec-Kit Cost & Effectiveness Report")
    add("")
    add(f"Runs analyzed: **{len(runs)}**")
    for r in runs:
        add(f"- {r.path}")
    add("")

    # Aggregate across all runs
    grand = Bucket()
    grand_by_model: dict[str, Bucket] = defaultdict(Bucket)
    grand_by_prefix: dict[str, Bucket] = defaultdict(Bucket)
    grand_by_prefix_model: dict[tuple[str, str], Bucket] = defaultdict(Bucket)
    total_events = 0
    total_completes = 0
    missing_model_total = 0
    for r in runs:
        total_events += r.events
        total_completes += r.task_completes
        missing_model_total += r.missing_model_events
        _merge(grand, r.total)
        for k, b in r.by_model.items():
            _merge(grand_by_model[k], b)
        for k, b in r.by_task_prefix.items():
            _merge(grand_by_prefix[k], b)
        for k, b in r.by_task_prefix_model.items():
            _merge(grand_by_prefix_model[k], b)

    grand_cost = sum(grand_by_model[m].cost(m) for m in grand_by_model)

    add("## Grand total")
    add("")
    add(f"- **Events processed**: {total_events:,}")
    add(f"- **Agent completions**: {total_completes:,}")
    add(f"- **Total tokens**: {_fmt_tokens(grand.tokens_total)} "
        f"(in: {_fmt_tokens(grand.input_tokens_total)}, "
        f"out: {_fmt_tokens(grand.output_tokens)})")
    add(f"- **Estimated cost**: **{_fmt_money(grand_cost)}**")
    add(f"- **Total agent wall-clock**: {_fmt_duration(grand.duration_s)}")
    add("")

    # By model
    add("## Cost & tokens by model")
    add("")
    add("| Model | Events | Input (fresh) | Cache read | Cache create | Output | Total tok | Cost | % of $ |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for family in ("opus", "sonnet", "haiku"):
        b = grand_by_model.get(family)
        if not b or b.count == 0:
            continue
        c = b.cost(family)
        pct = (c / grand_cost * 100) if grand_cost > 0 else 0
        fresh_total = b.input_tokens_fresh + b.input_tokens_unknown
        legacy_note = ""
        if b.input_tokens_unknown and b.input_tokens_fresh:
            legacy_note = f" ({_fmt_tokens(b.input_tokens_unknown)} legacy)"
        elif b.input_tokens_unknown:
            legacy_note = " (legacy)"
        add(f"| {family} | {b.count} | {_fmt_tokens(fresh_total)}{legacy_note} "
            f"| {_fmt_tokens(b.input_tokens_cache_read)} "
            f"| {_fmt_tokens(b.input_tokens_cache_create)} "
            f"| {_fmt_tokens(b.output_tokens)} "
            f"| {_fmt_tokens(b.tokens_total)} "
            f"| {_fmt_money(c)} | {pct:.1f}% |")
    add("")

    # By phase
    add("## Cost & tokens by phase")
    add("")
    add("Grouped by task-id prefix so you can see where the money goes.")
    add("")
    add("| Phase | Events | Tokens | Cost | Cost % | Avg tok/event | Avg $/event |")
    add("|---|---:|---:|---:|---:|---:|---:|")
    prefix_rows = []
    for prefix, b in grand_by_prefix.items():
        cost = sum(
            sub.cost(fam)
            for (p, fam), sub in grand_by_prefix_model.items()
            if p == prefix
        )
        prefix_rows.append((prefix, b, cost))
    prefix_rows.sort(key=lambda row: row[2], reverse=True)
    for prefix, b, cost in prefix_rows:
        pct = (cost / grand_cost * 100) if grand_cost > 0 else 0
        avg_tok = b.tokens_total // b.count if b.count else 0
        avg_cost = cost / b.count if b.count else 0
        add(f"| {prefix} | {b.count} | {_fmt_tokens(b.tokens_total)} "
            f"| {_fmt_money(cost)} | {pct:.1f}% "
            f"| {_fmt_tokens(avg_tok)} | {_fmt_money(avg_cost)} |")
    add("")

    # Phase x model
    add("## Phase × model matrix (cost)")
    add("")
    add("Shows where each model is actually being spent. Useful for checking")
    add("whether model-choice changes (e.g. verify → Sonnet) landed correctly.")
    add("")
    add("| Phase | Opus | Sonnet | Haiku | Total |")
    add("|---|---:|---:|---:|---:|")
    for prefix, _, _ in prefix_rows:
        row_cost = {"opus": 0.0, "sonnet": 0.0, "haiku": 0.0}
        for (p, fam), sub in grand_by_prefix_model.items():
            if p == prefix:
                row_cost[fam] = row_cost.get(fam, 0.0) + sub.cost(fam)
        total = sum(row_cost.values())
        add(f"| {prefix} "
            f"| {_fmt_money(row_cost['opus']) if row_cost['opus'] else '—'} "
            f"| {_fmt_money(row_cost['sonnet']) if row_cost['sonnet'] else '—'} "
            f"| {_fmt_money(row_cost['haiku']) if row_cost['haiku'] else '—'} "
            f"| {_fmt_money(total)} |")
    add("")

    # Per-run breakdown
    if len(runs) > 1:
        add("## Per-run breakdown")
        add("")
        add("| Run | Completions | Tokens | Cost | Wall-clock |")
        add("|---|---:|---:|---:|---:|")
        for r in runs:
            cost = sum(r.by_model[m].cost(m) for m in r.by_model)
            add(f"| {r.path.parent.name}/{r.path.name} "
                f"| {r.task_completes} "
                f"| {_fmt_tokens(r.total.tokens_total)} "
                f"| {_fmt_money(cost)} "
                f"| {_fmt_duration(r.total.duration_s)} |")
        add("")

    # Effectiveness signals
    add("## Effectiveness signals")
    add("")
    e2e_buckets = [(p, b, c) for p, b, c in prefix_rows if p.startswith("e2e")]
    if e2e_buckets:
        e2e_cost = sum(c for _, _, c in e2e_buckets)
        e2e_tok = sum(b.tokens_total for _, b, _ in e2e_buckets)
        add(f"- **E2E loop spend**: {_fmt_money(e2e_cost)} "
            f"({_fmt_tokens(e2e_tok)} tok) across {len(e2e_buckets)} phases")

        planner_cost = sum(c for p, _, c in e2e_buckets if p == "e2e-planner")
        executor_cost = sum(c for p, _, c in e2e_buckets if p == "e2e-executor")
        legacy_explore_cost = sum(c for p, _, c in e2e_buckets if p == "e2e-explore (legacy)")
        if planner_cost or executor_cost:
            add(f"- **Planner/executor split**: planner {_fmt_money(planner_cost)}, "
                f"executor {_fmt_money(executor_cost)} "
                f"(combined {_fmt_money(planner_cost + executor_cost)})")
            if legacy_explore_cost:
                add(f"- **Legacy explore baseline**: {_fmt_money(legacy_explore_cost)} "
                    f"— compare against combined planner+executor")

        fix_cost = sum(c for p, _, c in e2e_buckets if p == "e2e-fix")
        verify_cost = sum(c for p, _, c in e2e_buckets if p == "e2e-verify")
        if fix_cost or verify_cost:
            add(f"- **Fix vs verify**: fix {_fmt_money(fix_cost)}, verify {_fmt_money(verify_cost)}")

        # Model mix checks
        def _opus_pct(phase: str) -> float | None:
            o = grand_by_prefix_model.get((phase, "opus"))
            s = grand_by_prefix_model.get((phase, "sonnet"))
            if not (o or s):
                return None
            o_cost = o.cost("opus") if o else 0.0
            s_cost = s.cost("sonnet") if s else 0.0
            if (o_cost + s_cost) == 0:
                return None
            return o_cost / (o_cost + s_cost) * 100

        exec_opus = _opus_pct("e2e-executor")
        if exec_opus is not None:
            add(f"- **Executor Opus%**: {exec_opus:.0f}% "
                f"(target: 0% — executor should be Sonnet)")
        verify_opus = _opus_pct("e2e-verify")
        if verify_opus is not None:
            add(f"- **Verify Opus%**: {verify_opus:.0f}% "
                f"(target: 0% after 2026-04-19 change)")

    # Warnings
    if grand.input_tokens_unknown > 0:
        pct = grand.input_tokens_unknown / max(1, grand.input_tokens_total) * 100
        add("")
        add(f"> **Legacy data note**: {_fmt_tokens(grand.input_tokens_unknown)} input tokens "
            f"({pct:.0f}%) predate the cache breakdown. Priced as fresh input "
            f"(no cache discount) — may overestimate cost for agents with high cache hit rates.")

    if missing_model_total > 0:
        pct = missing_model_total / max(1, total_completes) * 100
        add("")
        add(f"> **Assumed-Opus note**: {missing_model_total:,} of {total_completes:,} "
            f"completions ({pct:.0f}%) have no `model` field and were assumed Opus "
            f"(legacy default before 2026-04-19).")

    return "\n".join(lines)


def render_json(runs: list[Run]) -> dict:
    grand_by_model: dict[str, Bucket] = defaultdict(Bucket)
    grand_by_prefix_model: dict[tuple[str, str], Bucket] = defaultdict(Bucket)
    grand_total = Bucket()
    for r in runs:
        _merge(grand_total, r.total)
        for k, b in r.by_model.items():
            _merge(grand_by_model[k], b)
        for k, b in r.by_task_prefix_model.items():
            _merge(grand_by_prefix_model[k], b)

    out: dict = {
        "runs": [str(r.path) for r in runs],
        "grand_total": {
            "input_tokens_fresh": grand_total.input_tokens_fresh,
            "input_tokens_cache_read": grand_total.input_tokens_cache_read,
            "input_tokens_cache_create": grand_total.input_tokens_cache_create,
            "input_tokens_unknown": grand_total.input_tokens_unknown,
            "output_tokens": grand_total.output_tokens,
            "tokens_total": grand_total.tokens_total,
            "duration_s": grand_total.duration_s,
            "cost_usd": sum(grand_by_model[m].cost(m) for m in grand_by_model),
        },
        "by_model": {},
        "by_phase_and_model": {},
    }
    for fam, b in grand_by_model.items():
        out["by_model"][fam] = {
            "count": b.count,
            "input_tokens_fresh": b.input_tokens_fresh,
            "input_tokens_cache_read": b.input_tokens_cache_read,
            "input_tokens_cache_create": b.input_tokens_cache_create,
            "input_tokens_unknown": b.input_tokens_unknown,
            "output_tokens": b.output_tokens,
            "tokens_total": b.tokens_total,
            "cost_usd": b.cost(fam),
        }
    for (phase, fam), b in grand_by_prefix_model.items():
        out["by_phase_and_model"].setdefault(phase, {})[fam] = {
            "count": b.count,
            "tokens_total": b.tokens_total,
            "cost_usd": b.cost(fam),
        }
    return out


# ── CLI ────────────────────────────────────────────────────────────────


def _expand_paths(paths: list[str], scan_all: str | None) -> list[Path]:
    out: list[Path] = []
    if scan_all:
        root = Path(scan_all)
        out.extend(sorted(root.glob("*/run-log.jsonl")))
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            out.extend(sorted(pp.glob("*/run-log.jsonl")))
        else:
            out.append(pp)
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in out:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        uniq.append(p)
    return uniq


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("logs", nargs="*", help="run-log.jsonl file(s) or directory of specs")
    ap.add_argument("--all", metavar="SPECS_DIR",
                    help="scan SPECS_DIR/*/run-log.jsonl")
    ap.add_argument("--output", "-o", default="cost-report.md",
                    help="markdown report path (default: cost-report.md)")
    ap.add_argument("--json-output", default="cost-report.json",
                    help="JSON report path (default: cost-report.json)")
    ap.add_argument("--no-display", action="store_true",
                    help="write files only, skip stdout printing")
    args = ap.parse_args()

    paths = _expand_paths(args.logs, args.all)
    if not paths:
        print("error: no run-log.jsonl paths given (use positional args or --all SPECS_DIR)",
              file=sys.stderr)
        return 2

    runs = [load_run(p) for p in paths]
    report_md = render_report(runs)
    report_json = render_json(runs)

    Path(args.output).write_text(report_md)
    Path(args.json_output).write_text(json.dumps(report_json, indent=2))

    if not args.no_display:
        print(report_md)
        print()
        print(f"# Written: {args.output} ({len(report_md)} bytes), {args.json_output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
