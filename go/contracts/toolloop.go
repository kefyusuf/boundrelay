package contracts

// M1 (order-investigation) failure codes shared with the TS/PY runtimes.
// The four tool failure classes map 1:1 from the runtime sentinel errors;
// the budget classes fail closed from the bounded loop's counters, and
// INVALID_MODEL_DECISION covers scripted-provider and model-turn drift.
const (
	FailureUnknownTool          = "UNKNOWN_TOOL"
	FailureInvalidToolArguments = "INVALID_TOOL_ARGUMENTS"
	FailureToolTimeout          = "TOOL_TIMEOUT"
	FailureToolExecutionFailed  = "TOOL_EXECUTION_FAILED"
	FailureStepBudgetExceeded   = "STEP_BUDGET_EXCEEDED"
	FailureTokenBudgetExceeded  = "TOKEN_BUDGET_EXCEEDED"
	FailureInvalidModelDecision = "INVALID_MODEL_DECISION"
)

// M1FailureCodes is the closed failure-code enum of the M1 tool-loop result
// schema (tool-loop-result.schema.json).
var M1FailureCodes = []string{
	FailureUnknownTool, FailureInvalidToolArguments, FailureToolTimeout,
	FailureToolExecutionFailed, FailureStepBudgetExceeded,
	FailureTokenBudgetExceeded, FailureInvalidModelDecision,
}

// IsM1FailureCode reports whether the code is inside the M1 enum.
func IsM1FailureCode(code string) bool {
	for _, failure := range M1FailureCodes {
		if failure == code {
			return true
		}
	}
	return false
}

// ToolLoopResult is the M1 order-investigation run result
// (contracts/results/tool-loop-result.schema.json). Answer and FailureCode
// are pointers so null round-trips without being conflated with zero
// values; Attribution is required.
type ToolLoopResult struct {
	SchemaVersion   string      `json:"schema_version"`
	RunID           string      `json:"run_id"`
	ScenarioID      string      `json:"scenario_id"`
	CaseID          string      `json:"case_id"`
	Mode            string      `json:"mode"`
	Status          string      `json:"status"`
	Answer          *string     `json:"answer"`
	FailureCode     *string     `json:"failure_code"`
	ModelSteps      int         `json:"model_steps"`
	TokensUsed      int         `json:"tokens_used"`
	ToolInvocations int         `json:"tool_invocations"`
	TracePath       string      `json:"trace_path"`
	Attribution     Attribution `json:"attribution"`
}
