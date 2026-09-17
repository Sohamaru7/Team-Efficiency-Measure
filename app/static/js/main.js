async function checkStatus(url, elementId, okLabel, errorLabel) {
    const el = document.getElementById(elementId);
    try {
        const response = await fetch(url);
        const data = await response.json();
        if (response.ok && data.status === "ok") {
            el.textContent = okLabel;
            el.className = "card-text text-success";
        } else {
            el.textContent = `${errorLabel}: ${data.detail || "unknown error"}`;
            el.className = "card-text text-danger";
        }
    } catch (err) {
        el.textContent = `${errorLabel}: ${err.message}`;
        el.className = "card-text text-danger";
    }
}

document.addEventListener("DOMContentLoaded", () => {
    checkStatus("/api/health", "app-status", "Application is running", "Application error");
    checkStatus("/api/health/db", "db-status", "Database connected", "Database error");
});
