// Manager AI Assistant page. Sends the manager's question to POST /api/ai/ask and renders the
// answer plus the supporting tool-call evidence the backend returns. This file does not compute
// any metric itself — it only formats what the backend (which enforces the read-only tool-use
// loop) already produced.

const SUGGESTED_QUESTIONS = [
    "Why did team efficiency decrease?",
    "Who is overloaded?",
    "Which deadlines are at risk?",
    "What caused recent delays?",
    "Which projects are falling behind?",
    "Who has unusually high or low workload?",
    "What should I prioritize?",
];

document.addEventListener("DOMContentLoaded", () => {
    renderSuggestedQuestions();
    document.getElementById("ask-form").addEventListener("submit", onSubmit);
    document.getElementById("refresh-actions-btn").addEventListener("click", loadActions);
    loadActions();
});

function renderSuggestedQuestions() {
    const container = document.getElementById("suggested-questions");
    container.innerHTML = SUGGESTED_QUESTIONS.map(
        (q) => `<button type="button" class="btn btn-outline-secondary btn-sm suggested-question">${escapeHtml(q)}</button>`
    ).join("");
    container.querySelectorAll(".suggested-question").forEach((btn) => {
        btn.addEventListener("click", () => {
            const input = document.getElementById("question-input");
            input.value = btn.textContent;
            input.focus();
        });
    });
}

async function onSubmit(event) {
    event.preventDefault();
    clearAlert("assistant-alert");

    const input = document.getElementById("question-input");
    const question = input.value.trim();
    if (!question) return;

    const button = document.getElementById("ask-button");
    button.disabled = true;
    button.textContent = "Thinking…";

    const pendingId = addPendingEntry(question);

    try {
        const data = await apiRequest("/ai/ask", { method: "POST", body: { question } });
        resolvePendingEntry(pendingId, data);
        input.value = "";
        loadActions();
    } catch (err) {
        removePendingEntry(pendingId);
        showAlert("assistant-alert", err.message);
    } finally {
        button.disabled = false;
        button.textContent = "Ask";
    }
}

let entryCounter = 0;

function addPendingEntry(question) {
    const id = `entry-${++entryCounter}`;
    const container = document.getElementById("conversation");
    const card = document.createElement("div");
    card.className = "card mb-3";
    card.id = id;
    card.innerHTML = `
        <div class="card-body">
            <p class="fw-semibold mb-2">${escapeHtml(question)}</p>
            <p class="text-muted mb-0"><span class="spinner-border spinner-border-sm me-2"></span>Thinking…</p>
        </div>`;
    container.prepend(card);
    return id;
}

function removePendingEntry(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function resolvePendingEntry(id, data) {
    const card = document.getElementById(id);
    if (!card) return;
    const question = card.querySelector("p.fw-semibold").textContent;

    const toolCallsHtml =
        data.tool_calls.length === 0
            ? ""
            : `
        <details class="mt-3">
            <summary class="text-muted small" style="cursor: pointer;">
                Supporting metrics (${data.tool_calls.length} tool call${data.tool_calls.length === 1 ? "" : "s"})
            </summary>
            <div class="mt-2 d-flex flex-column gap-2">
                ${data.tool_calls.map(renderToolCall).join("")}
            </div>
        </details>`;

    card.querySelector(".card-body").innerHTML = `
        <p class="fw-semibold mb-2">${escapeHtml(question)}</p>
        <p class="mb-0" style="white-space: pre-wrap;">${escapeHtml(data.answer)}</p>
        ${toolCallsHtml}
    `;
}

function renderToolCall(call) {
    const argsText = Object.keys(call.input).length ? JSON.stringify(call.input) : "(no arguments)";
    return `
        <div class="border rounded p-2 bg-light">
            <div class="small"><code>${escapeHtml(call.name)}</code> <span class="text-muted">${escapeHtml(argsText)}</span></div>
            <pre class="small mb-0 mt-1" style="white-space: pre-wrap;">${escapeHtml(JSON.stringify(call.result, null, 2))}</pre>
        </div>`;
}

// ---------------------------------------------------------------- agent actions / approvals ----

const ACTION_STATUS_LABELS = {
    pending: "Pending approval",
    auto_approved: "Auto-executed",
    approved: "Approved",
    rejected: "Rejected",
    failed: "Failed",
};
const ACTION_STATUS_CLASSES = {
    pending: "bg-warning text-dark",
    auto_approved: "bg-info text-dark",
    approved: "bg-success",
    rejected: "bg-secondary",
    failed: "bg-danger",
};

async function loadActions() {
    try {
        const all = await apiRequest("/ai/actions?limit=100");
        const pending = all.filter((a) => a.status === "pending");
        const others = all.filter((a) => a.status !== "pending");
        renderPendingActions(pending);
        renderActionLog(others);
    } catch (err) {
        showAlert("assistant-alert", err.message);
    }
}

function renderPendingActions(actions) {
    const container = document.getElementById("pending-actions");
    if (actions.length === 0) {
        container.innerHTML = '<p class="text-muted small mb-0">No actions are waiting on approval.</p>';
        return;
    }
    container.innerHTML = actions.map(renderPendingActionCard).join("");
    container.querySelectorAll("[data-decide]").forEach((btn) => {
        btn.addEventListener("click", () => decideAction(btn.dataset.actionId, btn.dataset.decide === "approve"));
    });
}

function renderPendingActionCard(action) {
    return `
        <div class="border rounded p-2 mb-2" id="pending-action-${action.id}">
            <div class="d-flex justify-content-between align-items-start">
                <div>
                    <div><code>${escapeHtml(action.action)}</code> <span class="text-muted small">${escapeHtml(action.target || "")}</span></div>
                    <div class="small text-muted">${escapeHtml(action.reason || "")}</div>
                </div>
                <div class="d-flex gap-2">
                    <button type="button" class="btn btn-sm btn-success" data-decide="approve" data-action-id="${action.id}">Approve</button>
                    <button type="button" class="btn btn-sm btn-outline-danger" data-decide="reject" data-action-id="${action.id}">Reject</button>
                </div>
            </div>
        </div>`;
}

async function decideAction(actionId, approve) {
    const card = document.getElementById(`pending-action-${actionId}`);
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
        await apiRequest(`/ai/actions/${actionId}/${approve ? "approve" : "reject"}`, { method: "POST" });
        loadActions();
    } catch (err) {
        showAlert("assistant-alert", err.message);
        card.querySelectorAll("button").forEach((b) => (b.disabled = false));
    }
}

function renderActionLog(actions) {
    const container = document.getElementById("action-log");
    if (actions.length === 0) {
        container.innerHTML = '<p class="text-muted small mb-0">No agent activity yet.</p>';
        return;
    }
    container.innerHTML = `
        <div class="table-responsive">
            <table class="table table-sm align-middle mb-0">
                <thead><tr><th>When</th><th>Action</th><th>Target</th><th>Reason</th><th>Status</th><th>Result</th></tr></thead>
                <tbody>
                    ${actions.map(renderActionLogRow).join("")}
                </tbody>
            </table>
        </div>`;
}

function renderActionLogRow(action) {
    const cls = ACTION_STATUS_CLASSES[action.status] || "bg-secondary";
    const label = ACTION_STATUS_LABELS[action.status] || action.status;
    return `
        <tr>
            <td class="small text-nowrap">${escapeHtml(new Date(action.timestamp).toLocaleString())}</td>
            <td><code>${escapeHtml(action.action)}</code></td>
            <td class="small">${escapeHtml(action.target || "")}</td>
            <td class="small">${escapeHtml(action.reason || "")}</td>
            <td><span class="badge ${cls}">${escapeHtml(label)}</span></td>
            <td class="small">${escapeHtml(action.result || "")}</td>
        </tr>`;
}
