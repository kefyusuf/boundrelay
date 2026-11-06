package m5

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func openLedger(t *testing.T, stateDir string) *EffectLedger {
	t.Helper()
	ledger, err := NewEffectLedger(stateDir)
	if err != nil {
		t.Fatalf("open ledger: %v", err)
	}
	return ledger
}

func ledgerRecordCount(t *testing.T, ledger *EffectLedger) int {
	t.Helper()
	records, err := ledger.Records()
	if err != nil {
		t.Fatalf("read ledger: %v", err)
	}
	return len(records)
}

// TestLedgerSubmitRecordsDeterministicRefund pins the first submit: a valid
// payload lands EFFECT_COMPLETED with the deterministic refund outcome
// RFL-1001 at 2026-11-02T00:00:00Z, written once at the state-dir root.
func TestLedgerSubmitRecordsDeterministicRefund(t *testing.T) {
	ledger := openLedger(t, filepath.Join(testTempDir(t), "state"))
	payload := EffectPayloadOf("ORD-1001")
	key := EffectKey(payload)
	digest := testPayloadDigest(t)
	submitted, err := ledger.submit(key, digest, payload)
	if err != nil {
		t.Fatalf("submit: %v", err)
	}
	if submitted.Status != EffectCompleted || submitted.Duplicate ||
		submitted.Outcome == nil || submitted.Outcome.RefundID != RefundID ||
		submitted.Outcome.RefundedAt != RefundedAt || submitted.Reason != nil {
		t.Fatalf("submit result: %+v", submitted)
	}
	if ledgerRecordCount(t, ledger) != 1 {
		t.Fatal("the submit must record exactly one record")
	}
	// The record is the closed schema shape on disk.
	records, err := ledger.Records()
	if err != nil {
		t.Fatalf("records: %v", err)
	}
	if records[0].Key != key || records[0].PayloadDigest != digest ||
		records[0].Effect.Status != EffectCompleted || records[0].Effect.Reason != nil {
		t.Fatalf("record: %+v", records[0])
	}
}

// TestLedgerSubmitAdoptsRecordedKeyWithZeroWrites pins once-per-key: a
// second submit for the recorded key adopts the recorded outcome
// (duplicate=true) and performs zero new writes — the ledger file is
// byte-identical after the adoption.
func TestLedgerSubmitAdoptsRecordedKeyWithZeroWrites(t *testing.T) {
	ledger := openLedger(t, filepath.Join(testTempDir(t), "state"))
	payload := EffectPayloadOf("ORD-1001")
	key := EffectKey(payload)
	digest := testPayloadDigest(t)
	if _, err := ledger.submit(key, digest, payload); err != nil {
		t.Fatalf("first submit: %v", err)
	}
	raw, err := os.ReadFile(ledger.Path())
	if err != nil {
		t.Fatalf("read ledger: %v", err)
	}
	submitted, err := ledger.submit(key, "a-different-digest-would-not-matter", payload)
	if err != nil {
		t.Fatalf("second submit: %v", err)
	}
	if !submitted.Duplicate || submitted.Status != EffectCompleted ||
		submitted.Outcome == nil || submitted.Outcome.RefundID != RefundID {
		t.Fatalf("adoption result: %+v", submitted)
	}
	after, err := os.ReadFile(ledger.Path())
	if err != nil {
		t.Fatalf("reread ledger: %v", err)
	}
	if string(raw) != string(after) {
		t.Fatal("an adoption must perform zero ledger writes")
	}
	if ledgerRecordCount(t, ledger) != 1 {
		t.Fatal("once-per-key: the ledger must hold exactly one record")
	}
}

// TestLedgerSubmitInvalidPayloadIsRejected pins the invalid-payload path: an
// out-of-schema payload is recorded EFFECT_REJECTED with the
// INVALID_PAYLOAD reason and no outcome.
func TestLedgerSubmitInvalidPayloadIsRejected(t *testing.T) {
	ledger := openLedger(t, filepath.Join(testTempDir(t), "state"))
	payload := EffectPayload{Operation: EffectOperation, OrderID: "ORD-1001",
		RefundAmountCents: 1, Currency: "EUR"}
	key := EffectKey(payload)
	submitted, err := ledger.submit(key, testPayloadDigest(t), payload)
	if err != nil {
		t.Fatalf("submit: %v", err)
	}
	if submitted.Status != EffectRejected || submitted.Outcome != nil ||
		submitted.Reason == nil || *submitted.Reason != "INVALID_PAYLOAD" || submitted.Duplicate {
		t.Fatalf("rejected submit result: %+v", submitted)
	}
	// The rejection is durable and subsequent submits adopt it.
	again, err := ledger.submit(key, testPayloadDigest(t), payload)
	if err != nil || !again.Duplicate || again.Status != EffectRejected {
		t.Fatalf("adopted rejection: %+v (err %v)", again, err)
	}
	if ledgerRecordCount(t, ledger) != 1 {
		t.Fatal("once-per-key applies to rejections too")
	}
}

// TestLedgerLookupProvenance pins the recovery decision point: lookup
// reports the recorded effect for a landed key and nil for an absent one.
func TestLedgerLookupProvenance(t *testing.T) {
	ledger := openLedger(t, filepath.Join(testTempDir(t), "state"))
	key := EffectKey(EffectPayloadOf("ORD-1001"))
	found, err := ledger.lookup(key)
	if err != nil || found != nil {
		t.Fatalf("absent key lookup: %v %+v", err, found)
	}
	if _, err := ledger.submit(key, testPayloadDigest(t), EffectPayloadOf("ORD-1001")); err != nil {
		t.Fatalf("submit: %v", err)
	}
	found, err = ledger.lookup(key)
	if err != nil || found == nil || found.Status != EffectCompleted ||
		found.Outcome == nil || found.Outcome.RefundID != RefundID {
		t.Fatalf("landed key lookup: %v %+v", err, found)
	}
}

// TestLedgerFailsClosedOnInvalidContent pins the fail-closed reads: a
// non-JSON ledger file and a record outside the closed schema both refuse
// every subsequent submit.
func TestLedgerFailsClosedOnInvalidContent(t *testing.T) {
	root := testTempDir(t)
	stateDir := filepath.Join(root, "state")
	ledger := openLedger(t, stateDir)
	if err := os.WriteFile(ledger.Path(), []byte("not json"), 0o644); err != nil {
		t.Fatalf("write ledger: %v", err)
	}
	if _, err := ledger.submit(EffectKey(EffectPayloadOf("ORD-1001")), testPayloadDigest(t),
		EffectPayloadOf("ORD-1001")); err == nil || !strings.Contains(err.Error(), "not valid JSON") {
		t.Fatalf("corrupt ledger must refuse submits, got %v", err)
	}
	broken := `{"records":[{"key":"cancel-and-refund:ORD-1001","payload_digest":"` +
		testPayloadDigest(t) + `","effect":{"status":"EFFECT_COMPLETED","outcome":null}}]}`
	if err := os.WriteFile(ledger.Path(), []byte(broken), 0o644); err != nil {
		t.Fatalf("write ledger: %v", err)
	}
	if _, err := ledger.lookup(EffectKey(EffectPayloadOf("ORD-1001"))); err == nil ||
		!strings.Contains(err.Error(), "closed schema") {
		t.Fatalf("schema-invalid record must refuse lookups, got %v", err)
	}
}
