package m3

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// pinnedM3CaseKeys mirrors tools/contracts/test_m7_contracts.py.
var pinnedM3CaseKeys = []string{
	"sequential-complete",
	"parallel-complete",
	"parallel-out-of-order",
	"parallel-partial-failure",
	"parallel-all-failed",
	"parallel-invalid-output",
}

type golden struct {
	ResultProjection map[string]any        `json:"result_projection"`
	EventSequence    []map[string]any      `json:"event_sequence"`
	Attribution      contracts.Attribution `json:"attribution"`
}

func loadGoldens(t *testing.T) map[string]golden {
	t.Helper()
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("repo root: %v", err)
	}
	dir := filepath.Join(root, "fixtures", "goldens", "order-brief")
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read goldens: %v", err)
	}
	goldens := map[string]golden{}
	for _, entry := range entries {
		name := entry.Name()
		if !strings.HasSuffix(name, ".json") {
			continue
		}
		raw, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			t.Fatalf("read golden %s: %v", name, err)
		}
		var g golden
		if err := json.Unmarshal(raw, &g); err != nil {
			t.Fatalf("parse golden %s: %v", name, err)
		}
		goldens[strings.TrimSuffix(name, ".json")] = g
	}
	if len(goldens) != len(pinnedM3CaseKeys) {
		t.Fatalf("expected %d goldens, found %d", len(pinnedM3CaseKeys), len(goldens))
	}
	for _, key := range pinnedM3CaseKeys {
		if _, ok := goldens[key]; !ok {
			t.Fatalf("missing golden for pinned key %s", key)
		}
	}
	return goldens
}

func runCaseKey(t *testing.T, caseID string) RunReport {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	report, err := RunCase(ctx, RunOptions{
		CaseID: caseID, TracePath: filepath.Join(t.TempDir(), "trace.jsonl")})
	if err != nil {
		t.Fatalf("RunCase(%s): %v", caseID, err)
	}
	return report
}

// canonicalWorkerWindows mirrors tools/evaluate.py _canonical_worker_windows:
// contiguous worker-event windows sort by canonical worker index, started
// before terminal, so any valid concurrent schedule maps to one sequence.
func canonicalWorkerWindows(sequence []map[string]any) []map[string]any {
	rankOf := map[string]int{}
	for rank, id := range contracts.CanonicalWorkerIDs {
		rankOf[id] = rank
	}
	type windowEntry struct {
		worker, terminal, order int
		entry                   map[string]any
	}
	var result []map[string]any
	var window []windowEntry
	flush := func() {
		sort.SliceStable(window, func(i, j int) bool {
			left, right := window[i], window[j]
			if left.worker != right.worker {
				return left.worker < right.worker
			}
			return left.terminal < right.terminal
		})
		for _, item := range window {
			result = append(result, item.entry)
		}
		window = nil
	}
	for _, entry := range sequence {
		name, _ := entry["step_name"].(string)
		eventType, _ := entry["type"].(string)
		if (eventType == "step.started" || eventType == "step.completed" || eventType == "step.failed") &&
			strings.HasPrefix(name, "worker.") {
			worker := strings.TrimPrefix(name, "worker.")
			if rank, ok := rankOf[worker]; ok {
				terminalRank := 0
				if eventType != "step.started" {
					terminalRank = 1
				}
				window = append(window, windowEntry{worker: rank, terminal: terminalRank, order: 1, entry: entry})
				continue
			}
		}
		flush()
		result = append(result, entry)
	}
	flush()
	return result
}

func eventProjection(events []contracts.Event) []map[string]any {
	sequence := make([]map[string]any, 0, len(events))
	for _, event := range events {
		stepName := any(nil)
		if name, ok := event.Data["step_name"].(string); ok {
			stepName = name
		}
		sequence = append(sequence, map[string]any{
			"type": string(event.Type), "step_name": stepName})
	}
	return canonicalWorkerWindows(sequence)
}

func resultProjection(t *testing.T, result contracts.OrderBriefResult) map[string]any {
	t.Helper()
	raw, err := json.Marshal(result)
	if err != nil {
		t.Fatalf("marshal result: %v", err)
	}
	var full map[string]any
	if err := json.Unmarshal(raw, &full); err != nil {
		t.Fatalf("unmarshal result: %v", err)
	}
	delete(full, "run_id")
	delete(full, "trace_path")
	return full
}

// TestGoldenParity pins all six M3 case keys against the TS/PY goldens.
func TestGoldenParity(t *testing.T) {
	goldens := loadGoldens(t)
	for _, key := range pinnedM3CaseKeys {
		t.Run(key, func(t *testing.T) {
			g := goldens[key]
			tracePath := filepath.Join(t.TempDir(), "trace.jsonl")
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			report, err := RunCase(ctx, RunOptions{CaseID: key, TracePath: tracePath})
			if err != nil {
				t.Fatalf("RunCase(%s): %v", key, err)
			}
			gotResult := resultProjection(t, report.Result)
			if !reflect.DeepEqual(gotResult, g.ResultProjection) {
				t.Errorf("result projection divergence:\n got %v\nwant %v", gotResult, g.ResultProjection)
			}
			gotEvents := eventProjection(report.Events)
			if !reflect.DeepEqual(gotEvents, g.EventSequence) {
				t.Errorf("event sequence divergence:\n got %v\nwant %v", gotEvents, g.EventSequence)
			}
			if !reflect.DeepEqual(report.Result.Attribution, g.Attribution) {
				t.Errorf("attribution divergence:\n got %+v\nwant %+v",
					report.Result.Attribution, g.Attribution)
			}
			assertTraceFile(t, tracePath, report.Events)
		})
	}
}

func assertTraceFile(t *testing.T, path string, events []contracts.Event) {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("trace file: %v", err)
	}
	if !strings.HasSuffix(string(raw), "\n") {
		t.Fatal("trace JSONL must end with a newline")
	}
	lines := strings.Split(strings.TrimSuffix(string(raw), "\n"), "\n")
	if len(lines) != len(events) {
		t.Fatalf("trace lines %d != events %d", len(lines), len(events))
	}
	for i, line := range lines {
		event, err := contracts.DecodeEvent([]byte(line))
		if err != nil {
			t.Fatalf("trace line %d: %v", i+1, err)
		}
		if event.Type != events[i].Type || event.Sequence != events[i].Sequence {
			t.Fatalf("trace line %d mismatch: %+v", i+1, event)
		}
	}
}

// TestRunnerPayloads pins the M3 event data payloads and result semantics
// beyond the {type, step_name} projection: context payloads, worker
// outcome objects, synthesize payloads, terminal payload, and the
// limit/peak/status invariants per mode.
func TestRunnerPayloads(t *testing.T) {
	for _, key := range pinnedM3CaseKeys {
		t.Run(key, func(t *testing.T) {
			report := runCaseKey(t, key)
			result := report.Result
			events := report.Events
			limit := 1
			if result.ExecutionMode == ModeParallel {
				limit = 2
			}
			if result.ConcurrencyLimit != limit || result.PeakConcurrency != limit {
				t.Fatalf("limit/peak: %d/%d want %d/%d",
					result.ConcurrencyLimit, result.PeakConcurrency, limit, limit)
			}
			context := map[string]any{
				"scenario_id": "order-brief", "case_id": result.CaseID,
				"execution_mode": result.ExecutionMode, "order_id": result.OrderID,
				"concurrency_limit": limit,
			}
			if !reflect.DeepEqual(events[0].Data, context) || !reflect.DeepEqual(events[1].Data, context) {
				t.Fatalf("run context payloads: %+v vs %+v", events[0].Data, events[1].Data)
			}
			for _, event := range events {
				data := event.Data
				name, _ := data["step_name"].(string)
				switch {
				case event.Type == contracts.EventStepStarted && strings.HasPrefix(name, "worker."):
					if data["worker_id"] != strings.TrimPrefix(name, "worker.") ||
						data["order_id"] != result.OrderID {
						t.Fatalf("worker started payload: %+v", data)
					}
				case event.Type == contracts.EventStepCompleted || event.Type == contracts.EventStepFailed:
					if strings.HasPrefix(name, "worker.") {
						outcome, ok := data["outcome"].(*WorkerOutcome)
						if !ok || outcome.WorkerID != strings.TrimPrefix(name, "worker.") {
							t.Fatalf("worker terminal payload: %+v", data)
						}
					}
				case event.Type == contracts.EventStepStarted && name == "synthesize":
					outcomes, ok := data["worker_outcomes"].([3]WorkerOutcome)
					if !ok || len(outcomes) != 3 {
						t.Fatalf("synthesize started payload: %+v", data)
					}
				case event.Type == contracts.EventStepCompleted && name == "synthesize":
					if _, ok := data["brief"].(*contracts.Brief); !ok {
						t.Fatalf("synthesize completed payload: %+v", data)
					}
				}
			}
			assertTerminal(t, result, events[len(events)-1])
			assertCanonicalOutcomes(t, result)
		})
	}
}

func assertTerminal(t *testing.T, result contracts.OrderBriefResult, terminal contracts.Event) {
	t.Helper()
	if terminal.Data["status"] != result.Status ||
		terminal.Data["synthesis_invoked"] != result.SynthesisInvoked ||
		terminal.Data["peak_concurrency"] != result.PeakConcurrency {
		t.Fatalf("terminal payload: %+v (want status %v synthesis %v peak %d)",
			terminal.Data, result.Status, result.SynthesisInvoked, result.PeakConcurrency)
	}
	outcomes, ok := terminal.Data["worker_outcomes"].([]WorkerOutcome)
	if !ok || !reflect.DeepEqual(outcomes, result.WorkerOutcomes) {
		t.Fatalf("terminal worker_outcomes: %+v", terminal.Data["worker_outcomes"])
	}
	brief, _ := terminal.Data["brief"].(*contracts.Brief)
	if (brief == nil) != (result.Brief == nil) ||
		(brief != nil && !reflect.DeepEqual(*brief, *result.Brief)) {
		t.Fatalf("terminal brief: %+v", terminal.Data["brief"])
	}
	failureCode, _ := terminal.Data["failure_code"].(*string)
	if (failureCode == nil) != (result.FailureCode == nil) ||
		(failureCode != nil && *failureCode != *result.FailureCode) {
		t.Fatalf("terminal failure_code: %+v", terminal.Data["failure_code"])
	}
}

func assertCanonicalOutcomes(t *testing.T, result contracts.OrderBriefResult) {
	t.Helper()
	if len(result.WorkerOutcomes) != 3 {
		t.Fatalf("worker outcomes: %d", len(result.WorkerOutcomes))
	}
	successes := 0
	for i, outcome := range result.WorkerOutcomes {
		if outcome.WorkerID != contracts.CanonicalWorkerIDs[i] {
			t.Fatalf("canonical order: %+v", result.WorkerOutcomes)
		}
		if outcome.Status == "SUCCEEDED" {
			successes++
		}
	}
	wantStatus := "FAILED"
	switch {
	case successes == 3:
		wantStatus = "SUCCEEDED"
	case successes > 0:
		wantStatus = "PARTIAL"
	}
	if result.Status != wantStatus {
		t.Fatalf("status %s for %d successes, want %s", result.Status, successes, wantStatus)
	}
	if (result.Brief != nil) != (successes > 0) || result.SynthesisInvoked != (successes > 0) {
		t.Fatalf("synthesis/brief must match successes: %+v", result)
	}
	if successes == 0 && (result.FailureCode == nil || *result.FailureCode != contracts.FailureAllWorkersFailed) {
		t.Fatalf("all-failed runs must carry ALL_WORKERS_FAILED: %+v", result)
	}
	if successes > 0 && result.FailureCode != nil {
		t.Fatalf("successful/partial runs carry no failure code: %+v", result)
	}
}

func TestRunnerToolingErrors(t *testing.T) {
	ctx := context.Background()
	if _, err := RunCase(ctx, RunOptions{CaseID: "no-such-case",
		TracePath: filepath.Join(t.TempDir(), "t.jsonl")}); !errors.Is(err, ErrUnknownCase) {
		t.Fatalf("unknown case must fail with ErrUnknownCase, got %v", err)
	}
	if _, err := RunCase(ctx, RunOptions{CaseID: "parallel-complete", Mode: ModeSequential,
		TracePath: filepath.Join(t.TempDir(), "t.jsonl")}); err == nil ||
		!strings.Contains(err.Error(), "incompatible") {
		t.Fatalf("mode override must match the case, got %v", err)
	}
	if _, err := RunCase(ctx, RunOptions{CaseID: "parallel-complete",
		TracePath: ""}); err == nil {
		t.Fatal("empty trace path must be a tooling error")
	}
	if _, err := RunCase(ctx, RunOptions{CaseID: "parallel-complete",
		TracePath: filepath.Join(t.TempDir(), "t.jsonl"),
		Provider:  NewScriptedWorkers(CaseSpec{}, "ORD-1001", WorkerInstructions{})}); err == nil {
		t.Fatal("provider without control must be rejected")
	}
}

func TestRunnerFlushesTraceOnFatal(t *testing.T) {
	scenario := loadRepoScenario(t)
	spec, err := scenario.FindCase("parallel-complete")
	if err != nil {
		t.Fatalf("FindCase: %v", err)
	}
	fixtures, err := LoadWorkerFixtures(mustWorkersPath(t))
	if err != nil {
		t.Fatalf("LoadWorkerFixtures: %v", err)
	}
	provider := NewScriptedWorkers(spec, scenario.OrderID, fixtures[spec.WorkerFixture])
	tracePath := filepath.Join(t.TempDir(), "trace.jsonl")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_, err = RunCase(ctx, RunOptions{
		CaseID: spec.CaseID, TracePath: tracePath,
		Provider: &fatalOnWorker{inner: provider, target: contracts.WorkerPaymentStatus},
		Control:  provider})
	if err == nil || !strings.Contains(err.Error(), "boom") {
		t.Fatalf("fatal must propagate through the runner, got %v", err)
	}
	raw, readErr := os.ReadFile(tracePath)
	if readErr != nil {
		t.Fatalf("trace must flush even on fatal: %v", readErr)
	}
	lines := strings.Split(strings.TrimSuffix(string(raw), "\n"), "\n")
	if len(lines) < 2 {
		t.Fatalf("trace must carry the run prefix, got %d lines", len(lines))
	}
	var first map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &first); err != nil || first["type"] != "run.created" {
		t.Fatalf("trace prefix must start with run.created: %v %v", first, err)
	}
}
