package m3

import (
	"encoding/json"
	"errors"
	"fmt"
	"sync"
)

// ScriptedWorkers is the deterministic offline worker provider: it admits
// bodies exactly once with the isolated input, releases completion gates in
// the case's scripted order (parallel runs hold the first completion until
// both leading workers have entered), and drains every entered gate on
// BeginDrain. It is both the WorkerProvider and the WorkerControl, exactly
// like the TS/Python fake.
type ScriptedWorkers struct {
	spec    CaseSpec
	orderID string
	fixture WorkerInstructions

	mu          sync.Mutex
	gates       map[string]chan struct{}
	entered     map[string]bool
	cursor      int
	awaitingAck bool
	draining    bool
}

// NewScriptedWorkers builds the scripted provider for one case.
func NewScriptedWorkers(spec CaseSpec, orderID string, fixture WorkerInstructions) *ScriptedWorkers {
	return &ScriptedWorkers{
		spec: spec, orderID: orderID, fixture: fixture,
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
	if s.cursor >= len(s.spec.CompletionOrder) {
		return
	}
	id := s.spec.CompletionOrder[s.cursor]
	if s.awaitingAck || !s.entered[id] {
		return
	}
	if s.cursor == 0 && s.spec.ExecutionMode == ModeParallel && len(s.entered) < 2 {
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
		return nil, errors.New("m3: invalid worker invocation")
	}
	s.entered[id] = true
	gate := make(chan struct{})
	s.gates[id] = gate
	s.pumpLocked()
	s.mu.Unlock()

	<-gate
	instruction, ok := s.fixture[id]
	if !ok {
		return nil, fmt.Errorf("m3: worker %s missing from fixture", id)
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
	if !s.awaitingAck || s.cursor >= len(s.spec.CompletionOrder) ||
		s.spec.CompletionOrder[s.cursor] != id {
		return errors.New("m3: invalid outcome acknowledgement")
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
