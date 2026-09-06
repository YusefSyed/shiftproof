# AI usage

ShiftProof uses AI in three distinct roles.

- GPT-6 Pro helped develop the high-level design and execution contract.
- Codex assisted with implementation and local test development.
- The application runtime uses the locally installed, pinned Qwen `qwen3.5:9b-q4_K_M` model through the local Ollama daemon for the constrained agent interaction.

The runtime is configured for local inference only. The launcher sets `OLLAMA_NO_CLOUD=1`, validates the local model metadata against `runtime-model.json`, and does not use an API key or hosted fallback.

Model output is not an assignment, an approval, or an export instruction. Only canonical solver results that pass independent verification can be presented for human approval. The assistant does not publish hidden reasoning logs; the coordinator-facing trace records actual tool activity and verified identifiers.

The local runtime model is [Qwen3.5 9B Q4_K_M](https://ollama.com/library/qwen3.5:9b-q4_K_M), distributed upstream under Apache-2.0. [Ollama](https://github.com/ollama/ollama/blob/main/LICENSE) is MIT-licensed. Neither model weights nor the Ollama executable are redistributed here.
