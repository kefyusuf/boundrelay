// Package results holds the closed M3 order-brief result shapes with
// structural validation. It mirrors the checked-in contracts by hand
// (contracts/results/order-brief-result.schema.json plus the per-worker
// output shapes): exact field sets, enums, the ORD-#### pattern, the
// canonical worker_outcomes ordering, and the status conditionals.
// Attribution totals must equal the sum of the steps (stronger than the
// JSON schema). The mapping's Eino graph runs schema-less on purpose:
// these validators are the gate that keeps the closed M3 shapes intact
// before publication.
package results

import (
	"bytes"
	"encoding/json"
	"fmt"
	"regexp"
)

// Worker identities and the fixed canonical order.
const (
	WorkerOrderDetails   = "order-details"
	WorkerPaymentStatus  = "payment-status"
	WorkerDeliveryStatus = "delivery-status"
)

// CanonicalWorkerIDs is the fixed worker execution and collector order.
var CanonicalWorkerIDs = []string{WorkerOrderDetails, WorkerPaymentStatus, WorkerDeliveryStatus}

// Failure codes carried by FAILED worker outcomes and all-failed runs.
const (
	FailureWorkerExecutionFailed = "WORKER_EXECUTION_FAILED"
	FailureInvalidWorkerOutput   = "INVALID_WORKER_OUTPUT"
	FailureAllWorkersFailed      = "ALL_WORKERS_FAILED"
)

// Execution modes.
const (
	ModeSequential = "sequential"
	ModeParallel   = "parallel"
)

// WorkerOutcome is one M3 worker execution result; Output carries the
// worker's JSON object for SUCCEEDED runs and null for failures.
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

// Brief is the synthesized order brief.
type Brief struct {
	OrderID        string         `json:"order_id"`
	Sections       []BriefSection `json:"sections"`
	MissingWorkers []string       `json:"missing_workers"`
	Complete       bool           `json:"complete"`
}

// StepAttribution is one attributed step: fixture-priced deterministic
// values, never wall-clock measurements.
type StepAttribution struct {
	StepName  string `json:"step_name"`
	LatencyMS int    `json:"latency_ms"`
	CostCents int    `json:"cost_cents"`
	Attempts  int    `json:"attempts"`
}

// Totals aggregates every step's attribution for the run.
type Totals struct {
	LatencyMS int `json:"latency_ms"`
	CostCents int `json:"cost_cents"`
	Attempts  int `json:"attempts"`
}

// Attribution is the required M6 attribution block embedded in every run
// result.
type Attribution struct {
	Steps  []StepAttribution `json:"steps"`
	Totals Totals            `json:"totals"`
}

// RunResult is the M3 order-brief run result.
type RunResult struct {
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

var orderIDPattern = regexp.MustCompile(`^ORD-[0-9]{4}$`)

func strPtr(value string) *string { return &value }

// validateWorkerOutput mirrors the per-worker closed output shapes: the raw
// return must strict-decode into the worker's exact shape (unknown and
// missing fields rejected) with an allowed enum value and the run's order
// id.
func validateWorkerOutput(id string, raw json.RawMessage, orderID string) bool {
	if len(raw) == 0 {
		return false
	}
	switch id {
	case WorkerOrderDetails:
		var output struct {
			OrderID     string `json:"order_id"`
			OrderStatus string `json:"order_status"`
		}
		if strictDecode(raw, &output) != nil || output.OrderID != orderID {
			return false
		}
		return output.OrderStatus == "PROCESSING" || output.OrderStatus == "SHIPPED" || output.OrderStatus == "CANCELLED"
	case WorkerPaymentStatus:
		var output struct {
			OrderID       string `json:"order_id"`
			PaymentStatus string `json:"payment_status"`
		}
		if strictDecode(raw, &output) != nil || output.OrderID != orderID {
			return false
		}
		return output.PaymentStatus == "PAID" || output.PaymentStatus == "UNPAID"
	case WorkerDeliveryStatus:
		var output struct {
			OrderID        string `json:"order_id"`
			DeliveryStatus string `json:"delivery_status"`
		}
		if strictDecode(raw, &output) != nil || output.OrderID != orderID {
			return false
		}
		return output.DeliveryStatus == "PENDING" || output.DeliveryStatus == "IN_TRANSIT" ||
			output.DeliveryStatus == "DELIVERED" || output.DeliveryStatus == "DELAYED"
	default:
		return false
	}
}

// strictDecode rejects unknown fields and trailing data.
func strictDecode(raw json.RawMessage, target any) error {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(target); err != nil {
		return err
	}
	if dec.More() {
		return fmt.Errorf("trailing data after JSON object")
	}
	return nil
}

// ValidateWorkerOutput exposes the per-worker closed-output validator for
// the node wrappers: the raw return must strict-decode into the worker's
// exact shape with an allowed enum value and the run's order id.
func ValidateWorkerOutput(workerID string, raw json.RawMessage, orderID string) bool {
	return validateWorkerOutput(workerID, raw, orderID)
}

// ValidateWorkerOutcome mirrors the closed outcome shape: a canonical
// identity whose SUCCEEDED output matches the run's order id.
func ValidateWorkerOutcome(outcome WorkerOutcome, orderID string) bool {
	canonical := false
	for _, id := range CanonicalWorkerIDs {
		if outcome.WorkerID == id {
			canonical = true
			break
		}
	}
	if !canonical {
		return false
	}
	switch outcome.Status {
	case "SUCCEEDED":
		if outcome.FailureCode != nil || !validateWorkerOutput(outcome.WorkerID, outcome.Output, orderID) {
			return false
		}
	case "FAILED":
		if outcome.Output != nil && !bytes.Equal(bytes.TrimSpace(outcome.Output), []byte("null")) {
			return false
		}
		if outcome.FailureCode == nil || (*outcome.FailureCode != FailureWorkerExecutionFailed &&
			*outcome.FailureCode != FailureInvalidWorkerOutput) {
			return false
		}
	default:
		return false
	}
	return true
}

// CanonicalizeOutcomes is the fan-in gate: exactly three validated outcomes
// with distinct canonical identities, reordered into the canonical worker
// order. Anything else is a tooling error.
func CanonicalizeOutcomes(raw []WorkerOutcome, orderID string) ([3]WorkerOutcome, error) {
	var canonical [3]WorkerOutcome
	if len(raw) != 3 {
		return canonical, fmt.Errorf("results: fan-in requires exactly three outcomes, got %d", len(raw))
	}
	for _, outcome := range raw {
		if !ValidateWorkerOutcome(outcome, orderID) {
			return canonical, fmt.Errorf("results: invalid worker outcome for %s", outcome.WorkerID)
		}
	}
	byID := map[string]WorkerOutcome{}
	for _, outcome := range raw {
		if _, duplicate := byID[outcome.WorkerID]; duplicate {
			return canonical, fmt.Errorf("results: duplicate worker identity %s", outcome.WorkerID)
		}
		byID[outcome.WorkerID] = outcome
	}
	for i, id := range CanonicalWorkerIDs {
		canonical[i] = byID[id]
	}
	return canonical, nil
}

// SynthesizeBrief assembles the order brief from the canonical outcomes:
// sections carry the successful outputs in canonical order, missing_workers
// the failed identities. Synthesis without successful evidence is an error.
func SynthesizeBrief(orderID string, outcomes []WorkerOutcome) (Brief, error) {
	brief := Brief{OrderID: orderID, Sections: []BriefSection{}, MissingWorkers: []string{}}
	for _, outcome := range outcomes {
		if outcome.Status == "SUCCEEDED" {
			brief.Sections = append(brief.Sections, BriefSection{
				WorkerID: outcome.WorkerID,
				Output:   append(json.RawMessage(nil), outcome.Output...),
			})
			continue
		}
		brief.MissingWorkers = append(brief.MissingWorkers, outcome.WorkerID)
	}
	if len(brief.Sections) == 0 {
		return Brief{}, fmt.Errorf("results: cannot synthesize without successful evidence")
	}
	brief.Complete = len(brief.MissingWorkers) == 0
	return brief, nil
}

// validateAttribution requires well-formed steps and totals equal to the
// step sums (the invariant the JSON schema cannot express).
func validateAttribution(attribution Attribution) error {
	if len(attribution.Steps) == 0 {
		return fmt.Errorf("results: attribution must carry at least one step")
	}
	sums := Totals{}
	for _, step := range attribution.Steps {
		if step.StepName == "" || step.LatencyMS < 0 || step.CostCents < 0 || step.Attempts < 1 {
			return fmt.Errorf("results: invalid attribution step %q", step.StepName)
		}
		sums.LatencyMS += step.LatencyMS
		sums.CostCents += step.CostCents
		sums.Attempts += step.Attempts
	}
	if attribution.Totals != sums {
		return fmt.Errorf("results: attribution totals must equal the step sums")
	}
	return nil
}

// validateResult mirrors the closed result schema: required fields, enums,
// the ORD pattern, canonical worker order, concurrency bounds, and the
// status conditionals over brief/failure_code/synthesis_invoked.
func validateResult(result RunResult) error {
	switch {
	case result.SchemaVersion != "1.0":
		return fmt.Errorf("results: result schema_version must be 1.0")
	case result.RunID == "" || result.TracePath == "":
		return fmt.Errorf("results: result run_id and trace_path must be nonempty")
	case result.ScenarioID != "order-brief" || result.CaseID == "":
		return fmt.Errorf("results: result scenario/case identifiers are invalid")
	case result.ExecutionMode != ModeSequential && result.ExecutionMode != ModeParallel:
		return fmt.Errorf("results: result execution_mode %q is outside the enum", result.ExecutionMode)
	case result.Status != "SUCCEEDED" && result.Status != "PARTIAL" && result.Status != "FAILED":
		return fmt.Errorf("results: result status %q is outside the enum", result.Status)
	case !orderIDPattern.MatchString(result.OrderID):
		return fmt.Errorf("results: result order_id %q is invalid", result.OrderID)
	}
	limit := 1
	if result.ExecutionMode == ModeParallel {
		limit = 2
	}
	if result.ConcurrencyLimit != limit || result.PeakConcurrency < 1 || result.PeakConcurrency > 2 {
		return fmt.Errorf("results: result concurrency %d/%d violates the schema", result.ConcurrencyLimit, result.PeakConcurrency)
	}
	if len(result.WorkerOutcomes) != 3 {
		return fmt.Errorf("results: result must carry exactly three worker outcomes")
	}
	successes := 0
	for i, outcome := range result.WorkerOutcomes {
		if outcome.WorkerID != CanonicalWorkerIDs[i] || !ValidateWorkerOutcome(outcome, result.OrderID) {
			return fmt.Errorf("results: worker outcome %d is invalid or out of canonical order", i)
		}
		if outcome.Status == "SUCCEEDED" {
			successes++
		}
	}
	if result.SynthesisInvoked != (successes > 0) {
		return fmt.Errorf("results: synthesis_invoked must match the successes")
	}
	if err := validateBrief(result, successes); err != nil {
		return err
	}
	if successes == 0 && (result.FailureCode == nil || *result.FailureCode != FailureAllWorkersFailed) {
		return fmt.Errorf("results: FAILED results must carry ALL_WORKERS_FAILED")
	}
	if successes > 0 && result.FailureCode != nil {
		return fmt.Errorf("results: successful/partial results carry no failure code")
	}
	return validateAttribution(result.Attribution)
}

// validateBrief checks the brief against the success count, including the
// rule that sections follow the canonical order of the succeeded subset.
func validateBrief(result RunResult, successes int) error {
	brief := result.Brief
	switch {
	case successes == 3:
		if brief == nil || !brief.Complete || len(brief.Sections) != 3 || len(brief.MissingWorkers) != 0 {
			return fmt.Errorf("results: SUCCEEDED results must carry a complete three-section brief")
		}
	case successes > 0:
		if brief == nil || brief.Complete || len(brief.Sections) != successes ||
			len(brief.MissingWorkers) != 3-successes {
			return fmt.Errorf("results: PARTIAL results must carry an incomplete brief")
		}
	default:
		if brief != nil {
			return fmt.Errorf("results: FAILED results carry no brief")
		}
	}
	if brief != nil {
		if brief.OrderID != result.OrderID {
			return fmt.Errorf("results: brief order_id must match the run")
		}
		position := 0
		for _, section := range brief.Sections {
			found := -1
			for i := position; i < len(CanonicalWorkerIDs); i++ {
				if CanonicalWorkerIDs[i] == section.WorkerID {
					found = i
					break
				}
			}
			if found < 0 {
				return fmt.Errorf("results: brief sections must follow the canonical order")
			}
			position = found + 1
		}
	}
	return nil
}

// RunStatus maps the success count to the closed result status.
func RunStatus(successes int) (string, *string) {
	switch {
	case successes == 3:
		return "SUCCEEDED", nil
	case successes > 0:
		return "PARTIAL", nil
	default:
		return "FAILED", strPtr(FailureAllWorkersFailed)
	}
}

// AssembleResult builds the run result from validated parts and gates it
// through the structural validator before publication.
func AssembleResult(input struct {
	RunID            string
	TracePath        string
	CaseID           string
	ExecutionMode    string
	OrderID          string
	PeakConcurrency  int
	Outcomes         []WorkerOutcome
	Brief            *Brief
	SynthesisInvoked bool
	Attribution      Attribution
}) (RunResult, error) {
	canonical, err := CanonicalizeOutcomes(input.Outcomes, input.OrderID)
	if err != nil {
		return RunResult{}, err
	}
	outcomes := make([]WorkerOutcome, 3)
	copy(outcomes, canonical[:])
	successes := 0
	for _, outcome := range outcomes {
		if outcome.Status == "SUCCEEDED" {
			successes++
		}
	}
	if input.SynthesisInvoked != (successes > 0) {
		return RunResult{}, fmt.Errorf("results: brief presence must match successful evidence")
	}
	status, failureCode := RunStatus(successes)
	limit := 1
	if input.ExecutionMode == ModeParallel {
		limit = 2
	}
	result := RunResult{
		SchemaVersion:    "1.0",
		RunID:            input.RunID,
		ScenarioID:       "order-brief",
		CaseID:           input.CaseID,
		ExecutionMode:    input.ExecutionMode,
		ConcurrencyLimit: limit,
		PeakConcurrency:  input.PeakConcurrency,
		OrderID:          input.OrderID,
		Status:           status,
		WorkerOutcomes:   outcomes,
		SynthesisInvoked: input.SynthesisInvoked,
		Brief:            input.Brief,
		FailureCode:      failureCode,
		TracePath:        input.TracePath,
		Attribution:      input.Attribution,
	}
	if err := validateResult(result); err != nil {
		return RunResult{}, err
	}
	return result, nil
}

// ValidateResult exposes the structural validator for tests and the CLI.
func ValidateResult(result RunResult) error { return validateResult(result) }
