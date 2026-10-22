package mcpserver

import (
	"bytes"
	"context"
	"encoding/json"
	"github.com/fcode09/data-mind/internal/api"
	"github.com/fcode09/data-mind/internal/contracts"
	"github.com/fcode09/data-mind/internal/data"
	"github.com/fcode09/data-mind/internal/mcpclient"
	"github.com/fcode09/data-mind/internal/orchestration"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"
)

type fakeRepository struct{ Repository }

func (fakeRepository) IncidentsSummary(_ context.Context, s contracts.Scope, _ string, _ int, _ data.Filters) (contracts.Evidence, error) {
	return contracts.Evidence{QueryID: "fixture", DatasetVersion: "v1", EffectiveScope: s, AsOf: time.Now(), TotalMatching: 5, ReturnedRows: 1, Rows: []map[string]any{{"count": 5}}}, nil
}
func TestSDKRoundTrip(t *testing.T) {
	server := httptest.NewServer(Handler(fakeRepository{}, "test-token"))
	defer server.Close()
	response, err := http.Post(server.URL, "application/json", nil)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 401 {
		t.Fatal("unauthenticated request accepted")
	}
	scope := contracts.Scope{TenantID: 1, FromDate: "2026-01-01", ToDateExclusive: "2026-02-01", Timezone: "America/Lima"}
	client := mcpclient.Client{URL: server.URL, Token: "test-token"}
	result, err := client.Call(context.Background(), "incidents_summary", scope, nil)
	if err != nil {
		t.Fatal(err)
	}
	if result.TotalMatching != 5 {
		t.Fatalf("wrong evidence: %+v", result)
	}
	bad := mcpclient.Client{URL: server.URL, Token: "wrong"}
	if _, err = bad.Call(context.Background(), "incidents_summary", scope, nil); err == nil {
		t.Fatal("bad token accepted")
	}
}

func TestPostgresSDKAndAPI(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not configured")
	}
	repo, err := data.New(context.Background(), dsn, "integration-cursor-key")
	if err != nil {
		t.Fatal(err)
	}
	defer repo.Close()
	server := httptest.NewServer(Handler(repo, "integration-token"))
	defer server.Close()
	client := mcpclient.Client{URL: server.URL, Token: "integration-token"}
	scope := contracts.Scope{TenantID: 1, FromDate: "2024-10-22", ToDateExclusive: "2026-10-24", Timezone: "America/Lima"}
	evidence, err := client.Call(context.Background(), "incidents_summary", scope, nil)
	if err != nil {
		t.Fatal(err)
	}
	if evidence.TotalMatching < 100000 {
		t.Fatalf("expected million-row dataset tenant slice, got %d", evidence.TotalMatching)
	}
	var sum float64
	for _, row := range evidence.Rows {
		sum += row["count"].(float64)
	}
	if int64(sum) != evidence.TotalMatching {
		t.Fatal("MCP aggregate total mismatch")
	}
	t.Logf("Real Go MCP returned %d exact tenant rows, dataset %s", evidence.TotalMatching, evidence.DatasetVersion)
	handler, err := api.New(api.Config{Demo: true, Secret: "integration-session"}, orchestration.Engine{Tools: client})
	if err != nil {
		t.Fatal(err)
	}
	call := func(path, token string, value any) *httptest.ResponseRecorder {
		raw, _ := json.Marshal(value)
		r := httptest.NewRequest("POST", path, bytes.NewReader(raw))
		if token != "" {
			r.Header.Set("Authorization", "Bearer "+token)
		}
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		return w
	}
	session := call("/api/session", "", map[string]int{"tenant_id": 1})
	var auth map[string]any
	json.Unmarshal(session.Body.Bytes(), &auth)
	turn := call("/api/turns", auth["token"].(string), map[string]string{"turn_id": "integration-turn-001", "message": "Cuántos abiertos de alumbrado", "from_date": scope.FromDate, "to_date_exclusive": scope.ToDateExclusive})
	if turn.Code != 200 {
		t.Fatal(turn.Code, turn.Body.String())
	}
	var result orchestration.Result
	json.Unmarshal(turn.Body.Bytes(), &result)
	if !result.Verified || result.Evidence == nil || result.Evidence.TotalMatching <= 0 {
		t.Fatal(turn.Body.String())
	}
	t.Logf("Go API -> official MCP -> PostgreSQL filtered answer: %s", result.Answer)
}
