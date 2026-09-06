# ShiftProof demo transcript

Locally synthesized narration. The video visualizes measured recorded outputs; it is not a live browser recording.

## Scene 1

ShiftProof helps a volunteer coordinator handle cancellations without silently changing the rules. This video visualizes a recorded local Strands run, rather than a live screen recording. The pantry data and coordinator actions are synthetic, and inference waits are shortened. The model calls, computed results, checks, and exported files came from the working application.

## Scene 2

The example has six volunteers and four two-hour shifts. Every shift requires one lead and one helper. The two leads each allow at most two shifts and two hundred forty minutes. Missing availability is treated as unavailable. The coordinator can inspect qualifications, limits, availability, and source records before confirming these inputs.

## Scene 3

The actual local model inspected the case, called the scheduling solver, and prepared a review. The solver found eight preferred assignments. A separate verifier recomputed coverage, availability, qualifications, overlaps, and workload limits. The model did not write this schedule in prose, and a verified candidate was not automatically approved.

## Scene 4

The model first proposed and simulated Bo's cancellation without changing the confirmed case. After a synthetic coordinator confirmation through the application's human route, the old approval was revoked. The agent then repaired the schedule. Simply adding midday to Asha would exceed both limits. Instead, it swapped two lead assignments and retained all four helper assignments.

## Scene 5

Now Bo also becomes unavailable for the afternoon. Every shift still has an eligible lead considered on its own. But Asha alone would need three shifts and three hundred sixty minutes, above the confirmed limits of two shifts and two hundred forty minutes. The application reports this concrete bottleneck. Reusing the old schedule approval to export is rejected.

## Scene 6

The real agent compared two alternatives. One restores Bo's afternoon availability. The other increases both of Asha's limits. Both simulations are independently checked, but neither is an established fact. The confirmed case remains infeasible, with no schedule approval. The agent cannot claim a volunteer consented, and it has no tool for applying or approving either option.

## Scene 7

After separate schedule approval, export recomputes the checks against the current snapshot. The actual repaired bundle includes the assignments, verification report, change record, calendar files, and checksum manifest. Its coordinator calendar contains eight events. These are importable snapshots, not invitations or synchronization updates. No calendar service is contacted.

## Scene 8

The automated suite has 56 passing tests. A separate genuine local run inspected four requests handed to the model provider: synthetic name, title, and instruction-note probes were absent. The app and its owned Ollama daemon run under a local-only process network policy on the tested Mac. There is no hosted model fallback. Approval tokens remain outside the agent worker.

## Scene 9

ShiftProof is a working local prototype for one site and a seven-day planning window. It has not been deployed to a real pantry or evaluated with real volunteers. GPT-six Pro assisted with the design, Codex implemented and tested it, and Qwen runs locally through Strands and Ollama. The aim is useful automation with checkable outputs and explicit human decisions.
