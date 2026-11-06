package m4

import (
	"errors"
	"fmt"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// stepRecord is one attribution entry (name + attempts). Attempts count
// real invocations across phases: a worker restored as RUNNING was invoked
// in the crashed phase and re-executed in the resuming phase, so it counts
// two attempts; PENDING/CANCELLED workers restored without invocation count
// one.
type stepRecord struct {
	name     string
	attempts int
}

// stepKind maps the attributed step name to its price kind.
func stepKind(stepName string) (string, error) {
	if stepName == "synthesize" {
		return "synthesis", nil
	}
	if len(stepName) > len("worker.") && stepName[:len("worker.")] == "worker." {
		return "read", nil
	}
	return "", fmt.Errorf("m4: unknown attribution step: %s", stepName)
}

// BuildAttribution assembles the attribution block: fixture-priced latency
// (table x attempts), fixture-priced cost (kind price x attempts), and the
// attempt sums. At least one executed step is required.
func BuildAttribution(records []stepRecord, tables AttributionTables) (contracts.Attribution, error) {
	steps := make([]contracts.StepAttribution, 0, len(records))
	totals := contracts.Totals{}
	for _, record := range records {
		if record.attempts < 1 {
			return contracts.Attribution{}, fmt.Errorf("m4: invalid attribution attempts for %s", record.name)
		}
		latency, ok := tables.LatencyMS[record.name]
		if !ok {
			return contracts.Attribution{}, fmt.Errorf("m4: unknown attribution step: %s", record.name)
		}
		kind, err := stepKind(record.name)
		if err != nil {
			return contracts.Attribution{}, err
		}
		price, ok := tables.PriceTable[kind]
		if !ok {
			return contracts.Attribution{}, fmt.Errorf("m4: unknown attribution price kind: %s", kind)
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
		return contracts.Attribution{}, errors.New("m4: attribution requires at least one executed step")
	}
	return contracts.Attribution{Steps: steps, Totals: totals}, nil
}

// workerRecords attributes every executed worker in canonical outcome order.
func workerRecords(outcomes []WorkerOutcome, reexecuted map[string]bool) []stepRecord {
	records := make([]stepRecord, 0, len(outcomes))
	for _, outcome := range outcomes {
		attempts := 1
		if reexecuted[outcome.WorkerID] {
			attempts = 2
		}
		records = append(records, stepRecord{name: "worker." + outcome.WorkerID, attempts: attempts})
	}
	return records
}

// restoredRunning collects the workers whose loaded step was still RUNNING:
// they were invoked in the crashed phase and re-execute exactly once on
// resume.
func restoredRunning(document RunStateDocument) map[string]bool {
	reexecuted := map[string]bool{}
	for _, step := range document.Steps {
		if step.Status == StepStatusRunning {
			reexecuted[step.WorkerID] = true
		}
	}
	return reexecuted
}
