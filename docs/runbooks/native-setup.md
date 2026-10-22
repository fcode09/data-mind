# Native Windows and Arch Linux setup

No WSL is required. The Go binaries and browser UI run natively on Windows or Linux. Python CPU model dependencies may need platform-specific wheel/runtime setup. This repository was validated in Linux; Windows compilation and actual Windows microphone tests are distinct checks, not implied by Linux success.

## Prerequisites

- Go 1.27.3, Node 22.12+ or the version required by the locked Vite release, Python 3.12.
- PostgreSQL 17; pgvector for optional semantic retrieval. Use official OS packages or a local container engine of your choice.
- A non-production local database, a migration administrator and a restricted application login.
- Sufficient disk space for explicit model downloads. Do not commit weights, .env or credentials.

On Windows use official installers and PowerShell. On Arch install supported native packages through your normal package manager. Docker/Podman are optional; do not change OS security or daemon settings merely to run this demo.

## Install

From the repository root:

```sh
go mod download
python -m venv .venv
# Activate .venv using your shell's normal command.
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
cd apps/web
npm ci
cd ../..
```

Copy .env.example to .env locally. Replace every placeholder. Generate independent random internal/session secrets using your normal secure tooling. Keep the file private and outside source control. Set DATABASE_ADMIN_URL to the synthetic database administrator and DATABASE_URL to its restricted reader login. For Compose the database hostname is postgres, not localhost.

## Migrate and seed

Load .env in your shell or use the provided dev script. The migration creates NOLOGIN data_mind_reader/data_mind_writer roles, not public credentials. Provision your application login using your normal PostgreSQL administration workflow and grant only data_mind_reader membership. It must not own tables, be superuser, or have BYPASSRLS. The application refuses an unsafe login.

```sh
go run ./apps/worker migrate --vectors
go run ./apps/worker seed --rows 1000000 --seed 42 --anchor 2026-10-23T00:00:00Z --batch-key demo-million --manifest-output artifacts/manifest.json
go run ./apps/worker verify --batch-key demo-million
```

Run from the root so db/migrations is found. Create artifacts/ before using that output path. Repeating the same key/specification resumes or verifies the same batch; changing the specification under the same key fails. Optional 10M stress is --rows 10000000 on a separate empty synthetic database or with a non-overlapping --offset. It was not measured in the baseline acceptance run.

```sh
go run ./apps/worker append-day --rows 10000 --anchor 2026-10-24T00:00:00Z --batch-key day-2026-10-24
```

The demo clock is the explicit anchor, not necessarily real today. No scheduler silently appends data; arrange scheduling only if you want it.

## Start independent terminals

PowerShell:

```powershell
./scripts/dev.ps1 mcp
./scripts/dev.ps1 api
./scripts/dev.ps1 voice
./scripts/dev.ps1 web
```

Bash:

```sh
./scripts/dev.sh mcp
./scripts/dev.sh api
./scripts/dev.sh voice
./scripts/dev.sh web
```

Open http://127.0.0.1:5173. API is 8100, MCP 8101 and voice 8102. Bind only loopback for the native demo. Text analytics work before voice models are installed. Voice activation is unavailable until the model and fixed acknowledgement assets are prepared; the UI says so rather than pretending.

## Voice models

See docs/voice.md for pinned source licenses, CPU installation, explicit model downloads and prepare_assets. The first model load is slower than warm inference. Do not promise real-time latency from hardware specifications alone. Microphone permission must be granted by the user, and browser support should be tested on the actual machine.

## Container option

infra/compose.yaml starts PostgreSQL, Go MCP and Go API. The tools profile exposes the worker; the voice profile builds the optional Python model service and mounts already prepared models. Run the web development server natively, or serve a reviewed production build separately. This Compose configuration is supplied but is not claimed as executed where Docker/Podman are unavailable. Docker Desktop has its own licensing terms; Podman is an alternative, not an automatically interchangeable tested runtime.
