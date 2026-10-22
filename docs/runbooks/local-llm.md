# Optional local LLM intent planner

Frequent supported analytics use a deterministic fast path. The local model only proposes typed intent; it cannot choose tenant identity, issue SQL, run tools freely, or write the factual answer. Proposed filters must be grounded in the user's question. Unsupported conditions clarify rather than silently selecting a broader or opposite query.

## Verified CPU smoke profile

- Official llama.cpp release b11669, commit 620d2225cc436ab0b001e3200e590e3b286ef9ab, MIT.
- Official Qwen/Qwen3-0.6B-GGUF revision 23749fefcc72300e3a2ad315e1317431b06b590a, Q8_0, Apache-2.0.
- Model SHA256: 9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031.
- Linux release archive SHA256: cf07c1c112d709bd67e522017471de57ed0ec8bea031d732c5422351c07f65ac.

Download the appropriate official binary for your OS from https://github.com/ggml-org/llama.cpp/releases/tag/b11669 and the pinned model from https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/tree/23749fefcc72300e3a2ad315e1317431b06b590a. Verify checksums and model license before use. The Linux archive hash does not apply to Windows binaries. This is a smoke-test model, not a claim that 0.6B matches the initially proposed 8B model's quality.

```sh
llama-server -m models/cache/Qwen3-0.6B-Q8_0.gguf --host 127.0.0.1 --port 18089 -c 2048 -t 2 -ngl 0 --parallel 1 --reasoning off --alias qwen3-test
```

Set LLAMA_BASE_URL=http://127.0.0.1:18089/v1 and LLAMA_MODEL=qwen3-test. Keep the endpoint on loopback/private local network, never expose an unauthenticated model server publicly. The API allowlists local endpoint hostnames.

## Actual findings

The initial structurally valid model response invented a status filter. The implementation was corrected: a clearer prompt separates grouping from filters, and server-side grounding rejects invented filters. JSON/schema validity alone is not semantic correctness.

The actual Go adapter, bypassing the deterministic path, then passed the compositional Spanish question about an Alumbrado breakdown by status: summary tool, status grouping, Alumbrado category, no status filter. Adapter call 6.75 s on this CPU test. Raw repeated identical-prefix requests measured first 5.57 s, warm 2.13/2.07 s, around 918 MiB RSS. These are smoke observations, not broad accuracy, throughput, p95 or 8B benchmarks.

```sh
LOCAL_LLM_TEST_URL=http://127.0.0.1:18089/v1 go test -v ./internal/orchestration -run TestLocalModelAdapter
```

Expand synthetic Spanish evaluation cases before switching models, prompts or precision. Keep negative/compound-filter, hallucinated-filter and tenant-isolation tests as mandatory gates.
