import { useState } from "react";
import { Button, Form } from "react-bootstrap";
import { apiPost } from "../api";

export default function AssistantFeedback({ interactionId, compact = false }) {
  const [rating, setRating] = useState("");
  const [category, setCategory] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  if (!interactionId) return null;

  async function submit(nextRating, nextCategory = category, nextNote = note) {
    setSaving(true);
    setError("");
    try {
      const response = await apiPost(
        `/api/assistant/interactions/${interactionId}/feedback/`,
        { rating: nextRating, category: nextCategory, note: nextNote }
      );
      setRating(response.rating);
      setCategory(response.category || "");
      setNote(response.note || "");
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`assistant-feedback mt-2 ${compact ? "small" : ""}`}>
      <div className="d-flex align-items-center gap-2">
        <span className="text-muted">Was this useful?</span>
        <Button
          type="button"
          size="sm"
          variant={rating === "UP" ? "success" : "outline-secondary"}
          disabled={saving}
          aria-label="Mark assistant response helpful"
          onClick={() => submit("UP", "", "")}
        >
          👍
        </Button>
        <Button
          type="button"
          size="sm"
          variant={rating === "DOWN" ? "danger" : "outline-secondary"}
          disabled={saving}
          aria-label="Mark assistant response not helpful"
          onClick={() => submit("DOWN")}
        >
          👎
        </Button>
        {saving && <span className="text-muted">Saving…</span>}
        {rating && !saving && <span className="text-muted">Feedback saved</span>}
      </div>

      {rating === "DOWN" && (
        <div className="d-flex flex-wrap gap-2 mt-2">
          <Form.Select
            size="sm"
            value={category}
            aria-label="Assistant feedback category"
            onChange={(event) => setCategory(event.target.value)}
            style={{ maxWidth: 190 }}
          >
            <option value="">Choose a reason</option>
            <option value="WRONG_ROUTE">Wrong route</option>
            <option value="WRONG_RECORDS">Wrong records</option>
            <option value="MISSING_DETAIL">Missing detail</option>
            <option value="UNWANTED_CHART">Unwanted chart</option>
            <option value="OTHER">Other</option>
          </Form.Select>
          <Form.Control
            size="sm"
            value={note}
            maxLength={1000}
            placeholder="Optional detail"
            onChange={(event) => setNote(event.target.value)}
            style={{ maxWidth: 280 }}
          />
          <Button
            type="button"
            size="sm"
            variant="outline-dark"
            disabled={saving}
            onClick={() => submit("DOWN")}
          >
            Save details
          </Button>
        </div>
      )}
      {error && <div className="text-danger mt-1">{error}</div>}
    </div>
  );
}
