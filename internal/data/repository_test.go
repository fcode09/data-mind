package data

import (
	"context"
	"github.com/fcode09/data-mind/internal/contracts"
	"github.com/jackc/pgx/v5"
	"os"
	"testing"
	"time"
)

func testScope(tenant int) contracts.Scope {
	return contracts.Scope{TenantID: tenant, FromDate: "2024-10-22", ToDateExclusive: "2026-10-25", Timezone: "America/Lima"}
}
func TestFilterAndCursor(t *testing.T) {
	s := testScope(1)
	where, args, err := filter(s, Filters{Category: "Alumbrado", Status: "Abierto"})
	if err != nil || len(args) != 5 || where == "" {
		t.Fatal(where, args, err)
	}
	if _, _, err = filter(s, Filters{Category: "'; DROP TABLE incidents;--"}); err == nil {
		t.Fatal("invalid filter accepted")
	}
	r := &Repository{cursorSecret: []byte("test-key")}
	row := map[string]any{"id": int64(7), "event_at": time.Now().UTC()}
	hash := scopeHash(s, "", Filters{})
	cursor, err := r.encodeCursor(hash, row)
	if err != nil {
		t.Fatal(err)
	}
	got, err := r.decodeCursor(cursor, hash)
	if err != nil || got.ID != 7 {
		t.Fatal(got, err)
	}
	if _, err = r.decodeCursor(cursor, scopeHash(testScope(2), "", Filters{})); err == nil {
		t.Fatal("cross-tenant cursor accepted")
	}
	if _, err = r.decodeCursor(cursor+"x", hash); err == nil {
		t.Fatal("tampered cursor accepted")
	}
}
func integrationRepository(t *testing.T) *Repository {
	t.Helper()
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL unset: PostgreSQL integration not run")
	}
	r, err := New(context.Background(), dsn, "integration-cursor-key")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(r.Close)
	return r
}
func TestPostgresQueriesAndTenantIsolation(t *testing.T) {
	r := integrationRepository(t)
	ctx := context.Background()
	s := testScope(1)
	summary, err := r.IncidentsSummary(ctx, s, "category", 100, Filters{})
	if err != nil {
		t.Fatal(err)
	}
	if summary.TotalMatching < 1 {
		t.Fatal("fixture dataset empty")
	}
	var sum int64
	for _, row := range summary.Rows {
		sum += row["count"].(int64)
	}
	if sum != summary.TotalMatching {
		t.Fatal("truncated total", sum, summary.TotalMatching)
	}
	page, err := r.IncidentsSearch(ctx, s, "", 2, "", Filters{})
	if err != nil {
		t.Fatal(err)
	}
	if !page.Truncated || page.NextCursor == nil || len(page.Rows) != 2 {
		t.Fatal(page)
	}
	next, err := r.IncidentsSearch(ctx, s, "", 2, *page.NextCursor, Filters{})
	if err != nil {
		t.Fatal(err)
	}
	if next.Rows[0]["id"] == page.Rows[0]["id"] || next.TotalMatching != page.TotalMatching {
		t.Fatal("unstable pagination")
	}
	if _, err = r.IncidentsSearch(ctx, testScope(2), "", 2, *page.NextCursor, Filters{}); err == nil {
		t.Fatal("cursor scope escape")
	}
	detail, err := r.IncidentDetail(ctx, testScope(2), page.Rows[0]["id"].(int64))
	if err != nil {
		t.Fatal(err)
	}
	if detail.TotalMatching != 0 {
		t.Fatal("tenant detail leak")
	}
	one, err := r.IncidentDetail(ctx, s, page.Rows[0]["id"].(int64))
	if err != nil || one.TotalMatching != 1 {
		t.Fatal(one, err)
	}
	timeline, err := r.IncidentsTimeseries(ctx, s, Filters{})
	if err != nil || timeline.TotalMatching != summary.TotalMatching {
		t.Fatal(timeline.TotalMatching, err)
	}
	status, err := r.DatasetStatus(ctx, s)
	if err != nil || status.TotalMatching < summary.TotalMatching {
		t.Fatal(status, err)
	}
	docs, err := r.KnowledgeSearch(ctx, s, "alumbrado", 5)
	if err != nil {
		t.Fatal(err)
	}
	if docs.TotalMatching < 1 || len(docs.Sources) == 0 {
		t.Fatal("missing SOP evidence", docs)
	}
	s.FromDate = "2026-01-01"
	s.ToDateExclusive = "2026-10-23"
	stats, err := r.ResolutionStatistics(ctx, s, Filters{})
	if err != nil {
		t.Fatal(err)
	}
	if stats.Rows[0]["resolved_count"].(int64) < 1 {
		t.Fatal(stats)
	}
	filtered, err := r.IncidentsSummary(ctx, s, "status", 10, Filters{Status: "Abierto"})
	if err != nil || len(filtered.Rows) != 1 || filtered.Rows[0]["label"] != "Abierto" {
		t.Fatal(filtered, err)
	}
	// Alternate tenants using the same pool. Transaction-local settings cannot leak.
	for tenant := 1; tenant <= 5; tenant++ {
		out, err := r.IncidentsSearch(ctx, testScope(tenant), "", 1, "", Filters{})
		if err != nil {
			t.Fatal(err)
		}
		if out.EffectiveScope.TenantID != tenant {
			t.Fatal("pool scope leak")
		}
	}
}
func TestPostgresReadOnlyAndSnapshot(t *testing.T) {
	r := integrationRepository(t)
	ctx := context.Background()
	s := testScope(1)
	_, err := r.read(ctx, s, func(ctx context.Context, tx pgx.Tx) (result, error) {
		var isolation, readonly, tenant string
		if err := tx.QueryRow(ctx, "SELECT current_setting('transaction_isolation'),current_setting('transaction_read_only'),current_setting('app.tenant_id')").Scan(&isolation, &readonly, &tenant); err != nil {
			return result{}, err
		}
		if isolation != "repeatable read" || readonly != "on" || tenant != "1" {
			t.Errorf("unsafe transaction: %s %s %s", isolation, readonly, tenant)
		}
		var leaked int64
		if err := tx.QueryRow(ctx, "SELECT count(*) FROM incidents WHERE tenant_id<>1").Scan(&leaked); err != nil {
			return result{}, err
		}
		if leaked != 0 {
			t.Error("RLS leaked tenant rows")
		}
		return result{rows: []map[string]any{}, total: 0}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
}
func TestPostgresRejectsAdmin(t *testing.T) {
	dsn := os.Getenv("ADMIN_DATABASE_URL")
	if dsn == "" {
		t.Skip("admin test DSN unset")
	}
	r, err := New(context.Background(), dsn, "test")
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	if _, err = r.DatasetStatus(context.Background(), testScope(1)); err == nil {
		t.Fatal("superuser query access accepted")
	}
}
