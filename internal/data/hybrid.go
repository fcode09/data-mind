package data

import (
	"context"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"

	"github.com/fcode09/data-mind/internal/contracts"
	"github.com/jackc/pgx/v5"
)

const EmbeddingModel = "intfloat/multilingual-e5-small"

// EmbeddingRevision is pinned to the same official model snapshot as the local
// embedding service. Re-embedding is required before this value may change.
const EmbeddingRevision = "614241f622f53c4eeff9890bdc4f31cfecc418b3"

func vectorLiteral(vector []float32) (string, error) {
	if len(vector) != 384 {
		return "", errors.New("query embedding must have 384 dimensions")
	}
	var norm float64
	values := make([]string, len(vector))
	for i, v := range vector {
		n := float64(v)
		if math.IsNaN(n) || math.IsInf(n, 0) {
			return "", errors.New("query embedding must contain only finite values")
		}
		norm += n * n
		values[i] = strconv.FormatFloat(n, 'g', -1, 32)
	}
	if math.Abs(norm-1) > 0.002 {
		return "", errors.New("query embedding must be unit normalized")
	}
	return "[" + strings.Join(values, ",") + "]", nil
}

// KnowledgeSearchHybrid fuses exact cosine and lexical ranks over a bounded SOP
// corpus. Vectors are produced by the separate authenticated local model service;
// this repository never calls a model, downloads weights, or fabricates vectors.
func (r *Repository) KnowledgeSearchHybrid(ctx context.Context, scope contracts.Scope, query string, limit int, queryVector []float32) (contracts.Evidence, error) {
	if err := limitCheck(limit, 10); err != nil {
		return contracts.Evidence{}, err
	}
	if strings.TrimSpace(query) == "" || len(query) > 500 {
		return contracts.Evidence{}, errors.New("query must have 1 to 500 characters")
	}
	vector, err := vectorLiteral(queryVector)
	if err != nil {
		return contracts.Evidence{}, err
	}
	_, end, err := scope.UTCBounds()
	if err != nil {
		return contracts.Evidence{}, err
	}
	return r.read(ctx, scope, func(ctx context.Context, tx pgx.Tx) (result, error) {
		var total int64
		if err := tx.QueryRow(ctx, `SELECT count(*) FROM documents WHERE tenant_id=$1 AND effective_at<$2 AND embedding IS NOT NULL AND embedding_model=$3 AND embedding_revision=$4`, scope.TenantID, end, EmbeddingModel, EmbeddingRevision).Scan(&total); err != nil {
			return result{}, err
		}
		if total == 0 {
			return result{}, errors.New("no documents embedded with the configured model revision; run embed-documents first")
		}
		if total > 10000 {
			return result{}, errors.New("exact hybrid retrieval is limited to 10000 eligible SOP chunks")
		}
		rows, err := queryMaps(ctx, tx, `WITH eligible AS MATERIALIZED (
   SELECT id,title,content,version,section,effective_at,embedding_model,embedding_revision,
    ts_rank(search_vector,plainto_tsquery('spanish',$3))::float8 lexical_score,
    (embedding <=> $4::vector)::float8 cosine_distance
   FROM documents WHERE tenant_id=$1 AND effective_at<$2 AND embedding IS NOT NULL
    AND embedding_model=$5 AND embedding_revision=$6
  ), ranked AS (
   SELECT *,row_number() OVER (ORDER BY cosine_distance,id) semantic_rank,
    row_number() OVER (ORDER BY lexical_score DESC,id) lexical_rank FROM eligible
  ) SELECT id,title,content,version,section,effective_at,embedding_model,embedding_revision,
    cosine_distance,lexical_score,
    (1.0/(60+semantic_rank)+CASE WHEN lexical_score>0 THEN 1.0/(60+lexical_rank) ELSE 0 END)::float8 AS score
   FROM ranked ORDER BY score DESC,id LIMIT $7`, scope.TenantID, end, query, vector, EmbeddingModel, EmbeddingRevision, limit)
		if err != nil {
			return result{}, err
		}
		sources := []string{"model:" + EmbeddingModel + "@" + EmbeddingRevision}
		for _, row := range rows {
			sources = append(sources, fmt.Sprintf("synthetic:document:%v:%v", row["id"], row["version"]))
		}
		return result{rows: rows, total: total, truncated: total > int64(limit), method: "hybrid_exact_cosine_rrf", sources: sources, warnings: []string{"Ranking scores are retrieval similarity, not factual confidence. Total matching counts eligible embedded chunks, not semantic relevance judgments."}}, nil
	})
}
