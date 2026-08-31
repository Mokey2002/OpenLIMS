import { clearLegacyTokens, getCSRFToken } from "./auth";

const API_BASE = "";
const UNVERSIONED_API_PATHS = ["/api/health/", "/api/schema/", "/api/docs/"];

function normalizeApiPath(path) {
  if (!path) return path;

  if (/^https?:\/\//i.test(path)) {
    const parsed = new URL(path);
    return `${parsed.pathname}${parsed.search}`;
  }

  if (path.startsWith("/api/v1/")) return path;
  if (UNVERSIONED_API_PATHS.some((prefix) => path.startsWith(prefix))) return path;
  if (path.startsWith("/api/")) return `/api/v1/${path.slice(5)}`;
  return path;
}

function withPageSize(path, pageSize) {
  const normalized = normalizeApiPath(path);
  if (!normalized || !pageSize || /[?&]page_size=/.test(normalized)) return normalized;
  if (!normalized.startsWith("/api/")) return normalized;
  return `${normalized}${normalized.includes("?") ? "&" : "?"}page_size=${pageSize}`;
}

function redirectToLogin() {
  clearLegacyTokens();
  if (window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

async function ensureCSRFToken() {
  let token = getCSRFToken();
  if (token) return token;

  const response = await fetch(`${API_BASE}/api/v1/auth/csrf/`, {
    method: "GET",
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(`Unable to initialize CSRF protection: ${response.status}`);
  }

  token = getCSRFToken();
  if (!token) {
    throw new Error("CSRF cookie was not set by the server.");
  }
  return token;
}

async function refreshSession() {
  try {
    const csrf = await ensureCSRFToken();
    const response = await fetch(`${API_BASE}/api/v1/auth/refresh/`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf },
    });
    return response.ok;
  } catch {
    return false;
  }
}

async function request(path, options = {}, retry = true) {
  const requestPath = normalizeApiPath(path);
  const method = (options.method || "GET").toUpperCase();
  const isFormData = options.body instanceof FormData;
  const headers = { ...(options.headers || {}) };

  if (!isFormData && options.body !== undefined && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {
    headers["X-CSRFToken"] = await ensureCSRFToken();
  }

  const response = await fetch(`${API_BASE}${requestPath}`, {
    ...options,
    method,
    headers,
    credentials: "same-origin",
  });

  const isAuthRequest = requestPath.startsWith("/api/v1/auth/");
  if (response.status === 401 && retry && !isAuthRequest) {
    if (await refreshSession()) {
      return request(requestPath, options, false);
    }
    redirectToLogin();
    throw new Error("Session expired. Please log in again.");
  }

  if (response.status === 401 && !isAuthRequest) {
    redirectToLogin();
    throw new Error("Session expired. Please log in again.");
  }

  return response;
}

function downloadResponseBlob(response, fallbackFilename) {
  return response.blob().then((blob) => {
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i);
    const filename = match ? decodeURIComponent(match[1].replace(/"$/, "")) : fallbackFilename;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  });
}

export async function apiGet(path) {
  const response = await request(path, { method: "GET" });
  if (!response.ok) {
    throw new Error(`GET ${normalizeApiPath(path)} failed: ${response.status}`);
  }
  return response.json();
}

export async function apiGetAll(path, maxPages = 100, pageSize = 200) {
  const items = [];
  let next = withPageSize(path, pageSize);
  let pageCount = 0;

  while (next && pageCount < maxPages) {
    const data = await apiGet(next);
    if (Array.isArray(data)) return [...items, ...data];

    items.push(...(data.results || []));
    next = data.next ? normalizeApiPath(data.next) : null;
    pageCount += 1;
  }

  return items;
}

export async function apiPost(path, body) {
  const response = await request(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`POST ${normalizeApiPath(path)} failed: ${response.status} ${text}`);
  }
  return response.status === 204 ? null : response.json();
}

export async function apiPatch(path, body) {
  const response = await request(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`PATCH ${normalizeApiPath(path)} failed: ${response.status} ${text}`);
  }
  return response.status === 204 ? null : response.json();
}

export async function apiDelete(path) {
  const response = await request(path, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`DELETE ${normalizeApiPath(path)} failed: ${response.status}`);
  }
  return true;
}

export async function apiPostForm(path, formData) {
  const response = await request(path, { method: "POST", body: formData });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`POST ${normalizeApiPath(path)} failed: ${response.status} ${text}`);
  }
  return response.json();
}

export async function apiPatchForm(path, formData) {
  const response = await request(path, { method: "PATCH", body: formData });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`PATCH ${normalizeApiPath(path)} failed: ${response.status} ${text}`);
  }
  return response.json();
}

export async function apiDownload(path, fallbackFilename = "openlims-download") {
  const response = await request(path, { method: "GET" });
  if (!response.ok) {
    throw new Error(`GET ${normalizeApiPath(path)} failed: ${response.status}`);
  }
  await downloadResponseBlob(response, fallbackFilename);
}

export async function apiPostDownload(path, body, fallbackFilename = "openlims-download") {
  const response = await request(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`POST ${normalizeApiPath(path)} failed: ${response.status} ${text}`);
  }
  await downloadResponseBlob(response, fallbackFilename);
}

export async function login(username, password) {
  clearLegacyTokens();
  const csrf = await ensureCSRFToken();
  const response = await fetch(`${API_BASE}/api/v1/auth/login/`, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrf,
    },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Login failed: ${response.status} ${text}`);
  }

  return response.json();
}

export async function logout() {
  try {
    const csrf = await ensureCSRFToken();
    await fetch(`${API_BASE}/api/v1/auth/logout/`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf },
    });
  } finally {
    clearLegacyTokens();
  }
}
