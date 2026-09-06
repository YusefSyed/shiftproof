(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  };
  const c = {
    demo: $("load-demo"),
    note: $("load-note-demo"),
    form: $("import-form"),
    confirm: $("confirm-inputs"),
    confirmCase: $("confirm-case"),
    request: $("request"),
    run: $("run-request"),
    cancel: $("cancel-run"),
    approve: $("approve-schedule"),
    export: $("export-approved"),
    diagnosis: $("export-diagnosis"),
  };
  let state, poll;
  const clear = (n) => n.replaceChildren();
  const notice = (m) => {
    $("notice").hidden = !m;
    $("notice").textContent = m || "";
  };
  const status = (v) =>
    String(v || "waiting")
      .replaceAll("_", " ")
      .toLowerCase();
  async function api(path, options = {}) {
    const h = new Headers(options.headers || {});
    if (typeof options.body === "string" && !h.has("Content-Type"))
      h.set("Content-Type", "application/json");
    if (state?.csrf && options.method && options.method !== "GET")
      h.set("X-CSRF-Token", state.csrf);
    const r = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: h,
    });
    const b = await r.json().catch(() => ({}));
    if (!r.ok)
      throw new Error(
        typeof b.error === "string"
          ? b.error
          : typeof b.detail === "string"
            ? b.detail
            : `Request failed (${r.status})`,
      );
    return b;
  }
  async function refresh() {
    try {
      state = await api("/api/state");
      notice(state.last_error || "");
      render();
    } catch (e) {
      notice(e.message);
    }
  }
  function table(parent, heads, rows) {
    const t = el("table"),
      h = el("thead"),
      r = el("tr"),
      b = el("tbody"),
      w = el("div", undefined, "table-wrap");
    heads.forEach((x) => r.append(el("th", x)));
    h.append(r);
    rows.forEach((row) => {
      const tr = el("tr");
      row.forEach((x) => tr.append(el("td", x)));
      b.append(tr);
    });
    t.append(h, b);
    w.append(t);
    parent.append(w);
  }
  function maps(k) {
    return {
      v: new Map(k.volunteers.map((x) => [x.volunteer_id, x])),
      s: new Map(k.shifts.map((x) => [x.shift_id, x])),
      a: new Map(
        k.availability.map((x) => [`${x.volunteer_id}:${x.shift_id}`, x]),
      ),
      d: new Map(
        k.coverage.map((x) => [`${x.shift_id}:${x.role}`, x.required_count]),
      ),
    };
  }
  function time(shift, zone) {
    try {
      const d = new Intl.DateTimeFormat(undefined, {
        timeZone: zone,
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
      const z = new Intl.DateTimeFormat(undefined, {
        timeZone: zone,
        hour: "numeric",
        minute: "2-digit",
        timeZoneName: "short",
      });
      return `${d.format(new Date(shift.start))}–${z.format(new Date(shift.end))}`;
    } catch {
      return `${shift.start}–${shift.end}`;
    }
  }
  function renderCase() {
    const out = $("case-summary"),
      k = state.case;
    clear(out);
    $("input-state").textContent = k ? status(state.status) : "No case loaded";
    if (!k)
      return out.append(
        el(
          "p",
          "Load an example or import a case to inspect its inputs.",
          "empty",
        ),
      );
    const m = maps(k);
    out.append(
      el(
        "p",
        `${k.case_id} · Week of ${k.week_start} · ${k.timezone}`,
        "quiet",
      ),
      el(
        "p",
        `${state.missing_availability_pairs || 0} volunteer/shift pairs have no availability record and are treated as unavailable.`,
        "callout",
      ),
    );
    table(
      out,
      ["Shift", `Time (${k.timezone})`, "Exact staffing"],
      k.shifts.map((s) => [
        s.title,
        time(s, k.timezone),
        k.roles
          .map((role) => `${m.d.get(`${s.shift_id}:${role}`) || 0} ${role}`)
          .join(", "),
      ]),
    );
    const limits = el("details");
    limits.append(
      el(
        "summary",
        `Qualifications and workload limits (${k.volunteers.length})`,
      ),
    );
    table(
      limits,
      ["Volunteer", "Roles", "Maximum minutes", "Maximum shifts", "Source"],
      k.volunteers.map((v) => [
        `${v.display_name} (${v.volunteer_id})`,
        v.roles.join(", "),
        v.max_total_minutes,
        v.max_shifts,
        v.source_ref,
      ]),
    );
    out.append(limits);
    const av = el("details");
    av.append(el("summary", "Availability and preferences by volunteer"));
    table(
      av,
      ["Volunteer", ...k.shifts.map((s) => s.shift_id)],
      k.volunteers.map((v) => [
        v.display_name,
        ...k.shifts.map(
          (s) =>
            m.a.get(`${v.volunteer_id}:${s.shift_id}`)?.status || "unavailable",
        ),
      ]),
    );
    k.availability
      .filter((a) => a.note || a.source_ref)
      .forEach((a) => {
        const d = el("details", undefined, "fact-details");
        d.append(
          el("summary", `${a.volunteer_id} · ${a.shift_id} · ${a.status}`),
          el("p", a.note ? `Note: ${a.note}` : "No source note."),
          el(
            "p",
            a.source_ref
              ? `Source reference: ${a.source_ref}`
              : "No source reference.",
          ),
        );
        av.append(d);
      });
    out.append(av);
    if (k.locks.length) {
      const l = el("details");
      l.append(el("summary", `Pinned assignments (${k.locks.length})`));
      table(
        l,
        ["Volunteer", "Shift", "Role", "Source"],
        k.locks.map((x) => [
          x.volunteer_id,
          x.shift_id,
          x.role,
          x.source_ref || "No source reference",
        ]),
      );
      out.append(l);
    }
  }
  function renderSchedule() {
    const out = $("schedule-content"),
      x = state.candidate,
      code = x?.solver?.status || state.status;
    clear(out);
    const label =
      code === "INFEASIBLE"
        ? "Infeasible"
        : ["UNDETERMINED", "UNKNOWN"].includes(code)
          ? "Undetermined"
          : code === "ERROR"
            ? "Error"
            : code === "CANCELLED"
              ? "Cancelled"
              : state.running
                ? "Planning"
                : "Waiting";
    $("candidate-state").textContent = x?.verification?.valid
      ? "Verified"
      : label;
    if (!x?.verification)
      return out.append(
        el(
          "p",
          label === "Infeasible"
            ? "No schedule was produced because the current case is infeasible. Review the diagnosis evidence below."
            : label === "Undetermined"
              ? "The local run did not establish a schedule or infeasibility."
              : label === "Error"
                ? "The local run ended with an error. No schedule is available for approval."
                : "A verified schedule will appear after a request completes.",
          "empty",
        ),
      );
    const m = maps(state.case),
      v = x.verification;
    const stats = el("div", undefined, "metrics");
    [
      [v.preferred, "Preferred assignments"],
      [v.non_preferred, "Other available assignments"],
      [v.replacements, "Replaced assignments"],
    ].forEach(([value, label]) => {
      const metric = el("div", undefined, "metric");
      metric.append(el("strong", value), el("span", label));
      stats.append(metric);
    });
    out.append(stats);
    const baseline = new Set(
      (x.baseline_assignments || []).map(
        (a) => `${a.volunteer_id}|${a.shift_id}|${a.role}`,
      ),
    );
    const assignments = [...(x.solver.assignments || [])].sort(
      (a, b) =>
        (m.s.get(a.shift_id)?.start || "").localeCompare(
          m.s.get(b.shift_id)?.start || "",
        ) ||
        state.case.roles.indexOf(a.role) - state.case.roles.indexOf(b.role) ||
        a.volunteer_id.localeCompare(b.volunteer_id),
    );
    table(
      out,
      ["Shift", "Role", "Volunteer", "Change"],
      assignments.map((a) => [
        m.s.get(a.shift_id)?.title || a.shift_id,
        a.role,
        m.v.get(a.volunteer_id)?.display_name || a.volunteer_id,
        baseline.size
          ? baseline.has(`${a.volunteer_id}|${a.shift_id}|${a.role}`)
            ? "Retained"
            : "Changed"
          : "Initial plan",
      ]),
    );
    out.append(el("h3", "Volunteer workloads"));
    table(
      out,
      ["Volunteer", "Minutes / limit", "Shifts / limit"],
      state.case.volunteers.map((person) => {
        const work = v.workload[person.volunteer_id];
        return [
          person.display_name,
          `${work.minutes} / ${person.max_total_minutes}`,
          `${work.shifts} / ${person.max_shifts}`,
        ];
      }),
    );
    const proof = el("details");
    proof.append(el("summary", "Verification and optimization evidence"));
    proof.append(
      el(
        "p",
        `Independent checks: ${v.valid ? "passed" : "failed"}. Workload dispersion: ${v.dispersion} (sum of pairwise differences in minutes).`,
      ),
    );
    table(
      proof,
      ["Phase", "Status", "Value", "Optimality proved"],
      (x.solver.phases || []).map((p) => [
        status(p.name),
        p.status,
        p.value ?? "Not established",
        p.proven_optimal ? "Yes" : "No",
      ]),
    );
    table(
      proof,
      ["Assignment", "Source records"],
      assignments.map((a) => [
        `${a.shift_id} · ${a.role} · ${a.volunteer_id}`,
        [
          m.s.get(a.shift_id)?.source_ref,
          m.v.get(a.volunteer_id)?.source_ref,
          m.a.get(`${a.volunteer_id}:${a.shift_id}`)?.source_ref,
        ]
          .filter(Boolean)
          .join("; "),
      ]),
    );
    out.append(proof);
  }
  function renderTrace() {
    const out = $("trace");
    clear(out);
    if (!state.trace?.length)
      return out.append(
        el("li", "Requests and tool activity will appear here.", "empty"),
      );
    state.trace.forEach((item) => {
      const row = el("li");
      row.append(
        el("strong", item.tool || item.type || "Activity"),
        el(
          "p",
          `${status(item.status)}${item.duration ? ` · ${item.duration}s` : ""}`,
          "trace-detail",
        ),
      );
      if (item.result_id)
        row.append(el("p", `Result: ${item.result_id}`, "trace-detail"));
      if (item.detail) row.append(el("p", item.detail, "trace-detail"));
      out.append(row);
    });
  }
  function renderReview() {
    const d = $("diagnosis-content"),
      p = $("proposal-content");
    clear(d);
    clear(p);
    $("approval-state").textContent = state.approval
      ? "Approved"
      : "Not approved";
    d.hidden = !state.diagnosis;
    if (state.diagnosis) {
      d.append(el("h3", `${status(state.diagnosis.status)} diagnosis`));
      if (state.diagnosis.limitation)
        d.append(el("p", state.diagnosis.limitation, "quiet"));
      (state.diagnosis.facts || []).forEach((f) => {
        const li = el("div");
        const z = f.details || {};
        const [v, ...tail] = f.entity_ids || [];
        const role = tail.at(-1);
        li.append(
          el(
            "p",
            f.code === "sole_eligible_capacity"
              ? `${v} is the only eligible ${role} for ${z.required_shifts} required shifts (${z.required_minutes} minutes), but their limits are ${z.max_shifts} shifts and ${z.max_total_minutes} minutes.`
              : `${f.code}: ${(f.entity_ids || []).join(", ")}`,
          ),
        );
        const q = el("details", undefined, "fact-details");
        q.append(
          el("summary", "Evidence references"),
          el(
            "p",
            (f.source_refs || []).join(", ") ||
              "No source references were returned.",
          ),
        );
        li.append(q);
        d.append(li);
      });
    }
    (state.proposals || []).forEach((q) => {
      const box = el("article", undefined, "proposal");
      const m = maps(state.case);
      box.append(el("h3", "Proposed change"), el("p", q.proposal_id, "quiet"));
      const changes = el("ul");
      (q.operations || []).forEach((op) => {
        let description;
        if (op.op === "set_availability") {
          const old =
            m.a.get(`${op.volunteer_id}:${op.shift_id}`)?.status ||
            "unavailable";
          description = `${m.v.get(op.volunteer_id)?.display_name || op.volunteer_id} (${op.volunteer_id}), ${m.s.get(op.shift_id)?.title || op.shift_id} (${op.shift_id}): ${old} → ${op.status}.`;
        } else if (op.op === "set_limits") {
          const person = m.v.get(op.volunteer_id);
          description = `${person?.display_name || op.volunteer_id} (${op.volunteer_id}): maximum minutes ${person?.max_total_minutes} → ${op.max_total_minutes}; maximum shifts ${person?.max_shifts} → ${op.max_shifts}.`;
        } else if (op.op === "remove_lock") {
          const lock = state.case.locks.find((x) => x.lock_id === op.lock_id);
          description = `Release pinned assignment ${op.lock_id}: ${lock?.volunteer_id}, ${lock?.shift_id}, ${lock?.role}.`;
        } else description = "Unsupported operation; do not apply.";
        changes.append(el("li", description));
      });
      box.append(
        changes,
        el("p", "This proposal has not changed the confirmed case.", "callout"),
      );
      (q.confirmations || []).forEach((text) =>
        box.append(el("p", text, "quiet")),
      );
      if (q.simulation) {
        const simulation = q.simulation,
          checked = simulation.verification;
        const label = checked?.valid
          ? "Hypothetical: verified feasible"
          : `Hypothetical: ${status(simulation.solver?.status)}`;
        box.append(el("p", label, "state-label"));
        if (checked)
          box.append(
            el(
              "p",
              `${checked.preferred} preferred assignments; ${checked.replacements} replacements. Not an approved schedule.`,
            ),
          );
        const preview = el("details");
        preview.append(el("summary", "Inspect the hypothetical result"));
        if (checked?.valid)
          table(
            preview,
            ["Shift", "Role", "Volunteer"],
            simulation.solver.assignments.map((a) => [
              a.shift_id,
              a.role,
              `${m.v.get(a.volunteer_id)?.display_name || a.volunteer_id} (${a.volunteer_id})`,
            ]),
          );
        if (simulation.diagnosis) {
          (simulation.diagnosis.facts || []).forEach((f) => {
            const z = f.details || {};
            preview.append(
              el(
                "p",
                f.code === "sole_eligible_capacity"
                  ? `${f.entity_ids[0]} alone must cover ${z.required_shifts} shifts / ${z.required_minutes} minutes, above limits of ${z.max_shifts} / ${z.max_total_minutes}.`
                  : `${status(f.code)}: ${f.entity_ids.join(", ")}`,
              ),
            );
            preview.append(
              el("p", `Evidence: ${(f.source_refs || []).join("; ")}`, "quiet"),
            );
          });
          if (simulation.diagnosis.limitation)
            preview.append(el("p", simulation.diagnosis.limitation));
        }
        box.append(preview);
      } else box.append(el("p", "Not simulated yet.", "quiet"));
      const check = el("input");
      check.type = "checkbox";
      check.id = `confirm-${q.proposal_id}`;
      check.disabled =
        !!state.running ||
        q.base_case_hash !== state.case_hash ||
        !q.apply_token;
      const label = el(
        "label",
        " I confirm this exact change to the supplied availability/limits.",
      );
      label.htmlFor = check.id;
      const b = el("button", "Apply confirmed change", "button secondary");
      b.disabled = true;
      check.addEventListener(
        "change",
        () => (b.disabled = state.running || !check.checked || check.disabled),
      );
      b.addEventListener("click", () =>
        mutate(`/api/proposals/${encodeURIComponent(q.proposal_id)}/apply`, {
          case_hash: state.case_hash,
          proposal_hash: q.proposal_hash,
          approval_token: q.apply_token,
          confirm: true,
        }),
      );
      box.append(check, label, b);
      p.append(box);
    });
    if (!state.proposals?.length)
      p.append(
        el("p", "Hypothetical changes will appear here for review.", "empty"),
      );
    const files = $("artifact-content");
    clear(files);
    if (state.approval)
      files.append(
        el(
          "p",
          `Approved at ${new Date(state.approval.approved_at).toLocaleString()}. Calendar files are snapshots, not invitations or synchronized updates.`,
        ),
      );
    else
      files.append(
        el(
          "p",
          "A schedule needs a separate approval before export. Existing files cannot be recalled.",
          "quiet",
        ),
      );
    (state.artifacts || []).forEach((a) => {
      const row = el("p");
      const link = el("a", a.name);
      link.href = `/api/artifacts/${encodeURIComponent(a.artifact_id)}`;
      link.download = a.name;
      row.append(
        link,
        el(
          "span",
          a.historical ? " · Historical snapshot" : " · Current snapshot",
        ),
      );
      files.append(row);
    });
  }
  function download(a) {
    const link = el("a");
    link.href = `/api/artifacts/${encodeURIComponent(a.artifact_id)}`;
    link.download = a.name || "";
    document.body.append(link);
    link.click();
    link.remove();
  }
  function render() {
    $("source-label").textContent =
      state.source_kind === "synthetic"
        ? "Synthetic community pantry example"
        : state.source_kind === "uploaded"
          ? "Uploaded scheduling case"
          : "Local volunteer scheduling";
    $("status-chip").textContent = status(state.status);
    $("model-state").textContent = state.model?.ready
      ? "Local model ready"
      : "Local model unavailable";
    $("model-detail").textContent = state.model?.ready
      ? `Ready: ${state.model.tag || "local model"}. Results require verification and human approval.`
      : state.model?.detail ||
        "Complete local model setup, then retry your request.";
    renderCase();
    renderTrace();
    renderSchedule();
    renderReview();
    const run = !!state.running,
      can =
        state.candidate?.verification?.valid &&
        state.candidate?.approve_token &&
        !state.approval;
    c.confirm.disabled = !state.case || state.confirmed || run;
    c.confirm.checked = !!state.confirmed;
    c.confirmCase.disabled =
      !state.case || state.confirmed || run || !c.confirm.checked;
    c.run.disabled = !state.confirmed || !state.model?.ready || run;
    c.cancel.disabled = !run;
    c.approve.disabled = run || !can;
    c.export.disabled = run || !state.approval;
    c.diagnosis.hidden =
      !state.diagnosis ||
      !["INFEASIBLE", "UNDETERMINED"].includes(state.status);
    c.diagnosis.disabled = run;
    if (run && !poll) poll = setInterval(refresh, 1000);
    if (!run && poll) {
      clearInterval(poll);
      poll = null;
    }
  }
  async function mutate(path, payload) {
    try {
      const result = await api(path, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await refresh();
      return result;
    } catch (e) {
      notice(e.message);
      return null;
    }
  }
  c.demo.onclick = () => mutate("/api/demo", { variant: "baseline" });
  c.note.onclick = () => mutate("/api/demo", { variant: "injected_note" });
  c.confirm.onchange = () =>
    (c.confirmCase.disabled = state.running || !c.confirm.checked);
  c.confirmCase.onclick = () =>
    mutate("/api/confirm", { case_hash: state.case_hash });
  c.run.onclick = () => {
    const request = c.request.value.trim();
    if (!request)
      return notice(
        "Describe the scheduling review you need before running it.",
      );
    mutate("/api/run", { request });
  };
  c.cancel.onclick = () => mutate("/api/cancel", {});
  c.approve.onclick = () =>
    mutate("/api/approve", {
      result_id: state.candidate.result_id,
      case_hash: state.case_hash,
      candidate_hash: state.candidate.candidate_hash,
      approval_token: state.candidate.approve_token,
    });
  c.export.onclick = async () => {
    const r = await mutate("/api/export", {
      approval_id: state.approval.approval_id,
      case_hash: state.case_hash,
      candidate_hash: state.candidate.candidate_hash,
    });
    if (r?.artifact_id) download(r);
  };
  c.diagnosis.onclick = async () => {
    const r = await mutate("/api/diagnosis-export", {
      case_hash: state.case_hash,
    });
    if (r?.artifact_id) download(r);
  };
  document.querySelectorAll(".preset").forEach(
    (b) =>
      (b.onclick = () => {
        c.request.value = b.dataset.request || "";
        c.request.focus();
      }),
  );
  c.form.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData();
    let ok = true;
    [
      "case.json",
      "volunteers.csv",
      "shifts.csv",
      "coverage.csv",
      "availability.csv",
    ].forEach((n) => {
      const file = c.form.elements.namedItem(n)?.files[0];
      if (file) f.append(n, file);
      else ok = false;
    });
    if (!ok)
      return notice("Select each of the five required files before importing.");
    try {
      await api("/api/import", { method: "POST", body: f });
      await refresh();
    } catch (e) {
      notice(e.message);
    }
  };
  refresh();
})();
