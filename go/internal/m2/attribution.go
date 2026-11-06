package m2

import (
	"fmt"
	"strings"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// stepRecord is one attributed step with its attempt count.
type stepRecord struct {
	name     string
	attempts int
}

// stepKind maps step names to price kinds (M6 attribution Ruling 5: the
// classify step prices as model_decision in model mode and as route in code
// mode; receiver.<name> dispatch steps price as handoff).
func stepKind(stepName string, mode string) (string, error) {
	if stepName == "classify" {
		if mode == ModeModel {
			return "model_decision", nil
		}
		return "route", nil
	}
	if strings.HasPrefix(stepName, "receiver.") {
		return "handoff", nil
	}
	return "", fmt.Errorf("Unknown attribution step: %s", stepName)
}

// buildAttribution assembles the attribution block from the fixture tables:
// latency is table*attempts, cost is price-kind*attempts, totals sum every
// record, and at least one record is required.
func buildAttribution(records []stepRecord, tables AttributionTables, mode string) (contracts.Attribution, error) {
	steps := make([]contracts.StepAttribution, 0, len(records))
	totals := contracts.Totals{}
	for _, record := range records {
		if record.attempts < 1 {
			return contracts.Attribution{}, fmt.Errorf("Invalid attribution attempts for %s", record.name)
		}
		latency, ok := tables.LatencyMS[record.name]
		if !ok {
			return contracts.Attribution{}, fmt.Errorf("Unknown attribution step: %s", record.name)
		}
		kind, err := stepKind(record.name, mode)
		if err != nil {
			return contracts.Attribution{}, err
		}
		price, ok := tables.PriceTable[kind]
		if !ok {
			return contracts.Attribution{}, fmt.Errorf("Unknown attribution price kind: %s", kind)
		}
		step := contracts.StepAttribution{
			StepName:  record.name,
			LatencyMS: latency * record.attempts,
			CostCents: price * record.attempts,
			Attempts:  record.attempts,
		}
		steps = append(steps, step)
		totals.LatencyMS += step.LatencyMS
		totals.CostCents += step.CostCents
		totals.Attempts += step.Attempts
	}
	if len(steps) == 0 {
		return contracts.Attribution{}, fmt.Errorf("Attribution requires at least one executed step")
	}
	return contracts.Attribution{Steps: steps, Totals: totals}, nil
}
