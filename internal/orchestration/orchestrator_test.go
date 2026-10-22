package orchestration

import (
	"context"
	"github.com/fcode09/data-mind/internal/contracts"
	"os"
	"testing"
	"time"
)

type caller struct {
	otherTenant bool
	args        map[string]any
}

func (c *caller) Call(_ context.Context, _ string, s contracts.Scope, args map[string]any) (contracts.Evidence, error) {
	c.args = args
	if c.otherTenant {
		s.TenantID = 2
	}
	return contracts.Evidence{QueryID: "fixture", DatasetVersion: "v", EffectiveScope: s, TotalMatching: 2, ReturnedRows: 1, Rows: []map[string]any{{"count": 2}}}, nil
}
func TestFiltersAndEvidence(t *testing.T) {
	scope := contracts.Scope{TenantID: 1, FromDate: "2026-01-01", ToDateExclusive: "2026-02-01", Timezone: "America/Lima"}
	c := &caller{}
	e := Engine{Tools: c}
	out, err := e.Answer(context.Background(), "Cuántos abiertos de alumbrado", scope)
	if err != nil || !out.Verified {
		t.Fatal(err)
	}
	if c.args["status"] != "Abierto" || c.args["category"] != "Alumbrado" {
		t.Fatal(c.args)
	}
	c.otherTenant = true
	if _, err = e.Answer(context.Background(), "cuántos", scope); err == nil {
		t.Fatal("mismatched tenant accepted")
	}
}
func TestClarification(t *testing.T) {
	s := contracts.Scope{TenantID: 1, FromDate: "2026-01-01", ToDateExclusive: "2026-02-01"}
	r, e := (Engine{}).Answer(context.Background(), "cuántos por prioridad", s)
	if e != nil || !r.Clarification || r.Verified {
		t.Fatal(r, e)
	}
}

func TestRejectInventedModelFilters(t *testing.T) {
	question := "¿Puedes darme un desglose por estado de las incidencias de alumbrado?"
	if groundedFilters(question, Intent{Tool: "incidents_search", GroupBy: "category", Category: "Alumbrado", Status: "Abierto"}) {
		t.Fatal("invented status accepted")
	}
	intent := Plan(question)
	if intent.Tool != "incidents_summary" || intent.GroupBy != "status" || intent.Status != "" {
		t.Fatal(intent)
	}
}

// TestLocalModelAdapter calls the real Go HTTP adapter, not the deterministic fast path.
func TestLocalModelAdapter(t *testing.T) {
	endpoint := os.Getenv("LOCAL_LLM_TEST_URL")
	if endpoint == "" {
		t.Skip("LOCAL_LLM_TEST_URL not configured")
	}
	model := os.Getenv("LOCAL_LLM_TEST_MODEL")
	if model == "" {
		model = "qwen3-test"
	}
	engine := Engine{LLMURL: endpoint, LLMModel: model}
	question := "¿Puedes darme un desglose por estado de las incidencias de alumbrado?"
	start := time.Now()
	intent, err := engine.modelIntent(context.Background(), question)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("Real local model intent after %s: %+v", time.Since(start), intent)
	if !validIntent(intent) || !groundedFilters(question, intent) {
		t.Fatalf("model result rejected by grounding gate: %+v", intent)
	}
	if intent.Tool != "incidents_summary" || intent.GroupBy != "status" || intent.Category != "Alumbrado" || intent.Status != "" {
		t.Fatalf("unexpected semantic intent: %+v", intent)
	}
}
