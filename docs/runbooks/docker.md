# Run the complete synthetic demo with Docker Compose

## Requirements and scope

Use Docker Engine with the Docker Compose plugin on Linux, or Docker Desktop in Linux-container mode on Windows. Run commands from the repository root. PowerShell is supported: no WSL shell is required. Docker Desktop itself needs a supported Linux-container backend (Hyper-V or WSL 2); native Windows containers cannot run these Linux images. Installation and OS virtualization changes are outside this repository.

The default stack supplies PostgreSQL/pgvector, automatic migrations, a restricted database reader, deterministic synthetic data, the Go MCP and API, and a production-built web UI behind nginx. Only http://localhost:8080 is published, bound to loopback. PostgreSQL, MCP, API, voice and models stay on the Compose network. This is a synthetic demonstration, not a production deployment or authenticated multi-user service.

## First setup (once)

Windows PowerShell:

```powershell
./scripts/docker.ps1 init
./scripts/docker.ps1 up
```

Arch Linux / Bash:

```bash
bash scripts/docker.sh init
bash scripts/docker.sh up
```

`init` uses an official Python container to create `.env` with random local-only secrets. No local Python, Go or Node installation is necessary. An existing `.env` is never overwritten. If reusing a native-development `.env`, add the required values listed below before continuing. Do not change an existing database password without a deliberate database credential migration: the PostgreSQL image only initializes credentials on an empty volume.

The equivalent portable commands are:

```bash
# If Python is already installed, this can replace the init helper:
python scripts/docker_setup.py
docker compose up --build -d --wait --wait-timeout 600
```

Open http://localhost:8080. Choose a fictional organization and ask, for example, “¿Cuántos incidentes hay?” Select a date range covering the demo data (2024-10-23 through 2026-10-22). The seeded clock is fixed, not today's live date.

By default the seed contains **1,000,000 incidents** and 100 fictional procedure documents. For a faster first trial, change `SEED_ROWS=10000` in `.env` **before the first startup**. Do not change the base seed specification on an existing volume: overlapping synthetic IDs will fail rather than silently overwrite records. Use a separate `COMPOSE_PROJECT_NAME` with its own volumes for another dataset size. The seed is deterministic and safely resumes/repeats the same batch; restarts do not duplicate data.

Required `.env` keys: `POSTGRES_PASSWORD`, `READER_PASSWORD`, `MCP_INTERNAL_TOKEN`, `VOICE_INTERNAL_TOKEN`, `API_SESSION_SECRET`, `CURSOR_SECRET`. Generate URL-safe hexadecimal secrets as the helper does, because database passwords are interpolated into DSNs. Optional keys: `SEED_ROWS` (default 1000000), `WEB_PORT` (default 8080).

## What happens at startup

1. PostgreSQL becomes healthy.
2. The administrative migration job creates tables, RLS policies and pgvector schema.
3. A separate job provisions a non-superuser, non-bypass-RLS read-only runtime login.
4. The worker loads or resumes the synthetic seed.
5. MCP starts using only the reader credentials; API starts after MCP; nginx starts after API.

A failed one-shot job prevents the dependent services from being marked ready. Inspect `docker compose logs migrate reader-role seed` instead of ignoring an exit code. Health checks establish service readiness; the integration smoke test establishes real query behavior.

## Voice, embeddings and optional language model

The default stack supports text-based analytical questions without an LLM. Voice/model weights are deliberately not downloaded on every boot. Follow [Docker model preparation](docker-models.md) for the voice overlay, explicit first-download step and optional llama.cpp overlay. The microphone requires browser permission; deny permission if you only want text. The client interface is Spanish.

Local speech uses bounded utterances, not a continuous WebRTC voice session. The optional small LLM routes requests into allowed typed tools; it never receives arbitrary SQL execution privileges. Do not treat this demonstration as a general conversational assistant or an externally reachable service.

## Everyday operations

```bash
docker compose ps
docker compose logs -f --tail 100
docker compose stop                 # keep containers and all data
docker compose start               # resume existing containers
docker compose down                # remove containers, preserve named volumes
docker compose up --build -d --wait --wait-timeout 600
```

When using model overlays, use the same `-f` arguments for subsequent commands. Do not use `down --volumes` unless intentionally deleting the local demo database and state. Volume deletion is not part of the helpers.

The API conversation/feedback state and database data have separate persistent named volumes. Never expose the stack publicly by changing the loopback binding without adding real authentication, TLS and an operational security review. Environment variables are visible to anyone with Docker administrator access; local generated credentials are not a production secret-management strategy.

## Image provenance

The PostgreSQL image is pinned to the official `pgvector/pgvector:pg17` manifest verified on 2026-10-22 (published 2026-10-01), rather than the older 0.8.0 image. The web image pins the verified official Node 22 and nginx manifests. Updating a digest is an explicit dependency update requiring CI; Go and Python base images remain version-tagged and receive upstream patch updates.

## Validation

```bash
python scripts/compose-smoke.py --rows 1000000
```

The smoke test checks the web UI and real authenticated API→MCP→database results, not mock replies. The Docker CI workflow uses a 10,000-row isolated dataset for fast verification, tests seed repetition and checks restricted database privileges. Core Docker validation does not establish voice quality, microphone behavior, downloaded-model compatibility, throughput or a production SLA. Consult the workflow result for the exact commit being reviewed.
