package m2

import (
	"crypto/rand"
	"encoding/json"
	"fmt"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// RunOptions configures one support-handoff run; the zero-value dependencies
// select the checked-in scenario/fake-model/failures projections, the
// scripted route provider, the recording receiver directory, and a fresh
// random run id.
type RunOptions struct {
	Mode      string
	CaseID    string
	TracePath string
	Scenario  *Scenario
	Provider  RouteDecisionProvider
	Directory ReceiverDirectory
	RunID     string
	RepoRoot  string
}

// RunReport carries the result, the full trace, and the receiver directory
// used (so callers can assert dispatch claims).
type RunReport struct {
	Result    contracts.HandoffResult
	Events    []contracts.Event
	Directory ReceiverDirectory
}

// runState carries the routing/handoff state and dependencies for one run.
type runState struct {
	mode         string
	scenarioCase Case
	threshold    float64
	failure      *FailureFixture
	sink         *EventSink
	provider     RouteDecisionProvider
	directory    ReceiverDirectory
	tables       AttributionTables
	tracePath    string

	proposedRoute     *string
	selectedRoute     *string
	receiver          *string
	fallbackApplied   bool
	specialistInvoked bool
}

func (s *runState) emit(eventType contracts.EventType, data map[string]any) error {
	_, err := s.sink.Emit(eventType, data)
	return err
}

// RunCase executes one support-handoff run: envelope lifecycle, the code or
// model router with the fixed 0.80 confidence policy, the handoff envelope
// with receiver availability and context validation, attribution, and the
// flushed trace. Tooling failures return an error and leave no trace; domain
// failures produce a FAILED result with the mapped failure code.
func RunCase(options RunOptions) (RunReport, error) {
	if options.Mode != ModeCode && options.Mode != ModeModel {
		return RunReport{}, fmt.Errorf("m2: --mode must be code or model, got %q", options.Mode)
	}
	root := options.RepoRoot
	if root == "" {
		discovered, err := FindRepoRoot()
		if err != nil {
			return RunReport{}, err
		}
		root = discovered
	}
	scenario := options.Scenario
	if scenario == nil {
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
	if scenarioCase.RouterMode != options.Mode {
		return RunReport{}, fmt.Errorf("%w: requested mode %s does not match canonical case mode %s",
			ErrModeMismatch, options.Mode, scenarioCase.RouterMode)
	}
	// The scripted failure fixtures load before the run starts (the TS/Py
	// runners load them up front; a missing referenced fixture is tooling
	// drift and must fail closed).
	fixtures, err := LoadFailureFixtures(DefaultFailuresPath(root))
	if err != nil {
		return RunReport{}, err
	}
	var failure *FailureFixture
	if scenarioCase.FailureRef != "" {
		failure = fixtures[scenarioCase.FailureRef]
		if failure == nil {
			return RunReport{}, fmt.Errorf("m2: unknown failure_ref: %s", scenarioCase.FailureRef)
		}
	}
	runID := options.RunID
	if runID == "" {
		runID = newUUID()
	}
	sink := NewEventSink(runID)
	directory := options.Directory
	if directory == nil {
		directory = NewRecordingReceiverDirectory()
	}
	provider := options.Provider
	if provider == nil {
		decisions, err := LoadFakeModelDecisions(DefaultFakeModelPath(root))
		if err != nil {
			return RunReport{}, err
		}
		provider = NewScriptedRouteProvider(decisions)
	}
	state := &runState{
		mode: options.Mode, scenarioCase: scenarioCase, threshold: scenario.ConfidenceThreshold,
		failure: failure, sink: sink, provider: provider, directory: directory,
		tables: scenario.Attribution, tracePath: options.TracePath,
	}
	if err := state.emit(contracts.EventRunCreated, map[string]any{
		"scenario_id": scenario.ScenarioID, "case_id": scenarioCase.ID,
		"router_mode": options.Mode}); err != nil {
		return RunReport{}, err
	}
	if err := state.emit(contracts.EventRunStarted, map[string]any{
		"case_id": scenarioCase.ID, "router_mode": options.Mode}); err != nil {
		return RunReport{}, err
	}
	result, err := state.run()
	if err != nil {
		return RunReport{}, err
	}
	return RunReport{Result: *result, Events: sink.Events(), Directory: directory}, nil
}

// run drives the routing and handoff flow after the run envelope events.
func (s *runState) run() (*contracts.HandoffResult, error) {
	rawDecision, err := s.classify()
	if err != nil {
		return nil, err
	}
	decision, decisionErr := ValidateRouteDecision(rawDecision)
	if decisionErr != nil {
		if err := s.emit(contracts.EventRouteRejected, map[string]any{
			"router_mode": s.mode, "failure_code": contracts.FailureInvalidRouteDecision}); err != nil {
			return nil, err
		}
		return s.finishFailure(contracts.FailureInvalidRouteDecision)
	}
	selection := ApplyConfidencePolicy(decision, s.threshold)
	s.proposedRoute = &selection.ProposedRoute
	s.selectedRoute = &selection.SelectedRoute
	s.receiver = &selection.Receiver
	s.fallbackApplied = selection.FallbackApplied
	if err := s.emit(contracts.EventRouteSelected, map[string]any{
		"router_mode": s.mode, "proposed_route": selection.ProposedRoute,
		"selected_route": selection.SelectedRoute, "confidence": selection.Confidence,
		"fallback_applied": selection.FallbackApplied}); err != nil {
		return nil, err
	}
	return s.handoff(selection)
}

// classify produces the raw decision payload: the code router in code mode
// (no model events), the scripted provider between the model event pair in
// model mode. Provider errors are tooling errors: the scripted schedule is
// fixture drift, not a domain failure.
func (s *runState) classify() (json.RawMessage, error) {
	if s.mode == ModeCode {
		decision := ClassifyWithCode(s.scenarioCase.Request)
		raw, err := json.Marshal(map[string]any{
			"route": decision.Route, "confidence": decision.Confidence})
		if err != nil {
			return nil, err
		}
		return raw, nil
	}
	if err := s.emit(contracts.EventModelRequested, map[string]any{
		"case_id": s.scenarioCase.ID}); err != nil {
		return nil, err
	}
	rawDecision, err := s.provider.NextDecision(DecisionInput{
		CaseID: s.scenarioCase.ID, Request: s.scenarioCase.Request})
	if err != nil {
		return nil, err
	}
	if err := s.emit(contracts.EventModelCompleted, map[string]any{
		"case_id": s.scenarioCase.ID, "decision": observableDecision(rawDecision)}); err != nil {
		return nil, err
	}
	return rawDecision, nil
}

// handoff builds the sender-intent/receiver-input envelope, applies the
// scripted context-loss and availability faults, and dispatches the
// specialist receiver. Every rejection path records zero dispatches.
func (s *runState) handoff(selection RouteSelection) (*contracts.HandoffResult, error) {
	receiverInput := map[string]any{
		"ticket_id": s.scenarioCase.TicketID, "request_text": s.scenarioCase.Request}
	if s.failure.IsOmitFields() {
		for _, field := range s.failure.OmitReceiverInputFields {
			delete(receiverInput, field)
		}
	}
	envelope := HandoffEnvelope{
		HandoffID: newUUID(), Sender: Sender, Receiver: selection.Receiver,
		SenderIntent: selection, ReceiverInput: receiverInput,
	}
	if err := s.emit(contracts.EventHandoffRequested, map[string]any{
		"handoff_id": envelope.HandoffID, "sender": envelope.Sender,
		"receiver": envelope.Receiver,
		"sender_intent": map[string]any{
			"route": selection.ProposedRoute, "confidence": selection.Confidence,
			"policy_outcome": selection.PolicyOutcome},
		"receiver_input": receiverInput}); err != nil {
		return nil, err
	}
	reject := func(failureCode string) (*contracts.HandoffResult, error) {
		if err := s.emit(contracts.EventHandoffRejected, map[string]any{
			"handoff_id": envelope.HandoffID, "receiver": envelope.Receiver,
			"failure_code": failureCode}); err != nil {
			return nil, err
		}
		return s.finishFailure(failureCode)
	}
	if err := validateHandoffEnvelope(envelope); err != nil {
		return reject(contracts.FailureHandoffContextInvalid)
	}
	unavailable := s.failure.MarksUnavailable(selection.Receiver)
	definition := s.directory.Resolve(selection.Receiver)
	if unavailable || definition == nil {
		return reject(contracts.FailureHandoffReceiverUnavailable)
	}
	if err := s.emit(contracts.EventHandoffAccepted, map[string]any{
		"handoff_id": envelope.HandoffID, "receiver": envelope.Receiver}); err != nil {
		return nil, err
	}
	input := ReceiverInput{
		TicketID:    receiverInput["ticket_id"].(string),
		RequestText: receiverInput["request_text"].(string)}
	if err := definition.Handle(input); err != nil {
		return nil, err
	}
	s.specialistInvoked = true
	return s.finishSuccess()
}

// finishFailure emits run.failed, validates the FAILED result, and flushes
// the trace. Failures never dispatch: specialist_invoked is false and no
// receiver record is attributed.
func (s *runState) finishFailure(failureCode string) (*contracts.HandoffResult, error) {
	fields := s.routeFields()
	if err := s.emit(contracts.EventRunFailed, map[string]any{
		"status": StatusFailed, "failure_code": failureCode,
		"proposed_route": fields["proposed_route"], "selected_route": fields["selected_route"],
		"receiver": fields["receiver"], "fallback_applied": s.fallbackApplied,
		"specialist_invoked": false}); err != nil {
		return nil, err
	}
	result, err := s.buildResult(StatusFailed, &failureCode)
	if err != nil {
		return nil, err
	}
	if err := WriteJSONL(s.tracePath, s.sink.Events()); err != nil {
		return nil, err
	}
	return result, nil
}

// finishSuccess emits run.completed, validates the SUCCEEDED result, and
// flushes the trace with the receiver dispatch attributed.
func (s *runState) finishSuccess() (*contracts.HandoffResult, error) {
	fields := s.routeFields()
	if err := s.emit(contracts.EventRunCompleted, map[string]any{
		"status":         StatusSucceeded,
		"proposed_route": fields["proposed_route"], "selected_route": fields["selected_route"],
		"receiver": fields["receiver"], "fallback_applied": s.fallbackApplied,
		"specialist_invoked": true}); err != nil {
		return nil, err
	}
	result, err := s.buildResult(StatusSucceeded, nil)
	if err != nil {
		return nil, err
	}
	if err := WriteJSONL(s.tracePath, s.sink.Events()); err != nil {
		return nil, err
	}
	return result, nil
}

// routeFields reads the nullable routing fields for the terminal payloads.
func (s *runState) routeFields() map[string]any {
	return map[string]any{
		"proposed_route": nullableString(s.proposedRoute),
		"selected_route": nullableString(s.selectedRoute),
		"receiver":       nullableString(s.receiver),
	}
}

func nullableString(value *string) any {
	if value == nil {
		return nil
	}
	return *value
}

// buildResult assembles and structurally validates the run result against
// the closed handoff-result schema shape: the classify record always, the
// receiver.<name> record only on success.
func (s *runState) buildResult(status string, failureCode *string) (*contracts.HandoffResult, error) {
	records := []stepRecord{{name: "classify", attempts: 1}}
	if status == StatusSucceeded {
		records = append(records, stepRecord{
			name: "receiver." + *s.receiver, attempts: 1})
	}
	attribution, err := buildAttribution(records, s.tables, s.mode)
	if err != nil {
		return nil, err
	}
	result := &contracts.HandoffResult{
		SchemaVersion:     contracts.EnvelopeVersion,
		RunID:             s.sink.runID,
		ScenarioID:        "support-handoff",
		CaseID:            s.scenarioCase.ID,
		RouterMode:        s.mode,
		Status:            status,
		ProposedRoute:     s.proposedRoute,
		SelectedRoute:     s.selectedRoute,
		Receiver:          s.receiver,
		FallbackApplied:   s.fallbackApplied,
		SpecialistInvoked: s.specialistInvoked,
		FailureCode:       failureCode,
		TracePath:         s.tracePath,
		Attribution:       attribution,
	}
	if err := validateResult(*result); err != nil {
		return nil, err
	}
	return result, nil
}

// validateResult mirrors the closed M2 result schema: required fields, enum
// values, the nullable route/receiver oneOfs, and the status/failure
// conditionals.
func validateResult(result contracts.HandoffResult) error {
	switch {
	case result.SchemaVersion != contracts.EnvelopeVersion:
		return fmt.Errorf("m2: result schema_version must be %q", contracts.EnvelopeVersion)
	case result.RunID == "" || result.TracePath == "":
		return fmt.Errorf("m2: result run_id and trace_path must be nonempty")
	case result.ScenarioID != "support-handoff" || result.CaseID == "":
		return fmt.Errorf("m2: result scenario/case identifiers are invalid")
	case result.RouterMode != ModeCode && result.RouterMode != ModeModel:
		return fmt.Errorf("m2: result router_mode %q is outside the enum", result.RouterMode)
	case result.Status != StatusSucceeded && result.Status != StatusFailed:
		return fmt.Errorf("m2: result status %q is outside the enum", result.Status)
	case result.ProposedRoute != nil && !isCanonicalRoute(*result.ProposedRoute):
		return fmt.Errorf("m2: result proposed_route %q is outside the enum", *result.ProposedRoute)
	case result.SelectedRoute != nil && !isCanonicalRoute(*result.SelectedRoute):
		return fmt.Errorf("m2: result selected_route %q is outside the enum", *result.SelectedRoute)
	case result.Receiver != nil && !isCanonicalReceiver(*result.Receiver):
		return fmt.Errorf("m2: result receiver %q is outside the enum", *result.Receiver)
	case result.FailureCode != nil && !contracts.IsM2FailureCode(*result.FailureCode):
		return fmt.Errorf("m2: result failure_code %q is outside the enum", *result.FailureCode)
	}
	if err := validateAttributionBlock(result.Attribution); err != nil {
		return err
	}
	switch {
	case result.Status == StatusSucceeded:
		if result.ProposedRoute == nil || result.SelectedRoute == nil || result.Receiver == nil ||
			!result.SpecialistInvoked || result.FailureCode != nil {
			return fmt.Errorf("m2: SUCCEEDED results must select a route and receiver, invoke the specialist, and carry no failure")
		}
	case result.FailureCode != nil && *result.FailureCode != contracts.FailureInvalidRouteDecision:
		// The handoff failures keep the full routing context but never
		// dispatch.
		if result.ProposedRoute == nil || result.SelectedRoute == nil || result.Receiver == nil ||
			result.SpecialistInvoked {
			return fmt.Errorf("m2: handoff failures must keep the routing context without a dispatch")
		}
	case result.FailureCode != nil:
		// INVALID_ROUTE_DECISION clears the routing context entirely.
		if result.ProposedRoute != nil || result.SelectedRoute != nil || result.Receiver != nil ||
			result.FallbackApplied || result.SpecialistInvoked {
			return fmt.Errorf("m2: INVALID_ROUTE_DECISION must clear the routing context without a dispatch")
		}
	default:
		return fmt.Errorf("m2: FAILED results must carry a failure code")
	}
	return nil
}

func validateAttributionBlock(attribution contracts.Attribution) error {
	if len(attribution.Steps) == 0 {
		return fmt.Errorf("m2: attribution requires at least one step record")
	}
	if attribution.Totals.LatencyMS < 0 || attribution.Totals.CostCents < 0 || attribution.Totals.Attempts < 1 {
		return fmt.Errorf("m2: attribution totals are outside the schema bounds")
	}
	for _, step := range attribution.Steps {
		if step.StepName == "" || step.LatencyMS < 0 || step.CostCents < 0 || step.Attempts < 1 {
			return fmt.Errorf("m2: attribution record %q is outside the schema bounds", step.StepName)
		}
	}
	return nil
}

// newUUID generates a random RFC 4122 version-4 id (stdlib only).
func newUUID() string {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		panic(fmt.Sprintf("m2: uuid generation failed: %v", err))
	}
	bytes[6] = (bytes[6] & 0x0f) | 0x40
	bytes[8] = (bytes[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", bytes[0:4], bytes[4:6], bytes[6:8], bytes[8:10], bytes[10:16])
}
