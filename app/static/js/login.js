// Login page. Posts to POST /api/auth/login and, on success, stores the access token + user
// (via setSession, in app/static/js/common.js) and redirects to the dashboard. This replaces
// the old Phase 3-6 client-side "employee switcher" — the server now verifies a real password
// rather than trusting whichever identity a visitor happened to click.
//
// Demo mode (scripts/run_demo.py, off by default): if GET /api/auth/demo-mode reports
// {enabled: true}, this page also shows one-click "Enter Demo" buttons that call
// POST /api/auth/demo-login (no password) instead of the form. RBAC is not disabled by this —
// the Admin persona simply has nothing to be blocked from, by the exact same rule that applies
// to any real admin account.

document.addEventListener("DOMContentLoaded", async () => {
    // If already logged in, there's nothing to do here.
    if (getCurrentUser() && getAccessToken()) {
        window.location.href = "/";
        return;
    }
    document.getElementById("login-form").addEventListener("submit", onSubmit);
    await initDemoMode();
});

async function initDemoMode() {
    try {
        const status = await apiRequest("/auth/demo-mode");
        if (!status.enabled) return;
        document.getElementById("demo-mode-section").classList.remove("d-none");
        document.querySelectorAll("[data-demo-role]").forEach((btn) => {
            btn.addEventListener("click", () => onDemoLogin(btn.dataset.demoRole, btn));
        });
    } catch {
        // Demo mode is an optional convenience -- if the check fails, just show the normal form.
    }
}

async function onDemoLogin(role, button) {
    clearAlert("login-alert");
    const buttons = document.querySelectorAll("[data-demo-role]");
    buttons.forEach((b) => (b.disabled = true));
    const originalText = button.textContent;
    button.textContent = "Entering…";
    try {
        const result = await apiRequest("/auth/demo-login", { method: "POST", body: { role } });
        setSession(result.access_token, result.user);
        window.location.href = "/";
    } catch (err) {
        showAlert("login-alert", err.message);
        buttons.forEach((b) => (b.disabled = false));
        button.textContent = originalText;
    }
}

async function onSubmit(event) {
    event.preventDefault();
    clearAlert("login-alert");

    const email = document.getElementById("email-input").value.trim();
    const password = document.getElementById("password-input").value;
    const button = document.getElementById("login-btn");
    button.disabled = true;
    button.textContent = "Logging in…";

    try {
        const result = await apiRequest("/auth/login", { method: "POST", body: { email, password } });
        setSession(result.access_token, result.user);
        window.location.href = "/";
    } catch (err) {
        showAlert("login-alert", err.message);
    } finally {
        button.disabled = false;
        button.textContent = "Log In";
    }
}
