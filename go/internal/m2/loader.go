// Package m2 is the Go runtime for the support-handoff lesson: scenario,
// scripted-route, and failure-fixture loading from the checked-in JSON
// projections, the direct/model router with the fixed 0.80 confidence
// policy, the sender-intent/receiver-input handoff envelope with receiver
// availability and context validation, the 1.0 trace envelope, attribution
// assembly, and the run result contract. It mirrors the TypeScript/Python
// semantics, not their code.
package m2

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// Run modes (the M2 CLI grammar calls them router modes).
const (
	ModeCode  = "code"
	ModeModel = "model"
)

// Canonical M2 statuses.
const (
	StatusSucceeded = "SUCCEEDED"
	StatusFailed    = "FAILED"
)

// The fixed M2 confidence policy threshold; the scenario document must pin
// exactly this value.
const ConfidenceThreshold = 0.80

// Routes and receivers.
const (
	RouteBilling   = "billing"
	RouteTechnical = "technical"
	RouteGeneral   = "general"

	ReceiverBilling   = "billing-specialist"
	ReceiverTechnical = "technical-specialist"
	ReceiverGeneral   = "general-specialist"

	// Sender is the handoff envelope's fixed sender identity.
	Sender = "support-router"
)

// Sentinel errors: unknown cases and mode mismatches are tooling errors
// (exit 2); the domain failure classes live in contracts and map 1:1 from
// the runner's internal sentinels.
var (
	// ErrUnknownCase marks tooling errors for unknown scenario cases.
	ErrUnknownCase = errors.New("m2: unknown scenario case")
	// ErrModeMismatch marks requested-mode/case-mode conflicts.
	ErrModeMismatch = errors.New("m2: requested mode does not match the canonical case mode")
)

// canonicalRoutes is the closed route enum; routeReceivers is the fixed
// route-to-receiver mapping the scenario must pin.
var canonicalRoutes = []string{RouteBilling, RouteTechnical, RouteGeneral}

var routeReceivers = map[string]string{
	RouteBilling:   ReceiverBilling,
	RouteTechnical: ReceiverTechnical,
	RouteGeneral:   ReceiverGeneral,
}

// canonicalReceivers is the closed receiver enum (the receiver directory's
// residents).
var canonicalReceivers = []string{ReceiverBilling, ReceiverTechnical, ReceiverGeneral}

// receiverInputFields is the closed receiver-input field set the failure
// fixtures may omit.
var receiverInputFields = []string{"ticket_id", "request_text"}

// ticketPattern is the closed receiver-input ticket_id shape.
var ticketPattern = regexp.MustCompile(`^TCK-[0-9]{4}$`)

// canonicalCaseIDs is the closed set of the five canonical M2 cases.
var canonicalCaseIDs = []string{
	"code-billing-handoff",
	"model-technical-handoff",
	"model-low-confidence-fallback",
	"handoff-context-loss",
	"handoff-receiver-unavailable",
}

// priceKinds is the closed set of attribution price kinds.
var priceKinds = map[string]bool{
	"read": true, "model_decision": true, "tool_call": true, "effect": true,
	"handoff": true, "route": true, "synthesis": true,
}

// AttributionTables are the scenario's fixture-priced latency/cost tables.
type AttributionTables struct {
	LatencyMS  map[string]int
	PriceTable map[string]int
}

// Case is one support-handoff case: a success expectation or a failure
// expectation (with its failure_ref), never both.
type Case struct {
	ID                        string
	TicketID                  string
	Request                   string
	RouterMode                string
	ExpectedStatus            string
	ExpectedProposedRoute     string
	ExpectedConfidence        float64
	ExpectedSelectedRoute     string
	ExpectedReceiver          string
	ExpectedPolicyOutcome     string
	ExpectedFallbackApplied   bool
	ExpectedSpecialistInvoked bool
	ExpectedFailureCode       string
	FailureRef                string
}

// Scenario is the validated support-handoff scenario document.
type Scenario struct {
	SchemaVersion       string
	ScenarioID          string
	ConfidenceThreshold float64
	RouteReceivers      map[string]string
	Cases               []Case
	Attribution         AttributionTables
}

// scenarioWire mirrors the scenario projection for strict decoding; unknown
// fields are rejected by contracts.DecodeStrict.
type scenarioWire struct {
	SchemaVersion       string            `json:"schema_version"`
	ScenarioID          string            `json:"scenario_id"`
	ConfidenceThreshold *float64          `json:"confidence_threshold"`
	RouteReceivers      map[string]string `json:"route_receivers"`
	Attribution         *struct {
		LatencyMS  map[string]int `json:"latency_ms"`
		PriceTable map[string]int `json:"price_table"`
	} `json:"attribution"`
	Cases []caseWire `json:"cases"`
}

type caseWire struct {
	ID                        string   `json:"id"`
	TicketID                  string   `json:"ticket_id"`
	Request                   string   `json:"request"`
	RouterMode                string   `json:"router_mode"`
	ExpectedStatus            string   `json:"expected_status"`
	ExpectedProposedRoute     string   `json:"expected_proposed_route"`
	ExpectedConfidence        *float64 `json:"expected_confidence"`
	ExpectedSelectedRoute     string   `json:"expected_selected_route"`
	ExpectedReceiver          string   `json:"expected_receiver"`
	ExpectedPolicyOutcome     string   `json:"expected_policy_outcome"`
	ExpectedFallbackApplied   *bool    `json:"expected_fallback_applied"`
	ExpectedSpecialistInvoked *bool    `json:"expected_specialist_invoked"`
	ExpectedFailureCode       *string  `json:"expected_failure_code"`
	FailureRef                *string  `json:"failure_ref"`
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
			"support-handoff.yaml")); err == nil && !info.IsDir() {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", errors.New("m2: repository root not found from " + dir)
		}
		dir = parent
	}
}

// DefaultScenarioPath, DefaultFakeModelPath, and DefaultFailuresPath are the
// checked-in JSON projections of the M2 scenario and scripted fixtures.
func DefaultScenarioPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections",
		"support-handoff", "scenario.json")
}

func DefaultFakeModelPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections",
		"support-handoff", "fake-model.json")
}

func DefaultFailuresPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections",
		"support-handoff", "failures.json")
}

// isCanonicalRoute reports whether the route is inside the enum.
func isCanonicalRoute(route string) bool {
	for _, canonical := range canonicalRoutes {
		if route == canonical {
			return true
		}
	}
	return false
}

// isCanonicalReceiver reports whether the receiver is inside the enum.
func isCanonicalReceiver(receiver string) bool {
	for _, canonical := range canonicalReceivers {
		if receiver == canonical {
			return true
		}
	}
	return false
}

// LoadScenario strict-decodes and validates the scenario projection: the 1.0
// support-handoff document pinning the 0.80 threshold and the canonical
// route-receiver mapping, with unique, well-formed cases drawn from the
// closed canonical set (a success expectation or a failure expectation with
// its failure_ref, never both) and non-empty attribution tables.
func LoadScenario(path string) (*Scenario, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("m2: read scenario: %w", err)
	}
	var wire scenarioWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return nil, fmt.Errorf("m2: invalid scenario projection: %w", err)
	}
	if wire.SchemaVersion != contracts.EnvelopeVersion || wire.ScenarioID != "support-handoff" {
		return nil, fmt.Errorf("m2: unsupported scenario document: schema_version %q, scenario_id %q",
			wire.SchemaVersion, wire.ScenarioID)
	}
	if wire.ConfidenceThreshold == nil || *wire.ConfidenceThreshold != ConfidenceThreshold {
		return nil, fmt.Errorf("m2: confidence_threshold must be %v", ConfidenceThreshold)
	}
	if len(wire.RouteReceivers) != len(canonicalRoutes) {
		return nil, errors.New("m2: route_receivers must map every canonical route")
	}
	for route, receiver := range routeReceivers {
		if wire.RouteReceivers[route] != receiver {
			return nil, fmt.Errorf("m2: route_receivers.%s must be %s", route, receiver)
		}
	}
	tables, err := parseTables(wire.Attribution)
	if err != nil {
		return nil, err
	}
	cases := make([]Case, 0, len(wire.Cases))
	seen := map[string]bool{}
	for _, wireCase := range wire.Cases {
		parsed, err := parseCase(wireCase)
		if err != nil {
			return nil, err
		}
		if seen[parsed.ID] {
			return nil, fmt.Errorf("m2: duplicate case id %q", parsed.ID)
		}
		seen[parsed.ID] = true
		cases = append(cases, parsed)
	}
	if len(cases) != len(canonicalCaseIDs) {
		return nil, fmt.Errorf("m2: scenario must contain exactly the %d canonical M2 cases",
			len(canonicalCaseIDs))
	}
	for _, canonical := range canonicalCaseIDs {
		if !seen[canonical] {
			return nil, fmt.Errorf("m2: scenario is missing canonical case %q", canonical)
		}
	}
	return &Scenario{SchemaVersion: wire.SchemaVersion, ScenarioID: wire.ScenarioID,
		ConfidenceThreshold: *wire.ConfidenceThreshold, RouteReceivers: routeReceivers,
		Cases: cases, Attribution: tables}, nil
}

func parseCase(wireCase caseWire) (Case, error) {
	if wireCase.ID == "" || wireCase.TicketID == "" || wireCase.Request == "" {
		return Case{}, fmt.Errorf("m2: scenario case %q must define id, ticket_id, and request", wireCase.ID)
	}
	if !ticketPattern.MatchString(wireCase.TicketID) {
		return Case{}, fmt.Errorf("m2: scenario case %q ticket_id is invalid", wireCase.ID)
	}
	if wireCase.RouterMode != ModeCode && wireCase.RouterMode != ModeModel {
		return Case{}, fmt.Errorf("m2: scenario case %q router_mode must be code or model", wireCase.ID)
	}
	if wireCase.ExpectedStatus != StatusSucceeded && wireCase.ExpectedStatus != StatusFailed {
		return Case{}, fmt.Errorf("m2: scenario case %q expected_status must be SUCCEEDED or FAILED", wireCase.ID)
	}
	if !isCanonicalRoute(wireCase.ExpectedProposedRoute) || !isCanonicalRoute(wireCase.ExpectedSelectedRoute) {
		return Case{}, fmt.Errorf("m2: scenario case %q expected routes must be canonical", wireCase.ID)
	}
	if wireCase.ExpectedConfidence == nil || *wireCase.ExpectedConfidence < 0 || *wireCase.ExpectedConfidence > 1 {
		return Case{}, fmt.Errorf("m2: scenario case %q expected_confidence must be between 0 and 1", wireCase.ID)
	}
	if !isCanonicalReceiver(wireCase.ExpectedReceiver) {
		return Case{}, fmt.Errorf("m2: scenario case %q expected_receiver is unsupported", wireCase.ID)
	}
	if wireCase.ExpectedPolicyOutcome != "selected" && wireCase.ExpectedPolicyOutcome != "fallback" {
		return Case{}, fmt.Errorf("m2: scenario case %q expected_policy_outcome must be selected or fallback", wireCase.ID)
	}
	if wireCase.ExpectedFallbackApplied == nil || wireCase.ExpectedSpecialistInvoked == nil {
		return Case{}, fmt.Errorf("m2: scenario case %q must define expected_fallback_applied and expected_specialist_invoked", wireCase.ID)
	}
	parsed := Case{
		ID: wireCase.ID, TicketID: wireCase.TicketID, Request: wireCase.Request,
		RouterMode: wireCase.RouterMode, ExpectedStatus: wireCase.ExpectedStatus,
		ExpectedProposedRoute:     wireCase.ExpectedProposedRoute,
		ExpectedConfidence:        *wireCase.ExpectedConfidence,
		ExpectedSelectedRoute:     wireCase.ExpectedSelectedRoute,
		ExpectedReceiver:          wireCase.ExpectedReceiver,
		ExpectedPolicyOutcome:     wireCase.ExpectedPolicyOutcome,
		ExpectedFallbackApplied:   *wireCase.ExpectedFallbackApplied,
		ExpectedSpecialistInvoked: *wireCase.ExpectedSpecialistInvoked,
	}
	switch wireCase.ExpectedStatus {
	case StatusSucceeded:
		if wireCase.ExpectedFailureCode != nil || wireCase.FailureRef != nil {
			return Case{}, fmt.Errorf("m2: scenario case %q success cases cannot define failure fields", wireCase.ID)
		}
		return parsed, nil
	default:
		if wireCase.ExpectedFailureCode == nil || !isHandoffFailureCode(*wireCase.ExpectedFailureCode) {
			return Case{}, fmt.Errorf("m2: scenario case %q expected_failure_code is unsupported", wireCase.ID)
		}
		if wireCase.FailureRef == nil || *wireCase.FailureRef == "" {
			return Case{}, fmt.Errorf("m2: scenario case %q failed cases must carry a failure_ref", wireCase.ID)
		}
		if *wireCase.FailureRef != wireCase.ID {
			return Case{}, fmt.Errorf("m2: scenario case %q has an invalid M2 failure reference", wireCase.ID)
		}
		parsed.ExpectedFailureCode = *wireCase.ExpectedFailureCode
		parsed.FailureRef = *wireCase.FailureRef
		return parsed, nil
	}
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

func parseTables(raw *struct {
	LatencyMS  map[string]int `json:"latency_ms"`
	PriceTable map[string]int `json:"price_table"`
}) (AttributionTables, error) {
	if raw == nil {
		return AttributionTables{}, errors.New("m2: scenario attribution tables are required")
	}
	if len(raw.LatencyMS) == 0 {
		return AttributionTables{}, errors.New("m2: invalid attribution latency table: must be nonempty")
	}
	if len(raw.PriceTable) == 0 {
		return AttributionTables{}, errors.New("m2: invalid attribution price table: must be nonempty")
	}
	for step, latency := range raw.LatencyMS {
		if step == "" || latency < 0 {
			return AttributionTables{}, fmt.Errorf("m2: invalid attribution latency for %q", step)
		}
	}
	for kind, price := range raw.PriceTable {
		if !priceKinds[kind] || price < 0 {
			return AttributionTables{}, fmt.Errorf("m2: invalid attribution price kind %q", kind)
		}
	}
	if read, ok := raw.PriceTable["read"]; ok && read != 0 {
		return AttributionTables{}, errors.New("m2: attribution reads must price zero")
	}
	return AttributionTables{LatencyMS: raw.LatencyMS, PriceTable: raw.PriceTable}, nil
}

// fakeModelWire mirrors the fake-model decisions projection for strict
// decoding: each entry is the projected decision value itself (the generator
// strips the source fixture's `return` wrapper), carried verbatim and
// validated per case by the runner's closed route-decision check.
type fakeModelWire struct {
	SchemaVersion string                     `json:"schema_version"`
	ScenarioID    string                     `json:"scenario_id"`
	Decisions     map[string]json.RawMessage `json:"decisions"`
}

// LoadFakeModelDecisions strict-decodes and validates the fake-model
// decisions projection: the 1.0 support-handoff document whose decisions map
// each case id to a scripted decision value.
func LoadFakeModelDecisions(path string) (map[string]json.RawMessage, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("m2: read fake-model projection: %w", err)
	}
	var wire fakeModelWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return nil, fmt.Errorf("m2: invalid fake-model projection: %w", err)
	}
	if wire.SchemaVersion != contracts.EnvelopeVersion || wire.ScenarioID != "support-handoff" {
		return nil, fmt.Errorf("m2: unsupported fake-model document: schema_version %q, scenario_id %q",
			wire.SchemaVersion, wire.ScenarioID)
	}
	if wire.Decisions == nil {
		return nil, errors.New("m2: fake-model document must contain decisions")
	}
	decisions := make(map[string]json.RawMessage, len(wire.Decisions))
	for caseID, entry := range wire.Decisions {
		decisions[caseID] = append(json.RawMessage(nil), entry...)
	}
	return decisions, nil
}

// FailureFixture is one scripted failure operator: omit receiver-input
// fields (context loss) or mark receivers unavailable. Exactly one operator
// is defined per fixture.
type FailureFixture struct {
	OmitReceiverInputFields []string
	UnavailableReceivers    []string
}

// IsOmitFields reports whether the fixture omits receiver-input fields.
func (f *FailureFixture) IsOmitFields() bool { return f != nil && len(f.OmitReceiverInputFields) > 0 }

// MarksUnavailable reports whether the fixture marks the receiver
// unavailable.
func (f *FailureFixture) MarksUnavailable(receiver string) bool {
	if f == nil {
		return false
	}
	for _, unavailable := range f.UnavailableReceivers {
		if unavailable == receiver {
			return true
		}
	}
	return false
}

// failureFixtureWire mirrors one failure-fixture record: exactly one of the
// two operators.
type failureFixtureWire struct {
	OmitReceiverInputFields *[]string `json:"omit_receiver_input_fields"`
	UnavailableReceivers    *[]string `json:"unavailable_receivers"`
}

// failuresWire mirrors the failures projection for strict decoding.
type failuresWire struct {
	SchemaVersion string                        `json:"schema_version"`
	ScenarioID    string                        `json:"scenario_id"`
	Failures      map[string]failureFixtureWire `json:"failures"`
}

// LoadFailureFixtures strict-decodes and validates the failure fixtures
// projection: the 1.0 support-handoff document mapping failure refs to
// exactly one scripted operator each, over the closed field/receiver sets.
func LoadFailureFixtures(path string) (map[string]*FailureFixture, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("m2: read failures projection: %w", err)
	}
	var wire failuresWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return nil, fmt.Errorf("m2: invalid failures projection: %w", err)
	}
	if wire.SchemaVersion != contracts.EnvelopeVersion || wire.ScenarioID != "support-handoff" {
		return nil, fmt.Errorf("m2: unsupported failures document: schema_version %q, scenario_id %q",
			wire.SchemaVersion, wire.ScenarioID)
	}
	if wire.Failures == nil {
		return nil, errors.New("m2: failures document must contain failures")
	}
	fixtures := make(map[string]*FailureFixture, len(wire.Failures))
	for failureID, entry := range wire.Failures {
		if (entry.OmitReceiverInputFields == nil) == (entry.UnavailableReceivers == nil) {
			return nil, fmt.Errorf("m2: failure %s must define exactly one operator", failureID)
		}
		fixture := &FailureFixture{}
		if entry.OmitReceiverInputFields != nil {
			fields := *entry.OmitReceiverInputFields
			if len(fields) == 0 {
				return nil, fmt.Errorf("m2: failure %s omit_receiver_input_fields must be non-empty", failureID)
			}
			for _, field := range fields {
				if !isReceiverInputField(field) {
					return nil, fmt.Errorf("m2: failure %s omit_receiver_input_fields is invalid", failureID)
				}
			}
			fixture.OmitReceiverInputFields = fields
		}
		if entry.UnavailableReceivers != nil {
			receivers := *entry.UnavailableReceivers
			if len(receivers) == 0 {
				return nil, fmt.Errorf("m2: failure %s unavailable_receivers must be non-empty", failureID)
			}
			for _, receiver := range receivers {
				if !isCanonicalReceiver(receiver) {
					return nil, fmt.Errorf("m2: failure %s unavailable_receivers is invalid", failureID)
				}
			}
			fixture.UnavailableReceivers = receivers
		}
		fixtures[failureID] = fixture
	}
	return fixtures, nil
}

func isReceiverInputField(field string) bool {
	for _, canonical := range receiverInputFields {
		if field == canonical {
			return true
		}
	}
	return false
}
