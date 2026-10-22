# Third-party components

This file records major components, not a replacement for their full license texts or a legal determination. The repository's owner has not selected a new license for the original project.

- Go and standard library: BSD-style; https://go.dev/LICENSE
- Official MCP Go SDK: MIT; https://github.com/modelcontextprotocol/go-sdk
- pgx: MIT; https://github.com/jackc/pgx
- PostgreSQL: PostgreSQL License; https://www.postgresql.org/about/licence/
- pgvector: PostgreSQL License; https://github.com/pgvector/pgvector
- React: MIT; Vite: MIT; see package-lock.json and upstream notices.
- Vosk Spanish small model 0.42: Apache-2.0; community vosk-browser wrapper has separate package dependencies/licenses.
- faster-whisper and Whisper model: MIT; pinned sources in models/models.lock.
- Kokoro 82M and selected voice: Apache-2.0 upstream model distribution; eSpeak NG runtime has GPL obligations to review when bundling.
- multilingual-e5-small: MIT; pinned model revision/hashes in apps/voice/embeddings.py.
- llama.cpp: MIT; Qwen3-0.6B-GGUF: Apache-2.0. The tested small model is a CPU smoke profile.

Download weights explicitly and retain upstream notices. Docker Desktop is optional external software with its own licensing, not part of an all-open-source licensing claim.
