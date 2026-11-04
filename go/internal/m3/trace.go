package m3

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// EventSink records the run's trace events in memory and flushes them as
// JSONL — the m3-local copy of the m0 sink (envelope 1.0, source "go",
// deterministic event ids from the sequence).
type EventSink struct {
	runID    string
	source   string
	events   []contracts.Event
	sequence int
	now      func() time.Time
}

// NewEventSink starts an empty trace for the run.
func NewEventSink(runID string) *EventSink {
	return &EventSink{runID: runID, source: contracts.SourceGo, now: time.Now}
}

// Events returns a copy of the recorded events.
func (s *EventSink) Events() []contracts.Event {
	return append([]contracts.Event(nil), s.events...)
}

// Emit validates and appends one event, assigning the next sequence number.
func (s *EventSink) Emit(eventType contracts.EventType, data map[string]any) (contracts.Event, error) {
	if data == nil {
		return contracts.Event{}, fmt.Errorf("m3: event %s data must be a JSON object", eventType)
	}
	if !eventType.Valid() {
		return contracts.Event{}, fmt.Errorf("m3: event type %q is outside the envelope enum", eventType)
	}
	if _, err := json.Marshal(data); err != nil {
		return contracts.Event{}, fmt.Errorf("m3: event %s data is not JSON-safe: %w", eventType, err)
	}
	s.sequence++
	event := contracts.Event{
		SchemaVersion: contracts.EnvelopeVersion,
		EventID:       fmt.Sprintf("evt-%d", s.sequence),
		RunID:         s.runID,
		Sequence:      s.sequence,
		Type:          eventType,
		Timestamp:     s.now().UTC().Format("2006-01-02T15:04:05.000Z"),
		Source:        s.source,
		Data:          data,
	}
	s.events = append(s.events, event)
	return event, nil
}

// WriteJSONL flushes the events as one compact JSON object per line with a
// trailing newline, creating the parent directory when needed.
func WriteJSONL(path string, events []contracts.Event) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("m3: create trace directory: %w", err)
	}
	content := make([]byte, 0, 512*len(events))
	for _, event := range events {
		line, err := json.Marshal(event)
		if err != nil {
			return fmt.Errorf("m3: marshal event %s: %w", event.EventID, err)
		}
		content = append(content, line...)
		content = append(content, '\n')
	}
	if err := os.WriteFile(path, content, 0o644); err != nil {
		return fmt.Errorf("m3: write trace: %w", err)
	}
	return nil
}
