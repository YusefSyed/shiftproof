# ShiftProof submission copy

Status: prepared text; not a submitted entry.

## Project name
ShiftProof

## Elevator pitch
A local AI agent helps volunteer coordinators repair schedules, explains impossible coverage, and exports only independently verified, human-approved plans.

## Track
Good Neighbor Agents

## Inspiration
A single cancellation can ripple through a volunteer schedule. Filling the empty slot may overload someone else or break another shift. ShiftProof explores how an agent can perform that coordination work while keeping availability, workload limits, and approval visible to the coordinator.

## What it does
ShiftProof imports five scheduling files or opens a synthetic pantry example. A coordinator reviews qualifications, availability, workload limits, and staffing needs. A Strands agent then inspects the case, calls a constraint solver, and prepares a verified schedule for review.

When availability changes, the agent proposes and simulates the edit before the coordinator applies it. Repairs prioritize fewer replaced assignments, then preferred availability, then workload balance. If no valid schedule exists, ShiftProof reports a concrete staffing bottleneck and can compare hypothetical alternatives without treating them as facts.

After a separate approval, the coordinator downloads a ZIP containing assignments, changes, verification evidence, checksums, and calendar snapshots. The application sends no invitations or messages.

## How it was built
Python, Strands Agents SDK, the native Ollama provider, Qwen running locally, OR-Tools CP-SAT, a separate Python verifier, FastAPI, and a plain browser interface. The agent runs in a supervised process with exactly six tools. Applying changes, approving schedules, and exporting are parent-application actions outside the agent's tool set.

On the tested Mac, the app and its owned Ollama daemon run under a process network policy that permits loopback only. No paid inference API, cloud deployment, or hosted model fallback is used.

GPT-6 Pro assisted with the design through ChatGPT. Codex assisted with implementation and verification. The runtime uses Qwen through Strands and Ollama. This is a new project created during the submission period, using standard open-source dependencies and synthetic fixtures. Dependency and model notices are included in the repository.

## Challenges and lessons
The difficult part was maintaining the distinction between a feasible simulation and the real confirmed case. An initial end-to-end evaluation exposed a status bug: a hypothetical repair could make the displayed case appear feasible. A regression test reproduced it, the state handling was corrected, and the full local-model workflow was run again successfully.

## What was measured
The release suite passed 56 automated tests. A separate real local-model evaluation exercised baseline planning, two cancellations, repair, infeasibility diagnosis, two hypothetical alternatives, approvals, and exports in 324.67 seconds. Another real provider-input probe confirmed that synthetic uploaded names, titles, and an instruction-like note were excluded from all four captured provider calls.

These are synthetic prototype checks, not evidence of real pantry deployment or general model reliability. The video visualizes the recorded application results with shortened inference waits and synthetic operator actions.

## Next steps
Evaluate usability with consenting volunteer coordinators, expand import diagnostics based on their feedback, and test larger and more varied schedules before considering wider deployment.

## Testing instructions
Use the repository README to install the pinned dependencies and local model. Launch the local server, load the pantry example, confirm the reviewed inputs, and select Find a schedule. Inspect the schedule and workloads before approving. Select Simulate an absence to inspect an exact proposed change and independently checked hypothetical result. Applying it invalidates the old approval. The native evaluation script reproduces the extended scenario; it can take several minutes on the tested 32 GB Apple Silicon Mac.

## Required links and account fields
- Public source repository: https://github.com/YusefSyed/shiftproof.
- Public YouTube demo: https://www.youtube.com/watch?v=PeNYosqIMco.
- Architecture: `docs/architecture.svg` in the source repository.
- AWS Builder ID: account holder must supply or create it.
- AWS account: required by the rules; not yet verified.
