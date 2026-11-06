// The naive teaching mode: the same Eino topology with no executor, no
// taxonomy, and no validation - the M3 lesson's regression baseline. It
// demonstrates what the framework's unbounded parallel dispatch plus
// default error propagation do on their own:
//
//   - a 3-way rendezvous records peak_concurrency 3 (outside the closed
//     schema's 1..2 bound) because Eino dispatches every ready node in its
//     own goroutine;
//   - a declared worker failure propagates as a node error and fails the
//     whole run (the trace prefix is still flushed);
//   - an invalid worker output is published as a SUCCEEDED fact and only
//     the closed validator - run after the fact by the proving tests -
//     rejects it.
package mapping

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"github.com/cloudwego/eino/compose"

	"boundrelay-m3-eino/internal/attribution"
	"boundrelay-m3-eino/internal/fixtures"
	"boundrelay-m3-eino/internal/results"
)

// NaiveGuardMS bounds the naive rendezvous wait.
const NaiveGuardMS = 30_000

// NaiveOptions configures one naive order-brief run.
type NaiveOptions struct {
	CaseID    string
	TracePath string
	RunID     string
	RepoRoot  string
}

// naiveRendezvous is the deterministic 3-way overlap probe: every worker
// holds its slot until all three are concurrently inside.
type naiveRendezvous struct {
	mu         sync.Mutex
	broadcast  chan struct{}
	concurrent int
	peak       int
}

func newNaiveRendezvous() *naiveRendezvous {
	return &naiveRendezvous{broadcast: make(chan struct{})}
}

// Enter records the worker's arrival and blocks until all three workers are
// concurrently inside (or the guard trips), proving peak 3.
func (r *naiveRendezvous) Enter(ctx context.Context) error {
	r.mu.Lock()
	r.concurrent++
	if r.concurrent > r.peak {
		r.peak = r.concurrent
	}
	full := r.concurrent >= 3
	subscription := r.broadcast
	r.mu.Unlock()
	if full {
		r.wake()
		return nil
	}
	timer := time.NewTimer(NaiveGuardMS * time.Millisecond)
	defer timer.Stop()
	select {
	case <-subscription:
		return nil
	case <-timer.C:
		return fmt.Errorf("%w: naive rendezvous guard tripped", ErrToolingInterrupted)
	case <-ctx.Done():
		return fmt.Errorf("%w: naive rendezvous canceled: %v", ErrToolingInterrupted, ctx.Err())
	}
}

// Exit releases the worker's slot.
func (r *naiveRendezvous) Exit() {
	r.mu.Lock()
	r.concurrent--
	r.mu.Unlock()
	r.wake()
}

// Peak returns the observed peak concurrency.
func (r *naiveRendezvous) Peak() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.peak
}

func (r *naiveRendezvous) wake() {
	r.mu.Lock()
	close(r.broadcast)
	r.broadcast = make(chan struct{})
	r.mu.Unlock()
}

// RunNaive executes one naive order-brief run: uncapped dispatch, default
// propagation, unvalidated publication.
func RunNaive(ctx context.Context, options NaiveOptions) (RunReport, error) {
	repoRoot := options.RepoRoot
	if repoRoot == "" {
		discovered, err := fixtures.FindRepoRoot()
		if err != nil {
			return RunReport{}, err
		}
		repoRoot = discovered
	}
	scenario, err := fixtures.LoadScenario(
		fixtures.DefaultScenarioPath(repoRoot), fixtures.DefaultWorkersPath(repoRoot))
	if err != nil {
		return RunReport{}, err
	}
	spec, err := scenario.FindCase(options.CaseID)
	if err != nil {
		return RunReport{}, err
	}
	if options.TracePath == "" {
		return RunReport{}, fmt.Errorf("mapping: trace path is required")
	}
	workerFixtures, err := fixtures.LoadWorkerFixtures(fixtures.DefaultWorkersPath(repoRoot))
	if err != nil {
		return RunReport{}, err
	}
	instructions, ok := workerFixtures[spec.WorkerFixture]
	if !ok {
		return RunReport{}, fmt.Errorf("mapping: case %q worker fixture %s not resolved", spec.CaseID, spec.WorkerFixture)
	}
	runID := options.RunID
	if runID == "" {
		runID = newUUID()
	}
	kit := &naiveKit{
		spec: spec, instructions: instructions, orderID: scenario.OrderID,
		tables: scenario.Attribution, runID: runID, tracePath: options.TracePath,
		rendezvous: newNaiveRendezvous(), synthesisCalls: &atomic.Int64{},
	}
	return runNaiveGraph(ctx, kit)
}

type naiveKit struct {
	spec           fixtures.CaseSpec
	instructions   fixtures.WorkerInstructions
	orderID        string
	tables         fixtures.AttributionTables
	runID          string
	tracePath      string
	rendezvous     *naiveRendezvous
	synthesisCalls *atomic.Int64
}

// buildNaiveGraph assembles the naive graph: identical topology, no
// admission cap, no taxonomy, no validation.
func buildNaiveGraph(kit *naiveKit) (*compose.Graph[map[string]any, map[string]any], error) {
	graph := compose.NewGraph[map[string]any, map[string]any]()
	for _, workerID := range fixtures.CanonicalWorkerIDs {
		id := workerID
		node := func(ctx context.Context, _ map[string]any) (map[string]any, error) {
			if err := kit.rendezvous.Enter(ctx); err != nil {
				return nil, err
			}
			defer kit.rendezvous.Exit()
			instruction := kit.instructions[id]
			if instruction.Operation == "raise" {
				// Default propagation: the declared failure escapes the node
				// and fails the whole run.
				return nil, errors.New("naive: declared worker failure: " + id)
			}
			// Unvalidated publication: the raw return is published as a
			// SUCCEEDED fact whatever it contains.
			return map[string]any{"worker." + id: results.WorkerOutcome{
				WorkerID: id, Status: "SUCCEEDED",
				Output: append(json.RawMessage(nil), instruction.Output...)}}, nil
		}
		if err := graph.AddLambdaNode("worker."+id, compose.InvokableLambda(node), compose.WithNodeName("worker."+id)); err != nil {
			return nil, err
		}
	}
	collect := func(ctx context.Context, input map[string]any) (map[string]any, error) {
		outcomes := make([]results.WorkerOutcome, 0, 3)
		for _, id := range fixtures.CanonicalWorkerIDs {
			outcome, ok := input["worker."+id].(results.WorkerOutcome)
			if !ok {
				return nil, fmt.Errorf("mapping: naive collector misses the %s outcome", id)
			}
			outcomes = append(outcomes, outcome)
		}
		successes := 0
		for _, outcome := range outcomes {
			if outcome.Status == "SUCCEEDED" {
				successes++
			}
		}
		return map[string]any{"outcomes": outcomes, "successes": successes}, nil
	}
	if err := graph.AddLambdaNode("collect", compose.InvokableLambda(collect), compose.WithNodeName("collect")); err != nil {
		return nil, err
	}
	synthesize := func(ctx context.Context, input map[string]any) (map[string]any, error) {
		outcomes, _ := input["outcomes"].([]results.WorkerOutcome)
		kit.synthesisCalls.Add(1)
		brief, err := results.SynthesizeBrief(kit.orderID, outcomes)
		if err != nil {
			return nil, err
		}
		return map[string]any{"outcomes": outcomes, "brief": brief}, nil
	}
	if err := graph.AddLambdaNode("synthesize", compose.InvokableLambda(synthesize), compose.WithNodeName("synthesize")); err != nil {
		return nil, err
	}
	finalize := func(ctx context.Context, input map[string]any) (map[string]any, error) {
		outcomes, _ := input["outcomes"].([]results.WorkerOutcome)
		brief, _ := input["brief"].(results.Brief)
		synthesisInvoked := input["brief"] != nil
		briefPointer := &brief
		if !synthesisInvoked {
			briefPointer = nil
		}
		blocks, err := attribution.Build(synthesisInvoked, kit.tables)
		if err != nil {
			return nil, err
		}
		// No structural validation: the naive result is published as-is,
		// peak 3 included.
		status, failureCode := results.RunStatus(countSuccesses(outcomes))
		limit := 1
		if kit.spec.ExecutionMode == fixtures.ModeParallel {
			limit = 2
		}
		return map[string]any{"result": results.RunResult{
			SchemaVersion: "1.0", RunID: kit.runID, ScenarioID: "order-brief",
			CaseID: kit.spec.CaseID, ExecutionMode: kit.spec.ExecutionMode,
			ConcurrencyLimit: limit, PeakConcurrency: kit.rendezvous.Peak(),
			OrderID: kit.orderID, Status: status, WorkerOutcomes: outcomes,
			SynthesisInvoked: synthesisInvoked, Brief: briefPointer,
			FailureCode: failureCode, TracePath: kit.tracePath, Attribution: blocks,
		}}, nil
	}
	if err := graph.AddLambdaNode("finalize", compose.InvokableLambda(finalize), compose.WithNodeName("finalize")); err != nil {
		return nil, err
	}
	// The synthesis gate is registered after every node exists (Eino
	// requires branch end nodes to be added first).
	branch := compose.NewGraphBranch(func(ctx context.Context, input map[string]any) (string, error) {
		successes, _ := input["successes"].(int)
		if successes > 0 {
			return "synthesize", nil
		}
		return "finalize", nil
	}, map[string]bool{"synthesize": true, "finalize": true})
	if err := graph.AddBranch("collect", branch); err != nil {
		return nil, err
	}
	for _, id := range fixtures.CanonicalWorkerIDs {
		if err := graph.AddEdge(compose.START, "worker."+id); err != nil {
			return nil, err
		}
		if err := graph.AddEdge("worker."+id, "collect"); err != nil {
			return nil, err
		}
	}
	if err := graph.AddEdge("synthesize", "finalize"); err != nil {
		return nil, err
	}
	if err := graph.AddEdge("finalize", compose.END); err != nil {
		return nil, err
	}
	return graph, nil
}

func countSuccesses(outcomes []results.WorkerOutcome) int {
	successes := 0
	for _, outcome := range outcomes {
		if outcome.Status == "SUCCEEDED" {
			successes++
		}
	}
	return successes
}

func runNaiveGraph(ctx context.Context, kit *naiveKit) (RunReport, error) {
	graph, err := buildNaiveGraph(kit)
	if err != nil {
		return RunReport{}, err
	}
	runnable, err := graph.Compile(ctx, compose.WithNodeTriggerMode(compose.AnyPredecessor), compose.WithGraphName("order-brief-eino-naive"))
	if err != nil {
		return RunReport{}, fmt.Errorf("mapping: compile naive graph: %w", err)
	}
	trace, err := newTraceWriter(kit.tracePath)
	if err != nil {
		return RunReport{}, err
	}
	defer trace.close()
	runCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	output, err := runnable.Invoke(runCtx, map[string]any{
		"case_id": kit.spec.CaseID, "order_id": kit.orderID,
		"execution_mode": kit.spec.ExecutionMode}, compose.WithCallbacks(callbacksTraceHandler(trace)))
	if err != nil {
		return RunReport{}, fmt.Errorf("mapping: naive run failed: %w", err)
	}
	result, ok := output["result"].(results.RunResult)
	if !ok {
		return RunReport{}, fmt.Errorf("mapping: naive run produced no publishable result")
	}
	return RunReport{Result: result}, nil
}
