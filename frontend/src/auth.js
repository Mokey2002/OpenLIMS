const LEGACY_TOKEN_KEYS = [
  "openlims_access",
  "openlims_refresh",
  "access",
  "refresh",
  "access_token",
  "refresh_token",
  "token",
];

export function clearLegacyTokens() {
  for (const key of LEGACY_TOKEN_KEYS) {
    localStorage.removeItem(key);
    sessionStorage.removeItem(key);
  }
}

export function getCookie(name) {
  const prefix = `${name}=`;
  const item = document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix));

  return item ? decodeURIComponent(item.slice(prefix.length)) : "";
}

export function getCSRFToken() {
  return getCookie("csrftoken");
}
