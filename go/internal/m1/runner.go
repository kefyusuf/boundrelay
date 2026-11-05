package m1

import (
	"crypto/rand"
	"fmt"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// RunOptions configures one order-investigation run; the zero-value
// dependencies select the checked-in scenario/fake-model/fake-tools
// projections and a fresh random run id.
type RunOptions struct {
	Mode      string
	CaseID    string
	TracePath string
	Scenario  *Scenario
	Provider  ModelProvider
	Registry  ToolRegistry
	RunID     string
	RepoRoot  string
}

// RunReport carries the result and the full trace.
type RunReport struct {
	Result contracts.ToolLoopResult
	Events []contracts.Event
}

// RunCase executes one order-investigation run: envelope lifecycle, the
// direct call or the bounded agent loop, attribution, and the flushed
// trace. Tooling failures return an error and leave no trace; domain
// failures produce a FAILED result with the mapped failure code.
func RunCase(options RunOptions) (RunReport, error) {
	if options.Mode != ModeDirect && options.Mode != ModeAgent {
		return RunReport{}, fmt.Errorf("m1: --mode must be direct or agent, got %q", options.Mode)
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
	if scenarioCase.Mode != options.Mode {
		return RunReport{}, fmt.Errorf("%w: requested mode %s does not match canonical case mode %s",
			ErrModeMismatch, options.Mode, scenarioCase.Mode)
	}
	runID := options.RunID
	if runID == "" {
		runID = newUUID()
	}
	sink := NewEventSink(runID)
	registry := options.Registry
	if registry == nil {
		root := options.RepoRoot
		if root == "" {
			discovered, err := FindRepoRoot()
			if err != nil {
				return RunReport{}, err
			}
			root = discovered
		}
		data, err := LoadFakeTools(DefaultFakeToolsPath(root))
		if err != nil {
			return RunReport{}, err
		}
		registry = NewFakeToolRegistry(data)
	}
	state := &runState{
		mode: options.Mode, scenarioCase: scenarioCase, sink: sink,
		registry: registry, tables: scenario.Attribution, tracePath: options.TracePath,
		toolCounts: map[string]int{},
	}
	if err := state.emit(contracts.EventRunCreated, map[string]any{
		"scenario_id": scenario.ScenarioID, "case_id": scenarioCase.ID, "mode": options.Mode}); err != nil {
		return RunReport{}, err
	}
	if err := state.emit(contracts.EventRunStarted, map[string]any{
		"case_id": scenarioCase.ID, "mode": options.Mode}); err != nil {
		return RunReport{}, err
	}
	var result *contracts.ToolLoopResult
	if options.Mode == ModeDirect {
		result, err = state.runDirect()
	} else {
		provider := options.Provider
		if provider == nil {
			root := options.RepoRoot
			if root == "" {
				discovered, discoverErr := FindRepoRoot()
				if discoverErr != nil {
					return RunReport{}, discoverErr
				}
				root = discovered
			}
			turns, loadErr := LoadFakeModelTurns(DefaultFakeModelPath(root))
			if loadErr != nil {
				return RunReport{}, loadErr
			}
			provider = NewScriptedModelProvider(turns)
		}
		state.provider = provider
		result, err = state.runAgent()
	}
	if err != nil {
		return RunReport{}, err
	}
	return RunReport{Result: *result, Events: sink.Events()}, nil
}

// buildResult assembles and structurally validates the run result against
// the closed tool-loop result schema shape.
func (s *runState) buildResult(status string, answer, failureCode *string) (*contracts.ToolLoopResult, error) {
	attribution, err := buildAttribution(s.stepRecords(), s.tables)
	if err != nil {
		return nil, err
	}
	result := &contracts.ToolLoopResult{
		SchemaVersion:   contracts.EnvelopeVersion,
		RunID:           s.sink.runID,
		ScenarioID:      "order-investigation",
		CaseID:          s.scenarioCase.ID,
		Mode:            s.mode,
		Status:          status,
		Answer:          answer,
		FailureCode:     failureCode,
		ModelSteps:      s.modelSteps,
		TokensUsed:      s.tokensUsed,
		ToolInvocations: s.toolInvocations,
		TracePath:       s.tracePath,
		Attribution:     attribution,
	}
	if err := validateResult(*result); err != nil {
		return nil, err
	}
	return result, nil
}

// validateResult mirrors the closed M1 result schema: required fields, enum
// values, the answer/failure_code conditionals per status, and the
// attribution block bounds.
func validateResult(result contracts.ToolLoopResult) error {
	switch {
	case result.SchemaVersion != contracts.EnvelopeVersion:
		return fmt.Errorf("m1: result schema_version must be %q", contracts.EnvelopeVersion)
	case result.RunID == "" || result.TracePath == "":
		return fmt.Errorf("m1: result run_id and trace_path must be nonempty")
	case result.ScenarioID != "order-investigation" || result.CaseID == "":
		return fmt.Errorf("m1: result scenario/case identifiers are invalid")
	case result.Mode != ModeDirect && result.Mode != ModeAgent:
		return fmt.Errorf("m1: result mode %q is outside the enum", result.Mode)
	case result.Status != StatusSucceeded && result.Status != StatusFailed:
		return fmt.Errorf("m1: result status %q is outside the enum", result.Status)
	case result.Answer != nil && *result.Answer == "":
		return fmt.Errorf("m1: result answer must be a non-empty string when present")
	case result.FailureCode != nil && !contracts.IsM1FailureCode(*result.FailureCode):
		return fmt.Errorf("m1: result failure_code %q is outside the enum", *result.FailureCode)
	case result.ModelSteps < 0 || result.TokensUsed < 0 || result.ToolInvocations < 0:
		return fmt.Errorf("m1: result counters must be non-negative")
	}
	if err := validateAttributionBlock(result.Attribution); err != nil {
		return err
	}
	if result.Status == StatusSucceeded {
		if result.Answer == nil || result.FailureCode != nil {
			return fmt.Errorf("m1: SUCCEEDED results must carry a non-empty answer and no failure")
		}
		return nil
	}
	if result.Answer != nil || result.FailureCode == nil {
		return fmt.Errorf("m1: FAILED results must carry a failure code and no answer")
	}
	return nil
}

func validateAttributionBlock(attribution contracts.Attribution) error {
	if len(attribution.Steps) == 0 {
		return fmt.Errorf("m1: attribution requires at least one step record")
	}
	if attribution.Totals.LatencyMS < 0 || attribution.Totals.CostCents < 0 || attribution.Totals.Attempts < 1 {
		return fmt.Errorf("m1: attribution totals are outside the schema bounds")
	}
	for _, step := range attribution.Steps {
		if step.StepName == "" || step.LatencyMS < 0 || step.CostCents < 0 || step.Attempts < 1 {
			return fmt.Errorf("m1: attribution record %q is outside the schema bounds", step.StepName)
		}
	}
	return nil
}

// newUUID generates a random RFC 4122 version-4 id (stdlib only).
func newUUID() string {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		panic(fmt.Sprintf("m1: uuid generation failed: %v", err))
	}
	bytes[6] = (bytes[6] & 0x0f) | 0x40
	bytes[8] = (bytes[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", bytes[0:4], bytes[4:6], bytes[6:8], bytes[8:10], bytes[10:16])
}
