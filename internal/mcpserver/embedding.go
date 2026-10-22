package mcpserver

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"github.com/fcode09/data-mind/internal/contracts"
	"github.com/fcode09/data-mind/internal/data"
	"io"
	"math"
	"net/http"
	"net/url"
	"os"
	"time"
)

type hybridRepository interface {
	KnowledgeSearchHybrid(context.Context, contracts.Scope, string, int, []float32) (contracts.Evidence, error)
}

func queryEmbedding(ctx context.Context, endpoint, query string) ([]float32, error) {
	u, err := url.Parse(endpoint)
	if err != nil {
		return nil, err
	}
	switch u.Hostname() {
	case "127.0.0.1", "localhost", "::1", "voice":
	default:
		return nil, errors.New("embedding endpoint must be local")
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	body, _ := json.Marshal(map[string]any{"texts": []string{query}, "kind": "query"})
	request, err := http.NewRequestWithContext(ctx, "POST", endpoint, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	token := os.Getenv("VOICE_INTERNAL_TOKEN")
	if token == "" {
		token = os.Getenv("MCP_INTERNAL_TOKEN")
	}
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("Content-Type", "application/json")
	response, err := (&http.Client{Timeout: 4 * time.Second}).Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return nil, errors.New("embedding unavailable")
	}
	var result struct {
		Vectors    [][]float32 `json:"vectors"`
		Model      string      `json:"model"`
		Dimensions int         `json:"dimensions"`
		Revision   string      `json:"revision"`
		Normalized bool        `json:"normalized"`
	}
	if json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&result) != nil || result.Model != data.EmbeddingModel || result.Revision != data.EmbeddingRevision || !result.Normalized || result.Dimensions != 384 || len(result.Vectors) != 1 || len(result.Vectors[0]) != 384 {
		return nil, errors.New("embedding contract mismatch")
	}
	var squared float64
	for _, v := range result.Vectors[0] {
		if math.IsNaN(float64(v)) || math.IsInf(float64(v), 0) {
			return nil, errors.New("invalid embedding")
		}
		squared += float64(v) * float64(v)
	}
	if squared < .95 || squared > 1.05 {
		return nil, errors.New("embedding must be normalized")
	}
	return result.Vectors[0], nil
}
func knowledge(ctx context.Context, repo Repository, input Input) (contracts.Evidence, error) {
	endpoint := os.Getenv("EMBEDDING_URL")
	if endpoint != "" {
		if hybrid, ok := repo.(hybridRepository); ok {
			vector, err := queryEmbedding(ctx, endpoint, input.Query)
			if err == nil {
				result, err := hybrid.KnowledgeSearchHybrid(ctx, input.Scope, input.Query, input.Limit, vector)
				if err == nil {
					return result, nil
				}
			}
		}
	}
	result, err := repo.KnowledgeSearch(ctx, input.Scope, input.Query, input.Limit)
	if endpoint != "" && err == nil {
		result.Warnings = append(result.Warnings, "Búsqueda semántica no disponible; se usó búsqueda de texto completo.")
	}
	return result, err
}
