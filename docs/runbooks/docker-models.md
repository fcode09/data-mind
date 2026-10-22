# Optional local voice, embeddings and LLM containers

Start with [Docker quick start](docker.md). The core stack does not require weights, a GPU, a cloud account, or a paid API. These overlays add CPU-only local inference. Run commands from the repository root, in PowerShell or Bash; the commands themselves are identical. Docker must already be installed and running in Linux-container mode. This does not require installing this project's tools in WSL. Windows may use Docker Desktop's supported virtualization backend.

## Before downloading

Review the model cards and licenses:

- Whisper small, [Systran model card](https://huggingface.co/Systran/faster-whisper-small): MIT.
- Kokoro-82M and Spanish `ef_dora`, [model card](https://huggingface.co/hexgrad/Kokoro-82M): Apache-2.0.
- Vosk Spanish small 0.42, [official model list](https://alphacephei.com/vosk/models): Apache-2.0.
- Multilingual E5 small, [model card](https://huggingface.co/intfloat/multilingual-e5-small): MIT.
- Optional Qwen3-0.6B GGUF Q8_0, [pinned official revision](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/tree/23749fefcc72300e3a2ad315e1317431b06b590a): Apache-2.0.
- Optional llama.cpp [official b11669 release](https://github.com/ggml-org/llama.cpp/releases/tag/b11669): MIT.

The explicit `--accept-model-licenses` flag records your decision to proceed after that review. There is no automatic download or license acceptance during `up` or an inference request. Files are version/revision-pinned and SHA256/size verified before activation. Rerunning initialization verifies existing files and only downloads missing or invalid files. Interrupted individual downloads restart from zero. Weights stay in named volumes, not Git or application images.

Allow several GB of disk for Python images, plus approximately 1.3 GB for voice/embedding/wake weights and another 639 MB for Qwen. At least 8 GB available RAM is a practical starting allocation for the combined demo, not a measured minimum or concurrency guarantee. Image builds and downloads require internet; inference uses local files with Hugging Face offline mode.

## Voice and semantic retrieval

First prepare the local `.env` using the core setup instructions. Then, explicitly initialize weights once:

```sh
docker compose -f compose.yaml -f infra/compose.voice.yaml run --build --rm model-init --group voice --accept-model-licenses
```

Start the stack, reusing the same Compose files on every later invocation:

```sh
docker compose -f compose.yaml -f infra/compose.voice.yaml up --build -d --wait --wait-timeout 600
docker compose -f compose.yaml -f infra/compose.voice.yaml ps -a
```

The overlay starts the internal voice service, checks provisioned model files and authenticated service health, embeds the seeded fictional SOPs, then allows MCP to start. `embed-documents` is a one-shot: exit code 0 is success, not an error. The worker recomputes the small 100-document synthetic corpus when this one-shot job reruns; model weight downloads are still cached and never repeated at startup. API calls the voice service internally. The browser wake-word model is served by nginx from the read-only browser-model volume. Only the root web port is exposed; API access is proxied through nginx, and model services are internal.

The voice health check proves service responsiveness and required files exist, **not model inference accuracy**. First inference loads weights lazily and can be slower. An embedding initialization failure blocks MCP; inspect `docker compose -f compose.yaml -f infra/compose.voice.yaml logs voice embed-documents`. STT/TTS use bounded HTTP requests, not continuous WebRTC or barge-in. A physical microphone/browser wake-word test remains a separate acceptance check.

## Optional LLM intent routing

The default core uses deterministic intent routing. The optional CPU LLM selects bounded structured intents; final numerical answers still come from verified database evidence. This is not an unrestricted chat model or self-training service. Qwen 0.6B is a modest demo profile, not a claim of production-quality intent coverage or the previously proposed 8B model.

```sh
docker compose -f compose.yaml -f infra/compose.llm.yaml run --build --rm llm-model-init --group llm --accept-model-licenses
docker compose -f compose.yaml -f infra/compose.llm.yaml up --build -d --wait --wait-timeout 600
```

The llama.cpp archive has a verified SHA256 and b11669 release pin. The supplied binary is **linux/amd64 only**; ARM systems would need a separately verified native build. The service binds only within the Docker network, with no published model port. It uses two CPU threads, a 2048-token context and one request slot, without GPU passthrough. It intentionally has no external provider credentials. Do not expose this unauthenticated internal endpoint publicly.

To combine all features, first run both initialization commands above, then:

```sh
docker compose -f compose.yaml -f infra/compose.voice.yaml -f infra/compose.llm.yaml up --build -d --wait --wait-timeout 600
```

Use that same three-file command prefix for `ps`, `logs`, `stop` and `down`. Do not use `down -v` unless you intend to discard all local model/data volumes and regenerate them. Switching from an overlay back to core can leave old containers; inspect `ps -a` before deliberately removing orphans.

## Validation scope

The Python dependency lock snapshots the previously exercised Python 3.12 CPU voice/embedding environment; Docker builds additionally run package consistency and import checks. Native inference was previously exercised separately. A container image build is not an end-to-end speech test. The Docker CI smoke test and its exact commit/run result are the authoritative container validation evidence; no claim is made that your Windows/Arch machine or microphone was tested.
