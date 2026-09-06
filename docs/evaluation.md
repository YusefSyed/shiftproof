# Evaluation evidence

This page records measured local evidence. It is not a publication, contest submission, customer claim, or proof of performance on non-synthetic data.

## Automated checks

- `pytest`: 56 passed, with two deprecation warnings.
- `ruff`: clean.
- `mypy`: 16 source files clean.
- Node syntax check: clean.

## Native local workflow

The accepted native local receipt completed on 2026-09-06. It used the pinned local `qwen3.5:9b-q4_K_M` model, synthetic data only, and the explicit human UI routes exercised by an automated test harness. It passed in 324.67 seconds. The receipt covers baseline, repair, diagnosis, and simulation workflow evidence. An earlier native evaluation was rejected for a status-handling bug; the regression was fixed before the accepted receipt.

## Uploaded-note isolation probe

The accepted synthetic uploaded-note probe completed on 2026-09-06 in 40.694 seconds with a real local model. It inspected four provider calls and confirmed that raw names, titles, and the instruction-like note were excluded from model input. The resulting schedule had eight preferred assignments. This is evidence of the tested probe only.

## Demo media

`media-work/ShiftProof-Demo.mp4` is a 208.25-second rendered visualization using synthetic operators and recorded results. Inference waits were shortened for presentation. It is not a live recording.

The sanitized structured receipts are [native workflow](evidence/native-workflow.json) and [uploaded-note probe](evidence/uploaded-note.json). They include actual tool activity, measured durations, and source-receipt checksums.

## Remaining release gates

The public source repository is https://github.com/YusefSyed/shiftproof. The [public video](https://www.youtube.com/watch?v=PeNYosqIMco) is published and contest registration is complete. Required AWS account/Builder ID verification and a final submission receipt remain pending. See [submission checklist](submission-checklist.md).

## Browser acceptance

The final interface was exercised with the live local provider: input review, baseline scheduling, explicit approval, a simulated absence, exact-change confirmation, approval revocation, and repair. The repaired view showed six preferred assignments, two replacements, unchanged helper assignments, and both leads within their 240-minute/two-shift limits.
