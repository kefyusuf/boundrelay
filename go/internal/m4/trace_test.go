package m4

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// TestTraceEnvelope pins the 1.0 envelope: source "go", sequence numbering,
// run id binding, and the flushed JSONL round trip.
func TestTraceEnvelope(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	tracePath := testTempDir(t) + "/trace.jsonl"
	report, err := RunCase(traceContext(), RunOptions{
		CaseID: "parallel-clean-complete", TracePath: tracePath,
		StateDir: testTempDir(t), Scenario: scenario, Fixtures: fixtures})
	if err != nil {
		t.Fatalf("run: %v", err)
	}
	events := readPhaseTrace(t, tracePath)
	if len(events) != len(report.Events) {
		t.Fatalf("flushed events %d != recorded %d", len(events), len(events))
	}
	for index, event := range events {
		if event.SchemaVersion != contracts.EnvelopeVersion || event.Source != contracts.SourceGo {
			t.Fatalf("event %d envelope: %+v", index+1, event)
		}
		if event.RunID != report.Result.RunID {
			t.Fatalf("event %d run id: %s", index+1, event.RunID)
		}
		if event.Sequence != index+1 || event.EventID != fmt.Sprintf("evt-%d", event.Sequence) {
			t.Fatalf("event %d identity: %+v", index+1, event)
		}
		if event.Timestamp == "" {
			t.Fatalf("event %d timestamp", index+1)
		}
	}
}

// TestTraceLifecycleEvents pins the fresh lifecycle event set: envelope
// open, worker steps with terminal outcomes, checkpoint.saved after each
// recorded terminal, and the terminal event matching the result status.
func TestTraceLifecycleEvents(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	tracePath := testTempDir(t) + "/trace.jsonl"
	report, err := RunCase(traceContext(), RunOptions{
		CaseID: "parallel-clean-complete", TracePath: tracePath,
		StateDir: testTempDir(t), Scenario: scenario, Fixtures: fixtures})
	if err != nil {
		t.Fatalf("run: %v", err)
	}
	types := []string{}
	for _, event := range report.Events {
		name, _ := event.Data["step_name"].(string)
		types = append(types, string(event.Type)+":"+name)
	}
	joined := strings.Join(types, ",")
	for _, expected := range []string{
		"run.created:", "run.started:", "step.started:worker.", "step.completed:worker.",
		"checkpoint.saved:", "step.started:synthesize", "step.completed:synthesize",
		"run.completed:"} {
		if !strings.Contains(joined, expected) {
			t.Fatalf("lifecycle missing %s: %v", expected, types)
		}
	}
	if report.Events[len(report.Events)-1].Type != contracts.EventRunCompleted {
		t.Fatalf("terminal event: %v", report.Events[len(report.Events)-1].Type)
	}
	// The checkpoint.saved events carry the bare worker id and the store's
	// post-write cursor; step_name drives the harness projection.
	for _, event := range report.Events {
		if event.Type != contracts.EventCheckpointSaved {
			continue
		}
		name, _ := event.Data["step_name"].(string)
		if name != contracts.WorkerOrderDetails && name != contracts.WorkerPaymentStatus &&
			name != contracts.WorkerDeliveryStatus {
			t.Fatalf("checkpoint.saved step_name: %+v", event.Data)
		}
		if _, ok := event.Data["sequence_cursor"].(int); !ok {
			t.Fatalf("checkpoint.saved cursor: %+v", event.Data)
		}
	}
}

// TestTraceCrashPrefixWithoutTerminal pins the crash trace shape: the
// flushed prefix carries no terminal event for the crashing worker and no
// run.completed.
func TestTraceCrashPrefixWithoutTerminal(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	tracePath := testTempDir(t) + "/crash.jsonl"
	_, err := RunCase(traceContext(), RunOptions{
		CaseID: "parallel-crash-resume", TracePath: tracePath,
		StateDir: testTempDir(t), Scenario: scenario, Fixtures: fixtures,
		OnCrash: crashProbe()})
	var signal *CrashSignal
	if !errors.As(err, &signal) {
		t.Fatalf("crash: %v", err)
	}
	events := readPhaseTrace(t, tracePath)
	var last string
	for _, event := range events {
		last = string(event.Type)
	}
	if last != "checkpoint.saved" {
		t.Fatalf("the crash prefix must end at a checkpoint, got %s", last)
	}
	for _, event := range events {
		if event.Type == contracts.EventRunCompleted || event.Type == contracts.EventRunFailed {
			t.Fatal("crash traces carry no terminal event")
		}
		name, _ := event.Data["step_name"].(string)
		if event.Type == contracts.EventStepCompleted && name == "worker.payment-status" {
			t.Fatal("the crashing worker's terminal must not be observed")
		}
	}
}

// TestTraceRestoredAndCancelledEvents pins the recovery event payloads:
// checkpoint.restored on resume and run.cancelled on scripted cancellation.
func TestTraceRestoredAndCancelledEvents(t *testing.T) {
	scenario, fixtures := loadRepoScenario(t)
	stateDir := crashedFreshState(t, "parallel-crash-resume",
		"fixtures/workers/order-brief/complete.yaml", contracts.WorkerPaymentStatus)
	tracePath := testTempDir(t) + "/resume.jsonl"
	report, err := RunCase(traceContext(), RunOptions{
		CaseID: "parallel-crash-resume", TracePath: tracePath,
		StateDir: stateDir, Scenario: scenario, Fixtures: fixtures, Resume: true})
	if err != nil {
		t.Fatalf("resume: %v", err)
	}
	var restored []contracts.Event
	for _, event := range report.Events {
		if event.Type == contracts.EventCheckpointRestored {
			restored = append(restored, event)
		}
	}
	if len(restored) != 1 {
		t.Fatalf("resume must emit one checkpoint.restored, got %d", len(restored))
	}
	data := restored[0].Data
	if data["state_status"] != RunStateStatusRunning || data["restored_cursor"] != 2 {
		t.Fatalf("checkpoint.restored payload: %+v", data)
	}
	ids, ok := data["restored_worker_ids"].([]string)
	if !ok || len(ids) != 2 || ids[0] != contracts.WorkerOrderDetails ||
		ids[1] != contracts.WorkerPaymentStatus {
		t.Fatalf("checkpoint.restored worker ids: %+v", data)
	}

	cancelDir := testTempDir(t) + "/cancel-state"
	cancelTrace := testTempDir(t) + "/cancel.jsonl"
	cancelled, err := RunCase(traceContext(), RunOptions{
		CaseID: "parallel-cancel-resume", TracePath: cancelTrace,
		StateDir: cancelDir, Scenario: scenario, Fixtures: fixtures})
	if err != nil {
		t.Fatalf("cancel run: %v", err)
	}
	var cancelledEvents []contracts.Event
	for _, event := range cancelled.Events {
		if event.Type == contracts.EventRunCancelled {
			cancelledEvents = append(cancelledEvents, event)
		}
	}
	if len(cancelledEvents) != 1 {
		t.Fatalf("cancellation must emit one run.cancelled, got %d", len(cancelledEvents))
	}
	cancelData := cancelledEvents[0].Data
	if cancelData["cancelled_before"] != contracts.WorkerDeliveryStatus ||
		cancelData["code"] != "CANCELLED_BEFORE_STEP" {
		t.Fatalf("run.cancelled payload: %+v", cancelData)
	}
	// A CANCELLED result emits no terminal run event.
	for _, event := range cancelled.Events {
		if event.Type == contracts.EventRunCompleted || event.Type == contracts.EventRunFailed {
			t.Fatal("cancelled runs carry no terminal event")
		}
	}
}

// traceContext bounds one library-level run.
func traceContext() context.Context {
	return context.Background()
}
