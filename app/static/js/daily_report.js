// Autonomous Daily Manager page. "Run Now" calls POST /api/daily-manager/run (a manual trigger
// for the same pipeline the optional scheduler calls once per working day) and renders the
// resulting report; the history table loads past reports via GET /api/daily-manager/reports and
// fetches full detail on click. This file does no detection/classification itself — it only
// formats what the backend's deterministic pipeline already computed.

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("run-now-btn").addEventListener("click", onRunNow);
    document.getElementById("load-latest-btn").addEventListener("click", loadLatest);
    document.getElementById("refresh-history-btn").addEventListener("click", loadHistory);
    loadHistory();
    loadLatest();
});

async function onRunNow() {
    clearAlert("daily-report-alert");
    const dateInput = document.getElementById("run-date-input").value;
    const button = document.getElementById("run-now-btn");
    button.disabled = true;
    button.textContent = "Running…";
    try {
        const params = new URLSearchParams();
        if (dateInput) params.set("as_of", dateInput);
        const result = await apiRequest(`/daily-manager/run?${params.toString()}`, { method: "POST" });
        if (result.status === "skipped_non_working_day") {
            showAlert("daily-report-alert", "That date is not a working day (weekend) — no run was performed.", "warning");
        } else if (result.status === "already_ran") {
            showAlert("daily-report-alert", "Already ran for that date — showing the existing report.", "info");
            renderReport(result.report);
        } else {
            showAlert("daily-report-alert", "Run complete.", "success");
            renderReport(result.report);
        }
        loadHistory();
    } catch (err) {
        showAlert("daily-report-alert", err.message);
    } finally {
        button.disabled = false;
        button.textContent = "Run Now";
    }
}

async function loadLatest() {
    try {
        const report = await apiRequest("/daily-manager/reports/latest");
        renderReport(report);
    } catch (err) {
        if (err.status !== 404) showAlert("daily-report-alert", err.message);
    }
}

async function loadReportDetail(id) {
    clearAlert("daily-report-alert");
    try {
        const report = await apiRequest(`/daily-manager/reports/${id}`);
        renderReport(report);
    } catch (err) {
        showAlert("daily-report-alert", err.message);
    }
}

async function loadHistory() {
    try {
        const reports = await apiRequest("/daily-manager/reports?limit=30");
        const tbody = document.getElementById("history-rows");
        if (reports.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-muted small">No runs yet.</td></tr>';
            return;
        }
        tbody.innerHTML = reports
            .map(
                (r) => `
            <tr style="cursor: pointer;" data-report-id="${r.id}">
                <td>${r.run_date}</td>
                <td>${r.team_efficiency ?? "—"}</td>
                <td>${r.action_required ? '<span class="badge bg-warning text-dark">Yes</span>' : '<span class="badge bg-light text-dark">No</span>'}</td>
                <td>${r.actions_taken_count}</td>
            </tr>`
            )
            .join("");
        tbody.querySelectorAll("tr[data-report-id]").forEach((row) => {
            row.addEventListener("click", () => loadReportDetail(Number(row.dataset.reportId)));
        });
    } catch (err) {
        showAlert("daily-report-alert", err.message);
    }
}

function renderReport(report) {
    document.getElementById("report-section").classList.remove("d-none");
    document.getElementById("report-date-heading").textContent = `Report for ${report.run_date}`;
    document.getElementById("team-efficiency-badge").textContent =
        report.team_efficiency !== null && report.team_efficiency !== undefined ? `Team efficiency: ${report.team_efficiency}` : "Team efficiency: —";
    const actionBadge = document.getElementById("action-required-badge");
    if (report.action_required) {
        actionBadge.textContent = "Action required";
        actionBadge.className = "badge bg-warning text-dark";
    } else {
        actionBadge.textContent = "Nothing new today";
        actionBadge.className = "badge bg-success";
    }

    renderList("section-major-changes", report.major_changes, (c) => `<span class="badge bg-secondary">${escapeHtml(c.change_type)}</span> ${escapeHtml(c.label)}`, "No significant changes today.");
    renderList("section-recommended-actions", report.recommended_actions, (r) => escapeHtml(r), "No recommendations today.");
    renderList(
        "section-actions-taken",
        report.actions_taken,
        (a) => `<code>${escapeHtml(a.action)}</code> on ${escapeHtml(a.target)} — ${escapeHtml(a.status)}`,
        "No actions were taken today."
    );
    renderList(
        "section-completed-work",
        report.completed_work,
        (t) => `${escapeHtml(t.title)} ${t.assignee ? "(" + escapeHtml(t.assignee) + ")" : ""}`,
        "No tasks completed today."
    );
    renderList(
        "section-delayed-work",
        report.delayed_work,
        (t) => `${escapeHtml(t.title)} — ${t.delay_days} day(s) late`,
        "No delayed tasks."
    );
    renderList(
        "section-at-risk",
        report.at_risk_deadlines,
        (t) => `${escapeHtml(t.title)} — ${escapeHtml(t.risk)} risk, ${t.days_left} day(s) left`,
        "No at-risk deadlines."
    );
    renderList(
        "section-workload",
        report.workload_problems,
        (w) => `${escapeHtml(w.name || "Team")} — ${escapeHtml(w.issue)} (${w.utilization_pct ?? w.spread_pct ?? "—"}%)`,
        "No workload problems."
    );
    renderList(
        "section-quality",
        report.quality_issues,
        (q) => `${escapeHtml(q.title)} — score ${q.quality_score} (${escapeHtml(q.name)})`,
        "No quality issues."
    );
    renderList(
        "section-project-risks",
        report.project_risks,
        (p) => `${escapeHtml(p.name)} — ${p.progress_pct}% done, ${p.days_left} day(s) left`,
        "No project risks."
    );
}

function renderList(elementId, items, formatter, emptyText) {
    const el = document.getElementById(elementId);
    if (!items || items.length === 0) {
        el.innerHTML = `<p class="text-muted small mb-0">${emptyText}</p>`;
        return;
    }
    el.innerHTML = `<ul class="mb-0 small">${items.map((item) => `<li>${formatter(item)}</li>`).join("")}</ul>`;
}
