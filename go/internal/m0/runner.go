package m0

import (
	"crypto/rand"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// SpecialistInvocation is one specialist dispatch.
type SpecialistInvocation struct {
	Route   string
	Request string
}

// SpecialistDispatcher receives specialist invocations.
type SpecialistDispatcher interface {
	Dispatch(invocation SpecialistInvocation) error
}

// RecordingSpecialistDispatcher records invocations in order (the scripted
// specialists are no-ops, exactly like the TS/Python recorder).
type RecordingSpecialistDispatcher struct {
	invocations []SpecialistInvocation
}

// NewRecordingSpecialistDispatcher returns an empty recorder.
func NewRecordingSpecialistDispatcher() *RecordingSpecialistDispatcher {
	return &RecordingSpecialistDispatcher{}
}

// Dispatch records the invocation.
func (d *RecordingSpecialistDispatcher) Dispatch(invocation SpecialistInvocation) error {
	d.invocations = append(d.invocations, invocation)
	return nil
}

// Invocations returns a copy of the recorded invocations.
func (d *RecordingSpecialistDispatcher) Invocations() []SpecialistInvocation {
	return append([]SpecialistInvocation(nil), d.invocations...)
}

// RunOptions configures one support-triage run; the zero-value dependencies
// select the checked-in scenario projection, the scripted fake model, and a
// recording specialist dispatcher.
type RunOptions struct {
	Mode       string
	CaseID     string
	TracePath  string
	Scenario   *Scenario
	Provider   DecisionProvider
	Dispatcher SpecialistDispatcher
	RunID      string
	RepoRoot   string
}

// RunReport carries the result, the full trace, and the recorder used.
type RunReport struct {
	Result     contracts.RunResult
	Events     []contracts.Event
	Dispatcher SpecialistDispatcher
}

// stepRecord is one attributed step with its attempt count.
type stepRecord struct {
	name     string
	attempts int
}

// RunCase executes one support-triage run: envelope lifecycle, routing,
// specialist dispatch, attribution, and the flushed trace. Tooling failures
// return an error and leave no trace; domain failures produce a FAILED
// result with the INVALID_ROUTE_DECISION code.
func RunCase(options RunOptions) (RunReport, error) {
	if options.Mode != ModeDeterministic && options.Mode != ModeModel {
		return RunReport{}, fmt.Errorf("m0: --mode must be deterministic or model, got %q", options.Mode)
	}
	scenario := options.Scenario
	if scenario == nil {
		root := options.RepoRoot
		if root == "" {
			discovered, err := FindRepoRoot()
			if err != nil {
				return RunReport{}, err
			}
			root = discovered
		}
		loaded, err := LoadScenario(DefaultScenarioPath(root))
		if err != nil {
			return RunReport{}, err
		}
		scenario = loaded
	}
	scenarioCase, err := scenario.FindCase(options.CaseID)
	if err != nil {
		return RunReport{}, err
	}
	runID := options.RunID
	if runID == "" {
		runID = newUUID()
	}
	sink := NewEventSink(runID)
	dispatcher := options.Dispatcher
	if dispatcher == nil {
		dispatcher = NewRecordingSpecialistDispatcher()
	}
	emit := func(eventType contracts.EventType, data map[string]any) error {
		_, err := sink.Emit(eventType, data)
		return err
	}
	if err := emit(contracts.EventRunCreated, map[string]any{
		"scenario_id": scenario.ScenarioID, "case_id": scenarioCase.ID, "mode": options.Mode}); err != nil {
		return RunReport{}, err
	}
	if err := emit(contracts.EventRunStarted, map[string]any{
		"case_id": scenarioCase.ID, "mode": options.Mode}); err != nil {
		return RunReport{}, err
	}
	if err := emit(contracts.EventStepStarted, map[string]any{"step": "classify"}); err != nil {
		return RunReport{}, err
	}
	rawDecision, err := classify(options, scenarioCase, sink)
	if err != nil {
		return RunReport{}, err
	}
	return finishRun(options, scenario, scenarioCase, sink, dispatcher, runID, rawDecision)
}

// classify produces the raw decision payload: the deterministic keyword
// route in direct mode, the scripted fake model (with model.* events) in
// model mode.
func classify(options RunOptions, scenarioCase Case, sink *EventSink) (json.RawMessage, error) {
	if options.Mode == ModeDeterministic {
		decision := ClassifyDeterministically(scenarioCase.Request)
		raw, err := json.Marshal(map[string]any{
			"route": decision.Route, "confidence": decision.Confidence})
		if err != nil {
			return nil, err
		}
		return raw, nil
	}
	if _, err := sink.Emit(contracts.EventModelRequested, map[string]any{
		"case_id": scenarioCase.ID}); err != nil {
		return nil, err
	}
	provider := options.Provider
	if provider == nil {
		provider = NewScriptedDecisionProvider()
	}
	rawDecision, err := provider.Classify(scenarioCase.ID, scenarioCase.Request)
	if err != nil {
		return nil, err
	}
	var decisionPayload any
	if err := json.Unmarshal(rawDecision, &decisionPayload); err != nil {
		return nil, fmt.Errorf("m0: scripted decision for %s is not JSON: %w", scenarioCase.ID, err)
	}
	if _, err := sink.Emit(contracts.EventModelCompleted, map[string]any{
		"case_id": scenarioCase.ID, "decision": decisionPayload}); err != nil {
		return nil, err
	}
	return rawDecision, nil
}

// finishRun validates the decision, dispatches or fails closed, assembles
// the attribution, validates the result, and flushes the trace.
func finishRun(options RunOptions, scenario *Scenario, scenarioCase Case,
	sink *EventSink, dispatcher SpecialistDispatcher, runID string, rawDecision json.RawMessage) (RunReport, error) {
	decision, rejectedRoute, routeErr := ValidateRouteDecision(rawDecision)
	emit := func(eventType contracts.EventType, data map[string]any) error {
		_, err := sink.Emit(eventType, data)
		return err
	}
	records := []stepRecord{{name: "classify", attempts: 1}}
	if routeErr != nil {
		rejection := map[string]any{"route": any(nil), "failure_code": contracts.FailureInvalidRouteDecision}
		if rejectedRoute != nil {
			rejection["route"] = *rejectedRoute
		}
		if err := emit(contracts.EventRouteRejected, rejection); err != nil {
			return RunReport{}, err
		}
		if err := emit(contracts.EventStepFailed, map[string]any{
			"step": "classify", "failure_code": contracts.FailureInvalidRouteDecision}); err != nil {
			return RunReport{}, err
		}
		if err := emit(contracts.EventRunFailed, map[string]any{
			"status": "FAILED", "failure_code": contracts.FailureInvalidRouteDecision}); err != nil {
			return RunReport{}, err
		}
		result, err := buildResult(runID, scenarioCase, options, "FAILED", nil, false, records, scenario.Attribution)
		if err != nil {
			return RunReport{}, err
		}
		if err := WriteJSONL(options.TracePath, sink.Events()); err != nil {
			return RunReport{}, err
		}
		return RunReport{Result: *result, Events: sink.Events(), Dispatcher: dispatcher}, nil
	}
	specialistStep := "specialist." + decision.Route
	if err := emit(contracts.EventRouteSelected, map[string]any{
		"route": decision.Route, "confidence": decision.Confidence}); err != nil {
		return RunReport{}, err
	}
	if err := emit(contracts.EventStepCompleted, map[string]any{
		"step": "classify", "route": decision.Route}); err != nil {
		return RunReport{}, err
	}
	if err := emit(contracts.EventStepStarted, map[string]any{
		"step": specialistStep, "route": decision.Route}); err != nil {
		return RunReport{}, err
	}
	if err := dispatcher.Dispatch(SpecialistInvocation{Route: decision.Route, Request: scenarioCase.Request}); err != nil {
		return RunReport{}, err
	}
	if err := emit(contracts.EventStepCompleted, map[string]any{
		"step": specialistStep, "route": decision.Route}); err != nil {
		return RunReport{}, err
	}
	if err := emit(contracts.EventRunCompleted, map[string]any{
		"status": "SUCCEEDED", "route": decision.Route}); err != nil {
		return RunReport{}, err
	}
	records = append(records, stepRecord{name: specialistStep, attempts: 1})
	result, err := buildResult(runID, scenarioCase, options, "SUCCEEDED", &decision.Route, true, records, scenario.Attribution)
	if err != nil {
		return RunReport{}, err
	}
	if err := WriteJSONL(options.TracePath, sink.Events()); err != nil {
		return RunReport{}, err
	}
	return RunReport{Result: *result, Events: sink.Events(), Dispatcher: dispatcher}, nil
}

// buildResult assembles and structurally validates the run result against
// the closed run-result schema shape (M0: run-result.schema.json).
func buildResult(runID string, scenarioCase Case, options RunOptions, status string,
	selectedRoute *string, specialistInvoked bool, records []stepRecord,
	tables AttributionTables) (*contracts.RunResult, error) {
	attribution, err := buildAttribution(records, tables, options.Mode)
	if err != nil {
		return nil, err
	}
	var failureCode *string
	if status == "FAILED" {
		failureCode = strPtr(contracts.FailureInvalidRouteDecision)
	}
	result := &contracts.RunResult{
		SchemaVersion:     contracts.EnvelopeVersion,
		RunID:             runID,
		ScenarioID:        "support-triage", // LoadScenario pins the canonical id
		CaseID:            scenarioCase.ID,
		Mode:              options.Mode,
		Status:            status,
		SelectedRoute:     selectedRoute,
		SpecialistInvoked: specialistInvoked,
		FailureCode:       failureCode,
		TracePath:         options.TracePath,
		Attribution:       attribution,
	}
	if err := validateResult(*result); err != nil {
		return nil, err
	}
	return result, nil
}

func strPtr(value string) *string { return &value }

// buildAttribution assembles the attribution block from the fixture tables
// (M6 Ruling 5: classify's price kind is mode-dependent; latency is
// table*attempts; totals sum every record; at least one record required).
func buildAttribution(records []stepRecord, tables AttributionTables, mode string) (contracts.Attribution, error) {
	steps := make([]contracts.StepAttribution, 0, len(records))
	totals := contracts.Totals{}
	for _, record := range records {
		if record.attempts < 1 {
			return contracts.Attribution{}, fmt.Errorf("m0: invalid attribution attempts for %s", record.name)
		}
		latency, ok := tables.LatencyMS[record.name]
		if !ok {
			return contracts.Attribution{}, fmt.Errorf("m0: unknown attribution step: %s", record.name)
		}
		kind, err := stepKind(record.name, mode)
		if err != nil {
			return contracts.Attribution{}, err
		}
		price, ok := tables.PriceTable[kind]
		if !ok {
			return contracts.Attribution{}, fmt.Errorf("m0: unknown attribution price kind: %s", kind)
		}
		step := contracts.StepAttribution{
			StepName:  record.name,
			LatencyMS: latency * record.attempts,
			CostCents: price * record.attempts,
			Attempts:  record.attempts,
		}
		steps = append(steps, step)
		totals.LatencyMS += step.LatencyMS
		totals.CostCents += step.CostCents
		totals.Attempts += step.Attempts
	}
	if len(steps) == 0 {
		return contracts.Attribution{}, fmt.Errorf("m0: attribution requires at least one executed step")
	}
	return contracts.Attribution{Steps: steps, Totals: totals}, nil
}

// stepKind maps step names to price kinds; classify's kind is mode-dependent.
func stepKind(stepName string, mode string) (string, error) {
	if stepName == "classify" {
		if mode == ModeModel {
			return "model_decision", nil
		}
		return "route", nil
	}
	if strings.HasPrefix(stepName, "specialist.") {
		return "read", nil
	}
	return "", fmt.Errorf("m0: unknown attribution step: %s", stepName)
}

// validateResult mirrors the closed M0 result schema: required fields, enum
// values, the route/failure oneOfs, and the status conditionals.
func validateResult(result contracts.RunResult) error {
	switch {
	case result.SchemaVersion != contracts.EnvelopeVersion:
		return fmt.Errorf("m0: result schema_version must be %q", contracts.EnvelopeVersion)
	case result.RunID == "" || result.TracePath == "":
		return fmt.Errorf("m0: result run_id and trace_path must be nonempty")
	case result.ScenarioID != "support-triage" || result.CaseID == "":
		return fmt.Errorf("m0: result scenario/case identifiers are invalid")
	case result.Mode != ModeDeterministic && result.Mode != ModeModel:
		return fmt.Errorf("m0: result mode %q is outside the enum", result.Mode)
	case result.Status != "SUCCEEDED" && result.Status != "FAILED":
		return fmt.Errorf("m0: result status %q is outside the enum", result.Status)
	case result.SelectedRoute != nil && !isCanonicalRoute(*result.SelectedRoute):
		return fmt.Errorf("m0: result selected_route %q is outside the enum", *result.SelectedRoute)
	case result.FailureCode != nil && *result.FailureCode != contracts.FailureInvalidRouteDecision:
		return fmt.Errorf("m0: result failure_code %q is outside the enum", *result.FailureCode)
	}
	if err := validateAttributionBlock(result.Attribution); err != nil {
		return err
	}
	if result.Status == "SUCCEEDED" {
		if result.SelectedRoute == nil || !result.SpecialistInvoked || result.FailureCode != nil {
			return fmt.Errorf("m0: SUCCEEDED results must select a route, invoke the specialist, and carry no failure")
		}
		return nil
	}
	if result.SelectedRoute != nil || result.SpecialistInvoked ||
		result.FailureCode == nil || *result.FailureCode != contracts.FailureInvalidRouteDecision {
		return fmt.Errorf("m0: FAILED results must carry the invalid-route failure without dispatch")
	}
	return nil
}

func isCanonicalRoute(route string) bool {
	for _, canonical := range canonicalRoutes {
		if route == canonical {
			return true
		}
	}
	return false
}

func validateAttributionBlock(attribution contracts.Attribution) error {
	if len(attribution.Steps) == 0 {
		return fmt.Errorf("m0: attribution requires at least one step record")
	}
	if attribution.Totals.LatencyMS < 0 || attribution.Totals.CostCents < 0 || attribution.Totals.Attempts < 1 {
		return fmt.Errorf("m0: attribution totals are outside the schema bounds")
	}
	for _, step := range attribution.Steps {
		if step.StepName == "" || step.LatencyMS < 0 || step.CostCents < 0 || step.Attempts < 1 {
			return fmt.Errorf("m0: attribution record %q is outside the schema bounds", step.StepName)
		}
	}
	return nil
}

// newUUID generates a random RFC 4122 version-4 id (stdlib only).
func newUUID() string {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		panic(fmt.Sprintf("m0: uuid generation failed: %v", err))
	}
	bytes[6] = (bytes[6] & 0x0f) | 0x40
	bytes[8] = (bytes[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", bytes[0:4], bytes[4:6], bytes[6:8], bytes[8:10], bytes[10:16])
}
