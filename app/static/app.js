"use strict";

/* TalentFlow AI recruiter UI.
 * All untrusted content (names, resume text, criteria, evidence) is inserted with textContent
 * through the h() builder. No HTML-string injection APIs are used. Failed API calls are shown, never replaced
 * with mock data.
 */
(() => {
  const state = { stages: [], jobs: [], candidates: [], selectedCandidateId: null };
  const VIEWS = ["dashboard", "jobs", "candidates", "interviews", "reports"];
  const $ = (selector) => document.querySelector(selector);

  function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "text") node.textContent = String(value);
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else if (key === "value" || key === "checked") node[key] = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function setStatus(text) { $("#status").textContent = text || ""; }
  function showAlert(text) {
    const box = $("#alert");
    box.textContent = text || "";
    box.hidden = !text;
  }
  function setBusy(form, busy) {
    form.querySelectorAll("button").forEach((b) => { b.disabled = busy; });
  }
  function fmt(iso) {
    if (!iso) return "-";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
  }
  function emptyNode(text) { return h("p", { class: "empty", text }); }

  function table(caption, headers, rows, emptyText) {
    if (rows.length === 0) return emptyNode(emptyText);
    return h("table", {},
      h("caption", { text: caption }),
      h("thead", {}, h("tr", {}, headers.map((t) => h("th", { scope: "col", text: t })))),
      h("tbody", {}, rows.map((cells) => h("tr", {}, cells.map((c) => h("td", {}, c ?? "-")))))
    );
  }

  async function api(path, options = {}) {
    const init = { method: options.method || "GET", headers: {} };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    if (options.form) init.body = options.form;
    let response;
    try {
      response = await fetch(path, init);
    } catch (_err) {
      throw new Error("Cannot reach the TalentFlow API. Check that the server is running.");
    }
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (_err) { data = null; }
    if (!response.ok) {
      let message = (data && data.error && data.error.message) || `Request failed (HTTP ${response.status}).`;
      const first = data && data.error && data.error.details && data.error.details[0];
      if (first && first.field) message += ` (${first.field}: ${first.message})`;
      throw new Error(message);
    }
    return data;
  }

  function showView(name) {
    for (const v of VIEWS) $(`#view-${v}`).hidden = v !== name;
    document.querySelectorAll("nav button").forEach((b) => {
      if (b.dataset.view === name) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    showAlert("");
    const loaders = { dashboard: loadDashboard, jobs: loadJobs, candidates: loadCandidates,
                      interviews: loadInterviews, reports: () => {} };
    run(loaders[name]);
  }

  // Shows a loading state, surfaces failures in the alert region, and clears the loading text only
  // if the action did not replace it with its own success message.
  async function run(fn) {
    setStatus("Loading...");
    try {
      await fn();
    } catch (err) {
      showAlert(err.message);
    } finally {
      if ($("#status").textContent === "Loading...") setStatus("");
    }
  }

  // ---- Dashboard -------------------------------------------------------
  async function loadDashboard() {
    const data = await api("/api/reports/funnel");
    state.stages = data.stages.map((s) => s.stage);
    fillStageSelects();
    $("#funnel-table").replaceChildren(table("Candidates per stage", ["Stage", "Count"],
      data.stages.map((s) => [s.stage, String(s.count)]), "No candidates yet."));
    $("#sources-table").replaceChildren(table("Candidates per source", ["Source", "Count"],
      data.sources.map((s) => [s.source, String(s.count)]), "No sources recorded."));
    $("#summary-list").replaceChildren(
      h("ul", {},
        h("li", { text: `Jobs: ${data.jobs.open} open, ${data.jobs.archived} archived` }),
        h("li", { text: `Jobs with assessments: ${data.jobs.with_assessments}` }),
        h("li", { text: `Assessments stored: ${data.assessments.total}` }),
        h("li", { text: `Interviews scheduled upcoming: ${data.interviews.upcoming}` }),
        h("li", { text: `Interviews awaiting outcome: ${data.interviews.awaiting_outcome}` })
      ));
    const overdue = data.overdue_feedback;
    $("#overdue-list").replaceChildren(
      h("p", { class: "disclaimer", text: `Threshold: more than ${overdue.threshold_hours} hours in "Submitted to Client".` }),
      table("Overdue candidates", ["Candidate", "Entered stage", "Hours waiting"],
        overdue.items.map((i) => [i.display_name, fmt(i.entered_stage_at), String(i.hours_waiting)]),
        "No candidates are past the feedback threshold."));
  }

  function fillStageSelects() {
    const filter = document.querySelector("#search-form select[name=stage]");
    filter.replaceChildren(h("option", { value: "", text: "All stages" }),
      ...state.stages.map((s) => h("option", { value: s, text: s })));
  }

  // ---- Jobs ------------------------------------------------------------
  async function loadJobs() {
    const data = await api("/api/jobs?limit=100");
    state.jobs = data.items;
    const rows = data.items.map((job) => [
      job.title,
      job.location || "-",
      job.status,
      String(job.requirements.length),
      job.status === "open"
        ? h("button", { type: "button", class: "secondary", text: "Archive",
            onclick: () => archiveJob(job.id) })
        : "-",
    ]);
    $("#jobs-table").replaceChildren(table("Job requisitions", ["Title", "Location", "Status", "Criteria", "Action"],
      rows, "No requisitions yet. Create one using the form."));
    fillJobSelects();
  }

  function fillJobSelects() {
    const select = document.querySelector("#interview-form select[name=job_id]");
    select.replaceChildren(h("option", { value: "", text: "None" }),
      ...state.jobs.map((j) => h("option", { value: j.id, text: j.title })));
  }

  async function archiveJob(id) {
    run(async () => {
      await api(`/api/jobs/${id}`, { method: "PATCH", body: { status: "archived" } });
      await loadJobs();
    });
  }

  $("#job-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const requirements = String(data.get("requirements") || "").split("\n").map((s) => s.trim()).filter(Boolean);
    const body = {
      title: String(data.get("title") || "").trim(),
      location: String(data.get("location") || "").trim(),
      description: String(data.get("description") || ""),
      requirements,
    };
    const minYears = data.get("min_years");
    const maxYears = data.get("max_years");
    if (minYears !== "") body.min_years = Number(minYears);
    if (maxYears !== "") body.max_years = Number(maxYears);
    setBusy(form, true);
    run(async () => {
      await api("/api/jobs", { method: "POST", body });
      form.reset();
      setStatus("Requisition created.");
      await loadJobs();
    }).finally(() => setBusy(form, false));
  });

  // ---- Candidates ------------------------------------------------------
  async function loadCandidates() {
    if (state.stages.length === 0) {
      const funnel = await api("/api/reports/funnel");
      state.stages = funnel.stages.map((s) => s.stage);
      fillStageSelects();
    }
    const form = $("#search-form");
    const params = new URLSearchParams({ limit: "100" });
    const q = String(new FormData(form).get("q") || "").trim();
    const stage = String(new FormData(form).get("stage") || "");
    if (q) params.set("q", q);
    if (stage) params.set("stage", stage);
    const data = await api(`/api/candidates?${params.toString()}`);
    state.candidates = data.items;
    const rows = data.items.map((c) => [
      h("button", { type: "button", class: "secondary", text: c.display_name,
        onclick: () => run(() => openCandidate(c.id)) }),
      c.stage,
      c.source,
      c.parse_status,
    ]);
    $("#candidates-table").replaceChildren(
      table(`Candidates (${data.total} matching)`, ["Name", "Stage", "Source", "Resume"],
        rows, "No candidates match. Upload a resume to add one."));
    fillCandidateSelects();
  }

  $("#search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run(loadCandidates);
  });

  function fillCandidateSelects() {
    const select = document.querySelector("#interview-form select[name=candidate_id]");
    const previous = select.value;
    select.replaceChildren(h("option", { value: "", text: "Select a candidate" }),
      ...state.candidates.map((c) => h("option", { value: c.id, text: `${c.display_name} (#${c.id})` })));
    if (previous) select.value = previous;
  }

  $("#upload-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const file = data.get("file");
    if (!file || !file.name) {
      showAlert("Choose a resume file (PDF, DOCX, TXT or Markdown).");
      return;
    }
    setBusy(form, true);
    run(async () => {
      const candidate = await api("/api/candidates/upload-resume", { method: "POST", form: data });
      form.reset();
      form.elements.source.value = "upload";
      setStatus(`Resume parsed for ${candidate.display_name}.`);
      await loadCandidates();
      await openCandidate(candidate.id);
    }).finally(() => setBusy(form, false));
  });

  async function openCandidate(id) {
    const detail = await api(`/api/candidates/${id}`);
    const events = await api(`/api/candidates/${id}/pipeline-events`);
    const jobs = (state.jobs.length ? state.jobs : (await api("/api/jobs?limit=100")).items);
    state.jobs = jobs;
    fillJobSelects();
    state.selectedCandidateId = id;

    const stageSelect = h("select", { name: "to_stage" },
      h("option", { value: "", text: "Choose a stage" }),
      state.stages.filter((s) => s !== detail.stage).map((s) => h("option", { value: s, text: s })));
    const stageForm = h("form", { onsubmit: (e) => submitStage(e, id) },
      h("label", {}, "Move to stage", stageSelect),
      h("label", {}, "Reason (optional) ", h("input", { name: "reason", maxlength: "500" })),
      h("button", { type: "submit", text: "Update stage" }));

    const jobSelect = h("select", { name: "job_id" },
      jobs.filter((j) => j.status === "open").map((j) => h("option", { value: j.id, text: j.title })));
    const assessForm = h("form", { onsubmit: (e) => submitAssessment(e, id) },
      h("label", {}, "Assess against job", jobSelect),
      h("button", { type: "submit", text: "Run fitment assessment" }),
      h("p", { class: "disclaimer", text: "Deterministic fitment (rules). Missing means not evidenced in the text, not proof the candidate lacks the skill." }));

    const historyItems = events.length
      ? h("ol", {}, events.map((e) => h("li", { text: `${fmt(e.created_at)}: ${e.prior_stage ?? "start"} -> ${e.new_stage}${e.reason ? ` (${e.reason})` : ""}` })))
      : emptyNode("No stage changes recorded.");

    const panel = $("#candidate-detail");
    panel.replaceChildren(
      h("h3", { text: detail.display_name }),
      h("dl", {},
        h("dt", { text: "Stage" }), h("dd", { text: detail.stage }),
        h("dt", { text: "Source" }), h("dd", { text: detail.source }),
        h("dt", { text: "Email" }), h("dd", { text: detail.email || "-" }),
        h("dt", { text: "Resume" }), h("dd", { text: `${detail.parse_status}${detail.resume_format ? ` (${detail.resume_format})` : ""}` })),
      h("h4", { text: "Extracted resume text (verify before relying on it)" }),
      h("pre", { class: "pre", text: detail.resume_text || "No resume text on file." }),
      h("h4", { text: "Pipeline history" }),
      historyItems,
      stageForm,
      h("h4", { text: "Assessment" }),
      assessForm,
      h("div", { id: "assessment-result", "aria-live": "polite" }),
    );
    panel.hidden = false;
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function submitStage(event, candidateId) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    if (!data.get("to_stage")) { showAlert("Choose a stage before updating."); return; }
    setBusy(form, true);
    try {
      await api(`/api/candidates/${candidateId}/stage`, {
        method: "PATCH",
        body: { to_stage: data.get("to_stage"), actor: "recruiter (web)", reason: String(data.get("reason") || "") || null },
      });
      setStatus("Stage updated.");
      await loadCandidates();
      await openCandidate(candidateId);
    } catch (err) {
      showAlert(err.message);
    } finally {
      setBusy(form, false);
    }
  }

  async function submitAssessment(event, candidateId) {
    event.preventDefault();
    const form = event.currentTarget;
    const jobId = Number(new FormData(form).get("job_id"));
    if (!jobId) { showAlert("Select an open job to assess against."); return; }
    setBusy(form, true);
    try {
      const a = await api("/api/assessments", { method: "POST", body: { candidate_id: candidateId, job_id: jobId } });
      renderAssessment(a);
    } catch (err) {
      showAlert(err.message);
    } finally {
      setBusy(form, false);
    }
  }

  function criteriaList(title, items, render) {
    return h("div", {},
      h("h5", { text: `${title} (${items.length})` }),
      items.length ? h("ul", {}, items.map(render)) : emptyNode("None."));
  }

  function renderAssessment(a) {
    const byStatus = (s) => a.criteria.filter((c) => c.status === s);
    const result = $("#assessment-result");
    result.replaceChildren(
      h("h4", { text: "Assessment result" }),
      h("p", {}, h("span", { class: "badge", text: `Fitment ${a.fitment_percent === null ? "not scored" : a.fitment_percent + "%"}` }),
        " ", h("span", { class: "badge", text: `Summary: ${a.summary_source}` }),
        " ", h("span", { class: "badge", text: `AI: ${a.ai_status}` })),
      h("p", { text: a.summary }),
      criteriaList("Matched", byStatus("matched"), (c) => h("li", {}, h("strong", { text: c.criterion }), ` - evidence: ${c.evidence}`)),
      criteriaList("Missing / not evidenced", byStatus("missing"), (c) => h("li", { text: c.criterion })),
      criteriaList("Needs recruiter review", byStatus("needs_review"), (c) => h("li", {}, h("strong", { text: c.criterion }), c.note ? ` - ${c.note}` : "")),
      h("p", { class: "disclaimer", text: `Assessment ${a.id} stored for review (version ${a.assessment_version}). No stage was changed automatically.` }));
  }

  // ---- Interviews ------------------------------------------------------
  async function loadInterviews() {
    if (state.candidates.length === 0) {
      state.candidates = (await api("/api/candidates?limit=100")).items;
    }
    if (state.jobs.length === 0) {
      state.jobs = (await api("/api/jobs?limit=100")).items;
    }
    fillCandidateSelects();
    fillJobSelects();
    const data = await api("/api/interviews?limit=100");
    const rows = data.items.map((i) => [
      `#${i.candidate_id}`,
      i.stage,
      fmt(i.scheduled_at),
      i.timezone,
      h("select", { "aria-label": `Status for interview ${i.id}`, "data-interview": i.id },
        ["scheduled", "completed", "cancelled", "no_show"].map((s) => h("option", { value: s, text: s, selected: s === i.status }))),
      h("button", { type: "button", class: "secondary", text: "Save status", onclick: () => saveInterviewStatus(i.id) }),
    ]);
    $("#interviews-table").replaceChildren(
      table(`Interviews (${data.total})`, ["Candidate", "Stage", "Scheduled (UTC shown locally)", "Timezone", "Status", ""],
        rows, "No interviews scheduled."));
  }

  async function saveInterviewStatus(id) {
    const select = document.querySelector(`select[data-interview="${id}"]`);
    run(async () => {
      await api(`/api/interviews/${id}`, { method: "PATCH", body: { status: select.value } });
      setStatus("Interview updated.");
      await loadInterviews();
    });
  }

  $("#interview-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const candidateId = Number(data.get("candidate_id"));
    const when = String(data.get("scheduled_at") || "");
    if (!candidateId) { showAlert("Select a candidate."); return; }
    if (!when) { showAlert("Enter a date and time."); return; }
    const jobId = data.get("job_id") ? Number(data.get("job_id")) : null;
    const body = {
      candidate_id: candidateId,
      job_id: jobId,
      stage: String(data.get("stage")),
      scheduled_at: new Date(when).toISOString(),
      timezone: String(data.get("timezone") || "UTC").trim(),
      notes: String(data.get("notes") || "") || null,
    };
    setBusy(form, true);
    run(async () => {
      await api("/api/interviews", { method: "POST", body });
      form.reset();
      setStatus("Interview scheduled.");
      await loadInterviews();
    }).finally(() => setBusy(form, false));
  });

  // ---- Boot ------------------------------------------------------------
  document.querySelectorAll("nav button").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
  const tzField = document.querySelector("#interview-form input[name=timezone]");
  if (tzField) tzField.value = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  showView("dashboard");
})();
