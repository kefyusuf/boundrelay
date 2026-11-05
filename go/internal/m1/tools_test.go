package m1

import (
	"errors"
	"strings"
	"testing"
	"time"
)

func testFakeTools(t *testing.T) *FakeToolData {
	t.Helper()
	data, err := LoadFakeTools(writeProjection(t, canonicalFakeTools))
	if err != nil {
		t.Fatalf("LoadFakeTools: %v", err)
	}
	return data
}

func TestRegistryClosedToolNames(t *testing.T) {
	registry := NewFakeToolRegistry(testFakeTools(t))
	for _, name := range canonicalToolNames {
		if _, ok := registry.Resolve(name); !ok {
			t.Fatalf("canonical tool %s must resolve", name)
		}
		definition, _ := registry.Resolve(name)
		if definition.SideEffect != "READ_ONLY" || definition.TimeoutMS != ToolTimeoutMS {
			t.Fatalf("definition metadata: %+v", definition)
		}
	}
	for _, unknown := range []string{"lookup_customer", "LOOKUP_ORDER", ""} {
		if _, ok := registry.Resolve(unknown); ok {
			t.Fatalf("unknown tool %q must not resolve", unknown)
		}
	}
}

func TestArgumentValidation(t *testing.T) {
	registry := NewFakeToolRegistry(testFakeTools(t))
	order, _ := registry.Resolve(ToolLookupOrder)
	shipment, _ := registry.Resolve(ToolLookupShipment)
	valid := []struct {
		definition ToolDefinition
		arguments  map[string]any
	}{
		{order, map[string]any{"order_id": "ORD-1001"}},
		{shipment, map[string]any{"shipment_id": "SHP-9999"}},
	}
	for _, tc := range valid {
		if validation := tc.definition.ValidateArguments(tc.arguments); !validation.OK {
			t.Fatalf("expected valid arguments, got %v", validation.Errors)
		}
	}
	invalid := []struct {
		name       string
		definition ToolDefinition
		arguments  map[string]any
	}{
		{"missing order_id", order, map[string]any{}},
		{"wrong type", order, map[string]any{"order_id": 1001}},
		{"bad pattern", order, map[string]any{"order_id": "1001"}},
		{"additional property", order, map[string]any{"order_id": "ORD-1001", "extra": true}},
		{"missing shipment_id", shipment, map[string]any{}},
		{"bad shipment pattern", shipment, map[string]any{"shipment_id": "ORD-1001"}},
		{"shipment additional property", shipment, map[string]any{"shipment_id": "SHP-1001", "order_id": "ORD-1001"}},
	}
	for _, tc := range invalid {
		t.Run(tc.name, func(t *testing.T) {
			validation := tc.definition.ValidateArguments(tc.arguments)
			if validation.OK || len(validation.Errors) == 0 {
				t.Fatalf("expected invalid arguments: %+v", validation)
			}
		})
	}
}

func TestFakeToolBehaviors(t *testing.T) {
	data := testFakeTools(t)
	registry := NewFakeToolRegistry(data)
	order, _ := registry.Resolve(ToolLookupOrder)
	output, err := order.Invoke(map[string]any{"order_id": "ORD-1001"})
	if err != nil {
		t.Fatalf("lookup_order: %v", err)
	}
	if output["order_id"] != "ORD-1001" || output["status"] != "SHIPPED" || output["shipment_id"] != "SHP-1001" {
		t.Fatalf("output: %v", output)
	}
	// Outputs must be isolated per invocation (mirroring structuredClone).
	output["status"] = "MUTATED"
	again, err := order.Invoke(map[string]any{"order_id": "ORD-1001"})
	if err != nil {
		t.Fatalf("lookup_order again: %v", err)
	}
	if again["status"] != "SHIPPED" {
		t.Fatalf("output mutated the fixture: %v", again)
	}
	if _, err := order.Invoke(map[string]any{"order_id": "ORD-7777"}); err == nil ||
		!strings.Contains(err.Error(), "Unknown order fixture") {
		t.Fatalf("unknown order must fail: %v", err)
	}
	shipment, _ := registry.Resolve(ToolLookupShipment)
	shipmentOutput, err := shipment.Invoke(map[string]any{"shipment_id": "SHP-1001"})
	if err != nil || shipmentOutput["reason"] != "WEATHER" {
		t.Fatalf("lookup_shipment: %v %v", err, shipmentOutput)
	}
	if _, err := shipment.Invoke(map[string]any{"shipment_id": "SHP-7777"}); err == nil ||
		!strings.Contains(err.Error(), "Unknown shipment fixture") {
		t.Fatalf("unknown shipment must fail: %v", err)
	}
	// The failure behavior raises the scripted execution error.
	if _, err := order.Invoke(map[string]any{"order_id": "ORD-9002"}); err == nil ||
		!strings.Contains(err.Error(), "Order ORD-9002 scripted failure.") {
		t.Fatalf("failure behavior: %v", err)
	}
	// The timeout behavior never returns; bound the probe so the suite
	// cannot hang on regression.
	blocked := make(chan error, 1)
	go func() {
		_, err := order.Invoke(map[string]any{"order_id": "ORD-9001"})
		blocked <- err
	}()
	select {
	case err := <-blocked:
		t.Fatalf("timeout behavior must not return: %v", err)
	case <-time.After(150 * time.Millisecond):
	}
}

func TestInvokeToolTimeoutAndFailure(t *testing.T) {
	data := testFakeTools(t)
	registry := NewFakeToolRegistry(data)
	order, _ := registry.Resolve(ToolLookupOrder)
	if _, err := InvokeTool(order, map[string]any{"order_id": "ORD-9001"}); err == nil {
		t.Fatal("timeout behavior must raise the timeout error")
	} else {
		var timeoutErr *ToolTimeoutError
		if !errors.As(err, &timeoutErr) || timeoutErr.Tool != ToolLookupOrder {
			t.Fatalf("expected ToolTimeoutError, got %v", err)
		}
	}
	if _, err := InvokeTool(order, map[string]any{"order_id": "ORD-9002"}); err == nil {
		t.Fatal("failure behavior must raise the execution error")
	} else {
		var executionErr *ToolExecutionError
		if !errors.As(err, &executionErr) || executionErr.Tool != ToolLookupOrder ||
			!strings.Contains(executionErr.Message, "scripted failure") {
			t.Fatalf("expected ToolExecutionError, got %v", err)
		}
	}
}
