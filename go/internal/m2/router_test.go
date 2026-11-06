package m2

import (
	"encoding/json"
	"strings"
	"testing"
)

// TestClassifyWithCode pins the code router: billing keywords win first,
// then technical, then the general route — always at full confidence.
func TestClassifyWithCode(t *testing.T) {
	cases := []struct {
		request string
		route   string
	}{
		{"I was charged twice for invoice INV-1001.", RouteBilling},
		{"I need a refund for my payment", RouteBilling},
		{"I cannot log in to my account", RouteTechnical},
		{"the app seems broken", RouteTechnical},
		{"What are your opening hours?", RouteGeneral},
		// No billing/technical keyword: the model decides the technical route
		// for the canonical model-technical-handoff request, not the code
		// router.
		{"The verification screen keeps rejecting the code and I cannot get in.", RouteGeneral},
	}
	for _, tc := range cases {
		decision := ClassifyWithCode(tc.request)
		if decision.Route != tc.route || decision.Confidence != 1 {
			t.Fatalf("ClassifyWithCode(%q) = %+v, want route %s at 1.0", tc.request, decision, tc.route)
		}
	}
}

// TestApplyConfidencePolicyBoundary pins the fixed 0.80 policy at its
// boundary: 0.79 falls back to general, 0.80 and above keep the proposed
// route.
func TestApplyConfidencePolicyBoundary(t *testing.T) {
	cases := []struct {
		name            string
		confidence      float64
		proposed        string
		selected        string
		outcome         string
		fallbackApplied bool
	}{
		{"below threshold", 0.79, RouteBilling, RouteGeneral, "fallback", true},
		{"at threshold", 0.80, RouteBilling, RouteBilling, "selected", false},
		{"above threshold", 0.81, RouteTechnical, RouteTechnical, "selected", false},
		{"zero confidence", 0, RouteTechnical, RouteGeneral, "fallback", true},
		{"full confidence", 1, RouteGeneral, RouteGeneral, "selected", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			selection := ApplyConfidencePolicy(
				RouteDecision{Route: tc.proposed, Confidence: tc.confidence}, ConfidenceThreshold)
			if selection.ProposedRoute != tc.proposed || selection.SelectedRoute != tc.selected ||
				selection.Confidence != tc.confidence || selection.PolicyOutcome != tc.outcome ||
				selection.FallbackApplied != tc.fallbackApplied {
				t.Fatalf("selection: %+v", selection)
			}
			if selection.Receiver != routeReceivers[tc.selected] {
				t.Fatalf("receiver %q does not match the selected route", selection.Receiver)
			}
		})
	}
}

// TestValidateRouteDecision covers the closed route-decision shape.
func TestValidateRouteDecision(t *testing.T) {
	decision, err := ValidateRouteDecision(json.RawMessage(
		`{"route": "technical", "confidence": 0.92}`))
	if err != nil || decision.Route != "technical" || decision.Confidence != 0.92 {
		t.Fatalf("valid decision: %+v, %v", decision, err)
	}
	for _, raw := range []string{
		`{"route": "sales", "confidence": 0.9}`,
		`{"route": "billing", "confidence": 1.5}`,
		`{"route": "billing", "confidence": -0.1}`,
		`{"route": "billing"}`,
		`{"confidence": 0.9}`,
		`{"route": "billing", "confidence": 0.9, "notes": "extra"}`,
		`["not-an-object"]`,
		`{"route": "billing", "confidence": "high"}`,
	} {
		if _, err := ValidateRouteDecision(json.RawMessage(raw)); err == nil ||
			!strings.Contains(err.Error(), ErrInvalidRoute.Error()) {
			t.Fatalf("expected invalid-route error for %s, got %v", raw, err)
		}
	}
}

// TestObservableDecision pins the public trace projection: only the routing
// fields, nulled when unreadable or out of range, extras dropped.
func TestObservableDecision(t *testing.T) {
	cases := []struct {
		raw        string
		route      any
		confidence any
	}{
		{`{"route": "billing", "confidence": 0.93}`, "billing", 0.93},
		{`{"route": "sales", "confidence": 0.9}`, nil, 0.9},
		{`{"route": "billing", "confidence": 2}`, "billing", nil},
		{`{"route": "billing", "confidence": 0.9, "secret": "x"}`, "billing", 0.9},
		{`"not-an-object"`, nil, nil},
		{`{}`, nil, nil},
	}
	for _, tc := range cases {
		decision := observableDecision(json.RawMessage(tc.raw))
		if decision["route"] != tc.route || decision["confidence"] != tc.confidence {
			t.Fatalf("observableDecision(%s) = %v, want route %v confidence %v",
				tc.raw, decision, tc.route, tc.confidence)
		}
	}
}

// TestScriptedRouteProvider pins the scripted schedule contract: decisions
// replay once per case; unknown or repeated schedules are provider errors
// (tooling drift).
func TestScriptedRouteProvider(t *testing.T) {
	provider := NewScriptedRouteProvider(map[string]json.RawMessage{
		"model-technical-handoff": json.RawMessage(`{"route": "technical", "confidence": 0.92}`),
	})
	first, err := provider.NextDecision(DecisionInput{CaseID: "model-technical-handoff"})
	if err != nil {
		t.Fatalf("first decision: %v", err)
	}
	var decision map[string]any
	if err := json.Unmarshal(first, &decision); err != nil {
		t.Fatalf("decision json: %v", err)
	}
	if decision["route"] != "technical" {
		t.Fatalf("decision: %v", decision)
	}
	if _, err := provider.NextDecision(DecisionInput{CaseID: "model-technical-handoff"}); err == nil ||
		!strings.Contains(err.Error(), "already consumed") {
		t.Fatalf("repeat decision must be rejected: %v", err)
	}
	if _, err := provider.NextDecision(DecisionInput{CaseID: "code-billing-handoff"}); err == nil ||
		!strings.Contains(err.Error(), "Missing scripted decision") {
		t.Fatalf("unknown case must be rejected: %v", err)
	}
}
