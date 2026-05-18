const ACCESS_KEY = "openlims_access";
const REFRESH_KEY = "openlims_refresh";

export function getAccessToken() {
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens({ access, refresh }) {
  if (access) {
    localStorage.setItem(ACCESS_KEY, access);
  }

  if (refresh) {
    localStorage.setItem(REFRESH_KEY, refresh);
  }
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

function isJwtExpired(token) {
  if (!token) return true;

  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    const expiresAt = payload.exp * 1000;

    return Date.now() >= expiresAt;
  } catch {
    return true;
  }
}

export function isLoggedIn() {
  const access = getAccessToken();
  const refresh = getRefreshToken();

  if (!access && !refresh) {
    return false;
  }

  if (access && !isJwtExpired(access)) {
    return true;
  }

  if (refresh && !isJwtExpired(refresh)) {
    return true;
  }

  clearTokens();
  return false;
}