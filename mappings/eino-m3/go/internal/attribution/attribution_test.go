package attribution

import (
	"reflect"
	"testing"

	"boundrelay-m3-eino/internal/fixtures"
	"boundrelay-m3-eino/internal/results"
)

var tables = fixtures.AttributionTables{
	LatencyMS: map[string]int{
		"worker.order-details": 10, "worker.payment-status": 11,
		"worker.delivery-status": 12, "synthesize": 15,
	},
	PriceTable: map[string]int{"read": 0, "synthesis": 0},
}

func TestBuildWithSynthesis(t *testing.T) {
	blocks, err := Build(true, tables)
	if err != nil {
		t.Fatalf("build: %v", err)
	}
	want := []struct {
		name      string
		latencyMS int
	}{
		{"worker.order-details", 10}, {"worker.payment-status", 11},
		{"worker.delivery-status", 12}, {"synthesize", 15},
	}
	if len(blocks.Steps) != 4 {
		t.Fatalf("expected four steps, got %d", len(blocks.Steps))
	}
	for i, step := range want {
		got := blocks.Steps[i]
		if got.StepName != step.name || got.LatencyMS != step.latencyMS || got.CostCents != 0 || got.Attempts != 1 {
			t.Fatalf("step %d = %+v, want %s/%d/0/1", i, got, step.name, step.latencyMS)
		}
	}
	if !reflect.DeepEqual(blocks.Totals, results.Totals{LatencyMS: 48, CostCents: 0, Attempts: 4}) {
		t.Fatalf("totals = %+v, want 48/0/4", blocks.Totals)
	}
}

func TestBuildWithoutSynthesis(t *testing.T) {
	blocks, err := Build(false, tables)
	if err != nil {
		t.Fatalf("build: %v", err)
	}
	if len(blocks.Steps) != 3 || blocks.Totals.LatencyMS != 33 || blocks.Totals.Attempts != 3 {
		t.Fatalf("all-failed attribution = %+v", blocks)
	}
	for _, step := range blocks.Steps {
		if step.StepName == "synthesize" {
			t.Fatal("synthesize step present without synthesis")
		}
	}
}

func TestBuildRejectsMissingTableEntries(t *testing.T) {
	if _, err := Build(true, fixtures.AttributionTables{
		LatencyMS: map[string]int{"worker.order-details": 10}, PriceTable: map[string]int{"read": 0}}); err == nil {
		t.Fatal("missing table entries accepted")
	}
}
