import { useState } from "react";
import { apiPost } from "../api";

export default function useConfirmedOperation(onCompleted) {
  const [action, setAction] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function propose(command, context = {}) {
    setBusy(true);
    setError("");
    setMessage("");
    setAction(null);

    try {
      const response = await apiPost("/api/assistant/chat/", {
        message: command,
        context,
      });

      if (!response.pending_action) {
        setError(response.answer || response.action_error || "No operation was proposed.");
        return null;
      }

      setMessage(response.answer || "Review and confirm this operation.");
      setAction(response.pending_action);
      return response.pending_action;
    } catch (requestError) {
      setError(requestError.message || String(requestError));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!action?.confirmation_token) return null;
    setBusy(true);
    setError("");

    try {
      const updated = await apiPost(
        `/api/assistant/actions/${action.confirmation_token}/confirm/`,
        { confirm: true }
      );
      setAction(updated);
      setMessage(
        updated.status === "COMPLETED"
          ? "Operation completed."
          : updated.summary || "Operation updated."
      );
      if (updated.status === "COMPLETED" && onCompleted) {
        await onCompleted(updated);
      }
      return updated;
    } catch (requestError) {
      setError(requestError.message || String(requestError));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!action?.confirmation_token) return null;
    setBusy(true);
    setError("");

    try {
      const updated = await apiPost(
        `/api/assistant/actions/${action.confirmation_token}/cancel/`,
        {}
      );
      setAction(updated);
      setMessage("Operation cancelled. No records were changed.");
      return updated;
    } catch (requestError) {
      setError(requestError.message || String(requestError));
      return null;
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setAction(null);
    setMessage("");
    setError("");
  }

  return { action, message, error, busy, propose, confirm, cancel, reset };
}
