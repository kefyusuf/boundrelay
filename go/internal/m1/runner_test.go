package m1

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

// pinnedM1CaseKeys mirrors the canonical M1 case keys pinned by
// tools/contracts/test_m7_contracts.py (eight case keys, goldens named by
// case id; the mode is canonical per case).
var pinnedM1CaseKeys = []string{
	"direct-order-status",
	"agent-delayed-shipment",
	"agent-unknown-tool",
	"agent-invalid-arguments",
	"agent-tool-timeout",
	"agent-tool-failure",
	"agent-step-budget",
	"agent-token-budget",
}

// pinnedM1Modes carries the canonical mode per case (agent by default).
var pinnedM1Modes = map[string]string{"direct-order-status": ModeDirect}

func modeForKey(key string) string {
	if mode, ok := pinnedM1Modes[key]; ok {
		return mode
	}
	return ModeAgent
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
	dir := filepath.Join(root, "fixtures", "goldens", "order-investigation")
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
	if len(goldens) != len(pinnedM1CaseKeys) {
		t.Fatalf("expected %d goldens, found %d", len(pinnedM1CaseKeys), len(goldens))
	}
	for _, key := range pinnedM1CaseKeys {
		if _, ok := goldens[key]; !ok {
			t.Fatalf("missing golden for pinned key %s", key)
		}
	}
	return goldens
}

func resultProjection(t *testing.T, result contracts.ToolLoopResult) map[string]any {
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

// TestGoldenParity is the parity target: for all eight pinned M1 case keys
// the Go run's normalized result projection, event-type sequence, and
// attribution must equal the checked-in TS/PY goldens.
func TestGoldenParity(t *testing.T) {
	goldens := loadGoldens(t)
	for _, key := range pinnedM1CaseKeys {
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

// TestTraceLifecycleAndPayloads mirrors the M1 EXPECTED_EVENT_SURFACE from
// tools/contracts/test_m6_contracts.py plus the verify_m1 payload rules:
// run.created/started context, budget payloads, tool failure payloads,
// terminal payloads matching the result, and the direct-mode model-event ban.
func TestTraceLifecycleAndPayloads(t *testing.T) {
	lifecycles := map[string][]string{
		"direct-order-status": {
			"run.created", "run.started", "tool.requested", "tool.completed", "run.completed"},
		"agent-delayed-shipment": {
			"run.created", "run.started",
			"model.requested", "model.completed", "budget.consumed",
			"tool.requested", "tool.completed",
			"model.requested", "model.completed", "budget.consumed",
			"tool.requested", "tool.completed",
			"model.requested", "model.completed", "budget.consumed",
			"run.completed"},
		"agent-unknown-tool": {
			"run.created", "run.started", "model.requested", "model.completed",
			"budget.consumed", "run.failed"},
		"agent-invalid-arguments": {
			"run.created", "run.started", "model.requested", "model.completed",
			"budget.consumed", "run.failed"},
		"agent-tool-timeout": {
			"run.created", "run.started", "model.requested", "model.completed",
			"budget.consumed", "tool.requested", "tool.failed", "run.failed"},
		"agent-tool-failure": {
			"run.created", "run.started", "model.requested", "model.completed",
			"budget.consumed", "tool.requested", "tool.failed", "run.failed"},
		"agent-step-budget": {
			"run.created", "run.started",
			"model.requested", "model.completed", "budget.consumed",
			"tool.requested", "tool.completed",
			"model.requested", "model.completed", "budget.consumed",
			"budget.exceeded", "run.failed"},
		"agent-token-budget": {
			"run.created", "run.started",
			"model.requested", "model.completed", "budget.consumed",
			"tool.requested", "tool.completed",
			"model.requested", "model.completed", "budget.consumed",
			"budget.exceeded", "run.failed"},
	}
	for _, key := range pinnedM1CaseKeys {
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
			if events[0].Data["scenario_id"] != "order-investigation" ||
				events[0].Data["case_id"] != result.CaseID ||
				events[0].Data["mode"] != result.Mode {
				t.Fatalf("run.created context: %+v", events[0].Data)
			}
			if events[1].Data["case_id"] != result.CaseID || events[1].Data["mode"] != result.Mode {
				t.Fatalf("run.started context: %+v", events[1].Data)
			}
			if result.Mode == ModeDirect {
				for _, event := range events {
					if strings.HasPrefix(string(event.Type), "model.") {
						t.Fatalf("direct mode emitted model events: %+v", event.Data)
					}
				}
			}
			assertRequestedToolsAndTerminal(t, result, events)
		})
	}
}

func assertRequestedToolsAndTerminal(t *testing.T, result contracts.ToolLoopResult, events []contracts.Event) {
	t.Helper()
	var requested, failed, exceeded []contracts.Event
	for _, event := range events {
		switch event.Type {
		case contracts.EventToolRequested:
			requested = append(requested, event)
		case contracts.EventToolFailed:
			failed = append(failed, event)
		case contracts.EventBudgetExceeded:
			exceeded = append(exceeded, event)
		}
	}
	if len(requested) != result.ToolInvocations {
		t.Fatalf("tool.requested count %d != tool_invocations %d", len(requested), result.ToolInvocations)
	}
	if result.FailureCode != nil &&
		(*result.FailureCode == contracts.FailureUnknownTool ||
			*result.FailureCode == contracts.FailureInvalidToolArguments) && len(requested) != 0 {
		t.Fatalf("rejected decision must not emit tool.requested: %+v", requested)
	}
	if result.FailureCode != nil &&
		(*result.FailureCode == contracts.FailureToolTimeout ||
			*result.FailureCode == contracts.FailureToolExecutionFailed) {
		if len(failed) != 1 || failed[0].Data["failure_code"] != *result.FailureCode ||
			failed[0].Data["tool"] == nil || failed[0].Data["call_id"] == nil {
			t.Fatalf("must emit exactly one tool.failed with the failure code: %+v", failed)
		}
	}
	if result.FailureCode != nil &&
		(*result.FailureCode == contracts.FailureStepBudgetExceeded ||
			*result.FailureCode == contracts.FailureTokenBudgetExceeded) {
		budget := "step"
		if *result.FailureCode == contracts.FailureTokenBudgetExceeded {
			budget = "token"
		}
		if len(exceeded) != 1 || exceeded[0].Data["budget"] != budget ||
			exceeded[0].Data["failure_code"] != *result.FailureCode ||
			exceeded[0].Data["limit"] == nil || exceeded[0].Data["consumed"] == nil {
			t.Fatalf("budget.exceeded payload: %+v", exceeded)
		}
	}
	terminal := events[len(events)-1]
	wantType := contracts.EventRunCompleted
	if result.Status == StatusFailed {
		wantType = contracts.EventRunFailed
	}
	if terminal.Type != wantType {
		t.Fatalf("terminal type %s does not match status %s", terminal.Type, result.Status)
	}
	for _, key := range []string{"status", "model_steps", "tokens_used", "tool_invocations"} {
		if terminal.Data[key] != resultField(result, key) {
			t.Fatalf("terminal payload %s: %+v vs %v", key, terminal.Data[key], resultField(result, key))
		}
	}
	if result.Status == StatusSucceeded {
		if terminal.Data["answer"] != *result.Answer {
			t.Fatalf("terminal answer: %+v vs %v", terminal.Data["answer"], *result.Answer)
		}
	} else if terminal.Data["failure_code"] != *result.FailureCode {
		t.Fatalf("terminal failure_code: %+v vs %v", terminal.Data["failure_code"], *result.FailureCode)
	}
}

// resultField reads the counter fields by their terminal-payload names.
func resultField(result contracts.ToolLoopResult, key string) any {
	switch key {
	case "status":
		return result.Status
	case "model_steps":
		return result.ModelSteps
	case "tokens_used":
		return result.TokensUsed
	case "tool_invocations":
		return result.ToolInvocations
	}
	return nil
}

// TestCanonicalFailureCodesHaveExactCounters pins the four tool failure
// classes (M1-F1..F4) to their exact counters and payloads.
func TestCanonicalFailureCodesHaveExactCounters(t *testing.T) {
	cases := []struct {
		key      string
		code     string
		invokes  int
		toolsRun []string
	}{
		{"agent-unknown-tool", contracts.FailureUnknownTool, 0, []string{}},
		{"agent-invalid-arguments", contracts.FailureInvalidToolArguments, 0, []string{}},
		{"agent-tool-timeout", contracts.FailureToolTimeout, 1, []string{"lookup_order"}},
		{"agent-tool-failure", contracts.FailureToolExecutionFailed, 1, []string{"lookup_order"}},
	}
	for _, tc := range cases {
		t.Run(tc.code, func(t *testing.T) {
			report := runPinned(t, tc.key)
			result := report.Result
			if result.Status != StatusFailed || result.Answer != nil ||
				result.FailureCode == nil || *result.FailureCode != tc.code {
				t.Fatalf("result: %+v", result)
			}
			if result.ModelSteps != 1 || result.TokensUsed != 25 ||
				result.ToolInvocations != tc.invokes {
				t.Fatalf("counters: model_steps %d tokens_used %d tool_invocations %d",
					result.ModelSteps, result.TokensUsed, result.ToolInvocations)
			}
			// The attribution carries the model record only when no tool ran;
			// tool records carry the tool_call price kind.
			var gotNames []string
			for _, step := range result.Attribution.Steps {
				gotNames = append(gotNames, step.StepName)
			}
			wantNames := []string{"model"}
			for _, name := range tc.toolsRun {
				wantNames = append(wantNames, "tool."+name)
			}
			if !reflect.DeepEqual(gotNames, wantNames) {
				t.Fatalf("attribution names: %v, want %v", gotNames, wantNames)
			}
			if result.Attribution.Totals.CostCents != 2+tc.invokes ||
				result.Attribution.Totals.LatencyMS != 30+8*tc.invokes ||
				result.Attribution.Totals.Attempts != 1+tc.invokes {
				t.Fatalf("attribution totals: %+v", result.Attribution.Totals)
			}
		})
	}
}

// TestBudgetsFailClosed pins the two budget classes (step/token) to their
// exact counters and the budget.exceeded payloads.
func TestBudgetsFailClosed(t *testing.T) {
	step := runPinned(t, "agent-step-budget").Result
	if step.Status != StatusFailed || *step.FailureCode != contracts.FailureStepBudgetExceeded ||
		step.ModelSteps != 2 || step.TokensUsed != 50 || step.ToolInvocations != 1 {
		t.Fatalf("step budget result: %+v", step)
	}
	token := runPinned(t, "agent-token-budget").Result
	if token.Status != StatusFailed || *token.FailureCode != contracts.FailureTokenBudgetExceeded ||
		token.ModelSteps != 2 || token.TokensUsed != 75 || token.ToolInvocations != 1 {
		t.Fatalf("token budget result: %+v", token)
	}
}

// TestAttributionOrderAndSums pins the M6 attribution ruling: the model
// record first in agent mode, tool.<name> records in first-invocation
// order, latency/price multiplied by attempts, totals summing every record,
// and no model record in direct mode.
func TestAttributionOrderAndSums(t *testing.T) {
	delayed := runPinned(t, "agent-delayed-shipment").Result
	names := make([]string, 0, len(delayed.Attribution.Steps))
	for _, step := range delayed.Attribution.Steps {
		names = append(names, step.StepName)
	}
	if !reflect.DeepEqual(names, []string{"model", "tool.lookup_order", "tool.lookup_shipment"}) {
		t.Fatalf("attribution order: %v", names)
	}
	if delayed.Attribution.Steps[0].LatencyMS != 90 || delayed.Attribution.Steps[0].CostCents != 6 {
		t.Fatalf("model record: %+v", delayed.Attribution.Steps[0])
	}
	if delayed.Attribution.Totals.LatencyMS != 107 || delayed.Attribution.Totals.CostCents != 8 ||
		delayed.Attribution.Totals.Attempts != 5 {
		t.Fatalf("totals: %+v", delayed.Attribution.Totals)
	}
	direct := runPinned(t, "direct-order-status").Result
	if len(direct.Attribution.Steps) != 1 || direct.Attribution.Steps[0].StepName != "tool.lookup_order" ||
		direct.Attribution.Totals.CostCents != 1 || direct.Attribution.Totals.LatencyMS != 8 {
		t.Fatalf("direct attribution: %+v", direct.Attribution)
	}
	for _, record := range append(append([]contracts.StepAttribution{}, delayed.Attribution.Steps...),
		direct.Attribution.Steps...) {
		if record.LatencyMS < 0 || record.CostCents < 0 || record.Attempts < 1 {
			t.Fatalf("record bounds: %+v", record)
		}
	}
}

// failingProvider errors on every turn (the scripted provider's missing
// trajectory/out-of-order classes).
type failingProvider struct{}

func (failingProvider) NextTurn(ModelInput) (json.RawMessage, error) {
	return nil, fmt.Errorf("Missing scripted trajectory for case: agent-unknown-tool")
}

// malformedProvider returns a schema-invalid turn.
type malformedProvider struct{}

func (malformedProvider) NextTurn(ModelInput) (json.RawMessage, error) {
	return json.RawMessage(`{"schema_version":"1.0","decision":{"kind":"teleport"},"usage":{"input_tokens":1,"output_tokens":1}}`), nil
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

// TestInvalidModelDecisionFailsClosed covers the seventh failure code:
// provider errors emit model.failed, malformed turns fail closed without
// one, and both produce the INVALID_MODEL_DECISION result.
func TestInvalidModelDecisionFailsClosed(t *testing.T) {
	scenario := scenarioFor(t)
	tracePath := filepath.Join(t.TempDir(), "trace.jsonl")
	report := runWithOptions(t, RunOptions{
		Mode: ModeAgent, CaseID: "agent-unknown-tool", TracePath: tracePath,
		Scenario: scenario, Provider: failingProvider{}})
	result := report.Result
	if result.Status != StatusFailed || result.FailureCode == nil ||
		*result.FailureCode != contracts.FailureInvalidModelDecision ||
		result.ModelSteps != 1 || result.TokensUsed != 0 || result.ToolInvocations != 0 {
		t.Fatalf("provider-error result: %+v", result)
	}
	types := make([]string, 0, len(report.Events))
	for _, event := range report.Events {
		types = append(types, string(event.Type))
	}
	want := []string{"run.created", "run.started", "model.requested", "model.failed", "run.failed"}
	if !reflect.DeepEqual(types, want) {
		t.Fatalf("provider-error lifecycle: %v", types)
	}
	lastModel := report.Events[len(report.Events)-2]
	if lastModel.Type != contracts.EventModelFailed ||
		lastModel.Data["failure_code"] != contracts.FailureInvalidModelDecision {
		t.Fatalf("model.failed payload: %+v", lastModel.Data)
	}
	// A malformed (schema-invalid) turn fails closed without model.failed.
	tracePath = filepath.Join(t.TempDir(), "trace.jsonl")
	report = runWithOptions(t, RunOptions{
		Mode: ModeAgent, CaseID: "agent-unknown-tool", TracePath: tracePath,
		Scenario: scenario, Provider: malformedProvider{}})
	result = report.Result
	if result.Status != StatusFailed || result.FailureCode == nil ||
		*result.FailureCode != contracts.FailureInvalidModelDecision || result.TokensUsed != 0 {
		t.Fatalf("malformed-turn result: %+v", result)
	}
	for _, event := range report.Events {
		if event.Type == contracts.EventModelFailed {
			t.Fatal("malformed turns must fail closed without model.failed")
		}
	}
}

// TestScriptedProviderRejectsDrift pins the scripted schedule contract:
// out-of-order or over-length schedules are domain failures, not tooling.
func TestScriptedProviderRejectsDrift(t *testing.T) {
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("repo root: %v", err)
	}
	turns, err := LoadFakeModelTurns(DefaultFakeModelPath(root))
	if err != nil {
		t.Fatalf("LoadFakeModelTurns: %v", err)
	}
	provider := NewScriptedModelProvider(turns)
	if _, err := provider.NextTurn(ModelInput{CaseID: "agent-unknown-tool", ModelStep: 2}); err == nil {
		t.Fatal("out-of-order step must be rejected")
	}
	first, err := provider.NextTurn(ModelInput{CaseID: "agent-unknown-tool", ModelStep: 1})
	if err != nil {
		t.Fatalf("step 1: %v", err)
	}
	turn, err := ValidateModelTurn(first)
	if err != nil {
		t.Fatalf("validate turn: %v", err)
	}
	if turn.Decision.Kind != DecisionToolCall || turn.Decision.Tool != "lookup_customer" ||
		turn.InputTokens != 20 || turn.OutputTokens != 5 {
		t.Fatalf("turn: %+v", turn)
	}
	if _, err := provider.NextTurn(ModelInput{CaseID: "agent-unknown-tool", ModelStep: 2}); err == nil ||
		!strings.Contains(err.Error(), "exhausted") {
		t.Fatalf("exhausted trajectory must be rejected: %v", err)
	}
}

func TestRunCaseToolingErrors(t *testing.T) {
	scenario := scenarioFor(t)
	tracePath := func() string { return filepath.Join(t.TempDir(), "t.jsonl") }
	// Unknown case.
	if _, err := RunCase(RunOptions{Mode: ModeAgent, CaseID: "no-such-case",
		TracePath: tracePath()}); !strings.Contains(err.Error(), "unknown scenario case") {
		t.Fatalf("unknown case: %v", err)
	}
	// Mode mismatch in both directions.
	if _, err := RunCase(RunOptions{Mode: ModeAgent, CaseID: "direct-order-status",
		TracePath: tracePath(), Scenario: scenario}); err == nil ||
		!strings.Contains(err.Error(), ErrModeMismatch.Error()) {
		t.Fatalf("mode mismatch: %v", err)
	}
	if _, err := RunCase(RunOptions{Mode: ModeDirect, CaseID: "agent-unknown-tool",
		TracePath: tracePath(), Scenario: scenario}); err == nil ||
		!strings.Contains(err.Error(), ErrModeMismatch.Error()) {
		t.Fatalf("mode mismatch: %v", err)
	}
	// Unknown mode.
	if _, err := RunCase(RunOptions{Mode: "bogus", CaseID: "agent-unknown-tool",
		TracePath: tracePath()}); err == nil {
		t.Fatal("unknown mode must be a tooling error")
	}
	// Empty trace path fails result validation without a trace file.
	if _, err := RunCase(RunOptions{Mode: ModeDirect, CaseID: "direct-order-status",
		TracePath: "", Scenario: scenario}); err == nil {
		t.Fatal("empty trace path must fail result validation")
	}
}
