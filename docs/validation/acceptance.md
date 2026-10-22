# Acceptance evidence and remaining limits

Validated on 2026-10-22 in a Linux CPU workspace. This report separates actual executions from implementation or configuration only. No production database or private dataset was used.

## Passed with real components

1. **Go ingestion:** 1,000,000 synthetic incidents generated, COPY-staged, inserted and independently verified in 55.04 seconds. Five tenant totals: 200330,199836,200312,199673,199849. Resolved count 333291; duration sum 28855234742 seconds. The Go generator agrees with the separately established Python numerical oracle. This is not a row-by-row cryptographic content proof. A separate repeated daily append was verified idempotent.
2. **PostgreSQL 17.11 + pgvector 0.8.0:** all seven Go query methods, exact counts/medians, bounded pagination, tenant isolation, pooled-context changes, read-only repeatable-read transactions and rejection of superuser login passed. Hybrid fixtures excluded other tenants and stale model revisions.
3. **Official Go MCP SDK 1.8.0:** real Streamable HTTP initialize/list/tool roundtrips passed. Go API→Go MCP→PostgreSQL returned verified counts and filtered queries, not a direct repository shortcut.
4. **Full million-row stack:** all five signed demo tenants matched the independent manifest.20 sequential count turns measured p50=0.272s, p95=0.286s. These are local warm/sequential observations, not production concurrency or an SLA.
5. **Real semantic retrieval:** all 100 fictional SOP sections were embedded locally using pinned multilingual-e5-small, 384 dimensions. Go ingestion stored model/revision provenance; a real query ranked Alumbrado SOPs first. API→MCP used hybrid_exact_cosine_rrf with actual model vectors. Cosine/ranking scores are not calibrated confidence.
6. **Real local Spanish voice:** Kokoro generated “Déjame consultar.”; faster-whisper transcribed it exactly. Authenticated service calls, then Go API voice proxy and verified-answer TTS passed. The integrated verified answer produced a 13.425-second WAV. A generated spoken question was transcribed and answered. Clarification speech was rejected 409. These are synthetic audio tests, not a real microphone test.
7. **Real local LLM:** actual Go typed-intent adapter passed against official llama.cpp/Qwen3-0.6B Q8_0 after fixing an invented-filter failure. This is not a broad model-quality evaluation or an 8B benchmark.
8. **Frontend:** 11 Vitest tests, TypeScript checks and Vite production build passed. Clarifications, stale cancellation and empty-transcription recovery have explicit tests.
9. **Python services:** 13 unit/contract tests passed for authentication, limits, missing models, archives/hash refusal, inference process timeout and embedding contracts. Fake-adapter tests are not counted as real-model evidence; real-model runs are separately listed above.
10. **Go checks:** unit, official-SDK fixture and environment-gated PostgreSQL/model integration tests passed in their documented runs; go vet passed. Go API, MCP and worker also cross-compiled successfully for Windows amd64 with CGO disabled; no Windows runtime execution is claimed.

See full-stack-results.json and million-row-manifest.json for machine-readable non-sensitive evidence. Test fixtures, generated datasets, model weights, credentials and audio are not committed.

## Local CPU voice observations

- TTS cold 8.30 s, warm 0.93 s; fixed acknowledgement WAV 1.475 s.
- STT cold 5.05 s, warm 2.73 s on that generated phrase.
- Embedding cold query 12.70 s; warm two-passage batch 46.8 ms with two CPU threads.
- Model warm-up matters. A 3 s semantic query budget can fall back truthfully to full-text search on a cold model. Explicit SOP indexing/prewarm avoids assuming cold startup is fast.

Single observations are not latency percentiles. No GPU benchmark is claimed.

## Not yet validated or intentionally limited

- **Browser wake/microphone end-to-end:** implemented, but browser launch was blocked by the execution sandbox. No hardware microphone, actual Windows/Arch browser, acoustic echo cancellation or background-tab operation is claimed. The user should test consent, “Hola asistente”, pause, question, stop and recovery on their actual machine.
- **Docker/Podman execution:** configuration supplied; engines were unavailable in the test workspace. No container build or Compose smoke pass is claimed.
- **10 million rows, concurrent 1/3/5 voice sessions, GPU latency, production deployment:** not run.
- **Streaming/barge-in:** baseline is bounded utterance HTTP, not Pipecat/WebRTC streaming or tested voice barge-in. Cancellation stops client playback and stale responses; running inference is bounded by service deadlines.
- **Authentication:** signed synthetic demo sessions, not production OIDC. No real data should be exposed through DEMO_MODE.
- **Semantic no-answer:** retrieval is scoped and cited; similarity scores are not proof of relevance. There is no calibrated universal similarity cutoff or broad domain evaluation.
- **Learning:** feedback is persisted and evaluation/review gates are documented and tested through golden invariants. No autonomous code changes, private-data training or automatic model promotion occurs.
- **Upstream dependency risk:** npm audit reported two moderate dependency entries associated with vosk-browser/uuid, with no upstream fixed wrapper available. High/critical findings were removed by updating Vite/Vitest. Review before wider distribution; do not claim a fake override fixes bundled code.
- **Licensing:** original project license was not silently chosen. Dependencies and model weights have separate licenses.

## Reproduce core gates

```sh
go test ./...
go vet ./...
python -m pytest tests -q
cd apps/web && npm test && npm run build
```

Set TEST_DATABASE_URL to a restricted synthetic test database for Go PostgreSQL tests. ADMIN_DATABASE_URL is used only by explicit fixture tests. Set RUN_HYBRID_FIXTURE_TEST=true only for the explicitly synthetic vector fixture write/cleanup test. Set LOCAL_LLM_TEST_URL for the real model adapter test. Use docs/voice.md and docs/embeddings.md for real local model runs. Never run fixtures against production.
