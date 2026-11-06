package m5

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func openAudit(t *testing.T, stateDir string) *AuditWriter {
	t.Helper()
	writer, err := NewAuditWriter(stateDir)
	if err != nil {
		t.Fatalf("open audit: %v", err)
	}
	return writer
}

func auditLines(t *testing.T, writer *AuditWriter) []string {
	t.Helper()
	raw, err := os.ReadFile(writer.Path())
	if err != nil {
		t.Fatalf("read audit: %v", err)
	}
	return strings.Split(strings.TrimRight(string(raw), "\n"), "\n")
}

// TestAuditAppendsCanonicalRecords pins the audit shape: every record is one
// canonical-JSON line, appended in order, at the state-dir root.
func TestAuditAppendsCanonicalRecords(t *testing.T) {
	writer := openAudit(t, filepath.Join(testTempDir(t), "state"))
	approval := ApprovalAuditRecord{Kind: "approval", Operation: EffectOperation,
		OrderID: "ORD-1001", PayloadDigest: testPayloadDigest(t),
		Decision: DecisionGranted, Approver: "approver-primary"}
	if err := writer.Append(approval); err != nil {
		t.Fatalf("append approval: %v", err)
	}
	effect := EffectAuditRecord{Kind: "effect", Operation: EffectOperation,
		OrderID: "ORD-1001", IdempotencyKey: EffectKey(EffectPayloadOf("ORD-1001")),
		EffectStatus: EffectCompleted, Duplicate: true}
	if err := writer.Append(effect); err != nil {
		t.Fatalf("append effect: %v", err)
	}
	lines := auditLines(t, writer)
	if len(lines) != 2 {
		t.Fatalf("audit must hold two records, got %d", len(lines))
	}
	if !strings.Contains(lines[0], `"decision":"granted"`) ||
		!strings.Contains(lines[0], `"kind":"approval"`) {
		t.Fatalf("approval record: %s", lines[0])
	}
	if !strings.Contains(lines[1], `"kind":"effect"`) ||
		!strings.Contains(lines[1], `"duplicate":true`) {
		t.Fatalf("effect record: %s", lines[1])
	}
	if strings.Contains(lines[0], " ") || strings.Contains(lines[1], " ") {
		t.Fatal("audit records must be the compact canonical form")
	}
}

// TestAuditIsAppendOnlyAndNeverRead pins the audit contract: the writer
// appends and never reads back — earlier records survive every later append
// and every later run against the same state dir, whatever the runtime does
// with the ledger and the state document.
func TestAuditIsAppendOnlyAndNeverRead(t *testing.T) {
	root := testTempDir(t)
	writer := openAudit(t, root)
	seed := ApprovalAuditRecord{Kind: "approval", Operation: EffectOperation,
		OrderID: "ORD-1001", PayloadDigest: testPayloadDigest(t),
		Decision: DecisionRejected, Approver: "approver-primary"}
	if err := writer.Append(seed); err != nil {
		t.Fatalf("seed audit: %v", err)
	}
	before, err := os.ReadFile(writer.Path())
	if err != nil {
		t.Fatalf("read audit: %v", err)
	}
	// A full run over the same state dir must leave the audit prefix intact
	// (the rejected case appends its own approval record after the seed).
	scenario, fixtures := loadRepoScenario(t)
	if _, err := RunCase(context.Background(), RunOptions{CaseID: "approval-rejected-no-effect",
		TracePath: filepath.Join(testTempDir(t), "trace.jsonl"), StateDir: root,
		Scenario: scenario, Fixtures: fixtures}); err != nil {
		t.Fatalf("run: %v", err)
	}
	after, err := os.ReadFile(writer.Path())
	if err != nil {
		t.Fatalf("reread audit: %v", err)
	}
	if !strings.HasPrefix(string(after), string(before)) {
		t.Fatal("the audit trail must be append-only across runs")
	}
	if lines := strings.Count(string(after), "\n"); lines != 2 {
		t.Fatalf("the run must append exactly one record, got %d lines", lines)
	}
}

// TestAuditValidatesAgainstClosedSchema pins the closed audit schema: only
// the two record kinds with exactly their field sets are writable.
func TestAuditValidatesAgainstClosedSchema(t *testing.T) {
	writer := openAudit(t, filepath.Join(testTempDir(t), "state"))
	if err := writer.Append(map[string]any{"kind": "mystery"}); err == nil {
		t.Fatal("unknown kinds must be refused")
	}
	if err := writer.Append(map[string]any{"kind": "approval", "operation": "refund-only",
		"order_id": "ORD-1001", "payload_digest": testPayloadDigest(t),
		"decision": "granted", "approver": "approver-primary"}); err == nil {
		t.Fatal("wrong operation must be refused")
	}
	good := EffectAuditRecord{Kind: "effect", Operation: EffectOperation,
		OrderID: "ORD-1001", IdempotencyKey: EffectKey(EffectPayloadOf("ORD-1001")),
		EffectStatus: EffectUnprovable, Duplicate: false}
	if err := writer.Append(good); err != nil {
		t.Fatalf("EFFECT_UNPROVABLE is a legal audit status: %v", err)
	}
	if err := writer.Append(EffectAuditRecord{Kind: "effect", Operation: EffectOperation,
		OrderID: "ORD-1001", IdempotencyKey: "k",
		EffectStatus: "EFFECT_MISSING", Duplicate: false}); err == nil {
		t.Fatal("unknown effect_status must be refused")
	}
}
