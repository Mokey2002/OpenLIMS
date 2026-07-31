import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Form, Spinner } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";

const STARTER_PROMPTS = [
  "Find sample",
  "Show failed migration jobs",
  "Show skipped migration rows",
  "What's my name?",
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
  const [assistantStatus, setAssistantStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [history, setHistory] = useState([
    {
      role: "assistant",
      content:
        "Hi, I can help you find samples, projects, migration jobs, skipped rows, and failed imports.",
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
      });

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
