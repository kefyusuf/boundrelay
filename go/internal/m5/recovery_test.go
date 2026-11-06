package m5

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// crashFreshRun executes a case's fresh phase with the panic-based crash
// control, returning the state dir with the crashed run's evidence on disk.
func crashFreshRun(t *testing.T, caseKey string) (string, *Scenario, map[string]WorkerInstructions) {
	t.Helper()
	scenario, fixtures := loadRepoScenario(t)
	stateDir := filepath.Join(testTempDir(t), "state")
	_, err := RunCase(context.Background(), RunOptions{
		CaseID: caseKey, TracePath: filepath.Join(testTempDir(t), "fresh.jsonl"),
		StateDir: stateDir, Scenario: scenario, Fixtures: fixtures,
		OnCrash: crashProbe()})
	var signal *CrashSignal
	if !errors.As(err, &signal) {
		t.Fatalf("fresh crash phase: %v", err)
	}
	return stateDir, scenario, fixtures
}

func crashProbe() func() {
	return func() {
		panic(&CrashSignal{})
	}
}

// seededMarkerRun hand-crafts the post-crash evidence: three recorded
// terminals, the write-ahead submit marker, no effect of record — as if the
// process died between the marker and the ledger submit.
func seededMarkerRun(t *testing.T, root string) (string, *EffectLedger, *AuditWriter) {
	t.Helper()
	stateDir := filepath.Join(root, "state")
	store := completeStore(t, stateDir)
	recordAllSteps(t, store)
	payload := EffectPayloadOf("ORD-1001")
	if err := store.MarkSubmitted(EffectKey(payload), testPayloadDigest(t)); err != nil {
		t.Fatalf("mark submitted: %v", err)
	}
	ledger, err := NewEffectLedger(stateDir)
	if err != nil {
		t.Fatalf("ledger: %v", err)
	}
	audit, err := NewAuditWriter(stateDir)
	if err != nil {
		t.Fatalf("audit: %v", err)
	}
	return stateDir, ledger, audit
}

// seededRunDocument loads the seeded run's document from disk.
func seededRunDocument(t *testing.T, stateDir string) RunStateDocument {
	t.Helper()
	document, err := loadRunStateDocument(filepath.Join(stateDir, runDirID(t, stateDir), "state.json"),
		testStateBinding())
	if err != nil {
		t.Fatalf("load run document: %v", err)
	}
	return document
}

// runDirID reads the single run directory id under the state root.
func runDirID(t *testing.T, stateDir string) string {
	t.Helper()
	entries, err := os.ReadDir(stateDir)
	if err != nil {
		t.Fatalf("read state root: %v", err)
	}
	for _, entry := range entries {
		if fileExists(filepath.Join(stateDir, entry.Name(), "state.json")) {
			return entry.Name()
		}
	}
	t.Fatalf("no run directory under %s", stateDir)
	return ""
}

// rewriteRunState replaces the run document on disk with a re-sealed copy.
func rewriteRunState(t *testing.T, stateDir string, document RunStateDocument) {
	t.Helper()
	body, err := canonicalStateBody(document)
	if err != nil {
		t.Fatalf("canonical body: %v", err)
	}
	document.Digest = stateDigest(body)
	content, err := canonicalJSON(document)
	if err != nil {
		t.Fatalf("canonical document: %v", err)
	}
	if err := os.WriteFile(filepath.Join(stateDir, document.RunID, "state.json"), []byte(content), 0o644); err != nil {
		t.Fatalf("write state: %v", err)
	}
}

// TestResumeAdoptsLandedEffectWithZeroSubmits pins the recovery decision:
// a submit marker whose key already landed in the ledger is adopted —
// reconciled=true, the ledger record count is unchanged (zero new submits),
// and the run closes SUCCEEDED.
func TestResumeAdoptsLandedEffectWithZeroSubmits(t *testing.T) {
	stateDir, ledger, audit := seededMarkerRun(t, testTempDir(t))
	payload := EffectPayloadOf("ORD-1001")
	key := EffectKey(payload)
	// The crashed submit landed before the process died.
	if _, err := ledger.submit(key, testPayloadDigest(t), payload); err != nil {
		t.Fatalf("seed ledger: %v", err)
	}
	before := ledgerRecordCount(t, ledger)
	result, err := ResumeRun(RecoveryOptions{StateRoot: stateDir, Binding: testStateBinding(),
		Ledger: ledger, Audit: audit})
	if err != nil {
		t.Fatalf("resume: %v", err)
	}
	if result.Status != RunStateSucceeded || !result.Reconciled ||
		result.Effect == nil || result.Effect.Key != key ||
		result.Effect.Status != EffectCompleted || result.Effect.Duplicate {
		t.Fatalf("adopted recovery: %+v", result)
	}
	if len(result.Reads) != 3 {
		t.Fatalf("recovery must carry the recorded reads: %+v", result.Reads)
	}
	if ledgerRecordCount(t, ledger) != before {
		t.Fatal("adoption must perform zero new submits")
	}
	// The adopted run rewrites its state document SUCCEEDED with the
	// adopted effect of record (the adopted record is not itself a
	// duplicate submit).
	document := seededRunDocument(t, stateDir)
	if document.Status != RunStateSucceeded || document.Effect == nil ||
		document.Effect.Duplicate || document.Effect.Key != key {
		t.Fatalf("adopted document: %+v", document)
	}
}

// TestResumeResubmitsExactlyOnceWhenAbsent pins the other recovery branch:
// a marker whose key never landed submits exactly once (reconciled=false)
// and closes SUCCEEDED with the settled effect.
func TestResumeResubmitsExactlyOnceWhenAbsent(t *testing.T) {
	stateDir, ledger, audit := seededMarkerRun(t, testTempDir(t))
	result, err := ResumeRun(RecoveryOptions{StateRoot: stateDir, Binding: testStateBinding(),
		Ledger: ledger, Audit: audit})
	if err != nil {
		t.Fatalf("resume: %v", err)
	}
	if result.Status != RunStateSucceeded || result.Reconciled ||
		result.Effect == nil || result.Effect.Status != EffectCompleted {
		t.Fatalf("resubmitted recovery: %+v", result)
	}
	if ledgerRecordCount(t, ledger) != 1 {
		t.Fatal("the absent key must be submitted exactly once")
	}
	// A second recovery on the now-terminal run is refused.
	_, err = ResumeRun(RecoveryOptions{StateRoot: stateDir, Binding: testStateBinding(),
		Ledger: ledger, Audit: audit})
	if err == nil || !strings.Contains(err.Error(), "not resumable") {
		t.Fatalf("a terminal run must refuse recovery, got %v", err)
	}
}

// TestResumeUnknownStaysUnknown pins M5-F3: the sink_unavailable control
// marks the run UNKNOWN — a terminal state that is never flattened to
// SUCCEEDED or FAILED — with the idempotency key still named; a further
// recovery is refused.
func TestResumeUnknownStaysUnknown(t *testing.T) {
	stateDir, ledger, audit := seededMarkerRun(t, testTempDir(t))
	result, err := ResumeRun(RecoveryOptions{StateRoot: stateDir, Binding: testStateBinding(),
		Ledger: ledger, Audit: audit, Controls: &EffectControls{SinkUnavailable: true}})
	if err != nil {
		t.Fatalf("resume: %v", err)
	}
	if result.Status != RunStateUnknown || result.Reconciled || result.Effect != nil ||
		result.IdempotencyKey != "cancel-and-refund:ORD-1001" {
		t.Fatalf("unknown recovery: %+v", result)
	}
	if ledgerRecordCount(t, ledger) != 0 {
		t.Fatal("an unprovable sink must not consult the ledger")
	}
	document := seededRunDocument(t, stateDir)
	if document.Status != RunStateUnknown {
		t.Fatalf("the UNKNOWN terminal must be durable: %+v", document.Status)
	}
	// UNKNOWN is terminal: no flattening, no second recovery.
	_, err = ResumeRun(RecoveryOptions{StateRoot: stateDir, Binding: testStateBinding(),
		Ledger: ledger, Audit: audit})
	if err == nil || !strings.Contains(err.Error(), "not resumable") {
		t.Fatalf("UNKNOWN must refuse recovery, got %v", err)
	}
}

// TestRecoveryRejectsUnresumableStates pins the fail-closed guards: a
// terminal document, a RUNNING document with no effect decision, and a
// foreign binding all refuse recovery without touching the ledger.
func TestRecoveryRejectsUnresumableStates(t *testing.T) {
	stateDir, ledger, audit := seededMarkerRun(t, testTempDir(t))
	document := seededRunDocument(t, stateDir)

	// A terminal document refuses recovery.
	terminal := document
	terminal.Status = RunStateSucceeded
	terminal.Effect = &EffectRecord{Key: EffectKey(EffectPayloadOf("ORD-1001")),
		PayloadDigest: testPayloadDigest(t), Status: EffectCompleted,
		Outcome: &RefundOutcome{RefundID: RefundID, RefundedAt: RefundedAt}}
	rewriteRunState(t, stateDir, terminal)
	if _, err := ResumeRun(RecoveryOptions{StateRoot: stateDir, Binding: testStateBinding(),
		Ledger: ledger, Audit: audit}); err == nil ||
		!strings.Contains(err.Error(), "not resumable") {
		t.Fatalf("terminal documents must refuse recovery, got %v", err)
	}

	// A RUNNING document without any effect decision has nothing to resolve.
	rewriteRunState(t, stateDir, document)
	markerless := document
	markerless.SubmitMarker = nil
	markerless.Effect = nil
	rewriteRunState(t, stateDir, markerless)
	if _, err := ResumeRun(RecoveryOptions{StateRoot: stateDir, Binding: testStateBinding(),
		Ledger: ledger, Audit: audit}); err == nil ||
		!strings.Contains(err.Error(), "no effect decision") {
		t.Fatalf("markerless runs must refuse recovery, got %v", err)
	}

	// A foreign binding cannot resolve the recorded run.
	rewriteRunState(t, stateDir, document)
	foreign := testStateBinding()
	foreign.RequestedOrderID = "ORD-2002"
	_, err := ResumeRun(RecoveryOptions{StateRoot: stateDir, Binding: foreign,
		Ledger: ledger, Audit: audit})
	var loadError *StateLoadError
	if !errors.As(err, &loadError) || loadError.Reason != ReasonBindingMismatch {
		t.Fatalf("foreign binding must fail BINDING_MISMATCH, got %v", err)
	}
	if ledgerRecordCount(t, ledger) != 0 {
		t.Fatal("refused recoveries must not touch the ledger")
	}
}

// TestRunnerRejectedRunHasZeroSubmissions pins M5-F1 end to end: the
// rejected-approval run fails APPROVAL_REJECTED with zero submissions — the
// ledger never gains a record, the audit holds exactly the rejection, and
// the terminal event is run.failed with the side-effect surface.
func TestRunnerRejectedRunHasZeroSubmissions(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	stateDir := filepath.Join(testTempDir(t), "state")
	report, err := RunCase(context.Background(), RunOptions{
		CaseID:    "approval-rejected-no-effect",
		TracePath: filepath.Join(testTempDir(t), "trace.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures})
	if err != nil {
		t.Fatalf("run: %v", err)
	}
	result := report.Result
	if result.Status != RunStateFailed || result.FailureCode == nil ||
		*result.FailureCode != FailureApprovalRejected ||
		result.ApprovalDecision != DecisionRejected ||
		result.EffectStatus != nil || result.IdempotencyKey != nil || result.Reconciled {
		t.Fatalf("rejected result: %+v", result)
	}
	ledger, err := NewEffectLedger(stateDir)
	if err != nil {
		t.Fatalf("ledger: %v", err)
	}
	if ledgerRecordCount(t, ledger) != 0 {
		t.Fatal("a rejected approval must submit nothing")
	}
	audit, err := NewAuditWriter(stateDir)
	if err != nil {
		t.Fatalf("audit: %v", err)
	}
	raw, err := os.ReadFile(audit.Path())
	if err != nil {
		t.Fatalf("read audit: %v", err)
	}
	if !strings.Contains(string(raw), `"decision":"rejected"`) ||
		strings.Contains(string(raw), `"kind":"effect"`) {
		t.Fatalf("the audit must hold exactly the rejection: %s", raw)
	}
	terminal := report.Events[len(report.Events)-1]
	if terminal.Type != contracts.EventRunFailed ||
		terminal.Data["approval_decision"] != DecisionRejected {
		t.Fatalf("terminal event: %+v", terminal)
	}
	// effect_status is null: a typed-nil pointer in the data map, never a
	// real value.
	if status, present := terminal.Data["effect_status"]; present && status != nil {
		if pointer, ok := status.(*string); !ok || pointer != nil {
			t.Fatalf("terminal effect_status must be null: %+v (%T)", status, status)
		}
	}
}

// TestDuplicateKeyAdoptsRecordedOutcome pins M5-F4: a fresh run over a
// state dir whose ledger already holds the key lands the same effect once —
// the ledger keeps exactly one record, the second phase's tool.completed
// carries duplicate=true, and the result projection stays reconciled=false.
func TestDuplicateKeyAdoptsRecordedOutcome(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	root := testTempDir(t)
	first, err := RunCase(context.Background(), RunOptions{
		CaseID: "duplicate-key-suppressed", TracePath: filepath.Join(root, "first.jsonl"),
		StateDir: filepath.Join(root, "state"), Scenario: scenario, Fixtures: fixtures})
	if err != nil {
		t.Fatalf("first run: %v", err)
	}
	if first.Result.Status != RunStateSucceeded || first.Result.Reconciled || first.Result.Resumed {
		t.Fatalf("first result: %+v", first.Result)
	}
	second, err := RunCase(context.Background(), RunOptions{
		CaseID: "duplicate-key-suppressed", TracePath: filepath.Join(root, "second.jsonl"),
		StateDir: filepath.Join(root, "state"), Scenario: scenario, Fixtures: fixtures})
	if err != nil {
		t.Fatalf("second run: %v", err)
	}
	if second.Result.Status != RunStateSucceeded || second.Result.EffectStatus == nil ||
		*second.Result.EffectStatus != EffectCompleted || second.Result.Reconciled ||
		second.Result.Resumed {
		t.Fatalf("duplicate result: %+v", second.Result)
	}
	if second.Result.RunID == first.Result.RunID {
		t.Fatal("the duplicate phase is a fresh run with its own run id")
	}
	ledger, err := NewEffectLedger(filepath.Join(root, "state"))
	if err != nil {
		t.Fatalf("ledger: %v", err)
	}
	if ledgerRecordCount(t, ledger) != 1 {
		t.Fatal("once-per-key: the ledger must hold exactly one record")
	}
	// The second phase's tool.completed event carries the adoption.
	duplicates := 0
	for _, event := range second.Events {
		if event.Type == contracts.EventToolCompleted {
			duplicate, ok := event.Data["duplicate"].(bool)
			if !ok || !duplicate {
				t.Fatalf("the duplicate phase's tool.completed must adopt: %+v", event.Data)
			}
			duplicates++
		}
	}
	if duplicates != 1 {
		t.Fatalf("expected one tool.completed in the duplicate phase, got %d", duplicates)
	}
}

// TestRunnerSubmitWindowResumeAdopts pins the M5_PHASES resume flow for the
// submit-window crash: the fresh phase crashes inside the window (the
// CrashSignal surfaces, the marker and the ledger record are on disk, no
// terminal), and the resume phase adopts the landed effect (reconciled=true,
// zero new submits, the recorded run id).
func TestRunnerSubmitWindowResumeAdopts(t *testing.T) {
	stateDir, scenario, fixtures := crashFreshRun(t, "crash-submit-window-resolved")
	ledger, err := NewEffectLedger(stateDir)
	if err != nil {
		t.Fatalf("ledger: %v", err)
	}
	if ledgerRecordCount(t, ledger) != 1 {
		t.Fatal("the crashed fresh phase must have submitted before dying")
	}
	loaded, err := loadRunState(stateDir, testBindingFor(t, scenario, "crash-submit-window-resolved"))
	if err != nil {
		t.Fatalf("load crashed state: %v", err)
	}
	runID := loaded.Document.RunID
	report, err := RunCase(context.Background(), RunOptions{
		CaseID:    "crash-submit-window-resolved",
		TracePath: filepath.Join(testTempDir(t), "resume.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures, Resume: true})
	if err != nil {
		t.Fatalf("resume: %v", err)
	}
	result := report.Result
	if result.Status != RunStateSucceeded || !result.Reconciled || !result.Resumed ||
		result.RestoredCursor == nil || *result.RestoredCursor != 3 ||
		len(result.RestoredWorkerIDs) != 3 || result.EffectStatus == nil ||
		*result.EffectStatus != EffectCompleted || result.ApprovalDecision != DecisionGranted {
		t.Fatalf("adopted resume result: %+v", result)
	}
	if result.RunID != runID {
		t.Fatal("the resumed run keeps the recorded run id")
	}
	if ledgerRecordCount(t, ledger) != 1 {
		t.Fatal("the resume must not submit again")
	}
}

// TestRunnerRetryBeforeSubmitResubmitsOnce pins the M5_PHASES flow for the
// before-submit crash: nothing was marked or submitted in the fresh phase;
// the resume re-runs the effect pipeline alone (no reads re-executed) and
// submits exactly once with reconciled=false.
func TestRunnerRetryBeforeSubmitResubmitsOnce(t *testing.T) {
	stateDir, scenario, fixtures := crashFreshRun(t, "retry-before-submit")
	ledger, err := NewEffectLedger(stateDir)
	if err != nil {
		t.Fatalf("ledger: %v", err)
	}
	if ledgerRecordCount(t, ledger) != 0 {
		t.Fatal("the before-submit crash must not have submitted")
	}
	report, err := RunCase(context.Background(), RunOptions{
		CaseID:    "retry-before-submit",
		TracePath: filepath.Join(testTempDir(t), "resume.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures, Resume: true})
	if err != nil {
		t.Fatalf("resume: %v", err)
	}
	result := report.Result
	if result.Status != RunStateSucceeded || result.Reconciled || !result.Resumed ||
		result.EffectStatus == nil || *result.EffectStatus != EffectCompleted ||
		result.ApprovalDecision != DecisionGranted {
		t.Fatalf("resubmitted resume result: %+v", result)
	}
	if ledgerRecordCount(t, ledger) != 1 {
		t.Fatal("the resume must submit exactly once")
	}
	// The resume phase re-runs no reads (all three were recorded) but
	// re-runs the approval surface.
	for _, event := range report.Events {
		if event.Type == contracts.EventStepStarted {
			t.Fatal("recorded reads must never re-execute")
		}
	}
	if !hasApprovalEvents(report.Events) {
		t.Fatal("the resumed effect pipeline must re-run the approval surface")
	}
}

func hasApprovalEvents(events []contracts.Event) bool {
	requested, granted := false, false
	for _, event := range events {
		switch event.Type {
		case contracts.EventApprovalRequested:
			requested = true
		case contracts.EventApprovalGranted:
			granted = true
		}
	}
	return requested && granted
}
