package contracts

// Failure codes shared with the TS/PY runtimes. M0 route decisions fail
// closed; M3 declared worker failures and malformed worker outputs map 1:1
// from the runtime sentinel errors. ALL_WORKERS_FAILED is M3's run-level
// code when no worker succeeded (order-brief-result.schema.json).
const (
	FailureInvalidRouteDecision  = "INVALID_ROUTE_DECISION"
	FailureWorkerExecutionFailed = "WORKER_EXECUTION_FAILED"
	FailureInvalidWorkerOutput   = "INVALID_WORKER_OUTPUT"
	FailureAllWorkersFailed      = "ALL_WORKERS_FAILED"
)

// RunResult is the M0 support-triage run result (run-result.schema.json).
// Nullable fields are pointers so null round-trips without being conflated
// with zero values; Attribution is required.
type RunResult struct {
	SchemaVersion     string      `json:"schema_version"`
	RunID             string      `json:"run_id"`
	ScenarioID        string      `json:"scenario_id"`
	CaseID            string      `json:"case_id"`
	Mode              string      `json:"mode"`
	Status            string      `json:"status"`
	SelectedRoute     *string     `json:"selected_route"`
	SpecialistInvoked bool        `json:"specialist_invoked"`
	FailureCode       *string     `json:"failure_code"`
	TracePath         string      `json:"trace_path"`
	Attribution       Attribution `json:"attribution"`
}
