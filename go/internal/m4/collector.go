package m4

import (
	"encoding/json"
	"fmt"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// Result and step statuses shared with the TS/PY runtimes.
const (
	StatusSucceeded = "SUCCEEDED"
	StatusFailed    = "FAILED"
	StatusCancelled = "CANCELLED"
)

// strPtr returns a pointer to the value.
func strPtr(value string) *string { return &value }

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

// workerOutputOrderID validates the raw return against the worker's closed
// output shape (unknown/missing fields rejected, enum-checked) and returns
// the output's order id.
func workerOutputOrderID(id string, raw json.RawMessage) (string, bool) {
	if len(raw) == 0 {
		return "", false
	}
	switch id {
	case contracts.WorkerOrderDetails:
		var output orderDetailsOutput
		if contracts.DecodeStrict(raw, &output) != nil ||
			!workerOutputEnums[id][output.OrderStatus] {
			return "", false
		}
		return output.OrderID, true
	case contracts.WorkerPaymentStatus:
		var output paymentStatusOutput
		if contracts.DecodeStrict(raw, &output) != nil ||
			!workerOutputEnums[id][output.PaymentStatus] {
			return "", false
		}
		return output.OrderID, true
	case contracts.WorkerDeliveryStatus:
		var output deliveryStatusOutput
		if contracts.DecodeStrict(raw, &output) != nil ||
			!workerOutputEnums[id][output.DeliveryStatus] {
			return "", false
		}
		return output.OrderID, true
	default:
		return "", false
	}
}

// validateWorkerOutput mirrors validateWorkerOutput in the TS schemas: the
// raw return must strict-decode into the worker's closed output shape and
// carry the run's order id.
func validateWorkerOutput(id string, raw json.RawMessage, orderID string) bool {
	extracted, ok := workerOutputOrderID(id, raw)
	return ok && extracted == orderID
}

// validateWorkerOutcome mirrors validateWorkerOutcome in the TS schemas: a
// closed outcome shape whose SUCCEEDED output matches the run's order id.
func validateWorkerOutcome(outcome WorkerOutcome, orderID string) bool {
	if !isCanonicalWorker(outcome.WorkerID) {
		return false
	}
	switch outcome.Status {
	case StatusSucceeded:
		if outcome.FailureCode != nil || !validateWorkerOutput(outcome.WorkerID, outcome.Output, orderID) {
			return false
		}
	case StatusFailed:
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
		return canonical, fmt.Errorf("m4: fan-in requires exactly three outcomes, got %d", len(raw))
	}
	for _, outcome := range raw {
		if !validateWorkerOutcome(outcome, orderID) {
			return canonical, fmt.Errorf("m4: invalid worker outcome for %s", outcome.WorkerID)
		}
	}
	byID := map[string]WorkerOutcome{}
	for _, outcome := range raw {
		if _, duplicate := byID[outcome.WorkerID]; duplicate {
			return canonical, fmt.Errorf("m4: duplicate worker identity %s", outcome.WorkerID)
		}
		byID[outcome.WorkerID] = outcome
	}
	for i, id := range contracts.CanonicalWorkerIDs {
		canonical[i] = byID[id]
	}
	return canonical, nil
}
