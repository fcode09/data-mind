# Local Spanish voice

## Implemented baseline and honest limits

The HTTP voice service uses a persistent spawned process, lazy local faster-whisper small STT and Kokoro-82M Spanish `ef_dora` TTS. It has no cloud inference path. Browser wake recognition is separate and uses Vosk. This baseline uses bounded utterance uploads, not streaming Pipecat/WebRTC, Silero turn detection, or tested barge-in. Those richer transports remain a later increment. A CPU synthetic-speech round trip has been measured below. GPU performance and real microphone operation have **not** been tested.

Only the API should call this internal service. The API must validate evidence before forwarding final answer text for speech. This service cannot independently authorize database facts. A prerecorded “Déjame consultar” is an acknowledgement, not a factual result. Missing models produce HTTP 503, never a fabricated answer or silent remote fallback.

## Setup

From the repository root, install the project's voice extra into your virtual environment:

```sh
python -m pip install -e '.[voice]'
python scripts/download_models.py --group all --prepare-browser --accept-model-licenses
```

The explicit model download is approximately 854 MB. The browser Vosk archive is generated locally under `apps/web/public/models/` and must not be committed. Whisper and Kokoro files live under `models/cache/`. Review the licenses before the explicit acceptance flag. The lock file pins upstream revisions, byte sizes and SHA256 digests. A digest mismatch refuses promotion of the downloaded file.

Kokoro Spanish requires the eSpeak NG runtime. In the tested Python environment, `misaki` installed `espeakng-loader==0.2.4`, which supplied the local shared library and data successfully, with no system installation. If your platform needs a separate runtime, use its official operating-system package/source. On Arch Linux use the maintained `espeak-ng` package. On Windows native use the official eSpeak NG Windows release and its documented library discovery configuration; do not assume WSL or a Linux path. Windows Kokoro audio quality must be tested before declaring support verified. Python multiprocessing uses `spawn` on both platforms.

Set `MODEL_DIR` to the absolute cache path, `VOICE_INTERNAL_TOKEN` to the internal credential supplied by your deployment, and optionally `VOICE_DEVICE=cpu` (default) or `cuda`. `WHISPER_COMPUTE_TYPE=int8` is the CPU default; select a supported GPU type explicitly. Never commit credentials or expose this service publicly.

```sh
python -m apps.voice.main
```

This binds 127.0.0.1:8102, one process worker. Container deployments may override the bind address only inside their private network, without publishing the voice port. `MCP_INTERNAL_TOKEN` is a compatibility fallback when `VOICE_INTERNAL_TOKEN` is absent; separate internal credentials are preferable.

- GET `/health`: authenticated service readiness, not a claim that models or inference passed.
- POST `/transcribe`: authenticated multipart `file` (WAV/WebM and other formats supported by installed PyAV); returns `{ "text": "..." }`.
- POST `/synthesize`: authenticated JSON `{ "text": "..." }`; returns mono 24 kHz 16-bit WAV with no-store.
- Headers: `Authorization: Bearer <internal token>`.

Limits: 4 MiB audio upload, 30 seconds decoded audio, 100 ms minimum, 1,200 text characters, 120 seconds generated output, one inference request at a time, 90-second hard worker deadline including first model load. The worker is terminated and recreated after a timeout; a busy worker returns 429. Chunk Spanish text to reduce Kokoro phoneme truncation. Missing runtime libraries or model files return a non-sensitive diagnostic. No raw audio or transcripts are persisted by this service.

## User permissions and cancellation

Microphone capture must start only after explicit user action and browser permission on localhost or HTTPS. Idle wake audio stays in the browser. Closing or suspending the tab disables activation; no always-on OS promise is made. Browser stop/cancel must immediately stop playback and ignore stale turn results. Aborting HTTP does not guarantee immediate GPU kernel interruption: the worker remains bounded by its hard deadline. Voice barge-in requires real AEC/VAD tests and is not claimed by this baseline.

## Verification performed

`python -m pytest tests/test_voice_service.py -q` covers HTTP authentication, missing configuration fail-closed, upload limits, empty inputs, fake transcription/WAV adapters, busy rejection, archive traversal defense and hash mismatch refusal. These are explicit fake-adapter unit/contract tests, **not** real STT, TTS, wake-word, browser audio or GPU tests. All pinned model files were subsequently downloaded and hash-verified for the CPU round trip below. The Vosk browser archive was prepared, but browser recognition was not tested. Runtime model loading has offline flags and explicit local paths.

Before rollout: download verified models, run an audio fixture with known Spanish text, inspect transcriptions and resulting WAV, test the actual browser wake phrase, record CPU/GPU cold/warm latency, test cancellation and concurrent requests, and verify no network traffic during inference. Maintain pronunciation golden cases for dates, identifiers, numbers and domain terms.

## Primary sources and licenses

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper): MIT; [small model](https://huggingface.co/Systran/faster-whisper-small), pinned revision in models.lock.
- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M): Apache-2.0; [pipeline source](https://github.com/hexgrad/kokoro/blob/main/kokoro/pipeline.py) documents Spanish `e`, local `.pt` voices and Spanish chunking caveat.
- [Vosk models](https://alphacephei.com/vosk/models): Spanish `vosk-model-small-es-0.42`, Apache-2.0, official ZIP.
- [vosk-browser model layout](https://github.com/ccoreilly/vosk-browser/blob/master/lib/README.md): gzip tar containing `model/` at its root. This is a community WASM wrapper, not the official Vosk Python runtime.
- [eSpeak NG](https://github.com/espeak-ng/espeak-ng): review GPL runtime distribution obligations. “Local/open source” does not remove license duties for bundled binaries.

## Prepare the immediate spoken acknowledgement

After installing the local voice dependencies, eSpeak NG, and verified Kokoro files, explicitly render the fixed phrase once:

```sh
python -m apps.voice.prepare_assets
```

This creates `apps/web/public/models/consulting.wav` using local Kokoro. The web application plays this same-origin asset only after accepting a voice question. It is not a data answer. If the file is absent, the UI should fall back to visible status instead of invoking remote browser speech. Generated audio is not checked into source control.


## Actual CPU validation, 2026-10-22

An isolated Python 3.12 environment successfully rendered “Déjame consultar.” using local Kokoro, then transcribed that generated WAV with local faster-whisper. Both cold and warm STT returned exactly “Déjame consultar.” The WAV contained 1.475 seconds of mono 24 kHz audio, 70,844 bytes.

Single-call observations, not p95 or an SLA:

| Operation | Observed seconds |
| --- | ---: |
| TTS cold (imports/model load included) | 8.297 |
| TTS warm | 0.926 |
| STT cold | 5.052 |
| STT warm | 2.731 |

The run set `OMP_NUM_THREADS=2` and `MKL_NUM_THREADS=2`; CPU resource scheduling was shared and uncontrolled. This establishes actual model/API compatibility on this Linux CPU environment, not conversational quality, Windows support, wake accuracy, human-microphone recognition or end-to-end response latency. A nonfatal UCX VFS socket diagnostic appeared during STT in the restricted environment; inference still completed. Do not change host security settings to suppress it.

Installed versions: torch 2.14.1+cpu (official CPU index), faster-whisper 1.2.1, ctranslate2 4.8.3, kokoro 0.9.4, misaki 0.9.4, espeakng-loader 0.2.4, transformers 5.20.2, av 19.0.2, numpy 2.5.4, soundfile 0.14.0. Other environments must validate this combination rather than assuming compatibility.

Reproduce in a separate virtual environment, selecting the CPU torch wheel first:

```sh
uv venv .voice-venv --python 3.12
uv pip install --python .voice-venv/bin/python torch==2.14.1+cpu --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .voice-venv/bin/python faster-whisper==1.2.1 kokoro==0.9.4 soundfile==0.14.0 python-multipart
# Run the previously documented pinned model downloader first.
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .voice-venv/bin/python -m apps.voice.benchmark --output artifacts/voice-round-trip.json
```

On Windows native, use `.voice-venv\Scripts\python.exe`, set environment variables using PowerShell `$env:OMP_NUM_THREADS='2'` and `$env:MKL_NUM_THREADS='2'`, and omit shell-style inline variable assignment. This is a platform-specific command adaptation, not a claim of Windows execution.
