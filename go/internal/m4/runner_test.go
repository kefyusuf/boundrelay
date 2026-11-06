package m4

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

// pinnedM4CaseKeys mirrors tools/contracts/test_m7_contracts.py.
var pinnedM4CaseKeys = []string{
	"parallel-clean-complete",
	"parallel-crash-resume",
	"parallel-crash-resume-partial",
	"parallel-cancel-resume",
	"parallel-replay-from-checkpoint",
	"parallel-corrupt-state",
}

// pinnedM4Phases mirrors tools/evaluate.py M4_PHASES: per key, the ordered
// (kind, crash) phase choreography the harness replays for every language.
var pinnedM4Phases = map[string][][2]any{
	"parallel-clean-complete":         {{"fresh", false}},
	"parallel-crash-resume":           {{"fresh", true}, {"resume", false}},
	"parallel-crash-resume-partial":   {{"fresh", true}, {"resume", false}},
	"parallel-cancel-resume":          {{"fresh", false}, {"resume", false}},
	"parallel-replay-from-checkpoint": {{"fresh", false}, {"replay", false}},
	"parallel-corrupt-state":          {{"fresh", false}, {"corrupt-resume", false}},
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
	dir := filepath.Join(root, "fixtures", "goldens", "order-brief-recovery")
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
	if len(goldens) != len(pinnedM4CaseKeys) {
		t.Fatalf("expected %d goldens, found %d", len(pinnedM4CaseKeys), len(goldens))
	}
	for _, key := range pinnedM4CaseKeys {
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
	dir, err := os.MkdirTemp("", "m4-test")
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

func testBinding(spec CaseSpec, scenario *Scenario) StateBinding {
	return StateBinding{CaseID: spec.CaseID, ExecutionMode: spec.ExecutionMode,
		RequestedOrderID: scenario.OrderID, ConcurrencyLimit: concurrencyLimitOf(spec.ExecutionMode)}
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

func resultProjection(t *testing.T, result contracts.OrderBriefRecoveryResult) map[string]any {
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

// TestGoldenParity pins all six M4 case keys against the TS/PY goldens by
// replaying the evaluator's phase choreography per key and comparing the
// FINAL result projection, the canonical union event sequence, and the
// attribution across the phases' traces.
func TestGoldenParity(t *testing.T) {
	goldens := loadGoldens(t)
	scenario, fixtures := loadRepoScenario(t)
	for _, key := range pinnedM4CaseKeys {
		t.Run(key, func(t *testing.T) {
			g := goldens[key]
			workdir := testTempDir(t)
			stateDir := filepath.Join(workdir, "state")
			var events []contracts.Event
			var final *contracts.OrderBriefRecoveryResult
			runID := ""
			for _, phase := range pinnedM4Phases[key] {
				kind := phase[0].(string)
				crash := phase[1].(bool)
				tracePath := filepath.Join(workdir, fmt.Sprintf("%s.%s.jsonl", key, kind))
				options := RunOptions{CaseID: key, TracePath: tracePath, StateDir: stateDir,
					Scenario: scenario, Fixtures: fixtures}
				switch kind {
				case "resume":
					options.Resume = true
				case "replay":
					options.ReplayFrom = filepath.Join(stateDir, runID, "checkpoints", "step-1.json")
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
				} else if kind == "corrupt-resume" {
					tampered := corruptStateCopy(t, stateDir)
					options.StateDir = tampered
					options.Resume = true
					_, loadErr := RunCase(context.Background(), options)
					var loadError *StateLoadError
					if !errors.As(loadErr, &loadError) || loadError.Reason != ReasonDigestMismatch {
						t.Fatalf("%s %s phase: tampered state must fail DIGEST_MISMATCH, got %v",
							key, kind, loadErr)
					}
					continue
				} else {
					report, runErr := RunCase(context.Background(), options)
					if runErr != nil {
						t.Fatalf("%s %s phase: %v", key, kind, runErr)
					}
					phaseResult := report.Result
					final = &phaseResult
					runID = phaseResult.RunID
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

// corruptStateCopy mirrors the evaluator's corrupt-resume probe: copy the
// state root and flip the recorded payment outcome inside the run document.
func corruptStateCopy(t *testing.T, stateDir string) string {
	t.Helper()
	tampered := filepath.Join(filepath.Dir(stateDir), "tampered")
	entries, err := os.ReadDir(stateDir)
	if err != nil {
		t.Fatalf("read state root: %v", err)
	}
	if err := os.MkdirAll(tampered, 0o755); err != nil {
		t.Fatalf("mkdir tampered: %v", err)
	}
	for _, entry := range entries {
		if err := copyDir(filepath.Join(stateDir, entry.Name()),
			filepath.Join(tampered, entry.Name())); err != nil {
			t.Fatalf("copy state: %v", err)
		}
	}
	runDirs, err := os.ReadDir(tampered)
	if err != nil {
		t.Fatalf("read tampered: %v", err)
	}
	for _, entry := range runDirs {
		statePath := filepath.Join(tampered, entry.Name(), "state.json")
		raw, err := os.ReadFile(statePath)
		if err != nil {
			continue
		}
		var document map[string]any
		if err := json.Unmarshal(raw, &document); err != nil {
			t.Fatalf("parse state: %v", err)
		}
		steps := document["steps"].([]any)
		step := steps[1].(map[string]any)
		output := step["output"].(map[string]any)
		output["payment_status"] = "UNPAID"
		content, err := json.Marshal(document)
		if err != nil {
			t.Fatalf("marshal tampered state: %v", err)
		}
		if err := os.WriteFile(statePath, content, 0o644); err != nil {
			t.Fatalf("write tampered state: %v", err)
		}
		return tampered
	}
	t.Fatal("no state document to tamper")
	return ""
}

func copyDir(source, destination string) error {
	return filepath.WalkDir(source, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		relative, err := filepath.Rel(source, path)
		if err != nil {
			return err
		}
		target := filepath.Join(destination, relative)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(target, raw, 0o644)
	})
}

// countingProvider counts worker body invocations and replays the fixture
// outputs; the permissive control accepts every acknowledgement.
type countingProvider struct {
	fixture     WorkerInstructions
	orderID     string
	invocations []string
}

func (p *countingProvider) Read(id string, input WorkerInput) (json.RawMessage, error) {
	p.invocations = append(p.invocations, id)
	if input.OrderID != p.orderID {
		return nil, fmt.Errorf("m4: invalid worker invocation")
	}
	instruction, ok := p.fixture[id]
	if !ok {
		return nil, fmt.Errorf("m4: worker %s missing from fixture", id)
	}
	if instruction.Operation == "raise" {
		return nil, fmt.Errorf("%w: %s declared failure", ErrWorkerExecution, id)
	}
	return append(json.RawMessage(nil), instruction.Output...), nil
}

func (p *countingProvider) AcknowledgeOutcome(id string) error { return nil }
func (p *countingProvider) BeginDrain()                        {}

// TestRunnerPayloads pins the M4 event data payloads and result semantics
// beyond the {type, step_name} projection: context payloads, checkpoint
// payloads, worker outcome objects, synthesize payloads, terminal payload,
// and the recovery provenance fields.
func TestRunnerPayloads(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	for _, key := range pinnedM4CaseKeys {
		if key != "parallel-clean-complete" {
			continue
		}
		stateDir := filepath.Join(testTempDir(t), "state")
		tracePath := filepath.Join(testTempDir(t), "trace.jsonl")
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		report, err := RunCase(ctx, RunOptions{CaseID: key, TracePath: tracePath,
			StateDir: stateDir, Scenario: scenario, Fixtures: fixtures})
		if err != nil {
			t.Fatalf("RunCase(%s): %v", key, err)
		}
		result := report.Result
		events := report.Events
		if result.ConcurrencyLimit != 2 || result.PeakConcurrency != 2 {
			t.Fatalf("limit/peak: %d/%d want 2/2", result.ConcurrencyLimit, result.PeakConcurrency)
		}
		context := map[string]any{
			"scenario_id": "order-brief-recovery", "case_id": result.CaseID,
			"execution_mode": result.ExecutionMode, "order_id": result.OrderID,
			"concurrency_limit": 2, "state_dir": stateDir,
		}
		if !reflect.DeepEqual(events[0].Data, context) || !reflect.DeepEqual(events[1].Data, context) {
			t.Fatalf("run context payloads: %+v vs %+v", events[0].Data, events[1].Data)
		}
		checkpoints := 0
		for _, event := range events {
			data := event.Data
			name, _ := data["step_name"].(string)
			switch {
			case event.Type == contracts.EventCheckpointSaved:
				checkpoints++
				if data["state_status"] != RunStateStatusRunning ||
					data["case_id"] != result.CaseID ||
					data["requested_order_id"] != result.OrderID ||
					data["concurrency_limit"] != 2 ||
					data["sequence_cursor"] != checkpoints {
					t.Fatalf("checkpoint payload: %+v", data)
				}
			case event.Type == contracts.EventStepStarted && strings.HasPrefix(name, "worker."):
				if data["worker_id"] != strings.TrimPrefix(name, "worker.") ||
					data["order_id"] != result.OrderID {
					t.Fatalf("worker started payload: %+v", data)
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
		if checkpoints != 3 {
			t.Fatalf("expected three checkpoint.saved events, got %d", checkpoints)
		}
		assertRecoveryTerminal(t, result, events[len(events)-1])
		if result.Resumed || result.RestoredCursor != nil || len(result.RestoredWorkerIDs) != 0 {
			t.Fatalf("fresh runs carry no recovery provenance: %+v", result)
		}
	}
}

func assertRecoveryTerminal(t *testing.T, result contracts.OrderBriefRecoveryResult, terminal contracts.Event) {
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

// TestRunnerToolingErrors pins the option validation.
func TestRunnerToolingErrors(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	ctx := context.Background()
	if _, err := RunCase(ctx, RunOptions{CaseID: "no-such-case",
		TracePath: filepath.Join(testTempDir(t), "t.jsonl"),
		StateDir:  filepath.Join(testTempDir(t), "s")}); !errors.Is(err, ErrUnknownCase) {
		t.Fatalf("unknown case must fail with ErrUnknownCase, got %v", err)
	}
	if _, err := RunCase(ctx, RunOptions{CaseID: "parallel-clean-complete",
		TracePath: filepath.Join(testTempDir(t), "t.jsonl")}); err == nil ||
		!strings.Contains(err.Error(), "state dir") {
		t.Fatalf("empty state dir must be a tooling error, got %v", err)
	}
	if _, err := RunCase(ctx, RunOptions{CaseID: "parallel-clean-complete",
		TracePath: filepath.Join(testTempDir(t), "t.jsonl"),
		StateDir:  filepath.Join(testTempDir(t), "s"),
		Scenario:  scenario, Fixtures: fixtures,
		Directory: DirectoryFromProvider(&countingProvider{})}); err == nil {
		t.Fatal("directory without control must be rejected")
	}
	if _, err := RunCase(ctx, RunOptions{CaseID: "parallel-clean-complete",
		TracePath: filepath.Join(testTempDir(t), "t.jsonl"),
		StateDir:  filepath.Join(testTempDir(t), "s"),
		Scenario:  scenario, Fixtures: fixtures,
		Resume: true, ReplayFrom: filepath.Join(testTempDir(t), "step-1.json")}); err == nil ||
		!strings.Contains(err.Error(), "mutually exclusive") {
		t.Fatalf("resume+replay must be rejected, got %v", err)
	}
}
