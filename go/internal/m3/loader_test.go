package m3

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func repoPaths(t *testing.T) (scenarioPath, workersPath string) {
	t.Helper()
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("repo root: %v", err)
	}
	return DefaultScenarioPath(root), DefaultWorkersPath(root)
}

func loadRepoScenario(t *testing.T) *Scenario {
	t.Helper()
	scenarioPath, workersPath := repoPaths(t)
	scenario, err := LoadScenario(scenarioPath, workersPath)
	if err != nil {
		t.Fatalf("LoadScenario: %v", err)
	}
	return scenario
}

func TestLoadScenarioFromProjections(t *testing.T) {
	scenario := loadRepoScenario(t)
	if scenario.SchemaVersion != "1.0" || scenario.ScenarioID != "order-brief" ||
		scenario.OrderID != "ORD-1001" {
		t.Fatalf("header: %+v", scenario)
	}
	if len(scenario.Cases) != 6 {
		t.Fatalf("expected 6 cases, got %d", len(scenario.Cases))
	}
	first := scenario.Cases[0]
	if first.CaseID != "sequential-complete" || first.ExecutionMode != ModeSequential ||
		first.WorkerFixture != "fixtures/workers/order-brief/complete.yaml" ||
		len(first.CompletionOrder) != 3 {
		t.Fatalf("first case: %+v", first)
	}
	third := scenario.Cases[2]
	if third.CaseID != "parallel-out-of-order" || third.ExecutionMode != ModeParallel ||
		third.CompletionOrder[0] != "payment-status" {
		t.Fatalf("out-of-order case: %+v", third)
	}
	if scenario.Attribution.LatencyMS["worker.order-details"] != 10 ||
		scenario.Attribution.LatencyMS["synthesize"] != 15 ||
		scenario.Attribution.PriceTable["read"] != 0 ||
		scenario.Attribution.PriceTable["synthesis"] != 0 {
		t.Fatalf("attribution tables: %+v", scenario.Attribution)
	}
}

func TestLoadWorkerFixtures(t *testing.T) {
	_, workersPath := repoPaths(t)
	fixtures, err := LoadWorkerFixtures(workersPath)
	if err != nil {
		t.Fatalf("LoadWorkerFixtures: %v", err)
	}
	wantKeys := []string{
		"fixtures/workers/order-brief/complete.yaml",
		"fixtures/workers/order-brief/partial-failure.yaml",
		"fixtures/workers/order-brief/all-failed.yaml",
		"fixtures/workers/order-brief/invalid-output.yaml",
	}
	if len(fixtures) != len(wantKeys) {
		t.Fatalf("fixture keys: %d", len(fixtures))
	}
	complete := fixtures[wantKeys[0]]
	if len(complete) != 3 {
		t.Fatalf("complete fixture entries: %d", len(complete))
	}
	instruction := complete["order-details"]
	if instruction.Operation != "return" || instruction.Output == nil {
		t.Fatalf("order-details instruction: %+v", instruction)
	}
	var output map[string]any
	if err := json.Unmarshal(instruction.Output, &output); err != nil ||
		output["order_id"] != "ORD-1001" || output["order_status"] != "SHIPPED" {
		t.Fatalf("order-details output: %s %v", instruction.Output, err)
	}
	raise := fixtures[wantKeys[2]]["payment-status"]
	if raise.Operation != "raise" || raise.FailureCode != "WORKER_EXECUTION_FAILED" || raise.Output != nil {
		t.Fatalf("all-failed payment-status: %+v", raise)
	}
}

func writeTempScenario(t *testing.T, scenarioJSON, workersJSON string) (string, string) {
	t.Helper()
	dir := t.TempDir()
	scenarioPath := filepath.Join(dir, "scenario.json")
	workersPath := filepath.Join(dir, "workers.json")
	if err := os.WriteFile(scenarioPath, []byte(scenarioJSON), 0o644); err != nil {
		t.Fatalf("write scenario: %v", err)
	}
	if err := os.WriteFile(workersPath, []byte(workersJSON), 0o644); err != nil {
		t.Fatalf("write workers: %v", err)
	}
	return scenarioPath, workersPath
}

func mutateRepoScenario(t *testing.T, change func(doc map[string]any)) (string, string) {
	t.Helper()
	scenarioPath, _ := repoPaths(t)
	raw, err := os.ReadFile(scenarioPath)
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
	return writeTempScenario(t, string(out), mustWorkersJSON(t))
}

func mustWorkersJSON(t *testing.T) string {
	t.Helper()
	_, workersPath := repoPaths(t)
	raw, err := os.ReadFile(workersPath)
	if err != nil {
		t.Fatalf("read workers: %v", err)
	}
	return string(raw)
}

func TestLoadScenarioRejectsInvalidDocuments(t *testing.T) {
	permutation := func(doc map[string]any, order []string) {
		cases := doc["cases"].([]any)
		cases[0].(map[string]any)["completion_order"] = order
	}
	cases := []struct {
		name   string
		change func(doc map[string]any)
		frag   string
	}{
		{"unknown top-level field", func(doc map[string]any) { doc["extra"] = 1 }, "unknown field"},
		{"wrong scenario id", func(doc map[string]any) { doc["scenario_id"] = "other" }, "scenario_id"},
		{"bad order id", func(doc map[string]any) { doc["order_id"] = "ORD-1" }, "order_id"},
		{"wrong case count", func(doc map[string]any) {
			doc["cases"] = doc["cases"].([]any)[:5]
		}, "six cases"},
		{"duplicate case id", func(doc map[string]any) {
			cases := doc["cases"].([]any)
			cases[1].(map[string]any)["case_id"] = "sequential-complete"
		}, "duplicate"},
		{"bad execution mode", func(doc map[string]any) {
			cases := doc["cases"].([]any)
			cases[0].(map[string]any)["execution_mode"] = "concurrent"
		}, "execution_mode"},
		{"non-permutation completion order", func(doc map[string]any) {
			permutation(doc, []string{"order-details", "order-details", "delivery-status"})
		}, "permutation"},
		{"infeasible completion schedule", func(doc map[string]any) {
			permutation(doc, []string{"payment-status", "order-details", "delivery-status"})
		}, "infeasible"},
		{"fixture escapes root", func(doc map[string]any) {
			cases := doc["cases"].([]any)
			cases[0].(map[string]any)["worker_fixture"] = "fixtures/scenarios/order-brief.yaml"
		}, "worker fixture"},
		{"unknown fixture", func(doc map[string]any) {
			cases := doc["cases"].([]any)
			cases[0].(map[string]any)["worker_fixture"] = "fixtures/workers/order-brief/missing.yaml"
		}, "worker fixture"},
		{"unknown price kind", func(doc map[string]any) {
			tables := doc["attribution"].(map[string]any)
			tables["price_table"].(map[string]any)["routez"] = 0
		}, "price"},
		{"negative latency", func(doc map[string]any) {
			tables := doc["attribution"].(map[string]any)
			tables["latency_ms"].(map[string]any)["synthesize"] = -15
		}, "latency"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			scenarioPath, workersPath := mutateRepoScenario(t, tc.change)
			if _, err := LoadScenario(scenarioPath, workersPath); err == nil ||
				!strings.Contains(err.Error(), tc.frag) {
				t.Fatalf("expected error containing %q, got %v", tc.frag, err)
			}
		})
	}
}

func TestLoadWorkerFixturesRejectsInvalid(t *testing.T) {
	valid := mustWorkersJSON(t)
	cases := []struct {
		name    string
		workers string
		frag    string
	}{
		{"missing worker", strings.Replace(valid, `"delivery-status"`, `"delivery-status-x"`, 1), "worker"},
		{"unknown operation", strings.Replace(valid, `"operation": "return"`, `"operation": "crash"`, 1), "operation"},
		{"wrong failure code", strings.Replace(valid, `"failure_code": "WORKER_EXECUTION_FAILED"`, `"failure_code": "OTHER"`, 1), "invalid operation"},
		{"raise with output", strings.Replace(valid, `"operation": "raise"`, `"operation": "raise", "output": {"x": 1}`, 1), "operation"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			workersPath := filepath.Join(dir, "workers.json")
			if err := os.WriteFile(workersPath, []byte(tc.workers), 0o644); err != nil {
				t.Fatalf("write workers: %v", err)
			}
			if _, err := LoadWorkerFixtures(workersPath); err == nil || !strings.Contains(err.Error(), tc.frag) {
				t.Fatalf("expected error containing %q, got %v", tc.frag, err)
			}
		})
	}
}

func TestScenarioFindCase(t *testing.T) {
	scenario := loadRepoScenario(t)
	if _, err := scenario.FindCase("parallel-complete"); err != nil {
		t.Fatalf("FindCase: %v", err)
	}
	if _, err := scenario.FindCase("nope"); !errors.Is(err, ErrUnknownCase) {
		t.Fatalf("unknown case must fail with ErrUnknownCase, got %v", err)
	}
}
