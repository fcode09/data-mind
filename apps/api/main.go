package main

import (
	"github.com/fcode09/data-mind/internal/api"
	"github.com/fcode09/data-mind/internal/mcpclient"
	"github.com/fcode09/data-mind/internal/orchestration"
	"log"
	"net/http"
	"os"
	"time"
)

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
func main() {
	tools := mcpclient.Client{URL: env("MCP_URL", "http://127.0.0.1:8101/mcp"), Token: os.Getenv("MCP_INTERNAL_TOKEN")}
	handler, err := api.New(api.Config{Demo: os.Getenv("DEMO_MODE") == "true", Secret: os.Getenv("API_SESSION_SECRET"), VoiceURL: env("VOICE_URL", "http://127.0.0.1:8102"), VoiceToken: env("VOICE_INTERNAL_TOKEN", os.Getenv("MCP_INTERNAL_TOKEN")), StatePath: env("API_STATE_PATH", "artifacts/api-state.json")}, orchestration.Engine{Tools: tools, LLMURL: os.Getenv("LLAMA_BASE_URL"), LLMModel: env("LLAMA_MODEL", "local")})
	if err != nil {
		log.Fatal(err)
	}
	server := &http.Server{Addr: env("API_ADDR", "127.0.0.1:8100"), Handler: handler, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 60 * time.Second, WriteTimeout: 100 * time.Second}
	log.Fatal(server.ListenAndServe())
}
