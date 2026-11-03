import AssistantConversations from "../components/AssistantConversations";
import AssistantRequestStatus from "../components/AssistantRequestStatus";
import useAssistantRequest from "../hooks/useAssistantRequest";
import { assistantMessage } from "../assistantTransport";
import WorkflowQueryBuilder from "../components/WorkflowQueryBuilder";
import WorkflowQueryExplanation from "../components/WorkflowQueryExplanation";
import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Form,
  Spinner,
} from "react-bootstrap";
import { Link, useLocation } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import AssistantChart from "../components/AssistantChart";
import ProjectWorkflowTable from "../components/ProjectWorkflowTable";
import ComparisonTable from "../components/ComparisonTable";
import InvestigationPanel from "../components/InvestigationPanel";
import AssistantActionPreview from "../components/AssistantActionPreview";
import AssistantClarification from "../components/AssistantClarification";
import AssistantContextBar from "../components/AssistantContextBar";
import AssistantFeedback from "../components/AssistantFeedback";
import AssistantDraft from "../components/AssistantDraft";
import AssistantEvidence from "../components/AssistantEvidence";
import AssistantInterpretation from "../components/AssistantInterpretation";
import { ASSISTANT_STARTER_PROMPTS } from "../assistantPrompts";
import { OPENLIMS_VERSION } from "../version";
import { pageSelection } from "../assistantPageContext";
import AssistantPageBar from "../components/AssistantPageBar";
import AssistantInstrumentUpload from "../components/AssistantInstrumentUpload";
import AssistantImportReceipt from "../components/AssistantImportReceipt";
import AssistantWorkflowGuide from "../components/AssistantWorkflowGuide";

function badgeVariantForProvider(provider) {
  if (provider === "openai") return "primary";
  if (provider === "ollama") return "success";
  return "secondary";
}

export default function Assistant() {
  const location = useLocation();
  return <AssistantSession key={location.key} initialPage={location.state?.assistantPage} />;
}

function AssistantSession({ initialPage }) {
  const [selectedPage, setSelectedPage] = useState(() => pageSelection(initialPage));
  const [message, setMessage] = useState("");
  const [conversationContext, setConversationContext] = useState({});
  const [conversationId, setConversationId] = useState(null);
  const transport = useAssistantRequest();
  const [assistantStatus, setAssistantStatus] = useState(null);
  const [starterPrompts, setStarterPrompts] = useState(ASSISTANT_STARTER_PROMPTS);
  const [history, setHistory] = useState([
    {
      role: "assistant",
      content:
        "Ask about samples, projects, QC, comparisons, inventory, sequences, or system status.",
      links: [],
      suggestions: ASSISTANT_STARTER_PROMPTS,
      modelInfo: {
        provider: "openlims",
        model: "rules",
        display_name: "OpenLIMS Rules",
      },
    },
  ]);
  const [loading, setLoading] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState("");
  const [err, setErr] = useState("");
  const workflowIndex = history.findLastIndex(item => item.workflowPlan);
  const workflowRevision = history.map(item => item.pendingAction ? `${item.pendingAction.id}:${item.pendingAction.status}` : "").join(";");

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    apiGet("/api/assistant/status/", { signal: controller.signal }).then(data => {
      if (!active) return;
      setAssistantStatus(data);
      setStarterPrompts(data.suggestions || ASSISTANT_STARTER_PROMPTS);
      setHistory((current) => {
        if (!current.length || current[0].role !== "assistant") return current;
        return [
          {
            ...current[0],
            content: data.welcome_message || current[0].content,
            suggestions: data.suggestions || current[0].suggestions,
          },
          ...current.slice(1),
        ];
      });
    }, () => {
      if (!active) return;
      setAssistantStatus({
        provider: "openlims",
        model: "rules",
        display_name: "OpenLIMS Rules",
      });
    });
    return () => { active = false; controller.abort(); };
  }, []);

  function selectConversation(data) {
    transport.reset();
    setConversationId(data.id);
    if (data.history) {
      setHistory(data.history.map(item => item.reply ? assistantMessage(item.reply) : item));
      setConversationContext(data.context || {});
    }
  }

  function newConversation() {
    transport.reset();
    setConversationId(null);
    setHistory([]);
    setConversationContext({});
  }

  async function sendMessage(textOverride = "") {
    const text = (textOverride || message).trim();
    if (!text || loading || importBusy || actionBusy) return;
    setErr(""); setLoading(true); setMessage("");
    const previous = history.at(-1)?.role === "user" && history.at(-1)?.content === text ? history.slice(0, -1) : history;
    const nextHistory = [...previous, { role: "user", content: text, links: [], suggestions: [] }];
    setHistory(nextHistory);
    try {
      const data = await transport.run({ message: text, context: conversationContext, conversation_id: conversationId,
        ...(selectedPage && assistantStatus?.page_context ? { page_context: { kind: selectedPage.kind, record_id: selectedPage.record_id } } : {}) },
        { streaming: Boolean(assistantStatus?.chat_streaming) });
      setConversationContext(data.context || {});
      setHistory([...nextHistory, assistantMessage(data)]);
      if (data.model_info) setAssistantStatus(current => ({ ...current, ...data.model_info }));
    } catch (e) {
      if (e.name !== "AbortError") setErr(e.message || String(e));
      setHistory(nextHistory);
    } finally { setLoading(false); }
  }

  function updateHistoryAction(index, pendingAction, actionError = "") {
    if (pendingAction.result?.context) {
      setConversationContext(current => ({ ...current, ...pendingAction.result.context }));
    }
    setHistory((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index
          ? { ...item, pendingAction, actionError }
          : item
      )
    );
  }

  function receiveImport(index, data) {
    setConversationContext(data.context || {});
    setHistory(current => current.map((item, position) => position === index ? assistantMessage(data) : item));
  }

  function receiveWorkflow(data) {
    setConversationContext(data.context || {});
    setHistory(current => [...current, assistantMessage(data)]);
  }

  async function confirmAssistantAction(index, pendingAction) {
    setErr("");
    setActionBusy(pendingAction.confirmation_token);

    try {
      const updated = await apiPost(
        `/api/assistant/actions/${pendingAction.confirmation_token}/confirm/`,
        { confirm: true }
      );
      updateHistoryAction(index, updated);
    } catch (e) {
      const latest = await apiGet(`/api/assistant/actions/${pendingAction.confirmation_token}/`).catch(() => pendingAction);
      updateHistoryAction(
        index,
        latest,
        ["COMPLETED", "QUEUED", "CANCELLED"].includes(latest.status) ? "" : latest.error_message || e.message || String(e)
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
      const latest = await apiGet(`/api/assistant/actions/${pendingAction.confirmation_token}/`).catch(() => pendingAction);
      updateHistoryAction(
        index,
        latest,
        ["COMPLETED", "QUEUED", "CANCELLED"].includes(latest.status) ? "" : latest.error_message || e.message || String(e)
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
          <Badge bg="dark">{OPENLIMS_VERSION} clarification and context</Badge>
          <Badge bg={badgeVariantForProvider(activeProvider)}>
            Using: {activeDisplayName}
          </Badge>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Alert variant="info">
        The assistant can investigate QC failures; compare samples, projects, and batches; graph result
        trends; find outliers and workflow bottlenecks; and preview sample, QC,
        inventory, work assignment, unreviewed result entry,
        barcode-label, compliance-report, and notification operations. It can
        also answer from approved SOPs and show read-only admin monitoring. A
        proposal expires after 15 minutes and never runs until you select Confirm.
        Ambiguous requests show clarification choices, and retained context is
        always visible and removable. After asking about a sample, try “Assign the next
        step to maria” or “Add result concentration = 43 to step 1”. Use your actual
        measurement; new results still require QC review. You can also ask “Which samples
        in project DEMO-360 are blocked, and why?” to review linked samples together.
      </Alert>

      <Alert variant="secondary">
        Public demo note: this hosted demo uses OpenLIMS Rules because server
        resources are limited. Self-hosted deployments can enable OpenAI or
        Ollama through environment settings.
      </Alert>


      <Card className="app-card mb-4">
        <Card.Body>
          <AssistantConversations conversationId={conversationId} onSelect={selectConversation} history={history} disabled={loading || importBusy || Boolean(actionBusy)} onNew={newConversation} />
          {assistantStatus?.page_context && <AssistantPageBar selection={selectedPage} onClear={() => setSelectedPage(null)} onRun={sendMessage} disabled={loading || importBusy || Boolean(actionBusy)} />}
          <AssistantRequestStatus transport={transport} loading={loading} onRetry={sendMessage} />
          <AssistantContextBar
            context={conversationContext}
            onRun={sendMessage}
            disabled={loading || importBusy || Boolean(actionBusy)}
            onClear={() => setConversationContext({})}
          />

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

                  <WorkflowQueryExplanation explanation={item.queryExplanation} />
                  {!item.queryExplanation && <pre className="assistant-message-body">{item.content}</pre>}

                  {item.llmError && (
                    <Alert variant="warning" className="mt-2 mb-2">
                      {item.llmError}
                    </Alert>
                  )}

                  {item.clarification && (
                    <AssistantClarification
                      clarification={item.clarification}
                      disabled={loading || importBusy || Boolean(actionBusy)}
                      onChoose={sendMessage}
                    />
                  )}

                  {item.chart && <AssistantChart chart={item.chart} />}

                  {item.projectWorkflows && <ProjectWorkflowTable data={item.projectWorkflows} />}

                  {item.comparison && (
                    <ComparisonTable comparison={item.comparison} />
                  )}

                  {item.investigation && (
                    <InvestigationPanel investigation={item.investigation} compact />
                  )}

                  {item.actionError && (
                    <Alert variant="danger" className="mt-2 mb-2">
                      {item.actionError}
                    </Alert>
                  )}

                  {index === workflowIndex && item.workflowPlan && typeof conversationContext.workflow_guide === "string" && <AssistantWorkflowGuide
                    initialPlan={item.workflowPlan} revision={workflowRevision} onPrepared={receiveWorkflow} onRun={sendMessage}
                    onBusy={setImportBusy} disabled={loading || importBusy || Boolean(actionBusy)} />}
                  {item.instrumentImportForm && <AssistantInstrumentUpload config={item.instrumentImportForm}
                    onPrepared={data => receiveImport(index, data)} onBusy={setImportBusy} disabled={loading || importBusy || Boolean(actionBusy)} />}
                  {item.instrumentImportJob && !item.pendingAction && <AssistantImportReceipt jobId={item.instrumentImportJob.id}
                    initialJob={item.instrumentImportJob} actionStatus={item.instrumentImportJob.action?.status}
                    onActionUpdate={action => updateHistoryAction(index, action)} onPrepared={data => receiveImport(index, data)}
                    onBusy={setImportBusy} disabled={loading || importBusy || Boolean(actionBusy)} />}

                  {item.pendingAction && (
                    <Card className="mt-3 mb-3 border-warning">
                      <Card.Body>
                        <div className="d-flex justify-content-between align-items-start gap-3">
                          <div>
                            <div className="fw-semibold">{item.pendingAction.status === "PROPOSED" ? "Confirmation required" : "Action status"}</div>
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

                        <AssistantActionPreview action={item.pendingAction} onActionUpdate={action => updateHistoryAction(index, action)}
                          onPrepared={data => receiveImport(index, data)} onBusy={setImportBusy} disabled={loading || importBusy || Boolean(actionBusy)} />

                        {item.pendingAction.status === "PROPOSED" && (
                          <div className="d-flex gap-2 mt-3">
                            <Button
                              size="sm"
                              variant="warning"
                              disabled={
                                importBusy || actionBusy === item.pendingAction.confirmation_token
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
                                importBusy || actionBusy === item.pendingAction.confirmation_token
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

                  {!item.projectWorkflows && item.links?.length > 0 && (
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

                  <AssistantEvidence citations={item.citations} readPlan={item.readPlan} />
                  {item.draft && <AssistantDraft draft={item.draft} />}
                  <AssistantInterpretation interpretation={item.interpretation} />
                  {item.suggestions?.length > 0 && (
                    <div className="assistant-suggestions mt-2">
                      {item.suggestions.map((suggestion) => (
                        <Button
                          key={suggestion}
                          size="sm"
                          variant="outline-secondary"
                          className="me-2 mb-2"
                          disabled={loading || importBusy || Boolean(actionBusy)}
                          onClick={() => sendMessage(suggestion)}
                        >
                          {suggestion}
                        </Button>
                      ))}
                    </div>
                  )}

                  {item.role === "assistant" && (
                    <AssistantFeedback interactionId={item.interactionId} />
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

          <WorkflowQueryBuilder context={conversationContext} onRun={sendMessage} disabled={loading || importBusy || Boolean(actionBusy)} />
          <Form onSubmit={submit} className="mt-3">
            <div className="d-flex gap-2">
              <Form.Control
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Compare samples or projects, graph results, find outliers..."
                disabled={loading || importBusy || Boolean(actionBusy)}
              />

              <Button
                type="submit"
                variant="dark"
                disabled={loading || importBusy || Boolean(actionBusy) || !message.trim()}
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
            {starterPrompts.map((prompt) => (
              <Button
                key={prompt}
                size="sm"
                variant="outline-dark"
                disabled={loading || importBusy || Boolean(actionBusy)}
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
