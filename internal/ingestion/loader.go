package ingestion

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/jackc/pgx/v5"
	"os"
	"path/filepath"
	"time"
)

var columns = []string{"id", "synthetic_id", "tenant_id", "event_at", "category", "status", "sector", "resolved_at", "description", "batch_key"}

const columnsSQL = "id,synthetic_id,tenant_id,event_at,category,status,sector,resolved_at,description,batch_key"

func Migrate(ctx context.Context, url string, vectors bool) error {
	conn, err := pgx.Connect(ctx, url)
	if err != nil {
		return err
	}
	defer conn.Close(ctx)
	files := []string{"001_initial.sql"}
	if vectors {
		files = append(files, "002_optional_vectors.sql", "003_embedding_provenance.sql")
	}
	for _, name := range files {
		raw, e := os.ReadFile(filepath.Join("db", "migrations", name))
		if e != nil {
			return e
		}
		if _, e = conn.Exec(ctx, string(raw)); e != nil {
			return e
		}
	}
	return nil
}
func Seed(ctx context.Context, url string, s Spec) (map[string]any, error) {
	if err := s.Validate(); err != nil {
		return nil, err
	}
	started := time.Now()
	version := s.Version()
	key := s.Key
	if key == "" {
		key = "go-base-" + version[:16]
	}
	conn, err := pgx.Connect(ctx, url)
	if err != nil {
		return nil, err
	}
	defer conn.Close(ctx)
	if _, err = conn.Exec(ctx, "SELECT pg_advisory_lock(hashtext($1))", key); err != nil {
		return nil, err
	}
	defer conn.Exec(context.Background(), "SELECT pg_advisory_unlock(hashtext($1))", key)
	tx, err := conn.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, "SET LOCAL ROLE data_mind_writer"); err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx, "INSERT INTO ingestion_batches(batch_key,dataset_version,expected_rows) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", key, version, s.Rows); err != nil {
		return nil, err
	}
	var checkpoint int64
	var previous string
	if err = tx.QueryRow(ctx, "SELECT checkpoint,dataset_version FROM ingestion_batches WHERE batch_key=$1 FOR UPDATE", key).Scan(&checkpoint, &previous); err != nil {
		return nil, err
	}
	if previous != version {
		return nil, fmt.Errorf("batch key belongs to a different generation specification")
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	manifest := NewManifest()
	for first := int64(1); first <= s.Rows; first += int64(s.BatchSize) {
		last := min(s.Rows, first+int64(s.BatchSize)-1)
		batch := make([][]any, 0, last-first+1)
		for i := first; i <= last; i++ {
			row := Incident(s.Offset+i, s.Seed, s.Anchor, s.Days, key)
			manifest.Add(row)
			if i > checkpoint {
				batch = append(batch, row)
			}
		}
		if len(batch) == 0 {
			continue
		}
		tx, err = conn.Begin(ctx)
		if err != nil {
			return nil, err
		}
		fail := func(e error) (map[string]any, error) { tx.Rollback(ctx); return nil, e }
		if _, err = tx.Exec(ctx, "SET LOCAL ROLE data_mind_writer"); err != nil {
			return fail(err)
		}
		if _, err = tx.Exec(ctx, "CREATE TEMP TABLE seed_stage ON COMMIT DROP AS SELECT "+columnsSQL+" FROM incidents WITH NO DATA"); err != nil {
			return fail(err)
		}
		if _, err = tx.CopyFrom(ctx, pgx.Identifier{"seed_stage"}, columns, pgx.CopyFromRows(batch)); err != nil {
			return fail(err)
		}
		if _, err = tx.Exec(ctx, "INSERT INTO incidents("+columnsSQL+") SELECT "+columnsSQL+" FROM seed_stage"); err != nil {
			return fail(err)
		}
		if _, err = tx.Exec(ctx, "UPDATE ingestion_batches SET checkpoint=$1,loaded_at=now() WHERE batch_key=$2", last, key); err != nil {
			return fail(err)
		}
		if err = tx.Commit(ctx); err != nil {
			return nil, err
		}
	}
	tx, err = conn.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, "SET LOCAL ROLE data_mind_writer"); err != nil {
		return nil, err
	}
	raw, _ := json.Marshal(manifest)
	if _, err = tx.Exec(ctx, "UPDATE ingestion_batches SET status='complete',manifest=$1,loaded_at=now() WHERE batch_key=$2", raw, key); err != nil {
		return nil, err
	}
	for tenant := 1; tenant <= 5; tenant++ {
		for index, category := range Categories {
			for section := 1; section <= 4; section++ {
				id := tenant*1000 + index*10 + section
				content := fmt.Sprintf("Procedimiento ficticio para %s. Paso %d: registrar el incidente, validar el sector y documentar la atención. El cierre requiere evidencia y revisión del responsable.", category, section)
				if _, err = tx.Exec(ctx, "INSERT INTO documents(id,tenant_id,title,content,version,section,effective_at) VALUES($1,$2,$3,$4,'1.0',$5,$6) ON CONFLICT DO NOTHING", id, tenant, "SOP ficticio: "+category, content, fmt.Sprintf("Sección %d", section), s.Anchor.AddDate(0, 0, -s.Days)); err != nil {
					return nil, err
				}
			}
		}
	}
	if _, err = tx.Exec(ctx, "DELETE FROM daily_metrics"); err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx, "INSERT INTO daily_metrics SELECT tenant_id,(event_at AT TIME ZONE 'America/Lima')::date,category,count(*),coalesce(sum(extract(epoch FROM resolved_at-event_at)),0),count(resolved_at) FROM incidents GROUP BY tenant_id,2,category"); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	return map[string]any{"batch_key": key, "dataset_version": version, "manifest": manifest, "elapsed_seconds": time.Since(started).Seconds()}, nil
}
func Verify(ctx context.Context, url, key string) (map[string]any, error) {
	conn, err := pgx.Connect(ctx, url)
	if err != nil {
		return nil, err
	}
	defer conn.Close(ctx)
	tx, err := conn.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, "SET LOCAL ROLE data_mind_writer"); err != nil {
		return nil, err
	}
	var raw []byte
	var status string
	if err = tx.QueryRow(ctx, "SELECT manifest,status FROM ingestion_batches WHERE batch_key=$1", key).Scan(&raw, &status); err != nil {
		return nil, err
	}
	if status != "complete" {
		return nil, fmt.Errorf("batch incomplete")
	}
	var expected Manifest
	if err = json.Unmarshal(raw, &expected); err != nil {
		return nil, err
	}
	actual := NewManifest()
	if err = tx.QueryRow(ctx, "SELECT count(*),count(resolved_at),coalesce(sum(extract(epoch FROM resolved_at-event_at)),0)::bigint FROM incidents WHERE batch_key=$1", key).Scan(&actual.Count, &actual.ResolvedCount, &actual.DurationSumSeconds); err != nil {
		return nil, err
	}
	for _, dimension := range []string{"tenant_id", "category"} {
		rows, e := tx.Query(ctx, "SELECT "+dimension+"::text,count(*) FROM incidents WHERE batch_key=$1 GROUP BY 1", key)
		if e != nil {
			return nil, e
		}
		for rows.Next() {
			var label string
			var count int64
			if e = rows.Scan(&label, &count); e != nil {
				return nil, e
			}
			if dimension == "tenant_id" {
				actual.Tenants[label] = count
			} else {
				actual.Categories[label] = count
			}
		}
		if e = rows.Err(); e != nil {
			return nil, e
		}
		rows.Close()
	}
	want, _ := json.Marshal(expected)
	got, _ := json.Marshal(actual)
	if string(want) != string(got) {
		return nil, fmt.Errorf("independent manifest mismatch")
	}
	return map[string]any{"verified": true, "batch_key": key, "actual": actual}, nil
}
