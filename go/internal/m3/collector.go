package m3

import (
	"fmt"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// strPtr returns a pointer to the value.
func strPtr(value string) *string { return &value }

// validateWorkerOutcome mirrors validateWorkerOutcome in the TS schemas: a
// closed outcome shape whose SUCCEEDED output matches the run's order id.
func validateWorkerOutcome(outcome WorkerOutcome, orderID string) bool {
	if !isCanonicalWorker(outcome.WorkerID) {
		return false
	}
	switch outcome.Status {
	case "SUCCEEDED":
		if outcome.FailureCode != nil || !validateWorkerOutput(outcome.WorkerID, outcome.Output, orderID) {
			return false
		}
	case "FAILED":
		if outcome.Output != nil && string(outcome.Output) != "null" {
			return false
		}
		if outcome.FailureCode == nil || (*outcome.FailureCode != contracts.FailureWorkerExecutionFailed &&
			*outcome.FailureCode != contracts.FailureInvalidWorkerOutput) {
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
		return canonical, fmt.Errorf("m3: fan-in requires exactly three outcomes, got %d", len(raw))
	}
	for _, outcome := range raw {
		if !validateWorkerOutcome(outcome, orderID) {
			return canonical, fmt.Errorf("m3: invalid worker outcome for %s", outcome.WorkerID)
		}
	}
	byID := map[string]WorkerOutcome{}
	for _, outcome := range raw {
		if _, duplicate := byID[outcome.WorkerID]; duplicate {
			return canonical, fmt.Errorf("m3: duplicate worker identity %s", outcome.WorkerID)
		}
		byID[outcome.WorkerID] = outcome
	}
	for i, id := range contracts.CanonicalWorkerIDs {
		canonical[i] = byID[id]
	}
	return canonical, nil
}
