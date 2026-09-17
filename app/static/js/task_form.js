function getEditTaskId() {
    const parts = window.location.pathname.split("/").filter(Boolean);
    if (parts[0] === "tasks" && parts.length === 3 && parts[2] === "edit" && /^\d+$/.test(parts[1])) {
        return Number(parts[1]);
    }
    return null;
}

document.addEventListener("DOMContentLoaded", async () => {
    const taskId = getEditTaskId();
    const isEdit = taskId !== null;

    if (isEdit) {
        document.getElementById("form-heading").textContent = "Edit Task";
        document.getElementById("form-breadcrumb").textContent = "Edit Task";
        document.title = "Edit Task - Team Efficiency Measure";
    }

    const user = requireUserOrBanner("no-user-banner", "task-form");
    if (!user) return;

    try {
        const projects = await apiRequest("/projects?limit=500");
        populateProjectSelect(projects);
    } catch (err) {
        showAlert("form-alert", "Could not load projects: " + err.message);
        return;
    }

    if (isEdit) {
        try {
            const task = await apiRequest(`/tasks/${taskId}`);
            fillForm(task);
        } catch (err) {
            showAlert("form-alert", "Could not load task: " + err.message);
            return;
        }
    }

    document.getElementById("field-deadline").addEventListener("input", validateDateRange);
    document.getElementById("field-start-date").addEventListener("input", validateDateRange);

    document.getElementById("task-form").addEventListener("submit", (e) => onSubmit(e, taskId, user));
});

function populateProjectSelect(projects) {
    const select = document.getElementById("field-project");
    projects.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = String(p.id);
        opt.textContent = p.name;
        select.appendChild(opt);
    });
}

function fillForm(task) {
    document.getElementById("field-project").value = String(task.project_id);
    document.getElementById("field-priority").value = task.priority;
    document.getElementById("field-title").value = task.title;
    document.getElementById("field-description").value = task.description || "";
    document.getElementById("field-status").value = task.status;
    document.getElementById("field-estimated-hours").value = task.estimated_hours ?? "";
    document.getElementById("field-actual-hours").value = task.actual_hours ?? "";
    document.getElementById("field-start-date").value = task.start_date || "";
    document.getElementById("field-deadline").value = task.deadline || "";
    document.getElementById("field-completed-date").value = task.completed_date || "";
    document.getElementById("field-quality-score").value = task.quality_score ?? "";
    document.getElementById("field-delay-reason").value = task.delay_reason || "";
}

function validateDateRange() {
    const start = document.getElementById("field-start-date").value;
    const deadline = document.getElementById("field-deadline").value;
    const deadlineField = document.getElementById("field-deadline");
    if (start && deadline && deadline < start) {
        deadlineField.setCustomValidity("Deadline must be on or after the start date.");
    } else {
        deadlineField.setCustomValidity("");
    }
}

function buildPayload(user, { includeChangedBy }) {
    const val = (id) => document.getElementById(id).value;
    const numOrNull = (id) => {
        const v = val(id);
        return v === "" ? null : Number(v);
    };
    const strOrNull = (id) => {
        const v = val(id).trim();
        return v === "" ? null : v;
    };

    const payload = {
        project_id: Number(val("field-project")),
        assigned_to: user.id,
        title: val("field-title").trim(),
        description: strOrNull("field-description"),
        priority: val("field-priority"),
        status: val("field-status"),
        estimated_hours: numOrNull("field-estimated-hours"),
        actual_hours: numOrNull("field-actual-hours"),
        start_date: strOrNull("field-start-date"),
        deadline: strOrNull("field-deadline"),
        completed_date: strOrNull("field-completed-date"),
        quality_score: numOrNull("field-quality-score"),
        delay_reason: strOrNull("field-delay-reason"),
    };
    if (includeChangedBy) {
        payload.changed_by = user.id;
    }
    return payload;
}

async function onSubmit(event, taskId, user) {
    event.preventDefault();
    clearAlert("form-alert");
    validateDateRange();

    const form = document.getElementById("task-form");
    form.classList.add("was-validated");
    if (!form.checkValidity()) {
        return;
    }

    const payload = buildPayload(user, { includeChangedBy: Boolean(taskId) });
    const submitBtn = document.getElementById("submit-btn");
    submitBtn.disabled = true;
    submitBtn.textContent = "Saving…";

    try {
        let saved;
        if (taskId) {
            saved = await apiRequest(`/tasks/${taskId}`, { method: "PATCH", body: payload });
        } else {
            saved = await apiRequest("/tasks", { method: "POST", body: payload });
        }
        window.location.href = `/tasks/${saved.id}`;
    } catch (err) {
        showAlert("form-alert", err.message);
        submitBtn.disabled = false;
        submitBtn.textContent = "Save Task";
    }
}
