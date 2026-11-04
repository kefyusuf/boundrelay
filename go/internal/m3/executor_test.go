package m3

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// countingProvider instruments worker bodies: peak concurrency, entry
// counts, and input isolation evidence (mirrors the TS executor probes).
type countingProvider struct {
	inner      WorkerProvider
	mu         sync.Mutex
	active     int
	peak       int
	entries    []string
	inputsSeen []WorkerInput
}

func (c *countingProvider) Read(id string, input WorkerInput) (json.RawMessage, error) {
	c.mu.Lock()
	c.active++
	if c.active > c.peak {
		c.peak = c.active
	}
	c.entries = append(c.entries, id)
	c.inputsSeen = append(c.inputsSeen, input)
	c.mu.Unlock()
	defer func() {
		c.mu.Lock()
		c.active--
		c.mu.Unlock()
	}()
	return c.inner.Read(id, input)
}

func (c *countingProvider) snapshot() (peak int, entries []string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.peak, append([]string(nil), c.entries...)
}

type executorResult struct {
	summary ExecutionSummary
	err     error
}

func runExecutor(spec CaseSpec, fixture WorkerInstructions, provider WorkerProvider,
	control WorkerControl) (executorResult, *countingProvider, []WorkerLifecycle) {
	instrumented := &countingProvider{inner: provider}
	var lifecycles []WorkerLifecycle
	var lifecycleMu sync.Mutex
	observer := func(event WorkerLifecycle) {
		lifecycleMu.Lock()
		lifecycles = append(lifecycles, event)
		lifecycleMu.Unlock()
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	summary, err := ExecuteWorkers(ctx, ExecutorOptions{
		Mode:      spec.ExecutionMode,
		Input:     WorkerInput{OrderID: "ORD-1001"},
		Directory: DirectoryFromProvider(instrumented),
		Control:   control,
		Observer:  observer,
	})
	return executorResult{summary, err}, instrumented, lifecycles
}

func scriptedFor(t *testing.T, caseID string) (CaseSpec, *ScriptedWorkers) {
	t.Helper()
	scenario := loadRepoScenario(t)
	spec, err := scenario.FindCase(caseID)
	if err != nil {
		t.Fatalf("FindCase: %v", err)
	}
	fixtures, err := LoadWorkerFixtures(mustWorkersPath(t))
	if err != nil {
		t.Fatalf("LoadWorkerFixtures: %v", err)
	}
	provider := NewScriptedWorkers(spec, scenario.OrderID, fixtures[spec.WorkerFixture])
	return spec, provider
}

func mustWorkersPath(t *testing.T) string {
	t.Helper()
	_, workersPath := repoPaths(t)
	return workersPath
}

func outcomeByWorker(t *testing.T, outcomes []WorkerOutcome, id string) WorkerOutcome {
	t.Helper()
	for _, outcome := range outcomes {
		if outcome.WorkerID == id {
			return outcome
		}
	}
	t.Fatalf("missing outcome for %s in %+v", id, outcomes)
	return WorkerOutcome{}
}

func TestExecutorBoundedAdmissionAndScriptedOrder(t *testing.T) {
	cases := []struct {
		caseID     string
		mode       string
		wantPeak   int
		wantStatus string
	}{
		{"sequential-complete", ModeSequential, 1, "SUCCEEDED"},
		{"parallel-complete", ModeParallel, 2, "SUCCEEDED"},
		{"parallel-out-of-order", ModeParallel, 2, "SUCCEEDED"},
	}
	for _, tc := range cases {
		t.Run(tc.caseID, func(t *testing.T) {
			spec, provider := scriptedFor(t, tc.caseID)
			result, instrumented, lifecycles := runExecutor(spec, nil, provider, provider)
			if result.err != nil {
				t.Fatalf("ExecuteWorkers: %v", result.err)
			}
			summary := result.summary
			if summary.PeakConcurrency != tc.wantPeak {
				t.Fatalf("peak concurrency %d, want %d", summary.PeakConcurrency, tc.wantPeak)
			}
			if len(summary.Outcomes) != 3 {
				t.Fatalf("outcomes: %+v", summary.Outcomes)
			}
			for _, outcome := range summary.Outcomes {
				if outcome.Status != tc.wantStatus {
					t.Fatalf("outcome: %+v", outcome)
				}
			}
			peak, entries := instrumented.snapshot()
			if peak != tc.wantPeak {
				t.Fatalf("instrumented peak %d, want %d", peak, tc.wantPeak)
			}
			if len(entries) != 3 {
				t.Fatalf("worker bodies must be invoked exactly once each: %v", entries)
			}
			seen := map[string]bool{}
			for _, id := range entries {
				if seen[id] {
					t.Fatalf("worker %s invoked more than once: %v", id, entries)
				}
				seen[id] = true
			}
			for _, input := range instrumented.inputsSeen {
				if input.OrderID != "ORD-1001" {
					t.Fatalf("isolated input must carry only the scenario order_id: %+v", input)
				}
			}
			started, terminal := 0, 0
			for _, event := range lifecycles {
				if event.Kind == LifecycleStarted {
					started++
				}
				if event.Kind == LifecycleTerminal {
					terminal++
				}
			}
			if started != 3 || terminal != 3 {
				t.Fatalf("lifecycle events: started %d terminal %d", started, terminal)
			}
		})
	}
}

func TestExecutorDeclaredFailureAndInvalidOutput(t *testing.T) {
	t.Run("declared raise maps to WORKER_EXECUTION_FAILED", func(t *testing.T) {
		spec, provider := scriptedFor(t, "parallel-partial-failure")
		result, _, lifecycles := runExecutor(spec, nil, provider, provider)
		if result.err != nil {
			t.Fatalf("ExecuteWorkers: %v", result.err)
		}
		delivery := outcomeByWorker(t, result.summary.Outcomes, contracts.WorkerDeliveryStatus)
		if delivery.Status != "FAILED" || delivery.Output != nil ||
			delivery.FailureCode == nil || *delivery.FailureCode != contracts.FailureWorkerExecutionFailed {
			t.Fatalf("delivery outcome: %+v", delivery)
		}
		var terminal *WorkerLifecycle
		for i := range lifecycles {
			if lifecycles[i].Kind == LifecycleTerminal && lifecycles[i].Outcome != nil &&
				lifecycles[i].Outcome.WorkerID == contracts.WorkerDeliveryStatus {
				terminal = &lifecycles[i]
			}
		}
		if terminal == nil || terminal.Outcome.FailureCode == nil ||
			*terminal.Outcome.FailureCode != contracts.FailureWorkerExecutionFailed {
			t.Fatalf("observer must see the validated failure outcome: %+v", terminal)
		}
	})
	t.Run("malformed return maps to INVALID_WORKER_OUTPUT", func(t *testing.T) {
		spec, provider := scriptedFor(t, "parallel-invalid-output")
		result, _, _ := runExecutor(spec, nil, provider, provider)
		if result.err != nil {
			t.Fatalf("ExecuteWorkers: %v", result.err)
		}
		payment := outcomeByWorker(t, result.summary.Outcomes, contracts.WorkerPaymentStatus)
		if payment.Status != "FAILED" || payment.Output != nil ||
			payment.FailureCode == nil || *payment.FailureCode != contracts.FailureInvalidWorkerOutput {
			t.Fatalf("payment outcome: %+v", payment)
		}
		details := outcomeByWorker(t, result.summary.Outcomes, contracts.WorkerOrderDetails)
		if details.Status != "SUCCEEDED" {
			t.Fatalf("valid sibling must succeed: %+v", details)
		}
	})
}

// fatalOnWorker lets the named worker enter the scripted gate and then
// fails with a plain (non-declared) error — the fatal lands after entry,
// which deterministically leaves later-entered workers gated mid-read.
type fatalOnWorker struct {
	inner  WorkerProvider
	target string
}

func (f *fatalOnWorker) Read(id string, input WorkerInput) (json.RawMessage, error) {
	raw, err := f.inner.Read(id, input)
	if err == nil && id == f.target {
		return nil, fmt.Errorf("boom in %s", id)
	}
	return raw, err
}

func TestExecutorFatalDrainsEnteredWorkers(t *testing.T) {
	// parallel-complete admits order-details+payment-status, completes
	// order-details (opening payment-status's gate), admits delivery-status
	// (gated until payment-status is acknowledged). The fatal in
	// payment-status therefore hits while delivery-status is entered and
	// gated mid-read: the drain must release it to a terminal.
	spec, provider := scriptedFor(t, "parallel-complete")
	directory := DirectoryFromProvider(&fatalOnWorker{inner: provider, target: contracts.WorkerPaymentStatus})
	var lifecycles []WorkerLifecycle
	var mu sync.Mutex
	observer := func(event WorkerLifecycle) {
		mu.Lock()
		lifecycles = append(lifecycles, event)
		mu.Unlock()
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	summary, err := ExecuteWorkers(ctx, ExecutorOptions{
		Mode: spec.ExecutionMode, Input: WorkerInput{OrderID: "ORD-1001"},
		Directory: directory, Control: provider, Observer: observer})
	if err == nil || !strings.Contains(err.Error(), "boom") {
		t.Fatalf("fatal error must propagate, got %v", err)
	}
	if summary.PeakConcurrency != 0 || len(summary.Outcomes) != 0 {
		t.Fatalf("fatal runs must not return a summary: %+v", summary)
	}
	terminals := map[string]bool{}
	started := map[string]bool{}
	for _, event := range lifecycles {
		if event.Kind == LifecycleStarted {
			started[event.WorkerID] = true
		}
		if event.Kind == LifecycleTerminal {
			terminals[event.Outcome.WorkerID] = true
		}
	}
	if !started[contracts.WorkerDeliveryStatus] {
		t.Fatalf("delivery-status must have been admitted before the fatal: %v", started)
	}
	if terminals[contracts.WorkerPaymentStatus] {
		t.Fatal("the fatal worker must not reach a terminal")
	}
	if !terminals[contracts.WorkerOrderDetails] || !terminals[contracts.WorkerDeliveryStatus] {
		t.Fatalf("entered workers must drain to terminals: %v", terminals)
	}
}

func TestScriptedWorkersGuards(t *testing.T) {
	_, provider := scriptedFor(t, "parallel-complete")
	t.Run("acknowledge requires the scripted next worker", func(t *testing.T) {
		if err := provider.AcknowledgeOutcome(contracts.WorkerPaymentStatus); err == nil ||
			!strings.Contains(err.Error(), "invalid outcome acknowledgement") {
			t.Fatalf("acknowledging out of script must fail, got %v", err)
		}
	})
	t.Run("once-only invocation", func(t *testing.T) {
		done := make(chan error, 1)
		go func() {
			_, err := provider.Read(contracts.WorkerOrderDetails, WorkerInput{OrderID: "ORD-1001"})
			done <- err
		}()
		time.Sleep(20 * time.Millisecond) // let the read enter its gate
		if _, err := provider.Read(contracts.WorkerOrderDetails, WorkerInput{OrderID: "ORD-1001"}); err == nil ||
			!strings.Contains(err.Error(), "invalid worker invocation") {
			t.Fatalf("re-entry must be rejected, got %v", err)
		}
		if _, err := provider.Read(contracts.WorkerPaymentStatus, WorkerInput{OrderID: "ORD-9999"}); err == nil {
			t.Fatal("input order mismatch must be rejected")
		}
		provider.BeginDrain()
		if err := <-done; err != nil {
			t.Fatalf("drained read must complete, got %v", err)
		}
	})
	t.Run("read after drain rejected", func(t *testing.T) {
		if _, err := provider.Read(contracts.WorkerDeliveryStatus, WorkerInput{OrderID: "ORD-1001"}); err == nil {
			t.Fatal("read after drain must be rejected")
		}
	})
	t.Run("drain releases entered gates", func(t *testing.T) {
		_, gated := scriptedFor(t, "parallel-complete")
		done := make(chan error, 1)
		go func() {
			_, err := gated.Read(contracts.WorkerOrderDetails, WorkerInput{OrderID: "ORD-1001"})
			done <- err
		}()
		time.Sleep(20 * time.Millisecond) // let the read enter its gate
		gated.BeginDrain()
		select {
		case err := <-done:
			if err != nil {
				t.Fatalf("drained read must complete, got %v", err)
			}
		case <-time.After(2 * time.Second):
			t.Fatal("drain must release entered gates")
		}
	})
}

func TestExecutorRejectsInvalidInput(t *testing.T) {
	provider := &staticProvider{responses: map[string]json.RawMessage{}}
	if _, err := ExecuteWorkers(context.Background(), ExecutorOptions{
		Mode: "concurrent", Input: WorkerInput{OrderID: "ORD-1001"},
		Directory: DirectoryFromProvider(provider), Control: nopControl{},
		Observer: func(WorkerLifecycle) {}}); err == nil {
		t.Fatal("unknown mode must be rejected")
	}
	if _, err := ExecuteWorkers(context.Background(), ExecutorOptions{
		Mode: ModeParallel, Input: WorkerInput{OrderID: "ORD-1"},
		Directory: DirectoryFromProvider(provider), Control: nopControl{},
		Observer: func(WorkerLifecycle) {}}); err == nil {
		t.Fatal("malformed order id must be rejected")
	}
	if _, err := ExecuteWorkers(context.Background(), ExecutorOptions{
		Mode: ModeParallel, Input: WorkerInput{OrderID: "ORD-1001"},
		Directory: partialDirectory{}, Control: nopControl{},
		Observer: func(WorkerLifecycle) {}}); err == nil || !strings.Contains(err.Error(), "unknown worker") {
		t.Fatalf("unknown worker must be a fatal tooling error, got %v", err)
	}
}

type staticProvider struct{ responses map[string]json.RawMessage }

func (s *staticProvider) Read(id string, input WorkerInput) (json.RawMessage, error) {
	return s.responses[id], nil
}

type nopControl struct{}

func (nopControl) AcknowledgeOutcome(string) error { return nil }
func (nopControl) BeginDrain()                     {}

type partialDirectory struct{}

func (partialDirectory) Resolve(id string) (WorkerDefinition, bool) {
	if id == contracts.WorkerOrderDetails {
		return WorkerDefinition{ID: id, Handle: func(WorkerInput) (json.RawMessage, error) {
			return json.RawMessage(`{"order_id":"ORD-1001","order_status":"SHIPPED"}`), nil
		}}, true
	}
	return WorkerDefinition{}, false
}
