package m1

import (
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

// canonicalScenario is a minimal valid scenario projection.
const canonicalScenario = `{
  "schema_version": "1.0",
  "scenario_id": "order-investigation",
  "attribution": {"latency_ms": {"model": 30, "tool.lookup_order": 8},
                  "price_table": {"model_decision": 2, "tool_call": 1}},
  "cases": [
    {"id": "direct-order-status", "mode": "direct", "request": "Show order ORD-1001 status.",
     "max_steps": 0, "max_tokens": 0,
     "direct_call": {"call_id": "direct-call-1", "tool": "lookup_order",
                     "arguments": {"order_id": "ORD-1001"}},
     "expected_status": "SUCCEEDED", "expected_answer": "Order ORD-1001 status is SHIPPED.",
     "expected_model_steps": 0, "expected_tokens_used": 0, "expected_tool_invocations": 1},
    {"id": "agent-failure", "mode": "agent", "request": "Investigate.",
     "max_steps": 2, "max_tokens": 100,
     "expected_status": "FAILED", "expected_failure_code": "UNKNOWN_TOOL",
     "expected_model_steps": 1, "expected_tokens_used": 25, "expected_tool_invocations": 0}
  ]
}`

func TestLoadScenarioCanonical(t *testing.T) {
	scenario, err := LoadScenario(writeProjection(t, canonicalScenario))
	if err != nil {
		t.Fatalf("LoadScenario: %v", err)
	}
	if scenario.ScenarioID != "order-investigation" || len(scenario.Cases) != 2 {
		t.Fatalf("scenario: %+v", scenario)
	}
	direct, err := scenario.FindCase("direct-order-status")
	if err != nil {
		t.Fatalf("FindCase: %v", err)
	}
	if direct.DirectCall == nil || direct.DirectCall.Tool != "lookup_order" ||
		direct.DirectCall.Arguments["order_id"] != "ORD-1001" {
		t.Fatalf("direct call: %+v", direct.DirectCall)
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
			`"schema_version": "1.0",`, `"schema_version": "1.0", "routes": [],`, 1), "unknown field"},
		{"trailing data", canonicalScenario + " {}", "trailing data"},
		{"wrong schema version", strings.Replace(canonicalScenario,
			`"schema_version": "1.0"`, `"schema_version": "2.0"`, 1), "unsupported scenario document"},
		{"wrong scenario id", strings.Replace(canonicalScenario,
			`"scenario_id": "order-investigation"`, `"scenario_id": "support-triage"`, 1),
			"unsupported scenario document"},
		{"empty latency table", strings.Replace(canonicalScenario,
			`"latency_ms": {"model": 30, "tool.lookup_order": 8}`, `"latency_ms": {}`, 1),
			"latency table"},
		{"unknown price kind", strings.Replace(canonicalScenario,
			`"price_table": {"model_decision": 2, "tool_call": 1}`,
			`"price_table": {"model_decision": 2, "tool_call": 1, "teleport": 9}`, 1), "price kind"},
		{"nonzero read price", strings.Replace(canonicalScenario,
			`"price_table": {"model_decision": 2, "tool_call": 1}`,
			`"price_table": {"model_decision": 2, "tool_call": 1, "read": 3}`, 1), "reads must price zero"},
		{"both expectations", strings.Replace(canonicalScenario,
			`"expected_status": "SUCCEEDED", "expected_answer": "Order ORD-1001 status is SHIPPED.",`,
			`"expected_status": "SUCCEEDED", "expected_answer": "Order ORD-1001 status is SHIPPED.",
	     "expected_failure_code": "UNKNOWN_TOOL",`, 1), "cannot define expected_failure_code"},
		{"success without answer", strings.Replace(canonicalScenario,
			`"expected_answer": "Order ORD-1001 status is SHIPPED.",`, `"expected_answer": "",`, 1),
			"expected_answer"},
		{"direct case without call", strings.Replace(canonicalScenario,
			`"direct_call": {"call_id": "direct-call-1", "tool": "lookup_order",
                     "arguments": {"order_id": "ORD-1001"}},`, ``, 1), "direct_call"},
		{"agent case with call", strings.Replace(canonicalScenario,
			`"expected_status": "FAILED", "expected_failure_code": "UNKNOWN_TOOL"`,
			`"expected_status": "SUCCEEDED", "expected_answer": "done", "direct_call": {"call_id": "c", "tool": "lookup_order", "arguments": {}}`, 1),
			"agent mode cannot define direct_call"},
		{"failed case in direct mode", strings.Replace(canonicalScenario,
			`"id": "agent-failure", "mode": "agent"`, `"id": "agent-failure", "mode": "direct"`, 1),
			"must use agent mode"},
		{"unknown failure code", strings.Replace(canonicalScenario,
			`"expected_failure_code": "UNKNOWN_TOOL"`, `"expected_failure_code": "SOMETHING_ELSE"`, 1),
			"expected_failure_code is unsupported"},
		{"failed case with answer", strings.Replace(canonicalScenario,
			`"expected_status": "FAILED", "expected_failure_code": "UNKNOWN_TOOL"`,
			`"expected_status": "FAILED", "expected_failure_code": "UNKNOWN_TOOL", "expected_answer": "x"`, 1),
			"success-only fields"},
		{"negative budget", strings.Replace(canonicalScenario,
			`"max_steps": 2, "max_tokens": 100`, `"max_steps": -1, "max_tokens": 100`, 1), "non-negative integer"},
		{"missing budget", strings.Replace(canonicalScenario,
			`"max_steps": 2, "max_tokens": 100`, `"max_steps": 2`, 1), "max_tokens must be a non-negative integer"},
		{"unknown direct tool", strings.Replace(canonicalScenario,
			`"tool": "lookup_order"`, `"tool": "lookup_customer"`, 1), "must name an M1 tool"},
		{"direct call without arguments", strings.Replace(canonicalScenario,
			`"tool": "lookup_order",
                     "arguments": {"order_id": "ORD-1001"}},`, `"tool": "lookup_order"},`, 1),
			"arguments must be an object"},
		{"missing request", strings.Replace(canonicalScenario,
			`"request": "Show order ORD-1001 status."`, `"request": ""`, 1), "id and request"},
		{"duplicate ids", strings.Replace(canonicalScenario,
			`"id": "agent-failure"`, `"id": "direct-order-status"`, 1), "duplicate case id"},
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

// canonicalFakeModel mirrors the checked-in fake-model turns projection:
// trajectory entries are the projected turn values (the generator strips
// the source fixture's `return` wrapper).
const canonicalFakeModel = `{
  "schema_version": "1.0",
  "scenario_id": "order-investigation",
  "trajectories": {
    "agent-delayed-shipment": [
      {"schema_version": "1.0",
       "decision": {"kind": "tool_call", "call_id": "call-1",
                    "tool": "lookup_order", "arguments": {"order_id": "ORD-1001"}},
       "usage": {"input_tokens": 50, "output_tokens": 10}}
    ]
  }
}`

func TestLoadFakeModelTurnsCanonical(t *testing.T) {
	turns, err := LoadFakeModelTurns(writeProjection(t, canonicalFakeModel))
	if err != nil {
		t.Fatalf("LoadFakeModelTurns: %v", err)
	}
	trajectory, ok := turns["agent-delayed-shipment"]
	if !ok || len(trajectory) != 1 {
		t.Fatalf("trajectory: %v", turns)
	}
	if !strings.Contains(string(trajectory[0]), `"call_id":"call-1"`) &&
		!strings.Contains(string(trajectory[0]), `"call_id": "call-1"`) {
		t.Fatalf("turn not carried verbatim: %s", trajectory[0])
	}
}

func TestLoadFakeModelRejections(t *testing.T) {
	header := `{"schema_version": "1.0", "scenario_id": "order-investigation", "trajectories": `
	rejections := []struct {
		name    string
		content string
		frag    string
	}{
		{"unknown top field", strings.Replace(canonicalFakeModel,
			`"schema_version": "1.0",`, `"schema_version": "1.0", "turns": [],`, 1), "unknown field"},
		{"wrong header", strings.Replace(canonicalFakeModel,
			`"scenario_id": "order-investigation"`, `"scenario_id": "support-triage"`, 1), "unsupported fake-model document"},
		{"missing trajectories", `{"schema_version": "1.0", "scenario_id": "order-investigation"}`,
			"must contain trajectories"},
		{"null trajectories", `{"schema_version": "1.0", "scenario_id": "order-investigation", "trajectories": null}`,
			"must contain trajectories"},
		{"empty trajectory", header + `{"case-x": []}}`, "non-empty array"},
		{"trailing data", canonicalFakeModel + " null", "trailing data"},
	}
	for _, rejection := range rejections {
		t.Run(rejection.name, func(t *testing.T) {
			_, err := LoadFakeModelTurns(writeProjection(t, rejection.content))
			if err == nil || !strings.Contains(err.Error(), rejection.frag) {
				t.Fatalf("expected error containing %q, got %v", rejection.frag, err)
			}
		})
	}
}

const canonicalFakeTools = `{
  "schema_version": "1.0",
  "scenario_id": "order-investigation",
  "orders": {"ORD-1001": {"output": {"order_id": "ORD-1001", "status": "SHIPPED", "shipment_id": "SHP-1001"}},
             "ORD-9001": {"behavior": "timeout"},
             "ORD-9002": {"behavior": "failure"}},
  "shipments": {"SHP-1001": {"output": {"shipment_id": "SHP-1001", "status": "DELAYED", "reason": "WEATHER"}}}
}`

func TestLoadFakeToolsCanonical(t *testing.T) {
	data, err := LoadFakeTools(writeProjection(t, canonicalFakeTools))
	if err != nil {
		t.Fatalf("LoadFakeTools: %v", err)
	}
	if len(data.Orders) != 3 || len(data.Shipments) != 1 {
		t.Fatalf("fake tools: %+v", data)
	}
}

func TestLoadFakeToolsRejections(t *testing.T) {
	rejections := []struct {
		name    string
		content string
		frag    string
	}{
		{"unknown top field", strings.Replace(canonicalFakeTools,
			`"schema_version": "1.0",`, `"schema_version": "1.0", "customers": {},`, 1), "unknown field"},
		{"wrong header", strings.Replace(canonicalFakeTools,
			`"scenario_id": "order-investigation"`, `"scenario_id": "order-brief"`, 1), "unsupported fake-tools document"},
		{"missing shipments", `{"schema_version": "1.0", "scenario_id": "order-investigation", "orders": {}}`,
			"must define orders and shipments"},
		{"non-object order entry", strings.Replace(canonicalFakeTools,
			`"ORD-1001": {"output": {"order_id": "ORD-1001", "status": "SHIPPED", "shipment_id": "SHP-1001"}}`,
			`"ORD-1001": [1, 2]`, 1), "invalid fake-tools projection"},
		{"trailing data", canonicalFakeTools + " 1", "trailing data"},
	}
	for _, rejection := range rejections {
		t.Run(rejection.name, func(t *testing.T) {
			_, err := LoadFakeTools(writeProjection(t, rejection.content))
			if err == nil || !strings.Contains(err.Error(), rejection.frag) {
				t.Fatalf("expected error containing %q, got %v", rejection.frag, err)
			}
		})
	}
}
