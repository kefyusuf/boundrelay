// Package fixtures loads the checked-in M3 order-brief projections
// (fixtures/goprojections/order-brief/scenario.json and workers.json) and
// the golden result projections, strict-decoded and validated. The mapping
// never feeds the goldens or the gates: it reads these checked-in
// artifacts only, exactly like the canonical runtimes do.
package fixtures

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Execution modes.
const (
	ModeSequential = "sequential"
	ModeParallel   = "parallel"
)

// CanonicalWorkerIDs is the fixed worker execution and collector order.
var CanonicalWorkerIDs = []string{"order-details", "payment-status", "delivery-status"}

// CaseSpec is one order-brief case: mode, worker fixture reference, and the
// deterministic completion order.
type CaseSpec struct {
	CaseID          string
	ExecutionMode   string
	WorkerFixture   string
	CompletionOrder []string
}

// Limit returns the admission cap for the case's mode (1 sequential, 2
// parallel).
func (c CaseSpec) Limit() int {
	if c.ExecutionMode == ModeParallel {
		return 2
	}
	return 1
}

// AttributionTables are the scenario's fixture-priced latency/cost tables.
type AttributionTables struct {
	LatencyMS  map[string]int `json:"latency_ms"`
	PriceTable map[string]int `json:"price_table"`
}

// Scenario is the validated order-brief scenario document.
type Scenario struct {
	SchemaVersion string            `json:"schema_version"`
	ScenarioID    string            `json:"scenario_id"`
	OrderID       string            `json:"order_id"`
	Attribution   AttributionTables `json:"attribution"`
	Cases         []CaseSpec
}

// WorkerInstruction is one scripted worker body: return an output or raise
// the declared failure.
type WorkerInstruction struct {
	Operation   string
	Output      json.RawMessage
	FailureCode string
}

// WorkerInstructions maps worker id to its scripted body.
type WorkerInstructions map[string]WorkerInstruction

// ErrUnknownCase marks tooling errors for unknown scenario cases.
var ErrUnknownCase = errors.New("fixtures: unknown scenario case")

// FindCase returns the case with the given id.
func (s *Scenario) FindCase(id string) (CaseSpec, error) {
	for _, scenarioCase := range s.Cases {
		if scenarioCase.CaseID == id {
			return scenarioCase, nil
		}
	}
	return CaseSpec{}, fmt.Errorf("%w: %s", ErrUnknownCase, id)
}

// FindRepoRoot walks up from the working directory to the repository root
// (marked by fixtures/scenarios/order-brief.yaml). The BOUNDRELAY_REPO_ROOT
// environment variable overrides the walk.
func FindRepoRoot() (string, error) {
	if override := os.Getenv("BOUNDRELAY_REPO_ROOT"); override != "" {
		if info, err := os.Stat(filepath.Join(override, "fixtures", "goprojections", "order-brief", "scenario.json")); err == nil && !info.IsDir() {
			return override, nil
		}
		return "", fmt.Errorf("fixtures: BOUNDRELAY_REPO_ROOT %q carries no order-brief projections", override)
	}
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if info, err := os.Stat(filepath.Join(dir, "fixtures", "scenarios", "order-brief.yaml")); err == nil && !info.IsDir() {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", errors.New("fixtures: repository root not found from " + dir)
		}
		dir = parent
	}
}

// DefaultScenarioPath and DefaultWorkersPath are the checked-in JSON
// projections of the M3 scenario and worker fixtures.
func DefaultScenarioPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections", "order-brief", "scenario.json")
}

// DefaultWorkersPath is the checked-in JSON projection of the M3 workers.
func DefaultWorkersPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections", "order-brief", "workers.json")
}

// GoldenPath is the checked-in golden projection for one case.
func GoldenPath(repoRoot string, caseID string) string {
	return filepath.Join(repoRoot, "fixtures", "goldens", "order-brief", caseID+".json")
}

// Golden is the subset of a golden projection the mapping reads: the
// result_projection parity target and its attribution block.
type Golden struct {
	CaseKey          string          `json:"case_key"`
	ResultProjection json.RawMessage `json:"result_projection"`
}

// LoadGolden reads one golden projection. The golden is a checked-in
// read-only parity artifact carrying extra fields (languages,
// event_sequence, ...); only case_key and result_projection are extracted.
func LoadGolden(path string) (Golden, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return Golden{}, fmt.Errorf("fixtures: read golden: %w", err)
	}
	var golden Golden
	if err := json.Unmarshal(raw, &golden); err != nil {
		return Golden{}, fmt.Errorf("fixtures: invalid golden projection: %w", err)
	}
	if golden.CaseKey == "" || golden.ResultProjection == nil {
		return Golden{}, fmt.Errorf("fixtures: golden %s is missing case_key or result_projection", path)
	}
	return golden, nil
}

// strictDecode rejects unknown fields and trailing data.
func strictDecode(raw []byte, target any) error {
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.DisallowUnknownFields()
	if err := dec.Decode(target); err != nil {
		return err
	}
	if dec.More() {
		return errors.New("trailing data after JSON document")
	}
	return nil
}

// LoadScenario strict-decodes and validates the scenario projection against
// the workers projection: header, six unique cases with bounded modes, a
// completion permutation each, in-bounds fixture references, attribution
// tables, and a feasible completion schedule per mode.
func LoadScenario(scenarioPath, workersPath string) (*Scenario, error) {
	fixtures, err := LoadWorkerFixtures(workersPath)
	if err != nil {
		return nil, err
	}
	raw, err := os.ReadFile(scenarioPath)
	if err != nil {
		return nil, fmt.Errorf("fixtures: read scenario: %w", err)
	}
	var wire struct {
		SchemaVersion string `json:"schema_version"`
		ScenarioID    string `json:"scenario_id"`
		OrderID       string `json:"order_id"`
		Attribution   *struct {
			LatencyMS  map[string]int `json:"latency_ms"`
			PriceTable map[string]int `json:"price_table"`
		} `json:"attribution"`
		Cases []struct {
			CaseID          string   `json:"case_id"`
			ExecutionMode   string   `json:"execution_mode"`
			WorkerFixture   string   `json:"worker_fixture"`
			CompletionOrder []string `json:"completion_order"`
		} `json:"cases"`
	}
	if err := strictDecode(raw, &wire); err != nil {
		return nil, fmt.Errorf("fixtures: invalid scenario projection: %w", err)
	}
	if wire.SchemaVersion != "1.0" || wire.ScenarioID != "order-brief" {
		return nil, fmt.Errorf("fixtures: unsupported scenario: schema_version %q, scenario_id %q",
			wire.SchemaVersion, wire.ScenarioID)
	}
	if !isOrderID(wire.OrderID) {
		return nil, fmt.Errorf("fixtures: invalid order_id %q", wire.OrderID)
	}
	if len(wire.Cases) != 6 {
		return nil, fmt.Errorf("fixtures: scenario must carry six cases, got %d", len(wire.Cases))
	}
	if wire.Attribution == nil || len(wire.Attribution.LatencyMS) == 0 || len(wire.Attribution.PriceTable) == 0 {
		return nil, errors.New("fixtures: scenario attribution tables are required")
	}
	for step, latency := range wire.Attribution.LatencyMS {
		if step == "" || latency < 0 {
			return nil, fmt.Errorf("fixtures: invalid attribution latency for %q", step)
		}
	}
	for kind, price := range wire.Attribution.PriceTable {
		if kind != "read" && kind != "synthesis" {
			return nil, fmt.Errorf("fixtures: invalid attribution price kind %q", kind)
		}
		if price < 0 {
			return nil, fmt.Errorf("fixtures: invalid attribution price for %q", kind)
		}
	}
	if read, ok := wire.Attribution.PriceTable["read"]; ok && read != 0 {
		return nil, errors.New("fixtures: attribution reads must price zero")
	}
	cases := make([]CaseSpec, 0, len(wire.Cases))
	seen := map[string]bool{}
	for _, wireCase := range wire.Cases {
		spec, err := parseCase(wireCase, fixtures)
		if err != nil {
			return nil, err
		}
		if seen[spec.CaseID] {
			return nil, fmt.Errorf("fixtures: duplicate case id %q", spec.CaseID)
		}
		seen[spec.CaseID] = true
		cases = append(cases, spec)
	}
	return &Scenario{SchemaVersion: wire.SchemaVersion, ScenarioID: wire.ScenarioID,
		OrderID: wire.OrderID,
		Attribution: AttributionTables{
			LatencyMS:  wire.Attribution.LatencyMS,
			PriceTable: wire.Attribution.PriceTable,
		}, Cases: cases}, nil
}

func parseCase(wireCase struct {
	CaseID          string   `json:"case_id"`
	ExecutionMode   string   `json:"execution_mode"`
	WorkerFixture   string   `json:"worker_fixture"`
	CompletionOrder []string `json:"completion_order"`
}, fixtures map[string]WorkerInstructions) (CaseSpec, error) {
	if wireCase.CaseID == "" {
		return CaseSpec{}, errors.New("fixtures: case id is required")
	}
	if wireCase.ExecutionMode != ModeSequential && wireCase.ExecutionMode != ModeParallel {
		return CaseSpec{}, fmt.Errorf("fixtures: case %q execution_mode must be sequential or parallel", wireCase.CaseID)
	}
	if !strings.HasPrefix(wireCase.WorkerFixture, "fixtures/workers/order-brief/") {
		return CaseSpec{}, fmt.Errorf("fixtures: case %q worker fixture escapes root: %s",
			wireCase.CaseID, wireCase.WorkerFixture)
	}
	if _, ok := fixtures[wireCase.WorkerFixture]; !ok {
		return CaseSpec{}, fmt.Errorf("fixtures: case %q references unknown worker fixture %s",
			wireCase.CaseID, wireCase.WorkerFixture)
	}
	if len(wireCase.CompletionOrder) != len(CanonicalWorkerIDs) {
		return CaseSpec{}, fmt.Errorf("fixtures: case %q completion order must be a permutation", wireCase.CaseID)
	}
	seen := map[string]bool{}
	for _, id := range wireCase.CompletionOrder {
		if !isCanonicalWorker(id) || seen[id] {
			return CaseSpec{}, fmt.Errorf("fixtures: case %q completion order must be a permutation", wireCase.CaseID)
		}
		seen[id] = true
	}
	if !completionScheduleFeasible(wireCase.ExecutionMode, wireCase.CompletionOrder) {
		return CaseSpec{}, fmt.Errorf("fixtures: case %q has an infeasible completion schedule", wireCase.CaseID)
	}
	return CaseSpec{CaseID: wireCase.CaseID, ExecutionMode: wireCase.ExecutionMode,
		WorkerFixture:   wireCase.WorkerFixture,
		CompletionOrder: append([]string(nil), wireCase.CompletionOrder...)}, nil
}

// completionScheduleFeasible simulates bounded admission over the canonical
// queue; every scripted completion must name an active worker.
func completionScheduleFeasible(mode string, completionOrder []string) bool {
	limit := 1
	if mode == ModeParallel {
		limit = 2
	}
	pending := append([]string(nil), CanonicalWorkerIDs...)
	active := map[string]bool{}
	for _, next := range completionOrder {
		for len(active) < limit && len(pending) > 0 {
			active[pending[0]] = true
			pending = pending[1:]
		}
		if !active[next] {
			return false
		}
		delete(active, next)
	}
	return true
}

func isCanonicalWorker(id string) bool {
	for _, canonical := range CanonicalWorkerIDs {
		if id == canonical {
			return true
		}
	}
	return false
}

func isOrderID(value string) bool {
	if len(value) != 8 || value[:4] != "ORD-" {
		return false
	}
	for _, digit := range value[4:] {
		if digit < '0' || digit > '9' {
			return false
		}
	}
	return true
}

// LoadWorkerFixtures strict-decodes and validates the workers projection:
// every entry covers exactly the canonical workers with well-formed
// instructions (return+output, or raise+WORKER_EXECUTION_FAILED).
func LoadWorkerFixtures(path string) (map[string]WorkerInstructions, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("fixtures: read workers projection: %w", err)
	}
	var wire map[string]map[string]struct {
		Operation   string          `json:"operation"`
		Output      json.RawMessage `json:"output"`
		FailureCode *string         `json:"failure_code"`
	}
	if err := strictDecode(raw, &wire); err != nil {
		return nil, fmt.Errorf("fixtures: invalid workers projection: %w", err)
	}
	fixtures := make(map[string]WorkerInstructions, len(wire))
	for relpath, entry := range wire {
		if !strings.HasPrefix(relpath, "fixtures/workers/order-brief/") {
			return nil, fmt.Errorf("fixtures: worker fixture escapes root: %s", relpath)
		}
		instructions, err := parseInstructions(entry)
		if err != nil {
			return nil, fmt.Errorf("fixtures: worker fixture %s: %w", relpath, err)
		}
		fixtures[relpath] = instructions
	}
	return fixtures, nil
}

func parseInstructions(entry map[string]struct {
	Operation   string          `json:"operation"`
	Output      json.RawMessage `json:"output"`
	FailureCode *string         `json:"failure_code"`
}) (WorkerInstructions, error) {
	if len(entry) != len(CanonicalWorkerIDs) {
		return nil, errors.New("worker fixture must script exactly the canonical workers")
	}
	instructions := WorkerInstructions{}
	for _, id := range CanonicalWorkerIDs {
		instruction, ok := entry[id]
		if !ok {
			return nil, fmt.Errorf("worker %s missing from fixture", id)
		}
		switch {
		case instruction.Operation == "return" && instruction.Output != nil && instruction.FailureCode == nil:
			instructions[id] = WorkerInstruction{Operation: "return", Output: instruction.Output}
		case instruction.Operation == "raise" && instruction.Output == nil &&
			instruction.FailureCode != nil && *instruction.FailureCode == "WORKER_EXECUTION_FAILED":
			instructions[id] = WorkerInstruction{Operation: "raise",
				FailureCode: *instruction.FailureCode}
		default:
			return nil, fmt.Errorf("worker %s has an invalid operation", id)
		}
	}
	return instructions, nil
}
