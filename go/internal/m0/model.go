package m0

import (
	"encoding/json"
	"fmt"
)

// DecisionProvider classifies a case request into a raw decision payload.
type DecisionProvider interface {
	Classify(caseID string, request string) (json.RawMessage, error)
}

// scriptedResponses mirrors fixtures/fake-model/support-triage.yaml. Go
// reads no YAML (M7 exclusion), and the fixture cannot join the generated
// projections until the generator change is committed, so the scripted
// turns are pinned here and in TestScriptedDecisionProvider. The
// invalid-model-route case intentionally returns an unsupported route so
// model mode exercises the INVALID_ROUTE_DECISION path.
var scriptedResponses = map[string]string{
	"billing-duplicate-charge": `{"route":"billing","confidence":0.98}`,
	"technical-login-error":    `{"route":"technical","confidence":0.97}`,
	"general-opening-hours":    `{"route":"general","confidence":0.94}`,
	"invalid-model-route":      `{"route":"unknown-specialist","confidence":0.99}`,
}

// ScriptedDecisionProvider is the deterministic, offline fake model used in
// model mode: one scripted decision per scenario case.
type ScriptedDecisionProvider struct {
	responses map[string]json.RawMessage
}

// NewScriptedDecisionProvider returns the provider carrying the scripted
// turns for every canonical support-triage case.
func NewScriptedDecisionProvider() *ScriptedDecisionProvider {
	responses := make(map[string]json.RawMessage, len(scriptedResponses))
	for caseID, decision := range scriptedResponses {
		responses[caseID] = json.RawMessage(decision)
	}
	return &ScriptedDecisionProvider{responses: responses}
}

// Classify returns the scripted decision for the case; the request text is
// ignored exactly like the TS/Python fakes.
func (p *ScriptedDecisionProvider) Classify(caseID string, request string) (json.RawMessage, error) {
	_ = request
	decision, ok := p.responses[caseID]
	if !ok {
		return nil, fmt.Errorf("m0: missing scripted decision for case: %s", caseID)
	}
	return json.RawMessage(append([]byte(nil), decision...)), nil
}
