package m4

import (
	"crypto/rand"
	"encoding/json"
	"fmt"
)

// newUUID generates a random RFC 4122 version-4 id (stdlib only).
func newUUID() (string, error) {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		return "", fmt.Errorf("m4: uuid generation failed: %w", err)
	}
	bytes[6] = (bytes[6] & 0x0f) | 0x40
	bytes[8] = (bytes[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", bytes[0:4], bytes[4:6], bytes[6:8], bytes[8:10], bytes[10:16]), nil
}

// jsonRaw aliases the raw JSON byte slice type.
func jsonRaw(raw []byte) json.RawMessage { return json.RawMessage(raw) }

// deref returns the pointed-to string or "" for nil.
func deref(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}
