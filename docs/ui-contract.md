# UI and server contract

Main owns the backend; the UI worker owns only `src/shiftproof/static/index.html`, `app.js`, and `styles.css`. Files are served at `/`, `/static/app.js`, and `/static/styles.css`; use system fonts and no CDN. The UI must use `textContent` or `createElement` for all dynamic content. No trusted HTML strings from server, model, or uploads. Responsive, keyboard-accessible panels: inputs and constraints, request and trace, schedule and metrics, and review, proposals, and export. Use a polished restrained navy, cream, and teal visual style, clear ShiftProof branding, and the “Local volunteer scheduling” description. Avoid developer implementation details in the default product flow except local-model readiness, verified status, and provenance useful for trust. Display “Synthetic community pantry example” for the demo. Do not imply an established customer.

`GET /api/state` initializes an HttpOnly same-site session cookie; JSON includes the `csrf` token. Mutations use same-origin fetch with `X-CSRF-Token: state.csrf`; browser `Origin` is set normally. Every response state can be refreshed with GET. Show errors from `{error, detail}` as escaped text. Poll state every second only while `running`; do not spam idle.

State shape:
```
{csrf,session_id,revision,case_hash,confirmed,status,running,run_id,last_error,source_kind,
 model:{ready,tag,detail},
 case:null|{schema_version,case_id,timezone,week_start,roles,locks,volunteers,shifts,coverage,availability,input_bundle_hash},
 missing_availability_pairs:number,
 candidate:null|{result_id,case_hash,candidate_hash,hypothetical,baseline_assignments,solver:{status,phases,assignments},verification:{valid,violations,coverage,workload,preferred,non_preferred,replacements,dispersion},approve_token},
 diagnosis:null|{case_hash,status,proof_kind,facts,conflict_demands,subset_minimal,limitation},
 approval:null|{approval_id,case_hash,candidate_hash,approved_at},
 proposals:[{proposal_id,base_case_hash,proposal_hash,operations,confirmations,apply_token,simulation:null|{result_id,solver,verification,diagnosis,hypothetical:true}}],
 trace:[{seq,type,tool,arguments,status,result_id,duration,detail}],
 artifacts:[{artifact_id,name,kind,case_hash,historical}]
}
```
`case` rows use `models.py` keys, `source_ref` strings, and ISO timestamps; render raw notes only escaped. The model never receives labels or notes. Coverage is an exact target count; missing availability means unavailable. Show confirmation of these rules before enabling the agent. Metrics are authoritative server values, not frontend computations. Candidate assignments contain IDs; look up display names, shifts, and roles using case data for rendering. Case scale supports a small table; use buttons to display provenance refs and details. Diagnostic facts use `{fact_id, code, entity_ids, source_refs, details}`; render labels from known static codes or generic readable keys, never model-generated HTML.

Routes:
- `POST /api/demo` with `{variant:"baseline"}` or `{variant:"injected_note"}` loads an example but leaves it unconfirmed.
- `POST /api/import` uses multipart fixed slots: `case.json`, `volunteers.csv`, `shifts.csv`, `coverage.csv`, and `availability.csv`. All five files are selected; basenames are ignored. Send the CSRF header with no `Content-Type` override.
- `POST /api/confirm` with `{case_hash}` confirms current input.
- POST `/api/run` `{request}` startsactualagent. Requesttextarea andhelpfulpresetbuttons (editable): "Inspect this case, find a schedule, and prepare a review using evidence from your tools."; "Propose marking V02 unavailable for S2. Simulate it and prepare a review, but do not apply it."; afterfirstrepair "Propose marking V02 unavailable for S3. Simulate the change and explain any conflict."; "Diagnose why this case is infeasible, then compare restoring V02 for S3 with raising both V01 limits to360 minutes and3 shifts. Keep all changes hypothetical." Presets are prompts,never scriptedtoolresults. UsermustclickRun/presettoinvoke.
- `POST /api/cancel` with `{}` cancels the run.
- `POST /api/proposals/{proposal_id}/apply` with `{case_hash, proposal_hash, approval_token: proposal.apply_token, confirm: true}`. Require the explicit checkbox “I confirm this change to the supplied availability/limits”; show exact operations and confirmations. Apply only after click. A successful simulation does not apply. Refetch state; the user then requests a new plan.
- POST `/api/approve` `{result_id,case_hash,candidate_hash,approval_token:candidate.approve_token}`. Explicitbutton "Approve this schedule" onlyvalidnonhypotheticalcurrentverified candidate; no automaticapproval. Refetchstate.
- POST `/api/export` `{approval_id,case_hash,candidate_hash}`. Response `{artifact_id,name}`; then GET `/api/artifacts/{id}` downloadsZIP. Button "Download approved bundle". Noexportwhenunapproved.
- POST `/api/diagnosis-export` `{case_hash}` separatebutton onlyinfeasible/undetermineddiagnosisavailable.
- GET `/api/artifacts/{id}` existingdownload. Historical labeled fromstate, noautomaticdownload.

UI should retain onlycsrf andcurrentstateinmemory, no localStorage. Statuses IMPORTED, HUMAN_CONFIRMED, PLANNING, VERIFIED_FEASIBLE, HUMAN_APPROVED, EXPORTED, INFEASIBLE, UNDETERMINED, ERROR, CANCELLED, STALE. Casechangesremoveoldcandidateapproval; historymay remainmarkedhistorical. Showtooltracewithduration/results; no fabricatedthoughts. Ifmodelunavailable, showlocalsetupmessage andkeepinputs; neverpretendlive orsilentlyusefixtures asoutput. API backend enforcesallgates too. Loadingexample is not a recordedagentresult.
