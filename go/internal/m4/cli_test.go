package m4

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// The CLI tests re-execute the test binary as a helper process so the crash
// control performs its real hard exit: exit 2, empty stdout, flushed trace
// prefix — exactly what the evaluator's phased flow observes.
const helperEnv = "BOUNDRELAY_M4_HELPER_PROCESS"

func TestMain(m *testing.M) {
	if os.Getenv(helperEnv) == "1" {
		os.Exit(RunCLI(os.Args[1:], os.Stdout, os.Stderr))
	}
	os.Exit(m.Run())
}

// runCLIProcess runs one CLI invocation in a helper subprocess.
func runCLIProcess(t *testing.T, args ...string) (int, string, string) {
	t.Helper()
	exe, err := os.Executable()
	if err != nil {
		t.Fatalf("executable: %v", err)
	}
	command := exec.Command(exe, args...)
	command.Env = append(os.Environ(), helperEnv+"=1")
	var stdout, stderr bytes.Buffer
	command.Stdout, command.Stderr = &stdout, &stderr
	runErr := command.Run()
	code := 0
	if runErr != nil {
		var exitError *exec.ExitError
		if !errors.As(runErr, &exitError) {
			t.Fatalf("helper run: %v", runErr)
		}
		code = exitError.ExitCode()
	}
	return code, stdout.String(), stderr.String()
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

func TestParseM4CLIOptions(t *testing.T) {
	options, err := ParseCLIOptions([]string{"--case", "parallel-clean-complete",
		"--trace", "t.jsonl", "--state-dir", "state"})
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if options.CaseID != "parallel-clean-complete" || options.TracePath != "t.jsonl" ||
		options.StateDir != "state" || options.Resume || options.ReplayFrom != "" {
		t.Fatalf("options: %+v", options)
	}
	options, err = ParseCLIOptions([]string{"--case", "c", "--trace", "t", "--state-dir", "s",
		"--resume"})
	if err != nil || !options.Resume {
		t.Fatalf("resume flag: %v %+v", err, options)
	}
	options, err = ParseCLIOptions([]string{"--case", "c", "--trace", "t", "--state-dir", "s",
		"--replay-from", "checkpoints/step-1.json"})
	if err != nil || options.ReplayFrom != "checkpoints/step-1.json" {
		t.Fatalf("replay option: %v %+v", err, options)
	}
}

func TestParseM4CLIOptionsRejects(t *testing.T) {
	cases := []struct {
		name string
		args []string
		frag string
	}{
		{"unknown option", []string{"--case", "c", "--trace", "t", "--state-dir", "s", "--mode", "parallel"}, "unexpected argument"},
		{"duplicate option", []string{"--case", "c", "--case", "d", "--trace", "t", "--state-dir", "s"}, "duplicate option"},
		{"duplicate flag", []string{"--case", "c", "--trace", "t", "--state-dir", "s", "--resume", "--resume"}, "duplicate option"},
		{"missing value", []string{"--case", "c", "--trace", "t", "--state-dir", "--resume"}, "missing required option"},
		{"missing option", []string{"--case", "c", "--trace", "t"}, "missing required option"},
		{"no arguments", nil, "missing required option"},
		{"resume and replay", []string{"--case", "c", "--trace", "t", "--state-dir", "s", "--resume", "--replay-from", "x"}, "mutually exclusive"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := ParseCLIOptions(tc.args); err == nil || !strings.Contains(err.Error(), tc.frag) {
				t.Fatalf("expected error containing %q, got %v", tc.frag, err)
			}
		})
	}
}

// TestM4RunCLI pins the domain outcome: one JSON result line, exit 0.
func TestM4RunCLI(t *testing.T) {
	root := testTempDir(t)
	code, stdout, stderr := runCLIProcess(t, "--case", "parallel-clean-complete",
		"--trace", filepath.Join(root, "trace.jsonl"),
		"--state-dir", filepath.Join(root, "state"))
	if code != 0 {
		t.Fatalf("exit code %d, stderr: %s", code, stderr)
	}
	lines := nonblankLines(stdout)
	if len(lines) != 1 {
		t.Fatalf("stdout must carry exactly one nonblank line, got %d", len(lines))
	}
	var result map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &result); err != nil {
		t.Fatalf("stdout line not JSON: %v", err)
	}
	if result["status"] != "SUCCEEDED" || result["scenario_id"] != "order-brief-recovery" {
		t.Fatalf("result: %v", result)
	}
}

// TestM4RunCLIToolingError pins exit 2 without a result line.
func TestM4RunCLIToolingError(t *testing.T) {
	root := testTempDir(t)
	code, stdout, stderr := runCLIProcess(t, "--case", "no-such-case",
		"--trace", filepath.Join(root, "trace.jsonl"),
		"--state-dir", filepath.Join(root, "state"))
	if code != 2 {
		t.Fatalf("tooling errors must exit 2, got %d", code)
	}
	if len(nonblankLines(stdout)) != 0 {
		t.Fatalf("tooling errors must not write stdout: %q", stdout)
	}
	if stderr == "" {
		t.Fatal("tooling errors must diagnose on stderr")
	}
}

// TestM4CLICrashThenResume is the real two-phase flow: the fresh phase with
// the scripted crash hard-exits 2 after flushing the trace prefix (no
// result line), and the resume phase completes the run with the recovered
// evidence.
func TestM4CLICrashThenResume(t *testing.T) {
	root := testTempDir(t)
	stateDir := filepath.Join(root, "state")
	crashTrace := filepath.Join(root, "fresh.jsonl")
	code, stdout, stderr := runCLIProcess(t, "--case", "parallel-crash-resume",
		"--trace", crashTrace, "--state-dir", stateDir)
	if code != 2 {
		t.Fatalf("crash phase must exit 2, got %d (stderr %s)", code, stderr)
	}
	if len(nonblankLines(stdout)) != 0 {
		t.Fatalf("crash phase must print no result: %q", stdout)
	}
	// The trace prefix flushed before the hard exit: no terminal event.
	events, err := ReadTrace(crashTrace)
	if err != nil {
		t.Fatalf("crash trace: %v", err)
	}
	if len(events) == 0 {
		t.Fatal("the crash phase must flush its trace prefix")
	}
	for _, event := range events {
		if event.Type == "run.completed" || event.Type == "run.failed" {
			t.Fatal("the crash prefix carries no terminal event")
		}
	}
	last := events[len(events)-1]
	if last.Type != "checkpoint.saved" {
		t.Fatalf("the prefix must end at a checkpoint, got %s", last.Type)
	}
	// The state document survived the hard exit with cursor 2.
	scenario, _ := loadRepoScenario(t)
	loaded, err := loadRunState(stateDir, testBinding(mustCase(t, scenario, "parallel-crash-resume"), scenario))
	if err != nil {
		t.Fatalf("load crashed state: %v", err)
	}
	if loaded.Document.SequenceCursor != 2 {
		t.Fatalf("crashed cursor: %d", loaded.Document.SequenceCursor)
	}
	// Resume completes the run.
	resumeTrace := filepath.Join(root, "resume.jsonl")
	code, stdout, stderr = runCLIProcess(t, "--case", "parallel-crash-resume",
		"--trace", resumeTrace, "--state-dir", stateDir, "--resume")
	if code != 0 {
		t.Fatalf("resume phase must exit 0, got %d (stderr %s)", code, stderr)
	}
	lines := nonblankLines(stdout)
	if len(lines) != 1 {
		t.Fatalf("resume must print exactly one result line, got %d", len(lines))
	}
	var result map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &result); err != nil {
		t.Fatalf("resume result not JSON: %v", err)
	}
	if result["status"] != "SUCCEEDED" || result["resumed"] != true {
		t.Fatalf("resume result: %v", result)
	}
	if result["restored_cursor"] != float64(2) {
		t.Fatalf("restored cursor: %v", result["restored_cursor"])
	}
	if result["run_id"] != loaded.Document.RunID {
		t.Fatal("the resumed run keeps the recorded run id")
	}
}

// TestM4CLICorruptResume is the evaluator's corrupt-resume probe: a
// digest-broken state document fails closed with exit 2 and no result.
func TestM4CLICorruptResume(t *testing.T) {
	root := testTempDir(t)
	stateDir := filepath.Join(root, "state")
	code, _, stderr := runCLIProcess(t, "--case", "parallel-clean-complete",
		"--trace", filepath.Join(root, "fresh.jsonl"), "--state-dir", stateDir)
	if code != 0 {
		t.Fatalf("fresh phase: %d (stderr %s)", code, stderr)
	}
	// Copy the state root and flip the recorded payment outcome.
	tampered := filepath.Join(root, "tampered")
	if err := copyDir(stateDir, tampered); err != nil {
		t.Fatalf("copy state: %v", err)
	}
	runDirs, err := os.ReadDir(tampered)
	if err != nil {
		t.Fatalf("read tampered: %v", err)
	}
	tamperedPath := ""
	for _, entry := range runDirs {
		candidate := filepath.Join(tampered, entry.Name(), "state.json")
		if raw, err := os.ReadFile(candidate); err == nil {
			var document map[string]any
			if err := json.Unmarshal(raw, &document); err != nil {
				t.Fatalf("parse state: %v", err)
			}
			steps := document["steps"].([]any)
			output := steps[1].(map[string]any)["output"].(map[string]any)
			output["payment_status"] = "UNPAID"
			content, err := json.Marshal(document)
			if err != nil {
				t.Fatalf("marshal: %v", err)
			}
			if err := os.WriteFile(candidate, content, 0o644); err != nil {
				t.Fatalf("write: %v", err)
			}
			tamperedPath = tampered
			break
		}
	}
	if tamperedPath == "" {
		t.Fatal("no state document to tamper")
	}
	code, corruptStdout, corruptStderr := runCLIProcess(t, "--case", "parallel-clean-complete",
		"--trace", filepath.Join(root, "corrupt.jsonl"), "--state-dir", tampered, "--resume")
	if code != 2 {
		t.Fatalf("corrupt resume must exit 2, got %d", code)
	}
	if len(nonblankLines(corruptStdout)) != 0 {
		t.Fatalf("corrupt resume must print no result: %q", corruptStdout)
	}
	if !strings.Contains(corruptStderr, "DIGEST_MISMATCH") {
		t.Fatalf("corrupt resume must diagnose the digest: %s", corruptStderr)
	}
}

// TestM4CLIReplayFromCheckpoint pins the replay CLI flow: a new run id, the
// source untouched, exit 0.
func TestM4CLIReplayFromCheckpoint(t *testing.T) {
	root := testTempDir(t)
	stateDir := filepath.Join(root, "state")
	code, stdout, stderr := runCLIProcess(t, "--case", "parallel-replay-from-checkpoint",
		"--trace", filepath.Join(root, "fresh.jsonl"), "--state-dir", stateDir)
	if code != 0 {
		t.Fatalf("fresh phase: %d (stderr %s)", code, stderr)
	}
	var fresh map[string]any
	if err := json.Unmarshal([]byte(nonblankLines(stdout)[0]), &fresh); err != nil {
		t.Fatalf("fresh result: %v", err)
	}
	runID, _ := fresh["run_id"].(string)
	sourceState, err := os.ReadFile(filepath.Join(stateDir, runID, "state.json"))
	if err != nil {
		t.Fatalf("read source state: %v", err)
	}
	code, stdout, stderr = runCLIProcess(t, "--case", "parallel-replay-from-checkpoint",
		"--trace", filepath.Join(root, "replay.jsonl"), "--state-dir", stateDir,
		"--replay-from", filepath.Join(stateDir, runID, "checkpoints", "step-1.json"))
	if code != 0 {
		t.Fatalf("replay phase: %d (stderr %s)", code, stderr)
	}
	var replayed map[string]any
	if err := json.Unmarshal([]byte(nonblankLines(stdout)[0]), &replayed); err != nil {
		t.Fatalf("replay result: %v", err)
	}
	if replayed["run_id"] == runID || replayed["resumed"] != true {
		t.Fatalf("replayed result: %v", replayed)
	}
	untouched, err := os.ReadFile(filepath.Join(stateDir, runID, "state.json"))
	if err != nil {
		t.Fatalf("read source state: %v", err)
	}
	if string(untouched) != string(sourceState) {
		t.Fatal("the source run's state must stay untouched")
	}
}
