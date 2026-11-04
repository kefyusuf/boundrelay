// Package contracts holds the typed shared-schema structs the Go runtimes
// exchange with the rest of BoundRelay: the 1.0 trace envelope, run results,
// and the required attribution block. The shapes mirror the JSON Schemas
// under contracts/ exactly; decoding goes through the strict helpers in
// decode.go so unknown fields, trailing data, and non-finite numbers fail
// closed.
package contracts

// EventType enumerates the trace event types from
// contracts/events/run-event.schema.json.
type EventType string

// EnvelopeVersion is the only trace schema version the runtimes emit.
const EnvelopeVersion = "1.0"

// SourceGo is stamped on every Go-emitted event, mirroring the TS/PY
// sources ("typescript", "python").
const SourceGo = "go"

// Event is the shared 1.0 trace envelope (run-event.schema.json). Go traces
// carry SchemaVersion "1.0" and Source "go".
type Event struct {
	SchemaVersion string         `json:"schema_version"`
	EventID       string         `json:"event_id"`
	RunID         string         `json:"run_id"`
	Sequence      int            `json:"sequence"`
	Type          EventType      `json:"type"`
	Timestamp     string         `json:"timestamp"`
	Source        string         `json:"source"`
	Data          map[string]any `json:"data"`
}

// Event types from the envelope enum.
const (
	EventRunCreated         EventType = "run.created"
	EventRunStarted         EventType = "run.started"
	EventRunCompleted       EventType = "run.completed"
	EventRunFailed          EventType = "run.failed"
	EventRunCancelled       EventType = "run.cancelled"
	EventStepStarted        EventType = "step.started"
	EventStepCompleted      EventType = "step.completed"
	EventStepFailed         EventType = "step.failed"
	EventModelRequested     EventType = "model.requested"
	EventModelCompleted     EventType = "model.completed"
	EventModelFailed        EventType = "model.failed"
	EventRouteSelected      EventType = "route.selected"
	EventRouteRejected      EventType = "route.rejected"
	EventToolRequested      EventType = "tool.requested"
	EventToolCompleted      EventType = "tool.completed"
	EventToolFailed         EventType = "tool.failed"
	EventBudgetConsumed     EventType = "budget.consumed"
	EventBudgetExceeded     EventType = "budget.exceeded"
	EventHandoffRequested   EventType = "handoff.requested"
	EventHandoffAccepted    EventType = "handoff.accepted"
	EventHandoffRejected    EventType = "handoff.rejected"
	EventCheckpointSaved    EventType = "checkpoint.saved"
	EventCheckpointRestored EventType = "checkpoint.restored"
	EventApprovalRequested  EventType = "approval.requested"
	EventApprovalGranted    EventType = "approval.granted"
	EventApprovalRejected   EventType = "approval.rejected"
)

// eventTypeEnum is the closed set behind EventType.Valid.
var eventTypeEnum = map[EventType]bool{
	EventRunCreated: true, EventRunStarted: true, EventRunCompleted: true,
	EventRunFailed: true, EventRunCancelled: true, EventStepStarted: true,
	EventStepCompleted: true, EventStepFailed: true, EventModelRequested: true,
	EventModelCompleted: true, EventModelFailed: true, EventRouteSelected: true,
	EventRouteRejected: true, EventToolRequested: true, EventToolCompleted: true,
	EventToolFailed: true, EventBudgetConsumed: true, EventBudgetExceeded: true,
	EventHandoffRequested: true, EventHandoffAccepted: true, EventHandoffRejected: true,
	EventCheckpointSaved: true, EventCheckpointRestored: true,
	EventApprovalRequested: true, EventApprovalGranted: true, EventApprovalRejected: true,
}

// Valid reports whether the event type is inside the envelope enum.
func (t EventType) Valid() bool { return eventTypeEnum[t] }
