package m4

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// State schema identities and step/run statuses
// (contracts/state/order-brief-run-state.schema.json).
const (
	StateSchemaVersion = "1.0"
	ScenarioID         = "order-brief-recovery"

	StepStatusPending   = "PENDING"
	StepStatusRunning   = "RUNNING"
	StepStatusSucceeded = "SUCCEEDED"
	StepStatusFailed    = "FAILED"
	StepStatusCancelled = "CANCELLED"

	RunStateStatusRunning   = "RUNNING"
	RunStateStatusCancelled = "CANCELLED"
	RunStateSucceeded       = "SUCCEEDED"
	RunStatePartial         = "PARTIAL"
	RunStateFailed          = "FAILED"
)

// StateLoadReason enumerates the fixed fail-closed load failures.
type StateLoadReason string

// The closed set of load reasons, in check order.
const (
	ReasonTruncated       StateLoadReason = "TRUNCATED"
	ReasonUnknownVersion  StateLoadReason = "UNKNOWN_VERSION"
	ReasonSchemaInvalid   StateLoadReason = "SCHEMA_INVALID"
	ReasonDigestMismatch  StateLoadReason = "DIGEST_MISMATCH"
	ReasonBindingMismatch StateLoadReason = "BINDING_MISMATCH"
	ReasonMissingSnapshot StateLoadReason = "MISSING_SNAPSHOT"
)

// StateLoadError is the fail-closed run-state load failure.
type StateLoadError struct {
	Reason  StateLoadReason
	Detail  string
	runID   string
	caseID  string
	fromDoc bool
}

func (e *StateLoadError) Error() string {
	if e.fromDoc {
		return fmt.Sprintf("Run state load failed: %s (run_id=%s case_id=%s)", e.Reason, e.runID, e.caseID)
	}
	return fmt.Sprintf("Run state load failed: %s (%s)", e.Reason, e.Detail)
}

func loadErrorf(reason StateLoadReason, format string, args ...any) *StateLoadError {
	return &StateLoadError{Reason: reason, Detail: fmt.Sprintf(format, args...)}
}

func documentErrorf(reason StateLoadReason, runID, caseID string) *StateLoadError {
	return &StateLoadError{Reason: reason, runID: runID, caseID: caseID, fromDoc: true}
}

// StepRecord is one worker's recorded step in the run-state document. Output
// carries the succeeded output (null otherwise); FailureCode carries the
// failure code for FAILED steps (null otherwise).
type StepRecord struct {
	WorkerID    string          `json:"worker_id"`
	Status      string          `json:"status"`
	Output      json.RawMessage `json:"output"`
	FailureCode *string         `json:"failure_code"`
}

// RunStateDocument is the typed, digest-protected durable state document.
type RunStateDocument struct {
	StateSchemaVersion string        `json:"state_schema_version"`
	RunID              string        `json:"run_id"`
	ScenarioID         string        `json:"scenario_id"`
	CaseID             string        `json:"case_id"`
	ExecutionMode      string        `json:"execution_mode"`
	ConcurrencyLimit   int           `json:"concurrency_limit"`
	RequestedOrderID   string        `json:"requested_order_id"`
	Status             string        `json:"status"`
	Steps              [3]StepRecord `json:"steps"`
	SequenceCursor     int           `json:"sequence_cursor"`
	Digest             string        `json:"digest"`
}

// StateBinding is the identity a state document must match on resume.
type StateBinding struct {
	CaseID           string
	ExecutionMode    string
	RequestedOrderID string
	ConcurrencyLimit int
}

// recordedStep reports whether the step carries a recorded terminal outcome.
func recordedStep(step StepRecord) bool {
	return step.Status == StepStatusSucceeded || step.Status == StepStatusFailed
}

// canonicalJSON serializes the value with sorted object keys, compact
// separators, no HTML escaping, and number literals preserved — the digest's
// canonical form.
func canonicalJSON(value any) (string, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var tree any
	if err := decoder.Decode(&tree); err != nil {
		return "", err
	}
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(tree); err != nil {
		return "", err
	}
	return strings.TrimSuffix(buffer.String(), "\n"), nil
}

// canonicalStateBody is the canonical JSON of the document without its
// digest field.
func canonicalStateBody(document RunStateDocument) (string, error) {
	raw, err := json.Marshal(document)
	if err != nil {
		return "", err
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var body map[string]any
	if err := decoder.Decode(&body); err != nil {
		return "", err
	}
	delete(body, "digest")
	return canonicalJSON(body)
}

// stateDigest is the SHA-256 hex digest of the canonical body.
func stateDigest(body string) string {
	sum := sha256.Sum256([]byte(body))
	return fmt.Sprintf("%x", sum)
}

// validateRunStateDocument mirrors the closed state schema: exact header and
// identity fields, bounded mode/limit/status enums, three canonical step
// records whose shapes branch on their status, and a bounded cursor.
func validateRunStateDocument(document RunStateDocument) error {
	switch {
	case document.StateSchemaVersion != StateSchemaVersion:
		return errors.New("state_schema_version must be 1.0")
	case document.RunID == "" || document.CaseID == "":
		return errors.New("run_id and case_id must be nonempty")
	case document.ScenarioID != ScenarioID:
		return errors.New("scenario_id must be order-brief-recovery")
	case document.ExecutionMode != ModeSequential && document.ExecutionMode != ModeParallel:
		return errors.New("execution_mode is outside the enum")
	case document.ConcurrencyLimit != 1 && document.ConcurrencyLimit != 2:
		return errors.New("concurrency_limit must be 1 or 2")
	case !orderIDPattern.MatchString(document.RequestedOrderID):
		return errors.New("requested_order_id is invalid")
	case !runStateStatusValid(document.Status):
		return errors.New("status is outside the enum")
	case document.SequenceCursor < 0 || document.SequenceCursor > 3:
		return errors.New("sequence_cursor is out of bounds")
	}
	for index, step := range document.Steps {
		if step.WorkerID != contracts.CanonicalWorkerIDs[index] {
			return fmt.Errorf("step %d is not the canonical worker", index)
		}
		if err := validateStepRecord(step); err != nil {
			return fmt.Errorf("step %d: %w", index, err)
		}
	}
	return nil
}

func runStateStatusValid(status string) bool {
	switch status {
	case RunStateStatusRunning, RunStateSucceeded, RunStatePartial,
		RunStateFailed, RunStateStatusCancelled:
		return true
	}
	return false
}

func validateStepRecord(step StepRecord) error {
	switch step.Status {
	case StepStatusPending, StepStatusRunning, RunStateStatusCancelled:
		if step.Output != nil || step.FailureCode != nil {
			return errors.New("unset steps carry no output or failure code")
		}
	case StepStatusFailed:
		if step.Output != nil {
			return errors.New("failed steps carry no output")
		}
		if step.FailureCode == nil || (*step.FailureCode != contracts.FailureWorkerExecutionFailed &&
			*step.FailureCode != contracts.FailureInvalidWorkerOutput) {
			return errors.New("failed steps carry a declared failure code")
		}
	case StepStatusSucceeded:
		// The closed state schema validates the output shape and its
		// well-formed order id; it does not bind it to the run's order id.
		if step.FailureCode != nil {
			return errors.New("succeeded steps carry no failure code")
		}
		if _, ok := workerOutputOrderID(step.WorkerID, step.Output); !ok {
			return errors.New("succeeded steps carry a validated output")
		}
	default:
		return errors.New("status is outside the enum")
	}
	return nil
}

// loadRunStateDocument reads, validates, digest-checks, and binding-checks
// one run-state document, failing closed with the fixed reason order
// TRUNCATED -> UNKNOWN_VERSION -> SCHEMA_INVALID -> DIGEST_MISMATCH ->
// BINDING_MISMATCH.
func loadRunStateDocument(path string, expectedBinding StateBinding) (RunStateDocument, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return RunStateDocument{}, loadErrorf(ReasonTruncated, "run state document is not readable")
	}
	return decodeRunStateDocument(raw, expectedBinding)
}

func decodeRunStateDocument(raw []byte, expectedBinding StateBinding) (RunStateDocument, error) {
	var header struct {
		StateSchemaVersion *string `json:"state_schema_version"`
	}
	// A document that is not JSON at all is TRUNCATED; one that parses but
	// carries the wrong or missing version is UNKNOWN_VERSION.
	var probe any
	if err := json.Unmarshal(raw, &probe); err != nil {
		return RunStateDocument{}, loadErrorf(ReasonTruncated, "run state document is not valid JSON")
	}
	_ = json.Unmarshal(raw, &header)
	if probe == nil || header.StateSchemaVersion == nil || *header.StateSchemaVersion != StateSchemaVersion {
		return RunStateDocument{}, loadErrorf(ReasonUnknownVersion, "missing or unsupported state_schema_version")
	}
	var document RunStateDocument
	if err := contracts.DecodeStrict(raw, &document); err != nil {
		return RunStateDocument{}, loadErrorf(ReasonSchemaInvalid, "run state document failed the closed schema")
	}
	normalizeStepOutputs(&document)
	if err := validateRunStateDocument(document); err != nil {
		return RunStateDocument{}, loadErrorf(ReasonSchemaInvalid, "run state document failed the closed schema: %v", err)
	}
	body, err := canonicalStateBody(document)
	if err != nil {
		return RunStateDocument{}, loadErrorf(ReasonSchemaInvalid, "canonical body failed: %v", err)
	}
	if document.Digest != stateDigest(body) {
		return RunStateDocument{}, documentErrorf(ReasonDigestMismatch, document.RunID, document.CaseID)
	}
	if document.CaseID != expectedBinding.CaseID ||
		document.ExecutionMode != expectedBinding.ExecutionMode ||
		document.RequestedOrderID != expectedBinding.RequestedOrderID ||
		document.ConcurrencyLimit != expectedBinding.ConcurrencyLimit {
		return RunStateDocument{}, documentErrorf(ReasonBindingMismatch, document.RunID, document.CaseID)
	}
	return document, nil
}

// LoadedRunState is one successful loadRunState: the validated document and
// the path it was restored from.
type LoadedRunState struct {
	Document     RunStateDocument
	RestoredFrom string
}

// loadRunState discovers the run's state document under the state root —
// either flat or under the single run directory — verifies an immutable
// snapshot for every recorded step, and fails closed when the layout or the
// evidence is wrong.
func loadRunState(stateRoot string, expectedBinding StateBinding) (LoadedRunState, error) {
	flat := filepath.Join(stateRoot, "state.json")
	var paths []string
	if fileExists(flat) {
		paths = append(paths, flat)
	} else {
		entries, err := os.ReadDir(stateRoot)
		if err != nil {
			return LoadedRunState{}, fmt.Errorf("m4: read state root: %w", err)
		}
		for _, entry := range entries {
			candidate := filepath.Join(stateRoot, entry.Name(), "state.json")
			if fileExists(candidate) {
				paths = append(paths, candidate)
			}
		}
		sort.Strings(paths)
	}
	if len(paths) != 1 {
		return LoadedRunState{}, fmt.Errorf("m4: expected exactly one run state document under %s, found %d",
			stateRoot, len(paths))
	}
	path := paths[0]
	document, err := loadRunStateDocument(path, expectedBinding)
	if err != nil {
		return LoadedRunState{}, err
	}
	for index, step := range document.Steps {
		if !recordedStep(step) {
			continue
		}
		snapshot := filepath.Join(stateRoot, document.RunID, "checkpoints",
			fmt.Sprintf("step-%d.json", index+1))
		if err := verifySnapshot(snapshot, index+1, document.RunID); err != nil {
			return LoadedRunState{}, err
		}
	}
	return LoadedRunState{Document: document, RestoredFrom: path}, nil
}

// verifySnapshot proves the immutable checkpoint for a recorded step exists
// and is a valid, digest-intact state document.
func verifySnapshot(path string, seq int, runID string) error {
	missing := func(detail string) error {
		return loadErrorf(ReasonMissingSnapshot, "checkpoint step-%d for run_id=%s: %s", seq, runID, detail)
	}
	if !fileExists(path) {
		return missing("missing")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return missing("unreadable")
	}
	var header struct {
		StateSchemaVersion *string `json:"state_schema_version"`
	}
	var probe any
	if err := json.Unmarshal(raw, &probe); err != nil || probe == nil {
		return missing("invalid")
	}
	_ = json.Unmarshal(raw, &header)
	if header.StateSchemaVersion == nil || *header.StateSchemaVersion != StateSchemaVersion {
		return missing("invalid")
	}
	var snapshot RunStateDocument
	if err := contracts.DecodeStrict(raw, &snapshot); err != nil {
		return missing("invalid")
	}
	normalizeStepOutputs(&snapshot)
	if err := validateRunStateDocument(snapshot); err != nil {
		return missing("invalid")
	}
	body, err := canonicalStateBody(snapshot)
	if err != nil || snapshot.Digest != stateDigest(body) {
		return missing("invalid")
	}
	return nil
}

// normalizeStepOutputs folds the JSON null literal back into a nil
// RawMessage: an encoded document writes "output":null, and decoding keeps
// those four literal bytes, which must not read as a present output.
func normalizeStepOutputs(document *RunStateDocument) {
	for index := range document.Steps {
		if string(document.Steps[index].Output) == "null" {
			document.Steps[index].Output = nil
		}
	}
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
