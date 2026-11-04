package contracts

// StepAttribution is one attributed step: fixture-priced deterministic
// values, never wall-clock measurements (attribution.schema.json).
type StepAttribution struct {
	StepName  string `json:"step_name"`
	LatencyMS int    `json:"latency_ms"`
	CostCents int    `json:"cost_cents"`
	Attempts  int    `json:"attempts"`
}

// Totals aggregates every step's attribution for the run.
type Totals struct {
	LatencyMS int `json:"latency_ms"`
	CostCents int `json:"cost_cents"`
	Attempts  int `json:"attempts"`
}

// Attribution is the required M6 attribution block embedded in every run
// result; the fixture tables come from the checked-in JSON projections.
type Attribution struct {
	Steps  []StepAttribution `json:"steps"`
	Totals Totals            `json:"totals"`
}
