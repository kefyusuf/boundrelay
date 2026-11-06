package m2

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

// pinnedM2CaseKeys mirrors the canonical M2 case keys pinned by
// tools/contracts/test_m7_contracts.py (five case keys, goldens named by
// case id; the router mode is canonical per case).
var pinnedM2CaseKeys = []string{
	"code-billing-handoff",
	"model-technical-handoff",
	"model-low-confidence-fallback",
	"handoff-context-loss",
	"handoff-receiver-unavailable",
}

// pinnedM2Modes carries the canonical router mode per case.
var pinnedM2Modes = map[string]string{
	"code-billing-handoff":          ModeCode,
	"model-technical-handoff":       ModeModel,
	"model-low-confidence-fallback": ModeModel,
	"handoff-context-loss":          ModeModel,
	"handoff-receiver-unavailable":  ModeCode,
}

func modeForKey(key string) string {
	if mode, ok := pinnedM2Modes[key]; ok {
		return mode
	}
	panic(fmt.Sprintf("m2 test: unpinned case key %s", key))
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
	dir := filepath.Join(root, "fixtures", "goldens", "support-handoff")
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
	if len(goldens) != len(pinnedM2CaseKeys) {
		t.Fatalf("expected %d goldens, found %d", len(pinnedM2CaseKeys), len(goldens))
	}
	for _, key := range pinnedM2CaseKeys {
		if _, ok := goldens[key]; !ok {
			t.Fatalf("missing golden for pinned key %s", key)
		}
	}
	return goldens
}

func resultProjection(t *testing.T, result contracts.HandoffResult) map[string]any {
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
		if step, ok := event.Data["step_name"].(string); ok {
			stepName = step
		} else if step, ok := event.Data["step"].(string); ok {
			stepName = step
		}
		projection = append(projection, map[string]any{
			"type": string(event.Type), "step_name": stepName})
	}
	return projection
}

// runPinned runs one pinned key in-process against the checked-in
// projections.
func runPinned(t *testing.T, key string) RunReport {
	t.Helper()
	tracePath := filepath.Join(t.TempDir(), "trace.jsonl")
	report, err := RunCase(RunOptions{
		Mode: modeForKey(key), CaseID: key, TracePath: tracePath})
	if err != nil {
		t.Fatalf("RunCase(%s): %v", key, err)
	}
	return report
}

// TestGoldenParity is the parity target: for all five pinned M2 case keys
// the Go run's normalized result projection, event-type sequence, and
// attribution must equal the checked-in TS/PY goldens.
func TestGoldenParity(t *testing.T) {
	goldens := loadGoldens(t)
	for _, key := range pinnedM2CaseKeys {
		t.Run(key, func(t *testing.T) {
			g := goldens[key]
			tracePath := filepath.Join(t.TempDir(), "trace.jsonl")
			report, err := RunCase(RunOptions{
				Mode: modeForKey(key), CaseID: key, TracePath: tracePath})
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
		if event.Source != contracts.SourceGo {
			t.Fatalf("trace line %d must carry source %q: %+v", i+1, contracts.SourceGo, event)
		}
	}
}

// TestTraceLifecycleAndPayloads mirrors the M2 EXPECTED_EVENT_SURFACE from
// tools/contracts/test_m6_contracts.py exactly, plus the payload rules:
// run.created/started context, the route.selected payload, the handoff
// envelope payload, handoff rejections, and terminal payloads matching the
// result (code mode emits no model events).
func TestTraceLifecycleAndPayloads(t *testing.T) {
	lifecycles := map[string][]string{
		"code-billing-handoff": {
			"run.created", "run.started", "route.selected", "handoff.requested",
			"handoff.accepted", "run.completed"},
		"model-technical-handoff": {
			"run.created", "run.started", "model.requested", "model.completed",
			"route.selected", "handoff.requested", "handoff.accepted", "run.completed"},
		"model-low-confidence-fallback": {
			"run.created", "run.started", "model.requested", "model.completed",
			"route.selected", "handoff.requested", "handoff.accepted", "run.completed"},
		"handoff-context-loss": {
			"run.created", "run.started", "model.requested", "model.completed",
			"route.selected", "handoff.requested", "handoff.rejected", "run.failed"},
		"handoff-receiver-unavailable": {
			"run.created", "run.started", "route.selected", "handoff.requested",
			"handoff.rejected", "run.failed"},
	}
	for _, key := range pinnedM2CaseKeys {
		t.Run(key, func(t *testing.T) {
			report := runPinned(t, key)
			result := report.Result
			events := report.Events
			want := lifecycles[key]
			got := make([]string, 0, len(events))
			for _, event := range events {
				got = append(got, string(event.Type))
			}
			if !reflect.DeepEqual(got, want) {
				t.Fatalf("lifecycle divergence:\n got %v\nwant %v", got, want)
			}
			if events[0].Data["scenario_id"] != "support-handoff" ||
				events[0].Data["case_id"] != result.CaseID ||
				events[0].Data["router_mode"] != result.RouterMode {
				t.Fatalf("run.created context: %+v", events[0].Data)
			}
			if events[1].Data["case_id"] != result.CaseID ||
				events[1].Data["router_mode"] != result.RouterMode {
				t.Fatalf("run.started context: %+v", events[1].Data)
			}
			if result.RouterMode == ModeCode {
				for _, event := range events {
					if strings.HasPrefix(string(event.Type), "model.") {
						t.Fatalf("code mode emitted model events: %+v", event.Data)
					}
				}
			}
			for _, event := range events {
				switch event.Type {
				case contracts.EventModelRequested:
					if event.Data["case_id"] != result.CaseID {
						t.Fatalf("model.requested payload: %+v", event.Data)
					}
				case contracts.EventModelCompleted:
					decision, ok := event.Data["decision"].(map[string]any)
					if !ok || event.Data["case_id"] != result.CaseID {
						t.Fatalf("model.completed payload: %+v", event.Data)
					}
					if _, ok := decision["confidence"].(float64); !ok {
						t.Fatalf("model.completed decision must carry a numeric confidence: %+v", decision)
					}
				case contracts.EventRouteSelected:
					if event.Data["router_mode"] != result.RouterMode ||
						event.Data["proposed_route"] != *result.ProposedRoute ||
						event.Data["selected_route"] != *result.SelectedRoute ||
						event.Data["fallback_applied"] != result.FallbackApplied {
						t.Fatalf("route.selected payload: %+v", event.Data)
					}
					if _, ok := event.Data["confidence"].(float64); !ok {
						t.Fatalf("route.selected must carry a numeric confidence: %+v", event.Data)
					}
				case contracts.EventHandoffRequested:
					if event.Data["sender"] != Sender || event.Data["receiver"] != *result.Receiver ||
						event.Data["handoff_id"] == "" {
						t.Fatalf("handoff.requested payload: %+v", event.Data)
					}
					intent, ok := event.Data["sender_intent"].(map[string]any)
					if !ok || intent["route"] != *result.ProposedRoute ||
						intent["policy_outcome"] != "selected" && intent["policy_outcome"] != "fallback" {
						t.Fatalf("handoff.requested sender_intent: %+v", event.Data)
					}
					input, ok := event.Data["receiver_input"].(map[string]any)
					if !ok || input["ticket_id"] == nil {
						t.Fatalf("handoff.requested receiver_input: %+v", event.Data)
					}
					// The context-loss fixture omits request_text; every other
					// canonical case carries the complete receiver input.
					_, hasRequestText := input["request_text"]
					if key == "handoff-context-loss" && hasRequestText {
						t.Fatalf("context loss must omit request_text: %+v", input)
					}
					if key != "handoff-context-loss" && !hasRequestText {
						t.Fatalf("receiver_input must carry request_text: %+v", input)
					}
				case contracts.EventHandoffAccepted, contracts.EventHandoffRejected:
					if event.Data["handoff_id"] == "" || event.Data["receiver"] != *result.Receiver {
						t.Fatalf("%s payload: %+v", event.Type, event.Data)
					}
				}
			}
			assertHandoffTerminal(t, result, events)
		})
	}
}

// assertHandoffTerminal pins the terminal event against the result and the
// zero-dispatch claims for the failure classes.
func assertHandoffTerminal(t *testing.T, result contracts.HandoffResult, events []contracts.Event) {
	t.Helper()
	terminal := events[len(events)-1]
	wantType := contracts.EventRunCompleted
	if result.Status == StatusFailed {
		wantType = contracts.EventRunFailed
	}
	if terminal.Type != wantType {
		t.Fatalf("terminal type %s does not match status %s", terminal.Type, result.Status)
	}
	for _, key := range []string{"status", "proposed_route", "selected_route",
		"receiver", "fallback_applied", "specialist_invoked"} {
		if !reflect.DeepEqual(terminal.Data[key], resultField(result, key)) {
			t.Fatalf("terminal payload %s: %+v vs %v", key, terminal.Data[key], resultField(result, key))
		}
	}
	if result.Status == StatusFailed {
		if terminal.Data["failure_code"] != *result.FailureCode {
			t.Fatalf("terminal failure_code: %+v vs %v", terminal.Data["failure_code"], *result.FailureCode)
		}
	} else if _, present := terminal.Data["failure_code"]; present {
		t.Fatalf("run.completed must not carry failure_code: %+v", terminal.Data)
	}
}

// resultField reads the result fields by their terminal-payload names.
func resultField(result contracts.HandoffResult, key string) any {
	switch key {
	case "status":
		return result.Status
	case "proposed_route":
		return nullableString(result.ProposedRoute)
	case "selected_route":
		return nullableString(result.SelectedRoute)
	case "receiver":
		return nullableString(result.Receiver)
	case "fallback_applied":
		return result.FallbackApplied
	case "specialist_invoked":
		return result.SpecialistInvoked
	}
	return nil
}

// TestHandoffFailuresFailClosed pins the two handoff failure classes
// (M2-F1/M2-F2): exact failure codes, specialist_invoked false, and zero
// dispatches recorded by the receiver directory.
func TestHandoffFailuresFailClosed(t *testing.T) {
	cases := []struct {
		key         string
		code        string
		proposeCost int
	}{
		{"handoff-context-loss", contracts.FailureHandoffContextInvalid, 2},
		{"handoff-receiver-unavailable", contracts.FailureHandoffReceiverUnavailable, 0},
	}
	for _, tc := range cases {
		t.Run(tc.code, func(t *testing.T) {
			tracePath := filepath.Join(t.TempDir(), "trace.jsonl")
			directory := NewRecordingReceiverDirectory()
			report, err := RunCase(RunOptions{
				Mode: modeForKey(tc.key), CaseID: tc.key, TracePath: tracePath,
				Directory: directory})
			if err != nil {
				t.Fatalf("RunCase: %v", err)
			}
			result := report.Result
			if result.Status != StatusFailed || result.FailureCode == nil ||
				*result.FailureCode != tc.code || result.SpecialistInvoked {
				t.Fatalf("result: %+v", result)
			}
			if result.ProposedRoute == nil || result.SelectedRoute == nil || result.Receiver == nil {
				t.Fatalf("handoff failures must keep the routing context: %+v", result)
			}
			if invocations := directory.Invocations(); len(invocations) != 0 {
				t.Fatalf("failures must record zero dispatches: %+v", invocations)
			}
			// The classify record only: no receiver record on failure.
			if len(result.Attribution.Steps) != 1 || result.Attribution.Steps[0].StepName != "classify" {
				t.Fatalf("attribution: %+v", result.Attribution)
			}
			if result.Attribution.Totals.CostCents != tc.proposeCost ||
				result.Attribution.Totals.LatencyMS != 30 || result.Attribution.Totals.Attempts != 1 {
				t.Fatalf("attribution totals: %+v", result.Attribution.Totals)
			}
		})
	}
}

// decisionProviderFor returns a provider whose decision for the case is an
// arbitrary route/confidence pair (the policy boundary probe).
func decisionProviderFor(route string, confidence float64) RouteDecisionProvider {
	raw, _ := json.Marshal(map[string]any{"route": route, "confidence": confidence})
	return NewScriptedRouteProvider(map[string]json.RawMessage{
		"model-low-confidence-fallback": raw})
}

// TestFallbackPolicyBoundary pins the 0.80 policy through injected model
// decisions: 0.79 falls back to general, 0.80/0.81 keep the proposed route,
// and the fallback still invokes the general receiver.
func TestFallbackPolicyBoundary(t *testing.T) {
	cases := []struct {
		confidence      float64
		selectedRoute   string
		receiver        string
		fallbackApplied bool
		outcome         string
	}{
		{0.79, RouteGeneral, ReceiverGeneral, true, "fallback"},
		{0.80, RouteBilling, ReceiverBilling, false, "selected"},
		{0.81, RouteBilling, ReceiverBilling, false, "selected"},
	}
	scenario := scenarioFor(t)
	for _, tc := range cases {
		t.Run(fmt.Sprintf("confidence_%v", tc.confidence), func(t *testing.T) {
			directory := NewRecordingReceiverDirectory()
			report, err := RunCase(RunOptions{
				Mode: ModeModel, CaseID: "model-low-confidence-fallback",
				TracePath: filepath.Join(t.TempDir(), "trace.jsonl"),
				Scenario:  scenario, Provider: decisionProviderFor(RouteBilling, tc.confidence),
				Directory: directory})
			if err != nil {
				t.Fatalf("RunCase: %v", err)
			}
			result := report.Result
			if result.Status != StatusSucceeded || result.FailureCode != nil ||
				!result.SpecialistInvoked || result.ProposedRoute == nil ||
				*result.ProposedRoute != RouteBilling ||
				*result.SelectedRoute != tc.selectedRoute || *result.Receiver != tc.receiver ||
				result.FallbackApplied != tc.fallbackApplied {
				t.Fatalf("result: %+v", result)
			}
			invocations := directory.Invocations()
			if len(invocations) != 1 || invocations[0].Receiver != tc.receiver ||
				invocations[0].Input.TicketID != "TCK-1003" ||
				invocations[0].Input.RequestText == "" {
				t.Fatalf("dispatch: %+v", invocations)
			}
			// The dispatch input is the receiver's own work item: the sender
			// intent travels beside it, never inside it.
			var wanted map[string]any
			for _, event := range report.Events {
				if event.Type == contracts.EventHandoffRequested {
					wanted, _ = event.Data["sender_intent"].(map[string]any)
				}
			}
			if wanted == nil || wanted["policy_outcome"] != tc.outcome ||
				wanted["route"] != RouteBilling {
				t.Fatalf("sender intent: %+v", wanted)
			}
			for _, event := range report.Events {
				if event.Type == contracts.EventHandoffRequested {
					input, _ := event.Data["receiver_input"].(map[string]any)
					if _, present := input["route"]; present ||
						input["ticket_id"] != "TCK-1003" {
						t.Fatalf("receiver_input must stay intent-free: %+v", input)
					}
				}
			}
		})
	}
}

// TestAttributionOrderAndSums pins the M6 attribution ruling for M2: the
// classify record first, the receiver.<name> record on success, the
// mode-dependent classify price kind, and totals summing every record.
func TestAttributionOrderAndSums(t *testing.T) {
	code := runPinned(t, "code-billing-handoff").Result
	names := make([]string, 0, len(code.Attribution.Steps))
	for _, step := range code.Attribution.Steps {
		names = append(names, step.StepName)
	}
	if !reflect.DeepEqual(names, []string{"classify", "receiver.billing-specialist"}) {
		t.Fatalf("code attribution order: %v", names)
	}
	if code.Attribution.Steps[0].CostCents != 0 || code.Attribution.Steps[0].LatencyMS != 30 {
		t.Fatalf("code classify record must price the route kind: %+v", code.Attribution.Steps[0])
	}
	if code.Attribution.Totals.LatencyMS != 40 || code.Attribution.Totals.CostCents != 0 ||
		code.Attribution.Totals.Attempts != 2 {
		t.Fatalf("code totals: %+v", code.Attribution.Totals)
	}
	model := runPinned(t, "model-low-confidence-fallback").Result
	if !reflect.DeepEqual(model.Attribution.Steps[0].StepName, "classify") ||
		model.Attribution.Steps[0].CostCents != 2 || model.Attribution.Steps[0].LatencyMS != 30 {
		t.Fatalf("model classify record must price the model_decision kind: %+v",
			model.Attribution.Steps[0])
	}
	if model.Attribution.Steps[1].StepName != "receiver.general-specialist" ||
		model.Attribution.Steps[1].LatencyMS != 12 || model.Attribution.Steps[1].CostCents != 0 {
		t.Fatalf("receiver record: %+v", model.Attribution.Steps[1])
	}
	if model.Attribution.Totals.LatencyMS != 42 || model.Attribution.Totals.CostCents != 2 ||
		model.Attribution.Totals.Attempts != 2 {
		t.Fatalf("model totals: %+v", model.Attribution.Totals)
	}
}

// missingDecisionProvider errors on every decision (the scripted provider's
// missing/consumed schedule classes).
type missingDecisionProvider struct{}

func (missingDecisionProvider) NextDecision(DecisionInput) (json.RawMessage, error) {
	return nil, fmt.Errorf("Missing scripted decision for case: model-technical-handoff")
}

// malformedDecisionProvider returns a schema-invalid decision.
type malformedDecisionProvider struct{}

func (malformedDecisionProvider) NextDecision(DecisionInput) (json.RawMessage, error) {
	return json.RawMessage(`{"route": "teleport", "confidence": 0.9}`), nil
}

func scenarioFor(t *testing.T) *Scenario {
	t.Helper()
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("repo root: %v", err)
	}
	scenario, err := LoadScenario(DefaultScenarioPath(root))
	if err != nil {
		t.Fatalf("LoadScenario: %v", err)
	}
	return scenario
}

func runWithOptions(t *testing.T, options RunOptions) RunReport {
	t.Helper()
	report, err := RunCase(options)
	if err != nil {
		t.Fatalf("RunCase: %v", err)
	}
	return report
}

// TestInvalidRouteDecisionFailsClosed covers the INVALID_ROUTE_DECISION
// class: a malformed scripted decision emits route.rejected, clears the
// routing context, and never builds a handoff.
func TestInvalidRouteDecisionFailsClosed(t *testing.T) {
	scenario := scenarioFor(t)
	directory := NewRecordingReceiverDirectory()
	tracePath := filepath.Join(t.TempDir(), "trace.jsonl")
	report := runWithOptions(t, RunOptions{
		Mode: ModeModel, CaseID: "model-technical-handoff", TracePath: tracePath,
		Scenario: scenario, Provider: malformedDecisionProvider{}, Directory: directory})
	result := report.Result
	if result.Status != StatusFailed || result.FailureCode == nil ||
		*result.FailureCode != contracts.FailureInvalidRouteDecision ||
		result.ProposedRoute != nil || result.SelectedRoute != nil || result.Receiver != nil ||
		result.FallbackApplied || result.SpecialistInvoked {
		t.Fatalf("result: %+v", result)
	}
	if invocations := directory.Invocations(); len(invocations) != 0 {
		t.Fatalf("invalid routes must record zero dispatches: %+v", invocations)
	}
	types := make([]string, 0, len(report.Events))
	for _, event := range report.Events {
		types = append(types, string(event.Type))
	}
	want := []string{"run.created", "run.started", "model.requested", "model.completed",
		"route.rejected", "run.failed"}
	if !reflect.DeepEqual(types, want) {
		t.Fatalf("lifecycle: %v", types)
	}
	rejected := report.Events[len(report.Events)-2]
	if rejected.Type != contracts.EventRouteRejected ||
		rejected.Data["failure_code"] != contracts.FailureInvalidRouteDecision ||
		rejected.Data["router_mode"] != ModeModel {
		t.Fatalf("route.rejected payload: %+v", rejected.Data)
	}
}

// TestProviderErrorsAreTooling pins the scripted-schedule boundary: provider
// errors are tooling drift (exit 2), leave no trace, and never flush events.
func TestProviderErrorsAreTooling(t *testing.T) {
	scenario := scenarioFor(t)
	tracePath := filepath.Join(t.TempDir(), "trace.jsonl")
	_, err := RunCase(RunOptions{
		Mode: ModeModel, CaseID: "model-technical-handoff", TracePath: tracePath,
		Scenario: scenario, Provider: missingDecisionProvider{}})
	if err == nil || !strings.Contains(err.Error(), "Missing scripted decision") {
		t.Fatalf("provider error must be a tooling error: %v", err)
	}
	if _, statErr := os.Stat(tracePath); !os.IsNotExist(statErr) {
		t.Fatal("tooling failures must leave no trace")
	}
}

// TestRunCaseToolingErrors covers the tooling error classes: unknown cases,
// mode mismatches in both directions, unknown modes, and empty trace paths.
func TestRunCaseToolingErrors(t *testing.T) {
	scenario := scenarioFor(t)
	tracePath := func() string { return filepath.Join(t.TempDir(), "t.jsonl") }
	if _, err := RunCase(RunOptions{Mode: ModeModel, CaseID: "no-such-case",
		TracePath: tracePath()}); !strings.Contains(err.Error(), "unknown scenario case") {
		t.Fatalf("unknown case: %v", err)
	}
	if _, err := RunCase(RunOptions{Mode: ModeModel, CaseID: "code-billing-handoff",
		TracePath: tracePath(), Scenario: scenario}); err == nil ||
		!strings.Contains(err.Error(), ErrModeMismatch.Error()) {
		t.Fatalf("mode mismatch: %v", err)
	}
	if _, err := RunCase(RunOptions{Mode: ModeCode, CaseID: "model-technical-handoff",
		TracePath: tracePath(), Scenario: scenario}); err == nil ||
		!strings.Contains(err.Error(), ErrModeMismatch.Error()) {
		t.Fatalf("mode mismatch: %v", err)
	}
	if _, err := RunCase(RunOptions{Mode: "bogus", CaseID: "code-billing-handoff",
		TracePath: tracePath()}); err == nil {
		t.Fatal("unknown mode must be a tooling error")
	}
	if _, err := RunCase(RunOptions{Mode: ModeCode, CaseID: "code-billing-handoff",
		TracePath: "", Scenario: scenario}); err == nil {
		t.Fatal("empty trace path must fail result validation")
	}
}

// TestHandoffResultContract pins the shared result contract against the
// closed handoff-result schema enum.
func TestHandoffResultContract(t *testing.T) {
	if !contracts.IsM2FailureCode("HANDOFF_CONTEXT_INVALID") ||
		!contracts.IsM2FailureCode("HANDOFF_RECEIVER_UNAVAILABLE") ||
		!contracts.IsM2FailureCode("INVALID_ROUTE_DECISION") ||
		contracts.IsM2FailureCode("UNKNOWN_TOOL") {
		t.Fatal("M2 failure-code enum drifted")
	}
	// The result JSON must carry null (not absent) for the nullable fields,
	// mirroring the TS/Py result lines.
	report := runPinned(t, "handoff-context-loss")
	raw, err := json.Marshal(report.Result)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var flat map[string]any
	if err := json.Unmarshal(raw, &flat); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	for _, key := range []string{"schema_version", "run_id", "scenario_id", "case_id",
		"router_mode", "status", "proposed_route", "selected_route", "receiver",
		"fallback_applied", "specialist_invoked", "failure_code", "trace_path", "attribution"} {
		if _, present := flat[key]; !present {
			t.Fatalf("result line must always carry %s: %v", key, flat)
		}
	}
}
