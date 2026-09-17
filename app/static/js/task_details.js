function getTaskIdFromPath() {
    const parts = window.location.pathname.split("/").filter(Boolean);
    const idx = parts.indexOf("tasks");
    const id = idx >= 0 ? parts[idx + 1] : null;
    return id && /^\d+$/.test(id) ? Number(id) : null;
}

document.addEventListener("DOMContentLoaded", async () => {
    const taskId = getTaskIdFromPath();
    if (!taskId) {
        showAlert("task-details-alert", "Invalid task id.");
        return;
    }
    document.getElementById("edit-link").href = `/tasks/${taskId}/edit`;
    document.getElementById("delete-btn").addEventListener("click", () => deleteTask(taskId));

    try {
        const [task, projects] = await Promise.all([apiRequest(`/tasks/${taskId}`), apiRequest("/projects?limit=500")]);
        const project = projects.find((p) => p.id === task.project_id);
        renderTask(task, project);
        loadEmails(taskId);
        loadDelayClassification(taskId);
    } catch (err) {
        if (err.status === 404) {
            showAlert("task-details-alert", "Task not found.");
        } else {
            showAlert("task-details-alert", err.message);
        }
    }
});

function renderTask(task, project) {
    document.getElementById("task-details-panel").classList.remove("d-none");
    document.getElementById("task-title").textContent = task.title;
    document.getElementById("task-badges").innerHTML = `${statusBadge(task.status)} ${priorityBadge(task.priority)}`;
    document.getElementById("task-description").textContent = task.description || "No description provided.";
    document.getElementById("task-project").textContent = project ? project.name : `Project #${task.project_id}`;
    document.getElementById("task-estimated-hours").textContent = task.estimated_hours ?? "—";
    document.getElementById("task-actual-hours").textContent = task.actual_hours ?? "—";
    document.getElementById("task-start-date").textContent = task.start_date || "—";
    document.getElementById("task-deadline").textContent = task.deadline || "—";
    document.getElementById("task-completed-date").textContent = task.completed_date || "—";
    document.getElementById("task-quality-score").textContent = task.quality_score ?? "—";
    document.getElementById("task-delay-reason").textContent = task.delay_reason || "—";
}

// ---------------------------------------------------------------------- Phase 9: emails ----

const DIRECTION_LABELS = { inbound: "Inbound", outbound: "Outbound" };

async function loadEmails(taskId) {
    const container = document.getElementById("email-list");
    try {
        const emails = await apiRequest(`/emails?task_id=${taskId}`);
        if (emails.length === 0) {
            container.innerHTML = '<p class="text-muted small mb-0">No emails linked to this task.</p>';
            return;
        }
        container.innerHTML = `
            <div class="list-group">
                ${emails.map((e) => renderEmailSummaryRow(e)).join("")}
            </div>`;
        container.querySelectorAll("[data-email-id]").forEach((row) => {
            row.addEventListener("click", () => toggleEmailDetail(row, Number(row.dataset.emailId)));
        });
    } catch (err) {
        container.innerHTML = "";
        showAlert("task-details-alert", err.message);
    }
}

function renderEmailSummaryRow(email) {
    const externalBadge = email.is_external ? '<span class="badge bg-warning text-dark">External</span>' : '<span class="badge bg-light text-dark">Internal</span>';
    return `
        <div class="list-group-item" style="cursor: pointer;" data-email-id="${email.id}">
            <div class="d-flex justify-content-between align-items-center">
                <span class="small">${DIRECTION_LABELS[email.direction] || email.direction} ${externalBadge}</span>
                <span class="small text-muted">${escapeHtml(new Date(email.sent_at).toLocaleString())}</span>
            </div>
            <div class="small text-muted mt-1" data-email-detail>Click to view details (requires permission)…</div>
        </div>`;
}

async function toggleEmailDetail(row, emailId) {
    const detailEl = row.querySelector("[data-email-detail]");
    if (row.dataset.expanded === "true") {
        row.dataset.expanded = "false";
        detailEl.textContent = "Click to view details (requires permission)…";
        return;
    }
    try {
        // The server derives "who's asking" from the logged-in session's own token — no
        // client-supplied id is sent or trusted.
        const email = await apiRequest(`/emails/${emailId}`);
        row.dataset.expanded = "true";
        detailEl.innerHTML = `
            <strong>${escapeHtml(email.subject || "(no subject)")}</strong><br>
            From: ${escapeHtml(email.from_address)} — To: ${escapeHtml(email.to_addresses)}<br>
            ${email.body_text ? `<pre class="small mt-1 mb-0" style="white-space: pre-wrap;">${escapeHtml(email.body_text)}</pre>` : '<span class="fst-italic">No body recorded.</span>'}
        `;
    } catch (err) {
        detailEl.textContent = err.status === 403 ? "You do not have permission to view this email's content." : err.message;
    }
}

async function loadDelayClassification(taskId) {
    const container = document.getElementById("email-delay-classification");
    try {
        const result = await apiRequest(`/emails/tasks/${taskId}/delay-classification`);
        if (!result.is_delayed) {
            container.innerHTML = "";
            return;
        }
        if (result.delay_type) {
            container.innerHTML = `
                <div class="alert alert-info mb-0">
                    <strong>Delay type:</strong> ${escapeHtml(result.delay_type)} &mdash;
                    <strong>Cause:</strong> ${escapeHtml(result.cause)}
                    ${result.duration_days !== null ? ` &mdash; <strong>Duration:</strong> ${result.duration_days} day(s)` : ""}
                    <div class="small mt-1">${escapeHtml(result.note)}</div>
                </div>`;
        } else {
            container.innerHTML = `<p class="text-muted small mb-0">${escapeHtml(result.note)}</p>`;
        }
    } catch (err) {
        container.innerHTML = err.status === 403
            ? '<p class="text-muted small mb-0">You do not have permission to view this task\'s email-derived delay classification.</p>'
            : "";
    }
}

async function deleteTask(taskId) {
    if (!confirm("Delete this task? This cannot be undone.")) return;
    try {
        await apiRequest(`/tasks/${taskId}`, { method: "DELETE" });
        window.location.href = "/tasks";
    } catch (err) {
        showAlert("task-details-alert", err.message);
    }
}
