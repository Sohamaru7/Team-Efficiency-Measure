let existingUpdates = [];
let editingId = null;

document.addEventListener("DOMContentLoaded", async () => {
    const user = requireUserOrBanner("no-user-banner", "daily-update-panel");
    if (!user) return;

    const dateField = document.getElementById("field-date");
    dateField.value = todayIso();
    dateField.addEventListener("change", () => syncFormWithDate(dateField.value));

    document.getElementById("daily-update-form").addEventListener("submit", (e) => onSubmit(e, user));

    await loadHistory(user);
    syncFormWithDate(dateField.value);
});

function todayIso() {
    const d = new Date();
    const offset = d.getTimezoneOffset();
    const local = new Date(d.getTime() - offset * 60 * 1000);
    return local.toISOString().slice(0, 10);
}

async function loadHistory(user) {
    try {
        existingUpdates = await apiRequest(`/daily-updates?user_id=${user.id}&limit=100`);
        renderHistory();
    } catch (err) {
        showAlert("form-alert", err.message);
    }
}

function renderHistory() {
    const tbody = document.getElementById("history-tbody");
    if (existingUpdates.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No updates submitted yet.</td></tr>';
        return;
    }
    const sorted = [...existingUpdates].sort((a, b) => b.date.localeCompare(a.date));
    tbody.innerHTML = sorted
        .map(
            (u) => `
        <tr>
            <td>${escapeHtml(u.date)}</td>
            <td>${u.tasks_completed}</td>
            <td>${u.tasks_pending}</td>
            <td>${u.blockers ? escapeHtml(u.blockers) : "—"}</td>
            <td class="text-end"><button type="button" class="btn btn-sm btn-outline-secondary" data-edit-date="${escapeHtml(u.date)}">Edit</button></td>
        </tr>`
        )
        .join("");
    tbody.querySelectorAll("[data-edit-date]").forEach((btn) => {
        btn.addEventListener("click", () => editUpdate(btn.getAttribute("data-edit-date")));
    });
}

function editUpdate(dateStr) {
    document.getElementById("field-date").value = dateStr;
    syncFormWithDate(dateStr);
    window.scrollTo({ top: 0, behavior: "smooth" });
}

function syncFormWithDate(dateStr) {
    const existing = existingUpdates.find((u) => u.date === dateStr);
    const hint = document.getElementById("existing-update-hint");
    const submitBtn = document.getElementById("submit-btn");
    if (existing) {
        editingId = existing.id;
        document.getElementById("field-tasks-completed").value = existing.tasks_completed;
        document.getElementById("field-tasks-pending").value = existing.tasks_pending;
        document.getElementById("field-blockers").value = existing.blockers || "";
        document.getElementById("field-notes").value = existing.notes || "";
        submitBtn.textContent = "Update";
        hint.textContent = "An update for this date already exists — saving will update it.";
    } else {
        editingId = null;
        document.getElementById("field-tasks-completed").value = 0;
        document.getElementById("field-tasks-pending").value = 0;
        document.getElementById("field-blockers").value = "";
        document.getElementById("field-notes").value = "";
        submitBtn.textContent = "Submit Update";
        hint.textContent = "";
    }
}

async function onSubmit(event, user) {
    event.preventDefault();
    clearAlert("form-alert");

    const form = document.getElementById("daily-update-form");
    form.classList.add("was-validated");
    if (!form.checkValidity()) return;

    const strOrNull = (id) => {
        const v = document.getElementById(id).value.trim();
        return v === "" ? null : v;
    };
    const payload = {
        user_id: user.id,
        date: document.getElementById("field-date").value,
        tasks_completed: Number(document.getElementById("field-tasks-completed").value || 0),
        tasks_pending: Number(document.getElementById("field-tasks-pending").value || 0),
        blockers: strOrNull("field-blockers"),
        notes: strOrNull("field-notes"),
    };

    const submitBtn = document.getElementById("submit-btn");
    submitBtn.disabled = true;

    try {
        if (editingId) {
            const { user_id, date, ...updatable } = payload;
            await apiRequest(`/daily-updates/${editingId}`, { method: "PATCH", body: updatable });
        } else {
            await apiRequest("/daily-updates", { method: "POST", body: payload });
        }
        await loadHistory(user);
        syncFormWithDate(payload.date);
        showAlert("form-alert", "Daily update saved.", "success");
    } catch (err) {
        showAlert("form-alert", err.message);
    } finally {
        submitBtn.disabled = false;
    }
}
