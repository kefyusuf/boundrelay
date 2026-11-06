package m5

import (
	"errors"
	"testing"
)

// TestApprovalGateBindsPayloadDigest pins the binding: the gate's record
// binds (operation, order_id, payload_digest) with the fixture decision and
// approver verbatim; the digest is the payload's canonical digest.
func TestApprovalGateBindsPayloadDigest(t *testing.T) {
	gate := NewApprovalGate(ApprovalMetadata{Decision: DecisionGranted, Approver: "approver-primary"})
	payload := EffectPayloadOf("ORD-1001")
	decision, record, err := gate.Decide(payload)
	if err != nil {
		t.Fatalf("decide: %v", err)
	}
	if decision != DecisionGranted {
		t.Fatalf("decision: %s", decision)
	}
	if record.Operation != EffectOperation || record.OrderID != "ORD-1001" ||
		record.PayloadDigest != testPayloadDigest(t) ||
		record.Decision != DecisionGranted || record.Approver != "approver-primary" {
		t.Fatalf("approval record: %+v", record)
	}
	// A different payload binds a different digest: the decision cannot be
	// replayed across payloads.
	other := EffectPayloadOf("ORD-2002")
	_, otherRecord, err := gate.Decide(other)
	if err != nil {
		t.Fatalf("decide other: %v", err)
	}
	if otherRecord.PayloadDigest == record.PayloadDigest || otherRecord.OrderID != "ORD-2002" {
		t.Fatalf("binding must follow the payload: %+v", otherRecord)
	}
}

// TestRequireApprovalEnforcesBinding pins the tooling guard: a record that
// does not bind the exact payload is a binding error (not a rejection), and
// a bound record without the granted decision is not-granted.
func TestRequireApprovalEnforcesBinding(t *testing.T) {
	payload := EffectPayloadOf("ORD-1001")
	gate := NewApprovalGate(ApprovalMetadata{Decision: DecisionGranted, Approver: "approver-primary"})
	_, record, err := gate.Decide(payload)
	if err != nil {
		t.Fatalf("decide: %v", err)
	}
	if err := RequireApproval(record, payload); err != nil {
		t.Fatalf("granted bound record must pass: %v", err)
	}
	tampered := record
	tampered.PayloadDigest = testPayloadDigest(t)[:63] + "0"
	if err := RequireApproval(tampered, payload); !errors.Is(err, ErrApprovalBinding) {
		t.Fatalf("digest drift must be a binding error, got %v", err)
	}
	tampered = record
	tampered.OrderID = "ORD-2002"
	if err := RequireApproval(tampered, payload); !errors.Is(err, ErrApprovalBinding) {
		t.Fatalf("order drift must be a binding error, got %v", err)
	}
	tampered = record
	tampered.Operation = "refund-only"
	if err := RequireApproval(tampered, payload); !errors.Is(err, ErrApprovalBinding) {
		t.Fatalf("operation drift must be a binding error, got %v", err)
	}
	rejectedGate := NewApprovalGate(ApprovalMetadata{Decision: DecisionRejected, Approver: "approver-primary"})
	_, rejectedRecord, err := rejectedGate.Decide(payload)
	if err != nil {
		t.Fatalf("decide: %v", err)
	}
	if err := RequireApproval(rejectedRecord, payload); !errors.Is(err, ErrApprovalNotGranted) {
		t.Fatalf("a rejected record must be not-granted, got %v", err)
	}
}
