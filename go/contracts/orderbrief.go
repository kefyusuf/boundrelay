package contracts

import "encoding/json"

// M3 worker identities and the fixed canonical order.
const (
	WorkerOrderDetails   = "order-details"
	WorkerPaymentStatus  = "payment-status"
	WorkerDeliveryStatus = "delivery-status"
)

// CanonicalWorkerIDs is the fixed worker execution and collector order.
var CanonicalWorkerIDs = []string{WorkerOrderDetails, WorkerPaymentStatus, WorkerDeliveryStatus}

// WorkerOutcome is one M3 worker execution result
// (contracts/workers/order-brief-worker-result.schema.json). Output carries
// the worker's JSON object for SUCCEEDED runs and null for failures.
type WorkerOutcome struct {
	WorkerID    string          `json:"worker_id"`
	Status      string          `json:"status"`
	Output      json.RawMessage `json:"output"`
	FailureCode *string         `json:"failure_code"`
}

// BriefSection is one synthesized section of the order brief.
type BriefSection struct {
	WorkerID string          `json:"worker_id"`
	Output   json.RawMessage `json:"output"`
}

// Brief is the synthesized order brief (order-brief-result $defs/brief).
type Brief struct {
	OrderID        string         `json:"order_id"`
	Sections       []BriefSection `json:"sections"`
	MissingWorkers []string       `json:"missing_workers"`
	Complete       bool           `json:"complete"`
}

// OrderBriefResult is the M3 order-brief run result
// (contracts/results/order-brief-result.schema.json); Attribution required.
type OrderBriefResult struct {
	SchemaVersion    string          `json:"schema_version"`
	RunID            string          `json:"run_id"`
	ScenarioID       string          `json:"scenario_id"`
	CaseID           string          `json:"case_id"`
	ExecutionMode    string          `json:"execution_mode"`
	ConcurrencyLimit int             `json:"concurrency_limit"`
	PeakConcurrency  int             `json:"peak_concurrency"`
	OrderID          string          `json:"order_id"`
	Status           string          `json:"status"`
	WorkerOutcomes   []WorkerOutcome `json:"worker_outcomes"`
	SynthesisInvoked bool            `json:"synthesis_invoked"`
	Brief            *Brief          `json:"brief"`
	FailureCode      *string         `json:"failure_code"`
	TracePath        string          `json:"trace_path"`
	Attribution      Attribution     `json:"attribution"`
}
