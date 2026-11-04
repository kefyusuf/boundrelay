package m0

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestScriptedDecisionProvider(t *testing.T) {
	// Pins the scripted turns mirrored from fixtures/fake-model/support-triage.yaml.
	want := map[string]map[string]any{
		"billing-duplicate-charge": {"route": "billing", "confidence": 0.98},
		"technical-login-error":    {"route": "technical", "confidence": 0.97},
		"general-opening-hours":    {"route": "general", "confidence": 0.94},
		"invalid-model-route":      {"route": "unknown-specialist", "confidence": 0.99},
	}
	provider := NewScriptedDecisionProvider()
	for caseID, expected := range want {
		raw, err := provider.Classify(caseID, "request is ignored")
		if err != nil {
			t.Fatalf("Classify(%s): %v", caseID, err)
		}
		var got map[string]any
		if err := json.Unmarshal(raw, &got); err != nil {
			t.Fatalf("Classify(%s) returned non-JSON: %v", caseID, err)
		}
		for key, value := range expected {
			if got[key] != value {
				t.Fatalf("Classify(%s)[%s] = %v, want %v", caseID, key, got[key], value)
			}
		}
		if len(got) != len(expected) {
			t.Fatalf("Classify(%s) has extra fields: %v", caseID, got)
		}
	}
}

func TestScriptedDecisionProviderUnknownCase(t *testing.T) {
	provider := NewScriptedDecisionProvider()
	_, err := provider.Classify("missing-case", "ignored")
	if err == nil || !strings.Contains(err.Error(), "missing scripted decision") {
		t.Fatalf("expected missing-scripted-decision error, got %v", err)
	}
}

func TestScriptedDecisionProviderCoversScenarioCases(t *testing.T) {
	root, err := FindRepoRoot()
	if err != nil {
		t.Fatalf("repo root: %v", err)
	}
	scenario, err := LoadScenario(DefaultScenarioPath(root))
	if err != nil {
		t.Fatalf("LoadScenario: %v", err)
	}
	provider := NewScriptedDecisionProvider()
	for _, scenarioCase := range scenario.Cases {
		if _, err := provider.Classify(scenarioCase.ID, scenarioCase.Request); err != nil {
			t.Fatalf("scripted turns must cover scenario case %s: %v", scenarioCase.ID, err)
		}
	}
}
