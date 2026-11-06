package m4

import (
	"encoding/json"
	"fmt"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

// SynthesizeBrief assembles the order brief from the canonical outcomes:
// sections carry the successful outputs in canonical order, missing_workers
// the failed identities. Synthesis without successful evidence is an error
// (the runner never calls it on all-failed runs).
func SynthesizeBrief(orderID string, outcomes [3]WorkerOutcome) (contracts.Brief, error) {
	brief := contracts.Brief{
		OrderID:        orderID,
		Sections:       []contracts.BriefSection{},
		MissingWorkers: []string{},
	}
	for _, outcome := range outcomes {
		if outcome.Status == StatusSucceeded {
			brief.Sections = append(brief.Sections, contracts.BriefSection{
				WorkerID: outcome.WorkerID,
				Output:   append(json.RawMessage(nil), outcome.Output...),
			})
			continue
		}
		brief.MissingWorkers = append(brief.MissingWorkers, outcome.WorkerID)
	}
	if len(brief.Sections) == 0 {
		return contracts.Brief{}, fmt.Errorf("m4: cannot synthesize without successful evidence")
	}
	brief.Complete = len(brief.MissingWorkers) == 0
	return brief, nil
}
