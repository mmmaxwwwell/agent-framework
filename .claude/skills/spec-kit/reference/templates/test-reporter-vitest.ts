/**
 * Canonical Vitest reporter for spec-kit projects.
 *
 * Writes structured output matching the schema in
 * reference/templates/EXAMPLE-OUTPUT.md. The runner and fix-validate agents
 * read these files directly — do NOT diverge from the schema.
 *
 * Install:
 *   1. Drop this file into your project (e.g. `src/test-reporter.ts`).
 *   2. In `vitest.config.ts`:
 *
 *      import { defineConfig } from "vitest/config";
 *      export default defineConfig({
 *        test: {
 *          reporters: ["default", "./src/test-reporter.ts"],
 *        },
 *      });
 *
 *   3. Add `test-logs/` to `.gitignore`.
 *
 * Output layout (see EXAMPLE-OUTPUT.md for schema):
 *   test-logs/
 *     summary.json
 *     <type>/<timestamp>/
 *       summary.json
 *       failures/<sanitized-test-name>.log
 *
 * Customise `RUN_TYPE` below (`unit` | `integration` | `e2e`).
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import type { File, Reporter, Task, TaskResult } from "vitest";

const RUN_TYPE = process.env.TEST_TYPE ?? "integration";
const PROJECT_ROOT = process.cwd();
const LOG_ROOT = join(PROJECT_ROOT, "test-logs");

type Status = "passed" | "failed" | "skipped";

interface ResultEntry {
  name: string;
  file: string;
  status: Status;
  duration_ms: number;
  failure_log?: string;
  error?: { message: string; expected?: string; actual?: string; stack?: string };
  reason?: string;
}

interface Summary {
  timestamp: string;
  duration_ms: number;
  type: string;
  pass: number;
  fail: number;
  skip: number;
  total: number;
  command: string;
  failures: string[];
  results: ResultEntry[];
}

function sanitizeName(name: string): string {
  return name
    .replace(/[^A-Za-z0-9._-]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 200);
}

function nowIsoCompact(): string {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function taskFullName(task: Task): string {
  const chain: string[] = [];
  let cur: Task | undefined = task;
  while (cur) {
    chain.unshift(cur.name);
    cur = cur.suite as Task | undefined;
  }
  return chain.join(" > ");
}

function mapStatus(result: TaskResult | undefined, task: Task): Status {
  if (task.mode === "skip" || task.mode === "todo") return "skipped";
  if (!result) return "skipped";
  if (result.state === "pass") return "passed";
  if (result.state === "fail") return "failed";
  if (result.state === "skip" || result.state === "todo") return "skipped";
  return "skipped";
}

export default class SpecKitReporter implements Reporter {
  private startTime = 0;

  onInit(): void {
    this.startTime = Date.now();
  }

  onFinished(files: File[] = []): void {
    const timestamp = new Date().toISOString();
    const runDir = join(LOG_ROOT, RUN_TYPE, nowIsoCompact());
    const failuresDir = join(runDir, "failures");
    mkdirSync(failuresDir, { recursive: true });

    const results: ResultEntry[] = [];
    let pass = 0;
    let fail = 0;
    let skip = 0;

    const walk = (tasks: Task[], filePath: string): void => {
      for (const task of tasks) {
        if (task.type === "suite" && task.tasks) {
          walk(task.tasks, filePath);
          continue;
        }
        if (task.type !== "test") continue;

        const status = mapStatus(task.result, task);
        const fullName = taskFullName(task);
        const relFile = relative(PROJECT_ROOT, filePath);
        const duration_ms = Math.round(task.result?.duration ?? 0);

        const entry: ResultEntry = {
          name: fullName,
          file: relFile,
          status,
          duration_ms,
        };

        if (status === "passed") pass++;
        else if (status === "failed") {
          fail++;
          const err = task.result?.errors?.[0];
          const logName = `${sanitizeName(fullName)}.log`;
          const logPath = join(failuresDir, logName);
          const logRel = relative(PROJECT_ROOT, logPath);
          entry.failure_log = logRel;
          entry.error = {
            message: err?.message ?? "(no message)",
            expected: err?.expected != null ? String(err.expected) : undefined,
            actual: err?.actual != null ? String(err.actual) : undefined,
            stack: err?.stack,
          };
          const body = [
            `Test: ${fullName}`,
            `File: ${relFile}`,
            `Duration: ${duration_ms}ms`,
            "",
            "ASSERTION FAILURE",
            `  Message:  ${err?.message ?? "(no message)"}`,
            err?.expected != null ? `  Expected: ${String(err.expected)}` : "",
            err?.actual != null ? `  Actual:   ${String(err.actual)}` : "",
            "",
            "STACK TRACE",
            err?.stack ?? "(no stack)",
          ]
            .filter(Boolean)
            .join("\n");
          writeFileSync(logPath, body + "\n");
        } else {
          skip++;
          entry.reason = (task.result as { note?: string } | undefined)?.note ?? "";
        }

        results.push(entry);
      }
    };

    for (const file of files) {
      walk(file.tasks, file.filepath);
    }

    const summary: Summary = {
      timestamp,
      duration_ms: Date.now() - this.startTime,
      type: RUN_TYPE,
      pass,
      fail,
      skip,
      total: pass + fail + skip,
      command: process.env.npm_lifecycle_script ?? process.argv.slice(1).join(" "),
      failures: results.filter((r) => r.status === "failed").map((r) => r.name),
      results,
    };

    const runSummaryPath = join(runDir, "summary.json");
    const latestSummaryPath = join(LOG_ROOT, "summary.json");
    mkdirSync(dirname(latestSummaryPath), { recursive: true });
    writeFileSync(runSummaryPath, JSON.stringify(summary, null, 2));
    writeFileSync(latestSummaryPath, JSON.stringify(summary, null, 2));

    if (summary.total === 0) {
      console.error(
        "\n[spec-kit-reporter] FAIL: 0 tests executed. A vacuous pass is a failure. " +
          "See reference/testing.md § Non-vacuous CI validation.",
      );
      process.exitCode = 1;
    }
  }
}

// Silence unused-import warnings when bundlers tree-shake types.
export type { Reporter };
void resolve;
