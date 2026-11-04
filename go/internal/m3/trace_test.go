package m3

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

func TestM3EventSinkEmitsEnvelope(t *testing.T) {
	sink := NewEventSink("run-1")
	if _, err := sink.Emit(contracts.EventRunCreated, map[string]any{
		"scenario_id": "order-brief", "case_id": "c", "execution_mode": "parallel",
		"order_id": "ORD-1001", "concurrency_limit": 2}); err != nil {
		t.Fatalf("Emit: %v", err)
	}
	events := sink.Events()
	if len(events) != 1 {
		t.Fatalf("events: %d", len(events))
	}
	event := events[0]
	if event.SchemaVersion != contracts.EnvelopeVersion || event.Source != contracts.SourceGo ||
		event.Sequence != 1 || event.Type != contracts.EventRunCreated {
		t.Fatalf("envelope: %+v", event)
	}
	if _, err := sink.Emit(contracts.EventType("mystery.event"), map[string]any{}); err == nil {
		t.Fatal("events outside the envelope enum must be rejected")
	}
	if _, err := sink.Emit(contracts.EventRunStarted, nil); err == nil {
		t.Fatal("nil data must be rejected")
	}
	if len(sink.Events()) != 1 {
		t.Fatal("rejected events must not be recorded")
	}
}

func TestM3WriteJSONL(t *testing.T) {
	sink := NewEventSink("run-1")
	for _, data := range []map[string]any{{"case_id": "c"}, {"case_id": "d"}} {
		if _, err := sink.Emit(contracts.EventRunStarted, data); err != nil {
			t.Fatalf("Emit: %v", err)
		}
	}
	path := filepath.Join(t.TempDir(), "nested", "trace.jsonl")
	if err := WriteJSONL(path, sink.Events()); err != nil {
		t.Fatalf("WriteJSONL: %v", err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read trace: %v", err)
	}
	content := string(raw)
	if !strings.HasSuffix(content, "\n") {
		t.Fatal("JSONL must end with a newline")
	}
	if _, err := contracts.DecodeEvent(raw); !errors.Is(err, contracts.ErrTrailingData) {
		t.Fatalf("the whole multi-event file must fail strict decode, got %v", err)
	}
	lines := strings.Split(strings.TrimSuffix(content, "\n"), "\n")
	if len(lines) != 2 {
		t.Fatalf("JSONL lines: %d", len(lines))
	}
	for i, line := range lines {
		if _, err := contracts.DecodeEvent([]byte(line)); err != nil {
			t.Fatalf("line %d strict decode: %v", i+1, err)
		}
	}
}
