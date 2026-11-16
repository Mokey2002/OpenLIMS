export function workAction(item) {
  if (item.qc_status === "PENDING_REVIEW") return { label: "Review results", to: "/qc-review" };
  if (item.qc_status === "RERUN_REQUIRED" || item.status === "FAILED") return { label: "Review and retry work", to: "/work-queue" };
  return { label: item.status === "IN_PROGRESS" ? "Continue work" : "Start work", to: "/work-queue" };
}

export function prioritizeWork(items, now = Date.now()) {
  const rank = item => item.due_at && Date.parse(item.due_at) < now ? 0
    : ["PENDING_REVIEW", "RERUN_REQUIRED"].includes(item.qc_status) || item.status === "FAILED" ? 1 : 2;
  return [...items].sort((a, b) => rank(a) - rank(b) ||
    (Date.parse(a.due_at) || Infinity) - (Date.parse(b.due_at) || Infinity));
}
