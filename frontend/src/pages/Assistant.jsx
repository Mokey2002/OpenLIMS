import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Form,
  Spinner,
} from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiPost } from "../api";

const STARTER_PROMPTS = [
  "Summarize project PRJ-UW-PILOT",
  "Find sample S-UW-101",
  "Show failed migration jobs",
  "Show skipped migration rows",
  "Why did migration job #1 fail?",
  "Show running migration jobs",
];

export default function Assistant() {
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState([
    {
      role: "assistant",
      content:
        "Ask me about samples, projects, migration jobs, skipped rows, failed imports, or where a sample is located.",
      links: [],
      suggestions: STARTER_PROMPTS,
    },
  ]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

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

      setHistory([
        ...nextHistory,
        {
          role: "assistant",
          content: data.answer || "No answer returned.",
          links: data.links || [],
          suggestions: data.suggestions || [],
          mode: data.mode || "rules",
          llmError: data.llm_error || "",
        },
      ]);
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

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">OpenLIMS Assistant</h1>
          <p className="page-subtitle">
            Read-only assistant for finding samples, reviewing projects, and
            explaining migration jobs.
          </p>
        </div>

        <Badge bg="dark">v0.19 read-only</Badge>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Alert variant="info">
        This assistant is read-only. When an LLM key is configured, it can
        summarize results more naturally. Without a key, it falls back to
        rule-based search.
      </Alert>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="assistant-chat-window">
            {history.map((item, index) => (
              <div
                key={`${item.role}-${index}`}
                className={`assistant-message assistant-message-${item.role}`}
              >
                <div className="assistant-message-label">
                  {item.role === "user" ? "You" : "Assistant"}
                  {item.role === "assistant" && item.mode && (
                    <Badge
                      bg={item.mode === "llm" ? "primary" : "secondary"}
                      className="ms-2"
                    >
                      {item.mode === "llm" ? "LLM" : "Rules"}
                    </Badge>
                  )}
                </div>

                <pre className="assistant-message-body">{item.content}</pre>

                {item.llmError && (
                  <Alert variant="warning" className="mt-2 mb-2">
                    {item.llmError}
                  </Alert>
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
            ))}

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
