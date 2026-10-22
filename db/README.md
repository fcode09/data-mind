# Synthetic PostgreSQL data

The supported loader is Go: `go run ./apps/worker`. It never reads a real database or personal dataset.

- `migrate --vectors`: core tables, forced RLS, optional pgvector and embedding provenance.
- `seed --rows 1000000 --seed 42 --batch-key demo-million`: deterministic fictional incidents, five tenants, 730 days and 100 SOP sections.
- `verify --batch-key demo-million`: compare SQL counts, tenant/category counts, resolved counts and total durations against the independently accumulated generator manifest.
- `append-day --rows 10000 --anchor 2026-10-24T00:00:00Z --batch-key day-2026-10-24`: idempotent additional day with non-overlapping IDs.
- `embed-documents --embedding-url http://127.0.0.1:8102/embed`: explicitly index SOP passages using the pinned local model; requires its internal token and prepared model service.

DATABASE_ADMIN_URL is the separate administrative synthetic DSN. DATABASE_URL is the restricted runtime login. Migrations create NOLOGIN reader/writer roles; provision your local login and grant reader membership through your normal administration workflow. Do not use a superuser or BYPASSRLS login for API/MCP.

Generation copies bounded batches into transaction-local staging, then inserts through the writer role, because PostgreSQL does not allow COPY directly into an RLS table. Checkpoints resume interrupted batches. Same batch key with a different generation specification fails. Manifests are independently accumulated counts and durations; they are not claimed to be row-by-row cryptographic content proofs. Python reference and Go generators agree on the million-row golden numerical oracle.

All reader queries use explicit tenant/date predicates, forced RLS and a read-only repeatable-read transaction. Full totals are computed before pagination. Resolution median/percentiles are exact SQL with a366-day budget. Retrieval scores are similarity/ranking signals, not calibrated probabilities. Query and passage embeddings must share pinned model revision; stale/mixed-model rows are excluded.
