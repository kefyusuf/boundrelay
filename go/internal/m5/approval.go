package m5

import (
	"fmt"
)

// ApprovalRecord is the gate's decision of record: the effect binding
// (operation, order_id, payload_digest) plus the fixture decision and
// approver. The audit writer records it verbatim under kind "approval".
type ApprovalRecord struct {
	Operation     string `json:"operation"`
	OrderID       string `json:"order_id"`
	PayloadDigest string `json:"payload_digest"`
	Decision      string `json:"decision"`
	Approver      string `json:"approver"`
}

// ApprovalGate decides the effect approval from the case's fixture metadata,
// binding the decision to (operation, order_id, payload_digest).
type ApprovalGate struct {
	metadata ApprovalMetadata
}

// NewApprovalGate binds the gate to the case's fixture approval block.
func NewApprovalGate(metadata ApprovalMetadata) ApprovalGate {
	return ApprovalGate{metadata: metadata}
}

// Decide returns the fixture decision and the binding record for the
// payload. The digest binds the decision to the exact payload bytes.
func (g ApprovalGate) Decide(payload EffectPayload) (string, ApprovalRecord, error) {
	digest, err := EffectDigest(payload)
	if err != nil {
		return "", ApprovalRecord{}, err
	}
	record := ApprovalRecord{Operation: payload.Operation, OrderID: payload.OrderID,
		PayloadDigest: digest, Decision: g.metadata.Decision, Approver: g.metadata.Approver}
	return g.metadata.Decision, record, nil
}

// RequireApproval mirrors the TS/Py require_approval: the record must bind
// the exact payload (operation, order_id, payload_digest) and carry the
// granted decision. Any mismatch is a tooling error, not a rejection.
func RequireApproval(record ApprovalRecord, payload EffectPayload) error {
	digest, err := EffectDigest(payload)
	if err != nil {
		return err
	}
	if record.Operation != payload.Operation || record.OrderID != payload.OrderID ||
		record.PayloadDigest != digest {
		return fmt.Errorf("%w: (operation, order_id, payload_digest)", ErrApprovalBinding)
	}
	if record.Decision != DecisionGranted {
		return ErrApprovalNotGranted
	}
	return nil
}
