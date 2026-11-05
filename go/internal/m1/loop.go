package m1

import (
	"encoding/json"
	"errors"
	"fmt"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// Model decision kinds (contracts/agent/model-turn.schema.json).
const (
	DecisionToolCall = "tool_call"
	DecisionFinal    = "final"
)

// ToolObservation is one completed tool observation fed back to the model.
type ToolObservation struct {
	CallID string
	Tool   string
	Output map[string]any
}

// ModelInput is the per-step input to the model provider.
type ModelInput struct {
	CaseID       string
	Request      string
	ModelStep    int
	Observations []ToolObservation
}

// ModelProvider produces the next raw scripted turn for one model step.
// Provider errors are domain failures: the loop maps them 1:1 to the
// INVALID_MODEL_DECISION failure code.
type ModelProvider interface {
	NextTurn(input ModelInput) (json.RawMessage, error)
}

// ModelDecision is the validated model decision: a tool call or a final
// answer.
type ModelDecision struct {
	Kind      string
	CallID    string
	Tool      string
	Arguments map[string]any
	Answer    string
}

// ModelTurn is the validated model turn: decision plus token usage.
type ModelTurn struct {
	Decision     ModelDecision
	InputTokens  int
	OutputTokens int
}

// turnWire mirrors the closed model-turn envelope for strict decoding.
type turnWire struct {
	SchemaVersion string          `json:"schema_version"`
	Decision      json.RawMessage `json:"decision"`
	Usage         *usageWire      `json:"usage"`
}

type usageWire struct {
	InputTokens  *int `json:"input_tokens"`
	OutputTokens *int `json:"output_tokens"`
}

// toolCallWire mirrors the tool_call decision branch (additionalProperties
// false: call_id, tool, arguments beside kind).
type toolCallWire struct {
	Kind      string         `json:"kind"`
	CallID    string         `json:"call_id"`
	Tool      string         `json:"tool"`
	Arguments map[string]any `json:"arguments"`
}

// finalWire mirrors the final decision branch (additionalProperties false:
// answer beside kind).
type finalWire struct {
	Kind   string `json:"kind"`
	Answer string `json:"answer"`
}

// ValidateModelTurn validates one raw model turn against the closed
// model-turn schema shape: the 1.0 header, a tool_call or final decision
// (branch-strict decoding), and non-negative integer usage.
func ValidateModelTurn(raw json.RawMessage) (ModelTurn, error) {
	var wire turnWire
	if err := contracts.DecodeStrict(raw, &wire); err != nil {
		return ModelTurn{}, fmt.Errorf("model turn is invalid: %w", err)
	}
	if wire.SchemaVersion != contracts.EnvelopeVersion {
		return ModelTurn{}, fmt.Errorf("model turn schema_version must be %q", contracts.EnvelopeVersion)
	}
	if wire.Usage == nil || wire.Usage.InputTokens == nil || wire.Usage.OutputTokens == nil ||
		*wire.Usage.InputTokens < 0 || *wire.Usage.OutputTokens < 0 {
		return ModelTurn{}, errors.New("model turn usage must carry non-negative integers")
	}
	turn := ModelTurn{InputTokens: *wire.Usage.InputTokens, OutputTokens: *wire.Usage.OutputTokens}
	var probe struct {
		Kind string `json:"kind"`
	}
	if err := json.Unmarshal(wire.Decision, &probe); err != nil {
		return ModelTurn{}, fmt.Errorf("model decision must be an object: %w", err)
	}
	switch probe.Kind {
	case DecisionToolCall:
		var decision toolCallWire
		if err := contracts.DecodeStrict(wire.Decision, &decision); err != nil {
			return ModelTurn{}, fmt.Errorf("tool_call decision is invalid: %w", err)
		}
		if decision.CallID == "" || decision.Tool == "" || decision.Arguments == nil {
			return ModelTurn{}, errors.New("tool_call decision requires call_id, tool, and an arguments object")
		}
		turn.Decision = ModelDecision{Kind: DecisionToolCall, CallID: decision.CallID,
			Tool: decision.Tool, Arguments: decision.Arguments}
		return turn, nil
	case DecisionFinal:
		var decision finalWire
		if err := contracts.DecodeStrict(wire.Decision, &decision); err != nil {
			return ModelTurn{}, fmt.Errorf("final decision is invalid: %w", err)
		}
		if decision.Answer == "" {
			return ModelTurn{}, errors.New("final decision requires a non-empty answer")
		}
		turn.Decision = ModelDecision{Kind: DecisionFinal, Answer: decision.Answer}
		return turn, nil
	default:
		return ModelTurn{}, fmt.Errorf("model decision kind %q is outside the enum", probe.Kind)
	}
}

// ScriptedModelProvider is the deterministic offline model: it replays the
// projected fake-model turns exactly once per case, in order, rejecting
// out-of-order or exhausted schedules (every provider error becomes the
// INVALID_MODEL_DECISION domain failure in the loop).
type ScriptedModelProvider struct {
	trajectories map[string][]json.RawMessage
	nextSteps    map[string]int
}

// NewScriptedModelProvider builds the scripted provider over the validated
// fake-model turns projection.
func NewScriptedModelProvider(turns map[string][]json.RawMessage) *ScriptedModelProvider {
	return &ScriptedModelProvider{trajectories: turns, nextSteps: map[string]int{}}
}

// NextTurn returns the case's scripted turn for the requested model step.
func (p *ScriptedModelProvider) NextTurn(input ModelInput) (json.RawMessage, error) {
	trajectory, ok := p.trajectories[input.CaseID]
	if !ok {
		return nil, fmt.Errorf("Missing scripted trajectory for case: %s", input.CaseID)
	}
	expected := p.nextSteps[input.CaseID] + 1
	if input.ModelStep != expected {
		return nil, fmt.Errorf("Out-of-order scripted turn for %s: expected %d, got %d.",
			input.CaseID, expected, input.ModelStep)
	}
	if input.ModelStep > len(trajectory) {
		return nil, fmt.Errorf("Scripted trajectory exhausted for %s at step %d.", input.CaseID, input.ModelStep)
	}
	p.nextSteps[input.CaseID] = expected
	return append(json.RawMessage(nil), trajectory[input.ModelStep-1]...), nil
}

// runState carries the counters and dependencies for one bounded run.
type runState struct {
	mode         string
	scenarioCase Case
	sink         *EventSink
	registry     ToolRegistry
	provider     ModelProvider
	tables       AttributionTables
	tracePath    string

	modelSteps      int
	tokensUsed      int
	toolInvocations int
	toolOrder       []string
	toolCounts      map[string]int
}

func (s *runState) emit(eventType contracts.EventType, data map[string]any) error {
	_, err := s.sink.Emit(eventType, data)
	return err
}

// recordToolInvocation bumps the invocation counters in first-invocation
// order (the attribution's tool.<name> record order).
func (s *runState) recordToolInvocation(name string) {
	s.toolInvocations++
	if _, seen := s.toolCounts[name]; !seen {
		s.toolOrder = append(s.toolOrder, name)
	}
	s.toolCounts[name]++
}

// stepRecords mirrors the TS/Py attribution order: the model record first in
// agent mode, then tool.<name> records in first-invocation order.
func (s *runState) stepRecords() []stepRecord {
	records := make([]stepRecord, 0, 1+len(s.toolOrder))
	if s.mode == ModeAgent {
		records = append(records, stepRecord{name: "model", attempts: s.modelSteps})
	}
	for _, name := range s.toolOrder {
		records = append(records, stepRecord{name: "tool." + name, attempts: s.toolCounts[name]})
	}
	return records
}

// finishFailure emits run.failed, validates the FAILED result, and flushes
// the trace. Attribution failures (e.g. a zero-attempt model record) are
// tooling errors.
func (s *runState) finishFailure(failureCode string) (*contracts.ToolLoopResult, error) {
	if err := s.emit(contracts.EventRunFailed, map[string]any{
		"status": StatusFailed, "failure_code": failureCode,
		"model_steps": s.modelSteps, "tokens_used": s.tokensUsed,
		"tool_invocations": s.toolInvocations}); err != nil {
		return nil, err
	}
	result, err := s.buildResult(StatusFailed, nil, &failureCode)
	if err != nil {
		return nil, err
	}
	if err := WriteJSONL(s.tracePath, s.sink.Events()); err != nil {
		return nil, err
	}
	return result, nil
}

// finishSuccess emits run.completed, validates the SUCCEEDED result, and
// flushes the trace.
func (s *runState) finishSuccess(answer string) (*contracts.ToolLoopResult, error) {
	if err := s.emit(contracts.EventRunCompleted, map[string]any{
		"status": StatusSucceeded, "answer": answer,
		"model_steps": s.modelSteps, "tokens_used": s.tokensUsed,
		"tool_invocations": s.toolInvocations}); err != nil {
		return nil, err
	}
	result, err := s.buildResult(StatusSucceeded, &answer, nil)
	if err != nil {
		return nil, err
	}
	if err := WriteJSONL(s.tracePath, s.sink.Events()); err != nil {
		return nil, err
	}
	return result, nil
}

// completeToolCall emits tool.requested, counts the invocation, and runs the
// tool body against its timeout; on completion it emits tool.completed with
// the observation and returns the output. The failure path (timeout or
// execution error) emits tool.failed and finishes the run with the mapped
// failure code.
func (s *runState) completeToolCall(definition ToolDefinition, callID string,
	arguments map[string]any) (map[string]any, *contracts.ToolLoopResult, error) {
	if err := s.emit(contracts.EventToolRequested, map[string]any{
		"call_id": callID, "tool": definition.Name, "arguments": arguments}); err != nil {
		return nil, nil, err
	}
	s.recordToolInvocation(definition.Name)
	output, err := InvokeTool(definition, arguments)
	if err != nil {
		var failureCode string
		var timeoutErr *ToolTimeoutError
		if errors.As(err, &timeoutErr) {
			failureCode = contracts.FailureToolTimeout
		} else {
			failureCode = contracts.FailureToolExecutionFailed
		}
		if err := s.emit(contracts.EventToolFailed, map[string]any{
			"call_id": callID, "tool": definition.Name, "failure_code": failureCode}); err != nil {
			return nil, nil, err
		}
		result, err := s.finishFailure(failureCode)
		return nil, result, err
	}
	if err := s.emit(contracts.EventToolCompleted, map[string]any{
		"call_id": callID, "tool": definition.Name,
		"observation": map[string]any{"call_id": callID, "tool": definition.Name, "output": output}}); err != nil {
		return nil, nil, err
	}
	return output, nil, nil
}

// runDirect is the direct mode path: one scripted scenario call, no model.
func (s *runState) runDirect() (*contracts.ToolLoopResult, error) {
	call := s.scenarioCase.DirectCall
	if call == nil {
		return nil, fmt.Errorf("m1: direct case %s must define a direct call", s.scenarioCase.ID)
	}
	definition, resolved := s.registry.Resolve(call.Tool)
	if !resolved {
		return s.finishFailure(contracts.FailureUnknownTool)
	}
	validation := definition.ValidateArguments(call.Arguments)
	if !validation.OK {
		return s.finishFailure(contracts.FailureInvalidToolArguments)
	}
	output, result, err := s.completeToolCall(definition, call.CallID, validation.Value)
	if err != nil || result != nil {
		return result, err
	}
	orderID, orderOK := output["order_id"].(string)
	status, statusOK := output["status"].(string)
	if !orderOK || !statusOK {
		return s.emitToolFailureAndFinish(call.CallID, definition.Name,
			&ToolExecutionError{Tool: definition.Name,
				Message: "lookup_order returned an invalid observation."})
	}
	return s.finishSuccess(fmt.Sprintf("Order %s status is %s.", orderID, status))
}

// emitToolFailureAndFinish maps the executor error to its failure code,
// emits tool.failed, and finishes the run (the direct-mode catch).
func (s *runState) emitToolFailureAndFinish(callID, toolName string, err error) (*contracts.ToolLoopResult, error) {
	var failureCode string
	var timeoutErr *ToolTimeoutError
	if errors.As(err, &timeoutErr) {
		failureCode = contracts.FailureToolTimeout
	} else {
		failureCode = contracts.FailureToolExecutionFailed
	}
	if err := s.emit(contracts.EventToolFailed, map[string]any{
		"call_id": callID, "tool": toolName, "failure_code": failureCode}); err != nil {
		return nil, err
	}
	return s.finishFailure(failureCode)
}

// runAgent is the bounded agent loop: model steps with token accounting from
// the scripted provider, budget checks that fail closed, and tool calls.
func (s *runState) runAgent() (*contracts.ToolLoopResult, error) {
	observations := []ToolObservation{}
	for {
		if s.modelSteps >= s.scenarioCase.MaxSteps {
			if err := s.emit(contracts.EventBudgetExceeded, map[string]any{
				"budget": "step", "consumed": s.modelSteps, "limit": s.scenarioCase.MaxSteps,
				"failure_code": contracts.FailureStepBudgetExceeded}); err != nil {
				return nil, err
			}
			return s.finishFailure(contracts.FailureStepBudgetExceeded)
		}

		modelStep := s.modelSteps + 1
		if err := s.emit(contracts.EventModelRequested, map[string]any{
			"case_id": s.scenarioCase.ID, "model_step": modelStep}); err != nil {
			return nil, err
		}
		s.modelSteps = modelStep

		rawTurn, err := s.provider.NextTurn(ModelInput{
			CaseID:       s.scenarioCase.ID,
			Request:      s.scenarioCase.Request,
			ModelStep:    modelStep,
			Observations: copyObservations(observations),
		})
		if err != nil {
			if err := s.emit(contracts.EventModelFailed, map[string]any{
				"case_id": s.scenarioCase.ID, "model_step": modelStep,
				"failure_code": contracts.FailureInvalidModelDecision}); err != nil {
				return nil, err
			}
			return s.finishFailure(contracts.FailureInvalidModelDecision)
		}

		turnPayload, err := decodeJSONValue(rawTurn)
		if err != nil {
			return nil, err
		}
		if err := s.emit(contracts.EventModelCompleted, map[string]any{
			"case_id": s.scenarioCase.ID, "model_step": modelStep, "turn": turnPayload}); err != nil {
			return nil, err
		}
		turn, turnErr := ValidateModelTurn(rawTurn)
		if turnErr != nil {
			return s.finishFailure(contracts.FailureInvalidModelDecision)
		}

		s.tokensUsed += turn.InputTokens + turn.OutputTokens
		if err := s.emit(contracts.EventBudgetConsumed, map[string]any{
			"model_steps": s.modelSteps, "max_steps": s.scenarioCase.MaxSteps,
			"tokens_used": s.tokensUsed, "max_tokens": s.scenarioCase.MaxTokens}); err != nil {
			return nil, err
		}

		if s.tokensUsed > s.scenarioCase.MaxTokens {
			if err := s.emit(contracts.EventBudgetExceeded, map[string]any{
				"budget": "token", "consumed": s.tokensUsed, "limit": s.scenarioCase.MaxTokens,
				"failure_code": contracts.FailureTokenBudgetExceeded}); err != nil {
				return nil, err
			}
			return s.finishFailure(contracts.FailureTokenBudgetExceeded)
		}

		if turn.Decision.Kind == DecisionFinal {
			return s.finishSuccess(turn.Decision.Answer)
		}

		definition, resolved := s.registry.Resolve(turn.Decision.Tool)
		if !resolved {
			return s.finishFailure(contracts.FailureUnknownTool)
		}
		validation := definition.ValidateArguments(turn.Decision.Arguments)
		if !validation.OK {
			return s.finishFailure(contracts.FailureInvalidToolArguments)
		}

		if s.modelSteps >= s.scenarioCase.MaxSteps {
			if err := s.emit(contracts.EventBudgetExceeded, map[string]any{
				"budget": "step", "consumed": s.modelSteps, "limit": s.scenarioCase.MaxSteps,
				"failure_code": contracts.FailureStepBudgetExceeded}); err != nil {
				return nil, err
			}
			return s.finishFailure(contracts.FailureStepBudgetExceeded)
		}

		output, result, err := s.completeToolCall(definition, turn.Decision.CallID, validation.Value)
		if err != nil || result != nil {
			return result, err
		}
		observations = append(observations, ToolObservation{
			CallID: turn.Decision.CallID, Tool: definition.Name, Output: output})
	}
}

// decodeJSONValue re-decodes a raw turn for the model.completed payload.
func decodeJSONValue(raw json.RawMessage) (any, error) {
	var value any
	if err := json.Unmarshal(raw, &value); err != nil {
		return nil, fmt.Errorf("m1: scripted turn is not JSON: %w", err)
	}
	return value, nil
}

// copyObservations isolates the observations handed to the provider
// (mirroring the TS/Py structuredClone boundary).
func copyObservations(observations []ToolObservation) []ToolObservation {
	copied := make([]ToolObservation, 0, len(observations))
	for _, observation := range observations {
		copied = append(copied, ToolObservation{
			CallID: observation.CallID, Tool: observation.Tool,
			Output: deepCopyMap(observation.Output)})
	}
	return copied
}
