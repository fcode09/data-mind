package mcpserver

import (
	"context"
	"encoding/json"
	"github.com/fcode09/data-mind/internal/data"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestEmbeddingModelTokenAndProvenance(t *testing.T) {
	t.Setenv("MODEL_INTERNAL_TOKEN", "model-test-token")
	t.Setenv("VOICE_INTERNAL_TOKEN", "different-voice-token")
	vector := make([]float32, 384)
	vector[0] = 1
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer model-test-token" {
			t.Error("wrong model token")
		}
		json.NewEncoder(w).Encode(map[string]any{"vectors": [][]float32{vector}, "model": data.EmbeddingModel, "revision": data.EmbeddingRevision, "dimensions": 384, "normalized": true})
	}))
	defer server.Close()
	result, err := queryEmbedding(context.Background(), server.URL, "synthetic question")
	if err != nil || len(result) != 384 {
		t.Fatalf("embedding contract: %v", err)
	}
}
