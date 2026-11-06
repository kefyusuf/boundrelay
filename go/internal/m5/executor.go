package m5

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// WorkerInput is the isolated worker payload: the order id only.
type WorkerInput struct {
	OrderID string
}

// WorkerHandler is one worker body.
type WorkerHandler func(input WorkerInput) (json.RawMessage, error)

// WorkerDefinition names a resolvable worker and carries its body.
type WorkerDefinition struct {
	ID     string
	Handle WorkerHandler
}

// WorkerProvider is the worker body boundary (Read). Providers must honor
// drain (Control.BeginDrain) for entered gates to release.
type WorkerProvider interface {
	Read(id string, input WorkerInput) (json.RawMessage, error)
}

// WorkerControl acknowledges settled outcomes and drains entered workers.
type WorkerControl interface {
	AcknowledgeOutcome(id string) error
	BeginDrain()
}

// WorkerDirectory resolves worker ids to definitions.
type WorkerDirectory interface {
	Resolve(id string) (WorkerDefinition, bool)
}

// DirectoryFromProvider resolves exactly the canonical workers through the
// provider (the TS workers.ts directory).
func DirectoryFromProvider(provider WorkerProvider) WorkerDirectory {
	return providerDirectory{provider: provider}
}

type providerDirectory struct{ provider WorkerProvider }

func (d providerDirectory) Resolve(id string) (WorkerDefinition, bool) {
	if isCanonicalWorker(id) {
		return WorkerDefinition{ID: id, Handle: func(input WorkerInput) (json.RawMessage, error) {
			return d.provider.Read(id, input)
		}}, true
	}
	return WorkerDefinition{}, false
}

// Worker lifecycle observer kinds.
const (
	LifecycleStarted  = "started"
	LifecycleTerminal = "terminal"
)

// WorkerLifecycle mirrors the TS observer union: started carries the
// isolated input; terminal carries the validated outcome.
type WorkerLifecycle struct {
	Kind     string
	WorkerID string
	Input    WorkerInput
	Outcome  *WorkerOutcome
}

// WorkerObserver receives worker lifecycle events (started before the body
// runs, terminal after the store recorded the outcome).
type WorkerObserver func(event WorkerLifecycle)

// CrashSignal is the panic sentinel raised by OnCrash implementations that
// do not exit the process directly (tests); the executor unwinds it without
// draining — at both crash boundaries no worker is in flight (the reads
// loop has settled and the ledger submit has returned).
type CrashSignal struct {
	Boundary string
}

func (e *CrashSignal) Error() string {
	return fmt.Sprintf("m5: scripted crash at the %s boundary", e.Boundary)
}

// Crash boundary names for the two effect-pipeline crash controls.
const (
	CrashBoundaryBeforeSubmit   = "before-submit"
	CrashBoundaryInSubmitWindow = "in-submit-window"
)

// EffectWiring bundles the side-effect collaborators the executor drives
// after the reads settle: the ledger, the fixture approval gate, the audit
// writer, the scripted controls, the crash hook, and the event sink.
type EffectWiring struct {
	Ledger       *EffectLedger
	ApprovalGate ApprovalGate
	Audit        *AuditWriter
	Controls     *EffectControls
	OnCrash      func()
	Events       *EventSink
}

// ExecutorOptions configures one bounded execution: the reads queue plus the
// optional effect wiring.
type ExecutorOptions struct {
	Mode      string
	Input     WorkerInput
	Directory WorkerDirectory
	Control   WorkerControl
	Observer  WorkerObserver
	Store     *StateStore
	Queue     []string
	Effect    *EffectWiring
}

// ExecutionSummary reports the settled outcomes (completion order), the
// peak admission level, the settled effect of record, and whether the
// approval rejected the effect.
type ExecutionSummary struct {
	Reads           []WorkerOutcome
	PeakConcurrency int
	Effect          *EffectRecord
	Rejected        bool
}

type settled struct {
	id      string
	outcome WorkerOutcome
	err     error
}

// ExecuteWorkers admits the requested worker queue under a bounded
// semaphore (1 sequential, 2 parallel): admission marks the worker RUNNING
// in the store (write-ahead) before its body starts, and each settled
// outcome is recorded through the store before the next admission. When the
// reads all succeed and effect wiring is present, the effect pipeline runs:
// approval.requested -> gate decision -> approval.granted/rejected -> audit
// -> require_approval -> crash_before_submit -> markSubmitted (write-ahead)
// -> tool.requested -> ledger.submit -> crash_in_submit_window ->
// tool.completed -> recordEffectOutcome -> audit. A fatal unexpected error
// stops everything, drains the entered workers, and propagates the first
// fatal error; a scripted crash unwinds through the CrashSignal without
// draining (no worker is in flight at either boundary).
func ExecuteWorkers(ctx context.Context, options ExecutorOptions) (summary ExecutionSummary, err error) {
	if options.Mode != ModeSequential && options.Mode != ModeParallel {
		return ExecutionSummary{}, fmt.Errorf("m5: execution mode must be sequential or parallel, got %q", options.Mode)
	}
	if !orderIDPattern.MatchString(options.Input.OrderID) {
		return ExecutionSummary{}, fmt.Errorf("m5: invalid worker input order_id %q", options.Input.OrderID)
	}
	if options.Directory == nil || options.Control == nil || options.Observer == nil {
		return ExecutionSummary{}, fmt.Errorf("m5: directory, control, and observer are required")
	}
	queue := options.Queue
	if queue == nil {
		queue = append([]string(nil), contracts.CanonicalWorkerIDs...)
	}
	expected := make([]string, 0, len(queue))
	for _, canonical := range contracts.CanonicalWorkerIDs {
		for _, id := range queue {
			if id == canonical {
				expected = append(expected, id)
				break
			}
		}
	}
	seen := map[string]bool{}
	for _, id := range queue {
		if seen[id] {
			return ExecutionSummary{}, fmt.Errorf("m5: invalid execution queue")
		}
		seen[id] = true
	}
	if len(queue) != len(expected) {
		return ExecutionSummary{}, fmt.Errorf("m5: invalid execution queue")
	}
	for index, id := range queue {
		if id != expected[index] {
			return ExecutionSummary{}, fmt.Errorf("m5: invalid execution queue")
		}
	}
	wiring := options.Effect
	if wiring != nil {
		if wiring.Controls != nil && (wiring.Controls.CrashBeforeSubmit || wiring.Controls.CrashInSubmitWindow) {
			if wiring.OnCrash == nil || options.Store == nil {
				return ExecutionSummary{}, fmt.Errorf("m5: crash control requires on_crash and the store")
			}
		}
	}

	// A crash implemented as a panic unwinds here without draining; both
	// scripted boundaries are quiescent, so nothing is left in flight.
	defer func() {
		if recovered := recover(); recovered != nil {
			if signal, ok := recovered.(*CrashSignal); ok {
				summary, err = ExecutionSummary{}, signal
				return
			}
			panic(recovered)
		}
	}()

	limit := 1
	if options.Mode == ModeParallel {
		limit = 2
	}
	pending := append([]string(nil), queue...)
	results := make(chan settled, len(contracts.CanonicalWorkerIDs)+len(queue))
	var entered sync.WaitGroup
	runContext, cancel := context.WithCancel(ctx)
	defer cancel()

	var fatal error
	reads := make([]WorkerOutcome, 0, len(pending))
	active, peak := 0, 0
	for len(pending) > 0 || active > 0 {
		for fatal == nil && len(pending) > 0 && active < limit {
			next := pending[0]
			pending = pending[1:]
			if options.Store != nil {
				if err := options.Store.MarkRunning(next); err != nil {
					fatal = err
					break
				}
			}
			active++
			if active > peak {
				peak = active
			}
			entered.Add(1)
			go invokeWorker(options, next, results, &entered)
		}
		if fatal != nil {
			break
		}
		select {
		case settledResult := <-results:
			active--
			if settledResult.err != nil {
				fatal = settledResult.err
				break
			}
			if options.Store != nil {
				if err := options.Store.RecordStepTerminal(settledResult.outcome.WorkerID, settledResult.outcome); err != nil {
					fatal = err
					break
				}
			}
			reads = append(reads, settledResult.outcome)
			options.Observer(WorkerLifecycle{Kind: LifecycleTerminal,
				WorkerID: settledResult.outcome.WorkerID, Outcome: &settledResult.outcome})
			if err := options.Control.AcknowledgeOutcome(settledResult.outcome.WorkerID); err != nil {
				fatal = err
			}
		case <-runContext.Done():
			if fatal == nil {
				fatal = runContext.Err()
			}
		}
	}
	if fatal != nil {
		options.Control.BeginDrain()
		entered.Wait()
		return ExecutionSummary{}, fatal
	}

	if wiring == nil || options.Store == nil || anyReadFailed(reads) {
		return ExecutionSummary{Reads: reads, PeakConcurrency: peak}, nil
	}
	effect, rejected, effectErr := runEffectPipeline(wiring, options.Store, options.Input.OrderID)
	if effectErr != nil {
		options.Control.BeginDrain()
		entered.Wait()
		return ExecutionSummary{}, effectErr
	}
	summary = ExecutionSummary{Reads: reads, PeakConcurrency: peak, Effect: effect, Rejected: rejected}
	return summary, nil
}

// anyReadFailed reports whether any settled read failed.
func anyReadFailed(reads []WorkerOutcome) bool {
	for _, outcome := range reads {
		if outcome.Status != StatusSucceeded {
			return true
		}
	}
	return false
}

// runEffectPipeline drives the side-effect pipeline after the reads settle,
// exactly in the TS/Python write-ahead order. It returns the settled effect
// of record (nil when the approval rejected or the wiring declined) and
// whether the approval rejected the effect.
func runEffectPipeline(wiring *EffectWiring, store *StateStore, orderID string) (*EffectRecord, bool, error) {
	payload := EffectPayloadOf(orderID)
	key := EffectKey(payload)
	digest, err := EffectDigest(payload)
	if err != nil {
		return nil, false, err
	}
	events := wiring.Events
	if events != nil {
		if _, err := events.Emit(contracts.EventApprovalRequested, map[string]any{
			"operation": EffectOperation, "order_id": orderID, "payload_digest": digest}); err != nil {
			return nil, false, err
		}
	}
	decision, record, err := wiring.ApprovalGate.Decide(payload)
	if err != nil {
		return nil, false, err
	}
	if events != nil {
		decisionEvent := contracts.EventApprovalGranted
		if decision != DecisionGranted {
			decisionEvent = contracts.EventApprovalRejected
		}
		if _, err := events.Emit(decisionEvent, map[string]any{
			"operation": EffectOperation, "order_id": orderID, "payload_digest": digest}); err != nil {
			return nil, false, err
		}
	}
	if wiring.Audit != nil {
		if err := wiring.Audit.Append(ApprovalAuditRecord{Kind: "approval",
			Operation: record.Operation, OrderID: record.OrderID,
			PayloadDigest: record.PayloadDigest, Decision: record.Decision,
			Approver: record.Approver}); err != nil {
			return nil, false, err
		}
	}
	if decision != DecisionGranted {
		return nil, true, nil
	}
	if err := RequireApproval(record, payload); err != nil {
		return nil, false, err
	}
	if wiring.Controls != nil && wiring.Controls.CrashBeforeSubmit {
		wiring.OnCrash()
	}
	if err := store.MarkSubmitted(key, digest); err != nil {
		return nil, false, err
	}
	if events != nil {
		if _, err := events.Emit(contracts.EventToolRequested, map[string]any{
			"key": key, "payload_digest": digest, "side_effect_class": "external"}); err != nil {
			return nil, false, err
		}
	}
	submitted, err := wiring.Ledger.submit(key, digest, payload)
	if err != nil {
		if events != nil {
			_, _ = events.Emit(contracts.EventToolFailed, map[string]any{"key": key})
		}
		return nil, false, err
	}
	if wiring.Controls != nil && wiring.Controls.CrashInSubmitWindow {
		wiring.OnCrash()
	}
	effect := EffectRecord{Key: key, PayloadDigest: digest, Status: submitted.Status,
		Outcome: submitted.Outcome, Duplicate: submitted.Duplicate}
	if events != nil {
		if _, err := events.Emit(contracts.EventToolCompleted, map[string]any{
			"key": key, "status": submitted.Status, "duplicate": submitted.Duplicate}); err != nil {
			return nil, false, err
		}
	}
	if err := store.RecordEffectOutcome(effect); err != nil {
		return nil, false, err
	}
	if wiring.Audit != nil {
		if err := wiring.Audit.Append(EffectAuditRecord{Kind: "effect",
			Operation: EffectOperation, OrderID: orderID, IdempotencyKey: key,
			EffectStatus: submitted.Status, Duplicate: submitted.Duplicate}); err != nil {
			return nil, false, err
		}
	}
	return &effect, false, nil
}

// invokeWorker runs one worker body: resolve, observe started with the
// isolated copied input, execute, validate, and settle. Declared failures
// become WORKER_EXECUTION_FAILED outcomes; any other error is fatal for the
// whole fan-out.
func invokeWorker(options ExecutorOptions, id string, results chan<- settled, entered *sync.WaitGroup) {
	defer entered.Done()
	worker, ok := options.Directory.Resolve(id)
	if !ok || worker.ID != id {
		results <- settled{id: id, err: fmt.Errorf("m5: unknown worker: %s", id)}
		return
	}
	isolated := WorkerInput{OrderID: options.Input.OrderID}
	options.Observer(WorkerLifecycle{Kind: LifecycleStarted, WorkerID: id, Input: isolated})
	outcome, err := workerOutcome(worker, isolated)
	if err != nil {
		results <- settled{id: id, err: err}
		return
	}
	results <- settled{id: id, outcome: outcome}
}

// workerOutcome executes the body and validates the return against the
// closed per-worker output shape and the run's order id.
func workerOutcome(worker WorkerDefinition, isolated WorkerInput) (WorkerOutcome, error) {
	raw, err := worker.Handle(isolated)
	if err != nil {
		if errors.Is(err, ErrWorkerExecution) {
			return failedWorkerOutcome(worker.ID, contracts.FailureWorkerExecutionFailed), nil
		}
		return WorkerOutcome{}, err
	}
	if validateWorkerOutput(worker.ID, raw, isolated.OrderID) {
		return WorkerOutcome{WorkerID: worker.ID, Status: StatusSucceeded,
			Output: append(json.RawMessage(nil), raw...), FailureCode: nil}, nil
	}
	return failedWorkerOutcome(worker.ID, contracts.FailureInvalidWorkerOutput), nil
}

func failedWorkerOutcome(id string, failureCode string) WorkerOutcome {
	code := failureCode
	return WorkerOutcome{WorkerID: id, Status: StatusFailed, Output: json.RawMessage(nil), FailureCode: &code}
}
