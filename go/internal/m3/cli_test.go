package m3

import (
	"bytes"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
)

func TestParseM3CLIOptions(t *testing.T) {
	options, err := ParseCLIOptions([]string{
		"--mode", "parallel", "--case", "parallel-complete", "--trace", "out.jsonl"})
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if options.Mode != ModeParallel || options.CaseID != "parallel-complete" ||
		options.TracePath != "out.jsonl" {
		t.Fatalf("options: %+v", options)
	}
}

func TestParseM3CLIOptionsRejects(t *testing.T) {
	cases := []struct {
		name string
		args []string
		frag string
	}{
		{"unknown option", []string{"--mode", "parallel", "--casez", "c", "--trace", "t"}, "unexpected argument"},
		{"duplicate option", []string{"--mode", "parallel", "--mode", "sequential", "--case", "c", "--trace", "t"}, "duplicate option"},
		{"missing value", []string{"--mode", "parallel", "--case", "--trace", "t"}, "missing required option"},
		{"missing option", []string{"--mode", "parallel", "--case", "c"}, "missing required option"},
		{"no arguments", nil, "missing required option"},
		{"bad mode", []string{"--mode", "concurrent", "--case", "c", "--trace", "t"}, "--mode must be sequential or parallel"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := ParseCLIOptions(tc.args); err == nil || !strings.Contains(err.Error(), tc.frag) {
				t.Fatalf("expected error containing %q, got %v", tc.frag, err)
			}
		})
	}
}

func TestM3RunCLI(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := RunCLI([]string{"--mode", "sequential", "--case", "sequential-complete",
		"--trace", tempM3Trace(t)}, &stdout, &stderr)
	if code != 0 {
		t.Fatalf("exit code %d, stderr: %s", code, stderr.String())
	}
	lines := nonblankM3Lines(stdout.String())
	if len(lines) != 1 {
		t.Fatalf("stdout must carry exactly one nonblank line, got %d", len(lines))
	}
	var result map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &result); err != nil {
		t.Fatalf("stdout line not JSON: %v", err)
	}
	if result["status"] != "SUCCEEDED" || result["scenario_id"] != "order-brief" {
		t.Fatalf("result: %v", result)
	}
}

func TestM3RunCLIToolingError(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := RunCLI([]string{"--mode", "parallel", "--case", "no-such-case",
		"--trace", tempM3Trace(t)}, &stdout, &stderr)
	if code != 2 {
		t.Fatalf("tooling errors must exit 2, got %d", code)
	}
	if len(nonblankM3Lines(stdout.String())) != 0 {
		t.Fatalf("tooling errors must not write stdout: %q", stdout.String())
	}
	if stderr.String() == "" {
		t.Fatal("tooling errors must diagnose on stderr")
	}
}

func tempM3Trace(t *testing.T) string {
	t.Helper()
	return filepath.Join(t.TempDir(), "trace.jsonl")
}

func nonblankM3Lines(text string) []string {
	var lines []string
	for _, line := range strings.Split(text, "\n") {
		if strings.TrimSpace(line) != "" {
			lines = append(lines, line)
		}
	}
	return lines
}
