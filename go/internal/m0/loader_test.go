package m0

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

func writeTempScenario(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "scenario.json")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write scenario: %v", err)
	}
	return path
}

func TestLoadScenarioFromProjection(t *testing.T) {
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("repo root: %v", err)
	}
	scenario, err := LoadScenario(DefaultScenarioPath(root))
	if err != nil {
		t.Fatalf("LoadScenario: %v", err)
	}
	if scenario.SchemaVersion != "1.0" || scenario.ScenarioID != "support-triage" {
		t.Fatalf("wrong scenario header: %s/%s", scenario.SchemaVersion, scenario.ScenarioID)
	}
	wantRoutes := []string{"billing", "technical", "general"}
	if len(scenario.Routes) != 3 {
		t.Fatalf("routes: %v", scenario.Routes)
	}
	for i, route := range wantRoutes {
		if scenario.Routes[i] != route {
			t.Fatalf("routes: %v", scenario.Routes)
		}
	}
	if len(scenario.Cases) != 4 {
		t.Fatalf("expected 4 cases, got %d", len(scenario.Cases))
	}
	if scenario.Cases[0].ID != "billing-duplicate-charge" || !scenario.Cases[0].Success() ||
		scenario.Cases[0].ExpectedRoute != "billing" || scenario.Cases[0].Request == "" {
		t.Fatalf("first case: %+v", scenario.Cases[0])
	}
	failure := scenario.Cases[3]
	if failure.ID != "invalid-model-route" || failure.Success() ||
		failure.ExpectedFailureCode != contracts.FailureInvalidRouteDecision {
		t.Fatalf("failure case: %+v", failure)
	}
	if scenario.Attribution.LatencyMS["classify"] != 30 ||
		scenario.Attribution.LatencyMS["specialist.billing"] != 10 ||
		scenario.Attribution.LatencyMS["specialist.technical"] != 11 ||
		scenario.Attribution.LatencyMS["specialist.general"] != 12 {
		t.Fatalf("latency table: %v", scenario.Attribution.LatencyMS)
	}
	if scenario.Attribution.PriceTable["route"] != 0 ||
		scenario.Attribution.PriceTable["model_decision"] != 2 ||
		scenario.Attribution.PriceTable["read"] != 0 {
		t.Fatalf("price table: %v", scenario.Attribution.PriceTable)
	}
}

func TestFindCase(t *testing.T) {
	scenario, err := LoadScenario(mustRepoScenario(t))
	if err != nil {
		t.Fatalf("LoadScenario: %v", err)
	}
	if _, err := scenario.FindCase("billing-duplicate-charge"); err != nil {
		t.Fatalf("FindCase: %v", err)
	}
	if _, err := scenario.FindCase("no-such-case"); !errors.Is(err, ErrUnknownCase) {
		t.Fatalf("unknown case must fail with ErrUnknownCase, got %v", err)
	}
}

func mustRepoScenario(t *testing.T) string {
	t.Helper()
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("repo root: %v", err)
	}
	return DefaultScenarioPath(root)
}

func TestLoadScenarioRejectsInvalidDocuments(t *testing.T) {
	mutate := func(t *testing.T, change func(doc map[string]any)) string {
		t.Helper()
		raw, err := os.ReadFile(mustRepoScenario(t))
		if err != nil {
			t.Fatalf("read scenario: %v", err)
		}
		var doc map[string]any
		if err := json.Unmarshal(raw, &doc); err != nil {
			t.Fatalf("parse scenario: %v", err)
		}
		change(doc)
		out, err := json.Marshal(doc)
		if err != nil {
			t.Fatalf("marshal scenario: %v", err)
		}
		return writeTempScenario(t, string(out))
	}
	dropThirdRoute := func(doc map[string]any) {
		doc["routes"] = []any{"billing", "technical", "generalx"}
	}
	bothExpectations := func(doc map[string]any) {
		cases := doc["cases"].([]any)
		cases[3].(map[string]any)["expected_route"] = "billing"
	}
	badFailureCode := func(doc map[string]any) {
		cases := doc["cases"].([]any)
		cases[3].(map[string]any)["expected_failure_code"] = "SOME_OTHER_CODE"
	}
	attribution := func(doc map[string]any) map[string]any {
		tables, _ := doc["attribution"].(map[string]any)
		return tables
	}
	cases := []struct {
		name   string
		change func(doc map[string]any)
		frag   string
	}{
		{"unknown top-level field", func(doc map[string]any) { doc["extra"] = 1 }, "unknown field"},
		{"wrong scenario id", func(doc map[string]any) { doc["scenario_id"] = "other-scenario" }, "scenario_id"},
		{"non-canonical routes", dropThirdRoute, "routes"},
		{"case with both expectations", bothExpectations, "exactly one"},
		{"case with unsupported failure code", badFailureCode, "exactly one"},
		{"missing attribution", func(doc map[string]any) { delete(doc, "attribution") }, "attribution"},
		{"negative latency", func(doc map[string]any) {
			attribution(doc)["latency_ms"].(map[string]any)["classify"] = -30
		}, "latency"},
		{"unknown price kind", func(doc map[string]any) {
			attribution(doc)["price_table"].(map[string]any)["routez"] = 0
		}, "price"},
		{"nonzero read price", func(doc map[string]any) {
			attribution(doc)["price_table"].(map[string]any)["read"] = 3
		}, "read"},
		{"empty latency table", func(doc map[string]any) {
			attribution(doc)["latency_ms"] = map[string]any{}
		}, "latency"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			path := mutate(t, tc.change)
			if _, err := LoadScenario(path); err == nil || !strings.Contains(err.Error(), tc.frag) {
				t.Fatalf("expected error containing %q, got %v", tc.frag, err)
			}
		})
	}
}
