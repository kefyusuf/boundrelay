package contracts

// OrderBriefRecoveryResult is the M4 order-brief-recovery run result
// (contracts/results/order-brief-recovery-result.schema.json). It extends
// the order-brief shape with the recovery fields: resumed (this run
// continued a recorded run), restored_cursor (the recorded-terminal count
// loaded from the state document), restored_worker_ids (the workers whose
// outcomes were recovered), state_dir (the durable state root), and
// run_state_status (the final state document status, adding CANCELLED to
// the M3 result statuses). Nullable fields are pointers so null round-trips
// without being conflated with zero values; Attribution is required.
type OrderBriefRecoveryResult struct {
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
	TracePath         string          `json:"trace_path"`
	Resumed           bool            `json:"resumed"`
	RestoredCursor    *int            `json:"restored_cursor"`
	RestoredWorkerIDs []string        `json:"restored_worker_ids"`
	StateDir          string          `json:"state_dir"`
	RunStateStatus    string          `json:"run_state_status"`
	Attribution       Attribution     `json:"attribution"`
}
