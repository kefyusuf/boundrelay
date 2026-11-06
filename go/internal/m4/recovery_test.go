package m4

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// crashedFreshState runs the fresh phase of a crash case with the
// panic-based crash control, returning the state dir.
func crashedFreshState(t *testing.T, caseKey, fixtureRef string, crashAfter string) string {
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
	return stateDir
}

// TestResumeSkipsRecordedFailures pins M4-F2: a resume never re-executes
// recorded outcomes (including recorded failures); the missing workers
// alone execute, and the merged result is partial.
func TestResumeSkipsRecordedFailures(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	stateDir := crashedFreshState(t, "parallel-crash-resume-partial",
		"fixtures/workers/order-brief/partial-failure.yaml", contracts.WorkerDeliveryStatus)
	document, err := loadRunState(stateDir, testBinding(mustCase(t, scenario, "parallel-crash-resume-partial"), scenario))
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if document.Document.SequenceCursor != 3 || document.Document.Steps[2].Status != StepStatusFailed {
		t.Fatalf("crashed state: %+v", document.Document)
	}
	provider := &countingProvider{
		fixture: fixtures["fixtures/workers/order-brief/partial-failure.yaml"],
		orderID: scenario.OrderID}
	report, err := RunCase(context.Background(), RunOptions{
		CaseID:    "parallel-crash-resume-partial",
		TracePath: filepath.Join(testTempDir(t), "resume.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures, Resume: true,
		Directory: DirectoryFromProvider(provider), Control: provider})
	if err != nil {
		t.Fatalf("resume: %v", err)
	}
	if len(provider.invocations) != 0 {
		t.Fatalf("recorded outcomes must never re-execute, invoked %v", provider.invocations)
	}
	result := report.Result
	if result.Status != RunStatePartial || !result.Resumed || result.RestoredCursor == nil ||
		*result.RestoredCursor != 3 || len(result.RestoredWorkerIDs) != 3 {
		t.Fatalf("resumed result: %+v", result)
	}
	// Two recorded successes: synthesis still runs over the recovered
	// evidence, and the recorded failure stays in the brief's missing set.
	if !result.SynthesisInvoked || result.Brief == nil || len(result.Brief.Sections) != 2 ||
		len(result.Brief.MissingWorkers) != 1 || result.Brief.MissingWorkers[0] != contracts.WorkerDeliveryStatus ||
		len(result.WorkerOutcomes) != 3 || result.WorkerOutcomes[2].Status != StatusFailed {
		t.Fatalf("recovered partial run: %+v", result)
	}
	if result.RunStateStatus != RunStatePartial || result.FailureCode != nil {
		t.Fatalf("partial close: %+v", result)
	}
}

// TestResumeReExecutesInFlightOnce pins the Ruling-5 attribution: a worker
// restored as RUNNING was invoked in the crashed phase and re-executes
// exactly once on resume, counting two attempts.
func TestResumeReExecutesInFlightOnce(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	binding := testBinding(mustCase(t, scenario, "parallel-clean-complete"), scenario)
	stateDir := filepath.Join(testTempDir(t), "state")
	store, err := CreateStore(stateDir, binding, append([]string(nil), contracts.CanonicalWorkerIDs...))
	if err != nil {
		t.Fatalf("create store: %v", err)
	}
	// Simulate the crash window: two terminals recorded, the third worker
	// was RUNNING (admitted, never settled) when the process died.
	if err := store.RecordStepTerminal(contracts.WorkerOrderDetails,
		succeededOutcome(contracts.WorkerOrderDetails, `{"order_id":"ORD-1001","order_status":"SHIPPED"}`)); err != nil {
		t.Fatalf("record: %v", err)
	}
	if err := store.RecordStepTerminal(contracts.WorkerPaymentStatus,
		succeededOutcome(contracts.WorkerPaymentStatus, `{"order_id":"ORD-1001","payment_status":"PAID"}`)); err != nil {
		t.Fatalf("record: %v", err)
	}
	if err := store.MarkRunning(contracts.WorkerDeliveryStatus); err != nil {
		t.Fatalf("mark running: %v", err)
	}
	provider := &countingProvider{
		fixture: fixtures["fixtures/workers/order-brief/complete.yaml"], orderID: scenario.OrderID}
	report, err := RunCase(context.Background(), RunOptions{
		CaseID:    "parallel-clean-complete",
		TracePath: filepath.Join(testTempDir(t), "resume.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures, Resume: true,
		Directory: DirectoryFromProvider(provider), Control: provider})
	if err != nil {
		t.Fatalf("resume: %v", err)
	}
	if len(provider.invocations) != 1 || provider.invocations[0] != contracts.WorkerDeliveryStatus {
		t.Fatalf("only the in-flight worker re-executes: %v", provider.invocations)
	}
	result := report.Result
	if result.Status != RunStateSucceeded || !result.Resumed || *result.RestoredCursor != 2 {
		t.Fatalf("resumed result: %+v", result)
	}
	// Ruling 5: the re-executed worker counts two attempts.
	latency := map[string]int{}
	attempts := map[string]int{}
	for _, step := range result.Attribution.Steps {
		latency[step.StepName] = step.LatencyMS
		attempts[step.StepName] = step.Attempts
	}
	if attempts["worker.delivery-status"] != 2 || latency["worker.delivery-status"] != 24 {
		t.Fatalf("re-executed worker must count two attempts: %+v", result.Attribution)
	}
	if attempts["worker.order-details"] != 1 {
		t.Fatalf("recorded workers count one attempt: %+v", result.Attribution)
	}
}

// TestReplayCreatesNewRunAndSourceUntouched pins the replay semantics: a
// new run id under the same state root, the snapshot's recorded outcomes
// never re-executed, and the source run's state untouched.
func TestReplayCreatesNewRunAndSourceUntouched(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	stateDir := filepath.Join(testTempDir(t), "state")
	fresh, err := RunCase(context.Background(), RunOptions{
		CaseID:    "parallel-clean-complete",
		TracePath: filepath.Join(testTempDir(t), "fresh.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures})
	if err != nil {
		t.Fatalf("fresh: %v", err)
	}
	sourceStatePath := filepath.Join(stateDir, fresh.Result.RunID, "state.json")
	sourceRaw, err := os.ReadFile(sourceStatePath)
	if err != nil {
		t.Fatalf("read source state: %v", err)
	}
	snapshot := filepath.Join(stateDir, fresh.Result.RunID, "checkpoints", "step-1.json")
	provider := &countingProvider{
		fixture: fixtures["fixtures/workers/order-brief/complete.yaml"], orderID: scenario.OrderID}
	report, err := RunCase(context.Background(), RunOptions{
		CaseID:    "parallel-clean-complete",
		TracePath: filepath.Join(testTempDir(t), "replay.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures,
		ReplayFrom: snapshot,
		Directory:  DirectoryFromProvider(provider), Control: provider})
	if err != nil {
		t.Fatalf("replay: %v", err)
	}
	if len(provider.invocations) != 2 {
		t.Fatalf("only the pending workers re-execute: %v", provider.invocations)
	}
	if report.Result.RunID == fresh.Result.RunID {
		t.Fatal("replay must mint a new run id")
	}
	if !report.Result.Resumed || report.Result.RestoredCursor == nil ||
		*report.Result.RestoredCursor != 1 || len(report.Result.RestoredWorkerIDs) != 1 ||
		report.Result.RestoredWorkerIDs[0] != contracts.WorkerOrderDetails {
		t.Fatalf("replayed result: %+v", report.Result)
	}
	if report.Result.Status != RunStateSucceeded {
		t.Fatalf("replayed status: %+v", report.Result)
	}
	untouched, err := os.ReadFile(sourceStatePath)
	if err != nil {
		t.Fatalf("read source state: %v", err)
	}
	if string(untouched) != string(sourceRaw) {
		t.Fatal("the source run's state must stay untouched")
	}
	// The replay writes its own state directory alongside the source.
	if _, err := os.Stat(filepath.Join(stateDir, report.Result.RunID, "state.json")); err != nil {
		t.Fatalf("replay state: %v", err)
	}
}

// TestResumeCancelledRunIsResumable pins that a CANCELLED run resumes and
// completes the remaining workers only.
func TestResumeCancelledRunIsResumable(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	stateDir := filepath.Join(testTempDir(t), "state")
	cancelled, err := RunCase(context.Background(), RunOptions{
		CaseID:    "parallel-cancel-resume",
		TracePath: filepath.Join(testTempDir(t), "fresh.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures})
	if err != nil {
		t.Fatalf("cancel run: %v", err)
	}
	if cancelled.Result.Status != StatusCancelled || cancelled.Result.Resumed {
		t.Fatalf("cancelled result: %+v", cancelled.Result)
	}
	if cancelled.Result.RunStateStatus != StatusCancelled {
		t.Fatalf("cancelled run state: %+v", cancelled.Result)
	}
	provider := &countingProvider{
		fixture: fixtures["fixtures/workers/order-brief/complete.yaml"], orderID: scenario.OrderID}
	report, err := RunCase(context.Background(), RunOptions{
		CaseID:    "parallel-cancel-resume",
		TracePath: filepath.Join(testTempDir(t), "resume.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures, Resume: true,
		Directory: DirectoryFromProvider(provider), Control: provider})
	if err != nil {
		t.Fatalf("resume: %v", err)
	}
	if len(provider.invocations) != 1 || provider.invocations[0] != contracts.WorkerDeliveryStatus {
		t.Fatalf("resume completes the remaining workers only: %v", provider.invocations)
	}
	result := report.Result
	if result.Status != RunStateSucceeded || !result.Resumed || *result.RestoredCursor != 2 {
		t.Fatalf("resumed result: %+v", result)
	}
}

// TestResumeRejectsTerminalState pins the fail-closed resumability check.
func TestResumeRejectsTerminalState(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	stateDir := filepath.Join(testTempDir(t), "state")
	if _, err := RunCase(context.Background(), RunOptions{
		CaseID:    "parallel-clean-complete",
		TracePath: filepath.Join(testTempDir(t), "fresh.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures}); err != nil {
		t.Fatalf("fresh: %v", err)
	}
	_, err := RunCase(context.Background(), RunOptions{
		CaseID:    "parallel-clean-complete",
		TracePath: filepath.Join(testTempDir(t), "resume.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures, Resume: true})
	if err == nil || !strings.Contains(err.Error(), "not resumable") {
		t.Fatalf("terminal state must refuse resume, got %v", err)
	}
}

// TestResumeRejectsBindingMismatch pins M4-F5: a resume whose case identity
// diverges from the recorded binding fails closed without invocations.
func TestResumeRejectsBindingMismatch(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	stateDir := filepath.Join(testTempDir(t), "state")
	if _, err := RunCase(context.Background(), RunOptions{
		CaseID:    "parallel-clean-complete",
		TracePath: filepath.Join(testTempDir(t), "fresh.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures}); err != nil {
		t.Fatalf("fresh: %v", err)
	}
	provider := &countingProvider{
		fixture: fixtures["fixtures/workers/order-brief/complete.yaml"], orderID: scenario.OrderID}
	_, err := RunCase(context.Background(), RunOptions{
		CaseID:    "parallel-crash-resume",
		TracePath: filepath.Join(testTempDir(t), "resume.jsonl"),
		StateDir:  stateDir, Scenario: scenario, Fixtures: fixtures, Resume: true,
		Directory: DirectoryFromProvider(provider), Control: provider})
	var loadError *StateLoadError
	if !errors.As(err, &loadError) || loadError.Reason != ReasonBindingMismatch {
		t.Fatalf("expected BINDING_MISMATCH, got %v", err)
	}
	if len(provider.invocations) != 0 {
		t.Fatalf("binding mismatch must not invoke workers: %v", provider.invocations)
	}
}

func mustCase(t *testing.T, scenario *Scenario, caseID string) CaseSpec {
	t.Helper()
	spec, err := scenario.FindCase(caseID)
	if err != nil {
		t.Fatalf("FindCase: %v", err)
	}
	return spec
}

// TestRecordedOutcomeRoundTrip pins that recorded failed steps rebuild as
// null-output outcomes.
func TestRecordedOutcomeRoundTrip(t *testing.T) {
	document := RunStateDocument{
		StateSchemaVersion: StateSchemaVersion, RunID: "run-1", ScenarioID: ScenarioID,
		CaseID: "parallel-crash-resume-partial", ExecutionMode: ModeParallel,
		ConcurrencyLimit: 2, RequestedOrderID: "ORD-1001", Status: RunStateStatusRunning,
	}
	document.Steps[0] = StepRecord{WorkerID: contracts.WorkerOrderDetails,
		Status: StepStatusSucceeded, Output: json.RawMessage(`{"order_id":"ORD-1001","order_status":"SHIPPED"}`)}
	failureCode := contracts.FailureWorkerExecutionFailed
	document.Steps[2] = StepRecord{WorkerID: contracts.WorkerDeliveryStatus,
		Status: StepStatusFailed, FailureCode: &failureCode}
	outcomes := recordedOutcomes(document)
	if len(outcomes) != 2 {
		t.Fatalf("recorded outcomes: %+v", outcomes)
	}
	if outcomes[1].Output != nil || outcomes[1].FailureCode == nil {
		t.Fatalf("failed outcome: %+v", outcomes[1])
	}
	if !validateWorkerOutcome(outcomes[0], "ORD-1001") || !validateWorkerOutcome(outcomes[1], "ORD-1001") {
		t.Fatal("recorded outcomes must validate")
	}
}
