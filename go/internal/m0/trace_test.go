package m0

import (
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

func TestEventSinkEmitsEnvelope(t *testing.T) {
	sink := NewEventSink("run-1")
	first, err := sink.Emit(contracts.EventRunCreated, map[string]any{
		"scenario_id": "support-triage", "case_id": "c", "mode": "model"})
	if err != nil {
		t.Fatalf("Emit: %v", err)
	}
	second, err := sink.Emit(contracts.EventRunStarted, map[string]any{"case_id": "c", "mode": "model"})
	if err != nil {
		t.Fatalf("Emit: %v", err)
	}
	events := sink.Events()
	if len(events) != 2 {
		t.Fatalf("events: %d", len(events))
	}
	for i, event := range events {
		if event.SchemaVersion != contracts.EnvelopeVersion || event.Source != contracts.SourceGo ||
			event.RunID != "run-1" || event.Sequence != i+1 || event.EventID == "" ||
			event.Timestamp == "" {
			t.Fatalf("event %d envelope: %+v", i, event)
		}
	}
	if events[0].Type != contracts.EventRunCreated || events[1].Type != contracts.EventRunStarted {
		t.Fatalf("types: %s %s", events[0].Type, events[1].Type)
	}
	if first.Data["scenario_id"] != "support-triage" || second.Data["case_id"] != "c" {
		t.Fatalf("data payloads: %+v %+v", first.Data, second.Data)
	}
}

func TestEventSinkRejectsInvalidEvents(t *testing.T) {
	sink := NewEventSink("run-1")
	if _, err := sink.Emit(contracts.EventType("bogus.event"), map[string]any{}); err == nil {
		t.Fatal("unknown event type must be rejected")
	}
	if _, err := sink.Emit(contracts.EventRunCreated, nil); err == nil {
		t.Fatal("nil data must be rejected")
	}
	if _, err := sink.Emit(contracts.EventStepStarted, map[string]any{
		"step": "classify", "payload": math.NaN()}); err == nil {
		t.Fatal("non-finite payload numbers must be rejected")
	}
	events := sink.Events()
	if len(events) != 0 {
		t.Fatalf("rejected events must not be recorded, got %d", len(events))
	}
}

func TestWriteJSONL(t *testing.T) {
	sink := NewEventSink("run-1")
	for _, eventType := range []contracts.EventType{contracts.EventRunCreated, contracts.EventRunStarted} {
		if _, err := sink.Emit(eventType, map[string]any{"case_id": "c", "mode": "model"}); err != nil {
			t.Fatalf("Emit: %v", err)
		}
	}
	path := filepath.Join(t.TempDir(), "traces", "run.jsonl")
	if err := WriteJSONL(path, sink.Events()); err != nil {
		t.Fatalf("WriteJSONL: %v", err)
	}
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read trace: %v", err)
	}
	if !strings.HasSuffix(string(content), "\n") {
		t.Fatal("JSONL must end with a newline")
	}
	lines := strings.Split(strings.TrimSuffix(string(content), "\n"), "\n")
	if len(lines) != 2 {
		t.Fatalf("JSONL lines: %d", len(lines))
	}
	for i, line := range lines {
		event, err := contracts.DecodeEvent([]byte(line))
		if err != nil {
			t.Fatalf("line %d does not strict-decode: %v", i+1, err)
		}
		if event.Sequence != i+1 {
			t.Fatalf("line %d sequence: %d", i+1, event.Sequence)
		}
	}
}
