// Package contracts defines transport-neutral scope and evidence types.
package contracts

import (
	"fmt"
	"time"
	_ "time/tzdata" // Make named time zones available on native Windows too.
)

type Scope struct {
	TenantID        int    `json:"tenant_id"`
	FromDate        string `json:"from_date"`
	ToDateExclusive string `json:"to_date_exclusive"`
	Timezone        string `json:"timezone"`
}

func (s Scope) Normalize() Scope {
	if s.Timezone == "" {
		s.Timezone = "America/Lima"
	}
	return s
}
func (s Scope) UTCBounds() (time.Time, time.Time, error) {
	s = s.Normalize()
	if s.TenantID < 1 || s.TenantID > 5 {
		return time.Time{}, time.Time{}, fmt.Errorf("tenant must be between 1 and 5")
	}
	zone, err := time.LoadLocation(s.Timezone)
	if err != nil {
		return time.Time{}, time.Time{}, fmt.Errorf("invalid timezone: %w", err)
	}
	start, err := time.ParseInLocation("2006-01-02", s.FromDate, zone)
	if err != nil {
		return time.Time{}, time.Time{}, fmt.Errorf("invalid start date")
	}
	end, err := time.ParseInLocation("2006-01-02", s.ToDateExclusive, zone)
	if err != nil {
		return time.Time{}, time.Time{}, fmt.Errorf("invalid exclusive end date")
	}
	// Calendar-day arithmetic does not confuse DST days with 24-hour durations.
	a, _ := time.Parse("2006-01-02", s.FromDate)
	b, _ := time.Parse("2006-01-02", s.ToDateExclusive)
	days := int(b.Sub(a).Hours() / 24)
	if days < 1 || days > 800 {
		return time.Time{}, time.Time{}, fmt.Errorf("date range must span 1 to 800 calendar days")
	}
	return start.UTC(), end.UTC(), nil
}
func (s Scope) Validate() error { _, _, err := s.UTCBounds(); return err }
func (s Scope) Days() int {
	a, e1 := time.Parse("2006-01-02", s.FromDate)
	b, e2 := time.Parse("2006-01-02", s.ToDateExclusive)
	if e1 != nil || e2 != nil {
		return 0
	}
	return int(b.Sub(a).Hours() / 24)
}

type Evidence struct {
	QueryID           string           `json:"query_id"`
	DatasetVersion    string           `json:"dataset_version"`
	EffectiveScope    Scope            `json:"effective_scope"`
	AsOf              time.Time        `json:"as_of"`
	EventWatermark    *time.Time       `json:"event_watermark"`
	TotalMatching     int64            `json:"total_matching"`
	ReturnedRows      int              `json:"returned_rows"`
	Truncated         bool             `json:"truncated"`
	Rows              []map[string]any `json:"rows"`
	AggregationMethod string           `json:"aggregation_method"`
	Sources           []string         `json:"sources"`
	Warnings          []string         `json:"warnings"`
	NextCursor        *string          `json:"next_cursor"`
}

func (e Evidence) Validate(scope Scope) error {
	if e.EffectiveScope.Normalize() != scope.Normalize() {
		return fmt.Errorf("evidence scope mismatch")
	}
	if e.QueryID == "" || e.DatasetVersion == "" || e.TotalMatching < 0 || e.ReturnedRows != len(e.Rows) {
		return fmt.Errorf("incomplete or inconsistent evidence")
	}
	return nil
}
