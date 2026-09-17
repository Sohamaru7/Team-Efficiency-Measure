const API_BASE = "/api";
// Same localStorage key names Phase 3 introduced for the old client-side "employee switcher" —
// kept unchanged (production-readiness pass) so every page's existing `getCurrentUser()` calls
// keep working: it now returns the REAL logged-in user (from /api/auth/login), not a freely
// picked one, but the shape ({id, name, department, role}) and the function name are the same.
const CURRENT_USER_KEY = "team_efficiency_current_user";
const ACCESS_TOKEN_KEY = "team_efficiency_access_token";

class ApiError extends Error {
    constructor(message, status, data) {
        super(message);
        this.status = status;
        this.data = data;
    }
}

function formatErrorDetail(detail) {
    if (Array.isArray(detail)) {
        return detail
            .map((d) => {
                const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : "field";
                return `${field}: ${d.msg}`;
            })
            .join("; ");
    }
    if (detail) return String(detail);
    return "Something went wrong.";
}

function getAccessToken() {
    return localStorage.getItem(ACCESS_TOKEN_KEY);
}

async function apiRequest(path, options = {}) {
    const token = getAccessToken();
    const opts = {
        headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            ...(options.headers || {}),
        },
        ...options,
    };
    if (opts.body && typeof opts.body !== "string") {
        opts.body = JSON.stringify(opts.body);
    }

    let response;
    try {
        response = await fetch(`${API_BASE}${path}`, opts);
    } catch (err) {
        throw new ApiError("Network error: could not reach the server. Is the API running?", 0, null);
    }

    let data = null;
    const text = await response.text();
    if (text) {
        try {
            data = JSON.parse(text);
        } catch {
            data = null;
        }
    }

    if (response.status === 401 && path !== "/auth/login") {
        // The token is missing/invalid/expired/revoked -- there is no recovering from this
        // client-side; send the user back to a real login rather than showing a confusing
        // partial page full of failed requests. A failed *login attempt* is its own, expected
        // 401 (wrong password) and must not clear/redirect an unrelated existing session.
        clearCurrentUser();
        if (!window.location.pathname.startsWith("/login")) {
            window.location.href = "/login";
        }
    }

    if (!response.ok) {
        const detail = data && data.detail ? formatErrorDetail(data.detail) : `Request failed (${response.status})`;
        throw new ApiError(detail, response.status, data);
    }
    return data;
}

function getCurrentUser() {
    const raw = localStorage.getItem(CURRENT_USER_KEY);
    if (!raw) return null;
    try {
        return JSON.parse(raw);
    } catch {
        return null;
    }
}

function setCurrentUser(user) {
    localStorage.setItem(CURRENT_USER_KEY, JSON.stringify(user));
}

function setSession(accessToken, user) {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    setCurrentUser(user);
}

function clearCurrentUser() {
    localStorage.removeItem(CURRENT_USER_KEY);
    localStorage.removeItem(ACCESS_TOKEN_KEY);
}

function requireUserOrBanner(bannerId, panelId) {
    const user = getCurrentUser();
    const banner = document.getElementById(bannerId);
    const panel = document.getElementById(panelId);
    if (!user) {
        if (banner) banner.classList.remove("d-none");
        if (panel) panel.classList.add("d-none");
        return null;
    }
    if (banner) banner.classList.add("d-none");
    if (panel) panel.classList.remove("d-none");
    return user;
}

function showAlert(containerId, message, type = "danger") {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = `<div class="alert alert-${type} alert-dismissible fade show" role="alert">
        ${escapeHtml(message)}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    </div>`;
}

function clearAlert(containerId) {
    const container = document.getElementById(containerId);
    if (container) container.innerHTML = "";
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
}

const STATUS_LABELS = {
    not_started: "Not Started",
    in_progress: "In Progress",
    blocked: "Blocked",
    completed: "Completed",
    cancelled: "Cancelled",
};
const STATUS_CLASSES = {
    not_started: "bg-secondary",
    in_progress: "bg-primary",
    blocked: "bg-danger",
    completed: "bg-success",
    cancelled: "bg-dark",
};
function statusBadge(statusValue) {
    const cls = STATUS_CLASSES[statusValue] || "bg-secondary";
    const label = STATUS_LABELS[statusValue] || statusValue;
    return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}

const PRIORITY_LABELS = { low: "Low", medium: "Medium", high: "High", urgent: "Urgent" };
const PRIORITY_CLASSES = {
    low: "bg-light text-dark",
    medium: "bg-info text-dark",
    high: "bg-warning text-dark",
    urgent: "bg-danger",
};
function priorityBadge(priority) {
    const cls = PRIORITY_CLASSES[priority] || "bg-secondary";
    const label = PRIORITY_LABELS[priority] || priority;
    return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}

const ROLE_LABELS = { employee: "Employee", manager: "Manager", admin: "Admin" };

// Replaces the old Phase 3-6 "Acting as" employee switcher (which let anyone impersonate
// anyone — a real security hole once authorization actually matters) with a real login-status
// display: who's logged in, their role, and a Logout button; a Login link when logged out.
function initAuthNav() {
    const container = document.getElementById("auth-nav");
    if (!container) return;
    const user = getCurrentUser();
    if (!user) {
        container.innerHTML = '<a class="btn btn-outline-light btn-sm" href="/login">Log in</a>';
        return;
    }
    container.innerHTML = `
        <span class="text-light small me-2">${escapeHtml(user.name)} (${ROLE_LABELS[user.role] || user.role})</span>
        <button type="button" class="btn btn-outline-light btn-sm" id="logout-btn">Log out</button>
    `;
    document.getElementById("logout-btn").addEventListener("click", async () => {
        try {
            await apiRequest("/auth/logout", { method: "POST" });
        } catch {
            // Even if the network call fails, still clear local state and leave -- staying
            // "logged in" client-side with a token the server might have rejected is worse.
        }
        clearCurrentUser();
        window.location.href = "/login";
    });
}

// Real server-side enforcement is what actually protects data (every API route checks the
// bearer token); this is a client-side convenience so an unauthenticated visitor lands on
// /login instead of a page full of failed 401 requests.
function redirectToLoginIfUnauthenticated() {
    const publicPaths = ["/login"];
    if (publicPaths.includes(window.location.pathname)) return;
    if (!getCurrentUser() || !getAccessToken()) {
        window.location.href = "/login";
    }
}

function highlightActiveNav() {
    const path = window.location.pathname;
    document.querySelectorAll("[data-nav]").forEach((link) => {
        const target = link.getAttribute("data-nav");
        const isActive = target === "/" ? path === "/" : path.startsWith(target);
        link.classList.toggle("active", isActive);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    redirectToLoginIfUnauthenticated();
    initAuthNav();
    highlightActiveNav();
});
