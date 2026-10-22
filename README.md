# Data Mind 2

Spanish conversational analytics over reproducible fictional data, with **Go API + official MCP + PostgreSQL**, local Python voice/models and a React interface.

This rebuild preserves the original Git history. Main remains unchanged; development proceeds through feature branches merged into develop.

## Start with Docker Compose

```bash
# Once: create random local demo secrets (requires Docker, no local Python).
bash scripts/docker.sh init
# Start DB, migrations, one million fictional records, MCP, API and web UI.
bash scripts/docker.sh up
```

Windows PowerShell: `./scripts/docker.ps1 init`, then `./scripts/docker.ps1 up`.
Open **http://localhost:8080**. No WSL shell is required; Docker must run Linux containers.
[Complete Docker guide](docs/runbooks/docker.md) · [Optional voice and local models](docs/runbooks/docker-models.md).
Text works without model downloads; voice and the optional LLM have explicit preparation steps.

## Start here

- [Native Windows and Linux setup](docs/runbooks/native-setup.md)
- [Architecture and trust boundaries](docs/architecture/system.md)
- [Local Spanish voice and actual measurements](docs/voice.md)
- [Controlled improvement](docs/evaluations/controlled-learning.md)
- [Validation and remaining limits](docs/validation/acceptance.md)

## Applications

| Application | Technology | Purpose |
|---|---|---|
| web | React / TypeScript / Vite | Spanish conversation, evidence, voice consent |
| api | Go | Sessions, typed intent, evidence validation, voice proxy |
| mcp | Go official MCP SDK | Seven bounded read-only domain tools |
| worker | Go | Synthetic millions, checkpoints, manifests, daily append |
| voice | Python | Local Spanish STT/TTS and model inference |

PostgreSQL owns exact numerical analytics. Documents use scoped retrieval; pgvector supports the optional local semantic path. No real database, external paid model or private data is necessary.

## Quick checks

```sh
go test ./...
go vet ./...
python -m pytest tests -q
cd apps/web && npm ci && npm test && npm run build
```

Database integration tests additionally require a restricted TEST_DATABASE_URL. Do not point tests at production. Voice tests use explicit fake adapters unless a real-model benchmark is selected; read the acceptance report rather than assuming every hardware path was tested.

## Important boundaries

- DEMO_MODE permits choosing only synthetic tenants. It is not production authentication.
- Local wake recognition requires consent, downloaded assets and an active browser tab.
- Dates are explicit and half-open; unsupported filters ask for clarification.
- Feedback does not autonomously change code or train a model.
- Models, credentials, generated audio and datasets stay out of Git.
- Original project licensing has not been replaced silently. Review third-party software and model licenses before distribution.
