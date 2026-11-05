package m1

import (
	"encoding/json"
	"fmt"
	"regexp"
	"time"
)

// Canonical M1 tool names; the registry is closed over exactly these.
const (
	ToolLookupOrder    = "lookup_order"
	ToolLookupShipment = "lookup_shipment"
)

// ToolSideEffect and the fixed fake-tool timeout mirror the TS/Py registry.
const (
	ToolSideEffect = "READ_ONLY"
	ToolTimeoutMS  = 100
)

// canonicalToolNames is the closed tool-name set.
var canonicalToolNames = []string{ToolLookupOrder, ToolLookupShipment}

func isCanonicalTool(name string) bool {
	for _, tool := range canonicalToolNames {
		if tool == name {
			return true
		}
	}
	return false
}

// ArgumentValidation mirrors the TS/Py ValidationResult: either the validated
// arguments or the collected schema errors.
type ArgumentValidation struct {
	OK     bool
	Value  map[string]any
	Errors []string
}

// ToolDefinition is one closed fake tool: name, side effect, the fixed
// timeout, closed argument validation, and the scripted body.
type ToolDefinition struct {
	Name              string
	SideEffect        string
	TimeoutMS         int
	ValidateArguments func(arguments map[string]any) ArgumentValidation
	Invoke            func(arguments map[string]any) (map[string]any, error)
}

// ToolRegistry resolves tool names to definitions; unknown names resolve to
// false so the loop fails closed with UNKNOWN_TOOL.
type ToolRegistry interface {
	Resolve(name string) (ToolDefinition, bool)
}

// StaticToolRegistry is the fixed two-tool registry.
type StaticToolRegistry struct {
	definitions map[string]ToolDefinition
}

// Resolve implements ToolRegistry.
func (r *StaticToolRegistry) Resolve(name string) (ToolDefinition, bool) {
	definition, ok := r.definitions[name]
	return definition, ok
}

var (
	orderIDPattern    = regexp.MustCompile(`^ORD-[0-9]{4}$`)
	shipmentIDPattern = regexp.MustCompile(`^SHP-[0-9]{4}$`)
)

// validateLookupArguments mirrors the closed tool-argument schemas
// (contracts/tools/lookup-{order,shipment}-arguments.schema.json): exactly
// one required string id with a fixed pattern, no additional properties.
func validateLookupArguments(arguments map[string]any, key string, pattern *regexp.Regexp) ArgumentValidation {
	var errors []string
	for name := range arguments {
		if name != key {
			errors = append(errors, fmt.Sprintf("%s: additional property %q is not allowed", key, name))
		}
	}
	value, present := arguments[key]
	if !present {
		errors = append(errors, fmt.Sprintf("%s: %q is required", key, key))
	} else {
		id, isString := value.(string)
		if !isString {
			errors = append(errors, fmt.Sprintf("%s: %q must be a string", key, key))
		} else if !pattern.MatchString(id) {
			errors = append(errors, fmt.Sprintf("%s: %q does not match pattern %s", key, key, pattern.String()))
		}
	}
	if len(errors) > 0 {
		return ArgumentValidation{OK: false, Errors: errors}
	}
	return ArgumentValidation{OK: true, Value: arguments}
}

// FakeToolData bodies: the scripted behaviors from the fake-tools projection.
// The timeout behavior never returns (mirroring the TS/Py fake), the failure
// behavior raises a scripted execution error, and otherwise the entry's
// output is returned deep-copied.
func (d *FakeToolData) invokeEntry(entry fakeToolEntryWire, label string) (map[string]any, error) {
	if entry.Behavior == "timeout" {
		<-make(chan struct{})
		return nil, fmt.Errorf("unreachable")
	}
	if entry.Behavior == "failure" {
		return nil, fmt.Errorf("%s scripted failure.", label)
	}
	if entry.Output == nil {
		return nil, fmt.Errorf("%s fixture must contain output or behavior.", label)
	}
	return deepCopyMap(entry.Output), nil
}

// LookupOrder is the scripted lookup_order body.
func (d *FakeToolData) LookupOrder(arguments map[string]any) (map[string]any, error) {
	orderID, _ := arguments["order_id"].(string)
	entry, ok := d.Orders[orderID]
	if !ok {
		return nil, fmt.Errorf("Unknown order fixture: %v", arguments["order_id"])
	}
	return d.invokeEntry(entry, "Order "+orderID)
}

// LookupShipment is the scripted lookup_shipment body.
func (d *FakeToolData) LookupShipment(arguments map[string]any) (map[string]any, error) {
	shipmentID, _ := arguments["shipment_id"].(string)
	entry, ok := d.Shipments[shipmentID]
	if !ok {
		return nil, fmt.Errorf("Unknown shipment fixture: %v", arguments["shipment_id"])
	}
	return d.invokeEntry(entry, "Shipment "+shipmentID)
}

// NewFakeToolRegistry builds the closed two-tool registry over the
// validated fake-tools data.
func NewFakeToolRegistry(data *FakeToolData) *StaticToolRegistry {
	return &StaticToolRegistry{definitions: map[string]ToolDefinition{
		ToolLookupOrder: {
			Name: ToolLookupOrder, SideEffect: ToolSideEffect, TimeoutMS: ToolTimeoutMS,
			ValidateArguments: func(arguments map[string]any) ArgumentValidation {
				return validateLookupArguments(arguments, "order_id", orderIDPattern)
			},
			Invoke: data.LookupOrder,
		},
		ToolLookupShipment: {
			Name: ToolLookupShipment, SideEffect: ToolSideEffect, TimeoutMS: ToolTimeoutMS,
			ValidateArguments: func(arguments map[string]any) ArgumentValidation {
				return validateLookupArguments(arguments, "shipment_id", shipmentIDPattern)
			},
			Invoke: data.LookupShipment,
		},
	}}
}

// ToolTimeoutError is raised when a tool body exceeds its fixed timeout; it
// maps 1:1 to the TOOL_TIMEOUT failure code.
type ToolTimeoutError struct {
	Tool string
}

func (e *ToolTimeoutError) Error() string {
	return fmt.Sprintf("Tool timed out: %s", e.Tool)
}

// ToolExecutionError wraps every non-timeout tool failure; it maps 1:1 to
// the TOOL_EXECUTION_FAILED failure code.
type ToolExecutionError struct {
	Tool    string
	Message string
}

func (e *ToolExecutionError) Error() string {
	return e.Message
}

// InvokeTool runs one tool body against its fixed timeout (mirroring the
// TS/Py executor race): a timed-out body maps to TOOL_TIMEOUT and any other
// body error to TOOL_EXECUTION_FAILED.
func InvokeTool(definition ToolDefinition, arguments map[string]any) (map[string]any, error) {
	type outcome struct {
		output map[string]any
		err    error
	}
	done := make(chan outcome, 1)
	go func() {
		output, err := definition.Invoke(arguments)
		done <- outcome{output: output, err: err}
	}()
	timer := time.NewTimer(time.Duration(definition.TimeoutMS) * time.Millisecond)
	defer timer.Stop()
	select {
	case result := <-done:
		if result.err != nil {
			return nil, &ToolExecutionError{Tool: definition.Name, Message: result.err.Error()}
		}
		return result.output, nil
	case <-timer.C:
		return nil, &ToolTimeoutError{Tool: definition.Name}
	}
}

// deepCopyMap clones a decoded JSON object so tool outputs and scripted
// fixtures are isolated per invocation (mirroring structuredClone).
func deepCopyMap(value map[string]any) map[string]any {
	raw, err := json.Marshal(value)
	if err != nil {
		return value
	}
	var copied map[string]any
	if err := json.Unmarshal(raw, &copied); err != nil {
		return value
	}
	return copied
}
