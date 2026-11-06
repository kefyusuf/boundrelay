package m4

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

func testStateBinding() StateBinding {
	return StateBinding{CaseID: "parallel-clean-complete", ExecutionMode: ModeParallel,
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
	// The digest covers every body field: any mutation moves it.
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
		t.Fatal("the step-1 snapshot must match the flushed document")
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

// TestStateStoreTerminalStatuses pins the failed/cancelled step shapes and
// the terminal status rule.
func TestStateStoreTerminalStatuses(t *testing.T) {
	store := completeStore(t, testTempDir(t))
	failureCode := contracts.FailureWorkerExecutionFailed
	if err := store.RecordStepTerminal(contracts.WorkerOrderDetails, WorkerOutcome{
		WorkerID: contracts.WorkerOrderDetails, Status: StatusFailed,
		FailureCode: &failureCode}); err != nil {
		t.Fatalf("record failure: %v", err)
	}
	document := store.State()
	if document.Steps[0].Status != StepStatusFailed || document.Steps[0].Output != nil ||
		document.Steps[0].FailureCode == nil {
		t.Fatalf("failed step: %+v", document.Steps[0])
	}
	if document.SequenceCursor != 1 {
		t.Fatalf("failures are recorded terminals: %d", document.SequenceCursor)
	}
	if err := store.MarkTerminal(RunStateFailed, ""); err == nil {
		t.Fatal("FAILED terminal requires ALL_WORKERS_FAILED")
	}
	if err := store.MarkTerminal(RunStateFailed, contracts.FailureAllWorkersFailed); err != nil {
		t.Fatalf("failed terminal: %v", err)
	}
	if store.State().Status != RunStateFailed {
		t.Fatalf("terminal status: %+v", store.State())
	}
	cancelled := completeStore(t, testTempDir(t))
	if err := cancelled.MarkRunning(contracts.WorkerPaymentStatus); err != nil {
		t.Fatalf("mark running: %v", err)
	}
	if err := cancelled.MarkCancelledFrom(contracts.WorkerDeliveryStatus); err != nil {
		t.Fatalf("cancel from: %v", err)
	}
	document = cancelled.State()
	// The RUNNING payment step is before the cancel boundary and stays
	// RUNNING; the pending delivery step becomes CANCELLED.
	if document.Steps[1].Status != StepStatusRunning || document.Steps[2].Status != StepStatusCancelled {
		t.Fatalf("cancelled steps: %+v %+v", document.Steps[1], document.Steps[2])
	}
	if err := cancelled.MarkTerminal(RunStateStatusCancelled, ""); err != nil {
		t.Fatalf("cancelled terminal: %v", err)
	}
}

// TestLoadRunStateFailClosed pins the fixed reason order of the fail-closed
// load: TRUNCATED -> UNKNOWN_VERSION -> SCHEMA_INVALID -> DIGEST_MISMATCH
// -> BINDING_MISMATCH.
func TestLoadRunStateFailClosed(t *testing.T) {
	root := testTempDir(t)
	store := completeStore(t, root)
	if err := store.RecordStepTerminal(contracts.WorkerOrderDetails,
		succeededOutcome(contracts.WorkerOrderDetails, `{"order_id":"ORD-1001","order_status":"SHIPPED"}`)); err != nil {
		t.Fatalf("record: %v", err)
	}
	statePath := store.StatePath()
	raw, err := os.ReadFile(statePath)
	if err != nil {
		t.Fatalf("read state: %v", err)
	}
	var document map[string]any
	if err := json.Unmarshal(raw, &document); err != nil {
		t.Fatalf("parse state: %v", err)
	}
	write := func(mutate func(map[string]any)) string {
		copy := map[string]any{}
		for key, value := range document {
			copy[key] = value
		}
		mutate(copy)
		content, err := json.Marshal(copy)
		if err != nil {
			t.Fatalf("marshal: %v", err)
		}
		path := filepath.Join(testTempDir(t), "state.json")
		if err := os.WriteFile(path, content, 0o644); err != nil {
			t.Fatalf("write: %v", err)
		}
		return path
	}
	truncated := filepath.Join(testTempDir(t), "truncated.json")
	if err := os.WriteFile(truncated, []byte(`{"state_schema_version":"1.0"`), 0o644); err != nil {
		t.Fatalf("write truncated: %v", err)
	}
	cases := []struct {
		name   string
		path   string
		reason StateLoadReason
	}{
		{"unreadable file", filepath.Join(root, "missing", "state.json"), ReasonTruncated},
		{"truncated json", truncated, ReasonTruncated},
		{"unknown version", write(func(d map[string]any) {
			d["state_schema_version"] = "9.9"
		}), ReasonUnknownVersion},
		{"schema invalid", write(func(d map[string]any) {
			d["unexpected_field"] = true
		}), ReasonSchemaInvalid},
		{"schema invalid status", write(func(d map[string]any) {
			d["status"] = "MAYBE"
		}), ReasonSchemaInvalid},
		{"digest mismatch", write(func(d map[string]any) {
			// A shape-valid mutation that breaks the digest, exactly like
			// the evaluator's UNPAID flip.
			steps := d["steps"].([]any)
			output := steps[0].(map[string]any)["output"].(map[string]any)
			output["order_status"] = "CANCELLED"
		}), ReasonDigestMismatch},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := loadRunStateDocument(tc.path, testStateBinding())
			var loadError *StateLoadError
			if !asLoadError(err, &loadError) || loadError.Reason != tc.reason {
				t.Fatalf("expected %s, got %v", tc.reason, err)
			}
		})
	}
	// Binding mismatch: a valid document for another case.
	binding := testStateBinding()
	binding.CaseID = "parallel-crash-resume"
	_, err = loadRunStateDocument(statePath, binding)
	var loadError *StateLoadError
	if !asLoadError(err, &loadError) || loadError.Reason != ReasonBindingMismatch {
		t.Fatalf("expected BINDING_MISMATCH, got %v", err)
	}
	// The honest document loads.
	loaded, err := loadRunStateDocument(statePath, testStateBinding())
	if err != nil {
		t.Fatalf("honest load: %v", err)
	}
	if loaded.RunID != store.RunID() || loaded.SequenceCursor != 1 {
		t.Fatalf("loaded document: %+v", loaded)
	}
}

// TestLoadRunStateVerifiesSnapshots pins the MISSING_SNAPSHOT reason: every
// recorded terminal's immutable checkpoint must exist and stay valid.
func TestLoadRunStateVerifiesSnapshots(t *testing.T) {
	root := testTempDir(t)
	store := completeStore(t, root)
	if err := store.RecordStepTerminal(contracts.WorkerOrderDetails,
		succeededOutcome(contracts.WorkerOrderDetails, `{"order_id":"ORD-1001","order_status":"SHIPPED"}`)); err != nil {
		t.Fatalf("record: %v", err)
	}
	if _, err := loadRunState(root, testStateBinding()); err != nil {
		t.Fatalf("honest load: %v", err)
	}
	snapshot := store.SnapshotPath(1)
	raw, err := os.ReadFile(snapshot)
	if err != nil {
		t.Fatalf("read snapshot: %v", err)
	}
	// A tampered snapshot fails the digest verification.
	if err := os.WriteFile(snapshot, []byte("{\"state_schema_version\":\"1.0\"}"), 0o644); err != nil {
		t.Fatalf("tamper snapshot: %v", err)
	}
	_, err = loadRunState(root, testStateBinding())
	var loadError *StateLoadError
	if !asLoadError(err, &loadError) || loadError.Reason != ReasonMissingSnapshot {
		t.Fatalf("expected MISSING_SNAPSHOT, got %v", err)
	}
	// A missing snapshot too.
	if err := os.Remove(snapshot); err != nil {
		t.Fatalf("remove snapshot: %v", err)
	}
	_, err = loadRunState(root, testStateBinding())
	if !asLoadError(err, &loadError) || loadError.Reason != ReasonMissingSnapshot {
		t.Fatalf("expected MISSING_SNAPSHOT, got %v", err)
	}
	_ = raw
}

// TestResumeStoreReAnchors pins the resume re-anchor: the loaded run id,
// binding, and recorded evidence survive; the status returns to RUNNING.
func TestResumeStoreReAnchors(t *testing.T) {
	root := testTempDir(t)
	store := completeStore(t, root)
	if err := store.RecordStepTerminal(contracts.WorkerOrderDetails,
		succeededOutcome(contracts.WorkerOrderDetails, `{"order_id":"ORD-1001","order_status":"SHIPPED"}`)); err != nil {
		t.Fatalf("record: %v", err)
	}
	loaded, err := loadRunState(root, testStateBinding())
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	resumed, err := ResumeStore(loaded.Document, loaded.RestoredFrom)
	if err != nil {
		t.Fatalf("resume store: %v", err)
	}
	document := resumed.State()
	if document.RunID != store.RunID() || document.Status != RunStateStatusRunning ||
		document.SequenceCursor != 1 || document.Steps[0].Status != StepStatusSucceeded {
		t.Fatalf("re-anchored document: %+v", document)
	}
	// The re-anchored store writes back under the same run directory.
	if resumed.StatePath() != store.StatePath() {
		t.Fatalf("state paths diverge: %s vs %s", resumed.StatePath(), store.StatePath())
	}
}

// TestLoadRunStateRequiresExactlyOneDocument pins the layout rule.
func TestLoadRunStateRequiresExactlyOneDocument(t *testing.T) {
	root := testTempDir(t)
	if _, err := loadRunState(root, testStateBinding()); err == nil {
		t.Fatal("an empty state root must fail closed")
	}
	first := completeStore(t, root)
	if err := first.RecordStepTerminal(contracts.WorkerOrderDetails,
		succeededOutcome(contracts.WorkerOrderDetails, `{"order_id":"ORD-1001","order_status":"SHIPPED"}`)); err != nil {
		t.Fatalf("record: %v", err)
	}
	// A second run document under the same root is a tooling error.
	second, err := CreateStore(root, testStateBinding(), append([]string(nil), contracts.CanonicalWorkerIDs...))
	if err != nil {
		t.Fatalf("second store: %v", err)
	}
	_, err = loadRunState(root, testStateBinding())
	if err == nil || !strings.Contains(err.Error(), "exactly one run state document") {
		t.Fatalf("two run documents must fail closed, got %v", err)
	}
	if second.RunID() == first.RunID() {
		t.Fatal("run ids must be unique")
	}
}

func asLoadError(err error, target **StateLoadError) bool {
	var loadError *StateLoadError
	if !errors.As(err, &loadError) {
		return false
	}
	*target = loadError
	return true
}
