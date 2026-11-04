package m3

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
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
// runs, terminal after the outcome is validated).
type WorkerObserver func(event WorkerLifecycle)

// ExecutorOptions configures one bounded fan-out.
type ExecutorOptions struct {
	Mode      string
	Input     WorkerInput
	Directory WorkerDirectory
	Control   WorkerControl
	Observer  WorkerObserver
}

// ExecutionSummary reports the settled outcomes (completion order) and the
// peak admission level.
type ExecutionSummary struct {
	Outcomes        []WorkerOutcome
	PeakConcurrency int
}

var workerInputPattern = regexp.MustCompile(`^ORD-[0-9]{4}$`)

type settled struct {
	id      string
	outcome WorkerOutcome
	err     error
}

// ExecuteWorkers admits the canonical worker queue under a bounded
// semaphore (1 sequential, 2 parallel), invokes each worker exactly once
// with an isolated copied input, validates outcomes, and honors the
// scripted completion order through the control. A fatal unexpected error
// stops admission, drains the entered workers (context cancellation), and
// propagates the first fatal error.
func ExecuteWorkers(ctx context.Context, options ExecutorOptions) (ExecutionSummary, error) {
	if options.Mode != ModeSequential && options.Mode != ModeParallel {
		return ExecutionSummary{}, fmt.Errorf("m3: execution mode must be sequential or parallel, got %q", options.Mode)
	}
	if !workerInputPattern.MatchString(options.Input.OrderID) {
		return ExecutionSummary{}, fmt.Errorf("m3: invalid worker input order_id %q", options.Input.OrderID)
	}
	if options.Directory == nil || options.Control == nil || options.Observer == nil {
		return ExecutionSummary{}, fmt.Errorf("m3: directory, control, and observer are required")
	}
	limit := 1
	if options.Mode == ModeParallel {
		limit = 2
	}
	pending := append([]string(nil), contracts.CanonicalWorkerIDs...)
	results := make(chan settled, len(contracts.CanonicalWorkerIDs))
	var entered sync.WaitGroup
	runContext, cancel := context.WithCancel(ctx)
	defer cancel()

	var fatal error
	outcomes := make([]WorkerOutcome, 0, len(pending))
	active, peak := 0, 0
	for len(pending) > 0 || active > 0 {
		for fatal == nil && len(pending) > 0 && active < limit {
			id := pending[0]
			pending = pending[1:]
			active++
			if active > peak {
				peak = active
			}
			entered.Add(1)
			go invokeWorker(runContext, options, id, results, &entered)
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
			outcomes = append(outcomes, settledResult.outcome)
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
	return ExecutionSummary{Outcomes: outcomes, PeakConcurrency: peak}, nil
}

// invokeWorker runs one worker body: resolve, observe started with the
// isolated copied input, execute, validate, observe terminal with the
// validated outcome. Declared failures become WORKER_EXECUTION_FAILED
// outcomes; any other error is fatal for the whole fan-out.
func invokeWorker(ctx context.Context, options ExecutorOptions, id string,
	results chan<- settled, entered *sync.WaitGroup) {
	defer entered.Done()
	worker, ok := options.Directory.Resolve(id)
	if !ok || worker.ID != id {
		results <- settled{id: id, err: fmt.Errorf("m3: unknown worker: %s", id)}
		return
	}
	isolated := WorkerInput{OrderID: options.Input.OrderID}
	options.Observer(WorkerLifecycle{Kind: LifecycleStarted, WorkerID: id, Input: isolated})
	outcome, err := workerOutcome(options, worker, isolated)
	if err != nil {
		results <- settled{id: id, err: err}
		return
	}
	options.Observer(WorkerLifecycle{Kind: LifecycleTerminal, WorkerID: id, Outcome: &outcome})
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
		return WorkerOutcome{WorkerID: worker.ID, Status: "SUCCEEDED",
			Output: append(json.RawMessage(nil), raw...), FailureCode: nil}, nil
	}
	return failedWorkerOutcome(worker.ID, contracts.FailureInvalidWorkerOutput), nil
}

func failedWorkerOutcome(id string, failureCode string) WorkerOutcome {
	code := failureCode
	return WorkerOutcome{WorkerID: id, Status: "FAILED", Output: json.RawMessage(nil), FailureCode: &code}
}

// workerOutputShapes are the closed per-worker output decoders
// (order-brief-worker-result.schema.json oneOf branches).
type orderDetailsOutput struct {
	OrderID     string `json:"order_id"`
	OrderStatus string `json:"order_status"`
}

type paymentStatusOutput struct {
	OrderID       string `json:"order_id"`
	PaymentStatus string `json:"payment_status"`
}

type deliveryStatusOutput struct {
	OrderID        string `json:"order_id"`
	DeliveryStatus string `json:"delivery_status"`
}

var workerOutputEnums = map[string]map[string]bool{
	contracts.WorkerOrderDetails:   {"PROCESSING": true, "SHIPPED": true, "CANCELLED": true},
	contracts.WorkerPaymentStatus:  {"PAID": true, "UNPAID": true},
	contracts.WorkerDeliveryStatus: {"PENDING": true, "IN_TRANSIT": true, "DELIVERED": true, "DELAYED": true},
}

// validateWorkerOutput mirrors validateWorkerOutput in the TS schemas: the
// raw return must strict-decode into the worker's closed output shape
// (unknown/missing fields rejected, finite numbers only) and carry the
// run's order id.
func validateWorkerOutput(id string, raw json.RawMessage, orderID string) bool {
	if len(raw) == 0 {
		return false
	}
	switch id {
	case contracts.WorkerOrderDetails:
		var output orderDetailsOutput
		if contracts.DecodeStrict(raw, &output) != nil ||
			!workerOutputEnums[id][output.OrderStatus] || output.OrderID != orderID {
			return false
		}
	case contracts.WorkerPaymentStatus:
		var output paymentStatusOutput
		if contracts.DecodeStrict(raw, &output) != nil ||
			!workerOutputEnums[id][output.PaymentStatus] || output.OrderID != orderID {
			return false
		}
	case contracts.WorkerDeliveryStatus:
		var output deliveryStatusOutput
		if contracts.DecodeStrict(raw, &output) != nil ||
			!workerOutputEnums[id][output.DeliveryStatus] || output.OrderID != orderID {
			return false
		}
	default:
		return false
	}
	return true
}
