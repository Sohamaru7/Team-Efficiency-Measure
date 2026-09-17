document.addEventListener("DOMContentLoaded", async () => {
    const user = requireUserOrBanner("no-user-banner", "performance-panel");
    if (!user) return;

    try {
        const scores = await apiRequest(`/performance-scores?user_id=${user.id}&limit=100`);
        renderScores(scores);
    } catch (err) {
        showAlert("perf-alert", err.message);
    }
});

function renderScores(scores) {
    const tbody = document.getElementById("performance-tbody");
    if (scores.length === 0) {
        tbody.innerHTML =
            '<tr><td colspan="7" class="text-center text-muted">No performance data yet. Scores are calculated in a later phase.</td></tr>';
        return;
    }
    const sorted = [...scores].sort((a, b) => a.period.localeCompare(b.period));
    tbody.innerHTML = sorted
        .map(
            (s) => `
        <tr>
            <td>${escapeHtml(s.period)}</td>
            <td>${scoreOrDash(s.completion_score)}</td>
            <td>${scoreOrDash(s.timeliness_score)}</td>
            <td>${scoreOrDash(s.quality_score)}</td>
            <td>${scoreOrDash(s.time_efficiency_score)}</td>
            <td>${scoreOrDash(s.workload_score)}</td>
            <td><strong>${scoreOrDash(s.overall_score)}</strong></td>
        </tr>`
        )
        .join("");
}

function scoreOrDash(value) {
    return value === null || value === undefined ? "—" : escapeHtml(String(value));
}
