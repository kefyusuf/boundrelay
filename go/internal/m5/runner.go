package m5

import (
	"context"
	"errors"
	"fmt"
	"os"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// RunOptions configures one order-closure run; zero-value dependencies
// select the checked-in projections and the scripted workers. Resume
// continues the recorded run in StateDir through the submit-window
// recovery.
type RunOptions struct {
	CaseID     string
	TracePath  string
	StateDir   string
	Resume     bool
	Sink       *EventSink
	Observer   WorkerObserver
	Directory  WorkerDirectory
	Control    WorkerControl
	StateStore *StateStore
	OnCrash    func()
	Scenario   *Scenario
	Fixtures   map[string]WorkerInstructions
	RepoRoot   string
}

// RunReport carries the validated result and the full trace of THIS phase.
type RunReport struct {
	Result contracts.OrderClosureResult
	Events []contracts.Event
}

// runDependencies bundles the resolved collaborators shared by the fresh
// and resume lifecycles.
type runDependencies struct {
	ctx       context.Context
	options   RunOptions
	scenario  *Scenario
	spec      CaseSpec
	binding   StateBinding
	sink      *EventSink
	observer  WorkerObserver
	directory WorkerDirectory
	control   WorkerControl
	fixtures  map[string]WorkerInstructions
	emit      func(contracts.EventType, map[string]any) error
}

// RunCase executes one lifecycle: envelope lifecycle, scripted bounded
// reads with the effect pipeline (write-ahead marker, once-per-key ledger,
// audit), the crash controls' hard exit, fail-closed submit-window recovery
// (adopt / resubmit / UNKNOWN), attribution, result validation, and the
// trace flush (which happens even on tooling failures, mirroring the
// TS/Python finally block; the crash control flushes before its hard exit).
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
		return RunReport{}, errors.New("m5: trace path and state dir are required")
	}
	if (options.Directory == nil) != (options.Control == nil) {
		return RunReport{}, errors.New("m5: directory and control must be supplied together")
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
	var store *StateStore
	if loaded == nil {
		store = options.StateStore
		if store == nil {
			created, err := CreateStore(options.StateDir, binding,
				append([]string(nil), contracts.CanonicalWorkerIDs...))
			if err != nil {
				return RunReport{}, err
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
	deps := runDependencies{ctx: ctx, options: options, scenario: scenario, spec: spec,
		binding: binding, sink: sink, observer: options.Observer, fixtures: fixtures, emit: emit}
	if options.Directory != nil {
		deps.directory, deps.control = options.Directory, options.Control
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

	var result contracts.OrderClosureResult
	if loaded != nil {
		result, err = resumedRun(deps, *loaded)
	} else {
		result, err = freshRun(deps, store)
	}
	if err != nil {
		return RunReport{}, err
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

// recordedWorkerIDs lists the workers whose outcomes are recorded in the
// document (SUCCEEDED or FAILED), in canonical step order.
func recordedWorkerIDs(document RunStateDocument) []string {
	ids := []string{}
	for _, step := range document.Steps {
		if recordedStep(step) {
			ids = append(ids, step.WorkerID)
		}
	}
	return ids
}

// derivePending derives the resuming queue from the step statuses, in
// canonical order: PENDING, RUNNING (the in-flight step re-executes once),
// and CANCELLED workers; recorded terminals never re-execute.
func derivePending(document RunStateDocument) []string {
	statuses := map[string]string{}
	for _, step := range document.Steps {
		statuses[step.WorkerID] = step.Status
	}
	pending := []string{}
	for _, id := range contracts.CanonicalWorkerIDs {
		switch statuses[id] {
		case StepStatusPending, StepStatusRunning, StepStatusCancelled:
			pending = append(pending, id)
		}
	}
	return pending
}

// freshRun executes the whole canonical queue with the case's scripted
// effect wiring: the crash controls hard-exit after flushing the trace
// prefix, exactly inside the submit window the case scripts.
func freshRun(deps runDependencies, store *StateStore) (contracts.OrderClosureResult, error) {
	if deps.directory == nil {
		provider := NewScriptedWorkers(deps.spec.ExecutionMode, deps.spec.CompletionOrder,
			deps.scenario.OrderID, deps.fixtures[deps.spec.WorkerFixture])
		deps.directory = DirectoryFromProvider(provider)
		deps.control = provider
	}
	observer := observerFor(deps, store)
	wiring, err := effectWiring(deps, deps.spec.Controls)
	if err != nil {
		return contracts.OrderClosureResult{}, err
	}
	execution, err := ExecuteWorkers(deps.ctx, ExecutorOptions{
		Mode:      deps.spec.ExecutionMode,
		Input:     WorkerInput{OrderID: deps.scenario.OrderID},
		Directory: deps.directory, Control: deps.control, Observer: observer,
		Store: store, Effect: wiring})
	if err != nil {
		return contracts.OrderClosureResult{}, err
	}
	reads := execution.Reads
	successes := 0
	for _, outcome := range reads {
		if outcome.Status == StatusSucceeded {
			successes++
		}
	}
	var effectStatus, key, failureCode string
	decision := DecisionNone
	status := RunStatePartial
	switch {
	case successes == 3 && execution.Rejected:
		// The approval rejected the effect: the run fails with
		// APPROVAL_REJECTED and zero submissions (no effect of record).
		status, decision, failureCode = RunStateFailed, DecisionRejected, FailureApprovalRejected
	case successes == 3:
		status, decision = RunStateSucceeded, DecisionGranted
		if execution.Effect != nil {
			effectStatus, key = execution.Effect.Status, execution.Effect.Key
		}
	case successes > 0:
		decision = DecisionNone
	default:
		status, decision, failureCode = RunStateFailed, DecisionNone, contracts.FailureAllWorkersFailed
	}
	result, err := assemble(deps, store.RunID(), execution.PeakConcurrency, status,
		reads, decision, effectStatus, key, failureCode, false, false, nil, nil)
	if err != nil {
		return contracts.OrderClosureResult{}, err
	}
	if status == RunStateFailed {
		if failureCode == "" {
			failureCode = contracts.FailureAllWorkersFailed
		}
		if err := store.MarkTerminal(RunStateFailed, failureCode); err != nil {
			return contracts.OrderClosureResult{}, err
		}
	} else if err := store.MarkTerminal(status, ""); err != nil {
		return contracts.OrderClosureResult{}, err
	}
	return publish(deps.sink, result)
}

// resumedRun continues a recorded run: pending reads re-execute (recorded
// terminals never do), and the effect decision is resolved through the
// submit-window recovery — adopt, one resubmit, or the UNKNOWN terminal.
func resumedRun(deps runDependencies, loaded LoadedRunState) (contracts.OrderClosureResult, error) {
	document := loaded.Document
	store := deps.options.StateStore
	if store == nil {
		created, err := ResumeStore(document, loaded.RestoredFrom)
		if err != nil {
			return contracts.OrderClosureResult{}, err
		}
		store = created
	}
	pending := derivePending(document)
	peak := 1
	if len(pending) > 0 {
		if deps.directory == nil {
			scriptedMode := deps.spec.ExecutionMode
			if len(pending) < 2 {
				scriptedMode = ModeSequential
			}
			scriptedCompletion := make([]string, 0, len(deps.spec.CompletionOrder))
			for _, id := range deps.spec.CompletionOrder {
				for _, candidate := range pending {
					if id == candidate {
						scriptedCompletion = append(scriptedCompletion, id)
						break
					}
				}
			}
			provider := NewScriptedWorkers(scriptedMode, scriptedCompletion,
				deps.scenario.OrderID, deps.fixtures[deps.spec.WorkerFixture])
			deps.directory = DirectoryFromProvider(provider)
			deps.control = provider
		}
		execution, err := ExecuteWorkers(deps.ctx, ExecutorOptions{
			Mode:      scriptedModeFor(deps.spec.ExecutionMode, pending),
			Input:     WorkerInput{OrderID: deps.binding.RequestedOrderID},
			Directory: deps.directory, Control: deps.control,
			Observer: observerFor(deps, store), Store: store, Queue: pending})
		if err != nil {
			return contracts.OrderClosureResult{}, err
		}
		peak = execution.PeakConcurrency
		if peak < 1 {
			peak = 1
		}
	}
	restoredCursor := document.SequenceCursor
	restoredWorkerIDs := recordedWorkerIDs(document)
	current := store.State()
	reads := recordedReads(current)
	successes := 0
	for _, outcome := range reads {
		if outcome.Status == StatusSucceeded {
			successes++
		}
	}
	if current.Effect != nil || current.SubmitMarker != nil {
		var controls *EffectControls
		if deps.spec.Controls != nil && deps.spec.Controls.SinkUnavailable {
			controls = &EffectControls{SinkUnavailable: true}
		}
		ledger, err := NewEffectLedger(deps.options.StateDir)
		if err != nil {
			return contracts.OrderClosureResult{}, err
		}
		audit, err := NewAuditWriter(deps.options.StateDir)
		if err != nil {
			return contracts.OrderClosureResult{}, err
		}
		recovery, err := ResumeRun(RecoveryOptions{StateRoot: deps.options.StateDir,
			Binding: deps.binding, Ledger: ledger, Audit: audit, Controls: controls})
		if err != nil {
			return contracts.OrderClosureResult{}, err
		}
		status := RunStateSucceeded
		effectStatus := ""
		if recovery.Effect != nil {
			effectStatus = recovery.Effect.Status
		}
		if recovery.Status == RunStateUnknown {
			status = RunStateUnknown
			effectStatus = EffectUnprovable
		}
		result, err := assemble(deps, store.RunID(), peak, status, reads, DecisionGranted,
			effectStatus, recovery.IdempotencyKey, "", recovery.Reconciled, true,
			&restoredCursor, restoredWorkerIDs)
		if err != nil {
			return contracts.OrderClosureResult{}, err
		}
		return publish(deps.sink, result)
	}
	if successes == 3 {
		// The reads are already recorded; the effect pipeline re-runs alone
		// (sequential, empty queue, no scripted controls) through the same
		// fixture approval gate.
		provider := NewScriptedWorkers(deps.spec.ExecutionMode, deps.spec.CompletionOrder,
			deps.scenario.OrderID, deps.fixtures[deps.spec.WorkerFixture])
		wiring, err := effectWiring(deps, nil)
		if err != nil {
			return contracts.OrderClosureResult{}, err
		}
		execution, err := ExecuteWorkers(deps.ctx, ExecutorOptions{
			Mode:      ModeSequential,
			Input:     WorkerInput{OrderID: deps.binding.RequestedOrderID},
			Directory: DirectoryFromProvider(provider), Control: provider,
			Observer: stepObserver(deps.sink), Store: store, Queue: []string{},
			Effect: wiring})
		if err != nil {
			return contracts.OrderClosureResult{}, err
		}
		if execution.Effect == nil {
			return contracts.OrderClosureResult{}, errors.New("m5: the resumed effect refire produced no effect of record")
		}
		result, err := assemble(deps, store.RunID(), execution.PeakConcurrency, RunStateSucceeded,
			reads, DecisionGranted, execution.Effect.Status, execution.Effect.Key, "",
			false, true, &restoredCursor, restoredWorkerIDs)
		if err != nil {
			return contracts.OrderClosureResult{}, err
		}
		if err := store.MarkTerminal(RunStateSucceeded, ""); err != nil {
			return contracts.OrderClosureResult{}, err
		}
		return publish(deps.sink, result)
	}
	status, failureCode := RunStatePartial, ""
	if successes == 0 {
		status, failureCode = RunStateFailed, contracts.FailureAllWorkersFailed
	}
	result, err := assemble(deps, store.RunID(), peak, status, reads, DecisionNone,
		"", "", failureCode, false, true, &restoredCursor, restoredWorkerIDs)
	if err != nil {
		return contracts.OrderClosureResult{}, err
	}
	if status == RunStateFailed {
		if err := store.MarkTerminal(RunStateFailed, failureCode); err != nil {
			return contracts.OrderClosureResult{}, err
		}
	} else if err := store.MarkTerminal(status, ""); err != nil {
		return contracts.OrderClosureResult{}, err
	}
	return publish(deps.sink, result)
}

// scriptedModeFor is the resuming spec's mode: a single pending worker
// executes sequentially even in a parallel case.
func scriptedModeFor(mode string, pending []string) string {
	if len(pending) < 2 {
		return ModeSequential
	}
	return mode
}

// effectWiring bundles the case's effect collaborators: the state-dir
// ledger and audit trail, the fixture approval gate, the scripted controls,
// and the crash hook (the hard exit by default).
func effectWiring(deps runDependencies, controls *EffectControls) (*EffectWiring, error) {
	ledger, err := NewEffectLedger(deps.options.StateDir)
	if err != nil {
		return nil, err
	}
	audit, err := NewAuditWriter(deps.options.StateDir)
	if err != nil {
		return nil, err
	}
	onCrash := deps.options.OnCrash
	if onCrash == nil {
		onCrash = func() {
			_ = deps.sink.Flush(deps.options.TracePath)
			os.Exit(2)
		}
	}
	return &EffectWiring{Ledger: ledger, ApprovalGate: NewApprovalGate(deps.spec.Approval),
		Audit: audit, Controls: controls, OnCrash: onCrash, Events: deps.sink}, nil
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

// observerFor is the read-phase observer: step events plus the checkpoint
// saved announcement after the store recorded the terminal, wrapped around
// the caller's observer.
func observerFor(deps runDependencies, store *StateStore) WorkerObserver {
	step := stepObserver(deps.sink)
	caller := deps.observer
	return func(event WorkerLifecycle) {
		if caller != nil {
			caller(event)
		}
		step(event)
		if event.Kind == LifecycleTerminal {
			_ = emitCheckpointSaved(deps, store, event.Outcome.WorkerID)
		}
	}
}

// emitCheckpointSaved announces one recorded terminal with the store's
// post-write status and cursor.
func emitCheckpointSaved(deps runDependencies, store *StateStore, workerID string) error {
	document := store.State()
	return deps.emit(contracts.EventCheckpointSaved, map[string]any{
		"case_id": deps.binding.CaseID, "execution_mode": deps.binding.ExecutionMode,
		"requested_order_id": deps.binding.RequestedOrderID,
		"concurrency_limit":  deps.binding.ConcurrencyLimit,
		"step_name":          workerID,
		"state_status":       document.Status,
		"sequence_cursor":    document.SequenceCursor})
}

// assemble builds the result: canonical worker outcomes, the
// fixture-priced attribution (worker reads plus the effect submission when
// an effect of record exists), and the side-effect/recovery provenance.
func assemble(deps runDependencies, runID string, peak int, status string,
	reads []WorkerOutcome, decision string, effectStatus string, key string,
	failureCode string, reconciled bool, resumed bool, restoredCursor *int,
	restoredWorkerIDs []string) (contracts.OrderClosureResult, error) {
	canonical, err := CanonicalizeReads(reads, deps.binding.RequestedOrderID)
	if err != nil {
		return contracts.OrderClosureResult{}, err
	}
	if peak < 1 {
		peak = 1
	}
	records := workerRecords(canonical[:])
	records = append(records, effectRecords(key)...)
	attribution, err := BuildAttribution(records, deps.scenario.Attribution)
	if err != nil {
		return contracts.OrderClosureResult{}, err
	}
	result := contracts.OrderClosureResult{
		SchemaVersion:     contracts.EnvelopeVersion,
		RunID:             runID,
		ScenarioID:        ScenarioID,
		CaseID:            deps.binding.CaseID,
		ExecutionMode:     deps.binding.ExecutionMode,
		ConcurrencyLimit:  deps.binding.ConcurrencyLimit,
		PeakConcurrency:   peak,
		OrderID:           deps.binding.RequestedOrderID,
		Status:            status,
		WorkerOutcomes:    append([]WorkerOutcome(nil), canonical[:]...),
		SynthesisInvoked:  false,
		Brief:             nil,
		ApprovalDecision:  decision,
		Reconciled:        reconciled,
		TracePath:         deps.options.TracePath,
		Resumed:           resumed,
		RestoredCursor:    restoredCursor,
		RestoredWorkerIDs: restoredWorkerIDs,
		StateDir:          deps.options.StateDir,
		RunStateStatus:    status,
		Attribution:       attribution,
	}
	if effectStatus != "" {
		result.EffectStatus = strPtr(effectStatus)
	}
	if key != "" {
		result.IdempotencyKey = strPtr(key)
	}
	if failureCode != "" {
		result.FailureCode = strPtr(failureCode)
	}
	if result.RestoredWorkerIDs == nil {
		result.RestoredWorkerIDs = []string{}
	}
	return result, nil
}

// publish validates the result against the closed order-closure result
// contract and emits the terminal event.
func publish(sink *EventSink, result contracts.OrderClosureResult) (contracts.OrderClosureResult, error) {
	if err := validateResult(result); err != nil {
		return contracts.OrderClosureResult{}, err
	}
	terminal := contracts.EventRunCompleted
	if result.Status == RunStateFailed {
		terminal = contracts.EventRunFailed
	}
	_, err := sink.Emit(terminal, map[string]any{
		"status": result.Status, "worker_outcomes": result.WorkerOutcomes,
		"synthesis_invoked": false, "brief": nil,
		"failure_code": result.FailureCode, "peak_concurrency": result.PeakConcurrency,
		"reconciled": result.Reconciled, "approval_decision": result.ApprovalDecision,
		"effect_status": result.EffectStatus, "idempotency_key": result.IdempotencyKey})
	if err != nil {
		return contracts.OrderClosureResult{}, err
	}
	return result, nil
}

// validateResult mirrors the closed order-closure result schema: required
// fields, enums, canonical worker order, the status conditionals, the
// recovery provenance conditionals, and the reconciled conditional.
func validateResult(result contracts.OrderClosureResult) error {
	switch {
	case result.SchemaVersion != contracts.EnvelopeVersion:
		return fmt.Errorf("m5: result schema_version must be %q", contracts.EnvelopeVersion)
	case result.RunID == "" || result.TracePath == "" || result.StateDir == "":
		return fmt.Errorf("m5: result run_id, trace_path, and state_dir must be nonempty")
	case result.ScenarioID != ScenarioID || result.CaseID == "":
		return fmt.Errorf("m5: result scenario/case identifiers are invalid")
	case result.ExecutionMode != ModeSequential && result.ExecutionMode != ModeParallel:
		return fmt.Errorf("m5: result execution_mode %q is outside the enum", result.ExecutionMode)
	case !resultStatusValid(result.Status):
		return fmt.Errorf("m5: result status %q is outside the enum", result.Status)
	case result.ApprovalDecision != DecisionGranted && result.ApprovalDecision != DecisionRejected &&
		result.ApprovalDecision != DecisionNone:
		return fmt.Errorf("m5: result approval_decision %q is outside the enum", result.ApprovalDecision)
	case !orderIDPattern.MatchString(result.OrderID):
		return fmt.Errorf("m5: result order_id %q is invalid", result.OrderID)
	}
	limit := concurrencyLimitOf(result.ExecutionMode)
	peakLimit := 2
	if result.ExecutionMode == ModeSequential {
		peakLimit = 1
	}
	if result.ConcurrencyLimit != limit || result.PeakConcurrency < 1 ||
		result.PeakConcurrency > peakLimit {
		return fmt.Errorf("m5: result concurrency %d/%d violates the schema",
			result.ConcurrencyLimit, result.PeakConcurrency)
	}
	if len(result.WorkerOutcomes) != 3 {
		return fmt.Errorf("m5: result carries %d worker outcomes, want 3", len(result.WorkerOutcomes))
	}
	successes := 0
	for i, outcome := range result.WorkerOutcomes {
		if outcome.WorkerID != contracts.CanonicalWorkerIDs[i] ||
			!validateWorkerOutcome(outcome, result.OrderID) {
			return fmt.Errorf("m5: worker outcome %d is invalid or out of canonical order", i)
		}
		if outcome.Status == StatusSucceeded {
			successes++
		}
	}
	if result.SynthesisInvoked || result.Brief != nil {
		return fmt.Errorf("m5: order-closure results never synthesize (Ruling 4)")
	}
	if err := validateStatusConditionals(result, successes); err != nil {
		return err
	}
	if err := validateProvenance(result); err != nil {
		return err
	}
	if result.Reconciled && result.Status != RunStateSucceeded {
		return fmt.Errorf("m5: reconciled results must be SUCCEEDED")
	}
	if len(result.Attribution.Steps) == 0 {
		return fmt.Errorf("m5: result attribution requires at least one executed step")
	}
	return nil
}

func resultStatusValid(status string) bool {
	switch status {
	case RunStateSucceeded, RunStatePartial, RunStateFailed, RunStateStatusCancelled, RunStateUnknown:
		return true
	}
	return false
}

// validateStatusConditionals pins the per-status shape: outcomes, failure
// code, approval decision, effect status, idempotency key, and the
// run-state status.
func validateStatusConditionals(result contracts.OrderClosureResult, successes int) error {
	switch {
	case result.Status == RunStateSucceeded:
		if successes != 3 || result.FailureCode != nil ||
			result.ApprovalDecision != DecisionGranted ||
			result.EffectStatus == nil || *result.EffectStatus != EffectCompleted ||
			result.IdempotencyKey == nil || *result.IdempotencyKey == "" ||
			result.RunStateStatus != RunStateSucceeded {
			return fmt.Errorf("m5: SUCCEEDED results need three successes, a granted approval, and a completed effect")
		}
	case result.Status == RunStatePartial:
		if successes < 1 || successes > 2 || result.FailureCode != nil ||
			result.ApprovalDecision != DecisionNone || result.EffectStatus != nil ||
			result.IdempotencyKey != nil || result.Reconciled ||
			result.RunStateStatus != RunStatePartial {
			return fmt.Errorf("m5: PARTIAL results need one or two successes and no effect")
		}
	case result.Status == RunStateFailed && result.FailureCode != nil &&
		*result.FailureCode == contracts.FailureAllWorkersFailed:
		if successes != 0 || result.ApprovalDecision != DecisionNone ||
			result.EffectStatus != nil || result.IdempotencyKey != nil || result.Reconciled ||
			result.RunStateStatus != RunStateFailed {
			return fmt.Errorf("m5: ALL_WORKERS_FAILED results need zero successes and no effect")
		}
	case result.Status == RunStateFailed && result.FailureCode != nil &&
		*result.FailureCode == FailureApprovalRejected:
		if successes != 3 || result.ApprovalDecision != DecisionRejected ||
			result.EffectStatus != nil || result.IdempotencyKey != nil || result.Reconciled ||
			result.RunStateStatus != RunStateFailed {
			return fmt.Errorf("m5: APPROVAL_REJECTED results need three successes, a rejected approval, and zero submissions")
		}
	case result.Status == RunStateUnknown:
		if successes != 3 || result.FailureCode != nil ||
			result.ApprovalDecision != DecisionGranted ||
			result.EffectStatus == nil || *result.EffectStatus != EffectUnprovable ||
			result.IdempotencyKey == nil || *result.IdempotencyKey == "" || result.Reconciled ||
			result.RunStateStatus != RunStateUnknown {
			return fmt.Errorf("m5: UNKNOWN results need three successes and an unprovable effect")
		}
	default:
		return fmt.Errorf("m5: FAILED results must carry ALL_WORKERS_FAILED or APPROVAL_REJECTED")
	}
	return nil
}

// validateProvenance pins the resumed/restored conditional block: fresh
// runs carry no restored evidence; resumed runs carry the cursor.
func validateProvenance(result contracts.OrderClosureResult) error {
	if !result.Resumed {
		if result.RestoredCursor != nil || len(result.RestoredWorkerIDs) != 0 {
			return fmt.Errorf("m5: fresh results carry no restored evidence")
		}
		return nil
	}
	if result.RestoredCursor == nil || *result.RestoredCursor < 0 || *result.RestoredCursor > 3 {
		return fmt.Errorf("m5: resumed results must carry the restored cursor")
	}
	if len(result.RestoredWorkerIDs) > 3 {
		return fmt.Errorf("m5: restored worker ids overflow the canonical set")
	}
	return nil
}

// concurrencyLimitOf maps the execution mode to its bounded limit.
func concurrencyLimitOf(mode string) int {
	if mode == ModeParallel {
		return 2
	}
	return 1
}
