export function notebookEditAccess(experiment) {
  const writable = Boolean(experiment?.permissions?.write);
  if (["LOCKED", "REVIEWED"].includes(experiment?.status)) return { allowed: false,
    reason: experiment.status === "LOCKED" ? "This experiment is locked." : "This experiment has been reviewed.",
    next_step: writable ? "Clone this experiment to continue in an editable copy." : "Ask the notebook owner for an editable copy." };
  if (!writable) return { allowed: false, reason: "Editing requires notebook edit access.", next_step: "Ask the notebook owner to grant edit access. Project membership alone may not grant editing.", href: "/me" };
  if (experiment?.status === "COMPLETED") return { allowed: false, reason: "This experiment is complete and awaiting review.", next_step: "Use the review workflow or clone the experiment to continue." };
  if (!["DRAFT", "IN_PROGRESS"].includes(experiment?.status)) return { allowed: false, reason: "The current experiment state is unavailable.", next_step: "Refresh the record before trying again." };
  return { allowed: true };
}
