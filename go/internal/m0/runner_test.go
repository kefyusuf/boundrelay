package m0

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// pinnedM0CaseKeys mirrors the canonical M0 keys pinned by
// tools/contracts/test_m7_contracts.py (seven case/mode combinations).
var pinnedM0CaseKeys = []string{
	"billing-duplicate-charge@deterministic",
	"billing-duplicate-charge@model",
	"technical-login-error@deterministic",
	"technical-login-error@model",
	"general-opening-hours@deterministic",
	"general-opening-hours@model",
	"invalid-model-route@model",
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
	dir := filepath.Join(root, "fixtures", "goldens", "support-triage")
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
	if len(goldens) != len(pinnedM0CaseKeys) {
		t.Fatalf("expected %d goldens, found %d", len(pinnedM0CaseKeys), len(goldens))
	}
	for _, key := range pinnedM0CaseKeys {
		if _, ok := goldens[key]; !ok {
			t.Fatalf("missing golden for pinned key %s", key)
		}
	}
	return goldens
}

func resultProjection(t *testing.T, result contracts.RunResult) map[string]any {
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

func eventProjection(events []contracts.Event) []map[string]any {
	projection := make([]map[string]any, 0, len(events))
	for _, event := range events {
		stepName := any(nil)
		if step, ok := event.Data["step"].(string); ok {
			stepName = step
		}
		projection = append(projection, map[string]any{
			"type": string(event.Type), "step_name": stepName})
	}
	return projection
}

// TestGoldenParity is the Task 2 parity target: for all seven pinned M0
// case/mode keys the Go run's normalized result projection, event-type
// sequence, and attribution must equal the checked-in TS/PY goldens.
func TestGoldenParity(t *testing.T) {
	goldens := loadGoldens(t)
	for _, key := range pinnedM0CaseKeys {
		t.Run(key, func(t *testing.T) {
			g := goldens[key]
			parts := strings.SplitN(key, "@", 2)
			tracePath := filepath.Join(t.TempDir(), "trace.jsonl")
			report, err := RunCase(RunOptions{
				Mode: parts[1], CaseID: parts[0], TracePath: tracePath})
			if err != nil {
				t.Fatalf("RunCase: %v", err)
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

// runPinned runs one pinned key in-process with a recording dispatcher.
func runPinned(t *testing.T, key string) (RunReport, *RecordingSpecialistDispatcher) {
	t.Helper()
	parts := strings.SplitN(key, "@", 2)
	dispatcher := NewRecordingSpecialistDispatcher()
	report, err := RunCase(RunOptions{
		Mode: parts[1], CaseID: parts[0],
		TracePath:  filepath.Join(t.TempDir(), "trace.jsonl"),
		Dispatcher: dispatcher})
	if err != nil {
		t.Fatalf("RunCase(%s): %v", key, err)
	}
	return report, dispatcher
}

// TestTraceLifecycleAndPayloads mirrors tools/parity/verify_m0.py: canonical
// lifecycle per mode/status, run.created/started context, model event
// payloads, route payload consistency, and terminal payloads.
func TestTraceLifecycleAndPayloads(t *testing.T) {
	lifecycles := map[string][]string{
		"deterministic/SUCCEEDED": {
			"run.created", "run.started", "step.started", "route.selected",
			"step.completed", "step.started", "step.completed", "run.completed"},
		"model/SUCCEEDED": {
			"run.created", "run.started", "step.started", "model.requested",
			"model.completed", "route.selected", "step.completed",
			"step.started", "step.completed", "run.completed"},
		"model/FAILED": {
			"run.created", "run.started", "step.started", "model.requested",
			"model.completed", "route.rejected", "step.failed", "run.failed"},
	}
	for _, key := range pinnedM0CaseKeys {
		t.Run(key, func(t *testing.T) {
			report, _ := runPinned(t, key)
			result := report.Result
			events := report.Events
			lifecycleKey := fmt.Sprintf("%s/%s", result.Mode, result.Status)
			want := lifecycles[lifecycleKey]
			if want == nil {
				t.Fatalf("unsupported lifecycle %s", lifecycleKey)
			}
			got := make([]string, 0, len(events))
			for _, event := range events {
				got = append(got, string(event.Type))
			}
			if !reflect.DeepEqual(got, want) {
				t.Fatalf("lifecycle divergence:\n got %v\nwant %v", got, want)
			}
			if events[0].Data["scenario_id"] != "support-triage" ||
				events[0].Data["case_id"] != result.CaseID ||
				events[0].Data["mode"] != result.Mode {
				t.Fatalf("run.created context: %+v", events[0].Data)
			}
			if events[1].Data["case_id"] != result.CaseID || events[1].Data["mode"] != result.Mode {
				t.Fatalf("run.started context: %+v", events[1].Data)
			}
			assertClassifyAndTerminal(t, result, events)
		})
	}
}

func assertClassifyAndTerminal(t *testing.T, result contracts.RunResult, events []contracts.Event) {
	t.Helper()
	var routeSelected, routeRejected, modelCompleted []contracts.Event
	for _, event := range events {
		switch event.Type {
		case contracts.EventRouteSelected:
			routeSelected = append(routeSelected, event)
		case contracts.EventRouteRejected:
			routeRejected = append(routeRejected, event)
		case contracts.EventModelRequested, contracts.EventModelCompleted:
			if event.Data["case_id"] != result.CaseID {
				t.Fatalf("%s context: %+v", event.Type, event.Data)
			}
			if event.Type == contracts.EventModelCompleted {
				modelCompleted = append(modelCompleted, event)
			}
		}
	}
	if result.Status == "SUCCEEDED" {
		if len(routeSelected) != 1 || routeSelected[0].Data["route"] != *result.SelectedRoute {
			t.Fatalf("route.selected payload: %+v", routeSelected)
		}
		if result.Mode == ModeModel {
			if len(modelCompleted) != 1 {
				t.Fatalf("model.completed count: %d", len(modelCompleted))
			}
			decision, ok := modelCompleted[0].Data["decision"].(map[string]any)
			if !ok || decision["route"] != routeSelected[0].Data["route"] ||
				decision["confidence"] != routeSelected[0].Data["confidence"] {
				t.Fatalf("model decision vs route.selected: %+v vs %+v", decision, routeSelected[0].Data)
			}
		}
	} else {
		if len(routeRejected) != 1 || routeRejected[0].Data["failure_code"] != *result.FailureCode {
			t.Fatalf("route.rejected payload: %+v", routeRejected)
		}
		if result.Mode == ModeModel {
			if len(modelCompleted) != 1 {
				t.Fatalf("model.completed count: %d", len(modelCompleted))
			}
			decision, _ := modelCompleted[0].Data["decision"].(map[string]any)
			if decision["route"] != routeRejected[0].Data["route"] {
				t.Fatalf("model decision vs route.rejected: %+v vs %+v", decision, routeRejected[0].Data)
			}
		}
	}
	terminal := events[len(events)-1]
	var wantRoute any
	if terminal.Type == contracts.EventRunFailed {
		wantRoute = nil // run.failed carries no route key; absent reads as null
	} else {
		wantRoute = *result.SelectedRoute
	}
	wantFailure := any(nil)
	if result.FailureCode != nil {
		wantFailure = *result.FailureCode
	}
	if terminal.Data["status"] != result.Status || terminal.Data["route"] != wantRoute ||
		terminal.Data["failure_code"] != wantFailure {
		t.Fatalf("terminal payload: %+v (want status %v route %v failure %v)",
			terminal.Data, result.Status, wantRoute, wantFailure)
	}
}

func TestInvalidRouteFailsClosed(t *testing.T) {
	report, dispatcher := runPinned(t, "invalid-model-route@model")
	result := report.Result
	if result.Status != "FAILED" || result.SelectedRoute != nil ||
		result.SpecialistInvoked || *result.FailureCode != contracts.FailureInvalidRouteDecision {
		t.Fatalf("invalid route result: %+v", result)
	}
	if len(dispatcher.Invocations()) != 0 {
		t.Fatalf("invalid route must dispatch zero specialists, got %+v", dispatcher.Invocations())
	}
	for _, event := range report.Events {
		if step, _ := event.Data["step"].(string); strings.HasPrefix(step, "specialist.") {
			t.Fatalf("invalid route must not emit specialist steps: %+v", event.Data)
		}
	}
}

func TestSuccessDispatchesSpecialistOnce(t *testing.T) {
	report, dispatcher := runPinned(t, "billing-duplicate-charge@model")
	invocations := dispatcher.Invocations()
	if len(invocations) != 1 {
		t.Fatalf("dispatch count: %d", len(invocations))
	}
	if invocations[0].Route != "billing" ||
		invocations[0].Request != "I was charged twice for the same invoice." {
		t.Fatalf("invocation: %+v", invocations[0])
	}
	if !report.Result.SpecialistInvoked || *report.Result.SelectedRoute != "billing" {
		t.Fatalf("result: %+v", report.Result)
	}
}

func TestAttributionRuling(t *testing.T) {
	// M6 Ruling 5: classify cost is mode-dependent (route @0, model_decision
	// @2); invalid-route runs carry the classify record only.
	direct, _ := runPinned(t, "general-opening-hours@deterministic")
	if direct.Result.Attribution.Steps[0].CostCents != 0 ||
		direct.Result.Attribution.Totals.CostCents != 0 ||
		direct.Result.Attribution.Totals.LatencyMS != 42 {
		t.Fatalf("deterministic attribution: %+v", direct.Result.Attribution)
	}
	model, _ := runPinned(t, "general-opening-hours@model")
	if model.Result.Attribution.Steps[0].CostCents != 2 ||
		model.Result.Attribution.Totals.CostCents != 2 {
		t.Fatalf("model attribution: %+v", model.Result.Attribution)
	}
	invalid, _ := runPinned(t, "invalid-model-route@model")
	if len(invalid.Result.Attribution.Steps) != 1 ||
		invalid.Result.Attribution.Steps[0].StepName != "classify" ||
		invalid.Result.Attribution.Totals.LatencyMS != 30 {
		t.Fatalf("invalid-route attribution: %+v", invalid.Result.Attribution)
	}
}

func TestRunCaseToolingErrors(t *testing.T) {
	if _, err := RunCase(RunOptions{Mode: "model", CaseID: "no-such-case",
		TracePath: filepath.Join(t.TempDir(), "t.jsonl")}); err == nil {
		t.Fatal("unknown case must be a tooling error")
	}
	if _, err := RunCase(RunOptions{Mode: "model", CaseID: "billing-duplicate-charge",
		TracePath: ""}); err == nil {
		t.Fatal("empty trace path must fail result validation")
	}
	if _, err := RunCase(RunOptions{Mode: "bogus", CaseID: "billing-duplicate-charge",
		TracePath: filepath.Join(t.TempDir(), "t.jsonl")}); err == nil {
		t.Fatal("unknown mode must be a tooling error")
	}
}
