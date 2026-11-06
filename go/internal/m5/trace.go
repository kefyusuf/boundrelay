package m5

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// EventSink records the run's trace events in memory and flushes them as
// JSONL — the m5-local copy of the m0-m4 sink (envelope 1.0, source "go",
// deterministic event ids from the sequence).
type EventSink struct {
	mutex    sync.Mutex
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
	s.mutex.Lock()
	defer s.mutex.Unlock()
	return append([]contracts.Event(nil), s.events...)
}

// Emit validates and appends one event, assigning the next sequence number.
func (s *EventSink) Emit(eventType contracts.EventType, data map[string]any) (contracts.Event, error) {
	if data == nil {
		return contracts.Event{}, fmt.Errorf("m5: event %s data must be a JSON object", eventType)
	}
	if !eventType.Valid() {
		return contracts.Event{}, fmt.Errorf("m5: event type %q is outside the envelope enum", eventType)
	}
	if _, err := json.Marshal(data); err != nil {
		return contracts.Event{}, fmt.Errorf("m5: event %s data is not JSON-safe: %w", eventType, err)
	}
	s.mutex.Lock()
	defer s.mutex.Unlock()
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

// Flush writes the recorded events as one compact JSON object per line with
// a trailing newline, creating the parent directory when needed. The crash
// control flushes explicitly before the hard exit.
func (s *EventSink) Flush(path string) error {
	s.mutex.Lock()
	events := append([]contracts.Event(nil), s.events...)
	s.mutex.Unlock()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("m5: create trace directory: %w", err)
	}
	content := make([]byte, 0, 512*len(events))
	for _, event := range events {
		line, err := json.Marshal(event)
		if err != nil {
			return fmt.Errorf("m5: marshal event %s: %w", event.EventID, err)
		}
		content = append(content, line...)
		content = append(content, '\n')
	}
	if err := os.WriteFile(path, content, 0o644); err != nil {
		return fmt.Errorf("m5: write trace: %w", err)
	}
	return nil
}

// ReadTrace reads back a flushed JSONL trace (the harness and the parity
// tests consume phase traces from disk).
func ReadTrace(path string) ([]contracts.Event, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("m5: read trace: %w", err)
	}
	lines := splitLines(string(raw))
	events := make([]contracts.Event, 0, len(lines))
	for index, line := range lines {
		event, err := contracts.DecodeEvent([]byte(line))
		if err != nil {
			return nil, fmt.Errorf("m5: trace line %d: %w", index+1, err)
		}
		events = append(events, event)
	}
	return events, nil
}

func splitLines(text string) []string {
	var lines []string
	start := 0
	for index, character := range text {
		if character == '\n' {
			if line := text[start:index]; line != "" {
				lines = append(lines, line)
			}
			start = index + 1
		}
	}
	if line := text[start:]; line != "" {
		lines = append(lines, line)
	}
	return lines
}
