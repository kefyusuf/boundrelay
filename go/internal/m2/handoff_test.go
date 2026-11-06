package m2

import (
	"strings"
	"testing"
)

func sampleSelection() RouteSelection {
	return ApplyConfidencePolicy(
		RouteDecision{Route: RouteBilling, Confidence: 0.93}, ConfidenceThreshold)
}

func sampleEnvelope() HandoffEnvelope {
	return HandoffEnvelope{
		HandoffID: "handoff-1", Sender: Sender, Receiver: ReceiverBilling,
		SenderIntent: sampleSelection(),
		ReceiverInput: map[string]any{
			"ticket_id": "TCK-9001", "request_text": "I was billed for a service I did not receive."},
	}
}

// TestValidateHandoffEnvelopeAcceptsCanonical pins the closed envelope
// validation on a well-formed candidate.
func TestValidateHandoffEnvelopeAcceptsCanonical(t *testing.T) {
	if err := validateHandoffEnvelope(sampleEnvelope()); err != nil {
		t.Fatalf("canonical envelope must validate: %v", err)
	}
}

// TestValidateHandoffEnvelopeRejects pins the context-validation failures:
// a lost receiver-input field, a malformed ticket, a wrong sender, an
// unknown receiver, and an out-of-range intent confidence all invalidate
// the context (HANDOFF_CONTEXT_INVALID).
func TestValidateHandoffEnvelopeRejects(t *testing.T) {
	rejections := []struct {
		name   string
		mutate func(HandoffEnvelope) HandoffEnvelope
		frag   string
	}{
		{"lost request_text", func(e HandoffEnvelope) HandoffEnvelope {
			delete(e.ReceiverInput, "request_text")
			return e
		}, "receiver_input must carry ticket_id and request_text"},
		{"lost ticket_id", func(e HandoffEnvelope) HandoffEnvelope {
			delete(e.ReceiverInput, "ticket_id")
			return e
		}, "receiver_input must carry ticket_id and request_text"},
		{"extra receiver-input field", func(e HandoffEnvelope) HandoffEnvelope {
			e.ReceiverInput["priority"] = "high"
			return e
		}, "handoff context is invalid"},
		{"malformed ticket", func(e HandoffEnvelope) HandoffEnvelope {
			e.ReceiverInput["ticket_id"] = "TK-1"
			return e
		}, "receiver_input must carry ticket_id and request_text"},
		{"empty request text", func(e HandoffEnvelope) HandoffEnvelope {
			e.ReceiverInput["request_text"] = ""
			return e
		}, "receiver_input must carry ticket_id and request_text"},
		{"wrong sender", func(e HandoffEnvelope) HandoffEnvelope {
			e.Sender = "another-router"
			return e
		}, "handoff_id and the \"support-router\" sender are required"},
		{"unknown receiver", func(e HandoffEnvelope) HandoffEnvelope {
			e.Receiver = "sales-specialist"
			return e
		}, "receiver \"sales-specialist\" is outside the enum"},
		{"intent confidence out of range", func(e HandoffEnvelope) HandoffEnvelope {
			selection := sampleSelection()
			selection.Confidence = 1.5
			e.SenderIntent = selection
			return e
		}, "sender intent route/confidence are invalid"},
		{"intent route drifts from intent policy", func(e HandoffEnvelope) HandoffEnvelope {
			selection := sampleSelection()
			selection.PolicyOutcome = "escalated"
			e.SenderIntent = selection
			return e
		}, "policy_outcome must be selected or fallback"},
	}
	for _, rejection := range rejections {
		t.Run(rejection.name, func(t *testing.T) {
			err := validateHandoffEnvelope(rejection.mutate(sampleEnvelope()))
			if err == nil || !strings.Contains(err.Error(), rejection.frag) ||
				!strings.Contains(err.Error(), ErrHandoffContextInvalid.Error()) {
				t.Fatalf("expected context-invalid error containing %q, got %v", rejection.frag, err)
			}
		})
	}
}

// TestReceiverDirectory pins the static directory: canonical residents
// resolve, unavailable ones do not, and dispatched inputs are recorded in
// order (the zero-dispatch claim for failures).
func TestReceiverDirectory(t *testing.T) {
	directory := NewRecordingReceiverDirectory()
	if definition := directory.Resolve(ReceiverBilling); definition == nil ||
		definition.Name != ReceiverBilling {
		t.Fatalf("billing-specialist must resolve: %+v", definition)
	}
	for _, receiver := range canonicalReceivers {
		if directory.Resolve(receiver) == nil {
			t.Fatalf("%s must be available by default", receiver)
		}
	}
	if len(directory.Invocations()) != 0 {
		t.Fatalf("resolution must not dispatch: %+v", directory.Invocations())
	}
	input := ReceiverInput{TicketID: "TCK-1001", RequestText: "I was charged twice."}
	definition := directory.Resolve(ReceiverTechnical)
	if err := definition.Handle(input); err != nil {
		t.Fatalf("handle: %v", err)
	}
	invocations := directory.Invocations()
	if len(invocations) != 1 || invocations[0].Receiver != ReceiverTechnical ||
		invocations[0].Input != input {
		t.Fatalf("invocations: %+v", invocations)
	}
	limited := NewRecordingReceiverDirectory(ReceiverBilling)
	if limited.Resolve(ReceiverBilling) != nil {
		t.Fatal("unavailable receiver must not resolve")
	}
	if limited.Resolve(ReceiverGeneral) == nil {
		t.Fatal("other receivers must stay available")
	}
}
