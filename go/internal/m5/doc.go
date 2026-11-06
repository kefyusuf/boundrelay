// Package m5 is the Go runtime for the order-closure lesson: the typed,
// digest-protected run-state document with write-ahead step records and the
// effect submit-marker, the deterministic idempotency key and payload
// digest, the once-per-key effect ledger, the fixture-bound approval gate,
// the append-only audit writer, the bounded concurrent reads executor with
// the crash controls in the effect pipeline (crash_before_submit,
// crash_in_submit_window), fail-closed recovery (submit-marker adoption,
// one resubmit, the UNKNOWN terminal that is never flattened), the 1.0
// trace envelope, and the run result contract. It mirrors the
// TypeScript/Python semantics, not their code.
package m5

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
// lesson; the order-closure runtime reuses its workers unchanged).
const (
	ModeSequential = "sequential"
	ModeParallel   = "parallel"
)

// Effect statuses and the deterministic refund outcome the ledger records.
const (
	EffectCompleted  = "EFFECT_COMPLETED"
	EffectRejected   = "EFFECT_REJECTED"
	EffectUnprovable = "EFFECT_UNPROVABLE"

	RefundID          = "RFL-1001"
	RefundedAt        = "2026-11-02T00:00:00Z"
	EffectOperation   = "cancel-and-refund"
	RefundAmountCents = 4200
	RefundCurrency    = "EUR"
)

// Approval decisions and result approval_decision values.
const (
	DecisionGranted  = "granted"
	DecisionRejected = "rejected"
	DecisionNone     = "none"

	// FailureApprovalRejected is the M5 run-level failure code for a
	// rejected approval (order-closure-result.schema.json).
	FailureApprovalRejected = "APPROVAL_REJECTED"
)

// Sentinels: declared worker failures become WORKER_EXECUTION_FAILED
// outcomes; unknown cases are tooling errors.
var (
	// ErrWorkerExecution is the declared-failure sentinel workers raise;
	// it maps 1:1 to the WORKER_EXECUTION_FAILED failure code.
	ErrWorkerExecution = errors.New("m5: declared worker failure")
	// ErrUnknownCase marks tooling errors for unknown scenario cases.
	ErrUnknownCase = errors.New("m5: unknown scenario case")
	// ErrApprovalBinding is the approval-gate binding/not-granted error.
	ErrApprovalBinding = errors.New("m5: approval binding mismatch")
	// ErrApprovalNotGranted marks a required approval that was not granted.
	ErrApprovalNotGranted = errors.New("m5: approval not granted")
)

// WorkerOutcome aliases the shared M3 worker result shape.
type WorkerOutcome = contracts.WorkerOutcome

// orderIDPattern mirrors the ORD-#### scenario/result constraint.
var orderIDPattern = regexp.MustCompile(`^ORD-[0-9]{4}$`)

// digestPattern mirrors the 64-hex payload/state digest constraint.
var digestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

// refundIDPattern mirrors the RFL-#### refund id constraint.
var refundIDPattern = regexp.MustCompile(`^RFL-[0-9]{4}$`)

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

// ApprovalMetadata is the case's fixture-bound approval block: the decision
// and the approver the gate records verbatim.
type ApprovalMetadata struct {
	Decision string
	Approver string
}

// EffectControls are the scripted effect-pipeline controls: at most one
// crash control per case, and sink_unavailable only on its canonical case.
type EffectControls struct {
	CrashBeforeSubmit   bool
	CrashInSubmitWindow bool
	SinkUnavailable     bool
}

// CaseSpec is one order-closure case: mode, worker fixture reference, the
// deterministic completion order, the fixture approval, and the optional
// scripted effect controls or duplicate-key marker.
type CaseSpec struct {
	CaseID          string
	ExecutionMode   string
	WorkerFixture   string
	CompletionOrder []string
	Approval        ApprovalMetadata
	Controls        *EffectControls
	DuplicateKey    bool
}

// Scenario is the validated order-closure scenario document.
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

// canonicalControls mirrors the Python scenario parser's CANONICAL_CONTROLS:
// the exact control field set each case may carry (absent for the plain
// cases). Any other set fails closed.
var canonicalControls = map[string][]string{
	"approval-granted-effect-once": {},
	"approval-rejected-no-effect":  {},
	"retry-before-submit":          {"crash_before_submit"},
	"crash-submit-window-resolved": {"crash_in_submit_window"},
	"sink-unavailable-unknown":     {"crash_in_submit_window", "sink_unavailable"},
	"duplicate-key-suppressed":     {},
}

// controlsWire mirrors the scenario's optional controls object: boolean
// flags from the fixed control field set.
type controlsWire struct {
	CrashBeforeSubmit   *bool `json:"crash_before_submit"`
	CrashInSubmitWindow *bool `json:"crash_in_submit_window"`
	SinkUnavailable     *bool `json:"sink_unavailable"`
}

// approvalWire mirrors the scenario's required approval block.
type approvalWire struct {
	Decision string `json:"decision"`
	Approver string `json:"approver"`
}

// caseWire mirrors one scenario case for strict decoding.
type caseWire struct {
	CaseID          string        `json:"case_id"`
	ExecutionMode   string        `json:"execution_mode"`
	WorkerFixture   string        `json:"worker_fixture"`
	CompletionOrder []string      `json:"completion_order"`
	Approval        approvalWire  `json:"approval"`
	Controls        *controlsWire `json:"controls"`
	DuplicateKey    *bool         `json:"duplicate_key"`
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
			"order-closure.yaml")); err == nil && !info.IsDir() {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", errors.New("m5: repository root not found from " + dir)
		}
		dir = parent
	}
}

// DefaultScenarioPath is the checked-in JSON projection of the M5 scenario.
func DefaultScenarioPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections",
		"order-closure", "scenario.json")
}

// DefaultWorkersPath is the checked-in JSON projection of the M5 workers.
func DefaultWorkersPath(repoRoot string) string {
	return filepath.Join(repoRoot, "fixtures", "goprojections",
		"order-closure", "workers.json")
}

// LoadScenario strict-decodes and validates the scenario projection against
// the workers projection: header, six unique parallel cases with a feasible
// completion schedule, a bound fixture approval each, the canonical control
// set per case, at most one duplicate-key marker, in-bounds fixture
// references, and the attribution tables.
func LoadScenario(scenarioPath, workersPath string) (*Scenario, error) {
	fixtures, err := LoadWorkerFixtures(workersPath)
	if err != nil {
		return nil, err
	}
	raw, err := os.ReadFile(scenarioPath)
	if err != nil {
		return nil, fmt.Errorf("m5: read scenario: %w", err)
	}
	var wire scenarioWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return nil, fmt.Errorf("m5: invalid scenario projection: %w", err)
	}
	if wire.SchemaVersion != "1.0" || wire.ScenarioID != "order-closure" {
		return nil, fmt.Errorf("m5: unsupported scenario: schema_version %q, scenario_id %q",
			wire.SchemaVersion, wire.ScenarioID)
	}
	if !orderIDPattern.MatchString(wire.OrderID) {
		return nil, fmt.Errorf("m5: invalid order_id %q", wire.OrderID)
	}
	if len(wire.Cases) != 6 {
		return nil, fmt.Errorf("m5: scenario must carry six cases, got %d", len(wire.Cases))
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
			return nil, fmt.Errorf("m5: duplicate case id %q", spec.CaseID)
		}
		seen[spec.CaseID] = true
		cases = append(cases, spec)
	}
	return &Scenario{SchemaVersion: wire.SchemaVersion, ScenarioID: wire.ScenarioID,
		OrderID: wire.OrderID, Cases: cases, Attribution: tables}, nil
}

func parseCase(wireCase caseWire, fixtures map[string]WorkerInstructions) (CaseSpec, error) {
	if wireCase.CaseID == "" {
		return CaseSpec{}, errors.New("m5: case id is required")
	}
	id := wireCase.CaseID
	if wireCase.ExecutionMode != ModeSequential && wireCase.ExecutionMode != ModeParallel {
		return CaseSpec{}, fmt.Errorf("m5: case %q execution_mode must be sequential or parallel", id)
	}
	if !strings.HasPrefix(wireCase.WorkerFixture, "fixtures/workers/order-brief/") {
		return CaseSpec{}, fmt.Errorf("m5: case %q worker fixture escapes root: %s", id, wireCase.WorkerFixture)
	}
	if _, ok := fixtures[wireCase.WorkerFixture]; !ok {
		return CaseSpec{}, fmt.Errorf("m5: case %q references unknown worker fixture %s", id, wireCase.WorkerFixture)
	}
	if len(wireCase.CompletionOrder) != len(contracts.CanonicalWorkerIDs) {
		return CaseSpec{}, fmt.Errorf("m5: case %q completion order must be a permutation", id)
	}
	seen := map[string]bool{}
	for _, worker := range wireCase.CompletionOrder {
		if !isCanonicalWorker(worker) || seen[worker] {
			return CaseSpec{}, fmt.Errorf("m5: case %q completion order must be a permutation", id)
		}
		seen[worker] = true
	}
	if !completionScheduleFeasible(wireCase.ExecutionMode, wireCase.CompletionOrder) {
		return CaseSpec{}, fmt.Errorf("m5: case %q has an infeasible completion schedule", id)
	}
	approval, err := parseApproval(wireCase.Approval)
	if err != nil {
		return CaseSpec{}, fmt.Errorf("m5: case %q: %w", id, err)
	}
	spec := CaseSpec{CaseID: id, ExecutionMode: wireCase.ExecutionMode,
		WorkerFixture:   wireCase.WorkerFixture,
		CompletionOrder: append([]string(nil), wireCase.CompletionOrder...),
		Approval:        approval}
	controls, duplicateKey := 0, false
	if wireCase.Controls != nil {
		parsed, err := parseControls(*wireCase.Controls, id)
		if err != nil {
			return CaseSpec{}, fmt.Errorf("m5: case %q: %w", id, err)
		}
		spec.Controls = &parsed
		controls = 1
	}
	if wireCase.DuplicateKey != nil {
		duplicateKey = *wireCase.DuplicateKey
		if id != "duplicate-key-suppressed" {
			return CaseSpec{}, fmt.Errorf("m5: case %q has an invalid duplicate_key", id)
		}
	}
	if duplicateKey {
		spec.DuplicateKey = true
		controls++
	}
	if controls > 1 {
		return CaseSpec{}, fmt.Errorf("m5: case %q combines scripted extensions", id)
	}
	return spec, nil
}

// parseApproval mirrors the Python parse_approval: exactly the decision and
// approver fields, a closed decision enum, and a nonempty approver.
func parseApproval(wire approvalWire) (ApprovalMetadata, error) {
	if wire.Decision != DecisionGranted && wire.Decision != DecisionRejected {
		return ApprovalMetadata{}, fmt.Errorf("invalid approval decision %q", wire.Decision)
	}
	if wire.Approver == "" {
		return ApprovalMetadata{}, errors.New("invalid approver")
	}
	return ApprovalMetadata{Decision: wire.Decision, Approver: wire.Approver}, nil
}

// parseControls mirrors the Python parse_controls: every flag true, every
// field inside the closed control set, crash_before_submit exclusive,
// sink_unavailable bound to its canonical case and paired with the submit
// window crash, and the field set equal to the case's canonical set.
func parseControls(wire controlsWire, caseID string) (EffectControls, error) {
	flags := map[string]bool{}
	for name, value := range map[string]*bool{
		"crash_before_submit":    wire.CrashBeforeSubmit,
		"crash_in_submit_window": wire.CrashInSubmitWindow,
		"sink_unavailable":       wire.SinkUnavailable,
	} {
		if value == nil {
			continue
		}
		if !*value {
			return EffectControls{}, fmt.Errorf("invalid control value for %s", name)
		}
		flags[name] = true
	}
	if len(flags) == 0 {
		return EffectControls{}, errors.New("invalid controls: must be nonempty")
	}
	if flags["crash_before_submit"] && len(flags) > 1 {
		return EffectControls{}, errors.New("invalid control combination")
	}
	if flags["sink_unavailable"] && (!flags["crash_in_submit_window"] || caseID != "sink-unavailable-unknown") {
		return EffectControls{}, errors.New("invalid control combination")
	}
	canonical := map[string]bool{}
	for _, name := range canonicalControls[caseID] {
		canonical[name] = true
	}
	if len(canonical) != len(flags) {
		return EffectControls{}, fmt.Errorf("invalid controls for case %s", caseID)
	}
	for name := range flags {
		if !canonical[name] {
			return EffectControls{}, fmt.Errorf("invalid controls for case %s", caseID)
		}
	}
	return EffectControls{CrashBeforeSubmit: flags["crash_before_submit"],
		CrashInSubmitWindow: flags["crash_in_submit_window"],
		SinkUnavailable:     flags["sink_unavailable"]}, nil
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
		return AttributionTables{}, errors.New("m5: scenario attribution tables are required")
	}
	if len(raw.LatencyMS) == 0 {
		return AttributionTables{}, errors.New("m5: invalid attribution latency table: must be nonempty")
	}
	if len(raw.PriceTable) == 0 {
		return AttributionTables{}, errors.New("m5: invalid attribution price table: must be nonempty")
	}
	for step, latency := range raw.LatencyMS {
		if step == "" || latency < 0 {
			return AttributionTables{}, fmt.Errorf("m5: invalid attribution latency for %q", step)
		}
	}
	for kind, price := range raw.PriceTable {
		if !stepPriceKinds[kind] || price < 0 {
			return AttributionTables{}, fmt.Errorf("m5: invalid attribution price kind %q", kind)
		}
	}
	if read, ok := raw.PriceTable["read"]; ok && read != 0 {
		return AttributionTables{}, errors.New("m5: attribution reads must price zero")
	}
	return AttributionTables{LatencyMS: raw.LatencyMS, PriceTable: raw.PriceTable}, nil
}

// LoadWorkerFixtures strict-decodes and validates the workers projection:
// every entry covers exactly the canonical workers with well-formed
// instructions (return+output, or raise+WORKER_EXECUTION_FAILED).
func LoadWorkerFixtures(path string) (map[string]WorkerInstructions, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("m5: read workers projection: %w", err)
	}
	var wire map[string]workerFixtureWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return nil, fmt.Errorf("m5: invalid workers projection: %w", err)
	}
	fixtures := make(map[string]WorkerInstructions, len(wire))
	for relpath, entry := range wire {
		if !strings.HasPrefix(relpath, "fixtures/workers/order-brief/") {
			return nil, fmt.Errorf("m5: worker fixture escapes root: %s", relpath)
		}
		instructions, err := parseInstructions(entry)
		if err != nil {
			return nil, fmt.Errorf("m5: worker fixture %s: %w", relpath, err)
		}
		fixtures[relpath] = instructions
	}
	return fixtures, nil
}

func parseInstructions(entry workerFixtureWire) (WorkerInstructions, error) {
	if len(entry) != len(contracts.CanonicalWorkerIDs) {
		return nil, errors.New("worker fixture must script exactly the canonical workers")
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
