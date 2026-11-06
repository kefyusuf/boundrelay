package m2

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
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
		"--mode", "model", "--case", "model-technical-handoff", "--trace", "out.jsonl"})
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if options.Mode != "model" || options.CaseID != "model-technical-handoff" ||
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
		{"unknown option", []string{"--mode", "code", "--casez", "c", "--trace", "t"}, "unexpected argument"},
		{"duplicate option", []string{"--mode", "code", "--mode", "model", "--case", "c", "--trace", "t"}, "duplicate option"},
		{"missing value", []string{"--mode", "code", "--case", "--trace", "t"}, "missing required option"},
		{"trailing option name", []string{"--mode", "code", "--case", "c", "--trace"}, "missing required option"},
		{"missing option", []string{"--mode", "code", "--case", "c"}, "missing required option"},
		{"no arguments", nil, "missing required option"},
		{"bad mode", []string{"--mode", "auto", "--case", "c", "--trace", "t"}, "--mode must be code or model"},
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
	code := RunCLI([]string{"--mode", "model", "--case", "model-technical-handoff",
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
	if result["status"] != "SUCCEEDED" || result["scenario_id"] != "support-handoff" ||
		result["router_mode"] != "model" {
		t.Fatalf("result: %v", result)
	}
	if _, err := os.Stat(tracePath); err != nil {
		t.Fatalf("trace file: %v", err)
	}
}

// TestRunCLIFailedResultIsDomain pins exit 0 for domain failures: the FAILED
// result is a valid outcome on stdout.
func TestRunCLIFailedResultIsDomain(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := RunCLI([]string{"--mode", "model", "--case", "handoff-context-loss",
		"--trace", tempTrace(t)}, &stdout, &stderr)
	if code != 0 {
		t.Fatalf("domain failures must exit 0, got %d, stderr: %s", code, stderr.String())
	}
	lines := nonblankLines(stdout.String())
	if len(lines) != 1 {
		t.Fatalf("stdout must carry exactly one nonblank line, got %d", len(lines))
	}
	var result map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &result); err != nil {
		t.Fatalf("stdout line not JSON: %v", err)
	}
	if result["status"] != "FAILED" || result["failure_code"] != "HANDOFF_CONTEXT_INVALID" ||
		result["specialist_invoked"] != false {
		t.Fatalf("result: %v", result)
	}
}

func TestRunCLIToolingError(t *testing.T) {
	cases := [][]string{
		{"--mode", "model", "--case", "no-such-case", "--trace", tempTrace(t)},
		{"--mode", "code", "--case", "model-technical-handoff", "--trace", tempTrace(t)},
		{"--modez", "code", "--case", "c", "--trace", "t"},
	}
	for _, args := range cases {
		var stdout, stderr bytes.Buffer
		code := RunCLI(args, &stdout, &stderr)
		if code != 2 {
			t.Fatalf("tooling errors must exit 2, got %d (args %v)", code, args)
		}
		if len(nonblankLines(stdout.String())) != 0 {
			t.Fatalf("tooling errors must not write stdout: %q", stdout.String())
		}
		if stderr.String() == "" {
			t.Fatal("tooling errors must diagnose on stderr")
		}
	}
}

// TestCLIMirrorsGoldenProjection pins the CLI result line, minus
// run_id/trace_path, against the golden result projection for one code-mode
// and one model-mode case (grammar-discipline smoke).
func TestCLIMirrorsGoldenProjection(t *testing.T) {
	goldens := loadGoldens(t)
	for _, key := range []string{"code-billing-handoff", "model-technical-handoff"} {
		t.Run(key, func(t *testing.T) {
			g := goldens[key]
			tracePath := tempTrace(t)
			var stdout, stderr bytes.Buffer
			code := RunCLI([]string{"--mode", modeForKey(key), "--case", key,
				"--trace", tracePath}, &stdout, &stderr)
			if code != 0 {
				t.Fatalf("exit code %d, stderr: %s", code, stderr.String())
			}
			var result map[string]any
			if err := json.Unmarshal([]byte(nonblankLines(stdout.String())[0]), &result); err != nil {
				t.Fatalf("stdout line not JSON: %v", err)
			}
			delete(result, "run_id")
			delete(result, "trace_path")
			if !reflect.DeepEqual(result, g.ResultProjection) {
				t.Fatalf("CLI projection divergence:\n got %v\nwant %v", result, g.ResultProjection)
			}
		})
	}
}
