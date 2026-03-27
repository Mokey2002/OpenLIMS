import { getAccessToken, getRefreshToken, setTokens, clearTokens } from "./auth";

const API_BASE = "";//import.meta.env.VITE_API_BASE || "http://localhost:8000";

export async function apiPostForm(path, formData) {
  const access = getAccessToken();

  const headers = {};
  if (access) {
    headers.Authorization = `Bearer ${access}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${path} failed: ${res.status} ${text}`);
  }

  return res.json();
}

async function refreshAccessToken() {
  const refresh = getRefreshToken();
  if (!refresh) return null;

  const res = await fetch(`${API_BASE}/api/auth/token/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });

  if (!res.ok) return null;

  const data = await res.json();
  // refresh endpoint returns { access: "..." }
  setTokens({ access: data.access });
  return data.access;
}

async function request(path, options = {}, retry = true) {
  const access = getAccessToken();

  const headers = {
    ...(options.headers || {}),
    "Content-Type": "application/json",
  };

  if (access) headers.Authorization = `Bearer ${access}`;

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  // If unauthorized, try refresh once
  if (res.status === 401 && retry) {
    const newAccess = await refreshAccessToken();
    if (newAccess) {
      return request(path, options, false);
    }
    clearTokens();
  }

  return res;
}

export async function apiGet(path) {
  const res = await request(path, { method: "GET" });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

export async function apiPost(path, body) {
  const res = await request(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${path} failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function apiPatch(path, body) {
  const res = await request(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PATCH ${path} failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function apiDelete(path) {
  const res = await request(path, { method: "DELETE" });
  if (!res.ok) throw new Error(`DELETE ${path} failed: ${res.status}`);
  return true;
}

// login helper
export async function login(username, password) {
  const res = await fetch(`${API_BASE}/api/auth/token/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Login failed: ${res.status} ${text}`);
  }

  const data = await res.json(); // { access, refresh }
  setTokens(data);
  return data;
}
