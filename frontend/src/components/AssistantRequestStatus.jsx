import { Button } from "react-bootstrap";

export default function AssistantRequestStatus({ transport, loading, onRetry }) {
  if (transport.status === "idle" || transport.status === "complete") return null;
  return <div className="my-2" aria-label="Assistant request status">
    {loading && <><div role="status" aria-live="polite">{transport.progress}</div>
      {transport.partial && <pre className="text-wrap">{transport.partial}</pre>}
      <Button size="sm" variant="outline-danger" onClick={transport.stop}>Stop</Button></>}
    {!loading && ["error", "stopped"].includes(transport.status) && <>
      {transport.status === "stopped" && <div role="status">{transport.progress}</div>}
      <Button size="sm" variant="outline-secondary" onClick={() => onRetry(transport.lastMessage)}>Retry last question</Button>
    </>}
  </div>;
}
