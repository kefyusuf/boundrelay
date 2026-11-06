package m5

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// countingProvider counts worker body invocations and replays the fixture
// outputs; the permissive control accepts every acknowledgement.
type countingProvider struct {
	fixture     WorkerInstructions
	orderID     string
	mutex       sync.Mutex
	invocations []string
}

func (p *countingProvider) Read(id string, input WorkerInput) (json.RawMessage, error) {
	p.mutex.Lock()
	p.invocations = append(p.invocations, id)
	p.mutex.Unlock()
	if input.OrderID != p.orderID {
		return nil, errors.New("m5: invalid worker invocation")
	}
	instruction, ok := p.fixture[id]
	if !ok {
		return nil, errors.New("m5: worker missing from fixture")
	}
	if instruction.Operation == "raise" {
		return nil, errors.New("m5: declared failure")
	}
	return append(json.RawMessage(nil), instruction.Output...), nil
}

func (p *countingProvider) AcknowledgeOutcome(id string) error { return nil }
func (p *countingProvider) BeginDrain()                        {}

// executorFor assembles the default executor options for one case spec.
func executorFor(t *testing.T, spec CaseSpec, scenario *Scenario, fixtures map[string]WorkerInstructions,
	store *StateStore, wiring *EffectWiring) ExecutorOptions {
	t.Helper()
	provider := NewScriptedWorkers(spec.ExecutionMode, spec.CompletionOrder,
		scenario.OrderID, fixtures[spec.WorkerFixture])
	return ExecutorOptions{Mode: spec.ExecutionMode,
		Input:     WorkerInput{OrderID: scenario.OrderID},
		Directory: DirectoryFromProvider(provider), Control: provider,
		Observer: func(WorkerLifecycle) {}, Store: store, Effect: wiring}
}

func testWiring(t *testing.T, stateDir string, spec CaseSpec, controls *EffectControls,
	onCrash func()) *EffectWiring {
	t.Helper()
	ledger, err := NewEffectLedger(stateDir)
	if err != nil {
		t.Fatalf("ledger: %v", err)
	}
	audit, err := NewAuditWriter(stateDir)
	if err != nil {
		t.Fatalf("audit: %v", err)
	}
	return &EffectWiring{Ledger: ledger, ApprovalGate: NewApprovalGate(spec.Approval),
		Audit: audit, Controls: controls, OnCrash: onCrash}
}

// TestExecutorEffectPipelineOrder pins the M5 write-ahead choreography end
// to end: the trace events (approval.requested -> approval.granted ->
// tool.requested -> tool.completed), the audit pair, and the store's
// marker-before-outcome order — with the settled effect of record.
func TestExecutorEffectPipelineOrder(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	spec := mustCase(t, scenario, "approval-granted-effect-once")
	stateDir := filepath.Join(testTempDir(t), "state")
	store := completeStore(t, stateDir)
	sink := NewEventSink(store.RunID())
	wiring := testWiring(t, stateDir, spec, nil, nil)
	wiring.Events = sink
	execution, err := ExecuteWorkers(context.Background(), executorFor(t, spec, scenario, fixtures, store, wiring))
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if execution.Effect == nil || execution.Rejected || execution.PeakConcurrency != 2 {
		t.Fatalf("execution: %+v", execution)
	}
	effect := *execution.Effect
	if effect.Key != "cancel-and-refund:ORD-1001" || effect.Status != EffectCompleted ||
		effect.PayloadDigest != testPayloadDigest(t) || effect.Duplicate {
		t.Fatalf("effect of record: %+v", effect)
	}
	// The event order is the M5 surface: reads, approval pair, tool pair.
	types := []contracts.EventType{}
	for _, event := range sink.Events() {
		types = append(types, event.Type)
	}
	joined := make([]string, 0, len(types))
	for _, eventType := range types {
		joined = append(joined, string(eventType))
	}
	sequence := strings.Join(joined, ",")
	for _, want := range []string{"approval.requested", "approval.granted", "tool.requested", "tool.completed"} {
		if !strings.Contains(sequence, want) {
			t.Fatalf("missing %s in %s", want, sequence)
		}
	}
	if strings.Index(sequence, "approval.requested") > strings.Index(sequence, "approval.granted") ||
		strings.Index(sequence, "approval.granted") > strings.Index(sequence, "tool.requested") ||
		strings.Index(sequence, "tool.requested") > strings.Index(sequence, "tool.completed") {
		t.Fatalf("effect event order violated: %s", sequence)
	}
	// The store carries the marker and the settled effect; the audit pair
	// is appended (approval first, effect last).
	document := store.State()
	if document.SubmitMarker == nil || document.Effect == nil ||
		document.Effect.Key != effect.Key {
		t.Fatalf("store document: %+v", document)
	}
	audit, err := NewAuditWriter(stateDir)
	if err != nil {
		t.Fatalf("audit: %v", err)
	}
	raw, err := os.ReadFile(audit.Path())
	if err != nil {
		t.Fatalf("read audit: %v", err)
	}
	lines := strings.Split(strings.TrimRight(string(raw), "\n"), "\n")
	if len(lines) != 2 || !strings.Contains(lines[0], `"kind":"approval"`) ||
		!strings.Contains(lines[1], `"kind":"effect"`) {
		t.Fatalf("audit order: %q", lines)
	}
}

// TestExecutorRejectedApprovalSubmitsNothing pins the rejection: the gate's
// rejected decision ends the pipeline after the audit record — no submit
// marker, no ledger record, no tool events, zero submissions.
func TestExecutorRejectedApprovalSubmitsNothing(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	spec := mustCase(t, scenario, "approval-rejected-no-effect")
	stateDir := filepath.Join(testTempDir(t), "state")
	store := completeStore(t, stateDir)
	sink := NewEventSink(store.RunID())
	wiring := testWiring(t, stateDir, spec, nil, nil)
	wiring.Events = sink
	execution, err := ExecuteWorkers(context.Background(), executorFor(t, spec, scenario, fixtures, store, wiring))
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if !execution.Rejected || execution.Effect != nil {
		t.Fatalf("execution: %+v", execution)
	}
	if store.State().SubmitMarker != nil || store.State().Effect != nil {
		t.Fatalf("a rejected approval must write nothing into the document: %+v", store.State())
	}
	ledger, err := NewEffectLedger(stateDir)
	if err != nil {
		t.Fatalf("ledger: %v", err)
	}
	if ledgerRecordCount(t, ledger) != 0 {
		t.Fatal("a rejected approval must submit nothing")
	}
	for _, event := range sink.Events() {
		if strings.HasPrefix(string(event.Type), "tool.") {
			t.Fatalf("no tool events on rejection: %s", event.Type)
		}
	}
}

// TestExecutorCrashBeforeSubmitFiresBeforeMarker pins the first crash
// boundary: crash_before_submit fires after the approval audit record and
// BEFORE the submit marker — the state document and the ledger both stay
// untouched.
func TestExecutorCrashBeforeSubmitFiresBeforeMarker(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	spec := mustCase(t, scenario, "retry-before-submit")
	stateDir := filepath.Join(testTempDir(t), "state")
	store := completeStore(t, stateDir)
	boundaryDocument := ""
	onCrash := func() {
		raw, err := os.ReadFile(store.StatePath())
		if err != nil {
			panic(err)
		}
		boundaryDocument = string(raw)
		panic(&CrashSignal{Boundary: CrashBoundaryBeforeSubmit})
	}
	wiring := testWiring(t, stateDir, spec, &EffectControls{CrashBeforeSubmit: true}, onCrash)
	_, err := ExecuteWorkers(context.Background(), executorFor(t, spec, scenario, fixtures, store, wiring))
	var signal *CrashSignal
	if !errors.As(err, &signal) || signal.Boundary != CrashBoundaryBeforeSubmit {
		t.Fatalf("crash must surface at the before-submit boundary, got %v", err)
	}
	var document RunStateDocument
	if err := json.Unmarshal([]byte(boundaryDocument), &document); err != nil {
		t.Fatalf("boundary document: %v", err)
	}
	if document.SubmitMarker != nil || document.Effect != nil {
		t.Fatalf("crash_before_submit must fire before the marker: %+v", document)
	}
	ledger, err := NewEffectLedger(stateDir)
	if err != nil {
		t.Fatalf("ledger: %v", err)
	}
	if ledgerRecordCount(t, ledger) != 0 {
		t.Fatal("no submit may happen before the marker")
	}
}

// TestExecutorCrashInSubmitWindowPinsMarkerAndSubmit pins the second crash
// boundary: crash_in_submit_window fires after the ledger submit returned —
// the marker and the ledger record are both durable, the effect of record is
// not yet written, and the audit holds only the approval record.
func TestExecutorCrashInSubmitWindowPinsMarkerAndSubmit(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	spec := mustCase(t, scenario, "crash-submit-window-resolved")
	stateDir := filepath.Join(testTempDir(t), "state")
	store := completeStore(t, stateDir)
	boundary := struct {
		document string
		audit    string
		ledger   string
	}{}
	onCrash := func() {
		raw, err := os.ReadFile(store.StatePath())
		if err != nil {
			panic(err)
		}
		boundary.document = string(raw)
		auditRaw, err := os.ReadFile(filepath.Join(stateDir, "audit.jsonl"))
		if err != nil {
			panic(err)
		}
		boundary.audit = string(auditRaw)
		ledgerRaw, err := os.ReadFile(filepath.Join(stateDir, "effect-ledger.json"))
		if err != nil {
			panic(err)
		}
		boundary.ledger = string(ledgerRaw)
		panic(&CrashSignal{Boundary: CrashBoundaryInSubmitWindow})
	}
	wiring := testWiring(t, stateDir, spec, &EffectControls{CrashInSubmitWindow: true}, onCrash)
	_, err := ExecuteWorkers(context.Background(), executorFor(t, spec, scenario, fixtures, store, wiring))
	var signal *CrashSignal
	if !errors.As(err, &signal) || signal.Boundary != CrashBoundaryInSubmitWindow {
		t.Fatalf("crash must surface at the in-submit-window boundary, got %v", err)
	}
	var document RunStateDocument
	if err := json.Unmarshal([]byte(boundary.document), &document); err != nil {
		t.Fatalf("boundary document: %v", err)
	}
	if document.SubmitMarker == nil || document.SubmitMarker.Key != "cancel-and-refund:ORD-1001" ||
		document.SubmitMarker.PayloadDigest != testPayloadDigest(t) {
		t.Fatalf("the marker must be durable in the submit window: %+v", document)
	}
	if document.Effect != nil {
		t.Fatalf("the effect of record must not exist in the submit window: %+v", document)
	}
	if got := strings.Count(boundary.ledger, `"key"`); got != 1 {
		t.Fatalf("the submit must have landed exactly one ledger record: %s", boundary.ledger)
	}
	if strings.Count(boundary.audit, `"kind"`) != 1 ||
		!strings.Contains(boundary.audit, `"kind":"approval"`) {
		t.Fatalf("only the approval audit record may exist in the window: %s", boundary.audit)
	}
}

// TestExecutorMarkerSurvivesFailedSubmit pins the write-ahead guarantee at
// the heart of the submit window: the marker is written BEFORE the ledger
// submit, so a failed submit (a corrupt sink) still leaves the marker
// behind — the run stays resumable exactly because the marker does not
// depend on the submit's success.
func TestExecutorMarkerSurvivesFailedSubmit(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	spec := mustCase(t, scenario, "approval-granted-effect-once")
	stateDir := filepath.Join(testTempDir(t), "state")
	store := completeStore(t, stateDir)
	// A corrupt sink: the ledger file is not valid JSON, so submit fails.
	if err := os.WriteFile(filepath.Join(stateDir, "effect-ledger.json"), []byte("not json"), 0o644); err != nil {
		t.Fatalf("write corrupt ledger: %v", err)
	}
	wiring := testWiring(t, stateDir, spec, nil, nil)
	_, err := ExecuteWorkers(context.Background(), executorFor(t, spec, scenario, fixtures, store, wiring))
	if err == nil || !strings.Contains(err.Error(), "not valid JSON") {
		t.Fatalf("the failed submit must be a tooling error, got %v", err)
	}
	document, err := loadRunStateDocument(store.StatePath(), testStateBinding())
	if err != nil {
		t.Fatalf("reload: %v", err)
	}
	if document.SubmitMarker == nil || document.SubmitMarker.Key != "cancel-and-refund:ORD-1001" {
		t.Fatalf("the write-ahead marker must survive a failed submit: %+v", document)
	}
	if document.Effect != nil {
		t.Fatalf("no effect of record can exist without a settled submit: %+v", document)
	}
}

// TestExecutorReadFailureStopsBeforeApproval pins the gate precondition:
// any failed read stops the fan-out before the effect pipeline — no
// approval events, no submissions.
func TestExecutorReadFailureStopsBeforeApproval(t *testing.T) {
	scenario, _ := loadRepoScenario(t)
	spec := mustCase(t, scenario, "approval-granted-effect-once")
	stateDir := filepath.Join(testTempDir(t), "state")
	store := completeStore(t, stateDir)
	sink := NewEventSink(store.RunID())
	// The M5 projection only carries the complete fixture; a declared
	// read failure is scripted inline.
	failingFixture := WorkerInstructions{
		contracts.WorkerOrderDetails:   {Operation: "return", Output: json.RawMessage(`{"order_id":"ORD-1001","order_status":"SHIPPED"}`)},
		contracts.WorkerPaymentStatus:  {Operation: "return", Output: json.RawMessage(`{"order_id":"ORD-1001","payment_status":"PAID"}`)},
		contracts.WorkerDeliveryStatus: {Operation: "raise", FailureCode: contracts.FailureWorkerExecutionFailed},
	}
	failing := NewScriptedWorkers(spec.ExecutionMode, spec.CompletionOrder,
		scenario.OrderID, failingFixture)
	wiring := testWiring(t, stateDir, spec, nil, nil)
	wiring.Events = sink
	execution, err := ExecuteWorkers(context.Background(), ExecutorOptions{
		Mode: spec.ExecutionMode, Input: WorkerInput{OrderID: scenario.OrderID},
		Directory: DirectoryFromProvider(failing), Control: failing,
		Observer: func(WorkerLifecycle) {}, Store: store, Effect: wiring})
	if err != nil {
		t.Fatalf("partial reads are declared outcomes, not errors: %v", err)
	}
	if !anyReadFailed(execution.Reads) {
		t.Fatalf("the partial fixture must record a failed read: %+v", execution.Reads)
	}
	if execution.Effect != nil {
		t.Fatalf("partial execution must not settle an effect: %+v", execution)
	}
	if store.State().SubmitMarker != nil || store.State().Effect != nil {
		t.Fatal("failed reads must stop before the effect pipeline")
	}
	for _, event := range sink.Events() {
		if strings.HasPrefix(string(event.Type), "approval.") ||
			strings.HasPrefix(string(event.Type), "tool.") {
			t.Fatalf("no effect events on failed reads: %s", event.Type)
		}
	}
}

// TestExecutorValidatesInputs pins the executor's fail-closed option
// validation: the mode, the order id, the queue shape, and the crash-control
// wiring requirements.
func TestExecutorValidatesInputs(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	spec := mustCase(t, scenario, "approval-granted-effect-once")
	provider := NewScriptedWorkers(spec.ExecutionMode, spec.CompletionOrder,
		scenario.OrderID, fixtures[spec.WorkerFixture])
	base := ExecutorOptions{Mode: spec.ExecutionMode, Input: WorkerInput{OrderID: scenario.OrderID},
		Directory: DirectoryFromProvider(provider), Control: provider,
		Observer: func(WorkerLifecycle) {}}
	if _, err := ExecuteWorkers(context.Background(), base); err != nil {
		t.Fatalf("baseline: %v", err)
	}
	badMode := base
	badMode.Mode = "serial"
	if _, err := ExecuteWorkers(context.Background(), badMode); err == nil {
		t.Fatal("unknown mode must be refused")
	}
	badOrder := base
	badOrder.Input = WorkerInput{OrderID: "ORD-1"}
	if _, err := ExecuteWorkers(context.Background(), badOrder); err == nil {
		t.Fatal("malformed order id must be refused")
	}
	badQueue := base
	badQueue.Queue = []string{contracts.WorkerPaymentStatus, contracts.WorkerOrderDetails,
		contracts.WorkerDeliveryStatus}
	if _, err := ExecuteWorkers(context.Background(), badQueue); err == nil {
		t.Fatal("a queue outside the canonical order must be refused")
	}
	dupQueue := base
	dupQueue.Queue = []string{contracts.WorkerOrderDetails, contracts.WorkerOrderDetails,
		contracts.WorkerPaymentStatus}
	if _, err := ExecuteWorkers(context.Background(), dupQueue); err == nil {
		t.Fatal("a duplicated queue must be refused")
	}
	noDirectory := base
	noDirectory.Directory = nil
	if _, err := ExecuteWorkers(context.Background(), noDirectory); err == nil {
		t.Fatal("a missing directory must be refused")
	}
	crashWiring := &EffectWiring{Controls: &EffectControls{CrashBeforeSubmit: true}}
	missingCrash := base
	missingCrash.Effect = crashWiring
	if _, err := ExecuteWorkers(context.Background(), missingCrash); err == nil {
		t.Fatal("a crash control without on_crash must be refused")
	}
}
