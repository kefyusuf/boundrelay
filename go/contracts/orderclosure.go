package contracts

// OrderClosureResult is the M5 order-closure run result
// (contracts/results/order-closure-result.schema.json). It carries the
// side-effect surface on top of the shared worker-outcome shape:
// approval_decision (granted/rejected/none), effect_status
// (EFFECT_COMPLETED/EFFECT_REJECTED/EFFECT_UNPROVABLE/null),
// idempotency_key, reconciled (the submit-marker was adopted from the
// ledger with zero new submits), and the M4-style recovery provenance.
// Synthesis is never invoked and brief is always null (Ruling 4); statuses
// add UNKNOWN — the terminal state of a submit-marker run whose sink could
// not be proven. Nullable fields are pointers so null round-trips without
// being conflated with zero values; Attribution is required.
type OrderClosureResult struct {
	SchemaVersion     string          `json:"schema_version"`
	RunID             string          `json:"run_id"`
	ScenarioID        string          `json:"scenario_id"`
	CaseID            string          `json:"case_id"`
	ExecutionMode     string          `json:"execution_mode"`
	ConcurrencyLimit  int             `json:"concurrency_limit"`
	PeakConcurrency   int             `json:"peak_concurrency"`
	OrderID           string          `json:"order_id"`
	Status            string          `json:"status"`
	WorkerOutcomes    []WorkerOutcome `json:"worker_outcomes"`
	SynthesisInvoked  bool            `json:"synthesis_invoked"`
	Brief             *Brief          `json:"brief"`
	FailureCode       *string         `json:"failure_code"`
	ApprovalDecision  string          `json:"approval_decision"`
	EffectStatus      *string         `json:"effect_status"`
	IdempotencyKey    *string         `json:"idempotency_key"`
	Reconciled        bool            `json:"reconciled"`
	TracePath         string          `json:"trace_path"`
	Resumed           bool            `json:"resumed"`
	RestoredCursor    *int            `json:"restored_cursor"`
	RestoredWorkerIDs []string        `json:"restored_worker_ids"`
	StateDir          string          `json:"state_dir"`
	RunStateStatus    string          `json:"run_state_status"`
	Attribution       Attribution     `json:"attribution"`
}
