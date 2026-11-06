package m2

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// writeProjection writes one JSON projection document into a temp directory
// and returns its path.
func writeProjection(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "projection.json")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write projection: %v", err)
	}
	return path
}

// canonicalScenario is a minimal valid scenario projection carrying one
// success case and one failure case (the loader's closed-set rule is
// exercised against the checked-in document in runner_test.go's parity
// tests; these unit tests pin the per-case validation against a trimmed
// document, so the canonical-set check is waived by using all five ids).
const canonicalScenario = `{
  "schema_version": "1.0",
  "scenario_id": "support-handoff",
  "confidence_threshold": 0.80,
  "route_receivers": {"billing": "billing-specialist", "technical": "technical-specialist", "general": "general-specialist"},
  "attribution": {"latency_ms": {"classify": 30, "receiver.billing-specialist": 10},
                  "price_table": {"route": 0, "model_decision": 2, "handoff": 0}},
  "cases": [
    {"id": "code-billing-handoff", "ticket_id": "TCK-1001",
     "request": "I was charged twice.", "router_mode": "code",
     "expected_status": "SUCCEEDED", "expected_proposed_route": "billing",
     "expected_confidence": 1.0, "expected_selected_route": "billing",
     "expected_receiver": "billing-specialist", "expected_policy_outcome": "selected",
     "expected_fallback_applied": false, "expected_specialist_invoked": true},
    {"id": "handoff-context-loss", "ticket_id": "TCK-9001",
     "request": "I was billed for a service I did not receive.", "router_mode": "model",
     "expected_status": "FAILED", "expected_proposed_route": "billing",
     "expected_confidence": 0.93, "expected_selected_route": "billing",
     "expected_receiver": "billing-specialist", "expected_policy_outcome": "selected",
     "expected_fallback_applied": false, "expected_specialist_invoked": false,
     "expected_failure_code": "HANDOFF_CONTEXT_INVALID", "failure_ref": "handoff-context-loss"},
    {"id": "model-technical-handoff", "ticket_id": "TCK-1002",
     "request": "The screen rejects the code.", "router_mode": "model",
     "expected_status": "SUCCEEDED", "expected_proposed_route": "technical",
     "expected_confidence": 0.92, "expected_selected_route": "technical",
     "expected_receiver": "technical-specialist", "expected_policy_outcome": "selected",
     "expected_fallback_applied": false, "expected_specialist_invoked": true},
    {"id": "model-low-confidence-fallback", "ticket_id": "TCK-1003",
     "request": "Something looks wrong.", "router_mode": "model",
     "expected_status": "SUCCEEDED", "expected_proposed_route": "billing",
     "expected_confidence": 0.54, "expected_selected_route": "general",
     "expected_receiver": "general-specialist", "expected_policy_outcome": "fallback",
     "expected_fallback_applied": true, "expected_specialist_invoked": true},
    {"id": "handoff-receiver-unavailable", "ticket_id": "TCK-9002",
     "request": "I need help with a charge.", "router_mode": "code",
     "expected_status": "FAILED", "expected_proposed_route": "billing",
     "expected_confidence": 1.0, "expected_selected_route": "billing",
     "expected_receiver": "billing-specialist", "expected_policy_outcome": "selected",
     "expected_fallback_applied": false, "expected_specialist_invoked": false,
     "expected_failure_code": "HANDOFF_RECEIVER_UNAVAILABLE", "failure_ref": "handoff-receiver-unavailable"}
  ]
}`

func TestLoadScenarioCanonical(t *testing.T) {
	scenario, err := LoadScenario(writeProjection(t, canonicalScenario))
	if err != nil {
		t.Fatalf("LoadScenario: %v", err)
	}
	if scenario.ScenarioID != "support-handoff" || scenario.ConfidenceThreshold != 0.80 ||
		len(scenario.Cases) != 5 {
		t.Fatalf("scenario: %+v", scenario)
	}
	if scenario.RouteReceivers["billing"] != ReceiverBilling ||
		scenario.RouteReceivers["general"] != ReceiverGeneral {
		t.Fatalf("route receivers: %+v", scenario.RouteReceivers)
	}
	code, err := scenario.FindCase("code-billing-handoff")
	if err != nil {
		t.Fatalf("FindCase: %v", err)
	}
	if code.TicketID != "TCK-1001" || code.RouterMode != ModeCode ||
		code.ExpectedFailureCode != "" || code.FailureRef != "" {
		t.Fatalf("code case: %+v", code)
	}
	failed, err := scenario.FindCase("handoff-context-loss")
	if err != nil {
		t.Fatalf("FindCase: %v", err)
	}
	if failed.ExpectedFailureCode != "HANDOFF_CONTEXT_INVALID" ||
		failed.FailureRef != "handoff-context-loss" {
		t.Fatalf("failed case: %+v", failed)
	}
	if _, err := scenario.FindCase("no-such-case"); err == nil {
		t.Fatal("unknown case must be a tooling error")
	}
}

func TestLoadScenarioRejections(t *testing.T) {
	rejections := []struct {
		name    string
		content string
		frag    string
	}{
		{"unknown top field", strings.Replace(canonicalScenario,
			`"schema_version": "1.0",`, `"schema_version": "1.0", "policies": [],`, 1), "unknown field"},
		{"trailing data", canonicalScenario + " {}", "trailing data"},
		{"wrong schema version", strings.Replace(canonicalScenario,
			`"schema_version": "1.0"`, `"schema_version": "2.0"`, 1), "unsupported scenario document"},
		{"wrong scenario id", strings.Replace(canonicalScenario,
			`"scenario_id": "support-handoff"`, `"scenario_id": "support-triage"`, 1),
			"unsupported scenario document"},
		{"missing threshold", strings.Replace(canonicalScenario,
			`"confidence_threshold": 0.80,`, ``, 1), "confidence_threshold must be"},
		{"wrong threshold", strings.Replace(canonicalScenario,
			`"confidence_threshold": 0.80`, `"confidence_threshold": 0.85`, 1), "confidence_threshold must be"},
		{"missing receiver mapping", strings.Replace(canonicalScenario,
			`"route_receivers": {"billing": "billing-specialist", "technical": "technical-specialist", "general": "general-specialist"}`,
			`"route_receivers": {"billing": "billing-specialist"}`, 1), "must map every canonical route"},
		{"wrong receiver mapping", strings.Replace(canonicalScenario,
			`"billing": "billing-specialist"`, `"billing": "technical-specialist"`, 1),
			"route_receivers.billing must be billing-specialist"},
		{"empty latency table", strings.Replace(canonicalScenario,
			`"latency_ms": {"classify": 30, "receiver.billing-specialist": 10}`, `"latency_ms": {}`, 1),
			"latency table"},
		{"unknown price kind", strings.Replace(canonicalScenario,
			`"price_table": {"route": 0, "model_decision": 2, "handoff": 0}`,
			`"price_table": {"route": 0, "model_decision": 2, "handoff": 0, "teleport": 9}`, 1), "price kind"},
		{"nonzero read price", strings.Replace(canonicalScenario,
			`"price_table": {"route": 0, "model_decision": 2, "handoff": 0}`,
			`"price_table": {"route": 0, "model_decision": 2, "handoff": 0, "read": 3}`, 1),
			"reads must price zero"},
		{"bad ticket pattern", strings.Replace(canonicalScenario,
			`"ticket_id": "TCK-1001"`, `"ticket_id": "TK-1"`, 1), "ticket_id is invalid"},
		{"bad router mode", strings.Replace(canonicalScenario,
			`"router_mode": "code"`, `"router_mode": "auto"`, 1), "router_mode must be code or model"},
		{"bad expected status", strings.Replace(canonicalScenario,
			`"expected_status": "SUCCEEDED", "expected_proposed_route": "billing",
     "expected_confidence": 1.0`,
			`"expected_status": "PARTIAL", "expected_proposed_route": "billing",
     "expected_confidence": 1.0`, 1), "expected_status must be SUCCEEDED or FAILED"},
		{"bad expected route", strings.Replace(canonicalScenario,
			`"expected_proposed_route": "billing"`, `"expected_proposed_route": "sales"`, 1),
			"expected routes must be canonical"},
		{"confidence out of range", strings.Replace(canonicalScenario,
			`"expected_confidence": 1.0`, `"expected_confidence": 1.5`, 1),
			"expected_confidence must be between 0 and 1"},
		{"bad expected receiver", strings.Replace(canonicalScenario,
			`"expected_receiver": "billing-specialist", "expected_policy_outcome": "selected",
     "expected_fallback_applied": false, "expected_specialist_invoked": true},
    {"id": "handoff-context-loss"`,
			`"expected_receiver": "sales-specialist", "expected_policy_outcome": "selected",
     "expected_fallback_applied": false, "expected_specialist_invoked": true},
    {"id": "handoff-context-loss"`, 1), "expected_receiver is unsupported"},
		{"bad policy outcome", strings.Replace(canonicalScenario,
			`"expected_policy_outcome": "fallback"`, `"expected_policy_outcome": "escalated"`, 1),
			"expected_policy_outcome must be selected or fallback"},
		{"missing booleans", strings.Replace(canonicalScenario,
			`"expected_fallback_applied": false, "expected_specialist_invoked": true},
    {"id": "handoff-context-loss"`,
			`"expected_fallback_applied": false},
    {"id": "handoff-context-loss"`, 1),
			"expected_fallback_applied and expected_specialist_invoked"},
		{"success with failure code", strings.Replace(canonicalScenario,
			`"expected_fallback_applied": false, "expected_specialist_invoked": true},
    {"id": "handoff-context-loss"`,
			`"expected_fallback_applied": false, "expected_specialist_invoked": true,
     "expected_failure_code": "HANDOFF_CONTEXT_INVALID"},
    {"id": "handoff-context-loss"`, 1), "success cases cannot define failure fields"},
		{"success with failure ref", strings.Replace(canonicalScenario,
			`"expected_fallback_applied": false, "expected_specialist_invoked": true},
    {"id": "handoff-context-loss"`,
			`"expected_fallback_applied": false, "expected_specialist_invoked": true,
     "failure_ref": "handoff-context-loss"},
    {"id": "handoff-context-loss"`, 1), "success cases cannot define failure fields"},
		{"failed without failure code", strings.Replace(canonicalScenario,
			`"expected_failure_code": "HANDOFF_CONTEXT_INVALID", "failure_ref": "handoff-context-loss"`,
			`"failure_ref": "handoff-context-loss"`, 1), "expected_failure_code is unsupported"},
		{"failed without failure ref", strings.Replace(canonicalScenario,
			`"expected_failure_code": "HANDOFF_CONTEXT_INVALID", "failure_ref": "handoff-context-loss"`,
			`"expected_failure_code": "HANDOFF_CONTEXT_INVALID"`, 1), "failed cases must carry a failure_ref"},
		{"failure ref mismatch", strings.Replace(canonicalScenario,
			`"failure_ref": "handoff-context-loss"`, `"failure_ref": "handoff-receiver-unavailable"`, 1),
			"invalid M2 failure reference"},
		{"unknown failure code", strings.Replace(canonicalScenario,
			`"expected_failure_code": "HANDOFF_CONTEXT_INVALID"`, `"expected_failure_code": "SOMETHING_ELSE"`, 1),
			"expected_failure_code is unsupported"},
		{"missing request", strings.Replace(canonicalScenario,
			`"request": "I was charged twice."`, `"request": ""`, 1), "id, ticket_id, and request"},
		{"duplicate ids", strings.Replace(canonicalScenario,
			`"id": "model-technical-handoff"`, `"id": "code-billing-handoff"`, 1), "duplicate case id"},
	}
	for _, rejection := range rejections {
		t.Run(rejection.name, func(t *testing.T) {
			_, err := LoadScenario(writeProjection(t, rejection.content))
			if err == nil || !strings.Contains(err.Error(), rejection.frag) {
				t.Fatalf("expected error containing %q, got %v", rejection.frag, err)
			}
		})
	}
}

// TestLoadScenarioRequiresCanonicalSet pins the closed five-case set (the
// Py runtime's exact-canonical-cases rule).
func TestLoadScenarioRequiresCanonicalSet(t *testing.T) {
	renamed := strings.Replace(canonicalScenario, `"id": "code-billing-handoff"`,
		`"id": "code-something-else"`, 1)
	if _, err := LoadScenario(writeProjection(t, renamed)); err == nil ||
		!strings.Contains(err.Error(), "scenario is missing canonical case") {
		t.Fatalf("non-canonical set must be rejected: %v", err)
	}
	shortened := strings.Replace(canonicalScenario, `,
    {"id": "handoff-receiver-unavailable", "ticket_id": "TCK-9002",
     "request": "I need help with a charge.", "router_mode": "code",
     "expected_status": "FAILED", "expected_proposed_route": "billing",
     "expected_confidence": 1.0, "expected_selected_route": "billing",
     "expected_receiver": "billing-specialist", "expected_policy_outcome": "selected",
     "expected_fallback_applied": false, "expected_specialist_invoked": false,
     "expected_failure_code": "HANDOFF_RECEIVER_UNAVAILABLE", "failure_ref": "handoff-receiver-unavailable"}`, ``, 1)
	if _, err := LoadScenario(writeProjection(t, shortened)); err == nil ||
		!strings.Contains(err.Error(), "must contain exactly the 5 canonical M2 cases") {
		t.Fatalf("short sets must be rejected: %v", err)
	}
}

// canonicalFakeModel mirrors the checked-in fake-model decisions projection:
// each entry is the projected decision value (the generator strips the
// source fixture's `return` wrapper).
const canonicalFakeModel = `{
  "schema_version": "1.0",
  "scenario_id": "support-handoff",
  "decisions": {
    "model-technical-handoff": {"route": "technical", "confidence": 0.92}
  }
}`

func TestLoadFakeModelDecisionsCanonical(t *testing.T) {
	decisions, err := LoadFakeModelDecisions(writeProjection(t, canonicalFakeModel))
	if err != nil {
		t.Fatalf("LoadFakeModelDecisions: %v", err)
	}
	raw, ok := decisions["model-technical-handoff"]
	if !ok {
		t.Fatalf("decisions: %v", decisions)
	}
	var decision struct {
		Route      string  `json:"route"`
		Confidence float64 `json:"confidence"`
	}
	if err := json.Unmarshal(raw, &decision); err != nil {
		t.Fatalf("decision value: %v", err)
	}
	if decision.Route != "technical" || decision.Confidence != 0.92 {
		t.Fatalf("decision not carried verbatim: %+v", decision)
	}
}

func TestLoadFakeModelRejections(t *testing.T) {
	rejections := []struct {
		name    string
		content string
		frag    string
	}{
		{"unknown top field", strings.Replace(canonicalFakeModel,
			`"schema_version": "1.0",`, `"schema_version": "1.0", "routes": [],`, 1), "unknown field"},
		{"wrong header", strings.Replace(canonicalFakeModel,
			`"scenario_id": "support-handoff"`, `"scenario_id": "support-triage"`, 1),
			"unsupported fake-model document"},
		{"missing decisions", `{"schema_version": "1.0", "scenario_id": "support-handoff"}`,
			"must contain decisions"},
		{"null decisions", `{"schema_version": "1.0", "scenario_id": "support-handoff", "decisions": null}`,
			"must contain decisions"},
		{"trailing data", canonicalFakeModel + " null", "trailing data"},
	}
	for _, rejection := range rejections {
		t.Run(rejection.name, func(t *testing.T) {
			_, err := LoadFakeModelDecisions(writeProjection(t, rejection.content))
			if err == nil || !strings.Contains(err.Error(), rejection.frag) {
				t.Fatalf("expected error containing %q, got %v", rejection.frag, err)
			}
		})
	}
}

const canonicalFailures = `{
  "schema_version": "1.0",
  "scenario_id": "support-handoff",
  "failures": {
    "handoff-context-loss": {"omit_receiver_input_fields": ["request_text"]},
    "handoff-receiver-unavailable": {"unavailable_receivers": ["billing-specialist"]}
  }
}`

func TestLoadFailureFixturesCanonical(t *testing.T) {
	fixtures, err := LoadFailureFixtures(writeProjection(t, canonicalFailures))
	if err != nil {
		t.Fatalf("LoadFailureFixtures: %v", err)
	}
	if len(fixtures) != 2 {
		t.Fatalf("fixtures: %v", fixtures)
	}
	contextLoss := fixtures["handoff-context-loss"]
	if !contextLoss.IsOmitFields() || len(contextLoss.OmitReceiverInputFields) != 1 ||
		contextLoss.OmitReceiverInputFields[0] != "request_text" {
		t.Fatalf("context-loss fixture: %+v", contextLoss)
	}
	unavailable := fixtures["handoff-receiver-unavailable"]
	if !unavailable.MarksUnavailable("billing-specialist") ||
		unavailable.MarksUnavailable("technical-specialist") || unavailable.IsOmitFields() {
		t.Fatalf("unavailable fixture: %+v", unavailable)
	}
	var missing *FailureFixture
	if missing.IsOmitFields() || missing.MarksUnavailable("billing-specialist") {
		t.Fatal("nil fixture must report no operators")
	}
}

func TestLoadFailureFixturesRejections(t *testing.T) {
	rejections := []struct {
		name    string
		content string
		frag    string
	}{
		{"unknown top field", strings.Replace(canonicalFailures,
			`"schema_version": "1.0",`, `"schema_version": "1.0", "faults": [],`, 1), "unknown field"},
		{"wrong header", strings.Replace(canonicalFailures,
			`"scenario_id": "support-handoff"`, `"scenario_id": "order-brief"`, 1),
			"unsupported failures document"},
		{"missing failures", `{"schema_version": "1.0", "scenario_id": "support-handoff"}`,
			"must contain failures"},
		{"both operators", strings.Replace(canonicalFailures,
			`"omit_receiver_input_fields": ["request_text"]`,
			`"omit_receiver_input_fields": ["request_text"], "unavailable_receivers": ["billing-specialist"]`, 1),
			"exactly one operator"},
		{"no operator", strings.Replace(canonicalFailures,
			`"handoff-context-loss": {"omit_receiver_input_fields": ["request_text"]}`,
			`"handoff-context-loss": {}`, 1), "exactly one operator"},
		{"empty omit list", strings.Replace(canonicalFailures,
			`"omit_receiver_input_fields": ["request_text"]`, `"omit_receiver_input_fields": []`, 1),
			"must be non-empty"},
		{"unknown omit field", strings.Replace(canonicalFailures,
			`"omit_receiver_input_fields": ["request_text"]`, `"omit_receiver_input_fields": ["payload"]`, 1),
			"omit_receiver_input_fields is invalid"},
		{"unknown receiver", strings.Replace(canonicalFailures,
			`"unavailable_receivers": ["billing-specialist"]`, `"unavailable_receivers": ["sales-specialist"]`, 1),
			"unavailable_receivers is invalid"},
		{"empty unavailable list", strings.Replace(canonicalFailures,
			`"unavailable_receivers": ["billing-specialist"]`, `"unavailable_receivers": []`, 1),
			"must be non-empty"},
		{"trailing data", canonicalFailures + " 1", "trailing data"},
	}
	for _, rejection := range rejections {
		t.Run(rejection.name, func(t *testing.T) {
			_, err := LoadFailureFixtures(writeProjection(t, rejection.content))
			if err == nil || !strings.Contains(err.Error(), rejection.frag) {
				t.Fatalf("expected error containing %q, got %v", rejection.frag, err)
			}
		})
	}
}

// TestDefaultPaths pins the projection layout the runner consumes.
func TestDefaultPaths(t *testing.T) {
	root := t.TempDir()
	if got := DefaultScenarioPath(root); !strings.HasSuffix(got,
		filepath.Join("fixtures", "goprojections", "support-handoff", "scenario.json")) {
		t.Fatalf("scenario path: %s", got)
	}
	if got := DefaultFakeModelPath(root); !strings.HasSuffix(got, "fake-model.json") {
		t.Fatalf("fake-model path: %s", got)
	}
	if got := DefaultFailuresPath(root); !strings.HasSuffix(got, "failures.json") {
		t.Fatalf("failures path: %s", got)
	}
	// FindRepoRoot walks up to the repository carrying the scenario fixture.
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("FindRepoRoot: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "fixtures", "scenarios",
		"support-handoff.yaml")); err != nil {
		t.Fatalf("repo root fixture: %v", err)
	}
}
