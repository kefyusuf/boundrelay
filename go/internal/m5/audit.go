package m5

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
)

// AuditWriter is the append-only audit trail (state_dir/audit.jsonl): one
// canonical-JSON record per line, appended, never read by the runtime. The
// contract schema is closed (order-closure-audit.schema.json): exactly two
// record kinds — the approval decision and the effect submission.
type AuditWriter struct {
	stateDir string
}

// ApprovalAuditRecord is the audit record of one gate decision.
type ApprovalAuditRecord struct {
	Kind          string `json:"kind"`
	Operation     string `json:"operation"`
	OrderID       string `json:"order_id"`
	PayloadDigest string `json:"payload_digest"`
	Decision      string `json:"decision"`
	Approver      string `json:"approver"`
}

// EffectAuditRecord is the audit record of one effect submission (or
// adoption — adoption counts the original attempt).
type EffectAuditRecord struct {
	Kind           string `json:"kind"`
	Operation      string `json:"operation"`
	OrderID        string `json:"order_id"`
	IdempotencyKey string `json:"idempotency_key"`
	EffectStatus   string `json:"effect_status"`
	Duplicate      bool   `json:"duplicate"`
}

// NewAuditWriter opens (and roots) the audit trail under the state dir.
func NewAuditWriter(stateDir string) (*AuditWriter, error) {
	if err := os.MkdirAll(stateDir, 0o755); err != nil {
		return nil, fmt.Errorf("m5: create state directory: %w", err)
	}
	return &AuditWriter{stateDir: stateDir}, nil
}

// Path is the audit trail's durable path (the state-dir root).
func (w *AuditWriter) Path() string { return w.stateDir + string(os.PathSeparator) + "audit.jsonl" }

// Append validates the record against the closed audit schema and appends
// its canonical JSON as one line.
func (w *AuditWriter) Append(record any) error {
	line, err := canonicalJSON(record)
	if err != nil {
		return fmt.Errorf("m5: canonical audit record: %w", err)
	}
	var decoded map[string]any
	if err := json.Unmarshal([]byte(line), &decoded); err != nil {
		return fmt.Errorf("m5: audit record is not a JSON object: %w", err)
	}
	if err := validateAuditRecord(decoded); err != nil {
		return fmt.Errorf("m5: invalid audit record: %w", err)
	}
	handle, err := os.OpenFile(w.Path(), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return fmt.Errorf("m5: open audit trail: %w", err)
	}
	defer handle.Close()
	if _, err := handle.WriteString(line + "\n"); err != nil {
		return fmt.Errorf("m5: append audit record: %w", err)
	}
	return nil
}

// validateAuditRecord mirrors the closed audit schema: kind "approval"
// carries the binding record; kind "effect" carries the submission record.
// Every other shape is refused.
func validateAuditRecord(record map[string]any) error {
	kind, _ := record["kind"].(string)
	switch kind {
	case "approval":
		if len(record) != 6 {
			return errors.New("approval audit records carry exactly the closed fields")
		}
		if record["operation"] != EffectOperation {
			return errors.New("operation must be cancel-and-refund")
		}
		orderID, _ := record["order_id"].(string)
		if !orderIDPattern.MatchString(orderID) {
			return errors.New("order_id is invalid")
		}
		digest, _ := record["payload_digest"].(string)
		if !digestPattern.MatchString(digest) {
			return errors.New("payload_digest is invalid")
		}
		decision, _ := record["decision"].(string)
		if decision != DecisionGranted && decision != DecisionRejected {
			return errors.New("decision is outside the enum")
		}
		approver, _ := record["approver"].(string)
		if approver == "" {
			return errors.New("approver must be nonempty")
		}
		return nil
	case "effect":
		if len(record) != 6 {
			return errors.New("effect audit records carry exactly the closed fields")
		}
		if record["operation"] != EffectOperation {
			return errors.New("operation must be cancel-and-refund")
		}
		orderID, _ := record["order_id"].(string)
		if !orderIDPattern.MatchString(orderID) {
			return errors.New("order_id is invalid")
		}
		key, _ := record["idempotency_key"].(string)
		if key == "" {
			return errors.New("idempotency_key must be nonempty")
		}
		status, _ := record["effect_status"].(string)
		if status != EffectCompleted && status != EffectRejected && status != EffectUnprovable {
			return errors.New("effect_status is outside the enum")
		}
		if _, ok := record["duplicate"].(bool); !ok {
			return errors.New("duplicate must be a boolean")
		}
		return nil
	default:
		return errors.New("kind must be approval or effect")
	}
}
