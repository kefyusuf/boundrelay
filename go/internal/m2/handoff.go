package m2

import (
	"encoding/json"
	"errors"
	"fmt"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// ErrHandoffContextInvalid marks the HANDOFF_CONTEXT_INVALID domain failure:
// the envelope failed its closed-shape validation before receiver dispatch.
var ErrHandoffContextInvalid = errors.New("handoff context is invalid")

// ReceiverInput is the receiver's own work item, separate from the sender's
// intent: the handoff envelope carries both, but the receiver only consumes
// its input.
type ReceiverInput struct {
	TicketID    string
	RequestText string
}

// ReceiverDefinition is one available specialist receiver.
type ReceiverDefinition struct {
	Name   string
	Handle func(ReceiverInput) error
}

// ReceiverDirectory resolves a receiver by name; an unresolvable name is a
// missing or unavailable receiver.
type ReceiverDirectory interface {
	Resolve(name string) *ReceiverDefinition
}

// SpecialistInvocation is one recorded specialist dispatch.
type SpecialistInvocation struct {
	Receiver string
	Input    ReceiverInput
}

// RecordingReceiverDirectory is the static directory of canonical receivers
// (no-op scripted handlers, exactly like the TS/Py recorder) that records
// every dispatch in order.
type RecordingReceiverDirectory struct {
	available   map[string]bool
	invocations []SpecialistInvocation
}

// NewRecordingReceiverDirectory builds the directory over the canonical
// receivers minus the explicitly unavailable set.
func NewRecordingReceiverDirectory(unavailable ...string) *RecordingReceiverDirectory {
	unavailableSet := map[string]bool{}
	for _, name := range unavailable {
		unavailableSet[name] = true
	}
	available := map[string]bool{}
	for _, name := range canonicalReceivers {
		available[name] = !unavailableSet[name]
	}
	return &RecordingReceiverDirectory{available: available}
}

// Resolve returns the receiver definition when the name is an available
// canonical receiver, and nil otherwise.
func (d *RecordingReceiverDirectory) Resolve(name string) *ReceiverDefinition {
	if !d.available[name] {
		return nil
	}
	return &ReceiverDefinition{Name: name, Handle: func(input ReceiverInput) error {
		d.invocations = append(d.invocations,
			SpecialistInvocation{Receiver: name, Input: input})
		return nil
	}}
}

// Invocations returns a copy of the recorded dispatches.
func (d *RecordingReceiverDirectory) Invocations() []SpecialistInvocation {
	return append([]SpecialistInvocation(nil), d.invocations...)
}

// handoffWire mirrors contracts/handoffs/support-handoff.schema.json for
// strict validation: the 1.0 header, the support-router sender, a canonical
// receiver, the closed sender-intent block, and the closed receiver-input
// block (both fields required — a lost field invalidates the context).
type handoffWire struct {
	SchemaVersion string            `json:"schema_version"`
	HandoffID     string            `json:"handoff_id"`
	Sender        string            `json:"sender"`
	Receiver      string            `json:"receiver"`
	SenderIntent  senderIntentWire  `json:"sender_intent"`
	ReceiverInput receiverInputWire `json:"receiver_input"`
}

type senderIntentWire struct {
	Route         string   `json:"route"`
	Confidence    *float64 `json:"confidence"`
	PolicyOutcome string   `json:"policy_outcome"`
}

type receiverInputWire struct {
	TicketID    *string `json:"ticket_id"`
	RequestText *string `json:"request_text"`
}

// HandoffEnvelope is the sender-intent/receiver-input envelope: the router's
// intent (route, confidence, policy outcome) travels beside — never inside —
// the receiver's input.
type HandoffEnvelope struct {
	HandoffID     string
	Sender        string
	Receiver      string
	SenderIntent  RouteSelection
	ReceiverInput map[string]any
}

// Wire renders the envelope as the closed handoff document (the receiver
// input carried verbatim, including any omitted field).
func (e HandoffEnvelope) Wire() map[string]any {
	return map[string]any{
		"schema_version": contracts.EnvelopeVersion,
		"handoff_id":     e.HandoffID,
		"sender":         e.Sender,
		"receiver":       e.Receiver,
		"sender_intent": map[string]any{
			"route":          e.SenderIntent.ProposedRoute,
			"confidence":     e.SenderIntent.Confidence,
			"policy_outcome": e.SenderIntent.PolicyOutcome,
		},
		"receiver_input": e.ReceiverInput,
	}
}

// validateHandoffEnvelope validates the envelope against the closed
// support-handoff shape: schema version, sender, receiver enum, intent
// fields, and the complete receiver input (ticket pattern + non-empty
// request text).
func validateHandoffEnvelope(envelope HandoffEnvelope) error {
	document, err := json.Marshal(envelope.Wire())
	if err != nil {
		return fmt.Errorf("m2: handoff envelope is not JSON-safe: %w", err)
	}
	var wire handoffWire
	if err := contracts.DecodeStrict(document, &wire); err != nil {
		return fmt.Errorf("%w: %s", ErrHandoffContextInvalid, err)
	}
	switch {
	case wire.SchemaVersion != contracts.EnvelopeVersion:
		return fmt.Errorf("%w: schema_version must be %q", ErrHandoffContextInvalid, contracts.EnvelopeVersion)
	case wire.HandoffID == "" || wire.Sender != Sender:
		return fmt.Errorf("%w: handoff_id and the %q sender are required", ErrHandoffContextInvalid, Sender)
	case !isCanonicalReceiver(wire.Receiver):
		return fmt.Errorf("%w: receiver %q is outside the enum", ErrHandoffContextInvalid, wire.Receiver)
	case !isCanonicalRoute(wire.SenderIntent.Route) || wire.SenderIntent.Confidence == nil ||
		*wire.SenderIntent.Confidence < 0 || *wire.SenderIntent.Confidence > 1:
		return fmt.Errorf("%w: sender intent route/confidence are invalid", ErrHandoffContextInvalid)
	case wire.SenderIntent.PolicyOutcome != "selected" && wire.SenderIntent.PolicyOutcome != "fallback":
		return fmt.Errorf("%w: policy_outcome must be selected or fallback", ErrHandoffContextInvalid)
	case wire.ReceiverInput.TicketID == nil || wire.ReceiverInput.RequestText == nil ||
		!ticketPattern.MatchString(*wire.ReceiverInput.TicketID) || *wire.ReceiverInput.RequestText == "":
		return fmt.Errorf("%w: receiver_input must carry ticket_id and request_text", ErrHandoffContextInvalid)
	}
	return nil
}
