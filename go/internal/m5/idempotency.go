package m5

import (
	"errors"
	"fmt"
)

// EffectPayload is the side-effect payload the effect pipeline submits: the
// deterministic cancel-and-refund for the run's order
// (order-closure-effect.schema.json $defs/effectPayload).
type EffectPayload struct {
	Operation         string `json:"operation"`
	OrderID           string `json:"order_id"`
	RefundAmountCents int    `json:"refund_amount_cents"`
	Currency          string `json:"currency"`
}

// EffectPayloadOf builds the canonical payload for an order id.
func EffectPayloadOf(orderID string) EffectPayload {
	return EffectPayload{Operation: EffectOperation, OrderID: orderID,
		RefundAmountCents: RefundAmountCents, Currency: RefundCurrency}
}

// validateEffectPayload mirrors the closed effectPayload schema: the fixed
// operation, a well-formed order id, the fixed amount, and the fixed
// currency. Anything else is an invalid payload (EFFECT_REJECTED).
func validateEffectPayload(payload EffectPayload) error {
	switch {
	case payload.Operation != EffectOperation:
		return fmt.Errorf("operation must be %q", EffectOperation)
	case !orderIDPattern.MatchString(payload.OrderID):
		return errors.New("order_id is invalid")
	case payload.RefundAmountCents != RefundAmountCents:
		return fmt.Errorf("refund_amount_cents must be %d", RefundAmountCents)
	case payload.Currency != RefundCurrency:
		return fmt.Errorf("currency must be %q", RefundCurrency)
	}
	return nil
}

// EffectDigest is the SHA-256 hex digest of the payload's canonical JSON —
// the digest bound into the approval record, the submit marker, and the
// ledger record.
func EffectDigest(payload EffectPayload) (string, error) {
	body, err := canonicalJSON(payload)
	if err != nil {
		return "", fmt.Errorf("m5: canonical effect payload: %w", err)
	}
	return stateDigest(body), nil
}

// EffectKey is the deterministic idempotency key: <operation>:<order_id>.
func EffectKey(payload EffectPayload) string {
	return fmt.Sprintf("%s:%s", payload.Operation, payload.OrderID)
}
