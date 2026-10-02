"""Canonical pytest reporter for spec-kit projects.

Writes structured output matching the schema in
reference/templates/EXAMPLE-OUTPUT.md. The runner and fix-validate agents
read these files directly — do NOT diverge from the schema.

Install:
    1. Drop this file into your project as ``conftest.py`` (or import it
       from an existing ``conftest.py``).
    2. Add ``test-logs/`` to ``.gitignore``.
    3. Customise ``RUN_TYPE`` below (``unit`` | ``integration`` | ``e2e``)
       or set the ``TEST_TYPE`` env var.

Output layout (see EXAMPLE-OUTPUT.md for schema):
    test-logs/
      summary.json
      <type>/<timestamp>/
        summary.json
        failures/<sanitized-test-name>.log
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

RUN_TYPE = os.environ.get("TEST_TYPE", "integration")
PROJECT_ROOT = Path.cwd()
LOG_ROOT = PROJECT_ROOT / "test-logs"


def _sanitize(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]", "-", name)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:200]


def _now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


class SpecKitReporter:
    def __init__(self) -> None:
        self.start_time = 0.0
        self.results: list[dict[str, Any]] = []
        self.run_dir = LOG_ROOT / RUN_TYPE / _now_compact()
        self.failures_dir = self.run_dir / "failures"
        self.command = " ".join(sys.argv)

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        self.start_time = time.time()
        self.failures_dir.mkdir(parents=True, exist_ok=True)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo):
        outcome = yield
        report: pytest.TestReport = outcome.get_result()
        if report.when != "call" and not (report.when == "setup" and report.skipped):
            return

        full_name = report.nodeid
        try:
            file = str(Path(item.location[0]).resolve().relative_to(PROJECT_ROOT))
        except (ValueError, OSError):
            file = item.location[0]
        duration_ms = int(round(report.duration * 1000))

        entry: dict[str, Any] = {
            "name": full_name,
            "file": file,
            "status": "skipped",
            "duration_ms": duration_ms,
        }

        if report.passed:
            entry["status"] = "passed"
        elif report.failed:
            entry["status"] = "failed"
            log_name = f"{_sanitize(full_name)}.log"
            log_path = self.failures_dir / log_name
            body_lines = [
                f"Test: {full_name}",
                f"File: {file}",
                f"Duration: {duration_ms}ms",
                "",
                "FAILURE",
                str(report.longreprtext or report.longrepr or "(no detail)"),
            ]
            if report.capstderr:
                body_lines += ["", "CAPTURED STDERR", report.capstderr]
            if report.capstdout:
                body_lines += ["", "CAPTURED STDOUT", report.capstdout]
            log_path.write_text("\n".join(body_lines) + "\n")
            try:
                rel_log = str(log_path.relative_to(PROJECT_ROOT))
            except ValueError:
                rel_log = str(log_path)
            entry["failure_log"] = rel_log
            entry["error"] = {"message": str(report.longreprtext or "(no message)")}
        elif report.skipped:
            entry["status"] = "skipped"
            reason = ""
            if isinstance(report.longrepr, tuple) and len(report.longrepr) >= 3:
                reason = str(report.longrepr[2])
            entry["reason"] = reason

        # Deduplicate in case setup + call both emit for same nodeid.
        for existing in self.results:
            if existing["name"] == full_name:
                if existing["status"] == "passed" and entry["status"] != "passed":
                    existing.update(entry)
                return
        self.results.append(entry)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        duration_ms = int(round((time.time() - self.start_time) * 1000))
        by_status = {"passed": 0, "failed": 0, "skipped": 0}
        for r in self.results:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1

        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "type": RUN_TYPE,
            "pass": by_status["passed"],
            "fail": by_status["failed"],
            "skip": by_status["skipped"],
            "total": by_status["passed"] + by_status["failed"] + by_status["skipped"],
            "command": self.command,
            "failures": [r["name"] for r in self.results if r["status"] == "failed"],
            "results": self.results,
        }

        run_summary = self.run_dir / "summary.json"
        latest_summary = LOG_ROOT / "summary.json"
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(summary, indent=2)
        run_summary.write_text(payload)
        latest_summary.write_text(payload)

        if summary["total"] == 0:
            sys.stderr.write(
                "\n[spec-kit-reporter] FAIL: 0 tests executed. "
                "A vacuous pass is a failure. "
                "See reference/testing.md § Non-vacuous CI validation.\n"
            )
            session.exitstatus = 1 if exitstatus == 0 else exitstatus


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(SpecKitReporter(), name="spec-kit-reporter")
