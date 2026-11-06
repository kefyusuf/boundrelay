package m5

import (
	"errors"
	"fmt"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// stepRecord is one attribution entry (name + attempts). Attempts count the
// invocation of record per step: one per recorded worker read, and one for
// the effect submission when an effect of record exists (landed or adopted
// — adoption counts the original attempt). A rejected approval never
// submits, so the effect step has no record at all.
type stepRecord struct {
	name     string
	attempts int
}

// stepKind maps the attributed step name to its price kind.
func stepKind(stepName string) (string, error) {
	if stepName == "effect.submit" {
		return "effect", nil
	}
	if len(stepName) > len("worker.") && stepName[:len("worker.")] == "worker." {
		return "read", nil
	}
	return "", fmt.Errorf("m5: unknown attribution step: %s", stepName)
}

// BuildAttribution assembles the attribution block: fixture-priced latency
// (table x attempts), fixture-priced cost (kind price x attempts), and the
// attempt sums. At least one executed step is required.
func BuildAttribution(records []stepRecord, tables AttributionTables) (contracts.Attribution, error) {
	steps := make([]contracts.StepAttribution, 0, len(records))
	totals := contracts.Totals{}
	for _, record := range records {
		if record.attempts < 1 {
			return contracts.Attribution{}, fmt.Errorf("m5: invalid attribution attempts for %s", record.name)
		}
		latency, ok := tables.LatencyMS[record.name]
		if !ok {
			return contracts.Attribution{}, fmt.Errorf("m5: unknown attribution step: %s", record.name)
		}
		kind, err := stepKind(record.name)
		if err != nil {
			return contracts.Attribution{}, err
		}
		price, ok := tables.PriceTable[kind]
		if !ok {
			return contracts.Attribution{}, fmt.Errorf("m5: unknown attribution price kind: %s", kind)
		}
		step := contracts.StepAttribution{StepName: record.name,
			LatencyMS: latency * record.attempts, CostCents: price * record.attempts,
			Attempts: record.attempts}
		steps = append(steps, step)
		totals.LatencyMS += step.LatencyMS
		totals.CostCents += step.CostCents
		totals.Attempts += step.Attempts
	}
	if len(steps) == 0 {
		return contracts.Attribution{}, errors.New("m5: attribution requires at least one executed step")
	}
	return contracts.Attribution{Steps: steps, Totals: totals}, nil
}

// effectRecords attributes the effect submission when an effect of record
// exists (a nonempty idempotency key).
func effectRecords(key string) []stepRecord {
	if key == "" {
		return nil
	}
	return []stepRecord{{name: "effect.submit", attempts: 1}}
}

// workerRecords attributes every recorded worker read in canonical order.
func workerRecords(outcomes []WorkerOutcome) []stepRecord {
	records := make([]stepRecord, 0, len(outcomes))
	for _, outcome := range outcomes {
		records = append(records, stepRecord{name: "worker." + outcome.WorkerID, attempts: 1})
	}
	return records
}
