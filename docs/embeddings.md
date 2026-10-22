# Local multilingual semantic embeddings

The Python model service exports `apps.voice.embeddings.router`. Mount it on the existing private voice/model FastAPI service. It adds authenticated `POST /embed` and does not change the Go API or PostgreSQL authorization boundary.

## Model and reproducibility

- Model: `intfloat/multilingual-e5-small`, MIT license, 384 dimensions.
- Immutable upstream revision: `614241f622f53c4eeff9890bdc4f31cfecc418b3`.
- Nine required files are pinned by SHA256 and size in `scripts/download_embedding_model.py`.
- Model weights use safetensors. Every pinned file is checked again before first runtime load.
- Sentence Transformers loads an existing local directory with `local_files_only=True` and `trust_remote_code=False`. Offline environment flags prevent runtime model downloads.
- Queries use `query: `; documents use `passage: `, including Spanish text. Both are normalized with the same model and a 512-token maximum.
- The repository does not bundle weights or grant additional licenses to the original project.

Primary sources: [official model card](https://huggingface.co/intfloat/multilingual-e5-small), [pinned model files](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3), [Sentence Transformers documentation](https://www.sbert.net/docs/package_reference/sentence_transformer/SentenceTransformer.html).

## Explicit setup

```sh
python -m pip install sentence-transformers==6.2.0
python scripts/download_embedding_model.py
```

The validated environment used CPU-only PyTorch `2.14.1+cpu`, Transformers `5.20.2` and Sentence Transformers `6.2.0`. Follow the official PyTorch CPU installation instructions rather than inadvertently installing large CUDA runtimes on CPU-only hosts.

Set `EMBEDDING_MODEL_DIR` to the existing model directory (default `models/cache/multilingual-e5-small`). Set `MODEL_INTERNAL_TOKEN`, or use the existing `VOICE_INTERNAL_TOKEN`/`MCP_INTERNAL_TOKEN` fallback. Native Windows and Linux use the same Python implementation; this test ran on Linux only. Set `OMP_NUM_THREADS=2` and `MKL_NUM_THREADS=2` as a starting point for CPU evaluation, not a universal tuning claim.

## API contract

```json
{"texts":["¿Cómo atender una luminaria apagada?"],"kind":"query"}
```

The response contains `vectors`, `dimensions`, `model`, `revision`, `normalized` and `kind`. Send `Authorization: Bearer <internal token>`. Persist model and revision beside each document vector and reject mixed encoders. Never expose `/embed` directly to unauthenticated browsers.

Limits: 1–32 texts; 1–2,000 characters per text; one inference call at a time; batch size 8; CPU-only model; finite 384-dimensional outputs. Busy requests return 429. Missing or corrupted models fail closed with 503 and never fall back to a cloud service. No inputs or embeddings are logged or retained by this service. HTTP request-body bounds are provided by the parent voice service middleware.

## Actual validation, 2026-10-22

A real Spanish query about a broken streetlight ranked the relevant lighting SOP above an unrelated cleaning SOP:

| Measurement | Observed value |
|---|---:|
| Relevant passage cosine | 0.851338 |
| Unrelated passage cosine | 0.801065 |
| Query vector norm | 0.99999997 |
| Cold single query, including imports/hash/model load | 12.701 s |
| Warm batch of two passages | 0.04684 s |

These are individual CPU calls, not p95, concurrent load, Windows measurements or a domain-wide retrieval quality guarantee. E5 cosine scores cluster high: do not interpret a generic threshold such as 0.75 as proof that an answer is relevant. Ground answers in retrieved scoped sources and calibrate no-answer behavior against a versioned golden set.

Three unit/HTTP contract tests cover unauthorized requests, bounds, missing models and busy rejection. The real model test separately verified dimensionality, normalization and Spanish semantic ranking. It did not query production data.
