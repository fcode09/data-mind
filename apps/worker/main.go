// Worker provides explicit administrative commands for fictional data only.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/fcode09/data-mind/internal/ingestion"
	"os"
	"time"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: worker migrate|seed|append-day|verify [flags]")
		os.Exit(2)
	}
	command := os.Args[1]
	f := flag.NewFlagSet(command, flag.ExitOnError)
	url := f.String("database-url", os.Getenv("DATABASE_ADMIN_URL"), "Administrative synthetic database URL")
	defaultRows := int64(1000000)
	if command == "append-day" {
		defaultRows = 10000
	}
	rows := f.Int64("rows", defaultRows, "Rows, maximum 10M")
	seed := f.Uint64("seed", 42, "Deterministic seed")
	anchorText := f.String("anchor", "2026-10-23T00:00:00Z", "Exclusive UTC demo clock")
	batch := f.Int("batch-size", 10000, "Bounded batch size")
	offset := f.Int64("offset", 0, "First ID offset")
	key := f.String("batch-key", "", "Idempotency key")
	embeddingURL := f.String("embedding-url", os.Getenv("EMBEDDING_URL"), "Local embedding endpoint")
	vectors := f.Bool("vectors", false, "Apply pgvector migration")
	manifestPath := f.String("manifest-output", "", "Write independent manifest JSON")
	f.Parse(os.Args[2:])
	if *url == "" {
		fatal(fmt.Errorf("DATABASE_ADMIN_URL is required; never use production data"))
	}
	ctx := context.Background()
	var result any
	var err error
	switch command {
	case "migrate":
		err = ingestion.Migrate(ctx, *url, *vectors)
		result = map[string]bool{"migrated": err == nil}
	case "embed-documents":
		result, err = ingestion.EmbedDocuments(ctx, *url, *embeddingURL, ingestion.ModelToken())
	case "verify":
		result, err = ingestion.Verify(ctx, *url, *key)
	case "seed", "append-day":
		anchor, e := time.Parse(time.RFC3339, *anchorText)
		if e != nil {
			fatal(e)
		}
		days := 730
		if command == "append-day" {
			days = 1
			if *offset == 0 {
				*offset = anchor.Unix() / 86400 * 10000000
			}
			if *key == "" {
				*key = "day-" + anchor.Format("2006-01-02")
			}
		}
		result, err = ingestion.Seed(ctx, *url, ingestion.Spec{Rows: *rows, Seed: *seed, Anchor: anchor, Days: days, Offset: *offset, BatchSize: *batch, Key: *key})
	default:
		err = fmt.Errorf("unknown command %q", command)
	}
	if err != nil {
		fatal(err)
	}
	raw, _ := json.MarshalIndent(result, "", "  ")
	if *manifestPath != "" {
		if err = os.WriteFile(*manifestPath, raw, 0600); err != nil {
			fatal(err)
		}
	}
	fmt.Println(string(raw))
}
func fatal(err error) { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
