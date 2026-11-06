package m4

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"sync"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// crashProbe is an OnCrash that unwinds with the CrashSignal sentinel so
// the library-level boundary is observable without killing the process.
func crashProbe() func() {
	return func() {
		panic(&CrashSignal{})
	}
}

// recordingObserver captures lifecycle events.
type recordingObserver struct {
	mutex   sync.Mutex
	started []string
	closed  []string
}

func (o *recordingObserver) observe(event WorkerLifecycle) {
	o.mutex.Lock()
	defer o.mutex.Unlock()
	if event.Kind == LifecycleStarted {
		o.started = append(o.started, event.WorkerID)
		return
	}
	o.closed = append(o.closed, event.Outcome.WorkerID)
}

// crashExecutor runs the executor with a panic-based crash control.
func crashExecutor(t *testing.T, crashAfter, fixtureRef string) (
	*StateStore, *recordingObserver, []string, error) {
	t.Helper()
	scenario, fixtures := loadRepoScenario(t)
	binding := StateBinding{CaseID: "parallel-crash-resume", ExecutionMode: ModeParallel,
		RequestedOrderID: scenario.OrderID, ConcurrencyLimit: 2}
	store, err := CreateStore(testTempDir(t), binding, append([]string(nil), contracts.CanonicalWorkerIDs...))
	if err != nil {
		t.Fatalf("create store: %v", err)
	}
	provider := &countingProvider{fixture: fixtures[fixtureRef], orderID: scenario.OrderID}
	observer := &recordingObserver{}
	_, execErr := ExecuteWorkers(context.Background(), ExecutorOptions{
		Mode: ModeParallel, Input: WorkerInput{OrderID: scenario.OrderID},
		Directory: DirectoryFromProvider(provider), Control: provider,
		Observer: observer.observe, Store: store,
		Controls: &RecoveryControls{CrashAfter: crashAfter},
		OnCrash:  crashProbe()})
	return store, observer, provider.invocations, execErr
}

// TestExecutorCrashCapsAdmission pins the Ruling-3 crash shaping: a crash
// target before the queue end caps admissions at its position (min(limit,
// pos)), the crash fires only at the quiescent boundary after the store
// recorded the target's terminal, and the crash unwinds without draining.
func TestExecutorCrashCapsAdmission(t *testing.T) {
	store, observer, invocations, err := crashExecutor(t,
		contracts.WorkerPaymentStatus, "fixtures/workers/order-brief/complete.yaml")
	var signal *CrashSignal
	if !errors.As(err, &signal) {
		t.Fatalf("crash must surface the CrashSignal for payment-status, got %v", err)
	}
	// Admission capped at the crash position: delivery-status never started.
	if len(invocations) != 2 {
		t.Fatalf("crash cap must admit exactly two workers, invoked %v", invocations)
	}
	// Quiescent boundary: both admitted workers recorded; the crashing
	// worker's terminal was written but not yet observed.
	document := store.State()
	if document.SequenceCursor != 2 || document.Steps[0].Status != StepStatusSucceeded ||
		document.Steps[1].Status != StepStatusSucceeded || document.Steps[2].Status != StepStatusPending {
		t.Fatalf("state at the crash boundary: %+v", document)
	}
	if len(observer.started) != 2 || len(observer.closed) != 1 {
		t.Fatalf("observer events at the boundary: started %v closed %v",
			observer.started, observer.closed)
	}
}

// TestExecutorCrashAfterLastWorker pins the terminal crash target: every
// worker is admitted and recorded, and the crash still fires before the
// final terminal observation.
func TestExecutorCrashAfterLastWorker(t *testing.T) {
	store, observer, invocations, err := crashExecutor(t,
		contracts.WorkerDeliveryStatus, "fixtures/workers/order-brief/partial-failure.yaml")
	var signal *CrashSignal
	if !errors.As(err, &signal) {
		t.Fatalf("crash must surface the CrashSignal, got %v", err)
	}
	if len(invocations) != 3 {
		t.Fatalf("all three workers must be admitted, invoked %v", invocations)
	}
	document := store.State()
	if document.SequenceCursor != 3 || document.Steps[2].Status != StepStatusFailed {
		t.Fatalf("state at the terminal crash boundary: %+v", document)
	}
	if len(observer.closed) != 2 {
		t.Fatalf("the crashed worker's terminal must not be observed: %v", observer.closed)
	}
}

// TestExecutorCancelDrainsQueue pins the Ruling-3 cancel shaping: admission
// stops at the cancel target (cap pos-1), the entered workers settle, and
// the summary reports the cancelled-before target for the caller's
// markCancelledFrom.
func TestExecutorCancelDrainsQueue(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	binding := StateBinding{CaseID: "parallel-cancel-resume", ExecutionMode: ModeParallel,
		RequestedOrderID: scenario.OrderID, ConcurrencyLimit: 2}
	store, err := CreateStore(testTempDir(t), binding, append([]string(nil), contracts.CanonicalWorkerIDs...))
	if err != nil {
		t.Fatalf("create store: %v", err)
	}
	provider := &countingProvider{
		fixture: fixtures["fixtures/workers/order-brief/complete.yaml"], orderID: scenario.OrderID}
	observer := &recordingObserver{}
	summary, execErr := ExecuteWorkers(context.Background(), ExecutorOptions{
		Mode: ModeParallel, Input: WorkerInput{OrderID: scenario.OrderID},
		Directory: DirectoryFromProvider(provider), Control: provider,
		Observer: observer.observe, Store: store,
		Controls: &RecoveryControls{CancelBefore: contracts.WorkerDeliveryStatus}})
	if execErr != nil {
		t.Fatalf("cancel run: %v", execErr)
	}
	if summary.CancelledBefore != contracts.WorkerDeliveryStatus {
		t.Fatalf("cancelled before: %+v", summary)
	}
	if len(provider.invocations) != 2 {
		t.Fatalf("cancel cap must leave the target uninvoked: %v", provider.invocations)
	}
	if len(summary.Outcomes) != 2 || summary.PeakConcurrency != 2 {
		t.Fatalf("summary: %+v", summary)
	}
	document := store.State()
	if document.SequenceCursor != 2 || document.Steps[2].Status != StepStatusPending {
		t.Fatalf("state after cancel: %+v", document)
	}
}

// TestExecutorFatalDrainsEnteredWorkers pins the fatal path: an unexpected
// worker error stops admission, drains the entered workers, and propagates.
func TestExecutorFatalDrainsEnteredWorkers(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	binding := StateBinding{CaseID: "parallel-clean-complete", ExecutionMode: ModeParallel,
		RequestedOrderID: scenario.OrderID, ConcurrencyLimit: 2}
	store, err := CreateStore(testTempDir(t), binding, append([]string(nil), contracts.CanonicalWorkerIDs...))
	if err != nil {
		t.Fatalf("create store: %v", err)
	}
	provider := &fatalOnPayment{inner: &countingProvider{
		fixture: fixtures["fixtures/workers/order-brief/complete.yaml"], orderID: scenario.OrderID}}
	observer := &recordingObserver{}
	_, execErr := ExecuteWorkers(context.Background(), ExecutorOptions{
		Mode: ModeParallel, Input: WorkerInput{OrderID: scenario.OrderID},
		Directory: DirectoryFromProvider(provider), Control: provider,
		Observer: observer.observe, Store: store})
	if execErr == nil || !strings.Contains(execErr.Error(), "boom") {
		t.Fatalf("fatal must propagate, got %v", execErr)
	}
	var signal *CrashSignal
	if errors.As(execErr, &signal) {
		t.Fatal("a fatal error is not a crash")
	}
}

// fatalOnPayment wraps a provider and raises an unexpected error from the
// payment-status body.
type fatalOnPayment struct{ inner *countingProvider }

func (p *fatalOnPayment) Read(id string, input WorkerInput) (json.RawMessage, error) {
	if id == contracts.WorkerPaymentStatus {
		return nil, errors.New("boom")
	}
	return p.inner.Read(id, input)
}
func (p *fatalOnPayment) AcknowledgeOutcome(id string) error { return nil }
func (p *fatalOnPayment) BeginDrain()                        {}

// TestExecutorRejectsInvalidInputs pins the closed input validation.
func TestExecutorRejectsInvalidInputs(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	base := ExecutorOptions{
		Mode: ModeParallel, Input: WorkerInput{OrderID: scenario.OrderID},
		Directory: DirectoryFromProvider(&countingProvider{
			fixture: fixtures["fixtures/workers/order-brief/complete.yaml"], orderID: scenario.OrderID}),
		Control:  &countingProvider{},
		Observer: func(WorkerLifecycle) {},
	}
	cases := []struct {
		name     string
		mutate   func(o ExecutorOptions) ExecutorOptions
		fragment string
	}{
		{"bad mode", func(o ExecutorOptions) ExecutorOptions { o.Mode = "concurrent"; return o }, "execution mode"},
		{"bad order id", func(o ExecutorOptions) ExecutorOptions { o.Input = WorkerInput{OrderID: "ORD-1"}; return o }, "order_id"},
		{"missing observer", func(o ExecutorOptions) ExecutorOptions { o.Observer = nil; return o }, "required"},
		{"duplicate queue", func(o ExecutorOptions) ExecutorOptions {
			o.Queue = []string{contracts.WorkerOrderDetails, contracts.WorkerOrderDetails}
			return o
		}, "queue"},
		{"non-canonical queue", func(o ExecutorOptions) ExecutorOptions {
			o.Queue = []string{contracts.WorkerPaymentStatus, contracts.WorkerOrderDetails}
			return o
		}, "queue"},
		{"both controls", func(o ExecutorOptions) ExecutorOptions {
			o.Controls = &RecoveryControls{CrashAfter: contracts.WorkerOrderDetails,
				CancelBefore: contracts.WorkerDeliveryStatus}
			return o
		}, "at most one control"},
		{"crash without on_crash", func(o ExecutorOptions) ExecutorOptions {
			o.Controls = &RecoveryControls{CrashAfter: contracts.WorkerOrderDetails}
			return o
		}, "requires store and on_crash"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			options := tc.mutate(base)
			_, err := ExecuteWorkers(context.Background(), options)
			if err == nil || !strings.Contains(err.Error(), tc.fragment) {
				t.Fatalf("expected error containing %q, got %v", tc.fragment, err)
			}
		})
	}
}

// TestExecutorSequentialModeRecordsAllSteps pins the sequential mode: peak
// one, every step recorded through the store.
func TestExecutorSequentialModeRecordsAllSteps(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	binding := StateBinding{CaseID: "sequential-complete", ExecutionMode: ModeSequential,
		RequestedOrderID: scenario.OrderID, ConcurrencyLimit: 1}
	store, err := CreateStore(testTempDir(t), binding, append([]string(nil), contracts.CanonicalWorkerIDs...))
	if err != nil {
		t.Fatalf("create store: %v", err)
	}
	provider := &countingProvider{
		fixture: fixtures["fixtures/workers/order-brief/complete.yaml"], orderID: scenario.OrderID}
	observer := &recordingObserver{}
	summary, execErr := ExecuteWorkers(context.Background(), ExecutorOptions{
		Mode: ModeSequential, Input: WorkerInput{OrderID: scenario.OrderID},
		Directory: DirectoryFromProvider(provider), Control: provider,
		Observer: observer.observe, Store: store})
	if execErr != nil {
		t.Fatalf("sequential run: %v", execErr)
	}
	if summary.PeakConcurrency != 1 || len(summary.Outcomes) != 3 {
		t.Fatalf("summary: %+v", summary)
	}
	if store.State().SequenceCursor != 3 {
		t.Fatalf("cursor: %+v", store.State())
	}
}
