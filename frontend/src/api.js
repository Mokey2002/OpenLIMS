export async function apiGet(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function apiPatch(path, body) {
  const res = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function apiDelete(path) {
  const res = await fetch(path, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error(await res.text());
  return true;
}

export async function apiPut(path, body) {
  const res = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function apiGetJson(path) {
  // same as apiGet, but keeps name clear when we read non-list endpoints
  return apiGet(path);
}
