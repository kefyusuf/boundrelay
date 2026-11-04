package m3

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

func succeededOutcome(id string, output string) WorkerOutcome {
	return WorkerOutcome{WorkerID: id, Status: "SUCCEEDED",
		Output: jsonRaw(output), FailureCode: nil}
}

func failedOutcome(id string, code string) WorkerOutcome {
	return WorkerOutcome{WorkerID: id, Status: "FAILED",
		Output: jsonRaw("null"), FailureCode: &code}
}

func jsonRaw(value string) json.RawMessage { return json.RawMessage(value) }

func TestCanonicalizeOutcomes(t *testing.T) {
	raw := []WorkerOutcome{
		failedOutcome(contracts.WorkerDeliveryStatus, contracts.FailureWorkerExecutionFailed),
		succeededOutcome(contracts.WorkerPaymentStatus, `{"order_id":"ORD-1001","payment_status":"PAID"}`),
		succeededOutcome(contracts.WorkerOrderDetails, `{"order_id":"ORD-1001","order_status":"SHIPPED"}`),
	}
	canonical, err := CanonicalizeOutcomes(raw, "ORD-1001")
	if err != nil {
		t.Fatalf("CanonicalizeOutcomes: %v", err)
	}
	for i, id := range contracts.CanonicalWorkerIDs {
		if canonical[i].WorkerID != id {
			t.Fatalf("canonical position %d = %s, want %s", i, canonical[i].WorkerID, id)
		}
	}
}

func TestCanonicalizeOutcomesRejects(t *testing.T) {
	valid := succeededOutcome(contracts.WorkerOrderDetails, `{"order_id":"ORD-1001","order_status":"SHIPPED"}`)
	cases := []struct {
		name string
		raw  []WorkerOutcome
		frag string
	}{
		{"wrong count", []WorkerOutcome{valid, valid}, "exactly three"},
		{"duplicate identity", []WorkerOutcome{valid, valid,
			succeededOutcome(contracts.WorkerPaymentStatus, `{"order_id":"ORD-1001","payment_status":"PAID"}`)},
			"duplicate worker identity"},
		{"bad output shape", []WorkerOutcome{
			succeededOutcome(contracts.WorkerOrderDetails, `{"order_id":"ORD-1001","order_status":"LOST"}`),
			succeededOutcome(contracts.WorkerPaymentStatus, `{"order_id":"ORD-1001","payment_status":"PAID"}`),
			succeededOutcome(contracts.WorkerDeliveryStatus, `{"order_id":"ORD-1001","delivery_status":"DELAYED"}`),
		}, "invalid"},
		{"foreign order id", []WorkerOutcome{
			succeededOutcome(contracts.WorkerOrderDetails, `{"order_id":"ORD-9999","order_status":"SHIPPED"}`),
			succeededOutcome(contracts.WorkerPaymentStatus, `{"order_id":"ORD-1001","payment_status":"PAID"}`),
			succeededOutcome(contracts.WorkerDeliveryStatus, `{"order_id":"ORD-1001","delivery_status":"DELAYED"}`),
		}, "invalid"},
		{"failed with output", []WorkerOutcome{
			WorkerOutcome{WorkerID: contracts.WorkerOrderDetails, Status: "FAILED",
				Output: jsonRaw(`{"order_id":"ORD-1001"}`), FailureCode: strPtr("X")},
			succeededOutcome(contracts.WorkerPaymentStatus, `{"order_id":"ORD-1001","payment_status":"PAID"}`),
			succeededOutcome(contracts.WorkerDeliveryStatus, `{"order_id":"ORD-1001","delivery_status":"DELAYED"}`),
		}, "invalid"},
		{"unknown worker id", []WorkerOutcome{
			succeededOutcome("mystery", `{"order_id":"ORD-1001","order_status":"SHIPPED"}`),
			succeededOutcome(contracts.WorkerPaymentStatus, `{"order_id":"ORD-1001","payment_status":"PAID"}`),
			succeededOutcome(contracts.WorkerDeliveryStatus, `{"order_id":"ORD-1001","delivery_status":"DELAYED"}`),
		}, "invalid"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := CanonicalizeOutcomes(tc.raw, "ORD-1001"); err == nil ||
				!strings.Contains(err.Error(), tc.frag) {
				t.Fatalf("expected error containing %q, got %v", tc.frag, err)
			}
		})
	}
}
