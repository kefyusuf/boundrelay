package results

import (
	"encoding/json"
	"strings"
	"testing"
)

func mustJSON(t *testing.T, value any) json.RawMessage {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return raw
}

func successOutcome(t *testing.T, workerID string, output map[string]any) WorkerOutcome {
	t.Helper()
	return WorkerOutcome{WorkerID: workerID, Status: "SUCCEEDED", Output: mustJSON(t, output)}
}

func failedOutcome(workerID, code string) WorkerOutcome {
	return WorkerOutcome{WorkerID: workerID, Status: "FAILED", FailureCode: strPtr(code)}
}

func completeOutcomes(t *testing.T) []WorkerOutcome {
	t.Helper()
	return []WorkerOutcome{
		successOutcome(t, WorkerOrderDetails, map[string]any{"order_id": "ORD-1001", "order_status": "SHIPPED"}),
		successOutcome(t, WorkerPaymentStatus, map[string]any{"order_id": "ORD-1001", "payment_status": "PAID"}),
		successOutcome(t, WorkerDeliveryStatus, map[string]any{"order_id": "ORD-1001", "delivery_status": "DELAYED"}),
	}
}

func TestValidateWorkerOutputAcceptsClosedShapes(t *testing.T) {
	if !ValidateWorkerOutput(WorkerOrderDetails, mustJSON(t, map[string]any{"order_id": "ORD-1001", "order_status": "SHIPPED"}), "ORD-1001") {
		t.Fatal("valid order-details output rejected")
	}
	if !ValidateWorkerOutput(WorkerPaymentStatus, mustJSON(t, map[string]any{"order_id": "ORD-1001", "payment_status": "PAID"}), "ORD-1001") {
		t.Fatal("valid payment-status output rejected")
	}
	if !ValidateWorkerOutput(WorkerDeliveryStatus, mustJSON(t, map[string]any{"order_id": "ORD-1001", "delivery_status": "IN_TRANSIT"}), "ORD-1001") {
		t.Fatal("valid delivery-status output rejected")
	}
}

func TestValidateWorkerOutputRejectsOffTaxonomyReturns(t *testing.T) {
	cases := []struct {
		name    string
		worker  string
		raw     json.RawMessage
		orderID string
	}{
		{"unknown enum", WorkerPaymentStatus, mustJSON(t, map[string]any{"order_id": "ORD-1001", "payment_status": "UNKNOWN"}), "ORD-1001"},
		{"foreign order id", WorkerOrderDetails, mustJSON(t, map[string]any{"order_id": "ORD-2002", "order_status": "SHIPPED"}), "ORD-1001"},
		{"missing field", WorkerOrderDetails, mustJSON(t, map[string]any{"order_id": "ORD-1001"}), "ORD-1001"},
		{"unknown field", WorkerOrderDetails, mustJSON(t, map[string]any{"order_id": "ORD-1001", "order_status": "SHIPPED", "extra": 1}), "ORD-1001"},
		{"wrong shape", WorkerPaymentStatus, mustJSON(t, map[string]any{"order_id": "ORD-1001", "order_status": "SHIPPED"}), "ORD-1001"},
		{"array body", WorkerOrderDetails, json.RawMessage(`[1,2]`), "ORD-1001"},
		{"empty body", WorkerOrderDetails, nil, "ORD-1001"},
		{"unknown worker", "mystery", mustJSON(t, map[string]any{"order_id": "ORD-1001"}), "ORD-1001"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if ValidateWorkerOutput(testCase.worker, testCase.raw, testCase.orderID) {
				t.Fatalf("invalid output accepted: %s", testCase.raw)
			}
		})
	}
}

func TestCanonicalizeOutcomesReordersCanonically(t *testing.T) {
	outcomes := completeOutcomes(t)
	reversed := []WorkerOutcome{outcomes[2], outcomes[1], outcomes[0]}
	canonical, err := CanonicalizeOutcomes(reversed, "ORD-1001")
	if err != nil {
		t.Fatalf("canonicalize: %v", err)
	}
	for i, id := range CanonicalWorkerIDs {
		if canonical[i].WorkerID != id {
			t.Fatalf("position %d = %s, want %s", i, canonical[i].WorkerID, id)
		}
	}
}

func TestCanonicalizeOutcomesRejectsBadFanIn(t *testing.T) {
	if _, err := CanonicalizeOutcomes(completeOutcomes(t)[:2], "ORD-1001"); err == nil {
		t.Fatal("two-outcome fan-in accepted")
	}
	duplicated := []WorkerOutcome{completeOutcomes(t)[0], completeOutcomes(t)[0], completeOutcomes(t)[2]}
	if _, err := CanonicalizeOutcomes(duplicated, "ORD-1001"); err == nil || !strings.Contains(err.Error(), "duplicate") {
		t.Fatalf("duplicate identity accepted: %v", err)
	}
	invalid := []WorkerOutcome{
		completeOutcomes(t)[0],
		successOutcome(t, WorkerPaymentStatus, map[string]any{"order_id": "ORD-1001", "payment_status": "MYSTERY"}),
		completeOutcomes(t)[2],
	}
	if _, err := CanonicalizeOutcomes(invalid, "ORD-1001"); err == nil {
		t.Fatal("invalid outcome accepted by the fan-in gate")
	}
}

func TestSynthesizeBriefSectionsAndMissing(t *testing.T) {
	outcomes := completeOutcomes(t)
	outcomes[2] = failedOutcome(WorkerDeliveryStatus, FailureWorkerExecutionFailed)
	brief, err := SynthesizeBrief("ORD-1001", outcomes)
	if err != nil {
		t.Fatalf("synthesize: %v", err)
	}
	if brief.Complete || len(brief.Sections) != 2 || len(brief.MissingWorkers) != 1 || brief.MissingWorkers[0] != WorkerDeliveryStatus {
		t.Fatalf("unexpected brief: %+v", brief)
	}
	if brief.Sections[0].WorkerID != WorkerOrderDetails || brief.Sections[1].WorkerID != WorkerPaymentStatus {
		t.Fatalf("sections out of canonical order: %+v", brief.Sections)
	}
	if _, err := SynthesizeBrief("ORD-1001", []WorkerOutcome{
		failedOutcome(WorkerOrderDetails, FailureWorkerExecutionFailed),
		failedOutcome(WorkerPaymentStatus, FailureWorkerExecutionFailed),
		failedOutcome(WorkerDeliveryStatus, FailureWorkerExecutionFailed),
	}); err == nil {
		t.Fatal("synthesis without successful evidence accepted")
	}
}

func goodAttribution() Attribution {
	steps := []StepAttribution{
		{StepName: "worker.order-details", LatencyMS: 10, Attempts: 1},
		{StepName: "worker.payment-status", LatencyMS: 11, Attempts: 1},
		{StepName: "worker.delivery-status", LatencyMS: 12, Attempts: 1},
		{StepName: "synthesize", LatencyMS: 15, Attempts: 1},
	}
	totals := Totals{}
	for _, step := range steps {
		totals.LatencyMS += step.LatencyMS
		totals.CostCents += step.CostCents
		totals.Attempts += step.Attempts
	}
	return Attribution{Steps: steps, Totals: totals}
}

func TestAssembleResultMatchesGoldenShape(t *testing.T) {
	brief, err := SynthesizeBrief("ORD-1001", completeOutcomes(t))
	if err != nil {
		t.Fatalf("brief: %v", err)
	}
	result, err := AssembleResult(struct {
		RunID            string
		TracePath        string
		CaseID           string
		ExecutionMode    string
		OrderID          string
		PeakConcurrency  int
		Outcomes         []WorkerOutcome
		Brief            *Brief
		SynthesisInvoked bool
		Attribution      Attribution
	}{
		RunID: "run-1", TracePath: "trace.jsonl", CaseID: "parallel-complete",
		ExecutionMode: ModeParallel, OrderID: "ORD-1001", PeakConcurrency: 2,
		Outcomes: completeOutcomes(t), Brief: &brief, SynthesisInvoked: true, Attribution: goodAttribution(),
	})
	if err != nil {
		t.Fatalf("assemble: %v", err)
	}
	if result.Brief == nil || !result.Brief.Complete || len(result.Brief.Sections) != 3 {
		t.Fatalf("unexpected brief in result: %+v", result.Brief)
	}
	if result.Status != "SUCCEEDED" || result.ConcurrencyLimit != 2 || result.PeakConcurrency != 2 {
		t.Fatalf("unexpected result header: %+v", result)
	}
	if err := ValidateResult(result); err != nil {
		t.Fatalf("validated result rejected: %v", err)
	}
}

func TestValidateResultRejectsSchemaViolations(t *testing.T) {
	base := func(t *testing.T) RunResult {
		t.Helper()
		brief, err := SynthesizeBrief("ORD-1001", completeOutcomes(t))
		if err != nil {
			t.Fatalf("brief: %v", err)
		}
		result, err := AssembleResult(struct {
			RunID            string
			TracePath        string
			CaseID           string
			ExecutionMode    string
			OrderID          string
			PeakConcurrency  int
			Outcomes         []WorkerOutcome
			Brief            *Brief
			SynthesisInvoked bool
			Attribution      Attribution
		}{
			RunID: "run-1", TracePath: "trace.jsonl", CaseID: "parallel-complete",
			ExecutionMode: ModeParallel, OrderID: "ORD-1001", PeakConcurrency: 2,
			Outcomes: completeOutcomes(t), Brief: &brief, SynthesisInvoked: true, Attribution: goodAttribution(),
		})
		if err != nil {
			t.Fatalf("assemble: %v", err)
		}
		return result
	}
	t.Run("peak outside the bound", func(t *testing.T) {
		result := base(t)
		result.PeakConcurrency = 3
		if err := ValidateResult(result); err == nil {
			t.Fatal("peak 3 accepted")
		}
	})
	t.Run("broken totals", func(t *testing.T) {
		result := base(t)
		result.Attribution.Totals.Attempts = 99
		if err := ValidateResult(result); err == nil {
			t.Fatal("broken totals accepted")
		}
	})
	t.Run("out of canonical order", func(t *testing.T) {
		result := base(t)
		outcomes := result.WorkerOutcomes
		result.WorkerOutcomes = []WorkerOutcome{outcomes[1], outcomes[0], outcomes[2]}
		if err := ValidateResult(result); err == nil {
			t.Fatal("out-of-canonical outcomes accepted")
		}
	})
	t.Run("published mystery output", func(t *testing.T) {
		result := base(t)
		result.WorkerOutcomes[1] = successOutcome(t, WorkerPaymentStatus, map[string]any{"order_id": "ORD-1001", "payment_status": "MYSTERY"})
		if err := ValidateResult(result); err == nil {
			t.Fatal("published MYSTERY output accepted")
		}
	})
	t.Run("failed without a code", func(t *testing.T) {
		result := base(t)
		result.WorkerOutcomes[2] = WorkerOutcome{WorkerID: WorkerDeliveryStatus, Status: "FAILED"}
		if err := ValidateResult(result); err == nil {
			t.Fatal("FAILED outcome without failure_code accepted")
		}
	})
	t.Run("synthesis mismatch", func(t *testing.T) {
		result := base(t)
		result.SynthesisInvoked = false
		if err := ValidateResult(result); err == nil {
			t.Fatal("synthesis_invoked=false with a brief accepted")
		}
	})
	t.Run("failed without ALL_WORKERS_FAILED", func(t *testing.T) {
		outcomes := []WorkerOutcome{
			failedOutcome(WorkerOrderDetails, FailureWorkerExecutionFailed),
			failedOutcome(WorkerPaymentStatus, FailureWorkerExecutionFailed),
			failedOutcome(WorkerDeliveryStatus, FailureInvalidWorkerOutput),
		}
		result, err := AssembleResult(struct {
			RunID            string
			TracePath        string
			CaseID           string
			ExecutionMode    string
			OrderID          string
			PeakConcurrency  int
			Outcomes         []WorkerOutcome
			Brief            *Brief
			SynthesisInvoked bool
			Attribution      Attribution
		}{
			RunID: "run-1", TracePath: "trace.jsonl", CaseID: "parallel-all-failed",
			ExecutionMode: ModeParallel, OrderID: "ORD-1001", PeakConcurrency: 2,
			Outcomes: outcomes, SynthesisInvoked: false,
			Attribution: Attribution{Steps: []StepAttribution{
				{StepName: "worker.order-details", LatencyMS: 10, Attempts: 1},
				{StepName: "worker.payment-status", LatencyMS: 11, Attempts: 1},
				{StepName: "worker.delivery-status", LatencyMS: 12, Attempts: 1},
			}, Totals: Totals{LatencyMS: 33, Attempts: 3}},
		})
		if err != nil {
			t.Fatalf("assemble all-failed: %v", err)
		}
		if result.Status != "FAILED" || result.FailureCode == nil || *result.FailureCode != FailureAllWorkersFailed {
			t.Fatalf("unexpected all-failed result: %+v", result)
		}
		result.Brief = &Brief{OrderID: "ORD-1001"}
		if err := ValidateResult(result); err == nil {
			t.Fatal("FAILED result with a brief accepted")
		}
	})
}
