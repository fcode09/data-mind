# Implementation contract

Five applications share typed contracts: web, api, mcp, voice and worker.
Python imports are rooted at `packages/data_mind`. API and MCP use `data_mind.repository.Repository`.
Repository methods: `dataset_status(scope)`, `incidents_summary(scope, group_by='category', limit=20)`, `incidents_timeseries(scope)`, `incidents_search(scope, text='', limit=20, cursor=None)`, `incident_detail(scope, incident_id)`, `resolution_statistics(scope)`, `knowledge_search(scope, query, limit=5)` return Evidence models (dataset_status may return a plain dict).
Configuration uses DATABASE_URL, MCP_URL, MCP_INTERNAL_TOKEN, API_SESSION_SECRET and VOICE_URL. Real data and cloud inference are out of scope. UI language Spanish; code and docs English.
