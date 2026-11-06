package mapping

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"boundrelay-m3-eino/internal/fixtures"
	"boundrelay-m3-eino/internal/results"
)

const parityCaseKeys = "sequential-complete|parallel-complete|parallel-out-of-order|parallel-partial-failure|parallel-all-failed|parallel-invalid-output"

func repoRoot(t *testing.T) string {
	t.Helper()
	root, err := fixtures.FindRepoRoot()
	if err != nil {
		t.Fatalf("find repo root: %v", err)
	}
	return root
}

func runCorrectedCase(t *testing.T, caseID string) results.RunResult {
	t.Helper()
	tracePath := filepath.Join(t.TempDir(), "traces", caseID+".jsonl")
	report, err := RunCase(context.Background(), RunOptions{
		CaseID: caseID, TracePath: tracePath, RepoRoot: repoRoot(t), GuardMS: 20_000})
	if err != nil {
		t.Fatalf("run corrected %s: %v", caseID, err)
	}
	if !strings.Contains(tracePath, caseID) {
		t.Fatalf("trace path drift: %s", tracePath)
	}
	return report.Result
}

// normalizeResult strips the run-scoped fields (run_id, trace_path) and
// returns the comparable projection.
func normalizeResult(t *testing.T, result results.RunResult) map[string]any {
	t.Helper()
	raw, err := json.Marshal(result)
	if err != nil {
		t.Fatalf("marshal result: %v", err)
	}
	var projection map[string]any
	if err := json.Unmarshal(raw, &projection); err != nil {
		t.Fatalf("decode result: %v", err)
	}
	delete(projection, "run_id")
	delete(projection, "trace_path")
	return projection
}

func goldenProjection(t *testing.T, caseID string) map[string]any {
	t.Helper()
	golden, err := fixtures.LoadGolden(fixtures.GoldenPath(repoRoot(t), caseID))
	if err != nil {
		t.Fatalf("load golden %s: %v", caseID, err)
	}
	var projection map[string]any
	if err := json.Unmarshal(golden.ResultProjection, &projection); err != nil {
		t.Fatalf("decode golden %s: %v", caseID, err)
	}
	return projection
}

func TestParitySixCases(t *testing.T) {
	for _, caseID := range strings.Split(parityCaseKeys, "|") {
		t.Run(caseID, func(t *testing.T) {
			result := runCorrectedCase(t, caseID)
			if err := results.ValidateResult(result); err != nil {
				t.Fatalf("published result fails the closed validator: %v", err)
			}
			projection := normalizeResult(t, result)
			golden := goldenProjection(t, caseID)
			if !reflect.DeepEqual(projection, golden) {
				t.Fatalf("result projection drift for %s:\n got: %v\nwant: %v", caseID, projection, golden)
			}
			// Attribution deep-equal against the golden's attribution block.
			goldenAttribution, ok := golden["attribution"]
			if !ok {
				t.Fatalf("golden %s carries no attribution", caseID)
			}
			attributionRaw, err := json.Marshal(result.Attribution)
			if err != nil {
				t.Fatalf("marshal attribution: %v", err)
			}
			var attributionProjection any
			if err := json.Unmarshal(attributionRaw, &attributionProjection); err != nil {
				t.Fatalf("decode attribution: %v", err)
			}
			if !reflect.DeepEqual(attributionProjection, goldenAttribution) {
				t.Fatalf("attribution drift for %s: got %v want %v", caseID, attributionProjection, goldenAttribution)
			}
		})
	}
}

func TestParityKeysCoverTheCanonicalSet(t *testing.T) {
	root := repoRoot(t)
	scenario, err := fixtures.LoadScenario(
		fixtures.DefaultScenarioPath(root), fixtures.DefaultWorkersPath(root))
	if err != nil {
		t.Fatalf("load scenario: %v", err)
	}
	keys := make([]string, 0, len(scenario.Cases))
	for _, scenarioCase := range scenario.Cases {
		keys = append(keys, scenarioCase.CaseID)
	}
	if strings.Join(keys, "|") != parityCaseKeys {
		t.Fatalf("parity keys drifted: %v", keys)
	}
}

func TestTaxonomyPreservedInsideNodes(t *testing.T) {
	t.Run("declared failure is a mapped outcome, not a run failure", func(t *testing.T) {
		result := runCorrectedCase(t, "parallel-partial-failure")
		if result.Status != "PARTIAL" || result.SynthesisInvoked != true {
			t.Fatalf("unexpected header: %+v", result)
		}
		delivery := result.WorkerOutcomes[2]
		if delivery.Status != "FAILED" || delivery.FailureCode == nil ||
			*delivery.FailureCode != results.FailureWorkerExecutionFailed {
			t.Fatalf("delivery outcome drifted: %+v", delivery)
		}
		if len(result.Brief.MissingWorkers) != 1 || result.Brief.MissingWorkers[0] != "delivery-status" {
			t.Fatalf("brief missing workers drifted: %+v", result.Brief)
		}
	})
	t.Run("invalid return never publishes", func(t *testing.T) {
		result := runCorrectedCase(t, "parallel-invalid-output")
		payment := result.WorkerOutcomes[1]
		if payment.Status != "FAILED" || payment.FailureCode == nil ||
			*payment.FailureCode != results.FailureInvalidWorkerOutput {
			t.Fatalf("payment outcome drifted: %+v", payment)
		}
		if payment.Output != nil && string(payment.Output) != "null" {
			t.Fatalf("invalid output published: %s", payment.Output)
		}
		if result.Status != "PARTIAL" || result.Brief.Complete {
			t.Fatalf("unexpected invalid-output header: %+v", result)
		}
	})
	t.Run("all failed carries ALL_WORKERS_FAILED with no synthesis", func(t *testing.T) {
		result := runCorrectedCase(t, "parallel-all-failed")
		if result.Status != "FAILED" || result.SynthesisInvoked || result.Brief != nil {
			t.Fatalf("unexpected all-failed header: %+v", result)
		}
		if result.FailureCode == nil || *result.FailureCode != results.FailureAllWorkersFailed {
			t.Fatalf("failure code drifted: %v", result.FailureCode)
		}
	})
}

func TestCanonicalOrderingUnderOutOfOrderCompletion(t *testing.T) {
	result := runCorrectedCase(t, "parallel-out-of-order")
	for i, id := range results.CanonicalWorkerIDs {
		if result.WorkerOutcomes[i].WorkerID != id {
			t.Fatalf("outcome %d = %s, want canonical %s", i, result.WorkerOutcomes[i].WorkerID, id)
		}
	}
	for i, section := range result.Brief.Sections {
		if section.WorkerID != results.CanonicalWorkerIDs[i] {
			t.Fatalf("brief section %d = %s, want canonical %s", i, section.WorkerID, results.CanonicalWorkerIDs[i])
		}
	}
	if !result.Brief.Complete || len(result.Brief.Sections) != 3 {
		t.Fatalf("brief drifted: %+v", result.Brief)
	}
}

func TestBoundedAdmission(t *testing.T) {
	t.Run("parallel peak is the cap, not the branch count", func(t *testing.T) {
		result := runCorrectedCase(t, "parallel-complete")
		if result.PeakConcurrency != 2 || result.ConcurrencyLimit != 2 {
			t.Fatalf("parallel peaks drifted: %d/%d", result.PeakConcurrency, result.ConcurrencyLimit)
		}
	})
	t.Run("sequential peak is one", func(t *testing.T) {
		result := runCorrectedCase(t, "sequential-complete")
		if result.PeakConcurrency != 1 || result.ConcurrencyLimit != 1 {
			t.Fatalf("sequential peaks drifted: %d/%d", result.PeakConcurrency, result.ConcurrencyLimit)
		}
	})
	t.Run("first parallel wave proves the cap binds", func(t *testing.T) {
		executor, err := NewBoundedExecutor(
			[]string{"order-details", "payment-status", "delivery-status"}, 2, 20_000)
		if err != nil {
			t.Fatalf("executor: %v", err)
		}
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		// Two workers enter; the first release must wait for the second
		// entrance (the binding proof: peak reaches the limit).
		entered := make(chan error, 2)
		for _, id := range []string{"order-details", "payment-status"} {
			worker := id
			go func() { entered <- executor.Enter(ctx, worker) }()
		}
		for i := 0; i < 2; i++ {
			if err := <-entered; err != nil {
				t.Fatalf("enter: %v", err)
			}
		}
		release := make(chan error, 1)
		go func() { release <- executor.AwaitRelease(ctx, "order-details") }()
		select {
		case err := <-release:
			if err != nil {
				t.Fatalf("release: %v", err)
			}
		case <-time.After(2 * time.Second):
			t.Fatal("first release did not proceed with the full first wave")
		}
		if executor.Peak() != 2 {
			t.Fatalf("peak = %d, want 2", executor.Peak())
		}
	})
	t.Run("third worker is admitted only after a slot frees", func(t *testing.T) {
		executor, err := NewBoundedExecutor(
			[]string{"order-details", "payment-status", "delivery-status"}, 2, 20_000)
		if err != nil {
			t.Fatalf("executor: %v", err)
		}
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		for _, id := range []string{"order-details", "payment-status"} {
			if err := executor.Enter(ctx, id); err != nil {
				t.Fatalf("enter %s: %v", id, err)
			}
		}
		third := make(chan error, 1)
		go func() { third <- executor.Enter(ctx, "delivery-status") }()
		select {
		case err := <-third:
			t.Fatalf("third admission slipped past the cap: %v", err)
		case <-time.After(200 * time.Millisecond):
		}
		if err := executor.AwaitRelease(ctx, "order-details"); err != nil {
			t.Fatalf("release: %v", err)
		}
		if err := executor.Record("order-details"); err != nil {
			t.Fatalf("record: %v", err)
		}
		select {
		case err := <-third:
			if err != nil {
				t.Fatalf("third admission failed: %v", err)
			}
		case <-time.After(2 * time.Second):
			t.Fatal("third admission did not proceed after a slot freed")
		}
	})
	t.Run("infeasible schedule trips the guard instead of hanging", func(t *testing.T) {
		// delivery-status cannot complete first under a 2-slot cap with
		// canonical admission: it can never enter (both slots are held by
		// its canonical priors) while its release gate is the first turn -
		// a circular wait the guard must break.
		executor, err := NewBoundedExecutor(
			[]string{"delivery-status", "order-details", "payment-status"}, 2, 300)
		if err != nil {
			t.Fatalf("executor: %v", err)
		}
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		failures := make(chan error, 3)
		for _, id := range []string{"order-details", "payment-status", "delivery-status"} {
			worker := id
			go func() {
				if err := executor.Enter(ctx, worker); err != nil {
					failures <- err
					return
				}
				failures <- executor.AwaitRelease(ctx, worker)
			}()
		}
		for i := 0; i < 3; i++ {
			select {
			case err := <-failures:
				if !errors.Is(err, ErrToolingInterrupted) {
					t.Fatalf("every waiter must fail with ErrToolingInterrupted, got %v", err)
				}
			case <-time.After(5 * time.Second):
				t.Fatal("infeasible schedule hung past the guard")
			}
		}
	})
	t.Run("abandon drains the run", func(t *testing.T) {
		executor, err := NewBoundedExecutor(
			[]string{"order-details", "payment-status", "delivery-status"}, 1, 20_000)
		if err != nil {
			t.Fatalf("executor: %v", err)
		}
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		waiting := make(chan error, 1)
		go func() {
			if err := executor.Enter(ctx, "payment-status"); err != nil {
				waiting <- err
			}
		}()
		time.Sleep(100 * time.Millisecond)
		executor.Abandon("order-details")
		select {
		case err := <-waiting:
			if !errors.Is(err, ErrToolingInterrupted) {
				t.Fatalf("waiter must fail with ErrToolingInterrupted, got %v", err)
			}
		case <-time.After(2 * time.Second):
			t.Fatal("waiter not drained by abandon")
		}
	})
}

func TestSingleSynthesisInvocationViaTrace(t *testing.T) {
	for _, testCase := range []struct {
		caseID      string
		synthesisOn bool
	}{
		{"parallel-complete", true},
		{"parallel-partial-failure", true},
		{"parallel-all-failed", false},
	} {
		t.Run(testCase.caseID, func(t *testing.T) {
			tracePath := filepath.Join(t.TempDir(), "traces", "synthesis.jsonl")
			report, err := RunCase(context.Background(), RunOptions{
				CaseID: testCase.caseID, TracePath: tracePath, RepoRoot: repoRoot(t), GuardMS: 20_000})
			if err != nil {
				t.Fatalf("run: %v", err)
			}
			_ = report
			raw, err := os.ReadFile(tracePath)
			if err != nil {
				t.Fatalf("read trace: %v", err)
			}
			starts, ends := 0, 0
			for _, line := range strings.Split(strings.TrimSpace(string(raw)), "\n") {
				var event map[string]any
				if err := json.Unmarshal([]byte(line), &event); err != nil {
					t.Fatalf("trace line is not JSON: %s", line)
				}
				if event["node"] == "synthesize" {
					switch event["event"] {
					case "node_start":
						starts++
					case "node_end":
						ends++
					}
				}
			}
			if testCase.synthesisOn && (starts != 1 || ends != 1) {
				t.Fatalf("synthesize must run exactly once (starts=%d ends=%d)", starts, ends)
			}
			if !testCase.synthesisOn && (starts != 0 || ends != 0) {
				t.Fatalf("synthesize must never run on an all-failed run (starts=%d ends=%d)", starts, ends)
			}
			for _, node := range []string{
				"worker.order-details", "worker.payment-status", "worker.delivery-status",
				"collect", "finalize",
			} {
				if !strings.Contains(string(raw), `"node":"`+node+`"`) {
					t.Fatalf("trace misses node %s", node)
				}
			}
		})
	}
}

func TestUnknownCaseIsToolingError(t *testing.T) {
	_, err := RunCase(context.Background(), RunOptions{
		CaseID: "no-such-case", TracePath: filepath.Join(t.TempDir(), "t.jsonl"),
		RepoRoot: repoRoot(t)})
	if err == nil || !errors.Is(err, fixtures.ErrUnknownCase) {
		t.Fatalf("unknown case must surface ErrUnknownCase, got %v", err)
	}
}

func TestNaiveRegression(t *testing.T) {
	t.Run("three-way rendezvous records peak 3", func(t *testing.T) {
		report, err := RunNaive(context.Background(), NaiveOptions{
			CaseID: "parallel-complete", TracePath: filepath.Join(t.TempDir(), "naive.jsonl"),
			RepoRoot: repoRoot(t)})
		if err != nil {
			t.Fatalf("naive run: %v", err)
		}
		if report.Result.PeakConcurrency != 3 {
			t.Fatalf("naive peak = %d, want the uncapped 3", report.Result.PeakConcurrency)
		}
		if err := results.ValidateResult(report.Result); err == nil {
			t.Fatal("the closed validator must reject the naive peak 3")
		}
	})
	t.Run("declared failure propagates and fails the run", func(t *testing.T) {
		tracePath := filepath.Join(t.TempDir(), "naive-fail.jsonl")
		_, err := RunNaive(context.Background(), NaiveOptions{
			CaseID: "parallel-partial-failure", TracePath: tracePath, RepoRoot: repoRoot(t)})
		if err == nil {
			t.Fatal("naive declared failure must fail the run")
		}
		if _, statErr := os.Stat(tracePath); statErr != nil {
			t.Fatalf("trace prefix must be flushed even on failure: %v", statErr)
		}
	})
	t.Run("invalid output published as a fact", func(t *testing.T) {
		report, err := RunNaive(context.Background(), NaiveOptions{
			CaseID: "parallel-invalid-output", TracePath: filepath.Join(t.TempDir(), "naive.jsonl"),
			RepoRoot: repoRoot(t)})
		if err != nil {
			t.Fatalf("naive run: %v", err)
		}
		payment := report.Result.WorkerOutcomes[1]
		if payment.Status != "SUCCEEDED" || payment.Output == nil ||
			!strings.Contains(string(payment.Output), "UNKNOWN") {
			t.Fatalf("naive must publish the UNKNOWN fact: %+v", payment)
		}
		if err := results.ValidateResult(report.Result); err == nil {
			t.Fatal("the closed validator must reject the published MYSTERY output")
		}
	})
}

// explodingTransport turns every network attempt into a hard failure - the
// Go equivalent of the other mappings' offline probes.
type explodingTransport struct{}

func (explodingTransport) RoundTrip(*http.Request) (*http.Response, error) {
	return nil, errors.New("offline proof: network attempted")
}

func TestOfflineProof(t *testing.T) {
	previous := http.DefaultTransport
	http.DefaultTransport = explodingTransport{}
	defer func() { http.DefaultTransport = previous }()
	client := &http.Client{Transport: http.DefaultTransport}
	req, err := http.NewRequest(http.MethodGet, "http://boundrelay.invalid/probe", nil)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	if _, err := client.Do(req); err == nil {
		t.Fatal("the exploding transport must fail network attempts")
	}
	for _, caseID := range strings.Split(parityCaseKeys, "|") {
		t.Run(caseID, func(t *testing.T) {
			result := runCorrectedCase(t, caseID)
			if err := results.ValidateResult(result); err != nil {
				t.Fatalf("offline corrected run invalid: %v", err)
			}
		})
	}
}
