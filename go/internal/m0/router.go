package m0

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// RouteDecision is a bounded routing decision: a canonical route plus a
// confidence in [0, 1].
type RouteDecision struct {
	Route      string
	Confidence float64
}

// billing/technical keyword lists mirrored from the deterministic baseline.
var (
	billingKeywords   = []string{"charged", "charge", "invoice", "payment", "refund", "billed"}
	technicalKeywords = []string{"error", "crash", "cannot log in", "can't log in", "bug", "broken"}
)

// ClassifyDeterministically is the direct-mode code route: keyword matching
// with full confidence, falling back to the general route.
func ClassifyDeterministically(request string) RouteDecision {
	value := strings.ToLower(request)
	for _, keyword := range billingKeywords {
		if strings.Contains(value, keyword) {
			return RouteDecision{Route: "billing", Confidence: 1}
		}
	}
	for _, keyword := range technicalKeywords {
		if strings.Contains(value, keyword) {
			return RouteDecision{Route: "technical", Confidence: 1}
		}
	}
	return RouteDecision{Route: "general", Confidence: 1}
}

// routeDecisionWire mirrors contracts/routing/route-decision.schema.json:
// both fields required, no additional properties, closed route enum.
type routeDecisionWire struct {
	Route      *string  `json:"route"`
	Confidence *float64 `json:"confidence"`
}

// ValidateRouteDecision validates a raw model/decision payload against the
// closed route-decision shape. On failure it returns an error wrapping
// ErrInvalidRoute plus the rejected route string when one is readable.
func ValidateRouteDecision(raw []byte) (RouteDecision, *string, error) {
	var wire routeDecisionWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return RouteDecision{}, rejectedRouteFrom(raw), fmt.Errorf("%w: %s", ErrInvalidRoute, err)
	}
	if wire.Route == nil || wire.Confidence == nil {
		return RouteDecision{}, rejectedRouteFrom(raw),
			fmt.Errorf("%w: route and confidence are required", ErrInvalidRoute)
	}
	routeValid := false
	for _, route := range canonicalRoutes {
		if *wire.Route == route {
			routeValid = true
		}
	}
	if !routeValid || *wire.Confidence < 0 || *wire.Confidence > 1 {
		return RouteDecision{}, wire.Route,
			fmt.Errorf("%w: unsupported route %q or confidence %v", ErrInvalidRoute, *wire.Route, *wire.Confidence)
	}
	return RouteDecision{Route: *wire.Route, Confidence: *wire.Confidence}, nil, nil
}

// rejectedRouteFrom extracts the rejected route for diagnostics, mirroring
// the TS bounded router (only when the raw value is an object carrying a
// string route).
func rejectedRouteFrom(raw []byte) *string {
	var loose struct {
		Route *string `json:"route"`
	}
	if err := json.Unmarshal(raw, &loose); err != nil || loose.Route == nil {
		return nil
	}
	return loose.Route
}
