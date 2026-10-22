package main

import (
	"context"
	"github.com/fcode09/data-mind/internal/data"
	"github.com/fcode09/data-mind/internal/mcpserver"
	"log"
	"net/http"
	"os"
	"time"
)

func main() {
	repo, err := data.New(context.Background(), os.Getenv("DATABASE_URL"), os.Getenv("CURSOR_SECRET"))
	if err != nil {
		log.Fatal(err)
	}
	defer repo.Close()
	addr := os.Getenv("MCP_ADDR")
	if addr == "" {
		addr = "127.0.0.1:8101"
	}
	server := &http.Server{Addr: addr, Handler: mcpserver.Handler(repo, os.Getenv("MCP_INTERNAL_TOKEN")), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 20 * time.Second, IdleTimeout: 60 * time.Second}
	log.Fatal(server.ListenAndServe())
}
