package ingestion

import (
	"testing"
	"time"
)

func TestIndependentMillionOracle(t *testing.T) {
	anchor := time.Date(2026, 10, 23, 0, 0, 0, 0, time.UTC)
	m := NewManifest()
	for id := int64(1); id <= 1000000; id++ {
		m.Add(Incident(id, 42, anchor, 730, "test"))
	}
	if m.Count != 1000000 || m.ResolvedCount != 333291 || m.DurationSumSeconds != 28855234742 {
		t.Fatalf("cross-language oracle mismatch: %+v", m)
	}
}
func TestSpecBounds(t *testing.T) {
	if (Spec{}).Validate() == nil {
		t.Fatal("unbounded specification accepted")
	}
}
