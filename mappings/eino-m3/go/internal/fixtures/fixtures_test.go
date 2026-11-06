package fixtures

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func repoScenario(t *testing.T) *Scenario {
	t.Helper()
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("find repo root: %v", err)
	}
	scenario, err := LoadScenario(DefaultScenarioPath(root), DefaultWorkersPath(root))
	if err != nil {
		t.Fatalf("load scenario: %v", err)
	}
	return scenario
}

func TestLoadScenarioValidatesTheCanonicalDocument(t *testing.T) {
	scenario := repoScenario(t)
	if scenario.SchemaVersion != "1.0" || scenario.ScenarioID != "order-brief" || scenario.OrderID != "ORD-1001" {
		t.Fatalf("unexpected header: %+v", scenario)
	}
	wantKeys := []string{
		"sequential-complete", "parallel-complete", "parallel-out-of-order",
		"parallel-partial-failure", "parallel-all-failed", "parallel-invalid-output",
	}
	if len(scenario.Cases) != 6 {
		t.Fatalf("expected six cases, got %d", len(scenario.Cases))
	}
	for i, want := range wantKeys {
		if scenario.Cases[i].CaseID != want {
			t.Fatalf("case %d = %s, want %s", i, scenario.Cases[i].CaseID, want)
		}
	}
	if scenario.Attribution.LatencyMS["worker.order-details"] != 10 ||
		scenario.Attribution.LatencyMS["worker.payment-status"] != 11 ||
		scenario.Attribution.LatencyMS["worker.delivery-status"] != 12 ||
		scenario.Attribution.LatencyMS["synthesize"] != 15 {
		t.Fatalf("unexpected latency table: %+v", scenario.Attribution.LatencyMS)
	}
	if scenario.Attribution.PriceTable["read"] != 0 || scenario.Attribution.PriceTable["synthesis"] != 0 {
		t.Fatalf("read/synthesis must price zero: %+v", scenario.Attribution.PriceTable)
	}
	parallel := 0
	sequential := 0
	for _, scenarioCase := range scenario.Cases {
		if scenarioCase.ExecutionMode == ModeParallel {
			parallel++
			if scenarioCase.Limit() != 2 {
				t.Fatalf("parallel case %s must cap at 2", scenarioCase.CaseID)
			}
		} else {
			sequential++
			if scenarioCase.Limit() != 1 {
				t.Fatalf("sequential case %s must cap at 1", scenarioCase.CaseID)
			}
		}
		if len(scenarioCase.CompletionOrder) != 3 {
			t.Fatalf("case %s completion order must be a permutation", scenarioCase.CaseID)
		}
	}
	if parallel != 5 || sequential != 1 {
		t.Fatalf("expected 5 parallel + 1 sequential, got %d/%d", parallel, sequential)
	}
}

func TestFindCaseUnknownIsToolingError(t *testing.T) {
	scenario := repoScenario(t)
	_, err := scenario.FindCase("no-such-case")
	if err == nil || !errors.Is(err, ErrUnknownCase) {
		t.Fatalf("unknown case must surface ErrUnknownCase, got %v", err)
	}
	found, err := scenario.FindCase("parallel-out-of-order")
	if err != nil {
		t.Fatalf("find: %v", err)
	}
	if found.CompletionOrder[0] != "payment-status" {
		t.Fatalf("out-of-order completion order drifted: %v", found.CompletionOrder)
	}
}

func TestLoadScenarioRejectsInfeasibleSchedule(t *testing.T) {
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("find repo root: %v", err)
	}
	// delivery-status cannot complete first under the parallel cap: only
	// order-details and payment-status are active in the first wave.
	dir := t.TempDir()
	scenarioPath := filepath.Join(dir, "scenario.json")
	if err := os.WriteFile(scenarioPath, []byte(`{
		"schema_version": "1.0",
		"scenario_id": "order-brief",
		"order_id": "ORD-1001",
		"attribution": {"latency_ms": {"worker.order-details": 10, "worker.payment-status": 11, "worker.delivery-status": 12, "synthesize": 15}, "price_table": {"read": 0, "synthesis": 0}},
		"cases": [{
			"case_id": "infeasible",
			"execution_mode": "parallel",
			"worker_fixture": "fixtures/workers/order-brief/complete.yaml",
			"completion_order": ["delivery-status", "order-details", "payment-status"]
		}]
	}`), 0o644); err != nil {
		t.Fatalf("write scenario: %v", err)
	}
	if _, err := LoadScenario(scenarioPath, DefaultWorkersPath(root)); err == nil {
		t.Fatal("infeasible completion schedule accepted")
	}
}

func TestLoadWorkerFixturesRejectsBadInstructions(t *testing.T) {
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("find repo root: %v", err)
	}
	fixtures, err := LoadWorkerFixtures(DefaultWorkersPath(root))
	if err != nil {
		t.Fatalf("load workers: %v", err)
	}
	if len(fixtures) != 4 {
		t.Fatalf("expected four fixtures, got %d", len(fixtures))
	}
	complete := fixtures["fixtures/workers/order-brief/complete.yaml"]
	if complete["order-details"].Operation != "return" || complete["delivery-status"].Output == nil {
		t.Fatalf("complete fixture drifted: %+v", complete)
	}
	invalid := fixtures["fixtures/workers/order-brief/invalid-output.yaml"]
	var output struct {
		PaymentStatus string `json:"payment_status"`
	}
	if err := json.Unmarshal(invalid["payment-status"].Output, &output); err != nil || output.PaymentStatus != "UNKNOWN" {
		t.Fatalf("invalid-output fixture drifted: %s", invalid["payment-status"].Output)
	}
	partial := fixtures["fixtures/workers/order-brief/partial-failure.yaml"]
	if partial["delivery-status"].Operation != "raise" || partial["delivery-status"].FailureCode != "WORKER_EXECUTION_FAILED" {
		t.Fatalf("partial-failure fixture drifted: %+v", partial["delivery-status"])
	}

	dir := t.TempDir()
	badPath := filepath.Join(dir, "workers.json")
	if err := os.WriteFile(badPath, []byte(`{
		"fixtures/workers/order-brief/bad.yaml": {
			"order-details": {"operation": "return", "output": {"order_id": "ORD-1001", "order_status": "SHIPPED"}, "failure_code": "WORKER_EXECUTION_FAILED"}
		}
	}`), 0o644); err != nil {
		t.Fatalf("write workers: %v", err)
	}
	if _, err := LoadWorkerFixtures(badPath); err == nil {
		t.Fatal("return+failure_code instruction accepted")
	}
}

func TestLoadGoldenReadsTheParityTarget(t *testing.T) {
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("find repo root: %v", err)
	}
	golden, err := LoadGolden(GoldenPath(root, "parallel-complete"))
	if err != nil {
		t.Fatalf("load golden: %v", err)
	}
	if golden.CaseKey != "parallel-complete" || golden.ResultProjection == nil {
		t.Fatalf("golden drifted: %+v", golden)
	}
	var projection map[string]any
	if err := json.Unmarshal(golden.ResultProjection, &projection); err != nil {
		t.Fatalf("decode result_projection: %v", err)
	}
	if projection["status"] != "SUCCEEDED" || projection["peak_concurrency"] != float64(2) {
		t.Fatalf("unexpected projection header: %v/%v", projection["status"], projection["peak_concurrency"])
	}
}
