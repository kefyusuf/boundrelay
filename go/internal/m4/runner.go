package m4

import (
	"context"
	"errors"
	"fmt"
	"os"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// RunOptions configures one order-brief-recovery run; zero-value
// dependencies select the checked-in projections, the scripted workers, and
// brief synthesis. Resume and ReplayFrom are mutually exclusive; Resume
// continues the recorded run in StateDir, ReplayFrom seeds a NEW run from an
// immutable checkpoint snapshot.
type RunOptions struct {
	CaseID      string
	TracePath   string
	StateDir    string
	Resume      bool
	ReplayFrom  string
	Sink        *EventSink
	Observer    WorkerObserver
	Directory   WorkerDirectory
	Control     WorkerControl
	Synthesizer func(orderID string, outcomes [3]WorkerOutcome) (contracts.Brief, error)
	StateStore  *StateStore
	OnCrash     func()
	Scenario    *Scenario
	Fixtures    map[string]WorkerInstructions
	RepoRoot    string
}

// RunReport carries the validated result and the full trace of THIS phase.
type RunReport struct {
	Result contracts.OrderBriefRecoveryResult
	Events []contracts.Event
}

// runDependencies bundles the resolved collaborators shared by the fresh,
// resume, and replay lifecycles.
type runDependencies struct {
	ctx         context.Context
	options     RunOptions
	scenario    *Scenario
	spec        CaseSpec
	binding     StateBinding
	sink        *EventSink
	observer    WorkerObserver
	directory   WorkerDirectory
	control     WorkerControl
	synthesizer func(orderID string, outcomes [3]WorkerOutcome) (contracts.Brief, error)
	emit        func(contracts.EventType, map[string]any) error
}

// RunCase executes one lifecycle: envelope lifecycle, scripted bounded
// fan-out with the Ruling-3 controls, durable state integration, canonical
// fan-in, synthesis, attribution, result validation, and the trace flush
// (which happens even on tooling failures, mirroring the TS/Python finally
// block; the crash control flushes before its hard exit).
func RunCase(ctx context.Context, options RunOptions) (report RunReport, err error) {
	scenario, fixtures, err := loadDependencies(options)
	if err != nil {
		return RunReport{}, err
	}
	spec, err := scenario.FindCase(options.CaseID)
	if err != nil {
		return RunReport{}, err
	}
	if options.TracePath == "" || options.StateDir == "" {
		return RunReport{}, errors.New("m4: trace path and state dir are required")
	}
	if (options.Directory == nil) != (options.Control == nil) {
		return RunReport{}, errors.New("m4: directory and control must be supplied together")
	}
	if options.Resume && options.ReplayFrom != "" {
		return RunReport{}, errors.New("m4: resume and replay are mutually exclusive")
	}
	binding := StateBinding{CaseID: spec.CaseID, ExecutionMode: spec.ExecutionMode,
		RequestedOrderID: scenario.OrderID, ConcurrencyLimit: concurrencyLimitOf(spec.ExecutionMode)}

	// Fail-closed state discovery happens before any event is emitted.
	var loaded *LoadedRunState
	if options.Resume {
		state, err := loadRunState(options.StateDir, binding)
		if err != nil {
			return RunReport{}, err
		}
		loaded = &state
	}
	var replayDocument *RunStateDocument
	if options.ReplayFrom != "" {
		document, err := loadRunStateDocument(options.ReplayFrom, binding)
		if err != nil {
			return RunReport{}, err
		}
		replayDocument = &document
	}
	pending := []string{}
	switch {
	case loaded != nil:
		pending = derivePending(loaded.Document)
	case replayDocument != nil:
		pending = derivePending(*replayDocument)
	}

	// A fresh or replay run owns a new state document; replay seeds the
	// recorded snapshot outcomes so their evidence is never re-executed.
	var store *StateStore
	if loaded == nil {
		store = options.StateStore
		if store == nil {
			created, err := CreateStore(options.StateDir, binding,
				append([]string(nil), contracts.CanonicalWorkerIDs...))
			if err != nil {
				return RunReport{}, err
			}
			if replayDocument != nil {
				for _, outcome := range recordedOutcomes(*replayDocument) {
					if err := created.RecordStepTerminal(outcome.WorkerID, outcome); err != nil {
						return RunReport{}, err
					}
				}
			}
			store = created
		}
	}
	runID := ""
	if loaded != nil {
		runID = loaded.Document.RunID
	} else {
		runID = store.RunID()
	}
	sink := options.Sink
	if sink == nil {
		sink = NewEventSink(runID)
	}

	emit := func(eventType contracts.EventType, data map[string]any) error {
		_, err := sink.Emit(eventType, data)
		return err
	}
	// Resumed and replayed runs observe their re-executed steps through the
	// step observer and wrap it with the checkpoint emitter.
	observer := options.Observer
	if observer == nil && (options.Resume || options.ReplayFrom != "") {
		observer = stepObserver(sink)
	}
	deps := runDependencies{ctx: ctx, options: options, scenario: scenario, spec: spec,
		binding: binding, sink: sink, observer: observer,
		synthesizer: options.Synthesizer, emit: emit}
	if deps.synthesizer == nil {
		deps.synthesizer = SynthesizeBrief
	}

	defer func() {
		if flushErr := sink.Flush(options.TracePath); err == nil {
			err = flushErr
		}
	}()

	contextPayload := map[string]any{
		"scenario_id": ScenarioID, "case_id": spec.CaseID,
		"execution_mode": spec.ExecutionMode, "order_id": scenario.OrderID,
		"concurrency_limit": binding.ConcurrencyLimit, "state_dir": options.StateDir}
	if err := emit(contracts.EventRunCreated, contextPayload); err != nil {
		return RunReport{}, err
	}
	if err := emit(contracts.EventRunStarted, contextPayload); err != nil {
		return RunReport{}, err
	}

	// The resuming scripted provider follows the pending schedule; a single
	// pending worker executes sequentially even in a parallel case. Fresh
	// runs build their own full-spec provider inside freshRun.
	if options.Directory == nil {
		if loaded != nil || replayDocument != nil {
			scriptedMode := spec.ExecutionMode
			if len(pending) < 2 {
				scriptedMode = ModeSequential
			}
			scriptedCompletion := make([]string, 0, len(spec.CompletionOrder))
			for _, id := range spec.CompletionOrder {
				for _, candidate := range pending {
					if id == candidate {
						scriptedCompletion = append(scriptedCompletion, id)
						break
					}
				}
			}
			provider := NewScriptedWorkers(scriptedMode, scriptedCompletion,
				scenario.OrderID, fixtures[spec.WorkerFixture])
			deps.directory = DirectoryFromProvider(provider)
			deps.control = provider
		}
	} else {
		deps.directory, deps.control = options.Directory, options.Control
	}

	var result contracts.OrderBriefRecoveryResult
	switch {
	case loaded != nil:
		result, err = resumeRun(deps, *loaded)
	case replayDocument != nil:
		result, err = replayFrom(deps, *replayDocument, store)
	default:
		result, err = freshRun(deps, store, fixtures)
	}
	if err != nil {
		return RunReport{}, err
	}
	if result.Status != StatusCancelled {
		terminal := contracts.EventRunCompleted
		if result.Status == StatusFailed {
			terminal = contracts.EventRunFailed
		}
		if err := emit(terminal, map[string]any{
			"status": result.Status, "worker_outcomes": result.WorkerOutcomes,
			"synthesis_invoked": result.SynthesisInvoked, "brief": result.Brief,
			"failure_code": result.FailureCode, "peak_concurrency": result.PeakConcurrency}); err != nil {
			return RunReport{}, err
		}
	}
	return RunReport{Result: result, Events: sink.Events()}, nil
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

// freshRun executes the whole canonical queue with the case's scripted
// controls: the crash control hard-exits after flushing the trace prefix,
// the cancel control records the deterministic cancellation.
func freshRun(deps runDependencies, store *StateStore,
	fixtures map[string]WorkerInstructions) (contracts.OrderBriefRecoveryResult, error) {
	if deps.options.Directory == nil {
		provider := NewScriptedWorkers(deps.spec.ExecutionMode, deps.spec.CompletionOrder,
			deps.scenario.OrderID, fixtures[deps.spec.WorkerFixture])
		deps.directory = DirectoryFromProvider(provider)
		deps.control = provider
	}
	observer := observerFor(deps, store)
	onCrash := deps.options.OnCrash
	if onCrash == nil {
		onCrash = func() {
			_ = deps.sink.Flush(deps.options.TracePath)
			os.Exit(2)
		}
	}
	var controls *RecoveryControls
	if deps.spec.Controls != nil {
		controls = &RecoveryControls{CrashAfter: deps.spec.Controls.CrashAfter,
			CancelBefore: deps.spec.Controls.CancelBefore}
	}
	execution, err := ExecuteWorkers(deps.ctx, ExecutorOptions{
		Mode:      deps.spec.ExecutionMode,
		Input:     WorkerInput{OrderID: deps.scenario.OrderID},
		Directory: deps.directory, Control: deps.control, Observer: observer,
		Store: store, Controls: controls, OnCrash: onCrash})
	if err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	if execution.CancelledBefore != "" {
		if err := store.MarkCancelledFrom(execution.CancelledBefore); err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
		if err := deps.emit(contracts.EventRunCancelled, map[string]any{
			"case_id": deps.binding.CaseID, "execution_mode": deps.binding.ExecutionMode,
			"requested_order_id": deps.binding.RequestedOrderID,
			"concurrency_limit":  deps.binding.ConcurrencyLimit,
			"cancelled_before":   execution.CancelledBefore,
			"code":               "CANCELLED_BEFORE_STEP"}); err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
		if err := store.MarkTerminal(RunStateStatusCancelled, ""); err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
		recorded := recordedOutcomes(store.State())
		attribution, err := BuildAttribution(workerRecords(recorded, nil), deps.scenario.Attribution)
		if err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
		result := assemble(deps, store.RunID(), execution.PeakConcurrency,
			StepStatusCancelled, recorded, false, nil, nil, attribution)
		if err := validateRecoveryResult(result); err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
		return result, nil
	}
	outcomes, err := CanonicalizeOutcomes(execution.Outcomes, deps.scenario.OrderID)
	if err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	successes := 0
	for _, outcome := range outcomes {
		if outcome.Status == StatusSucceeded {
			successes++
		}
	}
	var brief *contracts.Brief
	if successes > 0 {
		if err := deps.emit(contracts.EventStepStarted, map[string]any{
			"step_name": "synthesize", "worker_outcomes": outcomes}); err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
		assembled, err := deps.synthesizer(deps.scenario.OrderID, outcomes)
		if err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
		brief = &assembled
		if err := deps.emit(contracts.EventStepCompleted, map[string]any{
			"step_name": "synthesize", "brief": brief}); err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
	}
	status := RunStatePartial
	failureCode := ""
	switch {
	case successes == 3:
		status = RunStateSucceeded
	case successes == 0:
		status = RunStateFailed
		failureCode = contracts.FailureAllWorkersFailed
	}
	if err := store.MarkTerminal(status, failureCode); err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	records := workerRecords(outcomes[:], nil)
	if successes > 0 {
		records = append(records, stepRecord{name: "synthesize", attempts: 1})
	}
	attribution, err := BuildAttribution(records, deps.scenario.Attribution)
	if err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	var failureCodePtr *string
	if failureCode != "" {
		failureCodePtr = strPtr(failureCode)
	}
	result := assemble(deps, store.RunID(), execution.PeakConcurrency, status,
		append([]WorkerOutcome(nil), outcomes[:]...), successes > 0, brief,
		failureCodePtr, attribution)
	if err := validateRecoveryResult(result); err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	return result, nil
}

// stepObserver emits the worker step events from the lifecycle.
func stepObserver(sink *EventSink) WorkerObserver {
	return func(event WorkerLifecycle) {
		if event.Kind == LifecycleStarted {
			_, _ = sink.Emit(contracts.EventStepStarted, map[string]any{
				"step_name": "worker." + event.WorkerID,
				"worker_id": event.WorkerID, "order_id": event.Input.OrderID})
			return
		}
		terminal := contracts.EventStepCompleted
		if event.Outcome.Status == StatusFailed {
			terminal = contracts.EventStepFailed
		}
		_, _ = sink.Emit(terminal, map[string]any{
			"step_name": "worker." + event.Outcome.WorkerID, "outcome": event.Outcome})
	}
}

// observerFor is the fresh-run observer: step events plus the checkpoint
// saved announcement after the store recorded the terminal.
func observerFor(deps runDependencies, store *StateStore) WorkerObserver {
	step := stepObserver(deps.sink)
	return func(event WorkerLifecycle) {
		step(event)
		if event.Kind == LifecycleTerminal {
			_ = emitCheckpointSaved(deps, store, event.Outcome.WorkerID)
		}
	}
}

// assemble builds the fresh-run result: no recovery provenance.
func assemble(deps runDependencies, runID string, peak int, status string,
	outcomes []WorkerOutcome, synthesisInvoked bool, brief *contracts.Brief,
	failureCode *string, attribution contracts.Attribution) contracts.OrderBriefRecoveryResult {
	if peak < 1 {
		peak = 1
	}
	return contracts.OrderBriefRecoveryResult{
		SchemaVersion:     contracts.EnvelopeVersion,
		RunID:             runID,
		ScenarioID:        ScenarioID,
		CaseID:            deps.binding.CaseID,
		ExecutionMode:     deps.binding.ExecutionMode,
		ConcurrencyLimit:  deps.binding.ConcurrencyLimit,
		PeakConcurrency:   peak,
		OrderID:           deps.binding.RequestedOrderID,
		Status:            status,
		WorkerOutcomes:    outcomes,
		SynthesisInvoked:  synthesisInvoked,
		Brief:             brief,
		FailureCode:       failureCode,
		TracePath:         deps.options.TracePath,
		Resumed:           false,
		RestoredCursor:    nil,
		RestoredWorkerIDs: []string{},
		StateDir:          deps.options.StateDir,
		RunStateStatus:    status,
		Attribution:       attribution,
	}
}

// validateRecoveryResult mirrors the closed order-brief-recovery result
// schema: required fields, enums, canonical worker order, the status
// conditionals, and the recovery provenance conditionals.
func validateRecoveryResult(result contracts.OrderBriefRecoveryResult) error {
	switch {
	case result.SchemaVersion != contracts.EnvelopeVersion:
		return fmt.Errorf("m4: result schema_version must be %q", contracts.EnvelopeVersion)
	case result.RunID == "" || result.TracePath == "" || result.StateDir == "":
		return fmt.Errorf("m4: result run_id, trace_path, and state_dir must be nonempty")
	case result.ScenarioID != ScenarioID || result.CaseID == "":
		return fmt.Errorf("m4: result scenario/case identifiers are invalid")
	case result.ExecutionMode != ModeSequential && result.ExecutionMode != ModeParallel:
		return fmt.Errorf("m4: result execution_mode %q is outside the enum", result.ExecutionMode)
	case result.Status != RunStateSucceeded && result.Status != RunStatePartial &&
		result.Status != RunStateFailed && result.Status != StepStatusCancelled:
		return fmt.Errorf("m4: result status %q is outside the enum", result.Status)
	case !orderIDPattern.MatchString(result.OrderID):
		return fmt.Errorf("m4: result order_id %q is invalid", result.OrderID)
	}
	limit := concurrencyLimitOf(result.ExecutionMode)
	peakLimit := 2
	if result.ExecutionMode == ModeSequential {
		peakLimit = 1
	}
	if result.ConcurrencyLimit != limit || result.PeakConcurrency < 1 ||
		result.PeakConcurrency > peakLimit {
		return fmt.Errorf("m4: result concurrency %d/%d violates the schema",
			result.ConcurrencyLimit, result.PeakConcurrency)
	}
	successes := 0
	if len(result.WorkerOutcomes) > 3 {
		return fmt.Errorf("m4: result carries too many worker outcomes")
	}
	for i, outcome := range result.WorkerOutcomes {
		if outcome.WorkerID != contracts.CanonicalWorkerIDs[i] ||
			!validateWorkerOutcome(outcome, result.OrderID) {
			return fmt.Errorf("m4: worker outcome %d is invalid or out of canonical order", i)
		}
		if outcome.Status == StatusSucceeded {
			successes++
		}
	}
	if err := validateStatusConditionals(result, successes); err != nil {
		return err
	}
	if err := validateRecoveryProvenance(result); err != nil {
		return err
	}
	if len(result.Attribution.Steps) == 0 {
		return fmt.Errorf("m4: result attribution requires at least one executed step")
	}
	return nil
}

// validateStatusConditionals pins the per-status shape: outcomes, synthesis,
// brief, failure code, and the run-state status.
func validateStatusConditionals(result contracts.OrderBriefRecoveryResult, successes int) error {
	switch result.Status {
	case RunStateSucceeded:
		if successes != 3 || !result.SynthesisInvoked || result.FailureCode != nil {
			return fmt.Errorf("m4: SUCCEEDED results need three successes and synthesis")
		}
		if result.Brief == nil || !result.Brief.Complete || len(result.Brief.Sections) != 3 ||
			len(result.Brief.MissingWorkers) != 0 || result.RunStateStatus != RunStateSucceeded {
			return fmt.Errorf("m4: SUCCEEDED results must carry a complete three-section brief")
		}
	case RunStatePartial:
		if successes < 1 || successes > 2 || !result.SynthesisInvoked || result.FailureCode != nil {
			return fmt.Errorf("m4: PARTIAL results need one or two successes and synthesis")
		}
		if result.Brief == nil || result.Brief.Complete ||
			len(result.Brief.Sections) != successes || len(result.Brief.MissingWorkers) != 3-successes ||
			result.RunStateStatus != RunStatePartial {
			return fmt.Errorf("m4: PARTIAL results must carry an incomplete brief")
		}
	case RunStateFailed:
		if successes != 0 || result.SynthesisInvoked || result.Brief != nil ||
			result.FailureCode == nil || *result.FailureCode != contracts.FailureAllWorkersFailed ||
			result.RunStateStatus != RunStateFailed {
			return fmt.Errorf("m4: FAILED results must carry ALL_WORKERS_FAILED and no brief")
		}
	case StepStatusCancelled:
		if result.SynthesisInvoked || result.Brief != nil || result.FailureCode != nil ||
			result.RunStateStatus != StepStatusCancelled {
			return fmt.Errorf("m4: CANCELLED results carry no synthesis, brief, or failure code")
		}
	}
	if result.Brief != nil && result.Brief.OrderID != result.OrderID {
		return fmt.Errorf("m4: brief order_id must match the run")
	}
	return validateBriefSectionOrder(result)
}

// validateBriefSectionOrder pins the canonical order of the brief sections.
func validateBriefSectionOrder(result contracts.OrderBriefRecoveryResult) error {
	if result.Brief == nil {
		return nil
	}
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
			return fmt.Errorf("m4: brief sections must follow the canonical order")
		}
		position = found + 1
	}
	return nil
}

// validateRecoveryProvenance pins the resumed/restored conditional block:
// fresh runs carry no restored evidence; resumed runs carry the cursor.
func validateRecoveryProvenance(result contracts.OrderBriefRecoveryResult) error {
	if !result.Resumed {
		if result.RestoredCursor != nil || len(result.RestoredWorkerIDs) != 0 {
			return fmt.Errorf("m4: fresh results carry no restored evidence")
		}
		return nil
	}
	if result.RestoredCursor == nil || *result.RestoredCursor < 0 || *result.RestoredCursor > 3 {
		return fmt.Errorf("m4: resumed results must carry the restored cursor")
	}
	if len(result.RestoredWorkerIDs) > 3 {
		return fmt.Errorf("m4: restored worker ids overflow the canonical set")
	}
	return nil
}
