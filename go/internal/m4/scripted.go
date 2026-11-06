package m4

import (
	"encoding/json"
	"errors"
	"fmt"
	"sync"
)

// ScriptedWorkers is the deterministic offline worker provider: it admits
// bodies exactly once with the isolated input, releases completion gates in
// the scripted order (parallel runs hold the first completion until both
// leading workers have entered), and drains every entered gate on
// BeginDrain. It is both the WorkerProvider and the WorkerControl, exactly
// like the TS/Python fake. Resume and replay construct it from the
// filtered, possibly-sequential scripted spec.
type ScriptedWorkers struct {
	executionMode   string
	completionOrder []string
	orderID         string
	fixture         WorkerInstructions

	mu          sync.Mutex
	gates       map[string]chan struct{}
	entered     map[string]bool
	cursor      int
	awaitingAck bool
	draining    bool
}

// NewScriptedWorkers builds the scripted provider for one scripted run
// shape (mode plus the completion order actually in play).
func NewScriptedWorkers(executionMode string, completionOrder []string, orderID string, fixture WorkerInstructions) *ScriptedWorkers {
	return &ScriptedWorkers{
		executionMode: executionMode, completionOrder: append([]string(nil), completionOrder...),
		orderID: orderID, fixture: fixture,
		gates: map[string]chan struct{}{}, entered: map[string]bool{},
	}
}

// pumpLocked releases the next scripted gate (all gates when draining).
func (s *ScriptedWorkers) pumpLocked() {
	if s.draining {
		for id, gate := range s.gates {
			close(gate)
			delete(s.gates, id)
		}
		return
	}
	if s.cursor >= len(s.completionOrder) {
		return
	}
	id := s.completionOrder[s.cursor]
	if s.awaitingAck || !s.entered[id] {
		return
	}
	if s.cursor == 0 && s.executionMode == ModeParallel && len(s.entered) < 2 {
		return
	}
	s.awaitingAck = true
	close(s.gates[id])
	delete(s.gates, id)
}

// Read runs one scripted worker body: once-only, isolated-input-checked,
// gated until its scripted turn (or a drain).
func (s *ScriptedWorkers) Read(id string, input WorkerInput) (json.RawMessage, error) {
	s.mu.Lock()
	if s.draining || s.entered[id] || input.OrderID != s.orderID {
		s.mu.Unlock()
		return nil, errors.New("m4: invalid worker invocation")
	}
	s.entered[id] = true
	gate := make(chan struct{})
	s.gates[id] = gate
	s.pumpLocked()
	s.mu.Unlock()

	<-gate
	instruction, ok := s.fixture[id]
	if !ok {
		return nil, fmt.Errorf("m4: worker %s missing from fixture", id)
	}
	if instruction.Operation == "raise" {
		return nil, fmt.Errorf("%w: %s declared failure", ErrWorkerExecution, id)
	}
	return append(json.RawMessage(nil), instruction.Output...), nil
}

// AcknowledgeOutcome advances the scripted cursor after the executor
// settles the worker the schedule names next.
func (s *ScriptedWorkers) AcknowledgeOutcome(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.draining {
		return nil
	}
	if !s.awaitingAck || s.cursor >= len(s.completionOrder) ||
		s.completionOrder[s.cursor] != id {
		return errors.New("m4: invalid outcome acknowledgement")
	}
	delete(s.gates, id)
	s.cursor++
	s.awaitingAck = false
	s.pumpLocked()
	return nil
}

// BeginDrain releases every entered gate; further invocations are rejected.
func (s *ScriptedWorkers) BeginDrain() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.draining = true
	s.pumpLocked()
}
