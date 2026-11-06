// Package attribution assembles the M6 attribution block from the
// scenario's fixture-priced tables: worker.<id> records for every executed
// worker plus synthesize when invoked (read/synthesis kinds price zero;
// latency = table x attempts; totals sum).
package attribution

import (
	"fmt"

	"boundrelay-m3-eino/internal/fixtures"
	"boundrelay-m3-eino/internal/results"
)

// Build assembles the attribution block for one run: one attempt per
// executed worker step, plus synthesize when synthesis was invoked. Steps
// follow the canonical worker order, then synthesize.
func Build(synthesisInvoked bool, tables fixtures.AttributionTables) (results.Attribution, error) {
	names := make([]string, 0, 4)
	for _, id := range fixtures.CanonicalWorkerIDs {
		names = append(names, "worker."+id)
	}
	if synthesisInvoked {
		names = append(names, "synthesize")
	}
	steps := make([]results.StepAttribution, 0, len(names))
	totals := results.Totals{}
	for _, name := range names {
		latency, ok := tables.LatencyMS[name]
		if !ok {
			return results.Attribution{}, fmt.Errorf("attribution: latency table misses step %q", name)
		}
		kind := "read"
		if name == "synthesize" {
			kind = "synthesis"
		}
		price, ok := tables.PriceTable[kind]
		if !ok {
			return results.Attribution{}, fmt.Errorf("attribution: price table misses kind %q", kind)
		}
		step := results.StepAttribution{StepName: name, LatencyMS: latency,
			CostCents: price, Attempts: 1}
		steps = append(steps, step)
		totals.LatencyMS += step.LatencyMS
		totals.CostCents += step.CostCents
		totals.Attempts += step.Attempts
	}
	return results.Attribution{Steps: steps, Totals: totals}, nil
}
