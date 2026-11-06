package contracts

// M2 (support-handoff) failure codes shared with the TS/PY runtimes. The
// route-decision class fails closed before any handoff is built; the two
// handoff classes reject the envelope at context validation or receiver
// resolution, never after a dispatch (handoff-result.schema.json).
const (
	FailureHandoffContextInvalid      = "HANDOFF_CONTEXT_INVALID"
	FailureHandoffReceiverUnavailable = "HANDOFF_RECEIVER_UNAVAILABLE"
)

// M2FailureCodes is the closed failure-code enum of the M2 handoff result
// schema (contracts/results/handoff-result.schema.json). The route-decision
// class is shared with M0 (FailureInvalidRouteDecision).
var M2FailureCodes = []string{
	FailureInvalidRouteDecision, FailureHandoffContextInvalid,
	FailureHandoffReceiverUnavailable,
}

// IsM2FailureCode reports whether the code is inside the M2 enum.
func IsM2FailureCode(code string) bool {
	for _, failure := range M2FailureCodes {
		if failure == code {
			return true
		}
	}
	return false
}

// HandoffResult is the M2 support-handoff run result
// (contracts/results/handoff-result.schema.json). Nullable fields are
// pointers so null round-trips without being conflated with zero values;
// Attribution is required.
type HandoffResult struct {
	SchemaVersion     string      `json:"schema_version"`
	RunID             string      `json:"run_id"`
	ScenarioID        string      `json:"scenario_id"`
	CaseID            string      `json:"case_id"`
	RouterMode        string      `json:"router_mode"`
	Status            string      `json:"status"`
	ProposedRoute     *string     `json:"proposed_route"`
	SelectedRoute     *string     `json:"selected_route"`
	Receiver          *string     `json:"receiver"`
	FallbackApplied   bool        `json:"fallback_applied"`
	SpecialistInvoked bool        `json:"specialist_invoked"`
	FailureCode       *string     `json:"failure_code"`
	TracePath         string      `json:"trace_path"`
	Attribution       Attribution `json:"attribution"`
}
