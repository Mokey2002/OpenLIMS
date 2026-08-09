import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Form,
  Spinner,
} from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import AssistantChart from "../components/AssistantChart";
import AssistantActionPreview from "../components/AssistantActionPreview";
import { OPENLIMS_VERSION } from "../version";

const STARTER_PROMPTS = [
  "What needs attention?",
  "Show samples received today",
  "Find sample S-1042",
  "Which samples in Project Alpha are awaiting processing?",
  "Which results are awaiting approval?",
  "Show results that failed QC this week",
  "Which reagents expire in the next 30 days?",
  "Show inventory below its reorder level",
  "Show overdue sequencing work",
  "Who has unassigned work today?",
  "Create sequencing work for samples in batch B-100",
  "Create barcode labels for batch B-100",
  "Export sample status changes from July as CSV",
  "How do I receive a sample?",
  "List my notification subscriptions",
  "Show system status",
  "Find sample sequences",
  "Summarize sequence records",
  "Prepare BLAST for sample",
  "Summarize BLAST results",
  "Chart samples by status",
  "Find sample",
];

function badgeVariantForProvider(provider) {
  if (provider === "openai") return "primary";
  if (provider === "ollama") return "success";
  return "secondary";
}

export default function Assistant() {
  const [message, setMessage] = useState("");
  const [conversationContext, setConversationContext] = useState({});
  const [assistantStatus, setAssistantStatus] = useState(null);
  const [history, setHistory] = useState([
    {
      role: "assistant",
      content:
        "Ask what needs attention, or ask about samples, projects, migration jobs, skipped rows, failed imports, or where a sample is located.",
      links: [],
      suggestions: STARTER_PROMPTS,
      modelInfo: {
        provider: "openlims",
        model: "rules",
        display_name: "OpenLIMS Rules",
      },
    },
  ]);
  const [loading, setLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState("");
  const [err, setErr] = useState("");

  async function loadAssistantStatus() {
    try {
      const data = await apiGet("/api/assistant/status/");
      setAssistantStatus(data);
    } catch {
      setAssistantStatus({
        provider: "openlims",
        model: "rules",
        display_name: "OpenLIMS Rules",
      });
    }
  }

  useEffect(() => {
    loadAssistantStatus();
  }, []);

  async function sendMessage(textOverride = "") {
    const text = (textOverride || message).trim();

    if (!text) return;

    setErr("");
    setLoading(true);
    setMessage("");

    const nextHistory = [
      ...history,
      {
        role: "user",
        content: text,
        links: [],
        suggestions: [],
      },
    ];

    setHistory(nextHistory);

    try {
      const data = await apiPost("/api/assistant/chat/", {
        message: text,
        context: conversationContext,
      });

      setConversationContext(data.context || {});

      setHistory([
        ...nextHistory,
        {
          role: "assistant",
          content: data.answer || "No answer returned.",
          links: data.links || [],
          suggestions: data.suggestions || [],
          chart: data.chart || null,
          pendingAction: data.pending_action || null,
          actionError: data.action_error || "",
          mode: data.mode || "openlims",
          llmError: data.llm_error || "",
          modelInfo:
            data.model_info || {
              provider: "openlims",
              model: "rules",
              display_name: "OpenLIMS Rules",
            },
        },
      ]);

      if (data.model_info) {
        setAssistantStatus(data.model_info);
      }
    } catch (e) {
      setErr(e.message || String(e));
      setHistory(nextHistory);
    } finally {
      setLoading(false);
    }
  }

  function updateHistoryAction(index, pendingAction, actionError = "") {
    setHistory((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index
          ? { ...item, pendingAction, actionError }
          : item
      )
    );
  }

  async function confirmAssistantAction(index, pendingAction) {
    setErr("");
    setActionBusy(pendingAction.confirmation_token);

    try {
      const updated = await apiPost(
        `/api/assistant/actions/${pendingAction.confirmation_token}/confirm/`,
        { confirm: true }
      );
      if (updated.result?.context) {
        setConversationContext((current) => ({
          ...current,
          ...updated.result.context,
        }));
      }
      updateHistoryAction(index, updated);
    } catch (e) {
      updateHistoryAction(
        index,
        pendingAction,
        e.message || String(e)
      );
    } finally {
      setActionBusy("");
    }
  }

  async function cancelAssistantAction(index, pendingAction) {
    setErr("");
    setActionBusy(pendingAction.confirmation_token);

    try {
      const updated = await apiPost(
        `/api/assistant/actions/${pendingAction.confirmation_token}/cancel/`,
        {}
      );
      updateHistoryAction(index, updated);
    } catch (e) {
      updateHistoryAction(
        index,
        pendingAction,
        e.message || String(e)
      );
    } finally {
      setActionBusy("");
    }
  }

  function submit(e) {
    e.preventDefault();
    sendMessage();
  }

  const activeProvider = assistantStatus?.provider || "openlims";
  const activeDisplayName = assistantStatus?.display_name || "OpenLIMS Rules";

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">OpenLIMS Assistant</h1>
          <p className="page-subtitle">
            Find and review laboratory data, then explicitly confirm any
            action before OpenLIMS executes it.
          </p>
        </div>

        <div className="d-flex flex-column align-items-end gap-2">
          <Badge bg="dark">{OPENLIMS_VERSION} confirmed actions</Badge>
          <Badge bg={badgeVariantForProvider(activeProvider)}>
            Using: {activeDisplayName}
          </Badge>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Alert variant="info">
        The assistant can preview sample, QC, inventory, work assignment,
        barcode-label, compliance-report, and notification operations. It can
        also answer from approved SOPs and show read-only admin monitoring. A
        proposal expires after 15 minutes and never runs until you select Confirm.
      </Alert>

      <Alert variant="secondary">
        Public demo note: this hosted demo uses OpenLIMS Rules because server
        resources are limited. Self-hosted deployments can enable OpenAI or
        Ollama through environment settings.
      </Alert>


      <Card className="app-card mb-4">
        <Card.Body>
          <div className="assistant-chat-window">
            {history.map((item, index) => {
              const provider = item.modelInfo?.provider || "openlims";
              const displayName =
                item.modelInfo?.display_name || "OpenLIMS Rules";

              return (
                <div
                  key={`${item.role}-${index}`}
                  className={`assistant-message assistant-message-${item.role}`}
                >
                  <div className="assistant-message-label">
                    {item.role === "user" ? "You" : "Assistant"}
                    {item.role === "assistant" && (
                      <Badge
                        bg={badgeVariantForProvider(provider)}
                        className="ms-2"
                      >
                        {displayName}
                      </Badge>
                    )}
                  </div>

                  <pre className="assistant-message-body">{item.content}</pre>

                  {item.llmError && (
                    <Alert variant="warning" className="mt-2 mb-2">
                      {item.llmError}
                    </Alert>
                  )}

                  {item.chart && <AssistantChart chart={item.chart} />}

                  {item.actionError && (
                    <Alert variant="danger" className="mt-2 mb-2">
                      {item.actionError}
                    </Alert>
                  )}

                  {item.pendingAction && (
                    <Card className="mt-3 mb-3 border-warning">
                      <Card.Body>
                        <div className="d-flex justify-content-between align-items-start gap-3">
                          <div>
                            <div className="fw-semibold">Confirmation required</div>
                            <div>{item.pendingAction.summary}</div>
                            <small className="text-muted">
                              Status: {item.pendingAction.status}
                            </small>
                          </div>
                          <Badge
                            bg={
                              item.pendingAction.status === "PROPOSED"
                                ? "warning"
                                : item.pendingAction.status === "FAILED"
                                  ? "danger"
                                  : "success"
                            }
                            text={
                              item.pendingAction.status === "PROPOSED"
                                ? "dark"
                                : undefined
                            }
                          >
                            {item.pendingAction.status}
                          </Badge>
                        </div>

                        <AssistantActionPreview action={item.pendingAction} />

                        {item.pendingAction.status === "PROPOSED" && (
                          <div className="d-flex gap-2 mt-3">
                            <Button
                              size="sm"
                              variant="warning"
                              disabled={
                                actionBusy === item.pendingAction.confirmation_token
                              }
                              onClick={() =>
                                confirmAssistantAction(index, item.pendingAction)
                              }
                            >
                              {actionBusy ===
                              item.pendingAction.confirmation_token
                                ? "Confirming..."
                                : "Confirm action"}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline-secondary"
                              disabled={
                                actionBusy === item.pendingAction.confirmation_token
                              }
                              onClick={() =>
                                cancelAssistantAction(index, item.pendingAction)
                              }
                            >
                              Cancel
                            </Button>
                          </div>
                        )}
                      </Card.Body>
                    </Card>
                  )}

                  {item.links?.length > 0 && (
                    <div className="assistant-links">
                      {item.links.map((link, linkIndex) => (
                        <Link
                          key={`${link.url}-${linkIndex}`}
                          to={link.url}
                          className="btn btn-sm btn-outline-dark me-2 mb-2"
                        >
                          {link.label}
                        </Link>
                      ))}
                    </div>
                  )}

                  {item.suggestions?.length > 0 && (
                    <div className="assistant-suggestions mt-2">
                      {item.suggestions.map((suggestion) => (
                        <Button
                          key={suggestion}
                          size="sm"
                          variant="outline-secondary"
                          className="me-2 mb-2"
                          disabled={loading}
                          onClick={() => sendMessage(suggestion)}
                        >
                          {suggestion}
                        </Button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}

            {loading && (
              <div className="assistant-message assistant-message-assistant">
                <div className="assistant-message-label">Assistant</div>
                <div className="d-flex align-items-center gap-2">
                  <Spinner animation="border" size="sm" />
                  <span>Searching OpenLIMS...</span>
                </div>
              </div>
            )}
          </div>

          <Form onSubmit={submit} className="mt-3">
            <div className="d-flex gap-2">
              <Form.Control
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Ask about a sample, project, migration job, or failed import..."
                disabled={loading}
              />

              <Button
                type="submit"
                variant="dark"
                disabled={loading || !message.trim()}
              >
                Send
              </Button>
            </div>
          </Form>
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <h5 className="section-title">Example questions</h5>

          <div className="d-flex flex-wrap gap-2">
            {STARTER_PROMPTS.map((prompt) => (
              <Button
                key={prompt}
                size="sm"
                variant="outline-dark"
                disabled={loading}
                onClick={() => sendMessage(prompt)}
              >
                {prompt}
              </Button>
            ))}
          </div>
        </Card.Body>
      </Card>
    </div>
  );
}
