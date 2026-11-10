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

let sessionGeneration = 0;
let refreshPromise = null;

function refreshSession() {
  // Rotating refresh tokens must only be exchanged once per tab at a time.
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const csrf = await ensureCSRFToken();
        const response = await fetch(`${API_BASE}/api/v1/auth/refresh/`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRFToken": csrf },
        });
        if (response.ok) sessionGeneration += 1;
        return response.ok;
      } catch {
        return false;
      }
    })().finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

let activeMutations = 0;
let mutationFailure = null;
async function request(path, options = {}, retry = true) {
  const tracked = !["GET", "HEAD", "OPTIONS"].includes((options.method || "GET").toUpperCase())
    && !/\/(auth|assistant)\/|\/autosave\//.test(path);
  const publish = detail => window.dispatchEvent(new CustomEvent("openlims:request", { detail }));
  if (tracked) {
    if (activeMutations === 0) mutationFailure = null;
    activeMutations += 1;
    publish({ state: "pending" });
  }
  try {
    const response = await performRequest(path, options, retry);
    if (tracked && !response.ok) mutationFailure = { state: "error", status: response.status };
    return response;
  } catch (error) {
    if (tracked) mutationFailure = { state: "error" };
    throw error;
  } finally {
    if (tracked && --activeMutations === 0) publish(mutationFailure || { state: "success" });
  }
}

async function performRequest(path, options = {}, retry = true) {
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

  const requestGeneration = sessionGeneration;
  const response = await fetch(`${API_BASE}${requestPath}`, {
    ...options,
    method,
    headers,
    credentials: "same-origin",
  });

  const isAuthRequest = requestPath.startsWith("/api/v1/auth/");
  if (response.status === 401 && !isAuthRequest) {
    options.signal?.throwIfAborted();
    if (retry) {
      // A slow response may belong to the session we have already refreshed.
      const renewed = requestGeneration !== sessionGeneration || await refreshSession();
      options.signal?.throwIfAborted();
      if (renewed) return performRequest(requestPath, options, false);
    }
    redirectToLogin();
    throw new Error("Session expired. Please log in again.");
  }

  return response;
}

function downloadFilename(disposition, fallback) {
  let plain;
  let encoded;
  const parameters = /(?:^|;)\s*(filename\*?)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;]*))/gi;
  for (const match of disposition.matchAll(parameters)) {
    const value = match[2] === undefined ? match[3].trim() : match[2].replace(/\\(.)/g, "$1");
    if (match[1].toLowerCase() === "filename*") encoded ??= value;
    else plain ??= value;
  }

  const utf8 = encoded?.match(/^UTF-8'[^']*'(.*)$/i);
  if (utf8) {
    try {
      const decoded = decodeURIComponent(utf8[1]);
      if (decoded) return decoded;
    } catch {
      // A malformed extended name must not prevent downloading the file.
    }
  }
  return plain || fallback;
}

function downloadResponseBlob(response, fallbackFilename) {
  return response.blob().then((blob) => {
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = downloadFilename(disposition, fallbackFilename);
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

export async function apiGet(path, { signal } = {}) {
  const response = await request(path, { method: "GET", signal });
  if (!response.ok) {
    throw new Error(`GET ${normalizeApiPath(path)} failed: ${response.status}`);
  }
  return response.json();
}

export function apiPostResponse(path, body, { signal } = {}) {
  return request(path, { method: "POST", body: JSON.stringify(body), signal });
}

export function apiPatchResponse(path, body, { signal } = {}) {
  return request(path, { method: "PATCH", body: JSON.stringify(body), signal });
}

export function apiDeleteResponse(path, { signal } = {}) {
  return request(path, { method: "DELETE", signal });
}

export function apiGetResponse(path, { signal } = {}) {
  return request(path, { method: "GET", signal });
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

export async function apiPost(path, body, { signal } = {}) {
  const response = await request(path, {
    method: "POST",
    body: JSON.stringify(body),
    signal,
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

export function apiPostFormResponse(path, formData, { signal } = {}) {
  return request(path, { method: "POST", body: formData, signal });
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
