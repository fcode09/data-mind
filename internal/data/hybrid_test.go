package data

import (
	"context"
	"github.com/jackc/pgx/v5"
	"math"
	"os"
	"testing"
)

func TestVectorValidation(t *testing.T) {
	good := make([]float32, 384)
	good[0] = 1
	if _, err := vectorLiteral(good); err != nil {
		t.Fatal(err)
	}
	for _, bad := range [][]float32{nil, make([]float32, 383), make([]float32, 384)} {
		if _, err := vectorLiteral(bad); err == nil {
			t.Fatal("invalid vector accepted")
		}
	}
	for _, value := range []float32{float32(math.NaN()), float32(math.Inf(1)), 2} {
		bad := append([]float32{}, good...)
		bad[1] = value
		if _, err := vectorLiteral(bad); err == nil {
			t.Fatal("nonfinite or unnormalized vector accepted")
		}
	}
}
func TestPostgresHybridFixture(t *testing.T) {
	if os.Getenv("RUN_HYBRID_FIXTURE_TEST") != "true" {
		t.Skip("explicit synthetic vector fixture write opt-in required")
	}
	r := integrationRepository(t)
	ctx := context.Background()
	adminDSN := os.Getenv("ADMIN_DATABASE_URL")
	if adminDSN == "" {
		t.Skip("admin fixture DSN unset")
	}
	admin, err := pgx.Connect(ctx, adminDSN)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = admin.Close(context.Background()) })
	// These obvious unit vectors are fixture values, not a model quality test.
	// Use new high IDs and delete only those exact fixture rows at test cleanup.
	const firstID = int64(9223372036854775001)
	const foreignID = int64(9223372036854775002)
	const staleID = int64(9223372036854775003)
	first := make([]float32, 384)
	first[0] = 1
	v, _ := vectorLiteral(first)
	for _, fixture := range []struct {
		id     int64
		tenant int
	}{{firstID, 1}, {foreignID, 2}, {staleID, 1}} {
		_, err = admin.Exec(ctx, `INSERT INTO documents(id,tenant_id,title,content,version,section,effective_at,embedding,embedding_model,embedding_revision) VALUES($1,$2,'Hybrid fixture','Unique fixture retrieval','fixture-v1','test','2026-01-01',$3::vector,$4,$5)`, fixture.id, fixture.tenant, v, EmbeddingModel, EmbeddingRevision)
		if err != nil {
			t.Fatal(err)
		}
		if fixture.id == staleID {
			if _, err := admin.Exec(ctx, "UPDATE documents SET embedding_revision='stale-fixture-revision' WHERE id=$1", staleID); err != nil {
				t.Fatal(err)
			}
		}
		id := fixture.id
		t.Cleanup(func() {
			_, _ = admin.Exec(context.Background(), "DELETE FROM documents WHERE id=$1 AND version='fixture-v1'", id)
		})
	}
	out, err := r.KnowledgeSearchHybrid(ctx, testScope(1), "Unique fixture", 10, first)
	if err != nil {
		t.Fatal(err)
	}
	if out.AggregationMethod != "hybrid_exact_cosine_rrf" || len(out.Rows) == 0 {
		t.Fatal(out)
	}
	var seen bool
	for _, row := range out.Rows {
		if row["id"].(int64) == staleID {
			t.Fatal("stale model revision accepted")
		}
		if row["id"].(int64) == foreignID {
			t.Fatal("hybrid tenant leak")
		}
		if row["id"].(int64) == firstID {
			seen = true
			if row["embedding_revision"] != EmbeddingRevision {
				t.Fatal("missing model provenance")
			}
		}
	}
	if !seen {
		t.Fatal("known nearest fixture was not retrieved")
	}
}
