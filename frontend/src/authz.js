export function hasRole(me, role) {
  return me?.roles?.includes(role);
}

export function isAdmin(me) {
  return hasRole(me, "admin");
}

export function isTech(me) {
  return hasRole(me, "tech");
}

export function isViewer(me) {
  return hasRole(me, "viewer");
}

export function canWrite(me) {
  return isAdmin(me) || isTech(me);
}

export function canManageUsers(me) {
  return isAdmin(me);
}

export function readOnlyMessage(me) {
  if (isViewer(me)) {
    return "Read-only access: contact an admin or tech to make changes.";
  }

  return "";
}