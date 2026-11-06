package m5

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// pinnedM5CaseKeys mirrors tools/contracts/test_m7_contracts.py.
var pinnedM5CaseKeys = []string{
	"approval-granted-effect-once",
	"approval-rejected-no-effect",
	"retry-before-submit",
	"crash-submit-window-resolved",
	"sink-unavailable-unknown",
	"duplicate-key-suppressed",
}

// pinnedM5Phases mirrors tools/evaluate.py M5_PHASES: per key, the ordered
// (kind, crash) phase choreography the harness replays for every language.
var pinnedM5Phases = map[string][][2]any{
	"approval-granted-effect-once": {{"fresh", false}},
	"approval-rejected-no-effect":  {{"fresh", false}},
	"retry-before-submit":          {{"fresh", true}, {"resume", false}},
	"crash-submit-window-resolved": {{"fresh", true}, {"resume", false}},
	"sink-unavailable-unknown":     {{"fresh", true}, {"resume", false}},
	"duplicate-key-suppressed":     {{"fresh", false}, {"duplicate", false}},
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
	dir := filepath.Join(root, "fixtures", "goldens", "order-closure")
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
	if len(goldens) != len(pinnedM5CaseKeys) {
		t.Fatalf("expected %d goldens, found %d", len(pinnedM5CaseKeys), len(goldens))
	}
	for _, key := range pinnedM5CaseKeys {
		if _, ok := goldens[key]; !ok {
			t.Fatalf("missing golden for pinned key %s", key)
		}
	}
	return goldens
}

// testTempDir is a per-test temp root whose cleanup tolerates the Windows
// RemoveAll races (a freshly written file can still be held by the indexer
// or antivirus when the sweep runs); cleanup is retried and best effort.
func testTempDir(t *testing.T) string {
	t.Helper()
	dir, err := os.MkdirTemp("", "m5-test")
	if err != nil {
		t.Fatalf("temp dir: %v", err)
	}
	t.Cleanup(func() {
		for attempt := 0; attempt < 10; attempt++ {
			if err := os.RemoveAll(dir); err == nil {
				return
			}
			time.Sleep(20 * time.Millisecond)
		}
	})
	return dir
}

func loadRepoScenario(t *testing.T) (*Scenario, map[string]WorkerInstructions) {
	t.Helper()
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("repo root: %v", err)
	}
	scenario, err := LoadScenario(DefaultScenarioPath(root), DefaultWorkersPath(root))
	if err != nil {
		t.Fatalf("load scenario: %v", err)
	}
	fixtures, err := LoadWorkerFixtures(DefaultWorkersPath(root))
	if err != nil {
		t.Fatalf("load workers: %v", err)
	}
	return scenario, fixtures
}

func testBindingFor(t *testing.T, scenario *Scenario, caseID string) StateBinding {
	t.Helper()
	spec := mustCase(t, scenario, caseID)
	return StateBinding{CaseID: spec.CaseID, ExecutionMode: spec.ExecutionMode,
		RequestedOrderID: scenario.OrderID, ConcurrencyLimit: concurrencyLimitOf(spec.ExecutionMode)}
}

func mustCase(t *testing.T, scenario *Scenario, caseID string) CaseSpec {
	t.Helper()
	spec, err := scenario.FindCase(caseID)
	if err != nil {
		t.Fatalf("FindCase: %v", err)
	}
	return spec
}

// canonicalWorkerWindows mirrors tools/evaluate.py _canonical_worker_windows:
// contiguous worker-event windows sort by canonical worker index, started
// before terminal before checkpoint, so any valid concurrent schedule maps
// to one sequence.
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
		if eventType == "checkpoint.saved" {
			if rank, ok := rankOf[name]; ok {
				window = append(window, windowEntry{worker: rank, terminal: 2, order: 2, entry: entry})
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

func resultProjection(t *testing.T, result contracts.OrderClosureResult) map[string]any {
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
	delete(full, "state_dir")
	return full
}

func readPhaseTrace(t *testing.T, path string) []contracts.Event {
	t.Helper()
	events, err := ReadTrace(path)
	if err != nil {
		t.Fatalf("read trace %s: %v", path, err)
	}
	return events
}

// TestGoldenParity pins all six M5 case keys against the TS/PY goldens by
// replaying the evaluator's M5_PHASES choreography per key and comparing the
// FINAL result projection, the canonical union event sequence, and the
// attribution across the phases' traces.
func TestGoldenParity(t *testing.T) {
	goldens := loadGoldens(t)
	scenario, fixtures := loadRepoScenario(t)
	for _, key := range pinnedM5CaseKeys {
		t.Run(key, func(t *testing.T) {
			g := goldens[key]
			workdir := testTempDir(t)
			stateDir := filepath.Join(workdir, "state")
			var events []contracts.Event
			var final *contracts.OrderClosureResult
			for _, phase := range pinnedM5Phases[key] {
				kind := phase[0].(string)
				crash := phase[1].(bool)
				tracePath := filepath.Join(workdir, fmt.Sprintf("%s.%s.jsonl", key, kind))
				options := RunOptions{CaseID: key, TracePath: tracePath, StateDir: stateDir,
					Scenario: scenario, Fixtures: fixtures}
				if kind == "resume" {
					options.Resume = true
				}
				if crash {
					// The crash control hard-exits 2 without a result; the
					// test surfaces it as the CrashSignal sentinel.
					options.OnCrash = func() {
						panic(&CrashSignal{})
					}
					_, crashErr := RunCase(context.Background(), options)
					var signal *CrashSignal
					if !errors.As(crashErr, &signal) {
						t.Fatalf("%s %s phase: crash must surface CrashSignal, got %v", key, kind, crashErr)
					}
				} else {
					report, runErr := RunCase(context.Background(), options)
					if runErr != nil {
						t.Fatalf("%s %s phase: %v", key, kind, runErr)
					}
					phaseResult := report.Result
					final = &phaseResult
				}
				events = append(events, readPhaseTrace(t, tracePath)...)
			}
			if final == nil {
				t.Fatalf("%s: no phase produced a result", key)
			}
			gotResult := resultProjection(t, *final)
			if !reflect.DeepEqual(gotResult, g.ResultProjection) {
				t.Errorf("result projection divergence:\n got %v\nwant %v", gotResult, g.ResultProjection)
			}
			gotEvents := eventProjection(events)
			if !reflect.DeepEqual(gotEvents, g.EventSequence) {
				t.Errorf("event sequence divergence:\n got %v\nwant %v", gotEvents, g.EventSequence)
			}
			if !reflect.DeepEqual(final.Attribution, g.Attribution) {
				t.Errorf("attribution divergence:\n got %+v\nwant %+v",
					final.Attribution, g.Attribution)
			}
		})
	}
}

// TestRunnerEffectEventPayloads pins the M5 effect-surface payloads beyond
// the {type, step_name} projection: the approval pair binds
// (operation, order_id, payload_digest), the tool pair carries the key and
// the settled status, and the terminal event carries the side-effect
// provenance.
func TestRunnerEffectEventPayloads(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	stateDir := filepath.Join(testTempDir(t), "state")
	tracePath := filepath.Join(testTempDir(t), "trace.jsonl")
	report, err := RunCase(context.Background(), RunOptions{
		CaseID: "approval-granted-effect-once", TracePath: tracePath,
		StateDir: stateDir, Scenario: scenario, Fixtures: fixtures})
	if err != nil {
		t.Fatalf("RunCase: %v", err)
	}
	digest := testPayloadDigest(t)
	key := "cancel-and-refund:ORD-1001"
	requested, granted, toolsRequested, toolsCompleted := 0, 0, 0, 0
	for _, event := range report.Events {
		switch event.Type {
		case contracts.EventApprovalRequested:
			requested++
			if event.Data["operation"] != EffectOperation || event.Data["order_id"] != "ORD-1001" ||
				event.Data["payload_digest"] != digest {
				t.Fatalf("approval.requested payload: %+v", event.Data)
			}
		case contracts.EventApprovalGranted:
			granted++
			if event.Data["payload_digest"] != digest {
				t.Fatalf("approval.granted payload: %+v", event.Data)
			}
		case contracts.EventToolRequested:
			toolsRequested++
			if event.Data["key"] != key || event.Data["payload_digest"] != digest ||
				event.Data["side_effect_class"] != "external" {
				t.Fatalf("tool.requested payload: %+v", event.Data)
			}
		case contracts.EventToolCompleted:
			toolsCompleted++
			if event.Data["key"] != key || event.Data["status"] != EffectCompleted ||
				event.Data["duplicate"] != false {
				t.Fatalf("tool.completed payload: %+v", event.Data)
			}
		case contracts.EventCheckpointSaved:
			if event.Data["state_status"] != RunStateStatusRunning ||
				event.Data["case_id"] != "approval-granted-effect-once" ||
				event.Data["requested_order_id"] != "ORD-1001" ||
				event.Data["concurrency_limit"] != 2 {
				t.Fatalf("checkpoint payload: %+v", event.Data)
			}
		}
	}
	if requested != 1 || granted != 1 || toolsRequested != 1 || toolsCompleted != 1 {
		t.Fatalf("effect surface counts: %d/%d/%d/%d", requested, granted, toolsRequested, toolsCompleted)
	}
	// The result carries the side-effect provenance and never synthesizes.
	result := report.Result
	if result.SynthesisInvoked || result.Brief != nil || result.ApprovalDecision != DecisionGranted ||
		result.EffectStatus == nil || *result.EffectStatus != EffectCompleted ||
		result.IdempotencyKey == nil || *result.IdempotencyKey != key || result.Reconciled {
		t.Fatalf("result surface: %+v", result)
	}
	if result.RestoredCursor != nil || len(result.RestoredWorkerIDs) != 0 || result.Resumed {
		t.Fatalf("fresh runs carry no restored evidence: %+v", result)
	}
	// Ruling 5: three worker reads plus the effect submission.
	if len(result.Attribution.Steps) != 4 ||
		result.Attribution.Totals.LatencyMS != 73 || result.Attribution.Totals.CostCents != 25 ||
		result.Attribution.Totals.Attempts != 4 {
		t.Fatalf("attribution: %+v", result.Attribution)
	}
}

// TestRunnerScenarioValidation pins the loader's fail-closed validation:
// the six-case projection with per-case canonical controls and at most one
// scripted extension.
func TestRunnerScenarioValidation(t *testing.T) {
	scenario, _ := loadRepoScenario(t)
	if scenario.ScenarioID != ScenarioID || scenario.OrderID != "ORD-1001" || len(scenario.Cases) != 6 {
		t.Fatalf("scenario header: %+v", scenario)
	}
	for _, spec := range scenario.Cases {
		if spec.ExecutionMode != ModeParallel {
			t.Fatalf("every M5 case is parallel: %+v", spec)
		}
		if spec.Approval.Decision != DecisionGranted && spec.Approval.Decision != DecisionRejected {
			t.Fatalf("every M5 case binds a fixture approval: %+v", spec)
		}
	}
	if _, err := scenario.FindCase("no-such-case"); !errors.Is(err, ErrUnknownCase) {
		t.Fatalf("unknown case: %v", err)
	}
	// The worker fixtures must cover exactly the referenced fixture.
	fixtures, err := LoadWorkerFixtures(DefaultWorkersPath(FindRepoRootOrSkip(t)))
	if err != nil {
		t.Fatalf("workers: %v", err)
	}
	if _, ok := fixtures["fixtures/workers/order-brief/complete.yaml"]; !ok {
		t.Fatal("the M5 workers projection must carry the referenced fixture")
	}
}

func FindRepoRootOrSkip(t *testing.T) string {
	t.Helper()
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("repo root: %v", err)
	}
	return root
}

// TestRunnerToolingErrors pins the option validation.
func TestRunnerToolingErrors(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	ctx := context.Background()
	if _, err := RunCase(ctx, RunOptions{CaseID: "no-such-case",
		TracePath: filepath.Join(testTempDir(t), "t.jsonl"),
		StateDir:  filepath.Join(testTempDir(t), "s")}); !errors.Is(err, ErrUnknownCase) {
		t.Fatalf("unknown case must fail with ErrUnknownCase, got %v", err)
	}
	if _, err := RunCase(ctx, RunOptions{CaseID: "approval-granted-effect-once",
		TracePath: filepath.Join(testTempDir(t), "t.jsonl")}); err == nil ||
		!strings.Contains(err.Error(), "state dir") {
		t.Fatalf("empty state dir must be a tooling error, got %v", err)
	}
	if _, err := RunCase(ctx, RunOptions{CaseID: "approval-granted-effect-once",
		TracePath: filepath.Join(testTempDir(t), "t.jsonl"),
		StateDir:  filepath.Join(testTempDir(t), "s"),
		Scenario:  scenario, Fixtures: fixtures,
		Directory: DirectoryFromProvider(&countingProvider{})}); err == nil {
		t.Fatal("directory without control must be rejected")
	}
}

// TestRunnerResumesOnlyRunningStates pins that the resume of a terminal run
// without an effect decision refuses at the load/resume boundary.
func TestRunnerResumesOnlyRunningStates(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	stateDir := filepath.Join(testTempDir(t), "state")
	if _, err := RunCase(context.Background(), RunOptions{
		CaseID: "approval-granted-effect-once", TracePath: filepath.Join(testTempDir(t), "fresh.jsonl"),
		StateDir: stateDir, Scenario: scenario, Fixtures: fixtures}); err != nil {
		t.Fatalf("fresh: %v", err)
	}
	// The fresh run settled its effect and closed SUCCEEDED; the recovery
	// layer refuses the terminal document.
	_, err := ResumeRun(RecoveryOptions{StateRoot: stateDir,
		Binding: testBindingFor(t, scenario, "approval-granted-effect-once"),
		Ledger:  mustLedger(t, stateDir)})
	if err == nil || !strings.Contains(err.Error(), "not resumable") {
		t.Fatalf("a terminal run must refuse recovery, got %v", err)
	}
}

func mustLedger(t *testing.T, stateDir string) *EffectLedger {
	t.Helper()
	ledger, err := NewEffectLedger(stateDir)
	if err != nil {
		t.Fatalf("ledger: %v", err)
	}
	return ledger
}
