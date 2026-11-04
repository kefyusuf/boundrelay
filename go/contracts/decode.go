package contracts

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"reflect"
	"strings"
)

// Strict-decoding failures: the shared schemas are closed, so unexpected
// shapes must fail closed rather than be silently coerced.
var (
	// ErrTrailingData is returned when more than one JSON value is present.
	ErrTrailingData = errors.New("contracts: trailing data after the JSON value")
	// ErrNonFiniteNumber is returned for NaN or an infinity in a decoded tree.
	ErrNonFiniteNumber = errors.New("contracts: non-finite JSON number")
)

// DecodeStrict decodes exactly one JSON document into target, mirroring the
// lessons' bounded-JSON rules: unknown fields are refused, trailing data
// after the value is refused, and no number in the decoded tree may be NaN
// or an infinity.
func DecodeStrict(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	if _, err := decoder.Token(); !errors.Is(err, io.EOF) {
		return ErrTrailingData
	}
	return rejectNonFinite("", reflect.ValueOf(target))
}

// DecodeEvent strictly decodes a trace event envelope.
func DecodeEvent(data []byte) (Event, error) {
	var event Event
	if err := DecodeStrict(data, &event); err != nil {
		return Event{}, err
	}
	return event, nil
}

// DecodeRunResult strictly decodes an M0 run result.
func DecodeRunResult(data []byte) (RunResult, error) {
	var result RunResult
	if err := DecodeStrict(data, &result); err != nil {
		return RunResult{}, err
	}
	return result, nil
}

// rejectNonFinite walks a decoded value and refuses NaN/infinity floats —
// impossible from valid JSON text but possible in trees assembled in memory.
func rejectNonFinite(path string, value reflect.Value) error {
	switch value.Kind() {
	case reflect.Interface, reflect.Pointer:
		if value.IsNil() {
			return nil
		}
		return rejectNonFinite(path, value.Elem())
	case reflect.Float32, reflect.Float64:
		number := value.Float()
		if math.IsNaN(number) || math.IsInf(number, 0) {
			return fmt.Errorf("%w at %s", ErrNonFiniteNumber, path)
		}
	case reflect.Slice, reflect.Array:
		for i := 0; i < value.Len(); i++ {
			child := fmt.Sprintf("%s[%d]", path, i)
			if err := rejectNonFinite(child, value.Index(i)); err != nil {
				return err
			}
		}
	case reflect.Map:
		for _, key := range value.MapKeys() {
			child := fmt.Sprintf("%s[%v]", path, key)
			if err := rejectNonFinite(child, value.MapIndex(key)); err != nil {
				return err
			}
		}
	case reflect.Struct:
		structType := value.Type()
		for i := 0; i < structType.NumField(); i++ {
			field := structType.Field(i)
			name := field.Name
			if tag, ok := field.Tag.Lookup("json"); ok {
				if head := strings.Split(tag, ",")[0]; head != "" {
					name = head
				}
			}
			if err := rejectNonFinite(path+"."+name, value.Field(i)); err != nil {
				return err
			}
		}
	}
	return nil
}
