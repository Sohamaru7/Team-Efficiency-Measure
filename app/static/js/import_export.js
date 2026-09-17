// Data Import/Export page. Preview and Commit both upload the same file via multipart/form-data
// (not JSON, so this bypasses the shared apiRequest() helper) to POST /api/import/preview and
// POST /api/import/commit — the backend runs the identical parse/map/validate/dedupe pipeline
// for both, so what Preview shows is exactly what Commit will do. Export buttons are plain links
// (the backend returns a real file download), no JS involved there.

let selectedFile = null;

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("import-file-input").addEventListener("change", onFileChosen);
    document.getElementById("preview-btn").addEventListener("click", onPreview);
    document.getElementById("commit-btn").addEventListener("click", onCommit);
    document.getElementById("refresh-history-btn").addEventListener("click", loadHistory);
    document.querySelectorAll("[data-export]").forEach((btn) => {
        btn.addEventListener("click", () => downloadExport(btn.dataset.export, btn.dataset.filename, btn));
    });
    loadHistory();
});

// Export links must carry the Authorization header now that these endpoints require
// manager/admin auth — a plain <a href> can't attach a custom header to a browser navigation,
// so this fetches the file (with the header apiRequest() would use), then hands the browser a
// blob URL to save exactly as if it had followed a normal download link.
async function downloadExport(path, filename, button) {
    clearAlert("import-alert");
    button.disabled = true;
    try {
        const token = getAccessToken();
        const response = await fetch(`${API_BASE}${path}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (response.status === 401) {
            clearCurrentUser();
            window.location.href = "/login";
            return;
        }
        if (!response.ok) {
            const data = await response.json().catch(() => null);
            throw new ApiError(data && data.detail ? formatErrorDetail(data.detail) : "Export failed", response.status, data);
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    } catch (err) {
        showAlert("import-alert", err.message);
    } finally {
        button.disabled = false;
    }
}

function onFileChosen(event) {
    selectedFile = event.target.files[0] || null;
    document.getElementById("commit-btn").disabled = true;
    document.getElementById("preview-section").classList.add("d-none");
    clearAlert("import-alert");
}

async function uploadFile(path, file, extraFields) {
    const formData = new FormData();
    formData.append("file", file);
    if (extraFields) {
        for (const [key, value] of Object.entries(extraFields)) {
            if (value !== null && value !== undefined) formData.append(key, value);
        }
    }
    const token = getAccessToken();
    const response = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
    });
    const data = await response.json();
    if (response.status === 401) {
        clearCurrentUser();
        window.location.href = "/login";
    }
    if (!response.ok) {
        throw new ApiError(data && data.detail ? formatErrorDetail(data.detail) : "Upload failed", response.status, data);
    }
    return data;
}

async function onPreview() {
    if (!selectedFile) {
        showAlert("import-alert", "Choose a file first.");
        return;
    }
    clearAlert("import-alert");
    const button = document.getElementById("preview-btn");
    button.disabled = true;
    button.textContent = "Previewing…";
    try {
        const result = await uploadFile("/import/preview", selectedFile);
        renderPreview(result);
        document.getElementById("commit-btn").disabled = !!result.file_error || result.rows_accepted === 0;
    } catch (err) {
        showAlert("import-alert", err.message);
    } finally {
        button.disabled = false;
        button.textContent = "Preview";
    }
}

async function onCommit() {
    if (!selectedFile) return;
    clearAlert("import-alert");
    const button = document.getElementById("commit-btn");
    button.disabled = true;
    button.textContent = "Importing…";
    try {
        // The server attributes the import to the logged-in session's own token -- no
        // client-supplied id is sent or trusted.
        const result = await uploadFile("/import/commit", selectedFile);
        renderPreview(result);
        showAlert(
            "import-alert",
            `Imported ${result.rows_accepted} of ${result.rows_processed} row(s). ${result.rows_rejected} rejected.`,
            "success"
        );
        loadHistory();
    } catch (err) {
        showAlert("import-alert", err.message);
    } finally {
        button.textContent = "Commit Import";
        button.disabled = true; // require a fresh Preview before committing again
    }
}

const ROW_STATUS_CLASSES = { accepted: "table-success", rejected: "table-danger", duplicate: "table-warning" };

function renderPreview(result) {
    const section = document.getElementById("preview-section");
    section.classList.remove("d-none");

    const summary = document.getElementById("preview-summary");
    if (result.file_error) {
        summary.innerHTML = `<div class="alert alert-danger mb-0">${escapeHtml(result.file_error)}</div>`;
        document.getElementById("preview-mapping").innerHTML = "";
        document.getElementById("preview-rows").innerHTML = "";
        return;
    }

    summary.innerHTML = `
        <span class="badge bg-secondary me-2">${result.rows_processed} processed</span>
        <span class="badge bg-success me-2">${result.rows_accepted} accepted</span>
        <span class="badge bg-danger me-2">${result.rows_rejected} rejected</span>
        <span class="badge bg-warning text-dark">${result.rows_duplicate} duplicate</span>
    `;

    const mappedEntries = Object.entries(result.column_mapping).filter(([, header]) => header);
    document.getElementById("preview-mapping").innerHTML =
        "Mapped columns: " + mappedEntries.map(([field, header]) => `<code>${escapeHtml(header)}</code> → ${escapeHtml(field)}`).join(", ");

    document.getElementById("preview-rows").innerHTML = result.rows
        .map(
            (row) => `
        <tr class="${ROW_STATUS_CLASSES[row.status] || ""}">
            <td>${row.row_number}</td>
            <td>${escapeHtml(row.status)}</td>
            <td>${escapeHtml(row.employee || "")}</td>
            <td>${escapeHtml(row.task || "")}</td>
            <td>${escapeHtml(row.project || "")}</td>
            <td class="small">${row.errors.map(escapeHtml).join("; ")}</td>
        </tr>`
        )
        .join("");
}

async function loadHistory() {
    try {
        const history = await apiRequest("/import/history?limit=20");
        const tbody = document.getElementById("history-rows");
        if (history.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-muted small">No imports yet.</td></tr>';
            return;
        }
        tbody.innerHTML = history
            .map(
                (h) => `
            <tr>
                <td class="small text-nowrap">${escapeHtml(new Date(h.timestamp).toLocaleString())}</td>
                <td class="small">${escapeHtml(h.filename)}</td>
                <td>${h.rows_processed}</td>
                <td class="text-success">${h.rows_accepted}</td>
                <td class="text-danger">${h.rows_rejected}</td>
            </tr>`
            )
            .join("");
    } catch (err) {
        showAlert("import-alert", err.message);
    }
}
