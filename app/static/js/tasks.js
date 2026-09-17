let allTasks = [];
let projectMap = {};

document.addEventListener("DOMContentLoaded", async () => {
    const user = requireUserOrBanner("no-user-banner", "tasks-panel");
    if (!user) return;

    document.getElementById("filter-status").addEventListener("change", applyFilters);
    document.getElementById("filter-project").addEventListener("change", applyFilters);

    try {
        const [tasks, projects] = await Promise.all([
            apiRequest(`/tasks?assigned_to=${user.id}&limit=500`),
            apiRequest("/projects?limit=500"),
        ]);
        allTasks = tasks;
        projectMap = Object.fromEntries(projects.map((p) => [p.id, p.name]));
        populateProjectFilter(projects);
        renderTasks(allTasks);
    } catch (err) {
        showAlert("tasks-alert", err.message);
    }
});

function populateProjectFilter(projects) {
    const select = document.getElementById("filter-project");
    projects.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = String(p.id);
        opt.textContent = p.name;
        select.appendChild(opt);
    });
}

function applyFilters() {
    const status = document.getElementById("filter-status").value;
    const projectId = document.getElementById("filter-project").value;
    let filtered = allTasks;
    if (status) filtered = filtered.filter((t) => t.status === status);
    if (projectId) filtered = filtered.filter((t) => String(t.project_id) === projectId);
    renderTasks(filtered);
}

function renderTasks(tasks) {
    const tbody = document.getElementById("tasks-tbody");
    if (tasks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No tasks found.</td></tr>';
        return;
    }
    tbody.innerHTML = tasks
        .map(
            (t) => `
        <tr>
            <td><a href="/tasks/${t.id}">${escapeHtml(t.title)}</a></td>
            <td>${escapeHtml(projectMap[t.project_id] || "Project #" + t.project_id)}</td>
            <td>${priorityBadge(t.priority)}</td>
            <td>${statusBadge(t.status)}</td>
            <td>${t.deadline ? escapeHtml(t.deadline) : "—"}</td>
            <td class="text-end">
                <a href="/tasks/${t.id}" class="btn btn-sm btn-outline-secondary">View</a>
                <a href="/tasks/${t.id}/edit" class="btn btn-sm btn-outline-primary">Edit</a>
            </td>
        </tr>`
        )
        .join("");
}
