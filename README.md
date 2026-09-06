# ShiftProof

ShiftProof is a local prototype for reviewing a small synthetic community-pantry volunteer schedule. It separates a local scheduling assistant from independent constraint verification and from the coordinator actions that apply a change, approve a schedule, or export a bundle.

It is built for a single seven-day planning window with up to 20 volunteers, 12 shifts, three role codes, and 40 required assignment slots. It is not a payroll system, a legal-compliance system, or a production service. Exported calendars are schedule snapshots; they do not create invitations or synchronize with calendars.

## What it does

- Imports a strict five-file schedule bundle or loads a synthetic example.
- Treats missing availability as unavailable and coverage as an exact staffing target.
- Uses six constrained local-agent tools to inspect, solve, diagnose, propose, simulate, and prepare a review.
- Independently verifies candidate schedules before they can be approved.
- Keeps proposed changes hypothetical until a coordinator confirms and applies them.
- Exports an approved schedule as a deterministic ZIP with CSV, JSON, verification, and iCalendar files.

## Local setup

This project uses Python 3.12 and a locally installed Ollama model. It does not use hosted inference or API credentials.

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and [Ollama](https://ollama.com/download) first. This prototype was tested on a 32 GB Apple Silicon Mac. Install the model locally if it is not already present (a roughly 6.6 GB public model download; no inference API):

```sh
ollama pull qwen3.5:9b-q4_K_M
```

The launcher rejects a model whose digest differs from `runtime-model.json`; do not silently replace the lock if a registry tag changes. With the model installed, run:

```sh
uv sync --frozen
uv run --frozen python scripts/run_local.py
```

The launcher starts an owned Ollama daemon on `127.0.0.1:11435` and FastAPI on `127.0.0.1:8000`. It requires the pinned local `qwen3.5:9b-q4_K_M` model and its reviewed digest in `runtime-model.json`. The launcher sets `OLLAMA_NO_CLOUD=1`; it does not alter an existing default Ollama service. On macOS systems with `sandbox-exec`, the launcher uses the included sandbox profile to deny non-loopback egress for the app and owned daemon.

The development machine used for this prototype has 32 GB Apple Silicon memory. Other hardware has not been measured. Model weights are not distributed with this repository.

## Safety boundaries

The assistant cannot apply a proposal, approve a schedule, export files, read arbitrary paths, execute code, or call HTTP. Its six tools are:

- `inspect_case`
- `solve_schedule`
- `diagnose_infeasibility`
- `propose_change`
- `simulate_change`
- `prepare_review`

The parent application verifies results independently and requires explicit human confirmation for input review, changes, schedule approval, and export. Uploaded labels and notes are not placed into model context. See [the architecture](docs/architecture.svg), [the execution contract](docs/execution-contract.md), and [AI usage](AI_USAGE.md).

## Validation and demo

Run the local test suite with:

```sh
uv run --frozen pytest -m 'not local_llm'
uv run --frozen ruff check .
uv run --frozen mypy src
```

Measured local validation is summarized in [evaluation evidence](docs/evaluation.md). The rendered demo uses synthetic operators and recorded results with shortened inference waits; it is not a live recording. The [demo script](docs/demo-script.md) distinguishes recorded evidence from planned steps.

To reproduce the native evaluation while the app is running:

```sh
uv run --frozen python scripts/evaluate_local.py
uv run --frozen python scripts/evaluate_injection.py
```

The evaluation uses synthetic data and automated coordinator actions. Runtime and export files remain under ignored `workspace/`.

## Project status

This is a prototype using synthetic community-pantry data. Source: [YusefSyed/shiftproof](https://github.com/YusefSyed/shiftproof). The public video, required AWS account and Builder ID verification, and contest entry are pending. See [the submission checklist](docs/submission-checklist.md).

## License

ShiftProof is released under the [MIT License](LICENSE). Dependency notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
