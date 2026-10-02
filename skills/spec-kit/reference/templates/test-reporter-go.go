// Canonical Go test reporter for spec-kit projects.
//
// Go's testing package doesn't support custom reporters. Instead, this
// tool reads the JSON stream from `go test -json` and converts it to the
// canonical spec-kit schema documented in
// reference/templates/EXAMPLE-OUTPUT.md. The runner and fix-validate
// agents read the output files directly — do NOT diverge from the schema.
//
// Install:
//  1. Drop this file into tools/test-reporter/main.go
//  2. In your Makefile or test script, pipe `go test -json` through it:
//
//       go test -json ./... | go run ./tools/test-reporter
//
//  3. Add `test-logs/` to .gitignore.
//  4. Customise the RUN_TYPE env var (`unit` | `integration` | `e2e`).
//
// Output layout (see EXAMPLE-OUTPUT.md for schema):
//
//	test-logs/
//	  summary.json
//	  <type>/<timestamp>/
//	    summary.json
//	    failures/<sanitized-test-name>.log
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

type goEvent struct {
	Time    time.Time `json:"Time"`
	Action  string    `json:"Action"`
	Package string    `json:"Package"`
	Test    string    `json:"Test,omitempty"`
	Elapsed float64   `json:"Elapsed,omitempty"`
	Output  string    `json:"Output,omitempty"`
}

type result struct {
	Name        string     `json:"name"`
	File        string     `json:"file"`
	Status      string     `json:"status"`
	DurationMs  int64      `json:"duration_ms"`
	FailureLog  string     `json:"failure_log,omitempty"`
	Error       *errorInfo `json:"error,omitempty"`
	Reason      string     `json:"reason,omitempty"`
	outputLines []string
}

type errorInfo struct {
	Message string `json:"message"`
}

type summary struct {
	Timestamp  string   `json:"timestamp"`
	DurationMs int64    `json:"duration_ms"`
	Type       string   `json:"type"`
	Pass       int      `json:"pass"`
	Fail       int      `json:"fail"`
	Skip       int      `json:"skip"`
	Total      int      `json:"total"`
	Command    string   `json:"command"`
	Failures   []string `json:"failures"`
	Results    []result `json:"results"`
}

var sanitizeRe = regexp.MustCompile(`[^A-Za-z0-9._-]`)
var dashRe = regexp.MustCompile(`-+`)

func sanitize(s string) string {
	out := sanitizeRe.ReplaceAllString(s, "-")
	out = dashRe.ReplaceAllString(out, "-")
	out = strings.Trim(out, "-")
	if len(out) > 200 {
		out = out[:200]
	}
	return out
}

func nowCompact() string {
	return time.Now().UTC().Format("2006-01-02T15-04-05Z")
}

func main() {
	runType := os.Getenv("TEST_TYPE")
	if runType == "" {
		runType = "integration"
	}
	logRoot := "test-logs"
	runDir := filepath.Join(logRoot, runType, nowCompact())
	failuresDir := filepath.Join(runDir, "failures")
	if err := os.MkdirAll(failuresDir, 0o755); err != nil {
		fmt.Fprintln(os.Stderr, "spec-kit-reporter:", err)
		os.Exit(2)
	}

	results := map[string]*result{}
	start := time.Now()

	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 1024*1024), 16*1024*1024)
	for scanner.Scan() {
		var ev goEvent
		if err := json.Unmarshal(scanner.Bytes(), &ev); err != nil {
			// Non-JSON line (e.g. build error). Preserve to stderr.
			fmt.Fprintln(os.Stderr, scanner.Text())
			continue
		}
		if ev.Test == "" {
			continue // package-level event
		}
		key := ev.Package + "." + ev.Test
		r, ok := results[key]
		if !ok {
			r = &result{
				Name:   fmt.Sprintf("%s.%s", ev.Package, ev.Test),
				File:   ev.Package,
				Status: "skipped",
			}
			results[key] = r
		}
		switch ev.Action {
		case "output":
			r.outputLines = append(r.outputLines, strings.TrimRight(ev.Output, "\n"))
		case "pass":
			r.Status = "passed"
			r.DurationMs = int64(ev.Elapsed * 1000)
		case "fail":
			r.Status = "failed"
			r.DurationMs = int64(ev.Elapsed * 1000)
		case "skip":
			r.Status = "skipped"
			r.DurationMs = int64(ev.Elapsed * 1000)
		}
	}
	if err := scanner.Err(); err != nil {
		fmt.Fprintln(os.Stderr, "spec-kit-reporter:", err)
	}

	sum := summary{
		Timestamp:  time.Now().UTC().Format(time.RFC3339Nano),
		DurationMs: time.Since(start).Milliseconds(),
		Type:       runType,
		Command:    "go test -json ./...",
		Results:    make([]result, 0, len(results)),
	}

	for _, r := range results {
		switch r.Status {
		case "passed":
			sum.Pass++
		case "failed":
			sum.Fail++
			logName := sanitize(r.Name) + ".log"
			logPath := filepath.Join(failuresDir, logName)
			body := strings.Join([]string{
				"Test: " + r.Name,
				"File: " + r.File,
				fmt.Sprintf("Duration: %dms", r.DurationMs),
				"",
				"FAILURE",
				strings.Join(r.outputLines, "\n"),
			}, "\n") + "\n"
			if err := os.WriteFile(logPath, []byte(body), 0o644); err == nil {
				r.FailureLog = logPath
			}
			msg := r.Name
			if len(r.outputLines) > 0 {
				msg = r.outputLines[len(r.outputLines)-1]
			}
			r.Error = &errorInfo{Message: msg}
			sum.Failures = append(sum.Failures, r.Name)
		case "skipped":
			sum.Skip++
			if len(r.outputLines) > 0 {
				r.Reason = r.outputLines[len(r.outputLines)-1]
			}
		}
		r.outputLines = nil
		sum.Results = append(sum.Results, *r)
	}
	sum.Total = sum.Pass + sum.Fail + sum.Skip

	payload, _ := json.MarshalIndent(sum, "", "  ")
	_ = os.WriteFile(filepath.Join(runDir, "summary.json"), payload, 0o644)
	_ = os.WriteFile(filepath.Join(logRoot, "summary.json"), payload, 0o644)

	if sum.Total == 0 {
		fmt.Fprintln(os.Stderr,
			"[spec-kit-reporter] FAIL: 0 tests executed. A vacuous pass is a failure. "+
				"See reference/testing.md § Non-vacuous CI validation.")
		os.Exit(1)
	}
	if sum.Fail > 0 {
		os.Exit(1)
	}
}
