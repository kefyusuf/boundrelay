// Package m1 is the Go runtime for the order-investigation lesson: scenario
// and scripted-fixture loading from the checked-in JSON projections, the
// closed fake tool registry, the bounded agent loop with hard step/token
// budgets, the 1.0 trace envelope, attribution assembly, and the run result
// contract. It mirrors the TypeScript/Python semantics, not their code.
package m1

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// Run modes.
const (
	ModeDirect = "direct"
	ModeAgent  = "agent"
)

// Canonical M1 statuses.
const (
	StatusSucceeded = "SUCCEEDED"
	StatusFailed    = "FAILED"
)

// Sentinel errors: unknown cases, mode mismatches, and unreadable scripted
// fixtures are tooling errors (exit 2); the domain failure classes live in
// contracts and map 1:1 from the loop's internal sentinels.
var (
	// ErrUnknownCase marks tooling errors for unknown scenario cases.
	ErrUnknownCase = errors.New("m1: unknown scenario case")
	// ErrModeMismatch marks requested-mode/case-mode conflicts.
	ErrModeMismatch = errors.New("m1: requested mode does not match the canonical case mode")
)

// stepPriceKinds is the closed set of attribution price kinds.
var stepPriceKinds = map[string]bool{
	"read": true, "model_decision": true, "tool_call": true, "effect": true,
	"handoff": true, "route": true, "synthesis": true,
}

// AttributionTables are the scenario's fixture-priced latency/cost tables.
type AttributionTables struct {
	LatencyMS  map[string]int
	PriceTable map[string]int
}

// DirectCall is a direct-mode scripted tool call from the scenario.
type DirectCall struct {
	CallID    string
	Tool      string
	Arguments map[string]any
}

// Case is one order-investigation case: a success expectation (plus the
// direct call in direct mode) or a failure expectation, never both.
type Case struct {
	ID                      string
	Mode                    string
	Request                 string
	MaxSteps                int
	MaxTokens               int
	DirectCall              *DirectCall
	ExpectedStatus          string
	ExpectedAnswer          string
	ExpectedFailureCode     string
	ExpectedModelSteps      int
	ExpectedTokensUsed      int
	ExpectedToolInvocations int
}

// Scenario is the validated order-investigation scenario document.
type Scenario struct {
	SchemaVersion string
	ScenarioID    string
	Cases         []Case
	Attribution   AttributionTables
}

// scenarioWire mirrors the scenario projection for strict decoding; unknown
// fields are rejected by contracts.DecodeStrict.
type scenarioWire struct {
	SchemaVersion string `json:"schema_version"`
	ScenarioID    string `json:"scenario_id"`
	Attribution   *struct {
		LatencyMS  map[string]int `json:"latency_ms"`
		PriceTable map[string]int `json:"price_table"`
	} `json:"attribution"`
	Cases []caseWire `json:"cases"`
}

type caseWire struct {
	ID                      string          `json:"id"`
	Mode                    string          `json:"mode"`
	Request                 string          `json:"request"`
	MaxSteps                *int            `json:"max_steps"`
	MaxTokens               *int            `json:"max_tokens"`
	DirectCall              *directCallWire `json:"direct_call"`
	ExpectedStatus          string          `json:"expected_status"`
	ExpectedAnswer          *string         `json:"expected_answer"`
	ExpectedFailureCode     *string         `json:"expected_failure_code"`
	ExpectedModelSteps      *int            `json:"expected_model_steps"`
	ExpectedTokensUsed      *int            `json:"expected_tokens_used"`
	ExpectedToolInvocations *int            `json:"expected_tool_invocations"`
}

type directCallWire struct {
	CallID    string         `json:"call_id"`
	Tool      string         `json:"tool"`
	Arguments map[string]any `json:"arguments"`
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
			"order-investigation.yaml")); err == nil && !info.IsDir() {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", errors.New("m1: repository root not found from " + dir)
		}
		dir = parent
	}
}

// DefaultScenarioPath, DefaultFakeModelPath, and DefaultFakeToolsPath are
// the checked-in JSON projections of the M1 scenario and scripted fixtures.
func DefaultScenarioPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections",
		"order-investigation", "scenario.json")
}

func DefaultFakeModelPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections",
		"order-investigation", "fake-model.json")
}

func DefaultFakeToolsPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections",
		"order-investigation", "fake-tools.json")
}

// LoadScenario strict-decodes and validates the scenario projection: the
// 1.0 order-investigation document with unique, well-formed cases (a
// success expectation or a failure expectation, never both; direct calls
// only in direct mode) and non-empty attribution tables.
func LoadScenario(path string) (*Scenario, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("m1: read scenario: %w", err)
	}
	var wire scenarioWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return nil, fmt.Errorf("m1: invalid scenario projection: %w", err)
	}
	if wire.SchemaVersion != contracts.EnvelopeVersion || wire.ScenarioID != "order-investigation" {
		return nil, fmt.Errorf("m1: unsupported scenario document: schema_version %q, scenario_id %q",
			wire.SchemaVersion, wire.ScenarioID)
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
			return nil, fmt.Errorf("m1: duplicate case id %q", parsed.ID)
		}
		seen[parsed.ID] = true
		cases = append(cases, parsed)
	}
	return &Scenario{SchemaVersion: wire.SchemaVersion, ScenarioID: wire.ScenarioID,
		Cases: cases, Attribution: tables}, nil
}

func parseCase(wireCase caseWire) (Case, error) {
	if wireCase.ID == "" || wireCase.Request == "" {
		return Case{}, fmt.Errorf("m1: scenario case %q must define id and request", wireCase.ID)
	}
	if wireCase.Mode != ModeDirect && wireCase.Mode != ModeAgent {
		return Case{}, fmt.Errorf("m1: scenario case %q mode must be direct or agent", wireCase.ID)
	}
	maxSteps, err := requireNonNegative(wireCase.MaxSteps, wireCase.ID, "max_steps")
	if err != nil {
		return Case{}, err
	}
	maxTokens, err := requireNonNegative(wireCase.MaxTokens, wireCase.ID, "max_tokens")
	if err != nil {
		return Case{}, err
	}
	expectedModelSteps, err := requireNonNegative(wireCase.ExpectedModelSteps, wireCase.ID, "expected_model_steps")
	if err != nil {
		return Case{}, err
	}
	expectedTokensUsed, err := requireNonNegative(wireCase.ExpectedTokensUsed, wireCase.ID, "expected_tokens_used")
	if err != nil {
		return Case{}, err
	}
	expectedToolInvocations, err := requireNonNegative(wireCase.ExpectedToolInvocations, wireCase.ID, "expected_tool_invocations")
	if err != nil {
		return Case{}, err
	}
	parsed := Case{
		ID: wireCase.ID, Mode: wireCase.Mode, Request: wireCase.Request,
		MaxSteps: maxSteps, MaxTokens: maxTokens,
		ExpectedStatus:     wireCase.ExpectedStatus,
		ExpectedModelSteps: expectedModelSteps, ExpectedTokensUsed: expectedTokensUsed,
		ExpectedToolInvocations: expectedToolInvocations,
	}
	switch wireCase.ExpectedStatus {
	case StatusSucceeded:
		if wireCase.ExpectedAnswer == nil || *wireCase.ExpectedAnswer == "" {
			return Case{}, fmt.Errorf("m1: scenario case %q expected_answer must be a non-empty string", wireCase.ID)
		}
		parsed.ExpectedAnswer = *wireCase.ExpectedAnswer
		if wireCase.ExpectedFailureCode != nil {
			return Case{}, fmt.Errorf("m1: scenario case %q cannot define expected_failure_code on success", wireCase.ID)
		}
		if wireCase.Mode == ModeDirect {
			call, err := parseDirectCall(wireCase.DirectCall)
			if err != nil {
				return Case{}, err
			}
			parsed.DirectCall = call
			return parsed, nil
		}
		if wireCase.DirectCall != nil {
			return Case{}, fmt.Errorf("m1: scenario case %q agent mode cannot define direct_call", wireCase.ID)
		}
		return parsed, nil
	case StatusFailed:
		if wireCase.Mode != ModeAgent {
			return Case{}, fmt.Errorf("m1: scenario case %q failed canonical cases must use agent mode", wireCase.ID)
		}
		if wireCase.ExpectedFailureCode == nil || !contracts.IsM1FailureCode(*wireCase.ExpectedFailureCode) {
			return Case{}, fmt.Errorf("m1: scenario case %q expected_failure_code is unsupported", wireCase.ID)
		}
		if wireCase.ExpectedAnswer != nil || wireCase.DirectCall != nil {
			return Case{}, fmt.Errorf("m1: scenario case %q failed case cannot define success-only fields", wireCase.ID)
		}
		parsed.ExpectedFailureCode = *wireCase.ExpectedFailureCode
		return parsed, nil
	default:
		return Case{}, fmt.Errorf("m1: scenario case %q expected_status must be SUCCEEDED or FAILED", wireCase.ID)
	}
}

func parseDirectCall(raw *directCallWire) (*DirectCall, error) {
	if raw == nil {
		return nil, errors.New("m1: direct case must define a direct_call")
	}
	if raw.CallID == "" {
		return nil, errors.New("m1: direct_call.call_id must be a non-empty string")
	}
	if !isCanonicalTool(raw.Tool) {
		return nil, fmt.Errorf("m1: direct_call.tool %q must name an M1 tool", raw.Tool)
	}
	if raw.Arguments == nil {
		return nil, errors.New("m1: direct_call.arguments must be an object")
	}
	return &DirectCall{CallID: raw.CallID, Tool: raw.Tool, Arguments: raw.Arguments}, nil
}

func requireNonNegative(value *int, caseID, field string) (int, error) {
	if value == nil || *value < 0 {
		return 0, fmt.Errorf("m1: scenario case %q %s must be a non-negative integer", caseID, field)
	}
	return *value, nil
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
		return AttributionTables{}, errors.New("m1: scenario attribution tables are required")
	}
	if len(raw.LatencyMS) == 0 {
		return AttributionTables{}, errors.New("m1: invalid attribution latency table: must be nonempty")
	}
	if len(raw.PriceTable) == 0 {
		return AttributionTables{}, errors.New("m1: invalid attribution price table: must be nonempty")
	}
	for step, latency := range raw.LatencyMS {
		if step == "" || latency < 0 {
			return AttributionTables{}, fmt.Errorf("m1: invalid attribution latency for %q", step)
		}
	}
	for kind, price := range raw.PriceTable {
		if !stepPriceKinds[kind] || price < 0 {
			return AttributionTables{}, fmt.Errorf("m1: invalid attribution price kind %q", kind)
		}
	}
	if read, ok := raw.PriceTable["read"]; ok && read != 0 {
		return AttributionTables{}, errors.New("m1: attribution reads must price zero")
	}
	return AttributionTables{LatencyMS: raw.LatencyMS, PriceTable: raw.PriceTable}, nil
}

// fakeModelWire mirrors the fake-model turns projection for strict
// decoding: each trajectory entry is the projected turn value itself (the
// generator strips the source fixture's `return` wrapper), carried verbatim
// and validated per step by ValidateModelTurn.
type fakeModelWire struct {
	SchemaVersion string                       `json:"schema_version"`
	ScenarioID    string                       `json:"scenario_id"`
	Trajectories  map[string][]json.RawMessage `json:"trajectories"`
}

// LoadFakeModelTurns strict-decodes and validates the fake-model turns
// projection: the 1.0 order-investigation document whose trajectories map
// each case id to a non-empty array of scripted turns.
func LoadFakeModelTurns(path string) (map[string][]json.RawMessage, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("m1: read fake-model projection: %w", err)
	}
	var wire fakeModelWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return nil, fmt.Errorf("m1: invalid fake-model projection: %w", err)
	}
	if wire.SchemaVersion != contracts.EnvelopeVersion || wire.ScenarioID != "order-investigation" {
		return nil, fmt.Errorf("m1: unsupported fake-model document: schema_version %q, scenario_id %q",
			wire.SchemaVersion, wire.ScenarioID)
	}
	if wire.Trajectories == nil {
		return nil, errors.New("m1: fake-model document must contain trajectories")
	}
	turns := make(map[string][]json.RawMessage, len(wire.Trajectories))
	for caseID, entries := range wire.Trajectories {
		if len(entries) == 0 {
			return nil, fmt.Errorf("m1: trajectory %s must be a non-empty array", caseID)
		}
		projected := make([]json.RawMessage, 0, len(entries))
		for _, entry := range entries {
			projected = append(projected, append(json.RawMessage(nil), entry...))
		}
		turns[caseID] = projected
	}
	return turns, nil
}

// fakeToolEntryWire mirrors one fake-tools record: an output, a timeout
// behavior, or a declared failure behavior.
type fakeToolEntryWire struct {
	Behavior string         `json:"behavior"`
	Output   map[string]any `json:"output"`
}

// fakeToolsWire mirrors the fake-tools projection for strict decoding.
type fakeToolsWire struct {
	SchemaVersion string                       `json:"schema_version"`
	ScenarioID    string                       `json:"scenario_id"`
	Orders        map[string]fakeToolEntryWire `json:"orders"`
	Shipments     map[string]fakeToolEntryWire `json:"shipments"`
}

// FakeToolData is the validated fake-tools projection behind the registry.
type FakeToolData struct {
	Orders    map[string]fakeToolEntryWire
	Shipments map[string]fakeToolEntryWire
}

// LoadFakeTools strict-decodes and validates the fake-tools projection: the
// 1.0 order-investigation document defining the orders and shipments maps.
func LoadFakeTools(path string) (*FakeToolData, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("m1: read fake-tools projection: %w", err)
	}
	var wire fakeToolsWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return nil, fmt.Errorf("m1: invalid fake-tools projection: %w", err)
	}
	if wire.SchemaVersion != contracts.EnvelopeVersion || wire.ScenarioID != "order-investigation" {
		return nil, fmt.Errorf("m1: unsupported fake-tools document: schema_version %q, scenario_id %q",
			wire.SchemaVersion, wire.ScenarioID)
	}
	if wire.Orders == nil || wire.Shipments == nil {
		return nil, errors.New("m1: fake-tools document must define orders and shipments")
	}
	return &FakeToolData{Orders: wire.Orders, Shipments: wire.Shipments}, nil
}
