package m5

import (
	"fmt"
)

// RecoveryError is the fail-closed recovery failure: only RUNNING runs with
// an effect decision to resolve are recoverable.
type RecoveryError struct {
	Message string
}

func (e *RecoveryError) Error() string { return e.Message }

func recoveryErrorf(format string, args ...any) *RecoveryError {
	return &RecoveryError{Message: fmt.Sprintf(format, args...)}
}

// RecoveryOptions configures one submit-window recovery: the recorded run's
// state root and binding, the effect sink, the audit writer, and the
// sink_unavailable control.
type RecoveryOptions struct {
	StateRoot string
	Binding   StateBinding
	Ledger    *EffectLedger
	Audit     *AuditWriter
	Controls  *EffectControls
}

// RecoveryResult is the recovery answer: the terminal status, whether the
// effect was adopted from the ledger (reconciled, zero submits), the
// effect of record, the idempotency key, and the recorded reads.
type RecoveryResult struct {
	Status         string
	Reconciled     bool
	Effect         *EffectRecord
	IdempotencyKey string
	Reads          []WorkerOutcome
}

// recordedReads rebuilds the recorded worker outcomes from a document, in
// canonical step order.
func recordedReads(document RunStateDocument) []WorkerOutcome {
	reads := []WorkerOutcome{}
	for _, step := range document.Steps {
		if !recordedStep(step) {
			continue
		}
		outcome := WorkerOutcome{WorkerID: step.WorkerID, Status: step.Status,
			Output: append(jsonRaw(nil), step.Output...), FailureCode: step.FailureCode}
		if step.Output == nil {
			outcome.Output = nil
		}
		reads = append(reads, outcome)
	}
	return reads
}

// ResumeRun resolves one submit-window crash: the submit marker (written
// before the ledger submit) names the key the run committed to. The
// resolution is strict:
//
//   - a settled effect of record closes the run SUCCEEDED without any sink
//     interaction;
//   - sink_unavailable marks the run UNKNOWN — a terminal state that is
//     never flattened to SUCCEEDED or FAILED;
//   - a landed ledger record is adopted (reconciled: true, zero submits);
//   - otherwise the payload is submitted exactly once.
func ResumeRun(options RecoveryOptions) (RecoveryResult, error) {
	loaded, err := loadRunState(options.StateRoot, options.Binding)
	if err != nil {
		return RecoveryResult{}, err
	}
	document := loaded.Document
	if document.Status != RunStateStatusRunning {
		return RecoveryResult{}, recoveryErrorf(
			"m5: run state is not resumable (run_id=%s status=%s)", document.RunID, document.Status)
	}
	store, err := ResumeStore(document, loaded.RestoredFrom)
	if err != nil {
		return RecoveryResult{}, err
	}
	reads := recordedReads(document)
	payload := EffectPayloadOf(options.Binding.RequestedOrderID)
	key := EffectKey(payload)
	if document.Effect != nil {
		if err := store.MarkTerminal(RunStateSucceeded, ""); err != nil {
			return RecoveryResult{}, err
		}
		return RecoveryResult{Status: RunStateSucceeded, Reconciled: false,
			Effect: document.Effect, IdempotencyKey: document.Effect.Key, Reads: reads}, nil
	}
	marker := document.SubmitMarker
	if marker == nil {
		return RecoveryResult{}, recoveryErrorf(
			"m5: run state has no effect decision to resolve (run_id=%s)", document.RunID)
	}
	digest, err := EffectDigest(payload)
	if err != nil {
		return RecoveryResult{}, err
	}
	if marker.Key != key || marker.PayloadDigest != digest {
		return RecoveryResult{}, recoveryErrorf(
			"m5: effect binding mismatch (run_id=%s)", document.RunID)
	}
	if options.Controls != nil && options.Controls.SinkUnavailable {
		if err := store.MarkTerminal(RunStateUnknown, ""); err != nil {
			return RecoveryResult{}, err
		}
		return RecoveryResult{Status: RunStateUnknown, Reconciled: false,
			Effect: nil, IdempotencyKey: key, Reads: reads}, nil
	}
	found, err := options.Ledger.lookup(key)
	if err != nil {
		return RecoveryResult{}, err
	}
	if found != nil {
		adopted := EffectRecord{Key: key, PayloadDigest: marker.PayloadDigest,
			Status: found.Status, Outcome: found.Outcome, Duplicate: false}
		if err := store.RecordEffectOutcome(adopted); err != nil {
			return RecoveryResult{}, err
		}
		if options.Audit != nil {
			if err := options.Audit.Append(EffectAuditRecord{Kind: "effect",
				Operation: EffectOperation, OrderID: options.Binding.RequestedOrderID,
				IdempotencyKey: key, EffectStatus: found.Status, Duplicate: false}); err != nil {
				return RecoveryResult{}, err
			}
		}
		if err := store.MarkTerminal(RunStateSucceeded, ""); err != nil {
			return RecoveryResult{}, err
		}
		return RecoveryResult{Status: RunStateSucceeded, Reconciled: true,
			Effect: &adopted, IdempotencyKey: key, Reads: reads}, nil
	}
	submitted, err := options.Ledger.submit(key, marker.PayloadDigest, payload)
	if err != nil {
		return RecoveryResult{}, err
	}
	effect := EffectRecord{Key: key, PayloadDigest: marker.PayloadDigest,
		Status: submitted.Status, Outcome: submitted.Outcome, Duplicate: submitted.Duplicate}
	if err := store.RecordEffectOutcome(effect); err != nil {
		return RecoveryResult{}, err
	}
	if options.Audit != nil {
		if err := options.Audit.Append(EffectAuditRecord{Kind: "effect",
			Operation: EffectOperation, OrderID: options.Binding.RequestedOrderID,
			IdempotencyKey: key, EffectStatus: submitted.Status, Duplicate: submitted.Duplicate}); err != nil {
			return RecoveryResult{}, err
		}
	}
	if err := store.MarkTerminal(RunStateSucceeded, ""); err != nil {
		return RecoveryResult{}, err
	}
	return RecoveryResult{Status: RunStateSucceeded, Reconciled: false,
		Effect: &effect, IdempotencyKey: key, Reads: reads}, nil
}
