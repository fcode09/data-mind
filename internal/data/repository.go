// Package data implements bounded, tenant-scoped PostgreSQL queries.
package data

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/fcode09/data-mind/internal/contracts"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Filters struct {
	Category string `json:"category,omitempty"`
	Status   string `json:"status,omitempty"`
}

var Categories = []string{"Limpieza pública", "Alumbrado", "Vías", "Áreas verdes", "Seguridad vial"}
var Statuses = []string{"Abierto", "En proceso", "Resuelto"}

type Repository struct {
	pool         *pgxpool.Pool
	cursorSecret []byte
}

func New(ctx context.Context, databaseURL, cursorSecret string) (*Repository, error) {
	if databaseURL == "" {
		return nil, errors.New("DATABASE_URL is required")
	}
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, err
	}
	cfg.MaxConns = 8
	cfg.MinConns = 0
	cfg.ConnConfig.ConnectTimeout = 5 * time.Second
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	secret := []byte(cursorSecret)
	if len(secret) == 0 {
		secret = make([]byte, 32)
		if _, err = rand.Read(secret); err != nil {
			pool.Close()
			return nil, err
		}
	}
	return &Repository{pool: pool, cursorSecret: secret}, nil
}
func (r *Repository) Close() { r.pool.Close() }
func contains(options []string, value string) bool {
	for _, option := range options {
		if option == value {
			return true
		}
	}
	return false
}
func limitCheck(limit, max int) error {
	if limit < 1 || limit > max {
		return fmt.Errorf("limit must be between 1 and %d", max)
	}
	return nil
}
func filter(scope contracts.Scope, f Filters) (string, []any, error) {
	start, end, err := scope.UTCBounds()
	if err != nil {
		return "", nil, err
	}
	args := []any{scope.TenantID, start, end}
	where := "tenant_id=$1 AND event_at >= $2 AND event_at < $3"
	if f.Category != "" {
		if !contains(Categories, f.Category) {
			return "", nil, errors.New("unknown category")
		}
		args = append(args, f.Category)
		where += fmt.Sprintf(" AND category=$%d", len(args))
	}
	if f.Status != "" {
		if !contains(Statuses, f.Status) {
			return "", nil, errors.New("unknown status")
		}
		args = append(args, f.Status)
		where += fmt.Sprintf(" AND status=$%d", len(args))
	}
	return where, args, nil
}
func queryMaps(ctx context.Context, tx pgx.Tx, sql string, args ...any) ([]map[string]any, error) {
	rows, err := tx.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]map[string]any, 0)
	fields := rows.FieldDescriptions()
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return nil, err
		}
		row := make(map[string]any, len(values))
		for i, v := range values {
			row[fields[i].Name] = v
		}
		result = append(result, row)
	}
	return result, rows.Err()
}

type result struct {
	rows              []map[string]any
	total             int64
	truncated         bool
	method            string
	sources, warnings []string
	cursor            *string
}

func (r *Repository) read(ctx context.Context, scope contracts.Scope, fn func(context.Context, pgx.Tx) (result, error)) (contracts.Evidence, error) {
	scope = scope.Normalize()
	if err := scope.Validate(); err != nil {
		return contracts.Evidence{}, err
	}
	ctx, cancel := context.WithTimeout(ctx, 8*time.Second)
	defer cancel()
	tx, err := r.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return contracts.Evidence{}, err
	}
	defer tx.Rollback(context.Background())
	var super, bypass bool
	if err = tx.QueryRow(ctx, "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").Scan(&super, &bypass); err != nil {
		return contracts.Evidence{}, err
	}
	if super || bypass {
		return contracts.Evidence{}, errors.New("query login must not be superuser or BYPASSRLS")
	}
	if _, err = tx.Exec(ctx, "SET LOCAL ROLE data_mind_reader"); err != nil {
		return contracts.Evidence{}, err
	}
	if _, err = tx.Exec(ctx, "SELECT set_config('app.tenant_id',$1,true),set_config('statement_timeout','5000',true)", strconv.Itoa(scope.TenantID)); err != nil {
		return contracts.Evidence{}, err
	}
	data, err := fn(ctx, tx)
	if err != nil {
		return contracts.Evidence{}, err
	}
	var watermark *time.Time
	if err = tx.QueryRow(ctx, "SELECT max(event_at) FROM incidents WHERE tenant_id=$1", scope.TenantID).Scan(&watermark); err != nil {
		return contracts.Evidence{}, err
	}
	batches, err := queryMaps(ctx, tx, "SELECT batch_key,dataset_version,checkpoint,status FROM ingestion_batches ORDER BY batch_key")
	if err != nil {
		return contracts.Evidence{}, err
	}
	raw, err := json.Marshal(batches)
	if err != nil {
		return contracts.Evidence{}, err
	}
	digest := sha256.Sum256(raw)
	id := make([]byte, 16)
	if _, err = rand.Read(id); err != nil {
		return contracts.Evidence{}, err
	}
	if data.method == "" {
		data.method = "exact"
	}
	if data.sources == nil {
		data.sources = []string{"synthetic:incidents"}
	}
	if data.warnings == nil {
		data.warnings = []string{}
	}
	if data.rows == nil {
		data.rows = []map[string]any{}
	}
	evidence := contracts.Evidence{QueryID: hex.EncodeToString(id), DatasetVersion: hex.EncodeToString(digest[:])[:16], EffectiveScope: scope, AsOf: time.Now().UTC(), EventWatermark: watermark, TotalMatching: data.total, ReturnedRows: len(data.rows), Truncated: data.truncated, Rows: data.rows, AggregationMethod: data.method, Sources: data.sources, Warnings: data.warnings, NextCursor: data.cursor}
	if err = tx.Commit(ctx); err != nil {
		return contracts.Evidence{}, err
	}
	return evidence, nil
}
func (r *Repository) DatasetStatus(ctx context.Context, scope contracts.Scope) (contracts.Evidence, error) {
	return r.read(ctx, scope, func(ctx context.Context, tx pgx.Tx) (result, error) {
		rows, err := queryMaps(ctx, tx, "SELECT count(*) count,min(event_at) first_event,max(event_at) last_event FROM incidents WHERE tenant_id=$1", scope.TenantID)
		if err != nil {
			return result{}, err
		}
		return result{rows: rows, total: rows[0]["count"].(int64), sources: []string{"synthetic:dataset"}, warnings: []string{"Dataset availability covers the whole tenant history, not the selected date range."}}, nil
	})
}
func (r *Repository) IncidentsSummary(ctx context.Context, scope contracts.Scope, groupBy string, limit int, f Filters) (contracts.Evidence, error) {
	if !contains([]string{"category", "status", "sector"}, groupBy) {
		return contracts.Evidence{}, errors.New("unsupported grouping")
	}
	if err := limitCheck(limit, 100); err != nil {
		return contracts.Evidence{}, err
	}
	where, args, err := filter(scope, f)
	if err != nil {
		return contracts.Evidence{}, err
	}
	return r.read(ctx, scope, func(ctx context.Context, tx pgx.Tx) (result, error) {
		var total int64
		if err := tx.QueryRow(ctx, "SELECT count(*) FROM incidents WHERE "+where, args...).Scan(&total); err != nil {
			return result{}, err
		}
		rows, err := queryMaps(ctx, tx, fmt.Sprintf("SELECT %s AS label,count(*) AS count FROM incidents WHERE %s GROUP BY %s ORDER BY count(*) DESC,%s LIMIT $%d", groupBy, where, groupBy, groupBy, len(args)+1), append(args, limit+1)...)
		if err != nil {
			return result{}, err
		}
		truncated := len(rows) > limit
		if truncated {
			rows = rows[:limit]
		}
		return result{rows: rows, total: total, truncated: truncated}, nil
	})
}
func (r *Repository) IncidentsTimeseries(ctx context.Context, scope contracts.Scope, f Filters) (contracts.Evidence, error) {
	scope = scope.Normalize()
	where, args, err := filter(scope, f)
	if err != nil {
		return contracts.Evidence{}, err
	}
	args = append(args, scope.Timezone)
	return r.read(ctx, scope, func(ctx context.Context, tx pgx.Tx) (result, error) {
		rows, err := queryMaps(ctx, tx, fmt.Sprintf("SELECT to_char((event_at AT TIME ZONE $%d)::date,'YYYY-MM-DD') AS day,count(*) AS count FROM incidents WHERE %s GROUP BY day ORDER BY day", len(args), where), args...)
		if err != nil {
			return result{}, err
		}
		var total int64
		for _, row := range rows {
			total += row["count"].(int64)
		}
		return result{rows: rows, total: total}, nil
	})
}

type cursorPayload struct {
	Scope string    `json:"scope"`
	Time  time.Time `json:"time"`
	ID    int64     `json:"id"`
}

func scopeHash(scope contracts.Scope, text string, f Filters) string {
	raw, _ := json.Marshal([]any{scope.Normalize(), text, f})
	hash := sha256.Sum256(raw)
	return hex.EncodeToString(hash[:])
}
func (r *Repository) encodeCursor(scope string, row map[string]any) (string, error) {
	id, ok := row["id"].(int64)
	if !ok {
		return "", errors.New("invalid row ID")
	}
	at, ok := row["event_at"].(time.Time)
	if !ok {
		return "", errors.New("invalid event time")
	}
	raw, err := json.Marshal(cursorPayload{scope, at, id})
	if err != nil {
		return "", err
	}
	mac := hmac.New(sha256.New, r.cursorSecret)
	mac.Write(raw)
	return base64.RawURLEncoding.EncodeToString(append(raw, mac.Sum(nil)...)), nil
}
func (r *Repository) decodeCursor(cursor, scope string) (cursorPayload, error) {
	var value cursorPayload
	if len(cursor) > 2000 {
		return value, errors.New("invalid cursor")
	}
	raw, err := base64.RawURLEncoding.DecodeString(cursor)
	if err != nil || len(raw) <= 32 {
		return value, errors.New("invalid cursor")
	}
	payload, signature := raw[:len(raw)-32], raw[len(raw)-32:]
	mac := hmac.New(sha256.New, r.cursorSecret)
	mac.Write(payload)
	if !hmac.Equal(signature, mac.Sum(nil)) {
		return value, errors.New("invalid cursor")
	}
	if err = json.Unmarshal(payload, &value); err != nil || value.Scope != scope || value.ID < 1 || value.Time.IsZero() {
		return value, errors.New("invalid cursor or changed query scope")
	}
	return value, nil
}
func (r *Repository) IncidentsSearch(ctx context.Context, scope contracts.Scope, text string, limit int, cursor string, f Filters) (contracts.Evidence, error) {
	if err := limitCheck(limit, 100); err != nil {
		return contracts.Evidence{}, err
	}
	if len(text) > 300 {
		return contracts.Evidence{}, errors.New("search text too long")
	}
	where, args, err := filter(scope, f)
	if err != nil {
		return contracts.Evidence{}, err
	}
	if strings.TrimSpace(text) != "" {
		args = append(args, text)
		where += fmt.Sprintf(" AND search_vector @@ plainto_tsquery('spanish',$%d)", len(args))
	}
	hash := scopeHash(scope, text, f)
	var page cursorPayload
	if cursor != "" {
		page, err = r.decodeCursor(cursor, hash)
		if err != nil {
			return contracts.Evidence{}, err
		}
	}
	return r.read(ctx, scope, func(ctx context.Context, tx pgx.Tx) (result, error) {
		var total int64
		if err := tx.QueryRow(ctx, "SELECT count(*) FROM incidents WHERE "+where, args...).Scan(&total); err != nil {
			return result{}, err
		}
		queryWhere := where
		queryArgs := append([]any{}, args...)
		if cursor != "" {
			queryArgs = append(queryArgs, page.Time, page.ID)
			queryWhere += fmt.Sprintf(" AND (event_at,id) > ($%d,$%d)", len(queryArgs)-1, len(queryArgs))
		}
		queryArgs = append(queryArgs, limit+1)
		rows, err := queryMaps(ctx, tx, fmt.Sprintf("SELECT id,synthetic_id,event_at,category,status,sector,resolved_at,description FROM incidents WHERE %s ORDER BY event_at,id LIMIT $%d", queryWhere, len(queryArgs)), queryArgs...)
		if err != nil {
			return result{}, err
		}
		truncated := len(rows) > limit
		var next *string
		if truncated {
			rows = rows[:limit]
			encoded, err := r.encodeCursor(hash, rows[len(rows)-1])
			if err != nil {
				return result{}, err
			}
			next = &encoded
		}
		return result{rows: rows, total: total, truncated: truncated, cursor: next}, nil
	})
}
func (r *Repository) IncidentDetail(ctx context.Context, scope contracts.Scope, id int64) (contracts.Evidence, error) {
	if id < 1 {
		return contracts.Evidence{}, errors.New("incident ID must be positive")
	}
	where, args, err := filter(scope, Filters{})
	if err != nil {
		return contracts.Evidence{}, err
	}
	args = append(args, id)
	return r.read(ctx, scope, func(ctx context.Context, tx pgx.Tx) (result, error) {
		rows, err := queryMaps(ctx, tx, fmt.Sprintf("SELECT id,synthetic_id,event_at,category,status,sector,resolved_at,description FROM incidents WHERE %s AND id=$%d", where, len(args)), args...)
		if err != nil {
			return result{}, err
		}
		sources := []string{}
		if len(rows) > 0 {
			sources = append(sources, fmt.Sprintf("synthetic:incident:%d", id))
		}
		return result{rows: rows, total: int64(len(rows)), sources: sources}, nil
	})
}
func (r *Repository) ResolutionStatistics(ctx context.Context, scope contracts.Scope, f Filters) (contracts.Evidence, error) {
	if scope.Days() > 366 {
		return contracts.Evidence{}, errors.New("resolution statistics are limited to 366 days")
	}
	where, args, err := filter(scope, f)
	if err != nil {
		return contracts.Evidence{}, err
	}
	return r.read(ctx, scope, func(ctx context.Context, tx pgx.Tx) (result, error) {
		rows, err := queryMaps(ctx, tx, `SELECT count(*) AS matched_count,count(resolved_at) AS resolved_count,avg(extract(epoch FROM resolved_at-event_at))::float8 AS mean_seconds,percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM resolved_at-event_at)) AS median_seconds,min(extract(epoch FROM resolved_at-event_at))::float8 AS min_seconds,max(extract(epoch FROM resolved_at-event_at))::float8 AS max_seconds FROM incidents WHERE `+where, args...)
		if err != nil {
			return result{}, err
		}
		return result{rows: rows, total: rows[0]["matched_count"].(int64)}, nil
	})
}
func (r *Repository) KnowledgeSearch(ctx context.Context, scope contracts.Scope, query string, limit int) (contracts.Evidence, error) {
	if err := limitCheck(limit, 10); err != nil {
		return contracts.Evidence{}, err
	}
	if strings.TrimSpace(query) == "" || len(query) > 500 {
		return contracts.Evidence{}, errors.New("query must have 1 to 500 characters")
	}
	_, end, err := scope.UTCBounds()
	if err != nil {
		return contracts.Evidence{}, err
	}
	return r.read(ctx, scope, func(ctx context.Context, tx pgx.Tx) (result, error) {
		var total int64
		if err := tx.QueryRow(ctx, "SELECT count(*) FROM documents WHERE tenant_id=$1 AND effective_at<$2 AND search_vector @@ plainto_tsquery('spanish',$3)", scope.TenantID, end, query).Scan(&total); err != nil {
			return result{}, err
		}
		rows, err := queryMaps(ctx, tx, `SELECT id,title,content,version,section,effective_at,ts_rank(search_vector,plainto_tsquery('spanish',$3))::float8 AS score FROM documents WHERE tenant_id=$1 AND effective_at<$2 AND search_vector @@ plainto_tsquery('spanish',$3) ORDER BY score DESC,id LIMIT $4`, scope.TenantID, end, query, limit+1)
		if err != nil {
			return result{}, err
		}
		truncated := len(rows) > limit
		if truncated {
			rows = rows[:limit]
		}
		sources := []string{}
		for _, row := range rows {
			sources = append(sources, fmt.Sprintf("synthetic:document:%v:%v", row["id"], row["version"]))
		}
		return result{rows: rows, total: total, truncated: truncated, method: "full_text", sources: sources, warnings: []string{"PostgreSQL full-text retrieval; semantic embeddings are not enabled in this baseline."}}, nil
	})
}
