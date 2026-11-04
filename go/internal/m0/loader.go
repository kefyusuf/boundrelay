// Package m0 is the Go runtime for the support-triage lesson: scenario
// loading from the checked-in JSON projection, deterministic and scripted
// routing, the 1.0 trace envelope, attribution assembly, and the run result
// contract. It mirrors the TypeScript/Python semantics, not their code.
package m0

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// Sentinel errors mapped 1:1 to failure codes (M7 global constraint).
var (
	// ErrInvalidRoute is the invalid-route-decision failure class.
	ErrInvalidRoute = errors.New("m0: invalid route decision")
	// ErrUnknownCase marks tooling errors for unknown scenario cases.
	ErrUnknownCase = errors.New("m0: unknown scenario case")
)

// Run modes and the canonical M0 route order.
const (
	ModeDeterministic = "deterministic"
	ModeModel         = "model"
)

var canonicalRoutes = []string{"billing", "technical", "general"}

// stepPriceKinds is the closed set of attribution price kinds.
var stepPriceKinds = map[string]bool{
	"read": true, "model_decision": true, "tool_call": true, "effect": true,
	"handoff": true, "route": true, "synthesis": true,
}

// Case is one scenario case: a success expectation (route) or a failure
// expectation (failure code), never both.
type Case struct {
	ID                  string
	Request             string
	ExpectedRoute       string
	ExpectedFailureCode string
}

// Success reports whether the case expects a route dispatch.
func (c Case) Success() bool { return c.ExpectedRoute != "" }

// AttributionTables are the scenario's fixture-priced latency/cost tables.
type AttributionTables struct {
	LatencyMS  map[string]int
	PriceTable map[string]int
}

// Scenario is the validated support-triage scenario document.
type Scenario struct {
	SchemaVersion string
	ScenarioID    string
	Routes        []string
	Cases         []Case
	Attribution   AttributionTables
}

// scenarioWire mirrors the projection document for strict decoding; unknown
// fields are rejected by contracts.DecodeStrict.
type scenarioWire struct {
	SchemaVersion string   `json:"schema_version"`
	ScenarioID    string   `json:"scenario_id"`
	Routes        []string `json:"routes"`
	Attribution   *struct {
		LatencyMS  map[string]int `json:"latency_ms"`
		PriceTable map[string]int `json:"price_table"`
	} `json:"attribution"`
	Cases []struct {
		ID                  string  `json:"id"`
		Request             string  `json:"request"`
		ExpectedRoute       *string `json:"expected_route"`
		ExpectedFailureCode *string `json:"expected_failure_code"`
	} `json:"cases"`
}

// FindRepoRoot walks up from the working directory to the repository root
// (the nearest directory carrying the canonical scenario fixture).
func FindRepoRoot() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if info, err := os.Stat(filepath.Join(dir, "fixtures", "scenarios",
			"support-triage.yaml")); err == nil && !info.IsDir() {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", errors.New("m0: repository root not found from " + dir)
		}
		dir = parent
	}
}

// DefaultScenarioPath is the checked-in JSON projection of the M0 scenario.
func DefaultScenarioPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections",
		"support-triage", "scenario.json")
}

// LoadScenario strict-decodes and validates the scenario projection: the
// 1.0 support-triage document with canonical routes, cases carrying exactly
// one supported expectation each, and non-empty attribution tables.
func LoadScenario(path string) (*Scenario, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("m0: read scenario: %w", err)
	}
	var wire scenarioWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return nil, fmt.Errorf("m0: invalid scenario projection: %w", err)
	}
	if wire.SchemaVersion != "1.0" || wire.ScenarioID != "support-triage" {
		return nil, fmt.Errorf("m0: unsupported scenario document: schema_version %q, scenario_id %q",
			wire.SchemaVersion, wire.ScenarioID)
	}
	if len(wire.Routes) != len(canonicalRoutes) {
		return nil, errors.New("m0: scenario routes must match the canonical M0 routes")
	}
	for i, route := range canonicalRoutes {
		if wire.Routes[i] != route {
			return nil, errors.New("m0: scenario routes must match the canonical M0 routes")
		}
	}
	cases := make([]Case, 0, len(wire.Cases))
	for _, wireCase := range wire.Cases {
		parsed, err := parseCase(wireCase)
		if err != nil {
			return nil, err
		}
		cases = append(cases, parsed)
	}
	tables, err := parseTables(wire.Attribution)
	if err != nil {
		return nil, err
	}
	return &Scenario{SchemaVersion: wire.SchemaVersion, ScenarioID: wire.ScenarioID,
		Routes: append([]string(nil), wire.Routes...), Cases: cases, Attribution: tables}, nil
}

func parseCase(wireCase struct {
	ID                  string  `json:"id"`
	Request             string  `json:"request"`
	ExpectedRoute       *string `json:"expected_route"`
	ExpectedFailureCode *string `json:"expected_failure_code"`
}) (Case, error) {
	if wireCase.ID == "" || wireCase.Request == "" {
		return Case{}, fmt.Errorf("m0: scenario case %q must define id and request", wireCase.ID)
	}
	if wireCase.ExpectedRoute != nil && wireCase.ExpectedFailureCode != nil {
		return Case{}, fmt.Errorf("m0: scenario case %q must define exactly one expectation", wireCase.ID)
	}
	if wireCase.ExpectedRoute != nil {
		for _, route := range canonicalRoutes {
			if *wireCase.ExpectedRoute == route {
				return Case{ID: wireCase.ID, Request: wireCase.Request,
					ExpectedRoute: *wireCase.ExpectedRoute}, nil
			}
		}
		return Case{}, fmt.Errorf("m0: scenario case %q has unsupported route %q",
			wireCase.ID, *wireCase.ExpectedRoute)
	}
	if wireCase.ExpectedFailureCode != nil &&
		*wireCase.ExpectedFailureCode == contracts.FailureInvalidRouteDecision {
		return Case{ID: wireCase.ID, Request: wireCase.Request,
			ExpectedFailureCode: *wireCase.ExpectedFailureCode}, nil
	}
	return Case{}, fmt.Errorf("m0: scenario case %q must define exactly one expectation", wireCase.ID)
}

func parseTables(raw *struct {
	LatencyMS  map[string]int `json:"latency_ms"`
	PriceTable map[string]int `json:"price_table"`
}) (AttributionTables, error) {
	if raw == nil {
		return AttributionTables{}, errors.New("m0: scenario attribution tables are required")
	}
	if len(raw.LatencyMS) == 0 {
		return AttributionTables{}, errors.New("m0: invalid attribution latency table: must be nonempty")
	}
	if len(raw.PriceTable) == 0 {
		return AttributionTables{}, errors.New("m0: invalid attribution price table: must be nonempty")
	}
	for step, latency := range raw.LatencyMS {
		if step == "" || latency < 0 {
			return AttributionTables{}, fmt.Errorf("m0: invalid attribution latency for %q", step)
		}
	}
	for kind, price := range raw.PriceTable {
		if !stepPriceKinds[kind] || price < 0 {
			return AttributionTables{}, fmt.Errorf("m0: invalid attribution price kind %q", kind)
		}
	}
	if read, ok := raw.PriceTable["read"]; ok && read != 0 {
		return AttributionTables{}, errors.New("m0: attribution reads must price zero")
	}
	return AttributionTables{LatencyMS: raw.LatencyMS, PriceTable: raw.PriceTable}, nil
}

// FindCase returns the scenario case with the given id.
func (s *Scenario) FindCase(id string) (Case, error) {
	for _, scenarioCase := range s.Cases {
		if scenarioCase.ID == id {
			return scenarioCase, nil
		}
	}
	return Case{}, fmt.Errorf("%w: %s", ErrUnknownCase, id)
}
