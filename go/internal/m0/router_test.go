package m0

import (
	"errors"
	"testing"
)

func TestClassifyDeterministically(t *testing.T) {
	cases := []struct {
		request string
		route   string
	}{
		{"I was charged twice for the same invoice.", "billing"},
		{"Please refund my payment.", "billing"},
		{"I cannot log in because the app shows an error.", "technical"},
		{"The app started to crash after the update.", "technical"},
		{"What are your support opening hours?", "general"},
		{"Hello there", "general"},
	}
	for _, tc := range cases {
		decision := ClassifyDeterministically(tc.request)
		if decision.Route != tc.route || decision.Confidence != 1 {
			t.Fatalf("classify(%q) = %+v, want route %s confidence 1", tc.request, decision, tc.route)
		}
	}
}

func TestValidateRouteDecisionAccepts(t *testing.T) {
	decision, rejected, err := ValidateRouteDecision([]byte(`{"route":"billing","confidence":0.98}`))
	if err != nil || rejected != nil {
		t.Fatalf("valid decision rejected: %v %v", err, rejected)
	}
	if decision.Route != "billing" || decision.Confidence != 0.98 {
		t.Fatalf("decision: %+v", decision)
	}
	if _, _, err := ValidateRouteDecision([]byte(`{"route":"general","confidence":1}`)); err != nil {
		t.Fatalf("integer confidence 1 must be valid, got %v", err)
	}
	if _, _, err := ValidateRouteDecision([]byte(`{"route":"general","confidence":0}`)); err != nil {
		t.Fatalf("confidence 0 must be valid, got %v", err)
	}
}

func TestValidateRouteDecisionRejects(t *testing.T) {
	cases := []struct {
		name          string
		raw           string
		rejectedRoute *string
	}{
		{"unknown route", `{"route":"unknown-specialist","confidence":0.99}`, strPtr("unknown-specialist")},
		{"missing confidence", `{"route":"billing"}`, strPtr("billing")},
		{"missing route", `{"confidence":0.5}`, nil},
		{"confidence above one", `{"route":"billing","confidence":1.5}`, strPtr("billing")},
		{"negative confidence", `{"route":"billing","confidence":-0.1}`, strPtr("billing")},
		{"unknown field", `{"route":"billing","confidence":0.5,"extra":1}`, strPtr("billing")},
		{"route not a string", `{"route":7,"confidence":0.5}`, nil},
		{"not an object", `"billing"`, nil},
		{"empty input", ``, nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, rejected, err := ValidateRouteDecision([]byte(tc.raw))
			if !errors.Is(err, ErrInvalidRoute) {
				t.Fatalf("expected ErrInvalidRoute, got %v", err)
			}
			if !sameStringPtr(rejected, tc.rejectedRoute) {
				t.Fatalf("rejectedRoute = %v, want %v", rejected, tc.rejectedRoute)
			}
		})
	}
}

func sameStringPtr(got, want *string) bool {
	if got == nil || want == nil {
		return got == nil && want == nil
	}
	return *got == *want
}
