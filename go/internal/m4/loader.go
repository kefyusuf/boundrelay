// Package m4 is the Go runtime for the order-brief-recovery lesson: the
// typed, digest-protected run-state document with atomic write-ahead
// checkpoints, the bounded concurrent executor with Ruling-3 control
// shaping, canonical fan-in collection, brief synthesis, fail-closed resume
// and replay, the 1.0 trace envelope, and the run result contract. It
// mirrors the TypeScript/Python semantics, not their code.
package m4

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// Execution modes and the fixed worker queue (shared with the order-brief
// lesson; the recovery runtime reuses its workers unchanged).
const (
	ModeSequential = "sequential"
	ModeParallel   = "parallel"
)

// Sentinels: declared worker failures become WORKER_EXECUTION_FAILED
// outcomes; unknown cases are tooling errors.
var (
	// ErrWorkerExecution is the declared-failure sentinel workers raise;
	// it maps 1:1 to the WORKER_EXECUTION_FAILED failure code.
	ErrWorkerExecution = errors.New("m4: declared worker failure")
	// ErrUnknownCase marks tooling errors for unknown scenario cases.
	ErrUnknownCase = errors.New("m4: unknown scenario case")
)

// WorkerOutcome aliases the shared M3 worker result shape.
type WorkerOutcome = contracts.WorkerOutcome

// orderIDPattern mirrors the ORD-#### scenario/result constraint.
var orderIDPattern = regexp.MustCompile(`^ORD-[0-9]{4}$`)

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

// RecoveryControls are the scripted crash/cancellation controls; at most one
// may be set per case.
type RecoveryControls struct {
	CrashAfter   string
	CancelBefore string
}

// CaseSpec is one order-brief-recovery case: mode, worker fixture
// reference, the deterministic completion order, and the optional scripted
// control, replay anchor, or tamper marker.
type CaseSpec struct {
	CaseID          string
	ExecutionMode   string
	WorkerFixture   string
	CompletionOrder []string
	Controls        *RecoveryControls
	ReplayFromStep  int // 0 when unset
	TamperedState   string
}

// Scenario is the validated order-brief-recovery scenario document.
type Scenario struct {
	SchemaVersion string
	ScenarioID    string
	OrderID       string
	Cases         []CaseSpec
	Attribution   AttributionTables
}

// FindCase returns the case with the given id.
func (s *Scenario) FindCase(id string) (CaseSpec, error) {
	for _, scenarioCase := range s.Cases {
		if scenarioCase.CaseID == id {
			return scenarioCase, nil
		}
	}
	return CaseSpec{}, fmt.Errorf("%w: %s", ErrUnknownCase, id)
}

// controlsWire mirrors the scenario's scripted control object: exactly one
// key, crash_after or cancel_before.
type controlsWire struct {
	CrashAfter   *string `json:"crash_after"`
	CancelBefore *string `json:"cancel_before"`
}

// caseWire mirrors one scenario case for strict decoding.
type caseWire struct {
	CaseID          string        `json:"case_id"`
	ExecutionMode   string        `json:"execution_mode"`
	WorkerFixture   string        `json:"worker_fixture"`
	CompletionOrder []string      `json:"completion_order"`
	Controls        *controlsWire `json:"controls"`
	ReplayFromStep  *int          `json:"replay_from_step"`
	TamperedState   *string       `json:"tampered_state"`
}

// scenarioWire mirrors the scenario projection for strict decoding.
type scenarioWire struct {
	SchemaVersion string `json:"schema_version"`
	ScenarioID    string `json:"scenario_id"`
	OrderID       string `json:"order_id"`
	Attribution   *struct {
		LatencyMS  map[string]int `json:"latency_ms"`
		PriceTable map[string]int `json:"price_table"`
	} `json:"attribution"`
	Cases []caseWire `json:"cases"`
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

// workerFixtureWire mirrors one workers.json entry for strict decoding.
type workerFixtureWire map[string]struct {
	Operation   string          `json:"operation"`
	Output      json.RawMessage `json:"output"`
	FailureCode *string         `json:"failure_code"`
}

// FindRepoRoot walks up from the working directory to the repository root.
func FindRepoRoot() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if info, err := os.Stat(filepath.Join(dir, "fixtures", "scenarios",
			"order-brief-recovery.yaml")); err == nil && !info.IsDir() {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", errors.New("m4: repository root not found from " + dir)
		}
		dir = parent
	}
}

// DefaultScenarioPath is the checked-in JSON projection of the M4 scenario.
func DefaultScenarioPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections",
		"order-brief-recovery", "scenario.json")
}

// DefaultWorkersPath is the checked-in JSON projection of the M4 workers.
func DefaultWorkersPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections",
		"order-brief-recovery", "workers.json")
}

// LoadScenario strict-decodes and validates the scenario projection against
// the workers projection: header, six unique cases with bounded modes, a
// completion permutation each, in-bounds fixture references, at most one
// scripted control per case with a feasible target, attribution tables, and
// a feasible completion schedule per mode.
func LoadScenario(scenarioPath, workersPath string) (*Scenario, error) {
	fixtures, err := LoadWorkerFixtures(workersPath)
	if err != nil {
		return nil, err
	}
	raw, err := os.ReadFile(scenarioPath)
	if err != nil {
		return nil, fmt.Errorf("m4: read scenario: %w", err)
	}
	var wire scenarioWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return nil, fmt.Errorf("m4: invalid scenario projection: %w", err)
	}
	if wire.SchemaVersion != "1.0" || wire.ScenarioID != "order-brief-recovery" {
		return nil, fmt.Errorf("m4: unsupported scenario: schema_version %q, scenario_id %q",
			wire.SchemaVersion, wire.ScenarioID)
	}
	if !orderIDPattern.MatchString(wire.OrderID) {
		return nil, fmt.Errorf("m4: invalid order_id %q", wire.OrderID)
	}
	if len(wire.Cases) != 6 {
		return nil, fmt.Errorf("m4: scenario must carry six cases, got %d", len(wire.Cases))
	}
	tables, err := parseTables(wire.Attribution)
	if err != nil {
		return nil, err
	}
	cases := make([]CaseSpec, 0, len(wire.Cases))
	seen := map[string]bool{}
	for _, wireCase := range wire.Cases {
		spec, err := parseCase(wireCase, fixtures)
		if err != nil {
			return nil, err
		}
		if seen[spec.CaseID] {
			return nil, fmt.Errorf("m4: duplicate case id %q", spec.CaseID)
		}
		seen[spec.CaseID] = true
		cases = append(cases, spec)
	}
	return &Scenario{SchemaVersion: wire.SchemaVersion, ScenarioID: wire.ScenarioID,
		OrderID: wire.OrderID, Cases: cases, Attribution: tables}, nil
}

func parseCase(wireCase caseWire, fixtures map[string]WorkerInstructions) (CaseSpec, error) {
	if wireCase.CaseID == "" {
		return CaseSpec{}, errors.New("m4: case id is required")
	}
	if wireCase.ExecutionMode != ModeSequential && wireCase.ExecutionMode != ModeParallel {
		return CaseSpec{}, fmt.Errorf("m4: case %q execution_mode must be sequential or parallel", wireCase.CaseID)
	}
	if !strings.HasPrefix(wireCase.WorkerFixture, "fixtures/workers/order-brief/") {
		return CaseSpec{}, fmt.Errorf("m4: case %q worker fixture escapes root: %s",
			wireCase.CaseID, wireCase.WorkerFixture)
	}
	if _, ok := fixtures[wireCase.WorkerFixture]; !ok {
		return CaseSpec{}, fmt.Errorf("m4: case %q references unknown worker fixture %s",
			wireCase.CaseID, wireCase.WorkerFixture)
	}
	if len(wireCase.CompletionOrder) != len(contracts.CanonicalWorkerIDs) {
		return CaseSpec{}, fmt.Errorf("m4: case %q completion order must be a permutation", wireCase.CaseID)
	}
	seen := map[string]bool{}
	for _, id := range wireCase.CompletionOrder {
		if !isCanonicalWorker(id) || seen[id] {
			return CaseSpec{}, fmt.Errorf("m4: case %q completion order must be a permutation", wireCase.CaseID)
		}
		seen[id] = true
	}
	if !completionScheduleFeasible(wireCase.ExecutionMode, wireCase.CompletionOrder) {
		return CaseSpec{}, fmt.Errorf("m4: case %q has an infeasible completion schedule", wireCase.CaseID)
	}
	// At most one optional scripted extension per case.
	optionals := 0
	for _, set := range []bool{wireCase.Controls != nil, wireCase.ReplayFromStep != nil,
		wireCase.TamperedState != nil} {
		if set {
			optionals++
		}
	}
	if optionals > 1 {
		return CaseSpec{}, fmt.Errorf("m4: case %q combines scripted extensions", wireCase.CaseID)
	}
	spec := CaseSpec{CaseID: wireCase.CaseID, ExecutionMode: wireCase.ExecutionMode,
		WorkerFixture:   wireCase.WorkerFixture,
		CompletionOrder: append([]string(nil), wireCase.CompletionOrder...)}
	if wireCase.Controls != nil {
		controls, err := parseControls(*wireCase.Controls, wireCase.CompletionOrder)
		if err != nil {
			return CaseSpec{}, fmt.Errorf("m4: case %q: %w", wireCase.CaseID, err)
		}
		spec.Controls = &controls
	}
	if wireCase.ReplayFromStep != nil {
		if *wireCase.ReplayFromStep < 1 || *wireCase.ReplayFromStep > 3 {
			return CaseSpec{}, fmt.Errorf("m4: case %q replay_from_step out of bounds", wireCase.CaseID)
		}
		spec.ReplayFromStep = *wireCase.ReplayFromStep
	}
	if wireCase.TamperedState != nil {
		if *wireCase.TamperedState != "flip_payment_outcome" {
			return CaseSpec{}, fmt.Errorf("m4: case %q has an invalid tampered_state", wireCase.CaseID)
		}
		spec.TamperedState = *wireCase.TamperedState
	}
	return spec, nil
}

// parseControls mirrors the TS control validation: exactly one control, a
// canonical target, a crash target with a feasible prefix (at least two
// workers, no earlier-completing peer after the target), and a cancel
// target that is the final canonical worker.
func parseControls(wire controlsWire, completionOrder []string) (RecoveryControls, error) {
	set := 0
	for _, value := range []*string{wire.CrashAfter, wire.CancelBefore} {
		if value != nil {
			set++
		}
	}
	if set != 1 {
		return RecoveryControls{}, errors.New("controls must name exactly one target")
	}
	position := func(id string) int {
		for index, candidate := range completionOrder {
			if candidate == id {
				return index
			}
		}
		return -1
	}
	switch {
	case wire.CrashAfter != nil:
		target := *wire.CrashAfter
		if !isCanonicalWorker(target) {
			return RecoveryControls{}, fmt.Errorf("invalid crash target %q", target)
		}
		prefix := contracts.CanonicalWorkerIDs[:workerIndex(target)+1]
		if len(prefix) < 2 {
			return RecoveryControls{}, fmt.Errorf("infeasible crash target %q", target)
		}
		for _, id := range prefix {
			if id != target && position(id) > position(target) {
				return RecoveryControls{}, fmt.Errorf("infeasible crash target %q", target)
			}
		}
		return RecoveryControls{CrashAfter: target}, nil
	default:
		target := *wire.CancelBefore
		if target != contracts.CanonicalWorkerIDs[len(contracts.CanonicalWorkerIDs)-1] {
			return RecoveryControls{}, fmt.Errorf("infeasible cancel target %q", target)
		}
		return RecoveryControls{CancelBefore: target}, nil
	}
}

// completionScheduleFeasible mirrors the TS loader: simulate bounded
// admission over the canonical queue; every scripted completion must name
// an active worker.
func completionScheduleFeasible(mode string, completionOrder []string) bool {
	limit := 1
	if mode == ModeParallel {
		limit = 2
	}
	pending := append([]string(nil), contracts.CanonicalWorkerIDs...)
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
	return workerIndex(id) >= 0
}

func workerIndex(id string) int {
	for index, canonical := range contracts.CanonicalWorkerIDs {
		if id == canonical {
			return index
		}
	}
	return -1
}

func parseTables(raw *struct {
	LatencyMS  map[string]int `json:"latency_ms"`
	PriceTable map[string]int `json:"price_table"`
}) (AttributionTables, error) {
	if raw == nil {
		return AttributionTables{}, errors.New("m4: scenario attribution tables are required")
	}
	if len(raw.LatencyMS) == 0 {
		return AttributionTables{}, errors.New("m4: invalid attribution latency table: must be nonempty")
	}
	if len(raw.PriceTable) == 0 {
		return AttributionTables{}, errors.New("m4: invalid attribution price table: must be nonempty")
	}
	for step, latency := range raw.LatencyMS {
		if step == "" || latency < 0 {
			return AttributionTables{}, fmt.Errorf("m4: invalid attribution latency for %q", step)
		}
	}
	for kind, price := range raw.PriceTable {
		if !stepPriceKinds[kind] || price < 0 {
			return AttributionTables{}, fmt.Errorf("m4: invalid attribution price kind %q", kind)
		}
	}
	if read, ok := raw.PriceTable["read"]; ok && read != 0 {
		return AttributionTables{}, errors.New("m4: attribution reads must price zero")
	}
	return AttributionTables{LatencyMS: raw.LatencyMS, PriceTable: raw.PriceTable}, nil
}

// LoadWorkerFixtures strict-decodes and validates the workers projection:
// every entry covers exactly the canonical workers with well-formed
// instructions (return+output, or raise+WORKER_EXECUTION_FAILED).
func LoadWorkerFixtures(path string) (map[string]WorkerInstructions, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("m4: read workers projection: %w", err)
	}
	var wire map[string]workerFixtureWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return nil, fmt.Errorf("m4: invalid workers projection: %w", err)
	}
	fixtures := make(map[string]WorkerInstructions, len(wire))
	for relpath, entry := range wire {
		if !strings.HasPrefix(relpath, "fixtures/workers/order-brief/") {
			return nil, fmt.Errorf("m4: worker fixture escapes root: %s", relpath)
		}
		instructions, err := parseInstructions(entry)
		if err != nil {
			return nil, fmt.Errorf("m4: worker fixture %s: %w", relpath, err)
		}
		fixtures[relpath] = instructions
	}
	return fixtures, nil
}

func parseInstructions(entry workerFixtureWire) (WorkerInstructions, error) {
	if len(entry) != len(contracts.CanonicalWorkerIDs) {
		return nil, fmt.Errorf("worker fixture must script exactly the canonical workers")
	}
	instructions := WorkerInstructions{}
	for _, id := range contracts.CanonicalWorkerIDs {
		instruction, ok := entry[id]
		if !ok {
			return nil, fmt.Errorf("worker %s missing from fixture", id)
		}
		switch {
		case instruction.Operation == "return" && instruction.Output != nil && instruction.FailureCode == nil:
			instructions[id] = WorkerInstruction{Operation: "return", Output: instruction.Output}
		case instruction.Operation == "raise" && instruction.Output == nil &&
			instruction.FailureCode != nil && *instruction.FailureCode == contracts.FailureWorkerExecutionFailed:
			instructions[id] = WorkerInstruction{Operation: "raise",
				FailureCode: *instruction.FailureCode}
		default:
			return nil, fmt.Errorf("worker %s has an invalid operation", id)
		}
	}
	return instructions, nil
}
