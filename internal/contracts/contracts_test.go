package contracts

import "testing"

func TestScopeBoundaries(t *testing.T) {
	s := Scope{TenantID: 1, FromDate: "2026-01-01", ToDateExclusive: "2026-02-01"}
	a, b, err := s.UTCBounds()
	if err != nil {
		t.Fatal(err)
	}
	if a.Hour() != 5 || b.Hour() != 5 || s.Days() != 31 {
		t.Fatal(a, b, s.Days())
	}
	for _, bad := range []Scope{{TenantID: 0, FromDate: s.FromDate, ToDateExclusive: s.ToDateExclusive}, {TenantID: 1, FromDate: s.FromDate, ToDateExclusive: s.FromDate}, {TenantID: 1, FromDate: s.FromDate, ToDateExclusive: "2030-01-01"}, {TenantID: 1, FromDate: s.FromDate, ToDateExclusive: s.ToDateExclusive, Timezone: "Invalid/Zone"}} {
		if bad.Validate() == nil {
			t.Fatalf("accepted invalid scope: %+v", bad)
		}
	}
}
func TestEvidenceScope(t *testing.T) {
	s := Scope{TenantID: 1, FromDate: "2026-01-01", ToDateExclusive: "2026-02-01"}
	e := Evidence{QueryID: "q", DatasetVersion: "v", EffectiveScope: s, TotalMatching: 1, ReturnedRows: 1, Rows: []map[string]any{{"count": 1}}}
	if err := e.Validate(s); err != nil {
		t.Fatal(err)
	}
	s.TenantID = 2
	if e.Validate(s) == nil {
		t.Fatal("cross-tenant evidence accepted")
	}
}
