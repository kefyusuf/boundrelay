// The bounded executor wrapper re-establishing M3 admission caps inside
// Eino worker nodes.
//
// Eino admits every ready node in its own goroutine with no concurrency
// primitive at all (verified against v0.9.22: compose/graph_manager.go
// spawns `go t.execute(currentTask)` per submitted task; the compile
// options offer WithMaxRunSteps — rejected in DAG mode — and no concurrency
// bound; instrumented 3-branch rendezvous graphs record peak 3 through the
// Graph API in both trigger modes and through the Workflow field-mapping
// API). This wrapper caps concurrent workers at `limit` (2 for parallel, 1
// for sequential), admits in canonical worker order (so the fixture's
// completion order stays feasible), releases workers along the fixture's
// completion_order (a slot is occupied until the validated outcome is
// recorded), and records the observed peak concurrency. The first parallel
// release additionally waits for the whole first wave to have entered,
// proving the cap binds. Deadlock guard: bounded waits reject with
// ErrToolingInterrupted instead of hanging forever.
package mapping

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"boundrelay-m3-eino/internal/fixtures"
)

// ErrToolingInterrupted marks the guard-tripped / drained tooling failures.
var ErrToolingInterrupted = errors.New("mapping: tooling interrupted")

// DefaultGuardMS is the bounded-wait guard: an admission or release that
// cannot be satisfied within this budget fails the run fast instead of
// hanging.
const DefaultGuardMS = 90_000

// BoundedExecutor is the app-owned admission cap running inside the worker
// nodes while the engine still dispatches all three branches at once.
type BoundedExecutor struct {
	completionOrder []string
	limit           int
	guard           time.Duration

	mu        sync.Mutex
	broadcast chan struct{}
	active    map[string]bool
	entered   map[string]bool
	cursor    int
	peak      int
	broken    bool
}

// NewBoundedExecutor builds the executor for one case run.
func NewBoundedExecutor(completionOrder []string, limit int, guardMS int) (*BoundedExecutor, error) {
	if limit != 1 && limit != 2 {
		return nil, errors.New("mapping: admission limit must be 1 or 2")
	}
	if len(completionOrder) != len(fixtures.CanonicalWorkerIDs) {
		return nil, errors.New("mapping: completion order must be a permutation of the canonical workers")
	}
	if guardMS <= 0 {
		guardMS = DefaultGuardMS
	}
	return &BoundedExecutor{
		completionOrder: append([]string(nil), completionOrder...),
		limit:           limit,
		guard:           time.Duration(guardMS) * time.Millisecond,
		broadcast:       make(chan struct{}),
		active:          map[string]bool{},
		entered:         map[string]bool{},
	}, nil
}

// Peak returns the observed peak admission level.
func (e *BoundedExecutor) Peak() int {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.peak
}

// canonicalPriors lists the canonical workers before id.
func canonicalPriors(id string) []string {
	for i, canonical := range fixtures.CanonicalWorkerIDs {
		if canonical == id {
			return append([]string(nil), fixtures.CanonicalWorkerIDs[:i]...)
		}
	}
	return nil
}

// Enter occupies a slot: admitted only when a slot is free AND every
// canonical-prior worker has already entered (canonical admission).
func (e *BoundedExecutor) Enter(ctx context.Context, workerID string) error {
	return e.wait(ctx, fmt.Sprintf("enter(%s)", workerID), func() bool {
		if e.active[workerID] || e.entered[workerID] {
			return false
		}
		if len(e.active) >= e.limit {
			return false
		}
		for _, prior := range canonicalPriors(workerID) {
			if !e.entered[prior] {
				return false
			}
		}
		e.entered[workerID] = true
		e.active[workerID] = true
		if len(e.active) > e.peak {
			e.peak = len(e.active)
		}
		return true
	})
}

// AwaitRelease is the completion-order gate: run your instruction on your
// turn. The first parallel release additionally waits for the whole first
// wave to have entered (proves the cap binds: peak >= limit).
func (e *BoundedExecutor) AwaitRelease(ctx context.Context, workerID string) error {
	return e.wait(ctx, fmt.Sprintf("release(%s)", workerID), func() bool {
		if e.completionOrder[e.cursor] != workerID {
			return false
		}
		firstWave := e.cursor == 0 && e.limit == 2 && len(fixtures.CanonicalWorkerIDs) > e.limit
		if firstWave {
			return len(e.entered) >= e.limit
		}
		return true
	})
}

// Record acknowledges the validated outcome: the slot frees, the gate
// advances.
func (e *BoundedExecutor) Record(workerID string) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.broken {
		return ErrToolingInterrupted
	}
	if !e.active[workerID] {
		return fmt.Errorf("mapping: record() without an active slot: %s", workerID)
	}
	delete(e.active, workerID)
	e.cursor++
	e.notifyLocked()
	return nil
}

// Abandon is the unexpected-error path: drain the run and fail every
// waiter.
func (e *BoundedExecutor) Abandon(workerID string) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.broken = true
	delete(e.active, workerID)
	e.notifyLocked()
}

// wait runs attempt under the lock until it succeeds, the guard trips, the
// run is drained, or the context is canceled. A successful attempt
// broadcasts: a state change (a new entrance above all) may unblock other
// waiters (the first-wave release waits for the second entrance).
func (e *BoundedExecutor) wait(ctx context.Context, what string, attempt func() bool) error {
	for {
		e.mu.Lock()
		if e.broken {
			e.mu.Unlock()
			return fmt.Errorf("%w: run drained by an unexpected error", ErrToolingInterrupted)
		}
		if attempt() {
			e.notifyLocked()
			e.mu.Unlock()
			return nil
		}
		subscription := e.broadcast
		e.mu.Unlock()

		timer := time.NewTimer(e.guard)
		select {
		case <-subscription:
			timer.Stop()
		case <-timer.C:
			e.mu.Lock()
			if !e.broken {
				e.broken = true
			}
			e.notifyLocked()
			e.mu.Unlock()
			return fmt.Errorf("%w: admission guard tripped: %s", ErrToolingInterrupted, what)
		case <-ctx.Done():
			timer.Stop()
			e.mu.Lock()
			if !e.broken {
				e.broken = true
			}
			e.notifyLocked()
			e.mu.Unlock()
			return fmt.Errorf("%w: %s canceled: %v", ErrToolingInterrupted, what, ctx.Err())
		}
	}
}

// notifyLocked wakes every waiter by closing and replacing the broadcast
// channel. Callers must hold mu.
func (e *BoundedExecutor) notifyLocked() {
	close(e.broadcast)
	e.broadcast = make(chan struct{})
}
