// Package mapping rebuilds the M3 bounded fan-out/fan-in on Eino
// (github.com/cloudwego/eino v0.9.22): three deterministic worker nodes in
// parallel graph branches, a collector node as the fan-in gate, a
// framework-native conditional branch gating synthesis, and a finalize node
// assembling the validated result.
//
// Topology (one compiled graph per case run, DAG trigger mode):
//
//	START -> worker.order-details   -.
//	START -> worker.payment-status   -+-> collect -> branch -(< 1 success)- finalize -> END
//	START -> worker.delivery-status  -'                       '-(>= 1 success)-> synthesize -^
//
// Each worker node wraps a scripted worker: the BoundedExecutor
// re-establishes the 1/2-slot admission cap inside the node (Eino's
// parallel-branch dispatch is unbounded - the centerpiece finding), the
// M3 failure taxonomy is preserved inside the node (declared error ->
// WORKER_EXECUTION_FAILED, invalid return -> INVALID_WORKER_OUTPUT,
// validated before publication), and each worker publishes under its own
// key so the collector's map fan-in merges them for canonical reordering.
// The synthesize node is reachable only through the branch, so synthesis is
// invoked at most once, exactly when at least one worker succeeded.
package mapping

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"

	"github.com/cloudwego/eino/callbacks"
	"github.com/cloudwego/eino/compose"

	"boundrelay-m3-eino/internal/attribution"
	"boundrelay-m3-eino/internal/fixtures"
	"boundrelay-m3-eino/internal/results"
)

// RunOptions configures one corrected order-brief run.
type RunOptions struct {
	CaseID    string
	TracePath string
	RunID     string
	RepoRoot  string
	GuardMS   int
}

// RunReport carries the validated result.
type RunReport struct {
	Result results.RunResult
}

// runKit carries one case run's resolved inputs and instrumentation.
type runKit struct {
	spec           fixtures.CaseSpec
	instructions   fixtures.WorkerInstructions
	orderID        string
	tables         fixtures.AttributionTables
	executor       *BoundedExecutor
	runID          string
	tracePath      string
	synthesisCalls *atomic.Int64
}

// RunCase executes one corrected order-brief run through the Eino graph:
// bounded fan-out with scripted completion order, canonical fan-in,
// branch-gated single synthesis, attribution, and structural validation
// before publication. The Eino callback stream is written to the trace file
// while the run executes; a failed run leaves a flushed, inspectable prefix.
func RunCase(ctx context.Context, options RunOptions) (RunReport, error) {
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
	executor, err := NewBoundedExecutor(spec.CompletionOrder, spec.Limit(), options.GuardMS)
	if err != nil {
		return RunReport{}, err
	}
	runID := options.RunID
	if runID == "" {
		runID = newUUID()
	}
	kit := &runKit{
		spec: spec, instructions: instructions, orderID: scenario.OrderID,
		tables: scenario.Attribution, executor: executor, runID: runID,
		tracePath: options.TracePath, synthesisCalls: &atomic.Int64{},
	}
	return runGraph(ctx, kit)
}

// workerOutcome preserves the taxonomy INSIDE the node: declared error ->
// FAILED/WORKER_EXECUTION_FAILED; invalid return -> FAILED/
// INVALID_WORKER_OUTPUT (validated before publication); only unexpected
// implementation errors escape the node.
func workerOutcome(workerID string, instruction fixtures.WorkerInstruction, orderID string) (results.WorkerOutcome, error) {
	if instruction.Operation == "raise" {
		return results.WorkerOutcome{WorkerID: workerID, Status: "FAILED",
			FailureCode: strPtr(results.FailureWorkerExecutionFailed)}, nil
	}
	if results.ValidateWorkerOutput(workerID, instruction.Output, orderID) {
		return results.WorkerOutcome{WorkerID: workerID, Status: "SUCCEEDED",
			Output: append(json.RawMessage(nil), instruction.Output...)}, nil
	}
	return results.WorkerOutcome{WorkerID: workerID, Status: "FAILED",
		FailureCode: strPtr(results.FailureInvalidWorkerOutput)}, nil
}

func strPtr(value string) *string { return &value }

// buildGraph assembles the corrected Eino graph for one case run.
func buildGraph(kit *runKit) (*compose.Graph[map[string]any, map[string]any], error) {
	graph := compose.NewGraph[map[string]any, map[string]any]()

	// Worker nodes: the three scripted workers as parallel branches. Eino
	// dispatches all three at once (unbounded); the executor wrapper caps
	// admission at the case limit inside the nodes.
	for _, workerID := range fixtures.CanonicalWorkerIDs {
		id := workerID
		node := func(ctx context.Context, _ map[string]any) (map[string]any, error) {
			if err := kit.executor.Enter(ctx, id); err != nil {
				return nil, err
			}
			if err := kit.executor.AwaitRelease(ctx, id); err != nil {
				return nil, err
			}
			outcome, err := workerOutcome(id, kit.instructions[id], kit.orderID)
			if err != nil {
				kit.executor.Abandon(id)
				return nil, err
			}
			if err := kit.executor.Record(id); err != nil {
				return nil, err
			}
			return map[string]any{"worker." + id: outcome}, nil
		}
		if err := graph.AddLambdaNode("worker."+id, compose.InvokableLambda(node), compose.WithNodeName("worker."+id)); err != nil {
			return nil, err
		}
	}

	// Collector node: the fan-in gate. Eino merges the three branch outputs
	// into one map[string]any keyed by the workers' publish keys; the
	// collector reorders them into the canonical worker order and re-checks
	// the closed shapes.
	collect := func(ctx context.Context, input map[string]any) (map[string]any, error) {
		raw := make([]results.WorkerOutcome, 0, 3)
		for _, id := range fixtures.CanonicalWorkerIDs {
			outcome, ok := input["worker."+id].(results.WorkerOutcome)
			if !ok {
				return nil, fmt.Errorf("mapping: collector misses the %s outcome", id)
			}
			raw = append(raw, outcome)
		}
		canonical, err := results.CanonicalizeOutcomes(raw, kit.orderID)
		if err != nil {
			return nil, err
		}
		outcomes := canonical[:]
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

	// Synthesize node: the only synthesis caller. Its output carries the
	// outcomes through so finalize always reads one map.
	synthesize := func(ctx context.Context, input map[string]any) (map[string]any, error) {
		outcomes, ok := input["outcomes"].([]results.WorkerOutcome)
		if !ok {
			return nil, fmt.Errorf("mapping: synthesizer received no outcomes")
		}
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

	// Finalize node: attribution, result assembly, structural validation
	// before publication. Single synthesis invocation is structural: the
	// brief arrives only through the branch.
	finalize := func(ctx context.Context, input map[string]any) (map[string]any, error) {
		outcomes, ok := input["outcomes"].([]results.WorkerOutcome)
		if !ok {
			return nil, fmt.Errorf("mapping: finalize received no outcomes")
		}
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
		result, err := results.AssembleResult(struct {
			RunID            string
			TracePath        string
			CaseID           string
			ExecutionMode    string
			OrderID          string
			PeakConcurrency  int
			Outcomes         []results.WorkerOutcome
			Brief            *results.Brief
			SynthesisInvoked bool
			Attribution      results.Attribution
		}{
			RunID: kit.runID, TracePath: kit.tracePath, CaseID: kit.spec.CaseID,
			ExecutionMode: kit.spec.ExecutionMode, OrderID: kit.orderID,
			PeakConcurrency: kit.executor.Peak(), Outcomes: outcomes,
			Brief: briefPointer, SynthesisInvoked: synthesisInvoked, Attribution: blocks,
		})
		if err != nil {
			return nil, err
		}
		return map[string]any{"result": result}, nil
	}
	if err := graph.AddLambdaNode("finalize", compose.InvokableLambda(finalize), compose.WithNodeName("finalize")); err != nil {
		return nil, err
	}

	// Synthesis gate: the framework-native branch routes to the synthesize
	// node exactly when at least one worker succeeded.
	branch := compose.NewGraphBranch(func(ctx context.Context, input map[string]any) (string, error) {
		successes, ok := input["successes"].(int)
		if !ok {
			return "", fmt.Errorf("mapping: collector produced no success count")
		}
		if successes > 0 {
			return "synthesize", nil
		}
		return "finalize", nil
	}, map[string]bool{"synthesize": true, "finalize": true})
	if err := graph.AddBranch("collect", branch); err != nil {
		return nil, err
	}

	// Edges: fan-out from START to the three workers, fan-in to collect,
	// branch to synthesize|finalize, synthesize to finalize, finalize to END.
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

// traceWriter is the concurrency-safe JSONL trace sink.
type traceWriter struct {
	mu      sync.Mutex
	handle  *os.File
	encoder *json.Encoder
}

func newTraceWriter(path string) (*traceWriter, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, fmt.Errorf("mapping: create trace directory: %w", err)
	}
	handle, err := os.Create(path)
	if err != nil {
		return nil, fmt.Errorf("mapping: open trace file: %w", err)
	}
	encoder := json.NewEncoder(handle)
	return &traceWriter{handle: handle, encoder: encoder}, nil
}

func (t *traceWriter) write(line map[string]any) {
	t.mu.Lock()
	defer t.mu.Unlock()
	_ = t.encoder.Encode(line)
}

func (t *traceWriter) close() error {
	return t.handle.Close()
}

// callbacksTraceHandler builds the Eino callback handler streaming node
// events to the trace file (the mapping's native-ish record: node_start /
// node_end / node_error lines with the node's name and component).
func callbacksTraceHandler(trace *traceWriter) callbacks.Handler {
	handler := callbacks.NewHandlerBuilder()
	handler.OnStartFn(func(ctx context.Context, info *callbacks.RunInfo, input callbacks.CallbackInput) context.Context {
		name, component := runIdentity(info)
		trace.write(map[string]any{"event": "node_start", "node": name, "component": component})
		return ctx
	})
	handler.OnEndFn(func(ctx context.Context, info *callbacks.RunInfo, output callbacks.CallbackOutput) context.Context {
		name, component := runIdentity(info)
		trace.write(map[string]any{"event": "node_end", "node": name, "component": component})
		return ctx
	})
	handler.OnErrorFn(func(ctx context.Context, info *callbacks.RunInfo, err error) context.Context {
		name, _ := runIdentity(info)
		trace.write(map[string]any{"event": "node_error", "node": name, "error": fmt.Sprint(err)})
		return ctx
	})
	return handler.Build()
}

// runGraph compiles and runs the corrected graph, streaming the Eino
// callback events to the trace file and extracting the published result.
func runGraph(ctx context.Context, kit *runKit) (RunReport, error) {
	graph, err := buildGraph(kit)
	if err != nil {
		return RunReport{}, err
	}
	runnable, err := graph.Compile(ctx, compose.WithNodeTriggerMode(compose.AnyPredecessor), compose.WithGraphName("order-brief-eino-mapping"))
	if err != nil {
		return RunReport{}, fmt.Errorf("mapping: compile graph: %w", err)
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
		return RunReport{}, fmt.Errorf("mapping: corrected run failed: %w", err)
	}
	result, ok := output["result"].(results.RunResult)
	if !ok {
		return RunReport{}, fmt.Errorf("mapping: corrected run produced no publishable result")
	}
	return RunReport{Result: result}, nil
}

func runIdentity(info *callbacks.RunInfo) (string, string) {
	if info == nil {
		return "unknown", "unknown"
	}
	return info.Name, string(info.Component)
}

// newUUID generates a random RFC 4122 version-4 id (stdlib only).
func newUUID() string {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		panic(fmt.Sprintf("mapping: uuid generation failed: %v", err))
	}
	bytes[6] = (bytes[6] & 0x0f) | 0x40
	bytes[8] = (bytes[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", bytes[0:4], bytes[4:6], bytes[6:8], bytes[8:10], bytes[10:16])
}
