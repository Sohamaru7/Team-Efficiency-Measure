document.addEventListener("DOMContentLoaded", async () => {
    const user = requireUserOrBanner("no-user-banner", "task-summary-section");
    if (!user) return;

    try {
        const tasks = await apiRequest(`/tasks?assigned_to=${user.id}&limit=500`);
        renderSummary(tasks);
        renderUpcomingDeadlines(tasks);
    } catch (err) {
        showAlert("dashboard-alert", err.message);
    }
});

function renderSummary(tasks) {
    const counts = { not_started: 0, in_progress: 0, blocked: 0, completed: 0, cancelled: 0 };
    tasks.forEach((t) => {
        counts[t.status] = (counts[t.status] || 0) + 1;
    });
    document.getElementById("count-not-started").textContent = counts.not_started;
    document.getElementById("count-in-progress").textContent = counts.in_progress;
    document.getElementById("count-blocked").textContent = counts.blocked;
    document.getElementById("count-completed").textContent = counts.completed;
}

function renderUpcomingDeadlines(tasks) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const soon = new Date(today);
    soon.setDate(soon.getDate() + 7);

    const upcoming = tasks
        .filter((t) => t.deadline && !["completed", "cancelled"].includes(t.status))
        .filter((t) => {
            const d = new Date(t.deadline);
            return d >= today && d <= soon;
        })
        .sort((a, b) => a.deadline.localeCompare(b.deadline));

    const list = document.getElementById("upcoming-deadlines");
    if (upcoming.length === 0) {
        list.innerHTML = '<li class="list-group-item text-muted">No upcoming deadlines in the next 7 days.</li>';
        return;
    }
    list.innerHTML = upcoming
        .map(
            (t) => `
        <li class="list-group-item d-flex justify-content-between align-items-center">
            <a href="/tasks/${t.id}">${escapeHtml(t.title)}</a>
            <span class="badge bg-warning text-dark">${escapeHtml(t.deadline)}</span>
        </li>`
        )
        .join("");
}
