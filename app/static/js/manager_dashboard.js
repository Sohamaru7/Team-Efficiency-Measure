// Manager Dashboard rendering. Every number displayed here comes pre-computed from
// GET /api/dashboard (see app/services/analytics/dashboard.py) — this file only formats
// (rounding for display, "—" for null) and draws charts from numbers already computed
// server-side. It does not sum, average, or otherwise derive any statistic itself.

let charts = {};
let usersById = {};

document.addEventListener("DOMContentLoaded", async () => {
    await populateFilterOptions();
    document.getElementById("filter-form").addEventListener("submit", (e) => {
        e.preventDefault();
        loadDashboard();
    });
    document.getElementById("reset-filters-btn").addEventListener("click", () => {
        document.getElementById("filter-form").reset();
        loadDashboard();
    });
    await loadDashboard();
});

async function populateFilterOptions() {
    try {
        const [users, projects] = await Promise.all([
            apiRequest("/users?limit=500&active=true"),
            apiRequest("/projects?limit=500"),
        ]);
        usersById = Object.fromEntries(users.map((u) => [u.id, u]));

        const employeeSelect = document.getElementById("filter-employee");
        users.forEach((u) => {
            const opt = document.createElement("option");
            opt.value = String(u.id);
            opt.textContent = u.name;
            employeeSelect.appendChild(opt);
        });

        const departments = [...new Set(users.map((u) => u.department).filter(Boolean))].sort();
        const departmentSelect = document.getElementById("filter-department");
        departments.forEach((d) => {
            const opt = document.createElement("option");
            opt.value = d;
            opt.textContent = d;
            departmentSelect.appendChild(opt);
        });

        const projectSelect = document.getElementById("filter-project");
        projects.forEach((p) => {
            const opt = document.createElement("option");
            opt.value = String(p.id);
            opt.textContent = p.name;
            projectSelect.appendChild(opt);
        });
    } catch (err) {
        showAlert("dashboard-alert", "Could not load filter options: " + err.message);
    }
}

function buildQueryParams() {
    const params = new URLSearchParams();
    const dateFrom = document.getElementById("filter-date-from").value;
    const dateTo = document.getElementById("filter-date-to").value;
    const employee = document.getElementById("filter-employee").value;
    const department = document.getElementById("filter-department").value;
    const project = document.getElementById("filter-project").value;
    const statusValue = document.getElementById("filter-status").value;
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (employee) params.set("employee_id", employee);
    if (department) params.set("department", department);
    if (project) params.set("project_id", project);
    if (statusValue) params.set("status", statusValue);
    return params;
}

async function loadDashboard() {
    clearAlert("dashboard-alert");
    document.getElementById("dashboard-loading").classList.remove("d-none");
    document.getElementById("dashboard-content").classList.add("d-none");

    try {
        const params = buildQueryParams();
        const data = await apiRequest(`/dashboard?${params.toString()}`);

        renderSummary(data.summary);
        renderEfficiencyTrend(data.efficiency_trend);
        renderEmployeePerformance(data.employee_performance);
        renderWorkloadDistribution(data.workload_distribution);
        renderProjectProgress(data.project_progress);
        renderDelayedTasks(data.delayed_tasks);
        renderUpcomingDeadlines(data.upcoming_deadlines);

        document.getElementById("dashboard-content").classList.remove("d-none");
    } catch (err) {
        showAlert("dashboard-alert", err.message);
    } finally {
        document.getElementById("dashboard-loading").classList.add("d-none");
    }
}

// ---------------------------------------------------------------------------- formatting ----

function fmtNumber(value, digits = 1) {
    return value === null || value === undefined ? "—" : value.toFixed(digits);
}

function fmtPercent(value, digits = 1) {
    return value === null || value === undefined ? "—" : `${value.toFixed(digits)}%`;
}

function fmtDays(value, digits = 1) {
    return value === null || value === undefined ? "—" : `${value.toFixed(digits)}d`;
}

// -------------------------------------------------------------------------------- summary ----

function renderSummary(summary) {
    document.getElementById("kpi-team-efficiency").textContent = fmtNumber(summary.overall_team_efficiency);
    document.getElementById("kpi-tasks-completed").textContent = summary.tasks_completed;
    document.getElementById("kpi-tasks-overdue").textContent = summary.tasks_overdue;
    document.getElementById("kpi-tasks-at-risk").textContent = summary.tasks_at_risk;
    document.getElementById("kpi-avg-completion").textContent = fmtDays(summary.average_completion_days);
    document.getElementById("kpi-on-time-rate").textContent = fmtPercent(summary.on_time_completion_rate);
    document.getElementById("kpi-team-workload").textContent = fmtPercent(summary.team_workload.utilization_pct);
    document.getElementById("kpi-team-size").textContent = summary.team_size;
}

// ----------------------------------------------------------------------- efficiency trend ----

function renderEfficiencyTrend(trend) {
    const emptyState = document.getElementById("trend-empty-state");
    const canvas = document.getElementById("chart-efficiency-trend");
    emptyState.classList.toggle("d-none", trend.length > 0);
    canvas.classList.toggle("d-none", trend.length === 0);
    if (trend.length === 0) return;

    if (charts.trend) charts.trend.destroy();
    charts.trend = new Chart(canvas, {
        type: "line",
        data: {
            labels: trend.map((p) => p.date),
            datasets: [
                {
                    label: "Completion ratio (%)",
                    data: trend.map((p) => p.avg_completion_ratio),
                    borderColor: "#0d6efd",
                    backgroundColor: "rgba(13, 110, 253, 0.15)",
                    spanGaps: true,
                    tension: 0.2,
                    fill: true,
                },
            ],
        },
        options: {
            responsive: true,
            scales: { y: { beginAtZero: true, suggestedMax: 100 } },
            plugins: { legend: { display: false } },
        },
    });
}

// ----------------------------------------------------------------------- employee performance

function renderEmployeePerformance(rows) {
    const tbody = document.getElementById("employee-performance-tbody");
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted">No employees in scope.</td></tr>';
        return;
    }
    tbody.innerHTML = rows
        .map((row) => {
            const c = row.score.components;
            return `
        <tr>
            <td>${escapeHtml(row.name)}</td>
            <td><strong>${fmtNumber(row.score.overall_score)}</strong></td>
            <td>${fmtNumber(c.completion.value)}</td>
            <td>${fmtNumber(c.on_time.value)}</td>
            <td>${fmtNumber(c.quality.value)}</td>
            <td>${fmtNumber(c.time_efficiency.value)}</td>
            <td>${fmtNumber(c.deadline_adherence.value)}</td>
            <td>${fmtNumber(c.project_progress.value)}</td>
            <td>${fmtNumber(c.workload.value)}</td>
        </tr>`;
        })
        .join("");
}

// ------------------------------------------------------------------- workload distribution --

function renderWorkloadDistribution(rows) {
    const tbody = document.getElementById("workload-tbody");
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No employees in scope.</td></tr>';
    } else {
        tbody.innerHTML = rows
            .map(
                (row) => `
        <tr>
            <td>${escapeHtml(row.name)}</td>
            <td>${fmtNumber(row.workload.active_hours)}</td>
            <td>${fmtPercent(row.workload.utilization_pct)}</td>
            <td>${row.workload.active_task_count}</td>
        </tr>`
            )
            .join("");
    }

    const canvas = document.getElementById("chart-workload");
    if (charts.workload) charts.workload.destroy();
    if (rows.length === 0) return;
    charts.workload = new Chart(canvas, {
        type: "bar",
        data: {
            labels: rows.map((r) => r.name),
            datasets: [
                {
                    label: "Utilization (%)",
                    data: rows.map((r) => r.workload.utilization_pct),
                    backgroundColor: rows.map((r) => (r.workload.utilization_pct > 100 ? "#dc3545" : "#0d6efd")),
                },
            ],
        },
        options: {
            responsive: true,
            scales: { y: { beginAtZero: true } },
            plugins: { legend: { display: false } },
        },
    });
}

// ----------------------------------------------------------------------- project progress ----

function renderProjectProgress(rows) {
    const tbody = document.getElementById("project-progress-tbody");
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No projects in scope.</td></tr>';
    } else {
        tbody.innerHTML = rows
            .map(
                (row) => `
        <tr>
            <td>${escapeHtml(row.name)}</td>
            <td>${fmtPercent(row.progress.progress_pct)}</td>
            <td>${row.progress.completed_tasks}</td>
            <td>${row.progress.total_tasks}</td>
        </tr>`
            )
            .join("");
    }

    const canvas = document.getElementById("chart-project-progress");
    if (charts.projectProgress) charts.projectProgress.destroy();
    if (rows.length === 0) return;
    charts.projectProgress = new Chart(canvas, {
        type: "bar",
        data: {
            labels: rows.map((r) => r.name),
            datasets: [
                {
                    label: "Progress (%)",
                    data: rows.map((r) => r.progress.progress_pct),
                    backgroundColor: "#198754",
                },
            ],
        },
        options: {
            indexAxis: "y",
            responsive: true,
            scales: { x: { beginAtZero: true, max: 100 } },
            plugins: { legend: { display: false } },
        },
    });
}

// --------------------------------------------------------------------------- delayed tasks ---

function renderDelayedTasks(rows) {
    const tbody = document.getElementById("delayed-tasks-tbody");
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No delayed tasks. 🎉</td></tr>';
        return;
    }
    tbody.innerHTML = rows
        .map(
            (row) => `
        <tr>
            <td><a href="/tasks/${row.task_id}">${escapeHtml(row.title)}</a></td>
            <td>${row.assignee_name ? escapeHtml(row.assignee_name) : "Unassigned"}</td>
            <td>${row.deadline ? escapeHtml(row.deadline) : "—"}</td>
            <td><span class="badge bg-danger">${row.delay_days ?? "—"} day(s)</span></td>
        </tr>`
        )
        .join("");
}

// ----------------------------------------------------------------------- upcoming deadlines --

function renderUpcomingDeadlines(rows) {
    const tbody = document.getElementById("upcoming-deadlines-tbody");
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No upcoming deadlines in scope.</td></tr>';
        return;
    }
    tbody.innerHTML = rows
        .map(
            (row) => `
        <tr>
            <td><a href="/tasks/${row.task_id}">${escapeHtml(row.title)}</a> ${priorityBadge(row.priority)}</td>
            <td>${row.assignee_name ? escapeHtml(row.assignee_name) : "Unassigned"}</td>
            <td>${escapeHtml(row.deadline)}</td>
            <td><span class="badge bg-warning text-dark">${row.days_left} day(s)</span></td>
        </tr>`
        )
        .join("");
}
