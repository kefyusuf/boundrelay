package m4

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
// draining — at the crash boundary no worker is in flight.
type CrashSignal struct {
	WorkerID string
}

func (e *CrashSignal) Error() string {
	return fmt.Sprintf("m4: scripted crash after %s", e.WorkerID)
}

// RecoveryControls re-exported from the scenario types for executor use.
type ExecutorOptions struct {
	Mode      string
	Input     WorkerInput
	Directory WorkerDirectory
	Control   WorkerControl
	Observer  WorkerObserver
	Store     *StateStore
	Controls  *RecoveryControls
	OnCrash   func()
	Queue     []string
}

// ExecutionSummary reports the settled outcomes (completion order), the
// peak admission level, and the scripted cancellation target.
type ExecutionSummary struct {
	Outcomes        []WorkerOutcome
	PeakConcurrency int
	CancelledBefore string
}

var workerInputPattern = orderIDPattern

type settled struct {
	id      string
	outcome WorkerOutcome
	err     error
}

// ExecuteWorkers admits the requested worker queue under a bounded
// semaphore (1 sequential, 2 parallel) with the Ruling-3 control shaping:
// a crash control caps admissions at its position and fires the hard crash
// only at a quiescent boundary after the store recorded the target's
// terminal; a cancel control stops admission at its target and lets the
// entered workers drain. Admission marks the worker RUNNING in the store
// (write-ahead) before its body starts, and each settled outcome is
// recorded through the store before the next admission. A fatal unexpected
// error stops admission, drains the entered workers, and propagates the
// first fatal error.
func ExecuteWorkers(ctx context.Context, options ExecutorOptions) (summary ExecutionSummary, err error) {
	if options.Mode != ModeSequential && options.Mode != ModeParallel {
		return ExecutionSummary{}, fmt.Errorf("m4: execution mode must be sequential or parallel, got %q", options.Mode)
	}
	if !workerInputPattern.MatchString(options.Input.OrderID) {
		return ExecutionSummary{}, fmt.Errorf("m4: invalid worker input order_id %q", options.Input.OrderID)
	}
	if options.Directory == nil || options.Control == nil || options.Observer == nil {
		return ExecutionSummary{}, fmt.Errorf("m4: directory, control, and observer are required")
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
			return ExecutionSummary{}, fmt.Errorf("m4: invalid execution queue")
		}
		seen[id] = true
	}
	if len(queue) != len(expected) {
		return ExecutionSummary{}, fmt.Errorf("m4: invalid execution queue")
	}
	for index, id := range queue {
		if id != expected[index] {
			return ExecutionSummary{}, fmt.Errorf("m4: invalid execution queue")
		}
	}
	var crashAfter, cancelBefore string
	if options.Controls != nil {
		crashAfter, cancelBefore = options.Controls.CrashAfter, options.Controls.CancelBefore
	}
	if crashAfter != "" && cancelBefore != "" {
		return ExecutionSummary{}, fmt.Errorf("m4: at most one control is allowed")
	}
	if crashAfter != "" && (options.Store == nil || options.OnCrash == nil) {
		return ExecutionSummary{}, fmt.Errorf("m4: crash control requires store and on_crash")
	}
	crashPos := 0
	if crashAfter != "" {
		crashPos = workerIndex(crashAfter) + 1
	}
	limit := 1
	if options.Mode == ModeParallel {
		limit = 2
	}
	pending := append([]string(nil), queue...)
	results := make(chan settled, len(contracts.CanonicalWorkerIDs)+len(queue))
	var entered sync.WaitGroup
	runContext, cancel := context.WithCancel(ctx)
	defer cancel()

	// A crash implemented as a panic unwinds here without draining; the
	// scripted boundary is quiescent, so nothing is left in flight.
	defer func() {
		if recovered := recover(); recovered != nil {
			if signal, ok := recovered.(*CrashSignal); ok {
				summary, err = ExecutionSummary{}, signal
				return
			}
			panic(recovered)
		}
	}()

	var fatal error
	outcomes := make([]WorkerOutcome, 0, len(pending))
	active, peak := 0, 0
	cancelFired := false
	for len(pending) > 0 || active > 0 {
		for fatal == nil && !cancelFired && len(pending) > 0 && active < limit {
			next := pending[0]
			if cancelBefore != "" && next == cancelBefore {
				cancelFired = true
				break
			}
			if crashPos > 0 && workerIndex(next) >= crashPos {
				break
			}
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
			go invokeWorker(runContext, options, next, results, &entered)
		}
		if fatal != nil {
			break
		}
		if cancelFired && active == 0 {
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
			if crashAfter != "" && active == 0 &&
				crashBoundaryReady(options.Store, crashAfter) {
				options.OnCrash()
			}
			outcomes = append(outcomes, settledResult.outcome)
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
	summary = ExecutionSummary{Outcomes: outcomes, PeakConcurrency: peak}
	if cancelFired && cancelBefore != "" {
		summary.CancelledBefore = cancelBefore
	}
	return summary, nil
}

// crashBoundaryReady mirrors the TS gate: the crash fires only once the
// target's terminal is recorded (SUCCEEDED/FAILED), the document is still
// RUNNING, and the Ruling-2 cursor equals the recorded-terminal count — the
// quiescent crash boundary where a hard exit loses nothing.
func crashBoundaryReady(store *StateStore, crashAfter string) bool {
	document := store.State()
	step := document.Steps[workerIndex(crashAfter)]
	recorded := 0
	for _, entry := range document.Steps {
		if recordedStep(entry) {
			recorded++
		}
	}
	return document.Status == RunStateStatusRunning &&
		(step.Status == StepStatusSucceeded || step.Status == StepStatusFailed) &&
		document.SequenceCursor == recorded
}

// invokeWorker runs one worker body: resolve, observe started with the
// isolated copied input, execute, validate, and settle. Declared failures
// become WORKER_EXECUTION_FAILED outcomes; any other error is fatal for the
// whole fan-out.
func invokeWorker(ctx context.Context, options ExecutorOptions, id string,
	results chan<- settled, entered *sync.WaitGroup) {
	defer entered.Done()
	worker, ok := options.Directory.Resolve(id)
	if !ok || worker.ID != id {
		results <- settled{id: id, err: fmt.Errorf("m4: unknown worker: %s", id)}
		return
	}
	isolated := WorkerInput{OrderID: options.Input.OrderID}
	options.Observer(WorkerLifecycle{Kind: LifecycleStarted, WorkerID: id, Input: isolated})
	outcome, err := workerOutcome(options, worker, isolated)
	if err != nil {
		results <- settled{id: id, err: err}
		return
	}
	results <- settled{id: id, outcome: outcome}
}

// workerOutcome executes the body and validates the return against the
// closed per-worker output shape and the run's order id.
func workerOutcome(options ExecutorOptions, worker WorkerDefinition, isolated WorkerInput) (WorkerOutcome, error) {
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
