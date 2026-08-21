import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Form,
  Row,
  Col,
  Table,
} from "react-bootstrap";
import { apiGet, apiPatch, apiPost, apiPostForm } from "../api";
import ProjectSequences from "../components/ProjectSequences";
import { canWrite, isAdmin, readOnlyMessage } from "../authz";

function formatTimestamp(ts) {
  if (!ts) return "-";

  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function sampleStatusVariant(status) {
  switch (status) {
    case "RECEIVED":
      return "secondary";
    case "IN_PROGRESS":
      return "primary";
    case "QC":
      return "warning";
    case "REPORTED":
      return "success";
    case "ARCHIVED":
      return "dark";
    default:
      return "light";
  }
}

function qcVariant(status) {
  switch (status) {
    case "APPROVED":
      return "success";
    case "REJECTED":
      return "danger";
    case "RERUN_REQUIRED":
      return "warning";
    case "PENDING_REVIEW":
      return "secondary";
    default:
      return "light";
  }
}

function qcLabel(status) {
  switch (status) {
    case "APPROVED":
      return "Approved";
    case "REJECTED":
      return "Rejected";
    case "RERUN_REQUIRED":
      return "Re-run Required";
    case "PENDING_REVIEW":
      return "Pending Review";
    default:
      return status || "Pending Review";
  }
}

function jobVariant(status) {
  switch (status) {
    case "COMPLETED":
      return "success";
    case "FAILED":
      return "danger";
    case "RUNNING":
      return "primary";
    case "PENDING":
      return "warning";
    default:
      return "secondary";
  }
}

function workStatusVariant(status) {
  switch (status) {
    case "COMPLETED":
      return "success";
    case "FAILED":
      return "danger";
    case "IN_PROGRESS":
      return "primary";
    case "CANCELLED":
      return "dark";
    case "PENDING":
      return "warning";
    default:
      return "secondary";
  }
}

function countBy(items, field) {
  return items.reduce((acc, item) => {
    const key = item[field] || "UNKNOWN";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}

async function apiGetAllPages(basePath) {
  const separator = basePath.includes("?") ? "&" : "?";
  let page = 1;
  let results = [];

  while (page <= 100) {
    const data = await apiGet(`${basePath}${separator}page=${page}`);

    if (!data?.results) {
      return data || [];
    }

    results = [...results, ...data.results];

    if (!data.next) break;

    page += 1;
  }

  return results;
}

function formatCustomFieldValue(value) {
  if (value === null || value === undefined || value === "") return "-";

  if (typeof value === "object") {
    return JSON.stringify(value);
  }

  return String(value);
}

export default function ProjectDetail() {
  const { id } = useParams();

  const [project, setProject] = useState(null);
  const [samples, setSamples] = useState([]);
  const [sampleCustomFields, setSampleCustomFields] = useState({});
  const [workItems, setWorkItems] = useState([]);
  const [pipelineRuns, setPipelineRuns] = useState([]);
  const [batches, setBatches] = useState([]);
  const [analyses, setAnalyses] = useState([]);
  const [pipelineTemplates, setPipelineTemplates] = useState([]);
  const [posts, setPosts] = useState([]);
  const [users, setUsers] = useState([]);
  const [imports, setImports] = useState([]);
  const [sequences, setSequences] = useState([]);
  const [alignments, setAlignments] = useState([]);
  const [events, setEvents] = useState([]);
  const [me, setMe] = useState(null);

  const [err, setErr] = useState("");
  const [assignmentResult, setAssignmentResult] = useState(null);
  const [assigningWorkflow, setAssigningWorkflow] = useState(false);
  const [assignmentForm, setAssignmentForm] = useState({
    scope_type: "PROJECT",
    sample: "",
    batch: "",
    assignment_type: "PIPELINE",
    analysis: "",
    pipeline_template: "",
  });
  const [savingMembers, setSavingMembers] = useState(false);

  const [note, setNote] = useState("");
  const [image, setImage] = useState(null);

  const [memberQuery, setMemberQuery] = useState("");
  const [selectedMembers, setSelectedMembers] = useState([]);

  async function load() {
    setErr("");

    try {
      const [
        projectData,
        samplesData,
        workItemsData,
        pipelineRunsData,
        batchesData,
        analysesData,
        pipelineTemplatesData,
        postsData,
        importsData,
        sequencesData,
        alignmentsData,
        eventsData,
        meData,
      ] = await Promise.all([
        apiGet(`/api/projects/${id}/`),
        apiGetAllPages(`/api/samples/?project=${id}`),
        apiGetAllPages(`/api/work-items/?project=${id}`),
        apiGetAllPages(`/api/pipeline-runs/?project=${id}`),
        apiGetAllPages(`/api/sample-batches/?project=${id}`),
        apiGetAllPages("/api/analysis-definitions/"),
        apiGetAllPages("/api/pipeline-templates/"),
        apiGet(`/api/project-posts/?project=${id}`),
        apiGet(`/api/import-jobs/`),
        apiGet(`/api/sequences/?project=${id}`),
        apiGet(`/api/alignment-jobs/?project=${id}`),
        apiGet(`/api/events/`),
        apiGet(`/api/me/`),
      ]);

      const sampleList = samplesData.results || samplesData || [];
      const workItemList = workItemsData.results || workItemsData || [];
      const pipelineRunList = pipelineRunsData.results || pipelineRunsData || [];
      const batchList = batchesData.results || batchesData || [];
      const analysisList = analysesData.results || analysesData || [];
      const pipelineTemplateList =
        pipelineTemplatesData.results || pipelineTemplatesData || [];
      const postList = postsData.results || postsData || [];
      const importList = importsData.results || importsData || [];
      const sequenceList = sequencesData.results || sequencesData || [];
      const alignmentList = alignmentsData.results || alignmentsData || [];
      const eventList = eventsData.results || eventsData || [];

      const customFieldPairs = await Promise.all(
        sampleList.map(async (sample) => {
          try {
            const fieldData = await apiGet(
              `/api/samples/${sample.id}/custom-fields/`
            );

            return [sample.id, fieldData.fields || {}];
          } catch {
            return [sample.id, {}];
          }
        })
      );

      setSampleCustomFields(Object.fromEntries(customFieldPairs));

      setProject(projectData);
      setSamples(sampleList);
      setWorkItems(workItemList);
      setPipelineRuns(pipelineRunList);
      setBatches(batchList);
      setAnalyses(analysisList);
      setPipelineTemplates(pipelineTemplateList);
      setPosts(postList);
      setSequences(sequenceList);
      setAlignments(alignmentList);
      setMe(meData);

      setImports(
        importList.filter((job) => String(job.project) === String(id))
      );

      setEvents(
        eventList.filter((event) => {
          const payload = event.payload || {};

          return (
            String(payload.project_id) === String(id) ||
            String(payload.project) === String(id) ||
            payload.project_code === projectData.code ||
            (
              event.entity_type === "Project" &&
              String(event.entity_id) === String(id)
            )
          );
        })
      );

      const initialMembers = (projectData.members || []).map(
        (memberId, idx) => ({
          id: memberId,
          username: projectData.member_usernames?.[idx] || `user-${memberId}`,
        })
      );

      setSelectedMembers(initialMembers);

      if (isAdmin(meData)) {
        const usersData = await apiGet("/api/users/");
        setUsers(usersData.results || usersData || []);
      }
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const userIsAdmin = isAdmin(me);
  const userCanWrite = canWrite(me);
  const readOnlyText = readOnlyMessage(me);
  const assignmentScopeReady =
    assignmentForm.scope_type === "PROJECT" ||
    (assignmentForm.scope_type === "BATCH" && assignmentForm.batch) ||
    (assignmentForm.scope_type === "SAMPLE" && assignmentForm.sample);
  const assignmentDefinitionReady =
    (assignmentForm.assignment_type === "PIPELINE" &&
      assignmentForm.pipeline_template) ||
    (assignmentForm.assignment_type === "ANALYSIS" && assignmentForm.analysis);

  const filteredUsers = useMemo(() => {
    const q = memberQuery.trim().toLowerCase();

    if (!q) return [];

    return users
      .filter((user) => !selectedMembers.some((member) => member.id === user.id))
      .filter(
        (user) =>
          (user.username || "").toLowerCase().includes(q) ||
          (user.email || "").toLowerCase().includes(q)
      )
      .slice(0, 10);
  }, [users, memberQuery, selectedMembers]);

  const sampleStatusCounts = useMemo(() => {
    return countBy(samples, "status");
  }, [samples]);

  const workflowRows = useMemo(() => {
    const workBySample = new Map();
    const runsBySample = new Map();

    workItems.forEach((item) => {
      const key = String(item.sample);
      workBySample.set(key, [...(workBySample.get(key) || []), item]);
    });
    pipelineRuns.forEach((run) => {
      const key = String(run.sample);
      runsBySample.set(key, [...(runsBySample.get(key) || []), run]);
    });

    return samples.map((sample) => {
      const sampleWork = workBySample.get(String(sample.id)) || [];
      const sampleRuns = runsBySample.get(String(sample.id)) || [];
      const openWork = sampleWork.filter((item) =>
        ["PENDING", "IN_PROGRESS"].includes(item.status)
      );
      const resultCount = sampleWork.reduce(
        (total, item) => total + (item.results?.length || 0),
        0
      );
      const pendingQc = sampleWork.filter(
        (item) => item.qc_status === "PENDING_REVIEW"
      ).length;
      const rejectedQc = sampleWork.filter((item) =>
        ["REJECTED", "RERUN_REQUIRED"].includes(item.qc_status)
      ).length;
      const workStatus = sampleWork.some((item) => item.status === "FAILED")
        ? "FAILED"
        : sampleWork.some((item) => item.status === "IN_PROGRESS")
          ? "IN_PROGRESS"
          : sampleWork.some((item) => item.status === "PENDING")
            ? "PENDING"
            : sampleWork.some((item) => item.status === "CANCELLED")
              ? "CANCELLED"
              : sampleWork.length
                ? "COMPLETED"
                : null;
      const activeRun = sampleRuns.find((run) => run.status === "ACTIVE");
      const latestRun = activeRun || sampleRuns[0];
      const directAnalyses = Array.from(
        new Set(
          sampleWork
            .filter((item) => !item.pipeline_run_id && item.analysis_code)
            .map((item) => item.analysis_code)
        )
      );

      return {
        sample,
        workItems: sampleWork,
        openWork,
        resultCount,
        pendingQc,
        rejectedQc,
        workStatus,
        latestRun,
        directAnalyses,
      };
    });
  }, [samples, workItems, pipelineRuns]);

  const workflowTotals = useMemo(() => {
    return {
      openWork: workItems.filter((item) =>
        ["PENDING", "IN_PROGRESS"].includes(item.status)
      ).length,
      results: workItems.reduce(
        (total, item) => total + (item.results?.length || 0),
        0
      ),
      qc: workItems.filter((item) => item.qc_status === "PENDING_REVIEW")
        .length,
      reported: samples.filter((sample) => sample.status === "REPORTED").length,
    };
  }, [samples, workItems]);

  const sampleCustomFieldColumns = useMemo(() => {
    const names = new Set();

    Object.values(sampleCustomFields).forEach((fields) => {
      Object.keys(fields || {}).forEach((name) => names.add(name));
    });

    return Array.from(names).sort();
  }, [sampleCustomFields]);

  const qcStats = useMemo(() => {
    return {
      pending: workItems.filter((item) => item.qc_status === "PENDING_REVIEW")
        .length,
      approved: workItems.filter((item) => item.qc_status === "APPROVED")
        .length,
      rejected: workItems.filter((item) => item.qc_status === "REJECTED")
        .length,
      rerun: workItems.filter((item) => item.qc_status === "RERUN_REQUIRED")
        .length,
    };
  }, [workItems]);

  const openReviewItems = useMemo(() => {
    return workItems.filter((item) =>
      ["PENDING_REVIEW", "REJECTED", "RERUN_REQUIRED"].includes(item.qc_status)
    );
  }, [workItems]);

  const recentImports = useMemo(() => {
    return [...imports]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 5);
  }, [imports]);

  const recentAlignments = useMemo(() => {
    return [...alignments]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 5);
  }, [alignments]);

  const recentEvents = useMemo(() => {
    return [...events]
      .sort((a, b) => new Date(b.timestamp || b.created_at) - new Date(a.timestamp || a.created_at))
      .slice(0, 8);
  }, [events]);

  async function assignWorkflow(e) {
    e.preventDefault();
    if (!userCanWrite) return;

    setErr("");
    setAssignmentResult(null);
    setAssigningWorkflow(true);
    const payload = {
      scope_type: assignmentForm.scope_type,
      assignment_type: assignmentForm.assignment_type,
    };

    if (assignmentForm.scope_type === "PROJECT") {
      payload.project = Number(id);
    } else if (assignmentForm.scope_type === "BATCH") {
      payload.batch = Number(assignmentForm.batch);
    } else {
      payload.sample = Number(assignmentForm.sample);
    }

    if (assignmentForm.assignment_type === "PIPELINE") {
      payload.pipeline_template = Number(assignmentForm.pipeline_template);
    } else {
      payload.analysis = Number(assignmentForm.analysis);
    }

    try {
      const result = await apiPost("/api/pipeline-runs/assign/", payload);
      setAssignmentResult(result);
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setAssigningWorkflow(false);
    }
  }

  async function createPost(e) {
    e.preventDefault();
    setErr("");

    if (!userCanWrite) return;

    try {
      const formData = new FormData();

      formData.append("project", id);
      formData.append("note", note);

      if (image) {
        formData.append("image", image);
      }

      await apiPostForm("/api/project-posts/", formData);

      setNote("");
      setImage(null);

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  function addMember(user) {
    setSelectedMembers((prev) =>
      prev.some((member) => member.id === user.id)
        ? prev
        : [...prev, { id: user.id, username: user.username }]
    );

    setMemberQuery("");
  }

  function removeMember(userId) {
    setSelectedMembers((prev) =>
      prev.filter((member) => member.id !== userId)
    );
  }

  async function saveMembers() {
    setErr("");
    setSavingMembers(true);

    if (!userIsAdmin) {
      setSavingMembers(false);
      return;
    }

    try {
      const updated = await apiPatch(`/api/projects/${id}/`, {
        members: selectedMembers.map((member) => member.id),
      });

      setProject(updated);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSavingMembers(false);
    }
  }

  if (!project) {
    return (
      <div className="w-100">
        {err ? (
          <Alert variant="danger">{err}</Alert>
        ) : (
          <Card className="app-card">
            <Card.Body>Loading project...</Card.Body>
          </Card>
        )}
      </div>
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">{project.name}</h1>
          <p className="page-subtitle">
            {project.code} · Project dashboard, QC review, imports, sequences,
            alignments, and team activity.
          </p>
        </div>

        <div className="inline-actions">
          <Badge bg="dark">{project.sample_count ?? samples.length} samples</Badge>
          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {readOnlyText && <Alert variant="info">{readOnlyText}</Alert>}

      <div className="stat-grid mb-4">
        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Samples</div>
            <div className="metric-value">{samples.length}</div>
            <div className="metric-note">Linked to this project</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">QC Pending</div>
            <div className="metric-value">{qcStats.pending}</div>
            <div className="metric-note">
              Approved: {qcStats.approved} · Re-run: {qcStats.rerun}
            </div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Import Jobs</div>
            <div className="metric-value">{imports.length}</div>
            <div className="metric-note">
              Failed: {imports.filter((job) => job.status === "FAILED").length}
            </div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Sequences</div>
            <div className="metric-value">{sequences.length}</div>
            <div className="metric-note">
              Alignments: {alignments.length}
            </div>
          </Card.Body>
        </Card>
      </div>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-1">Project Workflow</h5>
              <div className="feed-meta">
                Project → samples → work → results → QC → report
              </div>
            </div>
            <div className="inline-actions">
              <Link className="btn btn-sm btn-outline-dark" to="/work-queue">
                Work Queue
              </Link>
              <Link className="btn btn-sm btn-outline-dark" to={`/reports?project=${id}`}>
                Reports
              </Link>
            </div>
          </div>

          <Row className="g-2 mb-4">
            {[
              ["Project", 1, project.code],
              ["Samples", samples.length, "Associated records"],
              ["Open Work", workflowTotals.openWork, `${workItems.length} total`],
              ["Results", workflowTotals.results, "Recorded values"],
              ["QC Pending", workflowTotals.qc, `${qcStats.approved} approved`],
              ["Reported", workflowTotals.reported, `${samples.length} samples`],
            ].map(([label, value, note]) => (
              <Col xs={6} md={4} xl={2} key={label}>
                <div className="soft-card h-100">
                  <div className="metric-label">{label}</div>
                  <div className="metric-value">{value}</div>
                  <div className="metric-note">{note}</div>
                </div>
              </Col>
            ))}
          </Row>

          {userCanWrite && (
            <div className="soft-card mb-4">
              <div className="toolbar-row mb-3">
                <div>
                  <strong>Assign analysis or pipeline</strong>
                  <div className="feed-meta">
                    Apply work to one sample, a project batch, or every primary sample in this project.
                  </div>
                </div>
              </div>

              <Form onSubmit={assignWorkflow}>
                <Row className="g-3 align-items-end">
                  <Col md={2}>
                    <Form.Label>Scope</Form.Label>
                    <Form.Select
                      value={assignmentForm.scope_type}
                      onChange={(e) =>
                        setAssignmentForm({
                          ...assignmentForm,
                          scope_type: e.target.value,
                          sample: "",
                          batch: "",
                        })
                      }
                    >
                      <option value="PROJECT">Entire project</option>
                      <option value="BATCH">Sample batch</option>
                      <option value="SAMPLE">One sample</option>
                    </Form.Select>
                  </Col>

                  <Col md={3}>
                    <Form.Label>Target</Form.Label>
                    {assignmentForm.scope_type === "PROJECT" && (
                      <Form.Control value={`${project.code} — ${project.name}`} disabled />
                    )}
                    {assignmentForm.scope_type === "BATCH" && (
                      <Form.Select
                        required
                        value={assignmentForm.batch}
                        onChange={(e) =>
                          setAssignmentForm({ ...assignmentForm, batch: e.target.value })
                        }
                      >
                        <option value="">Select batch</option>
                        {batches.map((batch) => (
                          <option key={batch.id} value={batch.id}>
                            {batch.code} · {batch.sample_count} samples
                          </option>
                        ))}
                      </Form.Select>
                    )}
                    {assignmentForm.scope_type === "SAMPLE" && (
                      <Form.Select
                        required
                        value={assignmentForm.sample}
                        onChange={(e) =>
                          setAssignmentForm({ ...assignmentForm, sample: e.target.value })
                        }
                      >
                        <option value="">Select sample</option>
                        {samples.map((sample) => (
                          <option key={sample.id} value={sample.id}>
                            {sample.sample_id} · {sample.sample_type}
                          </option>
                        ))}
                      </Form.Select>
                    )}
                  </Col>

                  <Col md={2}>
                    <Form.Label>Assignment</Form.Label>
                    <Form.Select
                      value={assignmentForm.assignment_type}
                      onChange={(e) =>
                        setAssignmentForm({
                          ...assignmentForm,
                          assignment_type: e.target.value,
                          analysis: "",
                          pipeline_template: "",
                        })
                      }
                    >
                      <option value="PIPELINE">Pipeline</option>
                      <option value="ANALYSIS">Analysis</option>
                    </Form.Select>
                  </Col>

                  <Col md={3}>
                    <Form.Label>
                      {assignmentForm.assignment_type === "PIPELINE"
                        ? "Pipeline template"
                        : "Analysis"}
                    </Form.Label>
                    {assignmentForm.assignment_type === "PIPELINE" ? (
                      <Form.Select
                        required
                        value={assignmentForm.pipeline_template}
                        onChange={(e) =>
                          setAssignmentForm({
                            ...assignmentForm,
                            pipeline_template: e.target.value,
                          })
                        }
                      >
                        <option value="">Select pipeline</option>
                        {pipelineTemplates
                          .filter((template) => template.active)
                          .map((template) => (
                            <option key={template.id} value={template.id}>
                              {template.code} — {template.name}
                            </option>
                          ))}
                      </Form.Select>
                    ) : (
                      <Form.Select
                        required
                        value={assignmentForm.analysis}
                        onChange={(e) =>
                          setAssignmentForm({ ...assignmentForm, analysis: e.target.value })
                        }
                      >
                        <option value="">Select analysis</option>
                        {analyses
                          .filter((analysis) => analysis.active)
                          .map((analysis) => (
                            <option key={analysis.id} value={analysis.id}>
                              {analysis.code} — {analysis.name}
                            </option>
                          ))}
                      </Form.Select>
                    )}
                  </Col>

                  <Col md={2}>
                    <Button
                      type="submit"
                      variant="dark"
                      className="w-100"
                      disabled={
                        assigningWorkflow ||
                        !assignmentScopeReady ||
                        !assignmentDefinitionReady
                      }
                    >
                      {assigningWorkflow ? "Assigning..." : "Assign"}
                    </Button>
                  </Col>
                </Row>
              </Form>
            </div>
          )}

          {assignmentResult && (
            <Alert variant={assignmentResult.assigned_count ? "success" : "warning"}>
              Assigned {assignmentResult.assignment.code} to {assignmentResult.assigned_count} sample(s).
              {assignmentResult.skipped_count > 0 && (
                <>
                  {" "}{assignmentResult.skipped_count} sample(s) could not be assigned.
                  <ul className="mb-0 mt-2">
                    {assignmentResult.skipped.slice(0, 5).map((item) => (
                      <li key={item.sample}>
                        {item.sample_code}: {item.reason}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Alert>
          )}

          {workflowRows.length === 0 ? (
            <div className="empty-state">No samples are associated with this project.</div>
          ) : (
            <Table responsive hover className="app-table mb-0">
              <thead>
                <tr>
                  <th>Sample</th>
                  <th>Batch</th>
                  <th>Pipeline / Analysis</th>
                  <th>Work</th>
                  <th>Results</th>
                  <th>QC</th>
                  <th>Report</th>
                </tr>
              </thead>
              <tbody>
                {workflowRows.map((row) => (
                  <tr key={row.sample.id}>
                    <td>
                      <Link to={`/samples/${row.sample.id}`}>{row.sample.sample_id}</Link>
                      <div className="feed-meta">{row.sample.sample_type}</div>
                    </td>
                    <td>{row.sample.batch_code || "—"}</td>
                    <td>
                      {row.latestRun && (
                        <>
                          <strong>{row.latestRun.template_code}</strong>
                          <div className="feed-meta">Pipeline · {row.latestRun.status}</div>
                        </>
                      )}
                      {row.directAnalyses.length > 0 && (
                        <div className={row.latestRun ? "feed-meta mt-1" : ""}>
                          Analysis · {row.directAnalyses.join(", ")}
                        </div>
                      )}
                      {!row.latestRun && row.directAnalyses.length === 0 && "—"}
                    </td>
                    <td>
                      {row.workItems.length ? (
                        <>
                          <Badge
                            bg={workStatusVariant(row.workStatus)}
                          >
                            {row.openWork.length
                              ? `${row.openWork.length} open`
                              : row.workStatus}
                          </Badge>
                          <div className="feed-meta">{row.workItems.length} total</div>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>{row.resultCount}</td>
                    <td>
                      {row.rejectedQc ? (
                        <Badge bg="danger">{row.rejectedQc} attention</Badge>
                      ) : row.pendingQc ? (
                        <Badge bg="warning">{row.pendingQc} pending</Badge>
                      ) : row.workItems.length ? (
                        <Badge bg="success">Approved</Badge>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <Badge bg={sampleStatusVariant(row.sample.status)}>
                        {row.sample.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <Row className="g-4 mb-4">
        <Col lg={8}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Project Overview</h5>

              <div className="soft-card mb-3">
                <div className="feed-meta">Description</div>
                <div>{project.description || "No description"}</div>
              </div>

              <div className="soft-card">
                <div className="feed-meta">Team Members</div>
                <div>
                  {project.member_usernames?.length
                    ? project.member_usernames.join(", ")
                    : "No members assigned"}
                </div>
              </div>
            </Card.Body>
          </Card>
        </Col>

        {userIsAdmin && (
          <Col lg={4}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Manage Team</h5>

                <Form.Control
                  placeholder="Search users by username or email"
                  value={memberQuery}
                  onChange={(e) => setMemberQuery(e.target.value)}
                />

                {memberQuery && (
                  <Card className="app-card mt-3">
                    <Card.Body>
                      {filteredUsers.length === 0 ? (
                        <div className="empty-state">No matching users.</div>
                      ) : (
                        <div className="d-grid gap-2">
                          {filteredUsers.map((user) => (
                            <div
                              key={user.id}
                              className="d-flex justify-content-between align-items-center soft-card"
                            >
                              <div>
                                <div className="fw-semibold">
                                  {user.username}
                                </div>
                                <div className="feed-meta">
                                  {user.email || "-"}
                                </div>
                              </div>

                              <Button
                                size="sm"
                                variant="outline-dark"
                                onClick={() => addMember(user)}
                              >
                                Add
                              </Button>
                            </div>
                          ))}
                        </div>
                      )}
                    </Card.Body>
                  </Card>
                )}

                <div className="mt-3 d-flex flex-wrap gap-2">
                  {selectedMembers.length === 0 ? (
                    <div className="empty-state">
                      No team members selected.
                    </div>
                  ) : (
                    selectedMembers.map((user) => (
                      <span key={user.id} className="click-chip">
                        {user.username}
                        <button
                          type="button"
                          onClick={() => removeMember(user.id)}
                        >
                          ×
                        </button>
                      </span>
                    ))
                  )}
                </div>

                <Button
                  className="mt-3"
                  variant="dark"
                  onClick={saveMembers}
                  disabled={savingMembers}
                >
                  {savingMembers ? "Saving..." : "Save Team"}
                </Button>
              </Card.Body>
            </Card>
          </Col>
        )}
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Samples by Status</h5>
                <Badge bg="dark">{samples.length}</Badge>
              </div>

              {Object.keys(sampleStatusCounts).length === 0 ? (
                <div className="empty-state">No samples yet.</div>
              ) : (
                <div className="d-grid gap-2">
                  {Object.entries(sampleStatusCounts).map(([status, count]) => (
                    <div
                      key={status}
                      className="d-flex justify-content-between align-items-center soft-card"
                    >
                      <Badge bg={sampleStatusVariant(status)}>{status}</Badge>
                      <strong>{count}</strong>
                    </div>
                  ))}
                </div>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">QC Review Queue</h5>
                <Badge bg="dark">{openReviewItems.length}</Badge>
              </div>

              {openReviewItems.length === 0 ? (
                <div className="empty-state">No open QC review items.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Work Item</th>
                      <th>Sample</th>
                      <th>QC</th>
                    </tr>
                  </thead>

                  <tbody>
                    {openReviewItems.slice(0, 8).map((item) => (
                      <tr key={item.id}>
                        <td>{item.name}</td>
                        <td>
                          <Link to={`/samples/${item.sample}`}>
                            Sample #{item.sample}
                          </Link>
                        </td>
                        <td>
                          <Badge bg={qcVariant(item.qc_status)}>
                            {qcLabel(item.qc_status)}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Recent Imports</h5>
                <Badge bg="dark">{imports.length}</Badge>
              </div>

              {recentImports.length === 0 ? (
                <div className="empty-state">No import jobs for this project.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Instrument</th>
                      <th>Status</th>
                      <th>Created</th>
                    </tr>
                  </thead>

                  <tbody>
                    {recentImports.map((job) => (
                      <tr key={job.id}>
                        <td>
                          <Link to={`/imports/${job.id}`}>
                            {job.instrument_code || job.instrument_name || `Import #${job.id}`}
                          </Link>
                        </td>
                        <td>
                          <Badge bg={jobVariant(job.status)}>
                            {job.status}
                          </Badge>
                        </td>
                        <td>{formatTimestamp(job.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Recent Alignments</h5>
                <Badge bg="dark">{alignments.length}</Badge>
              </div>

              {recentAlignments.length === 0 ? (
                <div className="empty-state">No alignments for this project.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Status</th>
                      <th>Created</th>
                    </tr>
                  </thead>

                  <tbody>
                    {recentAlignments.map((job) => (
                      <tr key={job.id}>
                        <td>{job.name}</td>
                        <td>
                          <Badge bg={jobVariant(job.status)}>
                            {job.status}
                          </Badge>
                        </td>
                        <td>{formatTimestamp(job.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <ProjectSequences projectId={project.id} />

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Project Feed</h5>

          {userCanWrite && (
            <Form onSubmit={createPost} className="mb-4">
              <Row className="g-2">
                <Col md={8}>
                  <Form.Control
                    as="textarea"
                    rows={3}
                    placeholder="Post a note to this project"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </Col>

                <Col md={2}>
                  <Form.Control
                    type="file"
                    accept="image/*"
                    onChange={(e) => setImage(e.target.files?.[0] || null)}
                  />
                </Col>

                <Col md={2}>
                  <Button
                    type="submit"
                    variant="dark"
                    className="w-100"
                    disabled={!note && !image}
                  >
                    Post
                  </Button>
                </Col>
              </Row>
            </Form>
          )}

          {posts.length === 0 ? (
            <div className="empty-state">No posts yet.</div>
          ) : (
            <div className="d-grid gap-3">
              {posts.map((post) => (
                <div key={post.id} className="feed-item">
                  <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap mb-2">
                    <div className="fw-semibold">
                      {post.author_username || "Unknown user"}
                    </div>

                    <div className="feed-meta">
                      {formatTimestamp(post.created_at)}
                    </div>
                  </div>

                  {post.note && <div className="mb-2">{post.note}</div>}

                  {post.image && (
                    <img
                      src={post.image}
                      alt="Project post"
                      className="thumbnail"
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">Recent Project Activity</h5>
            <Badge bg="dark">{recentEvents.length}</Badge>
          </div>

          {recentEvents.length === 0 ? (
            <div className="empty-state">No project activity found.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Entity</th>
                  <th>Action</th>
                </tr>
              </thead>

              <tbody>
                {recentEvents.map((event) => (
                  <tr key={event.id}>
                    <td>{formatTimestamp(event.timestamp || event.created_at)}</td>
                    <td>{event.actor_username || event.actor || "-"}</td>
                    <td>{event.entity_type}</td>
                    <td>
                      <Badge bg="secondary">{event.action}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">Project Samples</h5>
            <div className="feed-meta">{samples.length} linked samples</div>
          </div>

          {samples.length === 0 ? (
            <div className="empty-state">No samples in this project yet.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Sample ID</th>
                  <th>Status</th>
                  {sampleCustomFieldColumns.map((fieldName) => (
                    <th key={fieldName}>{fieldName}</th>
                  ))}
                  <th>Container</th>
                  <th>Created</th>
                </tr>
              </thead>

              <tbody>
                {samples.map((sample) => (
                  <tr key={sample.id}>
                    <td>{sample.id}</td>

                    <td>
                      <Link to={`/samples/${sample.id}`}>
                        {sample.sample_id}
                      </Link>
                    </td>

                    <td>
                      <Badge bg={sampleStatusVariant(sample.status)}>
                        {sample.status}
                      </Badge>
                    </td>

                    {sampleCustomFieldColumns.map((fieldName) => (
                      <td key={fieldName}>
                        {formatCustomFieldValue(
                          sampleCustomFields[sample.id]?.[fieldName]
                        )}
                      </td>
                    ))}

                    <td>{sample.container_code || "-"}</td>
                    <td>{formatTimestamp(sample.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}
