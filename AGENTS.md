# ShiftProof operational map

This repository is a new local volunteer scheduling prototype for the Agents for Humans contest. Runtime inference uses the installed local Qwen model through Strands and an owned Ollama daemon with cloud disabled. No hosted model fallback or API spending is authorized.

## Authority

Current code and executed checks outrank the design packet and documentation. `src/shiftproof/models.py` is the shared contract. `docs/execution-contract.md` distills the GPT-6 Pro design; its expected fixture results are not measured results. The public contest rules remain authoritative for entry requirements.

## Map and boundaries

| Area | First files | Invariant |
| --- | --- | --- |
| Inputs | models.py, ingest.py | Strict five-file schema; omitted availability means unavailable; raw labels/notes never enter model context |
| Scheduling | solver.py, diagnostics.py | Hard constraints remain fixed; unknown is not infeasible; repairs minimize replacements first |
| Independent checks | verify.py | No imports from solver, its eligibility helpers, OR-Tools or Strands |
| State | store.py, proposals.py | Case/proposal/result hashes scoped to session; edits revoke approvals; simulations stay hypothetical |
| Agent | tools.py, agent.py, worker.py | Six tools only; none can apply, approve, export, read paths, call HTTP or execute code |
| Export | export.py, server.py | Reverify the current approved snapshot; safe CSV/ICS; no invitations or remote attachments |
| Runtime | config.py, preflight.py, scripts/run_local.py | Own child processes only; exact pinned local model; no cloud and no inherited credentials |

## Work rules

Inspect scoped changes before editing. Preserve other workers' files. Parent career repository contains unrelated dirty work; all commands here must use this repository as working directory. Do not operate on the parent repository or user data. Synthetic fixtures only. A model-generated claim is never a verified assignment or test result.

Run focused tests for changed behavior and relevant boundary negatives, then the project's release checks. Record actual local-LLM results separately from mocked tests. The complete submission requires code, license, architecture, measured evaluation, genuine demo and an actual receipt; a preview is not submission or payment.
