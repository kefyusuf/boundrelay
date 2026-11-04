package m3

import (
	"context"
	"crypto/rand"
	"fmt"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// RunOptions configures one order-brief run; zero-value dependencies select
// the checked-in projections, the scripted workers, and brief synthesis.
type RunOptions struct {
	CaseID      string
	TracePath   string
	Mode        string
	Scenario    *Scenario
	Fixtures    map[string]WorkerInstructions
	Provider    WorkerProvider
	Control     WorkerControl
	Synthesizer func(orderID string, outcomes [3]WorkerOutcome) (contracts.Brief, error)
	RunID       string
	RepoRoot    string
}

// RunReport carries the validated result and the full trace.
type RunReport struct {
	Result contracts.OrderBriefResult
	Events []contracts.Event
}

// stepRecord is one attribution entry (name + attempts).
type stepRecord struct {
	name     string
	attempts int
}

// RunCase executes one order-brief run: envelope lifecycle, bounded fan-out
// with scripted completion order, canonical fan-in, synthesis, attribution,
// result validation, and the trace flush (which happens even on tooling
// failures, mirroring the TS/Python finally block; a flush failure surfaces
// like the TS finally's exception).
func RunCase(ctx context.Context, options RunOptions) (report RunReport, err error) {
	scenario, fixtures, err := loadDependencies(options)
	if err != nil {
		return RunReport{}, err
	}
	spec, err := scenario.FindCase(options.CaseID)
	if err != nil {
		return RunReport{}, err
	}
	if options.Mode != "" && options.Mode != spec.ExecutionMode {
		return RunReport{}, fmt.Errorf("m3: mode %q is incompatible with case %q", options.Mode, spec.CaseID)
	}
	if options.TracePath == "" {
		return RunReport{}, fmt.Errorf("m3: trace path is required")
	}
	if (options.Provider == nil) != (options.Control == nil) {
		return RunReport{}, fmt.Errorf("m3: provider and control must be supplied together")
	}
	runID := options.RunID
	if runID == "" {
		runID = newM3UUID()
	}
	sink := NewEventSink(runID)
	defer func() {
		if flushErr := WriteJSONL(options.TracePath, sink.Events()); err == nil {
			err = flushErr
		}
	}()
	return runScenario(ctx, options, scenario, fixtures, spec, runID, sink)
}

func loadDependencies(options RunOptions) (*Scenario, map[string]WorkerInstructions, error) {
	if options.Scenario != nil && options.Fixtures != nil {
		return options.Scenario, options.Fixtures, nil
	}
	root := options.RepoRoot
	if root == "" {
		discovered, err := FindRepoRoot()
		if err != nil {
			return nil, nil, err
		}
		root = discovered
	}
	scenario, err := LoadScenario(DefaultScenarioPath(root), DefaultWorkersPath(root))
	if err != nil {
		return nil, nil, err
	}
	fixtures, err := LoadWorkerFixtures(DefaultWorkersPath(root))
	if err != nil {
		return nil, nil, err
	}
	return scenario, fixtures, nil
}

// runScenario mirrors the TS runner flow: context payloads, worker events
// from the executor observer, canonical fan-in, gated synthesis events,
// validated result, and the terminal payload.
func runScenario(ctx context.Context, options RunOptions, scenario *Scenario,
	fixtures map[string]WorkerInstructions, spec CaseSpec, runID string, sink *EventSink) (RunReport, error) {
	concurrencyLimit := 1
	if spec.ExecutionMode == ModeParallel {
		concurrencyLimit = 2
	}
	context := map[string]any{
		"scenario_id": scenario.ScenarioID, "case_id": spec.CaseID,
		"execution_mode": spec.ExecutionMode, "order_id": scenario.OrderID,
		"concurrency_limit": concurrencyLimit,
	}
	emit := func(eventType contracts.EventType, data map[string]any) error {
		_, err := sink.Emit(eventType, data)
		return err
	}
	if err := emit(contracts.EventRunCreated, context); err != nil {
		return RunReport{}, err
	}
	if err := emit(contracts.EventRunStarted, context); err != nil {
		return RunReport{}, err
	}
	provider := options.Provider
	control := options.Control
	if provider == nil {
		scripted := NewScriptedWorkers(spec, scenario.OrderID, fixtures[spec.WorkerFixture])
		provider, control = scripted, scripted
	}
	execution, err := ExecuteWorkers(ctx, ExecutorOptions{
		Mode: spec.ExecutionMode, Input: WorkerInput{OrderID: scenario.OrderID},
		Directory: DirectoryFromProvider(provider), Control: control,
		Observer: func(event WorkerLifecycle) {
			if event.Kind == LifecycleStarted {
				_ = emit(contracts.EventStepStarted, map[string]any{
					"step_name": "worker." + event.WorkerID,
					"worker_id": event.WorkerID, "order_id": event.Input.OrderID})
				return
			}
			outcome := event.Outcome
			terminal := contracts.EventStepCompleted
			if outcome.Status == "FAILED" {
				terminal = contracts.EventStepFailed
			}
			_ = emit(terminal, map[string]any{
				"step_name": "worker." + outcome.WorkerID, "outcome": outcome})
		}})
	if err != nil {
		return RunReport{}, err
	}
	outcomes, err := CanonicalizeOutcomes(execution.Outcomes, scenario.OrderID)
	if err != nil {
		return RunReport{}, err
	}
	return finishRun(options, scenario, spec, sink, emit, execution, outcomes, runID, concurrencyLimit)
}

// finishRun gates synthesis on successes, assembles the result, validates
// it structurally, and emits the synthesis and terminal events.
func finishRun(options RunOptions, scenario *Scenario, spec CaseSpec, sink *EventSink,
	emit func(contracts.EventType, map[string]any) error, execution ExecutionSummary,
	outcomes [3]WorkerOutcome, runID string, concurrencyLimit int) (RunReport, error) {
	successes := 0
	for _, outcome := range outcomes {
		if outcome.Status == "SUCCEEDED" {
			successes++
		}
	}
	var brief *contracts.Brief
	if successes > 0 {
		if err := emit(contracts.EventStepStarted, map[string]any{
			"step_name": "synthesize", "worker_outcomes": outcomes}); err != nil {
			return RunReport{}, err
		}
		synthesizer := options.Synthesizer
		if synthesizer == nil {
			synthesizer = SynthesizeBrief
		}
		assembled, err := synthesizer(scenario.OrderID, outcomes)
		if err != nil {
			return RunReport{}, err
		}
		brief = &assembled
	}
	status, failureCode := runStatus(successes)
	result := contracts.OrderBriefResult{
		SchemaVersion:    contracts.EnvelopeVersion,
		RunID:            runID,
		ScenarioID:       "order-brief",
		CaseID:           spec.CaseID,
		ExecutionMode:    spec.ExecutionMode,
		ConcurrencyLimit: concurrencyLimit,
		PeakConcurrency:  execution.PeakConcurrency,
		OrderID:          scenario.OrderID,
		Status:           status,
		WorkerOutcomes:   append([]WorkerOutcome(nil), outcomes[:]...),
		SynthesisInvoked: successes > 0,
		Brief:            brief,
		FailureCode:      failureCode,
		TracePath:        options.TracePath,
		Attribution:      buildM3Attribution(successes > 0, scenario.Attribution),
	}
	if err := validateM3Result(result); err != nil {
		return RunReport{}, err
	}
	if successes > 0 {
		if err := emit(contracts.EventStepCompleted, map[string]any{
			"step_name": "synthesize", "brief": brief}); err != nil {
			return RunReport{}, err
		}
	}
	terminal := contracts.EventRunCompleted
	if successes == 0 {
		terminal = contracts.EventRunFailed
	}
	if err := emit(terminal, map[string]any{
		"status": result.Status, "worker_outcomes": result.WorkerOutcomes,
		"synthesis_invoked": result.SynthesisInvoked, "brief": brief,
		"failure_code": result.FailureCode, "peak_concurrency": result.PeakConcurrency}); err != nil {
		return RunReport{}, err
	}
	return RunReport{Result: result, Events: sink.Events()}, nil
}

// runStatus maps the success count to the closed result status.
func runStatus(successes int) (string, *string) {
	switch {
	case successes == 3:
		return "SUCCEEDED", nil
	case successes > 0:
		return "PARTIAL", nil
	default:
		return "FAILED", strPtr(contracts.FailureAllWorkersFailed)
	}
}

// buildM3Attribution assembles the attribution block: worker.<id> records
// for every executed worker plus synthesize when invoked (read/synthesis
// kinds price zero; latency = table x attempts; totals sum).
func buildM3Attribution(synthesisInvoked bool, tables AttributionTables) contracts.Attribution {
	records := make([]stepRecord, 0, 4)
	for _, id := range contracts.CanonicalWorkerIDs {
		records = append(records, stepRecord{name: "worker." + id, attempts: 1})
	}
	if synthesisInvoked {
		records = append(records, stepRecord{name: "synthesize", attempts: 1})
	}
	steps := make([]contracts.StepAttribution, 0, len(records))
	totals := contracts.Totals{}
	for _, record := range records {
		latency := tables.LatencyMS[record.name]
		kind := "read"
		if record.name == "synthesize" {
			kind = "synthesis"
		}
		price := tables.PriceTable[kind]
		step := contracts.StepAttribution{StepName: record.name,
			LatencyMS: latency * record.attempts, CostCents: price * record.attempts,
			Attempts: record.attempts}
		steps = append(steps, step)
		totals.LatencyMS += step.LatencyMS
		totals.CostCents += step.CostCents
		totals.Attempts += step.Attempts
	}
	return contracts.Attribution{Steps: steps, Totals: totals}
}

// validateM3Result mirrors the closed order-brief result schema: required
// fields, enums, the canonical worker order, and the status conditionals.
func validateM3Result(result contracts.OrderBriefResult) error {
	switch {
	case result.SchemaVersion != contracts.EnvelopeVersion:
		return fmt.Errorf("m3: result schema_version must be %q", contracts.EnvelopeVersion)
	case result.RunID == "" || result.TracePath == "":
		return fmt.Errorf("m3: result run_id and trace_path must be nonempty")
	case result.ScenarioID != "order-brief" || result.CaseID == "":
		return fmt.Errorf("m3: result scenario/case identifiers are invalid")
	case result.ExecutionMode != ModeSequential && result.ExecutionMode != ModeParallel:
		return fmt.Errorf("m3: result execution_mode %q is outside the enum", result.ExecutionMode)
	case result.Status != "SUCCEEDED" && result.Status != "PARTIAL" && result.Status != "FAILED":
		return fmt.Errorf("m3: result status %q is outside the enum", result.Status)
	case !orderIDPattern.MatchString(result.OrderID):
		return fmt.Errorf("m3: result order_id %q is invalid", result.OrderID)
	}
	limit := 1
	if result.ExecutionMode == ModeParallel {
		limit = 2
	}
	if result.ConcurrencyLimit != limit || result.PeakConcurrency < 1 || result.PeakConcurrency > 2 {
		return fmt.Errorf("m3: result concurrency %d/%d violates the schema", result.ConcurrencyLimit, result.PeakConcurrency)
	}
	if len(result.WorkerOutcomes) != 3 {
		return fmt.Errorf("m3: result must carry exactly three worker outcomes")
	}
	successes := 0
	for i, outcome := range result.WorkerOutcomes {
		if outcome.WorkerID != contracts.CanonicalWorkerIDs[i] ||
			!validateWorkerOutcome(outcome, result.OrderID) {
			return fmt.Errorf("m3: worker outcome %d is invalid or out of canonical order", i)
		}
		if outcome.Status == "SUCCEEDED" {
			successes++
		}
	}
	if result.SynthesisInvoked != (successes > 0) {
		return fmt.Errorf("m3: synthesis_invoked must match the successes")
	}
	if err := validateBrief(result, successes); err != nil {
		return err
	}
	if successes == 0 && (result.FailureCode == nil ||
		*result.FailureCode != contracts.FailureAllWorkersFailed) {
		return fmt.Errorf("m3: FAILED results must carry ALL_WORKERS_FAILED")
	}
	if successes > 0 && result.FailureCode != nil {
		return fmt.Errorf("m3: successful/partial results carry no failure code")
	}
	return nil
}

func validateBrief(result contracts.OrderBriefResult, successes int) error {
	switch {
	case successes == 3:
		if result.Brief == nil || !result.Brief.Complete || len(result.Brief.Sections) != 3 ||
			len(result.Brief.MissingWorkers) != 0 {
			return fmt.Errorf("m3: SUCCEEDED results must carry a complete three-section brief")
		}
	case successes > 0:
		if result.Brief == nil || result.Brief.Complete ||
			len(result.Brief.Sections) != successes || len(result.Brief.MissingWorkers) != 3-successes {
			return fmt.Errorf("m3: PARTIAL results must carry an incomplete brief")
		}
	default:
		if result.Brief != nil {
			return fmt.Errorf("m3: FAILED results carry no brief")
		}
	}
	if result.Brief != nil {
		if result.Brief.OrderID != result.OrderID {
			return fmt.Errorf("m3: brief order_id must match the run")
		}
		// Sections follow the canonical order of the succeeded subset.
		position := 0
		for _, section := range result.Brief.Sections {
			found := -1
			for i := position; i < len(contracts.CanonicalWorkerIDs); i++ {
				if contracts.CanonicalWorkerIDs[i] == section.WorkerID {
					found = i
					break
				}
			}
			if found < 0 {
				return fmt.Errorf("m3: brief sections must follow the canonical order")
			}
			position = found + 1
		}
	}
	return nil
}

// newM3UUID generates a random RFC 4122 version-4 id (stdlib only).
func newM3UUID() string {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		panic(fmt.Sprintf("m3: uuid generation failed: %v", err))
	}
	bytes[6] = (bytes[6] & 0x0f) | 0x40
	bytes[8] = (bytes[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", bytes[0:4], bytes[4:6], bytes[6:8], bytes[8:10], bytes[10:16])
}
