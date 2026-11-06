package m5

import (
	"crypto/sha256"
	"encoding/hex"
	"testing"
)

// testPayloadDigest is the canonical payload digest for the ORD-1001 effect
// payload (the digest the TS/Python runtimes derive from the canonical JSON).
func testPayloadDigest(t *testing.T) string {
	t.Helper()
	digest, err := EffectDigest(EffectPayloadOf("ORD-1001"))
	if err != nil {
		t.Fatalf("effect digest: %v", err)
	}
	return digest
}

// TestEffectKeyIsDeterministic pins the idempotency key grammar:
// <operation>:<order_id>, derived from the payload alone.
func TestEffectKeyIsDeterministic(t *testing.T) {
	payload := EffectPayloadOf("ORD-1001")
	if payload.Operation != EffectOperation || payload.OrderID != "ORD-1001" ||
		payload.RefundAmountCents != 4200 || payload.Currency != "EUR" {
		t.Fatalf("payload: %+v", payload)
	}
	if EffectKey(payload) != "cancel-and-refund:ORD-1001" {
		t.Fatalf("effect key: %s", EffectKey(payload))
	}
	if EffectKey(payload) != EffectKey(EffectPayloadOf("ORD-1001")) {
		t.Fatal("the key must be deterministic")
	}
}

// TestEffectDigestIsCanonicalSHA256 pins the digest: SHA-256 over the
// canonical (sorted-key, compact) JSON of the payload, hex-encoded.
func TestEffectDigestIsCanonicalSHA256(t *testing.T) {
	payload := EffectPayloadOf("ORD-1001")
	digest, err := EffectDigest(payload)
	if err != nil {
		t.Fatalf("effect digest: %v", err)
	}
	canonical, err := canonicalJSON(payload)
	if err != nil {
		t.Fatalf("canonical payload: %v", err)
	}
	if canonical != `{"currency":"EUR","operation":"cancel-and-refund","order_id":"ORD-1001","refund_amount_cents":4200}` {
		t.Fatalf("canonical payload is not the sorted-key compact form: %s", canonical)
	}
	sum := sha256.Sum256([]byte(canonical))
	if digest != hex.EncodeToString(sum[:]) {
		t.Fatalf("digest must be the canonical SHA-256: %s", digest)
	}
	if !digestPattern.MatchString(digest) {
		t.Fatalf("digest must be 64 hex chars: %s", digest)
	}
}

// TestValidateEffectPayloadRejectsInvalid pins the closed payload schema:
// any drift from the fixed operation/order/amount/currency is an invalid
// payload, which the ledger records as EFFECT_REJECTED.
func TestValidateEffectPayloadRejectsInvalid(t *testing.T) {
	cases := map[string]EffectPayload{
		"wrong operation": {Operation: "refund-only", OrderID: "ORD-1001", RefundAmountCents: 4200, Currency: "EUR"},
		"wrong amount":    {Operation: EffectOperation, OrderID: "ORD-1001", RefundAmountCents: 1, Currency: "EUR"},
		"wrong currency":  {Operation: EffectOperation, OrderID: "ORD-1001", RefundAmountCents: 4200, Currency: "USD"},
		"malformed order": {Operation: EffectOperation, OrderID: "ORD-1", RefundAmountCents: 4200, Currency: "EUR"},
		"empty order":     {Operation: EffectOperation, OrderID: "", RefundAmountCents: 4200, Currency: "EUR"},
	}
	for name, payload := range cases {
		t.Run(name, func(t *testing.T) {
			if err := validateEffectPayload(payload); err == nil {
				t.Fatalf("invalid payload accepted: %+v", payload)
			}
		})
	}
	if err := validateEffectPayload(EffectPayloadOf("ORD-1001")); err != nil {
		t.Fatalf("canonical payload must validate: %v", err)
	}
}

// TestCrashSignalIdentity pins the crash sentinel surfaces its boundary.
func TestCrashSignalIdentity(t *testing.T) {
	signal := &CrashSignal{Boundary: CrashBoundaryInSubmitWindow}
	if signal.Boundary != CrashBoundaryInSubmitWindow {
		t.Fatalf("boundary: %s", signal.Boundary)
	}
	if CrashBoundaryBeforeSubmit != "before-submit" ||
		CrashBoundaryInSubmitWindow != "in-submit-window" {
		t.Fatalf("boundary names: %s / %s", CrashBoundaryBeforeSubmit, CrashBoundaryInSubmitWindow)
	}
	if signal.Error() == "" {
		t.Fatal("the crash signal must diagnose")
	}
}
