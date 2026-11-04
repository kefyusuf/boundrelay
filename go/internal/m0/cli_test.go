package m0

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func tempTrace(t *testing.T) string {
	t.Helper()
	return filepath.Join(t.TempDir(), "trace.jsonl")
}

func nonblankLines(text string) []string {
	var lines []string
	for _, line := range strings.Split(text, "\n") {
		if strings.TrimSpace(line) != "" {
			lines = append(lines, line)
		}
	}
	return lines
}

func TestParseCLIOptions(t *testing.T) {
	options, err := ParseCLIOptions([]string{
		"--mode", "model", "--case", "billing-duplicate-charge", "--trace", "out.jsonl"})
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if options.Mode != "model" || options.CaseID != "billing-duplicate-charge" ||
		options.TracePath != "out.jsonl" {
		t.Fatalf("options: %+v", options)
	}
}

func TestParseCLIOptionsRejects(t *testing.T) {
	cases := []struct {
		name string
		args []string
		frag string
	}{
		{"unknown option", []string{"--mode", "model", "--casez", "c", "--trace", "t"}, "unexpected argument"},
		{"duplicate option", []string{"--mode", "model", "--mode", "deterministic", "--case", "c", "--trace", "t"}, "duplicate option"},
		{"missing value", []string{"--mode", "model", "--case", "--trace", "t"}, "missing required option"},
		{"trailing option name", []string{"--mode", "model", "--case", "c", "--trace"}, "missing required option"},
		{"missing option", []string{"--mode", "model", "--case", "c"}, "missing required option"},
		{"no arguments", nil, "missing required option"},
		{"bad mode", []string{"--mode", "auto", "--case", "c", "--trace", "t"}, "--mode must be deterministic or model"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := ParseCLIOptions(tc.args); err == nil || !strings.Contains(err.Error(), tc.frag) {
				t.Fatalf("expected error containing %q, got %v", tc.frag, err)
			}
		})
	}
}

func TestRunCLI(t *testing.T) {
	tracePath := tempTrace(t)
	var stdout, stderr bytes.Buffer
	code := RunCLI([]string{"--mode", "deterministic", "--case", "billing-duplicate-charge",
		"--trace", tracePath}, &stdout, &stderr)
	if code != 0 {
		t.Fatalf("exit code %d, stderr: %s", code, stderr.String())
	}
	lines := nonblankLines(stdout.String())
	if len(lines) != 1 {
		t.Fatalf("stdout must carry exactly one nonblank line, got %d: %q", len(lines), stdout.String())
	}
	var result map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &result); err != nil {
		t.Fatalf("stdout line not JSON: %v", err)
	}
	if result["status"] != "SUCCEEDED" || result["scenario_id"] != "support-triage" {
		t.Fatalf("result: %v", result)
	}
	if _, err := os.Stat(tracePath); err != nil {
		t.Fatalf("trace file: %v", err)
	}
}

func TestRunCLIToolingError(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := RunCLI([]string{"--mode", "model", "--case", "no-such-case",
		"--trace", tempTrace(t)}, &stdout, &stderr)
	if code != 2 {
		t.Fatalf("tooling errors must exit 2, got %d", code)
	}
	if len(nonblankLines(stdout.String())) != 0 {
		t.Fatalf("tooling errors must not write stdout: %q", stdout.String())
	}
	if stderr.String() == "" {
		t.Fatal("tooling errors must diagnose on stderr")
	}
}

func TestRunCLIBadGrammar(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := RunCLI([]string{"--modez", "model", "--case", "c", "--trace", "t"}, &stdout, &stderr)
	if code != 2 || stderr.String() == "" {
		t.Fatalf("bad grammar must exit 2 with stderr, got %d %q", code, stderr.String())
	}
}
