package m4

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// StateStore owns one run's durable state document: write-ahead step
// records under the state root (<root>/<run_id>/state.json), an immutable
// snapshot per recorded terminal (checkpoints/step-<seq>.json), and atomic
// temporary-file-plus-rename writes. The Ruling-2 sequence cursor — the
// recorded-terminal count — is recomputed on every flush. All methods must
// be called from the run's orchestrating goroutine, mirroring the TS/Python
// single-threaded store.
type StateStore struct {
	root     string
	binding  StateBinding
	document RunStateDocument
}

// NewStateStore creates the store: a fresh RUNNING document seeded with the
// queue's PENDING steps (a new Ruling-2 run), or a resume re-anchored on the
// loaded document with its recorded evidence intact.
func NewStateStore(root string, binding StateBinding, queue []string, runID string, seed *RunStateDocument) (*StateStore, error) {
	store := &StateStore{root: root, binding: binding}
	if seed != nil {
		document := *seed
		document.Status = RunStateStatusRunning
		store.document = document
	} else {
		if runID == "" {
			id, err := newUUID()
			if err != nil {
				return nil, err
			}
			runID = id
		}
		document := RunStateDocument{
			StateSchemaVersion: StateSchemaVersion,
			RunID:              runID,
			ScenarioID:         ScenarioID,
			CaseID:             binding.CaseID,
			ExecutionMode:      binding.ExecutionMode,
			ConcurrencyLimit:   binding.ConcurrencyLimit,
			RequestedOrderID:   binding.RequestedOrderID,
			Status:             RunStateStatusRunning,
			SequenceCursor:     0,
		}
		for _, id := range queue {
			document.Steps[workerIndex(id)] = StepRecord{WorkerID: id, Status: StepStatusPending}
		}
		store.document = document
	}
	if err := os.MkdirAll(filepath.Dir(store.statePath()), 0o755); err != nil {
		return nil, fmt.Errorf("m4: create state directory: %w", err)
	}
	if err := os.MkdirAll(filepath.Dir(store.snapshotPath(1)), 0o755); err != nil {
		return nil, fmt.Errorf("m4: create checkpoint directory: %w", err)
	}
	if err := store.flush(0); err != nil {
		return nil, err
	}
	return store, nil
}

// CreateStore starts a fresh run state for the binding and queue.
func CreateStore(root string, binding StateBinding, queue []string) (*StateStore, error) {
	return NewStateStore(root, binding, queue, "", nil)
}

// ResumeStore re-anchors a store on a loaded document, writing back under
// the run's own directory.
func ResumeStore(document RunStateDocument, statePath string) (*StateStore, error) {
	dir := filepath.Dir(statePath)
	root := dir
	if filepath.Base(dir) == document.RunID {
		root = filepath.Dir(dir)
	}
	binding := StateBinding{CaseID: document.CaseID, ExecutionMode: document.ExecutionMode,
		RequestedOrderID: document.RequestedOrderID, ConcurrencyLimit: document.ConcurrencyLimit}
	return NewStateStore(root, binding, nil, document.RunID, &document)
}

// State returns a copy of the current document.
func (s *StateStore) State() RunStateDocument {
	document := s.document
	for index, step := range document.Steps {
		if step.Output != nil {
			document.Steps[index].Output = append(jsonRaw(nil), step.Output...)
		}
	}
	return document
}

// StatePath is the document's durable path.
func (s *StateStore) StatePath() string { return s.statePath() }

// SnapshotPath is the immutable checkpoint path for one recorded terminal.
func (s *StateStore) SnapshotPath(seq int) string { return s.snapshotPath(seq) }

// RunID returns the document's run id.
func (s *StateStore) RunID() string { return s.document.RunID }

func (s *StateStore) statePath() string {
	return filepath.Join(s.root, s.document.RunID, "state.json")
}

func (s *StateStore) snapshotPath(seq int) string {
	return filepath.Join(s.root, s.document.RunID, "checkpoints", fmt.Sprintf("step-%d.json", seq))
}

// MarkRunning is the write-ahead admission: the worker is RUNNING in the
// document before its body starts.
func (s *StateStore) MarkRunning(worker string) error {
	step := &s.document.Steps[workerIndex(worker)]
	step.Status = StepStatusRunning
	return s.flush(0)
}

// RecordStepTerminal writes the settled outcome (write-ahead: before the
// next admission) and snapshots the document at the step's sequence.
func (s *StateStore) RecordStepTerminal(worker string, outcome WorkerOutcome) error {
	step := &s.document.Steps[workerIndex(worker)]
	if outcome.Status == StatusSucceeded {
		step.Status = StepStatusSucceeded
		step.Output = append(jsonRaw(nil), outcome.Output...)
		step.FailureCode = nil
	} else {
		step.Status = StepStatusFailed
		step.Output = nil
		step.FailureCode = strPtr(deref(outcome.FailureCode))
	}
	return s.flush(workerIndex(worker) + 1)
}

// MarkCancelledFrom records the deterministic cancellation: every step from
// the cancelled worker on that carries no recorded terminal becomes
// CANCELLED.
func (s *StateStore) MarkCancelledFrom(worker string) error {
	from := workerIndex(worker)
	for index := range s.document.Steps {
		if index >= from && !recordedStep(s.document.Steps[index]) {
			s.document.Steps[index].Status = StepStatusCancelled
		}
	}
	return s.flush(0)
}

// MarkTerminal closes the document with the run's terminal status; FAILED
// requires the ALL_WORKERS_FAILED code.
func (s *StateStore) MarkTerminal(status string, failureCode string) error {
	if status == RunStateFailed && failureCode != contracts.FailureAllWorkersFailed {
		return errors.New("m4: invalid terminal failure code")
	}
	s.document.Status = status
	return s.flush(0)
}

// flush recomputes the Ruling-2 cursor, seals the digest, validates the
// closed document, and atomically writes the state (plus the snapshot when
// a step terminal was recorded).
func (s *StateStore) flush(snapshotSeq int) error {
	cursor := 0
	for _, step := range s.document.Steps {
		if recordedStep(step) {
			cursor++
		}
	}
	s.document.SequenceCursor = cursor
	body, err := canonicalStateBody(s.document)
	if err != nil {
		return fmt.Errorf("m4: canonical state body: %w", err)
	}
	s.document.Digest = stateDigest(body)
	if err := validateRunStateDocument(s.document); err != nil {
		return fmt.Errorf("m4: invalid run state document: %w", err)
	}
	content, err := canonicalJSON(s.document)
	if err != nil {
		return fmt.Errorf("m4: canonical state document: %w", err)
	}
	if err := writeAtomic(s.statePath(), content); err != nil {
		return err
	}
	if snapshotSeq > 0 {
		if err := writeAtomic(s.snapshotPath(snapshotSeq), content); err != nil {
			return err
		}
	}
	return nil
}

// writeAtomic writes content via a temporary file plus rename so a crash
// never leaves a torn document behind.
func writeAtomic(path string, content string) error {
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, []byte(content), 0o644); err != nil {
		return fmt.Errorf("m4: atomic write: %w", err)
	}
	if err := os.Rename(tmp, path); err != nil {
		os.Remove(tmp)
		return fmt.Errorf("m4: atomic rename: %w", err)
	}
	return nil
}
