package m2

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// Handoff failure codes live in the shared contracts package
// (contracts/results/handoff-result.schema.json): the route-decision class
// fails closed before any handoff; the two handoff classes reject the
// envelope before or at receiver dispatch.

// ErrInvalidRoute marks the INVALID_ROUTE_DECISION domain failure.
var ErrInvalidRoute = errors.New("route decision is invalid")

// isHandoffFailureCode reports whether the code is inside the M2 enum.
func isHandoffFailureCode(code string) bool {
	return contracts.IsM2FailureCode(code)
}

// RouteDecision is a bounded routing decision: a canonical route plus a
// confidence in [0, 1].
type RouteDecision struct {
	Route      string
	Confidence float64
}

// RouteSelection is the confidence policy's outcome: the proposed route from
// the decision, the selected route after the 0.80 policy, the policy
// outcome, and the resolved receiver.
type RouteSelection struct {
	ProposedRoute   string
	SelectedRoute   string
	Confidence      float64
	PolicyOutcome   string
	FallbackApplied bool
	Receiver        string
}

// billing/technical keyword lists mirrored from the deterministic baseline.
var (
	billingKeywords   = []string{"charged", "charge", "invoice", "payment", "refund", "billed"}
	technicalKeywords = []string{"error", "crash", "cannot log in", "can't log in", "bug", "broken"}
)

// ClassifyWithCode is the code router: keyword matching with full
// confidence, falling back to the general route.
func ClassifyWithCode(request string) RouteDecision {
	value := strings.ToLower(request)
	for _, keyword := range billingKeywords {
		if strings.Contains(value, keyword) {
			return RouteDecision{Route: RouteBilling, Confidence: 1}
		}
	}
	for _, keyword := range technicalKeywords {
		if strings.Contains(value, keyword) {
			return RouteDecision{Route: RouteTechnical, Confidence: 1}
		}
	}
	return RouteDecision{Route: RouteGeneral, Confidence: 1}
}

// ApplyConfidencePolicy is the fixed 0.80 policy: confidence >= 0.80 keeps
// the proposed route (selected); below it the run deterministically falls
// back to the general route and its receiver.
func ApplyConfidencePolicy(decision RouteDecision, threshold float64) RouteSelection {
	fallbackApplied := decision.Confidence < threshold
	selectedRoute := decision.Route
	if fallbackApplied {
		selectedRoute = RouteGeneral
	}
	outcome := "selected"
	if fallbackApplied {
		outcome = "fallback"
	}
	return RouteSelection{
		ProposedRoute: decision.Route, SelectedRoute: selectedRoute,
		Confidence: decision.Confidence, PolicyOutcome: outcome,
		FallbackApplied: fallbackApplied, Receiver: routeReceivers[selectedRoute],
	}
}

// routeDecisionWire mirrors contracts/routing/route-decision.schema.json:
// both fields required, no additional properties, closed route enum.
type routeDecisionWire struct {
	Route      *string  `json:"route"`
	Confidence *float64 `json:"confidence"`
}

// ValidateRouteDecision validates a raw decision payload against the closed
// route-decision shape.
func ValidateRouteDecision(raw json.RawMessage) (RouteDecision, error) {
	var wire routeDecisionWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return RouteDecision{}, fmt.Errorf("%w: %s", ErrInvalidRoute, err)
	}
	if wire.Route == nil || wire.Confidence == nil {
		return RouteDecision{}, fmt.Errorf("%w: route and confidence are required", ErrInvalidRoute)
	}
	if !isCanonicalRoute(*wire.Route) || *wire.Confidence < 0 || *wire.Confidence > 1 ||
		math.IsNaN(*wire.Confidence) || math.IsInf(*wire.Confidence, 0) {
		return RouteDecision{}, fmt.Errorf("%w: unsupported route %q or confidence %v",
			ErrInvalidRoute, *wire.Route, *wire.Confidence)
	}
	return RouteDecision{Route: *wire.Route, Confidence: *wire.Confidence}, nil
}

// observableDecision mirrors the TS/Py public trace projection: only the
// routing fields belong in the trace, nulled when they are not readable and
// in-range (extra provider fields are dropped, never authorized).
func observableDecision(raw json.RawMessage) map[string]any {
	var loose struct {
		Route      *string      `json:"route"`
		Confidence *json.Number `json:"confidence"`
	}
	route := any(nil)
	confidence := any(nil)
	if err := json.Unmarshal(raw, &loose); err == nil {
		if loose.Route != nil && isCanonicalRoute(*loose.Route) {
			route = *loose.Route
		}
		if loose.Confidence != nil {
			if value, parseErr := loose.Confidence.Float64(); parseErr == nil &&
				value >= 0 && value <= 1 && !math.IsNaN(value) && !math.IsInf(value, 0) {
				confidence = value
			}
		}
	}
	return map[string]any{"route": route, "confidence": confidence}
}

// DecisionInput is the per-case input to the route decision provider.
type DecisionInput struct {
	CaseID  string
	Request string
}

// RouteDecisionProvider produces the raw scripted decision for one case.
// Provider errors are tooling errors: the scripted schedule is offline
// fixture drift, not a domain failure.
type RouteDecisionProvider interface {
	NextDecision(input DecisionInput) (json.RawMessage, error)
}

// ScriptedRouteProvider is the deterministic offline model: it replays the
// projected decisions exactly once per case, rejecting unknown or
// already-consumed schedules.
type ScriptedRouteProvider struct {
	decisions map[string]json.RawMessage
	consumed  map[string]bool
}

// NewScriptedRouteProvider builds the scripted provider over the validated
// decisions projection.
func NewScriptedRouteProvider(decisions map[string]json.RawMessage) *ScriptedRouteProvider {
	return &ScriptedRouteProvider{decisions: decisions, consumed: map[string]bool{}}
}

// NextDecision returns the case's scripted decision.
func (p *ScriptedRouteProvider) NextDecision(input DecisionInput) (json.RawMessage, error) {
	decision, ok := p.decisions[input.CaseID]
	if !ok {
		return nil, fmt.Errorf("Missing scripted decision for case: %s", input.CaseID)
	}
	if p.consumed[input.CaseID] {
		return nil, fmt.Errorf("Scripted decision already consumed for case: %s", input.CaseID)
	}
	p.consumed[input.CaseID] = true
	return append(json.RawMessage(nil), decision...), nil
}
