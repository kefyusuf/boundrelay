package cli

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"boundrelay-m3-eino/internal/fixtures"
)

func root(t *testing.T) string {
	t.Helper()
	repoRoot, err := fixtures.FindRepoRoot()
	if err != nil {
		t.Fatalf("find repo root: %v", err)
	}
	return repoRoot
}

func TestParseCLIOptions(t *testing.T) {
	options, err := ParseCLIOptions([]string{"--case", "parallel-complete", "--trace", "t.jsonl"})
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if options.Mode != "corrected" || options.CaseID != "parallel-complete" || options.TracePath != "t.jsonl" {
		t.Fatalf("defaults drifted: %+v", options)
	}
	if _, err := ParseCLIOptions([]string{"--mode", "naive", "--case", "c", "--trace", "t"}); err != nil {
		t.Fatalf("naive mode rejected: %v", err)
	}
	for _, bad := range [][]string{
		{"--case", "c"},  // missing --trace
		{"--trace", "t"}, // missing --case
		{"--case", "c", "--trace", "t", "--mode", "bogus"}, // bad mode
		{"--case", "c", "--trace", "t", "--extra", "x"},    // unknown option
		{"--case", "c", "--case", "c2", "--trace", "t"},    // duplicate
		{"--case", "--trace", "t"},                         // missing value
	} {
		if _, err := ParseCLIOptions(bad); err == nil {
			t.Fatalf("bad args accepted: %v", bad)
		}
	}
}

func TestRunCLIDomainResultsExitZero(t *testing.T) {
	for _, testCase := range []struct {
		caseID     string
		wantStatus string
	}{
		{"parallel-complete", "SUCCEEDED"},
		{"parallel-partial-failure", "PARTIAL"},
		{"parallel-all-failed", "FAILED"},
		{"sequential-complete", "SUCCEEDED"},
	} {
		t.Run(testCase.caseID, func(t *testing.T) {
			var stdout, stderr bytes.Buffer
			tracePath := t.TempDir() + "\\trace.jsonl"
			code := RunCLI([]string{"--case", testCase.caseID, "--trace", tracePath},
				&stdout, &stderr)
			if code != 0 {
				t.Fatalf("exit %d, stderr: %s", code, stderr.String())
			}
			lines := strings.Split(strings.TrimSpace(stdout.String()), "\n")
			if len(lines) != 1 || lines[0] == "" {
				t.Fatalf("expected exactly one JSON line, got %q", stdout.String())
			}
			var result map[string]any
			if err := json.Unmarshal([]byte(lines[0]), &result); err != nil {
				t.Fatalf("result line is not JSON: %v", err)
			}
			if result["status"] != testCase.wantStatus {
				t.Fatalf("status = %v, want %s", result["status"], testCase.wantStatus)
			}
			if result["run_id"] == "" || result["trace_path"] == "" {
				t.Fatal("result line misses run-scoped fields")
			}
		})
	}
}

func TestRunCLIToolingFailuresExitTwo(t *testing.T) {
	for _, testCase := range []struct {
		name string
		args []string
	}{
		{"unknown case", []string{"--case", "no-such-case", "--trace", "t.jsonl"}},
		{"missing trace", []string{"--case", "parallel-complete"}},
		{"unknown option", []string{"--case", "parallel-complete", "--trace", "t", "--extra", "x"}},
		{"naive declared failure", []string{"--mode", "naive", "--case", "parallel-partial-failure", "--trace", "t.jsonl"}},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			var stdout, stderr bytes.Buffer
			code := RunCLI(testCase.args, &stdout, &stderr)
			if code != 2 {
				t.Fatalf("exit %d, want 2 (stderr: %s)", code, stderr.String())
			}
			if strings.TrimSpace(stdout.String()) != "" {
				t.Fatalf("no result line on tooling failure, got %q", stdout.String())
			}
			if strings.TrimSpace(stderr.String()) == "" {
				t.Fatal("stderr diagnostic required")
			}
		})
	}
}

func TestRunCLINaiveDomainPath(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := RunCLI([]string{"--mode", "naive", "--case", "parallel-complete", "--trace", t.TempDir() + "\\naive.jsonl"},
		&stdout, &stderr)
	if code != 0 {
		t.Fatalf("exit %d, stderr: %s", code, stderr.String())
	}
	var result map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(stdout.String())), &result); err != nil {
		t.Fatalf("naive result line is not JSON: %v", err)
	}
	if result["peak_concurrency"] != float64(3) {
		t.Fatalf("naive peak = %v, want the uncapped 3", result["peak_concurrency"])
	}
}
