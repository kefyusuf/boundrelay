package m3

import (
	"strings"
	"testing"

	"github.com/kefyusuf/boundrelay/go/contracts"
)

func canonicalSuccesses() [3]WorkerOutcome {
	var outcomes [3]WorkerOutcome
	outcomes[0] = succeededOutcome(contracts.WorkerOrderDetails, `{"order_id":"ORD-1001","order_status":"SHIPPED"}`)
	outcomes[1] = succeededOutcome(contracts.WorkerPaymentStatus, `{"order_id":"ORD-1001","payment_status":"PAID"}`)
	outcomes[2] = succeededOutcome(contracts.WorkerDeliveryStatus, `{"order_id":"ORD-1001","delivery_status":"DELAYED"}`)
	return outcomes
}

func TestSynthesizeBriefComplete(t *testing.T) {
	brief, err := SynthesizeBrief("ORD-1001", canonicalSuccesses())
	if err != nil {
		t.Fatalf("SynthesizeBrief: %v", err)
	}
	if !brief.Complete || brief.OrderID != "ORD-1001" || len(brief.Sections) != 3 ||
		len(brief.MissingWorkers) != 0 {
		t.Fatalf("brief: %+v", brief)
	}
	if brief.Sections[0].WorkerID != contracts.WorkerOrderDetails ||
		brief.Sections[2].WorkerID != contracts.WorkerDeliveryStatus {
		t.Fatalf("sections order: %+v", brief.Sections)
	}
}

func TestSynthesizeBriefPartial(t *testing.T) {
	outcomes := canonicalSuccesses()
	outcomes[1] = failedOutcome(contracts.WorkerPaymentStatus, contracts.FailureInvalidWorkerOutput)
	brief, err := SynthesizeBrief("ORD-1001", outcomes)
	if err != nil {
		t.Fatalf("SynthesizeBrief: %v", err)
	}
	if brief.Complete || len(brief.Sections) != 2 || len(brief.MissingWorkers) != 1 ||
		brief.MissingWorkers[0] != contracts.WorkerPaymentStatus {
		t.Fatalf("partial brief: %+v", brief)
	}
}

func TestSynthesizeBriefRejectsZeroSuccesses(t *testing.T) {
	var outcomes [3]WorkerOutcome
	outcomes[0] = failedOutcome(contracts.WorkerOrderDetails, contracts.FailureWorkerExecutionFailed)
	outcomes[1] = failedOutcome(contracts.WorkerPaymentStatus, contracts.FailureWorkerExecutionFailed)
	outcomes[2] = failedOutcome(contracts.WorkerDeliveryStatus, contracts.FailureWorkerExecutionFailed)
	if _, err := SynthesizeBrief("ORD-1001", outcomes); err == nil ||
		!strings.Contains(err.Error(), "successful evidence") {
		t.Fatalf("zero-success synthesis must fail, got %v", err)
	}
}
