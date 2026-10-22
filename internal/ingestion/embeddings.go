package ingestion

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/jackc/pgx/v5"
	"io"
	"math"
	"net/http"
	"net/url"
	"os"
	"time"
)

const EmbeddingModel = "intfloat/multilingual-e5-small"
const EmbeddingRevision = "614241f622f53c4eeff9890bdc4f31cfecc418b3"

// EmbedDocuments sends fictional SOP passages to an explicitly local model service.
func EmbedDocuments(ctx context.Context, dsn, endpoint, token string) (map[string]any, error) {
	u, err := url.Parse(endpoint)
	if err != nil {
		return nil, err
	}
	if u.Scheme != "http" || (u.Hostname() != "127.0.0.1" && u.Hostname() != "localhost" && u.Hostname() != "::1" && u.Hostname() != "voice") {
		return nil, fmt.Errorf("embedding endpoint must be local HTTP")
	}
	if token == "" {
		return nil, fmt.Errorf("internal model token is required")
	}
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		return nil, err
	}
	defer conn.Close(ctx)
	rows, err := conn.Query(ctx, "SELECT id,title,content FROM documents ORDER BY id LIMIT 10001")
	if err != nil {
		return nil, err
	}
	type document struct {
		id   int64
		text string
	}
	docs := []document{}
	for rows.Next() {
		var id int64
		var title, content string
		if err = rows.Scan(&id, &title, &content); err != nil {
			return nil, err
		}
		docs = append(docs, document{id, title + "\n" + content})
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	if len(docs) > 10000 {
		return nil, fmt.Errorf("document corpus exceeds bounded embedding batch operation")
	}
	client := http.Client{Timeout: 90 * time.Second}
	embedded := 0
	for start := 0; start < len(docs); start += 32 {
		batch := docs[start:min(start+32, len(docs))]
		texts := []string{}
		for _, doc := range batch {
			texts = append(texts, doc.text)
		}
		body, _ := json.Marshal(map[string]any{"texts": texts, "kind": "passage"})
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("Content-Type", "application/json")
		resp, err := client.Do(req)
		if err != nil {
			return nil, err
		}
		raw, err := io.ReadAll(io.LimitReader(resp.Body, 2<<20))
		resp.Body.Close()
		if err != nil {
			return nil, err
		}
		if resp.StatusCode != 200 {
			return nil, fmt.Errorf("embedding service returned %d", resp.StatusCode)
		}
		var result struct {
			Vectors    [][]float64 `json:"vectors"`
			Model      string      `json:"model"`
			Revision   string      `json:"revision"`
			Dimensions int         `json:"dimensions"`
		}
		if err = json.Unmarshal(raw, &result); err != nil {
			return nil, err
		}
		if result.Model != EmbeddingModel || result.Revision != EmbeddingRevision || result.Dimensions != 384 || len(result.Vectors) != len(batch) {
			return nil, fmt.Errorf("embedding model provenance mismatch")
		}
		tx, err := conn.Begin(ctx)
		if err != nil {
			return nil, err
		}
		if _, err = tx.Exec(ctx, "SET LOCAL ROLE data_mind_writer"); err != nil {
			tx.Rollback(ctx)
			return nil, err
		}
		for i, vector := range result.Vectors {
			norm := 0.0
			if len(vector) != 384 {
				tx.Rollback(ctx)
				return nil, fmt.Errorf("wrong vector dimensions")
			}
			for _, value := range vector {
				if math.IsNaN(value) || math.IsInf(value, 0) {
					tx.Rollback(ctx)
					return nil, fmt.Errorf("invalid vector value")
				}
				norm += value * value
			}
			if math.Abs(norm-1) > 0.02 {
				tx.Rollback(ctx)
				return nil, fmt.Errorf("vector is not normalized")
			}
			serialized, _ := json.Marshal(vector)
			if _, err = tx.Exec(ctx, "UPDATE documents SET embedding=$1::vector,embedding_model=$2,embedding_revision=$3 WHERE id=$4", string(serialized), result.Model, result.Revision, batch[i].id); err != nil {
				tx.Rollback(ctx)
				return nil, err
			}
			embedded++
		}
		if err = tx.Commit(ctx); err != nil {
			return nil, err
		}
	}
	return map[string]any{"embedded_documents": embedded, "dimensions": 384, "model": EmbeddingModel, "revision": EmbeddingRevision}, nil
}
func ModelToken() string {
	for _, key := range []string{"MODEL_INTERNAL_TOKEN", "VOICE_INTERNAL_TOKEN", "MCP_INTERNAL_TOKEN"} {
		if value := os.Getenv(key); value != "" {
			return value
		}
	}
	return ""
}
