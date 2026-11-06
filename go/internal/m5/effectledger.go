package m5

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// EffectLedger is the file-backed effect sink: one record per idempotency
// key, written once (once-per-key), atomically, at the state-dir root. A
// submit for a recorded key adopts the recorded outcome with
// duplicate=true and performs zero new writes.
type EffectLedger struct {
	stateDir string
}

// LedgerEffect is the recorded effect of one ledger record
// (order-closure-effect.schema.json $defs/effectOutcome): EFFECT_COMPLETED
// carries the refund outcome and no reason; EFFECT_REJECTED carries a null
// outcome and the INVALID_PAYLOAD reason.
type LedgerEffect struct {
	Status  string         `json:"status"`
	Outcome *RefundOutcome `json:"outcome"`
	Reason  *string        `json:"reason,omitempty"`
}

// LedgerRecord is one ledger entry (order-closure-effect.schema.json).
type LedgerRecord struct {
	Key           string       `json:"key"`
	PayloadDigest string       `json:"payload_digest"`
	Effect        LedgerEffect `json:"effect"`
}

// SubmitResult is the outcome of one ledger submit.
type SubmitResult struct {
	Status    string
	Outcome   *RefundOutcome
	Reason    *string
	Duplicate bool
}

// ledgerFile is the on-disk document shape.
type ledgerFile struct {
	Records []LedgerRecord `json:"records"`
}

// NewEffectLedger opens (and roots) the ledger under the state dir.
func NewEffectLedger(stateDir string) (*EffectLedger, error) {
	if err := os.MkdirAll(stateDir, 0o755); err != nil {
		return nil, fmt.Errorf("m5: create state directory: %w", err)
	}
	return &EffectLedger{stateDir: stateDir}, nil
}

// Path is the ledger's durable path (the state-dir root).
func (l *EffectLedger) Path() string { return filepath.Join(l.stateDir, "effect-ledger.json") }

// load reads the ledger, failing closed on invalid JSON or a record that
// fails the closed schema. A missing file is an empty ledger.
func (l *EffectLedger) load() (ledgerFile, error) {
	raw, err := os.ReadFile(l.Path())
	if err != nil {
		if os.IsNotExist(err) {
			return ledgerFile{}, nil
		}
		return ledgerFile{}, fmt.Errorf("m5: read effect ledger: %w", err)
	}
	var file ledgerFile
	if err := json.Unmarshal(raw, &file); err != nil {
		return ledgerFile{}, errors.New("m5: effect ledger is not valid JSON")
	}
	for index, record := range file.Records {
		if err := validateLedgerRecord(record); err != nil {
			return ledgerFile{}, fmt.Errorf("m5: effect ledger failed the closed schema: record %d: %w", index, err)
		}
	}
	return file, nil
}

// validateLedgerRecord mirrors the closed effect-record schema: a nonempty
// key, a hex payload digest, and the effectOutcome shape — the completed
// branch carries a validated refund and no reason; the rejected branch
// carries a null outcome and the INVALID_PAYLOAD reason.
func validateLedgerRecord(record LedgerRecord) error {
	switch {
	case record.Key == "":
		return errors.New("key must be nonempty")
	case !digestPattern.MatchString(record.PayloadDigest):
		return errors.New("payload_digest is invalid")
	}
	switch record.Effect.Status {
	case EffectCompleted:
		if record.Effect.Reason != nil {
			return errors.New("completed effects carry no reason")
		}
		return validateRefundOutcome(EffectCompleted, record.Effect.Outcome)
	case EffectRejected:
		if record.Effect.Outcome != nil {
			return errors.New("rejected effects carry no outcome")
		}
		if record.Effect.Reason == nil || *record.Effect.Reason != "INVALID_PAYLOAD" {
			return errors.New("rejected effects carry the INVALID_PAYLOAD reason")
		}
		return nil
	default:
		return errors.New("effect status is outside the enum")
	}
}

// submit records the payload's effect under the key exactly once: a recorded
// key adopts its recorded outcome (duplicate=true, zero writes); a new key
// validates the payload — an invalid payload is recorded as EFFECT_REJECTED
// — and the record is written atomically.
func (l *EffectLedger) submit(key, payloadDigest string, payload EffectPayload) (SubmitResult, error) {
	file, err := l.load()
	if err != nil {
		return SubmitResult{}, err
	}
	for _, record := range file.Records {
		if record.Key == key {
			return submitResultOf(record.Effect, true), nil
		}
	}
	effect := LedgerEffect{Status: EffectRejected,
		Reason: strPtr("INVALID_PAYLOAD")}
	if validateEffectPayload(payload) == nil {
		effect = LedgerEffect{Status: EffectCompleted, Outcome: &RefundOutcome{
			RefundID: RefundID, RefundedAt: RefundedAt}}
	}
	record := LedgerRecord{Key: key, PayloadDigest: payloadDigest, Effect: effect}
	file.Records = append(file.Records, record)
	content, err := canonicalJSON(file)
	if err != nil {
		return SubmitResult{}, fmt.Errorf("m5: canonical effect ledger: %w", err)
	}
	if err := writeAtomic(l.Path(), content); err != nil {
		return SubmitResult{}, err
	}
	return submitResultOf(effect, false), nil
}

// submitResultOf projects a recorded effect into the submit result shape.
func submitResultOf(effect LedgerEffect, duplicate bool) SubmitResult {
	if effect.Status == EffectCompleted {
		return SubmitResult{Status: EffectCompleted, Outcome: effect.Outcome,
			Reason: nil, Duplicate: duplicate}
	}
	return SubmitResult{Status: EffectRejected, Outcome: nil,
		Reason: effect.Reason, Duplicate: duplicate}
}

// LookupResult is the provenance answer for one key: the recorded effect's
// status and outcome.
type LookupResult struct {
	Status  string
	Outcome *RefundOutcome
}

// lookup reports whether the key landed in the ledger (the recovery
// decision point: present means adopt, absent means submit once).
func (l *EffectLedger) lookup(key string) (*LookupResult, error) {
	file, err := l.load()
	if err != nil {
		return nil, err
	}
	for _, record := range file.Records {
		if record.Key == key {
			return &LookupResult{Status: record.Effect.Status, Outcome: record.Effect.Outcome}, nil
		}
	}
	return nil, nil
}

// Records returns a copy of every recorded ledger record.
func (l *EffectLedger) Records() ([]LedgerRecord, error) {
	file, err := l.load()
	if err != nil {
		return nil, err
	}
	records := make([]LedgerRecord, len(file.Records))
	copy(records, file.Records)
	return records, nil
}
