package m5

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

func testStateBinding() StateBinding {
	return StateBinding{CaseID: "approval-granted-effect-once", ExecutionMode: ModeParallel,
		RequestedOrderID: "ORD-1001", ConcurrencyLimit: 2}
}

func succeededOutcome(workerID string, output string) WorkerOutcome {
	return WorkerOutcome{WorkerID: workerID, Status: StatusSucceeded,
		Output: json.RawMessage(output)}
}

func completeStore(t *testing.T, root string) *StateStore {
	t.Helper()
	store, err := CreateStore(root, testStateBinding(), append([]string(nil), contracts.CanonicalWorkerIDs...))
	if err != nil {
		t.Fatalf("create store: %v", err)
	}
	return store
}

// recordAllSteps records three succeeded terminals so the store reaches
// cursor 3 with a snapshot per step.
func recordAllSteps(t *testing.T, store *StateStore) {
	t.Helper()
	outputs := map[string]string{
		contracts.WorkerOrderDetails:   `{"order_id":"ORD-1001","order_status":"SHIPPED"}`,
		contracts.WorkerPaymentStatus:  `{"order_id":"ORD-1001","payment_status":"PAID"}`,
		contracts.WorkerDeliveryStatus: `{"order_id":"ORD-1001","delivery_status":"DELAYED"}`,
	}
	for _, id := range contracts.CanonicalWorkerIDs {
		if err := store.RecordStepTerminal(id, succeededOutcome(id, outputs[id])); err != nil {
			t.Fatalf("record %s: %v", id, err)
		}
	}
}

// TestStateStoreDigestAndCursor pins the document shape: the Ruling-2
// cursor counts recorded terminals, the digest is the SHA-256 of the
// canonical body without the digest field, and every step terminal
// snapshots the document.
func TestStateStoreDigestAndCursor(t *testing.T) {
	store := completeStore(t, testTempDir(t))
	document := store.State()
	if document.SequenceCursor != 0 || document.Status != RunStateStatusRunning {
		t.Fatalf("fresh document: %+v", document)
	}
	if document.Steps[2].Status != StepStatusPending || document.Steps[2].Output != nil {
		t.Fatalf("pending step: %+v", document.Steps[2])
	}
	if document.SubmitMarker != nil || document.Effect != nil {
		t.Fatalf("fresh document carries no effect fields: %+v", document)
	}
	if err := store.MarkRunning(contracts.WorkerPaymentStatus); err != nil {
		t.Fatalf("mark running: %v", err)
	}
	if store.State().Steps[1].Status != StepStatusRunning {
		t.Fatalf("running step: %+v", store.State().Steps[1])
	}
	if err := store.RecordStepTerminal(contracts.WorkerPaymentStatus,
		succeededOutcome(contracts.WorkerPaymentStatus, `{"order_id":"ORD-1001","payment_status":"PAID"}`)); err != nil {
		t.Fatalf("record terminal: %v", err)
	}
	document = store.State()
	if document.SequenceCursor != 1 {
		t.Fatalf("cursor must count recorded terminals, got %d", document.SequenceCursor)
	}
	body, err := canonicalStateBody(document)
	if err != nil {
		t.Fatalf("canonical body: %v", err)
	}
	if document.Digest != stateDigest(body) {
		t.Fatalf("digest mismatch: %s vs %s", document.Digest, stateDigest(body))
	}
	// The digest covers every body field — including the effect fields —
	// so any mutation moves it.
	document.ConcurrencyLimit = 1
	otherBody, _ := canonicalStateBody(document)
	if document.Digest == stateDigest(otherBody) {
		t.Fatal("digest must cover the body")
	}
	// The step terminal snapshot exists (position-based step-<index+1>)
	// and matches the flushed document.
	snapshotRaw, err := os.ReadFile(store.SnapshotPath(2))
	if err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	stateRaw, err := os.ReadFile(store.StatePath())
	if err != nil {
		t.Fatalf("state: %v", err)
	}
	if string(snapshotRaw) != string(stateRaw) {
		t.Fatal("the step-2 snapshot must match the flushed document")
	}
	if _, err := os.Stat(store.SnapshotPath(1)); !os.IsNotExist(err) {
		t.Fatal("no snapshot without the first canonical terminal")
	}
	// Atomic writes leave no temporary files behind.
	entries, err := os.ReadDir(filepath.Dir(store.StatePath()))
	if err != nil {
		t.Fatalf("read run dir: %v", err)
	}
	for _, entry := range entries {
		if strings.HasSuffix(entry.Name(), ".tmp") {
			t.Fatalf("temporary write artifact left behind: %s", entry.Name())
		}
	}
}

// TestStateStoreSubmitMarkerAndEffect pins the M5 effect fields: the
// write-ahead marker and the settled effect of record live in the document,
// are digest-protected, and round-trip through the closed schema.
func TestStateStoreSubmitMarkerAndEffect(t *testing.T) {
	store := completeStore(t, testTempDir(t))
	recordAllSteps(t, store)
	if err := store.MarkSubmitted(EffectKey(EffectPayloadOf("ORD-1001")), testPayloadDigest(t)); err != nil {
		t.Fatalf("mark submitted: %v", err)
	}
	marker := store.State().SubmitMarker
	if marker == nil || marker.Key != "cancel-and-refund:ORD-1001" ||
		marker.PayloadDigest != testPayloadDigest(t) {
		t.Fatalf("submit marker: %+v", marker)
	}
	effect := EffectRecord{Key: marker.Key, PayloadDigest: marker.PayloadDigest,
		Status: EffectCompleted, Outcome: &RefundOutcome{RefundID: RefundID, RefundedAt: RefundedAt}}
	if err := store.RecordEffectOutcome(effect); err != nil {
		t.Fatalf("record effect: %v", err)
	}
	reloaded, err := loadRunStateDocument(store.StatePath(), testStateBinding())
	if err != nil {
		t.Fatalf("reload: %v", err)
	}
	if reloaded.SubmitMarker == nil || reloaded.Effect == nil ||
		reloaded.Effect.Status != EffectCompleted || reloaded.Effect.Outcome == nil ||
		reloaded.Effect.Outcome.RefundID != RefundID {
		t.Fatalf("effect fields must round-trip: %+v", reloaded)
	}
	// An invalid effect record is refused by the closed document.
	broken := store.State()
	broken.Effect.Status = "EFFECT_UNPROVABLE"
	if err := validateRunStateDocument(broken); err == nil {
		t.Fatal("effect status outside the closed enum must be refused")
	}
}

// TestLoadRunStateFailsClosed walks the fixed load-failure order: the
// unreadable/non-JSON document is TRUNCATED, a wrong version is
// UNKNOWN_VERSION, a schema violation is SCHEMA_INVALID, a body mutation is
// DIGEST_MISMATCH, a foreign case identity is BINDING_MISMATCH, and a
// recorded terminal without its checkpoint is MISSING_SNAPSHOT.
func TestLoadRunStateFailsClosed(t *testing.T) {
	root := testTempDir(t)
	store := completeStore(t, filepath.Join(root, "state"))
	recordAllSteps(t, store)
	raw, err := os.ReadFile(store.StatePath())
	if err != nil {
		t.Fatalf("read state: %v", err)
	}

	if _, err := loadRunStateDocument(filepath.Join(root, "missing.json"), testStateBinding()); err == nil ||
		err.(*StateLoadError).Reason != ReasonTruncated {
		t.Fatalf("missing document must be TRUNCATED, got %v", err)
	}
	if _, err := loadRunStateDocument(filepath.Join(root, "state"), testStateBinding()); err == nil ||
		err.(*StateLoadError).Reason != ReasonTruncated {
		t.Fatalf("a directory path must be TRUNCATED, got %v", err)
	}

	writeState := func(content string) string {
		t.Helper()
		path := filepath.Join(root, "case.json")
		if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
			t.Fatalf("write state: %v", err)
		}
		return path
	}
	if _, err := loadRunStateDocument(writeState("not json at all"), testStateBinding()); err == nil ||
		err.(*StateLoadError).Reason != ReasonTruncated {
		t.Fatalf("non-JSON must be TRUNCATED, got %v", err)
	}
	if _, err := loadRunStateDocument(writeState(`{"state_schema_version":"9.9"}`), testStateBinding()); err == nil ||
		err.(*StateLoadError).Reason != ReasonUnknownVersion {
		t.Fatalf("unknown version must be UNKNOWN_VERSION, got %v", err)
	}

	var document map[string]any
	if err := json.Unmarshal(raw, &document); err != nil {
		t.Fatalf("parse state: %v", err)
	}
	document["execution_mode"] = "sequential"
	mutated, _ := json.Marshal(document)
	if _, err := loadRunStateDocument(writeState(string(mutated)), testStateBinding()); err == nil ||
		err.(*StateLoadError).Reason != ReasonDigestMismatch {
		t.Fatalf("body mutation must be DIGEST_MISMATCH, got %v", err)
	}

	document = map[string]any{}
	if err := json.Unmarshal(raw, &document); err != nil {
		t.Fatalf("parse state: %v", err)
	}
	document["run_id"] = ""
	mutated, _ = json.Marshal(document)
	if _, err := loadRunStateDocument(writeState(string(mutated)), testStateBinding()); err == nil ||
		err.(*StateLoadError).Reason != ReasonSchemaInvalid {
		t.Fatalf("schema violation must be SCHEMA_INVALID, got %v", err)
	}

	foreign := testStateBinding()
	foreign.CaseID = "approval-rejected-no-effect"
	if _, err := loadRunStateDocument(writeState(string(raw)), foreign); err == nil ||
		err.(*StateLoadError).Reason != ReasonBindingMismatch {
		t.Fatalf("foreign binding must be BINDING_MISMATCH, got %v", err)
	}

	// A recorded terminal whose checkpoint vanished is MISSING_SNAPSHOT.
	pruned := filepath.Join(root, "pruned")
	if err := os.MkdirAll(filepath.Join(pruned, store.RunID()), 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(pruned, store.RunID(), "state.json"), raw, 0o644); err != nil {
		t.Fatalf("write state: %v", err)
	}
	if _, err := loadRunState(pruned, testStateBinding()); err == nil ||
		err.(*StateLoadError).Reason != ReasonMissingSnapshot {
		t.Fatalf("missing checkpoint must be MISSING_SNAPSHOT, got %v", err)
	}

	// The honest layout loads with every snapshot verified.
	if _, err := loadRunState(filepath.Join(root, "state"), testStateBinding()); err != nil {
		t.Fatalf("honest state must load: %v", err)
	}
}

// TestLoadRunStateRejectsAmbiguousLayout pins the discovery rule: exactly
// one run-state document under the state root (flat or in one run
// directory); two run directories are a tooling error.
func TestLoadRunStateRejectsAmbiguousLayout(t *testing.T) {
	root := testTempDir(t)
	first := completeStore(t, root)
	second := completeStore(t, root)
	for _, store := range []*StateStore{first, second} {
		recordAllSteps(t, store)
	}
	if _, err := loadRunState(root, testStateBinding()); err == nil ||
		!strings.Contains(err.Error(), "exactly one") {
		t.Fatalf("two run documents must fail closed, got %v", err)
	}
}

// TestRunStateTerminalFailureCodes pins the terminal guard: FAILED needs
// ALL_WORKERS_FAILED or APPROVAL_REJECTED; UNKNOWN is a legal terminal for
// the sink-unavailable resolution.
func TestRunStateTerminalFailureCodes(t *testing.T) {
	store := completeStore(t, testTempDir(t))
	if err := store.MarkTerminal(RunStateFailed, "SOME_OTHER_CODE"); err == nil {
		t.Fatal("FAILED with an undeclared code must be refused")
	}
	if err := store.MarkTerminal(RunStateFailed, contracts.FailureAllWorkersFailed); err != nil {
		t.Fatalf("ALL_WORKERS_FAILED terminal: %v", err)
	}
	if err := store.MarkTerminal(RunStateUnknown, ""); err != nil {
		t.Fatalf("UNKNOWN terminal: %v", err)
	}
	if store.State().Status != RunStateUnknown {
		t.Fatalf("terminal status: %+v", store.State())
	}
}
