package m4

import (
	"fmt"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

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

// recordedOutcomes rebuilds the recorded worker outcomes from the document.
func recordedOutcomes(document RunStateDocument) []WorkerOutcome {
	outcomes := []WorkerOutcome{}
	for _, step := range document.Steps {
		if !recordedStep(step) {
			continue
		}
		outcome := WorkerOutcome{WorkerID: step.WorkerID, Status: step.Status,
			Output: append(jsonRaw(nil), step.Output...), FailureCode: step.FailureCode}
		if step.Output == nil {
			outcome.Output = nil
		}
		outcomes = append(outcomes, outcome)
	}
	return outcomes
}

// derivePending derives the resuming queue from the step statuses, in
// canonical order: PENDING, RUNNING (the in-flight step re-executes once),
// and CANCELLED (a cancelled run is resumable) workers; recorded terminals
// never re-execute.
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

// requireResumable fails closed for terminal state documents: only RUNNING
// and CANCELLED runs resume.
func requireResumable(document RunStateDocument) error {
	if document.Status != RunStateStatusRunning && document.Status != RunStateStatusCancelled {
		return fmt.Errorf("m4: run state is not resumable (run_id=%s status=%s)",
			document.RunID, document.Status)
	}
	return nil
}

// emitRestored announces the recovery anchor: the loaded status, the
// Ruling-2 cursor, and the recorded worker identities.
func emitRestored(deps runDependencies, document RunStateDocument) error {
	return deps.emit(contracts.EventCheckpointRestored, map[string]any{
		"case_id": deps.binding.CaseID, "execution_mode": deps.binding.ExecutionMode,
		"requested_order_id":  deps.binding.RequestedOrderID,
		"concurrency_limit":   deps.binding.ConcurrencyLimit,
		"state_status":        document.Status,
		"restored_cursor":     document.SequenceCursor,
		"restored_worker_ids": recordedWorkerIDs(document)})
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

// resumeRun continues a recorded run: load (fail-closed), resumability,
// the restored event, and the recovered completion.
func resumeRun(deps runDependencies, loaded LoadedRunState) (contracts.OrderBriefRecoveryResult, error) {
	document := loaded.Document
	if err := requireResumable(document); err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	if err := emitRestored(deps, document); err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	store := deps.options.StateStore
	if store == nil {
		created, err := ResumeStore(document, loaded.RestoredFrom)
		if err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
		store = created
	}
	return completeRecoveredRun(deps, store, document)
}

// replayFrom starts a NEW run (a fresh run id under the same state root)
// seeded from an immutable checkpoint snapshot; the source run's state is
// never touched.
func replayFrom(deps runDependencies, document RunStateDocument, seeded *StateStore) (contracts.OrderBriefRecoveryResult, error) {
	if err := requireResumable(document); err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	if err := emitRestored(deps, document); err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	store := seeded
	if store == nil {
		created, err := CreateStore(deps.options.StateDir, deps.binding, append([]string(nil), contracts.CanonicalWorkerIDs...))
		if err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
		for _, outcome := range recordedOutcomes(document) {
			if err := created.RecordStepTerminal(outcome.WorkerID, outcome); err != nil {
				return contracts.OrderBriefRecoveryResult{}, err
			}
		}
		store = created
	}
	return completeRecoveredRun(deps, store, store.State())
}

// completeRecoveredRun executes the pending queue (recorded outcomes never
// re-execute; an in-flight step re-executes once), merges the recovered and
// fresh outcomes canonically, synthesizes when evidence exists, closes the
// state document, and assembles the validated resumed result.
func completeRecoveredRun(deps runDependencies, store *StateStore, document RunStateDocument) (contracts.OrderBriefRecoveryResult, error) {
	observer := func(event WorkerLifecycle) {
		if deps.observer != nil {
			deps.observer(event)
		}
		if event.Kind == LifecycleTerminal {
			_ = emitCheckpointSaved(deps, store, event.Outcome.WorkerID)
		}
	}
	summary, err := ExecuteWorkers(deps.ctx, ExecutorOptions{
		Mode:      deps.binding.ExecutionMode,
		Input:     WorkerInput{OrderID: deps.binding.RequestedOrderID},
		Directory: deps.directory, Control: deps.control, Observer: observer,
		Store: store, Queue: derivePending(document)})
	if err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	restored := map[string]WorkerOutcome{}
	for _, outcome := range recordedOutcomes(document) {
		restored[outcome.WorkerID] = outcome
	}
	fresh := map[string]WorkerOutcome{}
	for _, outcome := range summary.Outcomes {
		fresh[outcome.WorkerID] = outcome
	}
	merged := make([]WorkerOutcome, 0, 3)
	for _, id := range contracts.CanonicalWorkerIDs {
		if outcome, ok := restored[id]; ok {
			merged = append(merged, outcome)
			continue
		}
		outcome, ok := fresh[id]
		if !ok {
			return contracts.OrderBriefRecoveryResult{}, fmt.Errorf("m4: worker %s has no recovered or fresh outcome", id)
		}
		merged = append(merged, outcome)
	}
	canonical, err := CanonicalizeOutcomes(merged, deps.binding.RequestedOrderID)
	if err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	succeeded := 0
	for _, outcome := range canonical {
		if outcome.Status == StatusSucceeded {
			succeeded++
		}
	}
	status := RunStatePartial
	switch {
	case succeeded == 3:
		status = RunStateSucceeded
	case succeeded == 0:
		status = RunStateFailed
	}
	failureCode := ""
	if status == RunStateFailed {
		failureCode = contracts.FailureAllWorkersFailed
	}
	var brief *contracts.Brief
	synthesisInvoked := false
	if succeeded > 0 {
		if err := deps.emit(contracts.EventStepStarted, map[string]any{
			"step_name": "synthesize", "worker_outcomes": canonical}); err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
		assembled, err := deps.synthesizer(deps.binding.RequestedOrderID, canonical)
		if err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
		brief = &assembled
		synthesisInvoked = true
		if err := deps.emit(contracts.EventStepCompleted, map[string]any{
			"step_name": "synthesize", "brief": brief}); err != nil {
			return contracts.OrderBriefRecoveryResult{}, err
		}
	}
	if err := store.MarkTerminal(status, failureCode); err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	records := workerRecords(canonical[:], restoredRunning(document))
	if synthesisInvoked {
		records = append(records, stepRecord{name: "synthesize", attempts: 1})
	}
	attribution, err := BuildAttribution(records, deps.scenario.Attribution)
	if err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	peak := summary.PeakConcurrency
	if peak < 1 {
		peak = 1
	}
	result := contracts.OrderBriefRecoveryResult{
		SchemaVersion:     contracts.EnvelopeVersion,
		RunID:             store.RunID(),
		ScenarioID:        ScenarioID,
		CaseID:            deps.binding.CaseID,
		ExecutionMode:     deps.binding.ExecutionMode,
		ConcurrencyLimit:  deps.binding.ConcurrencyLimit,
		PeakConcurrency:   peak,
		OrderID:           deps.binding.RequestedOrderID,
		Status:            status,
		WorkerOutcomes:    append([]WorkerOutcome(nil), canonical[:]...),
		SynthesisInvoked:  synthesisInvoked,
		Brief:             brief,
		FailureCode:       nil,
		TracePath:         deps.options.TracePath,
		Resumed:           true,
		RestoredCursor:    &document.SequenceCursor,
		RestoredWorkerIDs: recordedWorkerIDs(document),
		StateDir:          deps.options.StateDir,
		RunStateStatus:    status,
		Attribution:       attribution,
	}
	if failureCode != "" {
		result.FailureCode = strPtr(failureCode)
	}
	if err := validateRecoveryResult(result); err != nil {
		return contracts.OrderBriefRecoveryResult{}, err
	}
	return result, nil
}

// concurrencyLimitOf maps the execution mode to its bounded limit.
func concurrencyLimitOf(mode string) int {
	if mode == ModeParallel {
		return 2
	}
	return 1
}
