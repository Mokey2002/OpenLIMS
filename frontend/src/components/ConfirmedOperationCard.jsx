import { Alert, Badge, Button, Card } from "react-bootstrap";
import AssistantActionPreview from "./AssistantActionPreview";

function statusVariant(status) {
  if (status === "COMPLETED") return "success";
  if (status === "FAILED" || status === "EXPIRED") return "danger";
  if (status === "CANCELLED") return "secondary";
  return "warning";
}

export default function ConfirmedOperationCard({ operation }) {
  if (!operation.action && !operation.error && !operation.message) return null;

  return (
    <Card className="app-card border-warning mt-4">
      <Card.Body>
        {operation.error && <Alert variant="danger">{operation.error}</Alert>}

        {operation.action && (
          <>
            <div className="d-flex justify-content-between align-items-start gap-3 flex-wrap">
              <div>
                <div className="fw-semibold">{operation.action.summary}</div>
                {operation.message && (
                  <div className="feed-meta mt-1">{operation.message}</div>
                )}
              </div>
              <Badge bg={statusVariant(operation.action.status)}>
                {operation.action.status}
              </Badge>
            </div>

            <AssistantActionPreview action={operation.action} />

            {operation.action.status === "PROPOSED" && (
              <div className="inline-actions mt-3">
                <Button
                  variant="warning"
                  size="sm"
                  disabled={operation.busy}
                  onClick={operation.confirm}
                >
                  {operation.busy ? "Confirming..." : "Confirm action"}
                </Button>
                <Button
                  variant="outline-secondary"
                  size="sm"
                  disabled={operation.busy}
                  onClick={operation.cancel}
                >
                  Cancel
                </Button>
              </div>
            )}

            {operation.action.status !== "PROPOSED" && (
              <Button
                variant="outline-dark"
                size="sm"
                className="mt-3"
                onClick={operation.reset}
              >
                Close
              </Button>
            )}
          </>
        )}
      </Card.Body>
    </Card>
  );
}
