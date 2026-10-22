# Implementation contract

Five applications share typed contracts: web, api, mcp, voice and worker.

- Go API owns signed synthetic sessions, conversation turns, feedback persistence and verified-answer speech authorization.
- Go MCP exposes seven bounded tools through the official SDK: dataset_status, incidents_summary, incidents_timeseries, incidents_search, incident_detail, resolution_statistics and knowledge_search.
- Go PostgreSQL access lives in internal/data. Methods return internal/contracts.Evidence with exact tenant/date scope, source method, snapshot timestamp, totals and bounded records. No arbitrary SQL tool exists.
- Go worker owns reproducible synthetic ingestion and SOP embedding indexing. Python is only the local voice/model service. Archived Python backend code is reference material, not the active runtime.
- Python model endpoints use explicit bounded contracts; embeddings include pinned model/revision metadata and normalized 384-dimensional vectors.
- React/TypeScript client-facing text is Spanish. Code, identifiers and documentation are English.

Configuration uses DATABASE_URL, MCP_URL, MCP_INTERNAL_TOKEN, API_SESSION_SECRET and VOICE_URL. Optional MODEL_INTERNAL_TOKEN overrides VOICE_INTERNAL_TOKEN for embeddings. Real data and cloud inference are outside this synthetic baseline. See .env.example and native setup for separate administrative ingestion credentials and internal runtime credentials.
