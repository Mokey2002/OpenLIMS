import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Form, Spinner } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import AssistantChart from "./AssistantChart";
import ComparisonTable from "./ComparisonTable";
import AssistantActionPreview from "./AssistantActionPreview";

const STARTER_PROMPTS = [
  "What needs attention?",
  "Compare samples S-100, S-101, and S-102",
  "Compare projects Alpha and Beta",
  "Find unusual results in Project Alpha",
  "Show samples received today",
  "Find sample S-1042",
  "Which samples in Project Alpha are awaiting processing?",
  "Which results are awaiting approval?",
  "Which reagents expire in the next 30 days?",
  "Where is sample S-1042?",
  "Find sample sequences",
  "Summarize sequence records",
  "Prepare BLAST for sample",
  "Chart samples by status",
];

const DEMO_ASSISTANT_NOTE =
  "Public demo note: this hosted demo uses OpenLIMS Rules because server resources are limited. Self-hosted deployments can enable OpenAI or Ollama.";

function badgeVariantForProvider(provider) {
  if (provider === "openai") return "primary";
  if (provider === "ollama") return "success";
  return "secondary";
}

export default function AssistantWidget() {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [conversationContext, setConversationContext] = useState({});
  const [assistantStatus, setAssistantStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState("");
  const [err, setErr] = useState("");
  const [history, setHistory] = useState([
    {
      role: "assistant",
      content:
        "Hi, ask what needs attention or let me help you find samples, projects, migration jobs, skipped rows, and failed imports.",
      links: [],
      suggestions: STARTER_PROMPTS,
      modelInfo: {
        provider: "openlims",
        model: "rules",
        display_name: "OpenLIMS Rules",
      },
    },
  ]);

  const bottomRef = useRef(null);

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

  useEffect(() => {
    if (open && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [history, loading, open]);

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

      const modelInfo =
        data.model_info || {
          provider: "openlims",
          model: "rules",
          display_name: "OpenLIMS Rules",
        };

      setHistory([
        ...nextHistory,
        {
          role: "assistant",
          content: data.answer || "No answer returned.",
          links: data.links || [],
          suggestions: data.suggestions || [],
          chart: data.chart || null,
          comparison: data.comparison || null,
          pendingAction: data.pending_action || null,
          actionError: data.action_error || "",
          llmError: data.llm_error || "",
          modelInfo,
        },
      ]);

      setAssistantStatus(modelInfo);
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

  async function handleAction(index, pendingAction, operation) {
    setActionBusy(pendingAction.confirmation_token);

    try {
      const body = operation === "confirm" ? { confirm: true } : {};
      const updated = await apiPost(
        `/api/assistant/actions/${pendingAction.confirmation_token}/${operation}/`,
        body
      );
      if (updated.result?.context) {
        setConversationContext((current) => ({
          ...current,
          ...updated.result.context,
        }));
      }
      updateHistoryAction(index, updated);
    } catch (e) {
      updateHistoryAction(index, pendingAction, e.message || String(e));
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
    <>
      {open && (
        <div className="assistant-widget-panel">
          <div className="assistant-widget-header">
            <div>
              <div className="assistant-widget-title">OpenLIMS Assistant</div>
              <Badge bg={badgeVariantForProvider(activeProvider)}>
                {activeDisplayName}
              </Badge>
            </div>

            <Button
              size="sm"
              variant="outline-light"
              onClick={() => setOpen(false)}
              aria-label="Close assistant"
            >
              ×
            </Button>
          </div>

          <div className="assistant-widget-demo-note">
            {DEMO_ASSISTANT_NOTE}
          </div>

          <div className="assistant-widget-body">
            {err && (
              <Alert variant="danger" className="assistant-widget-alert">
                {err}
              </Alert>
            )}

            {history.map((item, index) => {
              const provider = item.modelInfo?.provider || "openlims";
              const displayName =
                item.modelInfo?.display_name || "OpenLIMS Rules";

              return (
                <div
                  key={`${item.role}-${index}`}
                  className={`assistant-widget-message assistant-widget-message-${item.role}`}
                >
                  <div className="assistant-widget-message-label">
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

                  <div className="assistant-widget-message-text">
                    {item.content}
                  </div>

                  {item.llmError && (
                    <Alert variant="warning" className="mt-2 mb-1 py-2">
                      {item.llmError}
                    </Alert>
                  )}

                  {item.chart && <AssistantChart chart={item.chart} />}

                  {item.comparison && (
                    <ComparisonTable comparison={item.comparison} />
                  )}

                  {item.actionError && (
                    <Alert variant="danger" className="mt-2 mb-1 py-2">
                      {item.actionError}
                    </Alert>
                  )}

                  {item.pendingAction && (
                    <Alert variant="warning" className="mt-2 mb-2 py-2">
                      <div className="fw-semibold">Confirmation required</div>
                      <div className="small mb-2">{item.pendingAction.summary}</div>
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
                      <AssistantActionPreview action={item.pendingAction} />
                      {item.pendingAction.status === "PROPOSED" && (
                        <div className="d-flex gap-2 mt-2">
                          <Button
                            size="sm"
                            variant="dark"
                            disabled={
                              actionBusy === item.pendingAction.confirmation_token
                            }
                            onClick={() =>
                              handleAction(index, item.pendingAction, "confirm")
                            }
                          >
                            Confirm
                          </Button>
                          <Button
                            size="sm"
                            variant="outline-secondary"
                            disabled={
                              actionBusy === item.pendingAction.confirmation_token
                            }
                            onClick={() =>
                              handleAction(index, item.pendingAction, "cancel")
                            }
                          >
                            Cancel
                          </Button>
                        </div>
                      )}
                    </Alert>
                  )}

                  {item.links?.length > 0 && (
                    <div className="assistant-widget-links">
                      {item.links.map((link, linkIndex) => (
                        <Link
                          key={`${link.url}-${linkIndex}`}
                          to={link.url}
                          className="btn btn-sm btn-outline-dark me-2 mb-2"
                          onClick={() => setOpen(false)}
                        >
                          {link.label}
                        </Link>
                      ))}
                    </div>
                  )}

                  {item.suggestions?.length > 0 && (
                    <div className="assistant-widget-suggestions">
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
              <div className="assistant-widget-message assistant-widget-message-assistant">
                <div className="assistant-widget-message-label">Assistant</div>
                <div className="assistant-widget-thinking">
                  <Spinner animation="border" size="sm" />
                  <span className="assistant-typing-dots">
                    <span></span>
                    <span></span>
                    <span></span>
                  </span>
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          <Form onSubmit={submit} className="assistant-widget-form">
            <Form.Control
              size="sm"
              value={message}
              disabled={loading}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Ask OpenLIMS..."
            />
            <Button
              size="sm"
              type="submit"
              variant="dark"
              disabled={loading || !message.trim()}
            >
              Send
            </Button>
          </Form>
        </div>
      )}

      <button
        type="button"
        className={`assistant-widget-button ${open ? "assistant-widget-button-open" : ""}`}
        onClick={() => setOpen(!open)}
        aria-label="Open OpenLIMS Assistant"
      >
        <span className="assistant-widget-pulse"></span>
        <span className="assistant-widget-icon">🤖</span>
      </button>
    </>
  );
}
